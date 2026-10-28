from io import BytesIO

import pandas as pd
from flask import Blueprint, request, jsonify

from ..database import get_db
from ..auth import login_obrigatorio, admin_obrigatorio
from ..log import registrar_log
from ..regioes import _REGIOES, MAPA_REGIOES, _sem_acento
from ..config import NSC

bp = Blueprint('regioes', __name__, url_prefix='/api')


@bp.route('/regioes', methods=['GET'])
@login_obrigatorio
def listar():
    return jsonify([{'m': m, 'r': r} for r, muns in _REGIOES.items() for m in muns])


@bp.route('/regioes/importar', methods=['POST'])
@admin_obrigatorio
def importar():
    arq = request.files.get('arquivo')
    if not arq:
        return jsonify({'erro': 'Arquivo não enviado'}), 400
    try:
        nome = (arq.filename or '').lower()
        conteudo = arq.read()
        if nome.endswith('.csv'):
            df = pd.read_csv(BytesIO(conteudo), sep=None, engine='python')
        else:
            df = pd.read_excel(BytesIO(conteudo), engine='openpyxl')
    except Exception as e:
        return jsonify({'erro': f'Falha lendo arquivo: {e}'}), 400

    df.columns = [' '.join(str(c).split()).upper() for c in df.columns]
    col_mun = next((c for c in ('MUNICÍPIO', 'MUNICIPIO') if c in df.columns), None)
    col_reg = next((c for c in ('REGIÃO', 'REGIAO') if c in df.columns), None)
    if not col_mun or not col_reg:
        return jsonify({'erro': 'Colunas MUNICÍPIO e REGIÃO são obrigatórias'}), 400

    novos = {}
    for _, row in df.iterrows():
        m = str(row[col_mun]).strip() if pd.notna(row[col_mun]) else ''
        r = str(row[col_reg]).strip() if pd.notna(row[col_reg]) else ''
        if m and r:
            novos[_sem_acento(m)] = (m.upper(), r.upper())

    for chave, (m, r) in novos.items():
        MAPA_REGIOES[chave] = r
        for reg, muns in _REGIOES.items():
            if m in muns and reg != r:
                muns.remove(m)
                break
        _REGIOES.setdefault(r, [])
        if m not in _REGIOES[r]:
            _REGIOES[r].append(m)

    atualizadas = 0
    db = get_db()
    with db.cursor() as cur:
        cur.execute("SELECT id, municipio, regiao FROM emendas")
        for row in cur.fetchall():
            if not row['regiao'] or row['regiao'] == NSC:
                nova = MAPA_REGIOES.get(_sem_acento(row['municipio']))
                if nova:
                    cur.execute('UPDATE emendas SET regiao = %s WHERE id = %s',
                                (nova, row['id']))
                    atualizadas += 1
    db.commit()
    registrar_log('regiões',
                  detalhe=f'{len(novos)} municípios importados, {atualizadas} emendas atualizadas')
    return jsonify({'municipios': len(novos), 'emendas_atualizadas': atualizadas})
