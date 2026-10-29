from datetime import datetime

from flask import Blueprint, request, jsonify, abort
import psycopg2.errors

from ..database import get_db
from ..auth import login_obrigatorio
from ..log import registrar_log
from ..config import STATUS_DEMANDAS


def _up(v):
    """Sobe texto pra maiúsculo (None e vazio viram string vazia)."""
    return (v or '').strip().upper()


bp = Blueprint('demandas', __name__, url_prefix='/api')


def _serializar(row):
    d = dict(row)
    d['valor'] = float(d.get('valor') or 0)
    return d


@bp.route('/demandas', methods=['GET'])
@login_obrigatorio
def listar():
    q = request.args.get('q', '').strip()
    status = request.args.get('status', '').strip()
    ano = request.args.get('ano', '').strip()
    municipio = request.args.get('municipio', '').strip()
    secretaria = request.args.get('secretaria', '').strip()

    sql = 'SELECT * FROM demandas WHERE 1=1'
    params = []
    if q:
        like = f'%{q}%'
        sql += ' AND (municipio ILIKE %s OR destinatario ILIKE %s OR objeto ILIKE %s OR proposta_fpe ILIKE %s OR convenio ILIKE %s OR proa_sei ILIKE %s)'
        params += [like, like, like, like, like, like]
    if status:
        sql += ' AND status = %s'; params.append(status)
    if ano:
        sql += ' AND ano = %s'; params.append(ano)
    if municipio:
        sql += ' AND municipio = %s'; params.append(municipio)
    if secretaria:
        sql += ' AND secretaria = %s'; params.append(secretaria)
    sql += ' ORDER BY ano DESC, id DESC'

    db = get_db()
    with db.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    return jsonify([_serializar(r) for r in rows])


@bp.route('/demandas/<int:did>', methods=['GET'])
@login_obrigatorio
def obter(did):
    db = get_db()
    with db.cursor() as cur:
        cur.execute('SELECT * FROM demandas WHERE id = %s', (did,))
        row = cur.fetchone()
    if not row:
        abort(404)
    return jsonify(_serializar(row))


@bp.route('/demandas', methods=['POST'])
@login_obrigatorio
def criar():
    d = request.get_json(silent=True) or {}
    if not str(d.get('ano', '')).strip():
        return jsonify({'erro': 'Campo obrigatório ausente: ano'}), 400

    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute('''
                INSERT INTO demandas
                  (ano, secretaria, municipio, destinatario, objeto, valor,
                   proposta_fpe, status, observacoes, convenio, proa_sei,
                   data_pagto, atualizado_por, atualizado_em, criado_em)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'gabinete',%s,%s)
                RETURNING id
            ''', (
                int(d['ano']),
                _up(d.get('secretaria')),
                _up(d.get('municipio')),
                _up(d.get('destinatario')),
                _up(d.get('objeto')),
                float(d.get('valor') or 0),
                _up(d.get('proposta_fpe')),
                d.get('status') or 'Aguardando',
                (d.get('observacoes') or '').strip(),
                _up(d.get('convenio')),
                _up(d.get('proa_sei')),
                (d.get('data_pagto') or '').strip(),
                datetime.now().isoformat(timespec='seconds'),
                datetime.now().isoformat(timespec='seconds'),
            ))
            new_id = cur.fetchone()['id']
        db.commit()
        registrar_log('criou', demanda_id=new_id,
                      municipio=_up(d.get('municipio')),
                      ano=int(d['ano']),
                      detalhe=f"Demanda {d['ano']}"
                              + (f" · {_up(d.get('secretaria'))}" if d.get('secretaria') else '')
                              + (f" · {_up(d.get('municipio'))}" if d.get('municipio') else ''))
        return jsonify({'id': new_id, 'mensagem': 'Demanda criada'}), 201
    except Exception as e:
        db.rollback()
        return jsonify({'erro': str(e), 'tipo': type(e).__name__}), 500


@bp.route('/demandas/<int:did>', methods=['PUT'])
@login_obrigatorio
def atualizar(did):
    d = request.get_json(silent=True) or {}
    db = get_db()
    with db.cursor() as cur:
        cur.execute('SELECT * FROM demandas WHERE id = %s', (did,))
        row = cur.fetchone()
    if not row:
        return jsonify({'erro': 'Demanda não encontrada'}), 404

    versao_atual = row['versao'] if row['versao'] is not None else 1
    if 'versao' in d and int(d['versao']) != versao_atual:
        return jsonify({'erro': 'conflito', 'versao_atual': versao_atual}), 409

    try:
        with db.cursor() as cur:
            cur.execute('''
                UPDATE demandas SET
                  ano=%s, secretaria=%s, municipio=%s, destinatario=%s,
                  objeto=%s, valor=%s, proposta_fpe=%s, status=%s,
                  observacoes=%s, convenio=%s, proa_sei=%s, data_pagto=%s,
                  versao=versao+1, atualizado_por='gabinete', atualizado_em=%s
                WHERE id=%s
            ''', (
                int(d.get('ano') or row['ano']),
                _up(d.get('secretaria')),
                _up(d.get('municipio')),
                _up(d.get('destinatario')),
                _up(d.get('objeto')),
                float(d.get('valor') or 0),
                _up(d.get('proposta_fpe')),
                d.get('status') or 'Aguardando',
                (d.get('observacoes') or '').strip(),
                _up(d.get('convenio')),
                _up(d.get('proa_sei')),
                (d.get('data_pagto') or '').strip(),
                datetime.now().isoformat(timespec='seconds'),
                did,
            ))
        db.commit()
        registrar_log('editou', demanda_id=did,
                      municipio=row.get('municipio'),
                      ano=row.get('ano'),
                      detalhe=f"Demanda {row.get('ano')} · {row.get('municipio') or '—'}")
        return jsonify({'ok': True})
    except Exception as e:
        db.rollback()
        return jsonify({'erro': str(e), 'tipo': type(e).__name__}), 500


@bp.route('/demandas/<int:did>', methods=['DELETE'])
@login_obrigatorio
def excluir(did):
    db = get_db()
    with db.cursor() as cur:
        cur.execute('SELECT * FROM demandas WHERE id = %s', (did,))
        row = cur.fetchone()
        if not row:
            return jsonify({'erro': 'Não encontrada'}), 404
        cur.execute('DELETE FROM demandas WHERE id = %s', (did,))
    db.commit()
    registrar_log('excluiu', demanda_id=did,
                  municipio=row.get('municipio'),
                  ano=row.get('ano'),
                  detalhe=f"Demanda {row.get('ano')} · {row.get('municipio') or '—'}")
    return jsonify({'ok': True})


@bp.route('/filtros-demandas', methods=['GET'])
@login_obrigatorio
def filtros():
    db = get_db()
    with db.cursor() as cur:
        def uniq(sql):
            cur.execute(sql)
            return [r[list(r.keys())[0]] for r in cur.fetchall() if r[list(r.keys())[0]]]
        return jsonify({
            'anos': uniq('SELECT DISTINCT ano FROM demandas ORDER BY ano DESC'),
            'secretarias': uniq('SELECT DISTINCT secretaria FROM demandas ORDER BY secretaria'),
            'municipios': uniq('SELECT DISTINCT municipio FROM demandas ORDER BY municipio'),
            'status': STATUS_DEMANDAS,
        })
