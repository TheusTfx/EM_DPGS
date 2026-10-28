import hashlib
import os
import re
import secrets
import unicodedata
import json as _json
from datetime import datetime
from io import BytesIO
from functools import wraps

import pandas as pd
import psycopg2
from psycopg2.extras import RealDictCursor, execute_values
from flask import Flask, request, jsonify, render_template, g, abort

app = Flask(__name__)

DATABASE_URL = os.environ.get('DATABASE_URL')

SITUACOES = ['Aguardando', 'Empenhado', 'Pago', 'Cancelada']

# ============================================================
# BANCO
# ============================================================
def get_db():
    if 'db' not in g:
        g.db = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    return g.db

@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop('db', None)
    if db is not None:
        db.close()

def init_db():
    if not DATABASE_URL:
        print("AVISO: DATABASE_URL nao configurada.")
        return
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    try:
        with conn.cursor() as cur:
            cur.execute('''CREATE TABLE IF NOT EXISTS emendas (
                id SERIAL PRIMARY KEY, numero_emenda TEXT NOT NULL, ano INTEGER NOT NULL,
                municipio TEXT NOT NULL, objeto TEXT,
                valor_empenhado NUMERIC(12,2) DEFAULT 0, valor_pago NUMERIC(12,2) DEFAULT 0,
                situacao TEXT DEFAULT 'Aguardando', observacoes TEXT,
                versao INTEGER DEFAULT 1, atualizado_por TEXT, atualizado_em TEXT)''')

            novas_colunas = [
                ('secretaria','TEXT'),('lider','TEXT'),('oficio','TEXT'),
                ('referencia','TEXT'),('entidade','TEXT'),('cnpj','TEXT'),
                ('regiao','TEXT'),('numero_e','TEXT'),('justificativa','TEXT'),
                ('situacao_bruta','TEXT'),('pago_em','TEXT'),('data_entrada','TEXT'),
            ]
            for col, tipo in novas_colunas:
                cur.execute(f"ALTER TABLE emendas ADD COLUMN IF NOT EXISTS {col} {tipo}")

            cur.execute("""SELECT 1 FROM pg_constraint WHERE conname = 'emendas_ano_numero_key'""")
            if not cur.fetchone():
                cur.execute("SAVEPOINT add_unique")
                try:
                    cur.execute("""ALTER TABLE emendas ADD CONSTRAINT emendas_ano_numero_key UNIQUE (ano, numero_emenda)""")
                    cur.execute("RELEASE SAVEPOINT add_unique")
                except Exception:
                    cur.execute("ROLLBACK TO SAVEPOINT add_unique")
                    print("AVISO: duplicatas em (ano, numero_emenda). Constraint nao criada.")

            # --- Tabelas de autenticação e auditoria ---
            cur.execute('''CREATE TABLE IF NOT EXISTS usuarios (
                id SERIAL PRIMARY KEY, nome TEXT NOT NULL, usuario TEXT UNIQUE NOT NULL,
                senha_hash TEXT NOT NULL, admin BOOLEAN DEFAULT false, criado_em TEXT)''')

            # Tabela de sessões (substitui o dict TOKENS em memória)
            cur.execute('''CREATE TABLE IF NOT EXISTS sessoes (
                token TEXT PRIMARY KEY, usuario_id INTEGER REFERENCES usuarios(id) ON DELETE CASCADE,
                criado_em TIMESTAMP DEFAULT NOW(), expira_em TIMESTAMP)''')

            cur.execute('''CREATE TABLE IF NOT EXISTS logs (
                id SERIAL PRIMARY KEY, criado_em TEXT, usuario TEXT, acao TEXT,
                emenda_id INTEGER, numero_emenda TEXT, municipio TEXT, ano INTEGER,
                detalhe TEXT, mudancas JSONB)''')

            cur.execute('''CREATE TABLE IF NOT EXISTS lixeira (
                id SERIAL PRIMARY KEY, excluida_em TEXT, excluida_por TEXT, dados JSONB)''')

            # Cria admin se nao existir
            cur.execute("SELECT 1 FROM usuarios WHERE usuario = 'admin'")
            if not cur.fetchone():
                salt = secrets.token_hex(16)
                h = hashlib.pbkdf2_hmac('sha256', b'admin123', salt.encode(), 100_000).hex()
                cur.execute('''INSERT INTO usuarios (nome, usuario, senha_hash, admin, criado_em)
                               VALUES ('Administrador','admin',%s,true,%s)''',
                            (f'{salt}${h}', datetime.now().isoformat(timespec='seconds')))
                print("Usuario admin criado com senha 'admin123'. TROQUE NO PRIMEIRO ACESSO.")

        conn.commit()
        print("Banco inicializado/migrado com sucesso.")
    finally:
        conn.close()

init_db()

@app.errorhandler(Exception)
def handle_exception(e):
    from werkzeug.exceptions import HTTPException
    if isinstance(e, HTTPException):
        return e
    if request.path.startswith('/api/'):
        return jsonify({'erro': str(e), 'tipo': type(e).__name__}), 500
    return str(e), 500

# ============================================================
# AUTENTICAÇÃO (baseada no banco de dados)
# ============================================================
def _hash_senha(senha, salt=None):
    salt = salt or secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac('sha256', senha.encode(), salt.encode(), 100_000).hex()
    return f'{salt}${h}'

def _verifica_senha(senha, hashed):
    try:
        salt, _ = hashed.split('$', 1)
        return _hash_senha(senha, salt) == hashed
    except Exception:
        return False

def usuario_atual():
    h = request.headers.get('Authorization', '')
    if not h.startswith('Bearer '):
        return None
    token = h[7:]
    db = get_db()
    with db.cursor() as cur:
        cur.execute('''SELECT u.id, u.nome, u.usuario, u.admin
                       FROM sessoes s JOIN usuarios u ON u.id = s.usuario_id
                       WHERE s.token = %s AND (s.expira_em IS NULL OR s.expira_em > NOW())''', (token,))
        row = cur.fetchone()
    return dict(row) if row else None

def login_obrigatorio(f):
    @wraps(f)
    def w(*a, **k):
        if not usuario_atual():
            return jsonify({'erro': 'Não autorizado'}), 401
        return f(*a, **k)
    return w

def admin_obrigatorio(f):
    @wraps(f)
    def w(*a, **k):
        u = usuario_atual()
        if not u: return jsonify({'erro': 'Não autorizado'}), 401
        if not u.get('admin'): return jsonify({'erro': 'Apenas administradores'}), 403
        return f(*a, **k)
    return w

def registrar_log(acao, emenda_id=None, numero=None, municipio=None, ano=None, detalhe=None, mudancas=None):
    u = usuario_atual()
    db = get_db()
    with db.cursor() as cur:
        cur.execute('''INSERT INTO logs (criado_em, usuario, acao, emenda_id, numero_emenda, municipio, ano, detalhe, mudancas)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
                    (datetime.now().isoformat(timespec='seconds'),
                     (u or {}).get('nome', 'sistema'), acao, emenda_id, numero, municipio, ano,
                     detalhe, _json.dumps(mudancas or [], ensure_ascii=False)))
    db.commit()

# ---------------- ROTAS DE AUTH ----------------
@app.route('/api/login', methods=['POST'])
def api_login():
    d = request.get_json(silent=True) or {}
    usuario = (d.get('usuario') or '').strip()
    senha = d.get('senha') or ''
    db = get_db()
    with db.cursor() as cur:
        cur.execute('SELECT * FROM usuarios WHERE usuario = %s', (usuario,))
        row = cur.fetchone()
    if not row or not _verifica_senha(senha, row['senha_hash']):
        return jsonify({'erro': 'Usuário ou senha inválidos'}), 401
    token = secrets.token_hex(24)
    with db.cursor() as cur:
        cur.execute('''INSERT INTO sessoes (token, usuario_id, expira_em)
                       VALUES (%s, %s, NOW() + INTERVAL '7 days')''', (token, row['id']))
    db.commit()
    return jsonify(id=row['id'], nome=row['nome'], usuario=row['usuario'], admin=row['admin'], token=token)

@app.route('/api/senha', methods=['PUT'])
@login_obrigatorio
def api_alterar_senha():
    d = request.get_json(silent=True) or {}
    u = usuario_atual()
    db = get_db()
    with db.cursor() as cur:
        cur.execute('SELECT senha_hash FROM usuarios WHERE id = %s', (u['id'],))
        row = cur.fetchone()
        if not _verifica_senha(d.get('atual') or '', row['senha_hash']):
            return jsonify({'erro': 'Senha atual incorreta'}), 400
        nova = d.get('nova') or ''
        if len(nova) < 6:
            return jsonify({'erro': 'Senha nova deve ter ao menos 6 caracteres'}), 400
        cur.execute('UPDATE usuarios SET senha_hash = %s WHERE id = %s', (_hash_senha(nova), u['id']))
    db.commit()
    return jsonify({'ok': True})

@app.route('/api/usuarios', methods=['GET'])
@admin_obrigatorio
def api_listar_usuarios():
    db = get_db()
    with db.cursor() as cur:
        cur.execute('SELECT id, nome, usuario, admin FROM usuarios ORDER BY nome')
        return jsonify([dict(r) for r in cur.fetchall()])

@app.route('/api/usuarios', methods=['POST'])
@admin_obrigatorio
def api_criar_usuario():
    d = request.get_json(silent=True) or {}
    if not d.get('nome') or not d.get('usuario') or len(d.get('senha') or '') < 6:
        return jsonify({'erro': 'Nome, usuário e senha (mín. 6) são obrigatórios'}), 400
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute('''INSERT INTO usuarios (nome, usuario, senha_hash, admin, criado_em)
                           VALUES (%s,%s,%s,%s,%s) RETURNING id''',
                        (d['nome'].strip(), d['usuario'].strip(), _hash_senha(d['senha']),
                         bool(d.get('admin')), datetime.now().isoformat(timespec='seconds')))
            return jsonify({'id': cur.fetchone()['id']}), 201
        db.commit()
    except psycopg2.errors.UniqueViolation:
        db.rollback()
        return jsonify({'erro': 'Este login já existe'}), 400
    except Exception as e:
        db.rollback()
        return jsonify({'erro': str(e)}), 500

@app.route('/api/usuarios/<int:uid>/senha', methods=['PUT'])
@admin_obrigatorio
def api_redefinir_senha(uid):
    d = request.get_json(silent=True) or {}
    if len(d.get('nova') or '') < 6:
        return jsonify({'erro': 'Senha deve ter ao menos 6 caracteres'}), 400
    db = get_db()
    with db.cursor() as cur:
        cur.execute('UPDATE usuarios SET senha_hash = %s WHERE id = %s', (_hash_senha(d['nova']), uid))
    db.commit()
    return jsonify({'ok': True})

@app.route('/api/usuarios/<int:uid>', methods=['DELETE'])
@admin_obrigatorio
def api_remover_usuario(uid):
    u = usuario_atual()
    if uid == u['id']:
        return jsonify({'erro': 'Você não pode remover a si mesmo'}), 400
    db = get_db()
    with db.cursor() as cur:
        cur.execute('DELETE FROM usuarios WHERE id = %s', (uid,))
    db.commit()
    return jsonify({'ok': True})

# ============================================================
# REGIÕES
# ============================================================
_REGIOES = { ... }  # (manter o mapa COREDES que já existe no seu arquivo original)
MAPA_REGIOES = {_sem_acento(m): reg for reg, muns in _REGIOES.items() for m in muns}

def _sem_acento(s):
    s = unicodedata.normalize('NFD', str(s))
    return ''.join(c for c in s if unicodedata.category(c) != 'Mn').upper().strip()

def _regiao_do_mapa(municipio):
    return MAPA_REGIOES.get(_sem_acento(municipio))

@app.route('/api/regioes', methods=['GET'])
@login_obrigatorio
def api_listar_regioes():
    return jsonify([{'m': m, 'r': r} for r, muns in _REGIOES.items() for m in muns])

# ============================================================
# CRUD DE EMENDAS
# ============================================================
@app.route('/api/emendas', methods=['GET'])
@login_obrigatorio
def listar_emendas():
    q = request.args.get('q', '').strip()
    municipio = request.args.get('municipio', '').strip()
    situacao = request.args.get('situacao', '').strip()
    ano = request.args.get('ano', '').strip()
    parada_dias = request.args.get('parada_dias', '').strip()

    sql = 'SELECT * FROM emendas WHERE 1=1'
    params = []
    if q:
        sql += ' AND (numero_emenda ILIKE %s OR objeto ILIKE %s OR municipio ILIKE %s OR entidade ILIKE %s OR lider ILIKE %s)'
        like = f'%{q}%'
        params += [like, like, like, like, like]
    if municipio: sql += ' AND municipio = %s'; params.append(municipio)
    if situacao: sql += ' AND situacao = %s'; params.append(situacao)
    if ano: sql += ' AND ano = %s'; params.append(ano)
    if parada_dias:
        sql += " AND atualizado_em IS NOT NULL AND (CURRENT_DATE - atualizado_em::date) >= %s"
        params.append(int(parada_dias))
    sql += ' ORDER BY ano DESC, id DESC'

    db = get_db()
    with db.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()

    resultados = []
    for r in rows:
        d = dict(r)
        d['dias_parada'] = _dias_desde(d.get('atualizado_em'))
        d['situacao_data'] = d.get('atualizado_em')
        d['valor_empenhado'] = float(d.get('valor_empenhado') or 0)
        d['valor_pago'] = float(d.get('valor_pago') or 0)
        resultados.append(d)
    return jsonify(resultados)

@app.route('/api/emendas/<int:eid>', methods=['GET'])
@login_obrigatorio
def obter_emenda(eid):
    db = get_db()
    with db.cursor() as cur:
        cur.execute('SELECT * FROM emendas WHERE id = %s', (eid,))
        row = cur.fetchone()
    if not row: abort(404)
    d = dict(row)
    d['dias_parada'] = _dias_desde(d.get('atualizado_em'))
    d['valor_empenhado'] = float(d.get('valor_empenhado') or 0)
    d['valor_pago'] = float(d.get('valor_pago') or 0)
    return jsonify(d)

@app.route('/api/emendas', methods=['POST'])
@login_obrigatorio
def criar_emenda():
    d = request.get_json(silent=True) or {}
    for campo in ['numero_emenda', 'ano', 'municipio']:
        if not str(d.get(campo, '')).strip():
            return jsonify({'erro': f'Campo obrigatorio ausente: {campo}'}), 400
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute('''INSERT INTO emendas
              (numero_emenda, ano, municipio, objeto, valor_empenhado, valor_pago, situacao, observacoes,
               secretaria, lider, oficio, referencia, entidade, cnpj, regiao, numero_e, justificativa,
               atualizado_por, atualizado_em)
              VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'gabinete',%s) RETURNING id''',
                        (d['numero_emenda'].strip(), int(d['ano']), d['municipio'].strip(),
                         (d.get('objeto') or '').strip(), float(d.get('valor_empenhado') or 0),
                         float(d.get('valor_pago') or 0), d.get('situacao', 'Aguardando'),
                         (d.get('observacoes') or '').strip(), (d.get('secretaria') or '').strip(),
                         (d.get('lider') or '').strip(), (d.get('oficio') or '').strip(),
                         (d.get('referencia') or '').strip(), (d.get('entidade') or '').strip(),
                         (d.get('cnpj') or '').strip(), (d.get('regiao') or '').strip(),
                         (d.get('numero_e') or '').strip(), (d.get('justificativa') or '').strip(),
                         datetime.now().isoformat(timespec='seconds')))
            new_id = cur.fetchone()['id']
        db.commit()
        registrar_log('criou', emenda_id=new_id, numero=d['numero_emenda'],
                      municipio=d['municipio'], ano=int(d['ano']))
        return jsonify({'id': new_id, 'mensagem': 'Emenda criada'}), 201
    except Exception as e:
        db.rollback()
        return jsonify({'erro': str(e), 'tipo': type(e).__name__}), 500

@app.route('/api/emendas/<int:eid>', methods=['PUT'])
@login_obrigatorio
def atualizar_emenda(eid):
    d = request.get_json(silent=True) or {}
    db = get_db()
    with db.cursor() as cur:
        cur.execute('SELECT * FROM emendas WHERE id = %s', (eid,))
        row = cur.fetchone()
    if not row: return jsonify({'erro': 'Emenda nao encontrada'}), 404
    versao_atual = row['versao'] if row['versao'] is not None else 1
    if 'versao' in d and int(d['versao']) != versao_atual:
        return jsonify({'erro': 'conflito', 'versao_atual': versao_atual}), 409
    try:
        with db.cursor() as cur:
            cur.execute('''UPDATE emendas SET
              numero_emenda = %s, ano = %s, municipio = %s, objeto = %s, valor_empenhado = %s, valor_pago = %s,
              situacao = %s, observacoes = %s, secretaria = %s, lider = %s, oficio = %s, referencia = %s,
              entidade = %s, cnpj = %s, regiao = %s, numero_e = %s, justificativa = %s,
              versao = versao + 1, atualizado_por = 'gabinete', atualizado_em = %s
              WHERE id = %s''',
                        (d.get('numero_emenda', row['numero_emenda']), int(d.get('ano') or row['ano']),
                         d.get('municipio', row['municipio']), (d.get('objeto') or '').strip(),
                         float(d.get('valor_empenhado') or 0), float(d.get('valor_pago') or 0),
                         d.get('situacao', 'Aguardando'), (d.get('observacoes') or '').strip(),
                         (d.get('secretaria') or '').strip(), (d.get('lider') or '').strip(),
                         (d.get('oficio') or '').strip(), (d.get('referencia') or '').strip(),
                         (d.get('entidade') or '').strip(), (d.get('cnpj') or '').strip(),
                         (d.get('regiao') or '').strip(), (d.get('numero_e') or '').strip(),
                         (d.get('justificativa') or '').strip(),
                         datetime.now().isoformat(timespec='seconds'), eid))
        db.commit()
        registrar_log('editou', emenda_id=eid, numero=row['numero_emenda'],
                      municipio=row['municipio'], ano=row['ano'])
        return jsonify({'ok': True})
    except Exception as e:
        db.rollback()
        return jsonify({'erro': str(e), 'tipo': type(e).__name__}), 500

@app.route('/api/emendas/<int:eid>', methods=['DELETE'])
@login_obrigatorio
def excluir_emenda(eid):
    u = usuario_atual()
    db = get_db()
    with db.cursor() as cur:
        cur.execute('SELECT * FROM emendas WHERE id = %s', (eid,))
        row = cur.fetchone()
        if not row: return jsonify({'erro': 'Não encontrada'}), 404
        dados = dict(row)
        for k in ('valor_empenhado', 'valor_pago'):
            dados[k] = float(dados.get(k) or 0)
        cur.execute('''INSERT INTO lixeira (excluida_em, excluida_por, dados)
                       VALUES (%s,%s,%s)''',
                    (datetime.now().isoformat(timespec='seconds'),
                     (u or {}).get('nome', 'sistema'),
                     _json.dumps(dados, default=str, ensure_ascii=False)))
        cur.execute('DELETE FROM emendas WHERE id = %s', (eid,))
    db.commit()
    registrar_log('excluiu', emenda_id=eid, numero=row['numero_emenda'],
                  municipio=row['municipio'], ano=row['ano'])
    return jsonify({'ok': True})

# ============================================================
# FILTROS E ESTATÍSTICAS
# ============================================================
@app.route('/api/filtros', methods=['GET'])
@login_obrigatorio
def filtros():
    db = get_db()
    with db.cursor() as cur:
        def uniq(sql):
            cur.execute(sql)
            return [r[list(r.keys())[0]] for r in cur.fetchall() if r[list(r.keys())[0]]]
        return jsonify({
            'municipios': uniq('SELECT DISTINCT municipio FROM emendas ORDER BY municipio'),
            'anos': uniq('SELECT DISTINCT ano FROM emendas ORDER BY ano DESC'),
            'secretarias': uniq('SELECT DISTINCT secretaria FROM emendas ORDER BY secretaria'),
            'lideres': uniq('SELECT DISTINCT lider FROM emendas ORDER BY lider'),
            'regioes': uniq('SELECT DISTINCT regiao FROM emendas ORDER BY regiao'),
            'situacoes': SITUACOES,
        })

def _dias_desde(iso):
    if not iso: return None
    try:
        d = datetime.fromisoformat(str(iso)[:10]).date()
        return (datetime.now().date() - d).days
    except Exception:
        return None

@app.route('/api/estatisticas', methods=['GET'])
@login_obrigatorio
def api_estatisticas():
    ano = request.args.get('ano', '').strip()
    db = get_db()
    with db.cursor() as cur:
        sql = 'SELECT * FROM emendas'
        params = []
        if ano:
            sql += ' WHERE ano = %s'; params.append(int(ano))
        cur.execute(sql, params)
        em = [dict(r) for r in cur.fetchall()]

    total = len(em)
    vt = sum(float(e['valor_empenhado'] or 0) for e in em)
    vp = sum(float(e['valor_pago'] or 0) for e in em)
    pagas = sum(1 for e in em if e['situacao'] == 'Pago')
    aguard = sum(1 for e in em if e['situacao'] == 'Aguardando')
    paradas30 = sum(1 for e in em if e['situacao'] == 'Aguardando' and (_dias_desde(e.get('atualizado_em')) or 0) >= 30)

    def rank(campo):
        agg = {}
        for e in em:
            k = e.get(campo) or '(vazio)'
            a = agg.setdefault(k, {'nome': k, 'n': 0, 'valor': 0, 'pagas': 0})
            a['n'] += 1; a['valor'] += float(e['valor_empenhado'] or 0)
            if e['situacao'] == 'Pago': a['pagas'] += 1
        return sorted(agg.values(), key=lambda x: -x['n'])[:10]

    por_sit = {}
    for e in em:
        s = e['situacao'] or 'Aguardando'
        por_sit.setdefault(s, {'nome': s, 'n': 0, 'valor': 0})
        por_sit[s]['n'] += 1; por_sit[s]['valor'] += float(e['valor_empenhado'] or 0)

    faixas = [{'nome': '0 a 29 dias', 'n': 0}, {'nome': '30 a 59 dias', 'n': 0}, {'nome': '60+ dias', 'n': 0}]
    for e in em:
        if e['situacao'] != 'Aguardando': continue
        d = _dias_desde(e.get('atualizado_em')) or 0
        faixas[2 if d >= 60 else 1 if d >= 30 else 0]['n'] += 1

    tempos = []
    for e in em:
        if e['situacao'] == 'Pago' and e.get('pago_em') and e.get('data_entrada'):
            d = (datetime.fromisoformat(str(e['pago_em'])[:10]).date() - datetime.fromisoformat(str(e['data_entrada'])[:10]).date()).days
            if d >= 0: tempos.append(d)
    tempos.sort()
    tp = {'n': len(tempos), 'media': 0, 'mediana': 0, 'minimo': 0, 'maximo': 0}
    if tempos:
        tp['media'] = sum(tempos)/len(tempos); tp['mediana'] = tempos[len(tempos)//2]
        tp['minimo'], tp['maximo'] = tempos[0], tempos[-1]

    por_ano_agg = {}
    for e in em:
        a = str(e['ano'])
        por_ano_agg.setdefault(a, {'nome': a, 'n': 0, 'valor': 0, 'pago': 0})
        por_ano_agg[a]['n'] += 1; por_ano_agg[a]['valor'] += float(e['valor_empenhado'] or 0)
        por_ano_agg[a]['pago'] += float(e['valor_pago'] or 0)

    return jsonify(resumo={'total': total, 'valor_total': vt, 'valor_pago': vp, 'aguardando': aguard, 'pagas': pagas, 'paradas_30': paradas30},
                   tempo_pagamento=tp, tempo_secretaria=[], por_situacao=list(por_sit.values()), faixas_paradas=faixas,
                   lider_n=rank('lider'), lider_valor=rank('lider'), municipio_n=rank('municipio'), municipio_valor=rank('municipio'),
                   regiao_n=rank('regiao'), regiao_valor=rank('regiao'), secretaria_n=rank('secretaria'), secretaria_valor=rank('secretaria'),
                   objeto_n=rank('objeto')[:8], pagamentos_mes=[], por_ano=sorted(por_ano_agg.values(), key=lambda x: x['nome']))

# ============================================================
# LOGS, LIXEIRA, IMPORTAÇÃO E DEMAIS ROTAS
# ============================================================
# (Manter as rotas de logs, lixeira, importação e regiões/importar como no código anterior)
# ...

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
