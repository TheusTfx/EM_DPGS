import traceback

from flask import Blueprint, request, jsonify
from psycopg2.extras import execute_values

from ..database import get_db
from ..auth import login_obrigatorio
from ..log import registrar_log
from ..importacao import (
    ABAS_CONFIGURADAS, COLUNAS_INSERT, AbaAusente,
    _processar_dataframe, _montar_upsert, comparar_com_banco,
)

bp = Blueprint('importacao', __name__, url_prefix='/api')

ABAS_EMENDAS = ['2026', '2025', '2024']


def _abas_solicitadas():
    valor = (request.form.get('aba') or '2026').strip().lower()
    if valor == 'todas':
        return list(ABAS_EMENDAS), True
    if valor in ABAS_CONFIGURADAS:
        return [valor], False
    if valor == 'contatos':
        raise ValueError('A importação de contatos (aba ENTIDADES) não está disponível nesta versão.')
    raise ValueError(f'Aba {valor} ainda não configurada')


def _ler_arquivo():
    arquivo = request.files.get('arquivo')
    if not arquivo or not arquivo.filename:
        raise ValueError('Nenhum arquivo enviado')
    if arquivo.filename.lower().endswith('.xls'):
        raise ValueError('Formato .xls antigo não é suportado. Abra no Excel e salve como .xlsx.')
    return arquivo.read()


def _processar_abas(abas, conteudo, todas):
    resultados = {}
    for aba in abas:
        try:
            resultados[aba] = _processar_dataframe(aba, conteudo)
        except AbaAusente:
            if not todas:
                raise
            resultados[aba] = None
    if all(v is None for v in resultados.values()):
        raise ValueError('Nenhuma das abas 2024, 2025 ou 2026 foi encontrada na planilha')
    return resultados


def _bloco(registros, ignoradas, resumo, comp):
    return {
        'tipo': 'emendas',
        'total_linhas': len(registros),
        'novas': comp['novas'],
        'alteradas': comp['alteradas'],
        'iguais': comp['iguais'],
        'ignoradas': len(ignoradas),
        'lista_ignoradas': ignoradas[:50],
        'duplicadas': resumo['duplicadas'],
        'avisos': resumo['avisos'][:40],
        'n_avisos': len(resumo['avisos']),
        'pagas': resumo['pagas'],
        'aguardando': resumo['aguardando'],
        'sem_numero': resumo['sem_numero'],
        'nao_consta': {k: v for k, v in resumo['nao_consta'].items() if v},
        'exemplos_novas': comp['exemplos_novas'],
        'lista_alteradas': comp['lista_alteradas'],
    }


@bp.route('/importar/preview', methods=['POST'])
@login_obrigatorio
def preview():
    try:
        abas, todas = _abas_solicitadas()
        conteudo = _ler_arquivo()
        resultados = _processar_abas(abas, conteudo, todas)

        db = get_db()
        saida = {}
        try:
            with db.cursor() as cur:
                for aba, res in resultados.items():
                    if res is None:
                        saida[aba] = {'tipo': 'ausente'}
                        continue
                    registros, ignoradas, resumo = res
                    comp, _ = comparar_com_banco(cur, aba, registros)
                    saida[aba] = _bloco(registros, ignoradas, resumo, comp)
        finally:
            db.rollback()
        return jsonify({'abas': saida})
    except ValueError as e:
        return jsonify({'erro': str(e)}), 400
    except Exception as e:
        traceback.print_exc()
        return jsonify({'erro': str(e), 'tipo': type(e).__name__}), 500


@bp.route('/importar', methods=['POST'])
@login_obrigatorio
def importar():
    try:
        abas, todas = _abas_solicitadas()
        conteudo = _ler_arquivo()
        resultados = _processar_abas(abas, conteudo, todas)

        if all(v is None or not v[0] for v in resultados.values()):
            return jsonify({'erro': 'Nenhuma linha válida para importar'}), 400

        por_aba = {}
        tot_criadas = tot_atualizadas = tot_iguais = tot_ignoradas = 0

        db = get_db()
        try:
            with db.cursor() as cur:
                for aba, res in resultados.items():
                    if res is None:
                        continue
                    registros, ignoradas, resumo = res
                    comp, a_gravar = comparar_com_banco(cur, aba, registros)

                    criadas = atualizadas = 0
                    if a_gravar:
                        query = _montar_upsert(ABAS_CONFIGURADAS[aba]['tem_situacao'],
                                               returning=True)
                        tuplas = [tuple(r[c] for c in COLUNAS_INSERT) for r in a_gravar]
                        retorno = execute_values(cur, query, tuplas,
                                                 page_size=500, fetch=True)
                        for linha in retorno:
                            ins = linha['inserido'] if isinstance(linha, dict) else linha[0]
                            if ins:
                                criadas += 1
                            else:
                                atualizadas += 1

                    por_aba[aba] = {'criadas': criadas, 'atualizadas': atualizadas,
                                    'iguais': comp['iguais'], 'ignoradas': len(ignoradas),
                                    'sem_numero': resumo['sem_numero']}
                    tot_criadas += criadas
                    tot_atualizadas += atualizadas
                    tot_iguais += comp['iguais']
                    tot_ignoradas += len(ignoradas)
            db.commit()
        except Exception:
            db.rollback()
            raise

        partes = [f"Aba {a}: {v['criadas']} novas, {v['atualizadas']} atualizadas, "
                  f"{v['iguais']} sem alteração, {v['ignoradas']} ignoradas"
                  for a, v in por_aba.items()]
        registrar_log('importou', detalhe=' | '.join(partes))

        return jsonify({
            'ok': True, 'abas': por_aba,
            'criadas': tot_criadas, 'atualizadas': tot_atualizadas,
            'sem_alteracao': tot_iguais, 'ignoradas': tot_ignoradas,
            'importadas': tot_criadas + tot_atualizadas,
        })
    except ValueError as e:
        return jsonify({'erro': str(e)}), 400
    except Exception as e:
        traceback.print_exc()
        return jsonify({'erro': str(e), 'tipo': type(e).__name__}), 500
