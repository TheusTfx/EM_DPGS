from datetime import datetime
import json as _json

from flask import Blueprint, request, jsonify, abort
import psycopg2.errors
from psycopg2.extras import Json

from ..database import get_db
from ..auth import login_obrigatorio, usuario_atual
from ..log import registrar_log
from ..config import NSC, SITUACOES
from ..utils import serializar_emenda

bp = Blueprint('emendas', __name__, url_prefix='/api')


@bp.route('/emendas', methods=['GET'])
@login_obrigatorio
def listar():
    q = request.args.get('q', '').strip()
    municipio = request.args.get('municipio', '').strip()
    situacao = request.args.get('situacao', '').strip()
    ano = request.args.get('ano', '').strip()
    parada = request.args.get('parada_dias', '').strip()
    incompletos = request.args.get('incompletos', '').strip()

    sql = 'SELECT * FROM emendas WHERE 1=1'
    params = []
    if q:
        like = f'%{q}%'
        sql += (' AND (numero_emenda ILIKE %s OR objeto ILIKE %s OR municipio ILIKE %s'
                ' OR entidade ILIKE %s OR lider ILIKE %s OR cnpj ILIKE %s)')
        params += [like, like, like, like, like, like]
    if municipio:
        sql += ' AND municipio = %s'; params.append(municipio)
    if situacao:
        sql += ' AND situacao = %s'; params.append(situacao)
    if ano:
        sql += ' AND ano = %s'; params.append(ano)
    if parada:
        sql += (" AND atualizado_em IS NOT NULL AND atualizado_em <> '' "
                "AND (CURRENT_DATE - atualizado_em::date) >= %s")
        params.append(int(parada))
    if incompletos:
        sql += f""" AND (COALESCE(entidade,'') = '' OR COALESCE(entidade,'') = '{NSC}'
                     OR COALESCE(objeto,'') = '' OR COALESCE(objeto,'') = '{NSC}'
                     OR COALESCE(lider,'') = '' OR COALESCE(lider,'') = '{NSC}'
                     OR COALESCE(secretaria,'') = '' OR COALESCE(secretaria,'') = '{NSC}')"""
    sql += ' ORDER BY ano DESC, id DESC'

    db = get_db()
    with db.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()

    return jsonify([serializar_emenda(r) for r in rows])


@bp.route('/emendas/<int:eid>', methods=['GET'])
@login_obrigatorio
def obter(eid):
    db = get_db()
    with db.cursor() as cur:
        cur.execute('SELECT * FROM emendas WHERE id = %s', (eid,))
        row = cur.fetchone()
    if not row:
        abort(404)
    return jsonify(serializar_emenda(row))


@bp.route('/emendas', methods=['POST'])
@login_obrigatorio
def criar():
    d = request.get_json(silent=True) or {}
    for campo in ['numero_emenda', 'ano', 'municipio']:
        if not str(d.get(campo, '')).strip():
            return jsonify({'erro': f'Campo obrigatório ausente: {campo}'}), 400

    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute('''
                INSERT INTO emendas
                  (numero_emenda, ano, municipio, objeto, valor_empenhado, valor_pago,
                   situacao, observacoes, secretaria, lider, oficio, referencia,
                   entidade, cnpj, regiao, numero_e, justificativa, pago_em,
                   data_entrada, resp_nome, resp_contato, resp_email,
                   pf_nome, pf_contato, pf_email,
                   atualizado_por, atualizado_em)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                        %s,%s,%s,%s,%s,%s,'gabinete',%s)
                RETURNING id
            ''', (
                d['numero_emenda'].strip(), int(d['ano']), d['municipio'].strip(),
                (d.get('objeto') or '').strip(),
                float(d.get('valor_empenhado') or 0),
                float(d.get('valor_pago') or 0),
                d.get('situacao', 'Aguardando'),
                (d.get('observacoes') or '').strip(),
                (d.get('secretaria') or '').strip(),
                (d.get('lider') or '').strip(),
                (d.get('oficio') or '').strip(),
                (d.get('referencia') or '').strip(),
                (d.get('entidade') or '').strip(),
                (d.get('cnpj') or '').strip(),
                (d.get('regiao') or '').strip(),
                (d.get('numero_e') or '').strip(),
                (d.get('justificativa') or '').strip(),
                (d.get('pago_em') or '').strip(),
                (d.get('data_entrada') or '').strip(),
                (d.get('resp_nome') or '').strip(),
                (d.get('resp_contato') or '').strip(),
                (d.get('resp_email') or '').strip(),
                (d.get('pf_nome') or '').strip(),
                (d.get('pf_contato') or '').strip(),
                (d.get('pf_email') or '').strip(),
                datetime.now().isoformat(timespec='seconds'),
            ))
            new_id = cur.fetchone()['id']
        db.commit()
        registrar_log('criou', emenda_id=new_id, numero=d['numero_emenda'],
                      municipio=d['municipio'], ano=int(d['ano']))
        return jsonify({'id': new_id, 'mensagem': 'Emenda criada'}), 201
    except psycopg2.errors.UniqueViolation:
        db.rollback()
        return jsonify({'erro': 'Já existe emenda com este nº para este ano'}), 400
    except Exception as e:
        db.rollback()
        return jsonify({'erro': str(e), 'tipo': type(e).__name__}), 500


@bp.route('/emendas/<int:eid>', methods=['PUT'])
@login_obrigatorio
def atualizar(eid):
    d = request.get_json(silent=True) or {}
    db = get_db()
    with db.cursor() as cur:
        cur.execute('SELECT * FROM emendas WHERE id = %s', (eid,))
        row = cur.fetchone()
    if not row:
        return jsonify({'erro': 'Emenda nao encontrada'}), 404

    versao_atual = row['versao'] if row['versao'] is not None else 1
    if 'versao' in d and int(d['versao']) != versao_atual:
        return jsonify({'erro': 'conflito', 'versao_atual': versao_atual}), 409

    try:
        with db.cursor() as cur:
            cur.execute('''
                UPDATE emendas SET
                  numero_emenda=%s, ano=%s, municipio=%s, objeto=%s,
                  valor_empenhado=%s, valor_pago=%s, situacao=%s, observacoes=%s,
                  secretaria=%s, lider=%s, oficio=%s, referencia=%s,
                  entidade=%s, cnpj=%s, regiao=%s, numero_e=%s, justificativa=%s,
                  pago_em=%s, data_entrada=%s,
                  resp_nome=%s, resp_contato=%s, resp_email=%s,
                  pf_nome=%s, pf_contato=%s, pf_email=%s,
                  versao=versao+1, atualizado_por='gabinete', atualizado_em=%s
                WHERE id=%s
            ''', (
                d.get('numero_emenda', row['numero_emenda']),
                int(d.get('ano') or row['ano']),
                d.get('municipio', row['municipio']),
                (d.get('objeto') or '').strip(),
                float(d.get('valor_empenhado') or 0),
                float(d.get('valor_pago') or 0),
                d.get('situacao', 'Aguardando'),
                (d.get('observacoes') or '').strip(),
                (d.get('secretaria') or '').strip(),
                (d.get('lider') or '').strip(),
                (d.get('oficio') or '').strip(),
                (d.get('referencia') or '').strip(),
                (d.get('entidade') or '').strip(),
                (d.get('cnpj') or '').strip(),
                (d.get('regiao') or '').strip(),
                (d.get('numero_e') or '').strip(),
                (d.get('justificativa') or '').strip(),
                (d.get('pago_em') or '').strip(),
                (d.get('data_entrada') or '').strip(),
                (d.get('resp_nome') or '').strip(),
                (d.get('resp_contato') or '').strip(),
                (d.get('resp_email') or '').strip(),
                (d.get('pf_nome') or '').strip(),
                (d.get('pf_contato') or '').strip(),
                (d.get('pf_email') or '').strip(),
                datetime.now().isoformat(timespec='seconds'),
                eid,
            ))
        db.commit()
        registrar_log('editou', emenda_id=eid, numero=row['numero_emenda'],
                      municipio=row['municipio'], ano=row['ano'])
        return jsonify({'ok': True})
    except psycopg2.errors.UniqueViolation:
        db.rollback()
        return jsonify({'erro': 'Já existe outra emenda com este nº para este ano'}), 400
    except Exception as e:
        db.rollback()
        return jsonify({'erro': str(e), 'tipo': type(e).__name__}), 500


@bp.route('/emendas/<int:eid>', methods=['DELETE'])
@login_obrigatorio
def excluir(eid):
    u = usuario_atual()
    db = get_db()
    with db.cursor() as cur:
        cur.execute('SELECT * FROM emendas WHERE id = %s', (eid,))
        row = cur.fetchone()
        if not row:
            return jsonify({'erro': 'Não encontrada'}), 404
        dados = dict(row)
        for k in ('valor_empenhado', 'valor_pago'):
            dados[k] = float(dados.get(k) or 0)
        cur.execute('''INSERT INTO lixeira (excluida_em, excluida_por, dados)
                       VALUES (%s,%s,%s)''',
                    (datetime.now().isoformat(timespec='seconds'),
                     (u or {}).get('nome', 'sistema'),
                     Json(dados, dumps=lambda o: _json.dumps(
                         o, default=str, ensure_ascii=False))))
        cur.execute('DELETE FROM emendas WHERE id = %s', (eid,))
    db.commit()
    registrar_log('excluiu', emenda_id=eid, numero=row['numero_emenda'],
                  municipio=row['municipio'], ano=row['ano'])
    return jsonify({'ok': True})


@bp.route('/filtros', methods=['GET'])
@login_obrigatorio
def filtros():
    db = get_db()
    with db.cursor() as cur:
        def uniq(sql):
            cur.execute(sql)
            return [r[list(r.keys())[0]] for r in cur.fetchall() if r[list(r.keys())[0]]]
        return jsonify({
            'municipios':  uniq('SELECT DISTINCT municipio FROM emendas ORDER BY municipio'),
            'anos':        uniq('SELECT DISTINCT ano FROM emendas ORDER BY ano DESC'),
            'secretarias': uniq('SELECT DISTINCT secretaria FROM emendas ORDER BY secretaria'),
            'lideres':     uniq('SELECT DISTINCT lider FROM emendas ORDER BY lider'),
            'regioes':     uniq('SELECT DISTINCT regiao FROM emendas ORDER BY regiao'),
            'situacoes':   SITUACOES,
        })
