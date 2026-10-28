from flask import Blueprint, request, jsonify
from psycopg2.extras import execute_values

from ..database import get_db
from ..auth import login_obrigatorio
from ..log import registrar_log
from ..importacao import (
    ABAS_CONFIGURADAS, COLUNAS_INSERT,
    _processar_dataframe, _montar_upsert,
)

bp = Blueprint('importacao', __name__, url_prefix='/api')


@bp.route('/importar/preview', methods=['POST'])
@login_obrigatorio
def preview():
    aba = request.form.get('aba', '2026')
    if aba not in ABAS_CONFIGURADAS:
        return jsonify({'erro': f'Aba {aba} ainda não configurada'}), 400
    arquivo = request.files.get('arquivo')
    if not arquivo or not arquivo.filename:
        return jsonify({'erro': 'Nenhum arquivo enviado'}), 400
    try:
        registros, ignoradas, resumo = _processar_dataframe(aba, arquivo.read())
        return jsonify({
            'aba': aba,
            'total_linhas': len(registros),
            'ignoradas': ignoradas,
            'pagas': resumo['pagas'],
            'aguardando': resumo['aguardando'],
            'sem_numero': resumo['sem_numero'],
            'nao_consta': {k: v for k, v in resumo['nao_consta'].items() if v},
            'amostra': [{
                'numero_emenda': r['numero_emenda'], 'ano': r['ano'],
                'municipio': r['municipio'], 'valor_empenhado': r['valor_empenhado'],
                'situacao': r['situacao'], 'observacoes': r['observacoes'],
            } for r in registros[:5]],
        })
    except Exception as e:
        return jsonify({'erro': str(e), 'tipo': type(e).__name__}), 500


@bp.route('/importar', methods=['POST'])
@login_obrigatorio
def importar():
    aba = request.form.get('aba', '2026')
    if aba not in ABAS_CONFIGURADAS:
        return jsonify({'erro': f'Aba {aba} ainda não configurada'}), 400
    arquivo = request.files.get('arquivo')
    if not arquivo or not arquivo.filename:
        return jsonify({'erro': 'Nenhum arquivo enviado'}), 400
    try:
        registros, ignoradas, resumo = _processar_dataframe(aba, arquivo.read())
        if not registros:
            return jsonify({'erro': 'Nenhuma linha válida para importar'}), 400

        tuplas = [tuple(r[c] for c in COLUNAS_INSERT) for r in registros]
        query = _montar_upsert(ABAS_CONFIGURADAS[aba]['tem_situacao'])

        db = get_db()
        try:
            with db.cursor() as cur:
                execute_values(cur, query, tuplas, page_size=500)
            db.commit()
        except Exception:
            db.rollback()
            raise

        registrar_log('importou',
                      detalhe=f'Aba {aba}: {len(registros)} linhas importadas, '
                              f'{ignoradas} ignoradas')
        return jsonify({'ok': True, 'aba': aba, 'importadas': len(registros),
                        'ignoradas': ignoradas, 'sem_numero': resumo['sem_numero']})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'erro': str(e), 'tipo': type(e).__name__}), 500
