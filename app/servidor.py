"""
Controle de Emendas — backend
Start (Render): gunicorn servidor:app --timeout 120
Env: DATABASE_URL (Supabase pooler, porta 6543, ?sslmode=require&pgbouncer=true)
"""
import hashlib
import hmac
import json
import os
import re
import secrets
import unicodedata
from datetime import datetime
from functools import wraps
from io import BytesIO

import pandas as pd
import psycopg2
import psycopg2.errors
from psycopg2.extras import RealDictCursor, execute_values, Json
from flask import Flask, request, jsonify, render_template, g, abort

app = Flask(__name__)
DATABASE_URL = os.environ.get('DATABASE_URL')

SITUACOES = ['Aguardando', 'Empenhado', 'Pago', 'Cancelada']
NSC = "não consta na planilha"
PREFIXO_OBS = "Situação (planilha):"


# ============================================================
# HELPERS BÁSICOS
# ============================================================
def _sem_acento(s):
    s = unicodedata.normalize('NFD', str(s))
    return ''.join(c for c in s if unicodedata.category(c) != 'Mn').upper().strip()


def _hash_senha(senha, salt=None):
    salt = salt or secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac('sha256', senha.encode(), salt.encode(), 100_000).hex()
    return f'{salt}${h}'


def _verifica_senha(senha, hashed):
    try:
        salt, _ = hashed.split('$', 1)
        return hmac.compare_digest(_hash_senha(senha, salt), hashed)
    except Exception:
        return False


def _dias_desde(iso):
    if not iso:
        return None
    try:
        d = datetime.fromisoformat(str(iso)[:10]).date()
        return (datetime.now().date() - d).days
    except Exception:
        return None


# ============================================================
# REGIÕES (COREDES RS)
# ============================================================
_REGIOES = {
    "NOROESTE COLONIAL": ["IJUÍ", "SANTO AUGUSTO", "CÉSAR AUGUSTO", "AJURICABA"],
    "ALTO JACUÍ": ["CRUZ ALTA", "IBIRUBÁ", "SELBACH", "TAPERA", "SALDANHA MARINHO",
                   "SANTA BÁRBARA DO SUL", "QUINZE DE NOVEMBRO"],
    "CELEIRO – ITIBERÊ OSÓRIO": ["TRÊS PASSOS", "FREDERICO WESTPHALEN", "HORIZONTINA",
                                 "PALMEIRA DAS MISSÕES", "SARANDI", "TUCUNDUVA",
                                 "SÃO MARTINHO", "VISTA GAÚCHA"],
    "VINHEDOS": ["BENTO GONÇALVES", "GARIBALDI", "CARLOS BARBOSA", "MONTE BELO DO SUL",
                 "PINTO BANDEIRA", "SANTA TEREZA", "VALE REAL", "NOVA ROMA DO SUL"],
    "ALTO URUGUAI – LEONEL BRIZOLA": ["ERECHIM", "GETÚLIO VARGAS", "ARATIBA", "JACUTINGA",
                                      "SEVERIANO DE ALMEIDA"],
    "GRANDE GUAPORÉ": ["GUAPORÉ", "ENCONSTADO", "MUÇUM", "DOIS LAJEADOS", "COTIPOARA",
                       "COTIPORÃ", "SÉRIO", "PUTINGA", "NOVA BASSANO"],
    "TRABALHISTA DO PLANALTO": ["PASSO FUNDO", "CARAZINHO", "TAPEJARA", "CAMPO NOVO",
                                "CIRÍACO", "COXILHA", "SANTA CECÍLIA DO SUL", "NÃO-ME-TOQUE"],
    "ZONA SUL": ["PELOTAS", "RIO GRANDE", "CAMAQUÃ", "CANGUÇU", "SÃO JOSÉ DO NORTE",
                 "CRISTAL", "TAPES", "ARAMBARÉ", "DOM FELICIANO", "SENTINELA DO SUL",
                 "CHUVISCA"],
    "FRONTEIRA OESTE": ["URUGUAIANA", "ALEGRETE", "SÃO BORJA", "ITAQUI",
                        "BARRA DO QUARAÍ", "QUARAÍ", "MANOEL VIANA", "MAÇAMBARÁ"],
    "FRONTEIRA NOROESTE - PAULO MADEIRA": ["SANTA ROSA", "SANTO CRISTO", "GIRUÁ",
                                           "TRÊS DE MAIO", "TUPARENDI",
                                           "BOA VISTA DO BURICÁ", "NOVO MACHADO"],
    "FRONTEIRA SUDESTE": ["BAGÉ", "DOM PEDRITO", "HERVAL", "PEDRAS ALTAS",
                          "PINHEIRO MACHADO", "ACEGUÁ", "CANDIOTA", "HULHA NEGRA"],
    "VALE DO JACUÍ": ["CACHOEIRA DO SUL", "RIO PARDO", "SOBRADINHO", "CERRO BRANCO",
                      "NOVO CABRAIS", "PANTANO GRANDE", "AGUDO", "PARAÍSO DO SUL"],
    "GRANDE CAXIAS": ["CAXIAS DO SUL", "FLORES DA CUNHA", "SÃO MARCOS",
                      "NOVA PÁDUA", "FARROUPILHA"],
    "JOSÉ AMÉRICO FREIRE": ["SÃO JERÔNIMO", "CHARQUEADAS", "ARROIO DOS RATOS",
                            "ELDORADO DO SUL"],
    "VALE DO ALTO TAQUARI": ["LAJEADO", "ARROIO DO MEIO", "ROCA SALES", "TRAVESSEIRO",
                             "CAPITÃO", "POUSO NOVO", "PROGRESSO", "FORQUETINHA"],
    "ALTO DA SERRA DO BOTUCARAÍ": ["SOLEDADE", "ESPUMOSO", "FONTOURA XAVIER",
                                    "NOVA PALMA", "TUNAS"],
    "GRANDE SANTA MARIA": ["SANTA MARIA", "JÚLIO DE CASTILHOS", "SÃO PEDRO DO SUL",
                            "RESTINGA SÉCA", "TOROPI", "SILVEIRA MARTINS"],
    "ALTO DA SERRA": ["VACARIA", "BOM JESUS", "MONTE ALEGRE DOS CAMPOS",
                       "CAMPESTRE DA SERRA", "SÃO JOSÉ DOS AUSENTES", "JAQUIRANA"],
    "MEDIO ALTO URUGUAI – JOÃO GOULART": ["VICENTE DUTRA", "SÃO PEDRO DAS MISSÕES",
                                          "TRINDADE DO SUL"],
    "GRANDE LAGOA": ["OSÓRIO", "TRAMANDAÍ", "IMBÉ", "XANGRI-LÁ", "MOSTARDAS",
                     "PALMARES DO SUL", "CIDREIRA", "CAPIVARI DO SUL"],
    "LITORAL NORTE": ["TORRES", "ARROIO DO SAL", "DOM PEDRO DE ALCÂNTARA",
                       "TRÊS CACHOEIRAS", "MAQUINÉ", "MORRINHOS DO SUL"],
    "VALE DO PARANHANA": ["TAQUARA", "IGREJINHA", "PAROBÉ", "ROLANTE", "TRÊS COROAS",
                          "SANTA MARIA DO HERVAL"],
    "MILTON GARCIA DUTRA": ["RONDA ALTA", "LIBERATO SALZANO"],
    "METROPOLITANO DELTA DO JACUÍ": ["PORTO ALEGRE", "GRAVATAÍ", "VIAMÃO", "ALVORADA"],
    "VALE DO RIO DOS SINOS": ["NOVO HAMBURGO", "SÃO LEOPOLDO", "ESTEIO"],
    "SERRA": ["GRAMADO", "CANELA", "NOVA PETRÓPOLIS"],
}

MAPA_REGIOES = {_sem_acento(m): reg for reg, muns in _REGIOES.items() for m in muns}


def _regiao_do_mapa(municipio):
    return MAPA_REGIOES.get(_sem_acento(municipio))


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
            cur.execute('''
                CREATE TABLE IF NOT EXISTS emendas (
                    id SERIAL PRIMARY KEY,
                    numero_emenda TEXT NOT NULL,
                    ano INTEGER NOT NULL,
                    municipio TEXT NOT NULL,
                    objeto TEXT,
                    valor_empenhado NUMERIC(12,2) DEFAULT 0,
                    valor_pago NUMERIC(12,2) DEFAULT 0,
                    situacao TEXT DEFAULT 'Aguardando',
                    observacoes TEXT,
                    versao INTEGER DEFAULT 1,
                    atualizado_por TEXT,
                    atualizado_em TEXT
                )
            ''')

            for col, tipo in [
                ('secretaria', 'TEXT'), ('lider', 'TEXT'), ('oficio', 'TEXT'),
                ('referencia', 'TEXT'), ('entidade', 'TEXT'), ('cnpj', 'TEXT'),
                ('regiao', 'TEXT'), ('numero_e', 'TEXT'), ('justificativa', 'TEXT'),
                ('situacao_bruta', 'TEXT'), ('pago_em', 'TEXT'), ('data_entrada', 'TEXT'),
            ]:
                cur.execute(f"ALTER TABLE emendas ADD COLUMN IF NOT EXISTS {col} {tipo}")

            cur.execute("SELECT 1 FROM pg_constraint WHERE conname = 'emendas_ano_numero_key'")
            if not cur.fetchone():
                cur.execute("SAVEPOINT add_unique")
                try:
                    cur.execute("""
                        ALTER TABLE emendas
                        ADD CONSTRAINT emendas_ano_numero_key UNIQUE (ano, numero_emenda)
                    """)
                    cur.execute("RELEASE SAVEPOINT add_unique")
                except Exception:
                    cur.execute("ROLLBACK TO SAVEPOINT add_unique")
                    print("AVISO: duplicatas em (ano,numero_emenda). Constraint nao criada.")

            cur.execute('''CREATE TABLE IF NOT EXISTS usuarios (
                id SERIAL PRIMARY KEY,
                nome TEXT NOT NULL,
                usuario TEXT UNIQUE NOT NULL,
                senha_hash TEXT NOT NULL,
                admin BOOLEAN DEFAULT false,
                criado_em TEXT)''')

            cur.execute('''CREATE TABLE IF NOT EXISTS sessoes (
                token TEXT PRIMARY KEY,
                usuario_id INTEGER REFERENCES usuarios(id) ON DELETE CASCADE,
                criado_em TIMESTAMP DEFAULT NOW(),
                expira_em TIMESTAMP)''')

            cur.execute('''CREATE TABLE IF NOT EXISTS logs (
                id SERIAL PRIMARY KEY,
                criado_em TEXT,
                usuario TEXT,
                acao TEXT,
                emenda_id INTEGER,
                numero_emenda TEXT,
                municipio TEXT,
                ano INTEGER,
                detalhe TEXT,
                mudancas JSONB)''')

            cur.execute('''CREATE TABLE IF NOT EXISTS lixeira (
                id SERIAL PRIMARY KEY,
                excluida_em TEXT,
                excluida_por TEXT,
                dados JSONB)''')

            # Limpeza de sessões antigas
            cur.execute("DELETE FROM sessoes WHERE expira_em IS NOT NULL "
                        "AND expira_em < NOW() - INTERVAL '30 days'")

            # Cria admin se não existir
            cur.execute("SELECT 1 FROM usuarios WHERE LOWER(usuario) = 'admin'")
            if not cur.fetchone():
                cur.execute('''INSERT INTO usuarios (nome, usuario, senha_hash, admin, criado_em)
                               VALUES ('Administrador','admin',%s,true,%s)''',
                            (_hash_senha('admin123'),
                             datetime.now().isoformat(timespec='seconds')))
                print("Usuario admin criado (admin/admin123). TROQUE A SENHA!")

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
# AUTH HELPERS
# ============================================================
def usuario_atual():
    h = request.headers.get('Authorization', '')
    if not h.startswith('Bearer '):
        return None
    token = h[7:]
    db = get_db()
    with db.cursor() as cur:
        cur.execute('''
            SELECT u.id, u.nome, u.usuario, u.admin
            FROM sessoes s JOIN usuarios u ON u.id = s.usuario_id
            WHERE s.token = %s AND (s.expira_em IS NULL OR s.expira_em > NOW())
        ''', (token,))
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
        if not u:
            return jsonify({'erro': 'Não autorizado'}), 401
        if not u.get('admin'):
            return jsonify({'erro': 'Apenas administradores'}), 403
        return f(*a, **k)
    return w


def registrar_log(acao, emenda_id=None, numero=None, municipio=None, ano=None,
                  detalhe=None, mudancas=None):
    u = usuario_atual()
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute('''
                INSERT INTO logs (criado_em, usuario, acao, emenda_id, numero_emenda,
                                  municipio, ano, detalhe, mudancas)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ''', (
                datetime.now().isoformat(timespec='seconds'),
                (u or {}).get('nome', 'sistema'),
                acao, emenda_id, numero, municipio,
                int(ano) if ano else None, detalhe,
                Json(mudancas or [],
                     dumps=lambda o: json.dumps(o, default=str, ensure_ascii=False)),
            ))
        db.commit()
    except Exception as e:
        print('Erro registrando log:', e)
        db.rollback()


# ============================================================
# ROTAS DE AUTH
# ============================================================
@app.route('/')
def index():
    return render_template('index.html')


@app.route('/favicon.ico')
def favicon():
    return '', 204


@app.route('/api/login', methods=['POST'])
def api_login():
    d = request.get_json(silent=True) or {}
    usuario = (d.get('usuario') or '').strip().lower()
    senha = d.get('senha') or ''
    db = get_db()
    with db.cursor() as cur:
        # LOWER() nos dois lados — aceita 'admin', 'Admin', 'ADMIN'
        cur.execute('SELECT * FROM usuarios WHERE LOWER(usuario) = %s', (usuario,))
        row = cur.fetchone()
    if not row or not _verifica_senha(senha, row['senha_hash']):
        return jsonify({'erro': 'Usuário ou senha inválidos'}), 401
    token = secrets.token_hex(24)
    with db.cursor() as cur:
        cur.execute('''INSERT INTO sessoes (token, usuario_id, expira_em)
                       VALUES (%s,%s, NOW() + INTERVAL '7 days')''',
                    (token, row['id']))
    db.commit()
    return jsonify(id=row['id'], nome=row['nome'], usuario=row['usuario'],
                   admin=row['admin'], token=token)


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
        cur.execute('UPDATE usuarios SET senha_hash = %s WHERE id = %s',
                    (_hash_senha(nova), u['id']))
    db.commit()
    return jsonify({'ok': True})


# ============================================================
# USUÁRIOS
# ============================================================
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
    login = (d.get('usuario') or '').strip().lower()   # normaliza p/ minúsculo
    if not d.get('nome') or not login or len(d.get('senha') or '') < 6:
        return jsonify({'erro': 'Nome, usuário e senha (mín. 6) são obrigatórios'}), 400
    db = get_db()
    try:
        with db.cursor() as cur:
            # Impede duplicidade mesmo se já houver alguma linha em maiúscula
            cur.execute('SELECT 1 FROM usuarios WHERE LOWER(usuario) = %s', (login,))
            if cur.fetchone():
                return jsonify({'erro': 'Este login já existe'}), 400
            cur.execute('''INSERT INTO usuarios (nome, usuario, senha_hash, admin, criado_em)
                           VALUES (%s,%s,%s,%s,%s) RETURNING id''',
                        (d['nome'].strip(), login, _hash_senha(d['senha']),
                         bool(d.get('admin')),
                         datetime.now().isoformat(timespec='seconds')))
            new_id = cur.fetchone()['id']
        db.commit()
        return jsonify({'id': new_id}), 201
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
        cur.execute('UPDATE usuarios SET senha_hash = %s WHERE id = %s',
                    (_hash_senha(d['nova']), uid))
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
@app.route('/api/regioes', methods=['GET'])
@login_obrigatorio
def api_listar_regioes():
    return jsonify([{'m': m, 'r': r} for r, muns in _REGIOES.items() for m in muns])


@app.route('/api/regioes/importar', methods=['POST'])
@admin_obrigatorio
def api_importar_regioes():
    global MAPA_REGIOES, _REGIOES
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


# ============================================================
# CRUD EMENDAS
# ============================================================
@app.route('/api/emendas', methods=['GET'])
@login_obrigatorio
def listar_emendas():
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

    out = []
    for r in rows:
        d = dict(r)
        d['valor_empenhado'] = float(d.get('valor_empenhado') or 0)
        d['valor_pago'] = float(d.get('valor_pago') or 0)
        d['dias_parada'] = _dias_desde(d.get('atualizado_em'))
        d['situacao_data'] = d.get('atualizado_em')
        out.append(d)
    return jsonify(out)


@app.route('/api/emendas/<int:eid>', methods=['GET'])
@login_obrigatorio
def obter_emenda(eid):
    db = get_db()
    with db.cursor() as cur:
        cur.execute('SELECT * FROM emendas WHERE id = %s', (eid,))
        row = cur.fetchone()
    if not row:
        abort(404)
    d = dict(row)
    d['valor_empenhado'] = float(d.get('valor_empenhado') or 0)
    d['valor_pago'] = float(d.get('valor_pago') or 0)
    d['dias_parada'] = _dias_desde(d.get('atualizado_em'))
    d['situacao_data'] = d.get('atualizado_em')
    return jsonify(d)


@app.route('/api/emendas', methods=['POST'])
@login_obrigatorio
def criar_emenda():
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
                   data_entrada, atualizado_por, atualizado_em)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'gabinete',%s)
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


@app.route('/api/emendas/<int:eid>', methods=['PUT'])
@login_obrigatorio
def atualizar_emenda(eid):
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


@app.route('/api/emendas/<int:eid>', methods=['DELETE'])
@login_obrigatorio
def excluir_emenda(eid):
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
                     Json(dados, dumps=lambda o: json.dumps(o, default=str, ensure_ascii=False))))
        cur.execute('DELETE FROM emendas WHERE id = %s', (eid,))
    db.commit()
    registrar_log('excluiu', emenda_id=eid, numero=row['numero_emenda'],
                  municipio=row['municipio'], ano=row['ano'])
    return jsonify({'ok': True})


# ============================================================
# FILTROS
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
            'municipios':  uniq('SELECT DISTINCT municipio FROM emendas ORDER BY municipio'),
            'anos':        uniq('SELECT DISTINCT ano FROM emendas ORDER BY ano DESC'),
            'secretarias': uniq('SELECT DISTINCT secretaria FROM emendas ORDER BY secretaria'),
            'lideres':     uniq('SELECT DISTINCT lider FROM emendas ORDER BY lider'),
            'regioes':     uniq('SELECT DISTINCT regiao FROM emendas ORDER BY regiao'),
            'situacoes':   SITUACOES,
        })


# ============================================================
# ESTATÍSTICAS
# ============================================================
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
    paradas30 = sum(1 for e in em if e['situacao'] == 'Aguardando'
                    and (_dias_desde(e.get('atualizado_em')) or 0) >= 30)

    def rank(campo):
        agg = {}
        for e in em:
            k = e.get(campo) or '(vazio)'
            a = agg.setdefault(k, {'nome': k, 'n': 0, 'valor': 0, 'pagas': 0})
            a['n'] += 1
            a['valor'] += float(e['valor_empenhado'] or 0)
            if e['situacao'] == 'Pago':
                a['pagas'] += 1
        return sorted(agg.values(), key=lambda x: -x['n'])[:10]

    por_sit = {}
    for e in em:
        s = e['situacao'] or 'Aguardando'
        por_sit.setdefault(s, {'nome': s, 'n': 0, 'valor': 0})
        por_sit[s]['n'] += 1
        por_sit[s]['valor'] += float(e['valor_empenhado'] or 0)

    faixas = [{'nome': '0 a 29 dias', 'n': 0},
              {'nome': '30 a 59 dias', 'n': 0},
              {'nome': '60+ dias', 'n': 0}]
    for e in em:
        if e['situacao'] != 'Aguardando':
            continue
        d = _dias_desde(e.get('atualizado_em')) or 0
        faixas[2 if d >= 60 else 1 if d >= 30 else 0]['n'] += 1

    tempos = []
    tempos_sec = {}
    for e in em:
        if e['situacao'] == 'Pago' and e.get('pago_em') and e.get('data_entrada'):
            try:
                d = (datetime.fromisoformat(str(e['pago_em'])[:10]).date()
                     - datetime.fromisoformat(str(e['data_entrada'])[:10]).date()).days
                if d >= 0:
                    tempos.append(d)
                    sec = e.get('secretaria') or '(vazio)'
                    tempos_sec.setdefault(sec, []).append(d)
            except Exception:
                pass
    tempos.sort()
    tp = {'n': len(tempos), 'media': 0, 'mediana': 0, 'minimo': 0, 'maximo': 0}
    if tempos:
        tp['media'] = sum(tempos) / len(tempos)
        tp['mediana'] = tempos[len(tempos) // 2]
        tp['minimo'], tp['maximo'] = tempos[0], tempos[-1]

    tempo_secretaria = [
        {'nome': s, 'media': sum(v) / len(v), 'n': len(v)}
        for s, v in tempos_sec.items()
    ]
    tempo_secretaria.sort(key=lambda x: x['media'])

    por_ano_agg = {}
    for e in em:
        a = str(e['ano'])
        por_ano_agg.setdefault(a, {'nome': a, 'n': 0, 'valor': 0, 'pago': 0})
        por_ano_agg[a]['n'] += 1
        por_ano_agg[a]['valor'] += float(e['valor_empenhado'] or 0)
        por_ano_agg[a]['pago'] += float(e['valor_pago'] or 0)

    pag_mes = {}
    for e in em:
        if e['situacao'] == 'Pago' and e.get('pago_em') and e['valor_pago']:
            k = str(e['pago_em'])[:7]
            pag_mes.setdefault(k, {'nome': k, 'valor': 0, 'n': 0})
            pag_mes[k]['valor'] += float(e['valor_pago'])
            pag_mes[k]['n'] += 1

    return jsonify(
        resumo={'total': total, 'valor_total': vt, 'valor_pago': vp,
                'aguardando': aguard, 'pagas': pagas, 'paradas_30': paradas30},
        tempo_pagamento=tp,
        tempo_secretaria=tempo_secretaria,
        por_situacao=list(por_sit.values()),
        faixas_paradas=faixas,
        lider_n=rank('lider'), lider_valor=rank('lider'),
        municipio_n=rank('municipio'), municipio_valor=rank('municipio'),
        regiao_n=rank('regiao'), regiao_valor=rank('regiao'),
        secretaria_n=rank('secretaria'), secretaria_valor=rank('secretaria'),
        objeto_n=rank('objeto')[:8],
        pagamentos_mes=sorted(pag_mes.values(), key=lambda x: x['nome']),
        por_ano=sorted(por_ano_agg.values(), key=lambda x: x['nome']),
    )


# ============================================================
# LOGS
# ============================================================
@app.route('/api/logs', methods=['GET'])
@login_obrigatorio
def api_logs():
    q = request.args.get('q', '').strip()
    usuario = request.args.get('usuario', '').strip()
    acao = request.args.get('acao', '').strip()
    emenda_id = request.args.get('emenda_id', '').strip()
    limite = int(request.args.get('limite', 50))
    offset = int(request.args.get('offset', 0))

    where, params = '1=1', []
    if q:
        like = f'%{q}%'
        where += ' AND (numero_emenda ILIKE %s OR municipio ILIKE %s OR detalhe ILIKE %s)'
        params += [like, like, like]
    if usuario:
        where += ' AND usuario = %s'; params.append(usuario)
    if acao:
        where += ' AND acao = %s'; params.append(acao)
    if emenda_id:
        where += ' AND emenda_id = %s'; params.append(int(emenda_id))

    db = get_db()
    with db.cursor() as cur:
        cur.execute(f'SELECT COUNT(*) AS n FROM logs WHERE {where}', params)
        total = cur.fetchone()['n']
        cur.execute(f'SELECT * FROM logs WHERE {where} ORDER BY id DESC LIMIT %s OFFSET %s',
                    params + [limite, offset])
        itens = cur.fetchall()
        cur.execute('SELECT DISTINCT usuario FROM logs WHERE usuario IS NOT NULL ORDER BY usuario')
        usuarios = [r['usuario'] for r in cur.fetchall()]

    for it in itens:
        it['mudancas'] = it['mudancas'] or []
    return jsonify(itens=[dict(i) for i in itens], total=total, usuarios=usuarios)


# ============================================================
# LIXEIRA
# ============================================================
@app.route('/api/lixeira', methods=['GET'])
@login_obrigatorio
def api_lixeira():
    db = get_db()
    with db.cursor() as cur:
        cur.execute('SELECT * FROM lixeira ORDER BY id DESC')
        return jsonify([dict(r) for r in cur.fetchall()])


@app.route('/api/lixeira/<int:lid>/restaurar', methods=['POST'])
@login_obrigatorio
def api_restaurar(lid):
    db = get_db()
    with db.cursor() as cur:
        cur.execute('SELECT * FROM lixeira WHERE id = %s', (lid,))
        item = cur.fetchone()
        if not item:
            return jsonify({'erro': 'Item não encontrado'}), 404
        dados = item['dados']
        cols = [c for c in dados.keys() if c != 'id']
        cols = [c for c in cols if c in (
            'numero_emenda', 'ano', 'municipio', 'objeto', 'valor_empenhado',
            'valor_pago', 'situacao', 'observacoes', 'versao', 'atualizado_por',
            'atualizado_em', 'secretaria', 'lider', 'oficio', 'referencia',
            'entidade', 'cnpj', 'regiao', 'numero_e', 'justificativa',
            'situacao_bruta', 'pago_em', 'data_entrada')]
        placeholders = ','.join(['%s'] * len(cols))
        vals = [dados.get(c) for c in cols]
        try:
            cur.execute(f'INSERT INTO emendas ({",".join(cols)}) VALUES ({placeholders})', vals)
            cur.execute('DELETE FROM lixeira WHERE id = %s', (lid,))
            db.commit()
        except psycopg2.errors.UniqueViolation:
            db.rollback()
            return jsonify({
                'erro': 'Já existe uma emenda ativa com o mesmo nº e ano. '
                        'Exclua ou renomeie antes de restaurar.'
            }), 409
        except Exception as e:
            db.rollback()
            return jsonify({'erro': str(e)}), 500
    registrar_log('restaurou', numero=dados.get('numero_emenda'),
                  municipio=dados.get('municipio'), ano=dados.get('ano'))
    return jsonify({'ok': True})


@app.route('/api/lixeira/<int:lid>', methods=['DELETE'])
@admin_obrigatorio
def api_excluir_definitivo(lid):
    db = get_db()
    with db.cursor() as cur:
        cur.execute('DELETE FROM lixeira WHERE id = %s', (lid,))
    db.commit()
    return jsonify({'ok': True})


# ============================================================
# IMPORTAÇÃO
# ============================================================
MAPA_COLUNAS = {
    "SITUAÇÃO": "situacao_bruta", "MUNICÍPIO": "municipio",
    "SECRETARIA": "secretaria", "SEC": "secretaria",
    "Nº E": "numero_emenda", "Nº P": "numero_emenda",
    "VALOR": "valor_empenhado", "OFÍCIO": "oficio", "ANO": "ano",
    "OBJETO": "objeto", "LÍDER": "lider", "REFERÊNCIA": "referencia",
    "ENTIDADE": "entidade", "CNPJ": "cnpj", "REGIÃO": "regiao",
    "JUSTIFICATIVA": "justificativa",
}

ABAS_CONFIGURADAS = {
    "2024": {"tem_situacao": False},
    "2025": {"tem_situacao": False},
    "2026": {"tem_situacao": True},
}

CAMPOS_TEXTO = ['objeto', 'secretaria', 'lider', 'oficio', 'referencia',
                'entidade', 'cnpj', 'regiao', 'justificativa']

COLUNAS_INSERT = [
    'numero_emenda', 'ano', 'municipio', 'objeto',
    'valor_empenhado', 'valor_pago', 'situacao',
    'secretaria', 'lider', 'oficio', 'referencia',
    'entidade', 'cnpj', 'regiao', 'justificativa',
    'situacao_bruta', 'observacoes', 'atualizado_em',
]


def _txt(v):
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, (int, float)):
        fv = float(v)
        return str(int(fv)) if fv.is_integer() else str(fv)
    s = str(v).strip()
    return s if s else None


def _valor(v):
    try:
        if v is None or pd.isna(v):
            return 0.0
        if isinstance(v, str):
            v = v.replace('R$', '').strip()
            if ',' in v:
                v = v.replace('.', '').replace(',', '.')
        return float(v)
    except (ValueError, TypeError):
        return 0.0


def _ano(v):
    try:
        if v is None or pd.isna(v):
            return None
        return int(float(v))
    except (ValueError, TypeError):
        return None


def _derivar_situacao(texto_bruto):
    if texto_bruto and re.match(r'^\s*PAGO\b', str(texto_bruto).upper()):
        return "Pago"
    return "Aguardando"


def _codigo_sem_numero(ano, municipio, lider, objeto, valor, secretaria, ocorrencia):
    base = '|'.join([str(ano), _sem_acento(municipio), _sem_acento(lider or ''),
                     _sem_acento(objeto or ''), f'{valor:.2f}',
                     _sem_acento(secretaria or '')])
    cod = 'S/N-' + hashlib.sha1(base.encode('utf-8')).hexdigest()[:8].upper()
    return cod if ocorrencia == 1 else f'{cod}-{ocorrencia}'


def _processar_dataframe(aba, conteudo=None):
    cfg = ABAS_CONFIGURADAS[aba]

    if conteudo is None:
        arquivo = request.files.get('arquivo')
        if not arquivo or arquivo.filename == '':
            raise ValueError("Nenhum arquivo enviado")
        conteudo = arquivo.read()

    df = pd.read_excel(BytesIO(conteudo), sheet_name=aba, engine='openpyxl')
    df.columns = [' '.join(str(c).split()).upper() for c in df.columns]
    df = df.rename(columns=MAPA_COLUNAS)
    df = df.dropna(how='all')

    if 'municipio' not in df.columns:
        raise ValueError("Coluna obrigatória ausente na planilha: MUNICÍPIO")

    registros = []
    ignoradas = 0
    resumo = {'pagas': 0, 'aguardando': 0, 'sem_numero': 0,
              'nao_consta': {c: 0 for c in CAMPOS_TEXTO}}
    ocorrencias = {}
    agora = datetime.now().isoformat(timespec='seconds')

    for _, row in df.iterrows():
        municipio = _txt(row.get('municipio'))
        if not municipio:
            ignoradas += 1
            continue

        ano_val = _ano(row.get('ano')) or int(aba)
        valor = _valor(row.get('valor_empenhado'))

        campos = {}
        for c in CAMPOS_TEXTO:
            if c == 'regiao':
                v = _txt(row.get('regiao')) or _regiao_do_mapa(municipio)
            else:
                v = _txt(row.get(c))
            if not v:
                v = NSC
                resumo['nao_consta'][c] += 1
            campos[c] = v

        numero = _txt(row.get('numero_emenda'))
        if not numero:
            resumo['sem_numero'] += 1
            chave = (ano_val, municipio, campos['lider'], campos['objeto'],
                     valor, campos['secretaria'])
            ocorrencias[chave] = ocorrencias.get(chave, 0) + 1
            numero = _codigo_sem_numero(ano_val, municipio, campos['lider'],
                                        campos['objeto'], valor,
                                        campos['secretaria'], ocorrencias[chave])

        situacao_bruta = _txt(row.get('situacao_bruta')) if cfg['tem_situacao'] else None
        situacao = _derivar_situacao(situacao_bruta)
        valor_pago = valor if situacao == 'Pago' else 0.0

        if situacao == 'Pago':
            resumo['pagas'] += 1
            observacoes = None
        else:
            resumo['aguardando'] += 1
            observacoes = f"{PREFIXO_OBS} {situacao_bruta or NSC}"

        registros.append({
            'numero_emenda': numero, 'ano': ano_val, 'municipio': municipio,
            'objeto': campos['objeto'], 'valor_empenhado': valor,
            'valor_pago': valor_pago, 'situacao': situacao,
            'secretaria': campos['secretaria'], 'lider': campos['lider'],
            'oficio': campos['oficio'], 'referencia': campos['referencia'],
            'entidade': campos['entidade'], 'cnpj': campos['cnpj'],
            'regiao': campos['regiao'], 'justificativa': campos['justificativa'],
            'situacao_bruta': situacao_bruta, 'observacoes': observacoes,
            'atualizado_em': agora,
        })

    return registros, ignoradas, resumo


_SQL_OBS_SEM_LINHA_ANTIGA = (
    r"NULLIF(BTRIM(regexp_replace(COALESCE(emendas.observacoes, ''), "
    r"'(^|\n)Situação \(planilha\):[^\n]*', '', 'g'), ' ' || chr(10)), '')"
)


def _montar_upsert(tem_situacao):
    sets = [
        "municipio = EXCLUDED.municipio",
        "valor_empenhado = EXCLUDED.valor_empenhado",
        "atualizado_em = EXCLUDED.atualizado_em",
    ]
    for c in CAMPOS_TEXTO:
        sets.append(
            f"{c} = CASE WHEN EXCLUDED.{c} = '{NSC}' "
            f"THEN COALESCE(NULLIF(emendas.{c}, ''), EXCLUDED.{c}) "
            f"ELSE EXCLUDED.{c} END"
        )
    if tem_situacao:
        sets += [
            "situacao = CASE WHEN emendas.situacao = 'Cancelada' "
            "THEN emendas.situacao ELSE EXCLUDED.situacao END",
            "situacao_bruta = EXCLUDED.situacao_bruta",
            "observacoes = NULLIF(BTRIM(CONCAT_WS(chr(10), "
            f"{_SQL_OBS_SEM_LINHA_ANTIGA}, EXCLUDED.observacoes), ' ' || chr(10)), '')",
        ]
    sets += [
        "valor_pago = GREATEST(emendas.valor_pago, EXCLUDED.valor_pago)",
        "versao = emendas.versao + 1",
    ]
    return (
        f"INSERT INTO emendas ({', '.join(COLUNAS_INSERT)}) VALUES %s "
        f"ON CONFLICT (ano, numero_emenda) DO UPDATE SET {', '.join(sets)}"
    )


@app.route('/api/importar/preview', methods=['POST'])
@login_obrigatorio
def importar_preview():
    aba = request.form.get('aba', '2026')
    if aba not in ABAS_CONFIGURADAS:
        return jsonify({'erro': f'Aba {aba} ainda não configurada'}), 400
    try:
        registros, ignoradas, resumo = _processar_dataframe(aba)
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


@app.route('/api/importar', methods=['POST'])
@login_obrigatorio
def importar():
    aba = request.form.get('aba', '2026')
    if aba not in ABAS_CONFIGURADAS:
        return jsonify({'erro': f'Aba {aba} ainda não configurada'}), 400
    try:
        registros, ignoradas, resumo = _processar_dataframe(aba)
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


# ============================================================
# MAIN
# ============================================================
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
