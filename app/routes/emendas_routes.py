# app/routes/emendas_routes.py
from datetime import datetime
import json as _json

from flask import Blueprint, request, jsonify, abort
import psycopg2.errors
from psycopg2.extras import Json

from ..database import get_db
from ..auth import login_obrigatorio, usuario_atual
from ..log import registrar_log
from ..config import NSC, SITUACOES
from ..utils import serializar_emenda, fmt_brl, valida_data_iso, valida_situacao

bp = Blueprint('emendas', __name__, url_prefix='/api')


# Campos de texto editáveis — usados no merge parcial do PUT e no diff do log
TEXT_FIELDS = [
    'numero_emenda', 'municipio', 'objeto', 'secretaria', 'lider',
    'oficio', 'referencia', 'entidade', 'cnpj', 'regiao',
    'numero_e', 'justificativa', 'observacoes', 'pago_em', 'data_entrada',
    'resp_nome', 'resp_contato', 'resp_email',
    'pf_nome', 'pf_contato', 'pf_email',
]

LABELS = {
    'numero_emenda': 'Nº emenda', 'ano': 'Ano', 'municipio': 'Município',
    'objeto': 'Objeto', 'valor_empenhado': 'Valor da emenda',
    'valor_pago': 'Valor pago', 'situacao': 'Situação',
    'secretaria': 'Secretaria', 'lider': 'Líder', 'oficio': 'Ofício',
    'referencia': 'Referência', 'entidade': 'Entidade', 'cnpj': 'CNPJ',
    'regiao': 'Região', 'numero_e': 'Nº E', 'justificativa': 'Justificativa',
    'observacoes': 'Observações', 'pago_em': 'Pago em',
    'data_entrada': 'Data de entrada',
    'resp_nome': 'Responsável (nome)', 'resp_contato': 'Responsável (contato)',
    'resp_email': 'Responsável (e-mail)',
    'pf_nome': 'Ponto focal (nome)', 'pf_contato': 'Ponto focal (contato)',
    'pf_email': 'Ponto focal (e-mail)',
}


def _valida_payload(d, parcial=False):
    """Valida campos presentes (parcial=True) ou o payload completo.
    Retorna mensagem de erro ou None."""
    # ano
    if 'ano' in d and d['ano'] not in (None, ''):
        try:
            ano = int(d['ano'])
        except (TypeError, ValueError):
            return 'Ano inválido'
        if not (2000 <= ano <= 2100):
            return 'Ano deve estar entre 2000 e 2100'
    elif not parcial:
        return 'Campo obrigatório ausente: ano'

    # obrigatórios (só no POST)
    if not parcial:
        for campo in ('numero_emenda', 'municipio'):
            if not str(d.get(campo, '')).strip():
                return f'Campo obrigatório ausente: {campo}'

    # valores
    for campo in ('valor_empenhado', 'valor_pago'):
        if campo in d and d[campo] not in (None, ''):
            try:
                v = float(d[campo])
            except (TypeError, ValueError):
                return f'{LABELS[campo]} inválido'
            if v < 0:
                return f'{LABELS[campo]} não pode ser negativo'

    # datas
    for campo in ('data_entrada', 'pago_em'):
        if campo in d and d[campo] not in (None, '') and not valida_data_iso(d[campo]):
            return f'{LABELS[campo]} deve estar no formato AAAA-MM-DD'

    # situação
    if 'situacao' in d and d['situacao'] not in (None, '') and not valida_situacao(d['situacao']):
        return f'Situação inválida (use: {", ".join(SITUACOES)})'

    return None


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
    erro = _valida_payload(d, parcial=False)
    if erro:
        return jsonify({'erro': erro}), 400

    valor_empenhado = float(d.get('valor_empenhado') or 0)
    valor_pago = float(d.get('valor_pago') or 0)
    situacao = d.get('situacao', 'Aguardando')
    pago_em = (d.get('pago_em') or '').strip()

    # Nova emenda já em "Pago" com valor pago zerado: espelha o valor da emenda
    if situacao == 'Pago' and valor_pago == 0:
        valor_pago = valor_empenhado
        if not pago_em:
            pago_em = datetime.now().date().isoformat()

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
                valor_empenhado, valor_pago, situacao,
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
                pago_em,
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
    """Aceita payload parcial (ex.: só {situacao, versao} do inline edit).
    Campos ausentes do JSON mantêm o valor atual do banco."""
    d = request.get_json(silent=True) or {}

    db = get_db()
    with db.cursor() as cur:
        cur.execute('SELECT * FROM emendas WHERE id = %s', (eid,))
        row = cur.fetchone()
    if not row:
        return jsonify({'erro': 'Emenda não encontrada'}), 404

    versao_atual = row['versao'] if row['versao'] is not None else 1
    if 'versao' in d and int(d['versao']) != versao_atual:
        return jsonify({'erro': 'conflito', 'versao_atual': versao_atual}), 409

    erro = _valida_payload(d, parcial=True)
    if erro:
        return jsonify({'erro': erro}), 400

    # --- merge parcial ---
    def _txt_field(k):
        if k in d:
            v = d[k]
            return '' if v is None else str(v).strip()
        return '' if row.get(k) is None else str(row.get(k)).strip()

    def _num_field(k):
        if k in d and d[k] not in (None, ''):
            return float(d[k])
        return float(row.get(k) or 0)

    if 'ano' in d and d['ano'] not in (None, ''):
        ano = int(d['ano'])
    else:
        ano = int(row['ano'])

    valor_empenhado = _num_field('valor_empenhado')
    valor_pago = _num_field('valor_pago')

    situacao_antiga = row.get('situacao') or 'Aguardando'
    situacao = (str(d['situacao']).strip() if 'situacao' in d and d['situacao']
                else situacao_antiga)

    pago_em = _txt_field('pago_em')

    # --- regra de transição para Pago ---
    auto_pago = False
    auto_pago_em = False
    if situacao == 'Pago' and situacao_antiga != 'Pago' and valor_pago == 0:
        valor_pago = valor_empenhado
        auto_pago = True
        if not pago_em:
            pago_em = datetime.now().date().isoformat()
            auto_pago_em = True

    merged = {}
    for k in TEXT_FIELDS:
        if k == 'pago_em':
            merged[k] = pago_em
        else:
            merged[k] = _txt_field(k)
    merged['ano'] = ano
    merged['valor_empenhado'] = valor_empenhado
    merged['valor_pago'] = valor_pago
    merged['situacao'] = situacao

    # --- diff para o log ---
    mudancas = []
    for k in TEXT_FIELDS:
        antigo = '' if row.get(k) is None else str(row.get(k)).strip()
        novo = merged[k]
        if antigo != novo:
            mudancas.append({
                'campo': LABELS.get(k, k),
                'de': antigo or None,
                'para': novo or None,
            })
    if int(row['ano']) != ano:
        mudancas.append({'campo': LABELS['ano'], 'de': row['ano'], 'para': ano})
    for k, label, fmt in (
        ('valor_empenhado', LABELS['valor_empenhado'], True),
        ('valor_pago', LABELS['valor_pago'], True),
    ):
        antigo = round(float(row.get(k) or 0), 2)
        novo = round(merged[k], 2)
        if antigo != novo:
            mudancas.append({
                'campo': label,
                'de': fmt_brl(antigo) if fmt else antigo,
                'para': fmt_brl(novo) if fmt else novo,
            })
    if situacao_antiga != situacao:
        mudancas.append({
            'campo': LABELS['situacao'],
            'de': situacao_antiga,
            'para': situacao,
        })

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
                merged['numero_emenda'], ano, merged['municipio'], merged['objeto'],
                merged['valor_empenhado'], merged['valor_pago'], situacao,
                merged['observacoes'],
                merged['secretaria'], merged['lider'], merged['oficio'],
                merged['referencia'], merged['entidade'], merged['cnpj'],
                merged['regiao'], merged['numero_e'], merged['justificativa'],
                merged['pago_em'], merged['data_entrada'],
                merged['resp_nome'], merged['resp_contato'], merged['resp_email'],
                merged['pf_nome'], merged['pf_contato'], merged['pf_email'],
                datetime.now().isoformat(timespec='seconds'),
                eid,
            ))
        db.commit()
        registrar_log('editou', emenda_id=eid, numero=merged['numero_emenda'],
                      municipio=merged['municipio'], ano=ano,
                      mudancas=mudancas or None)
        resp = {'ok': True}
        if auto_pago:
            resp['valor_pago'] = merged['valor_pago']
            resp['auto_pago'] = True
        if auto_pago_em:
            resp['pago_em'] = merged['pago_em']
            resp['auto_pago_em'] = True
        return jsonify(resp)
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
