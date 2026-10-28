import psycopg2
from psycopg2.extras import RealDictCursor
from flask import g
from datetime import datetime

from .config import DATABASE_URL
from .passwords import _hash_senha


def get_db():
    if 'db' not in g:
        g.db = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    return g.db


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
            _criar_tabelas(cur)
            _migrar_emendas(cur)
            _criar_admin(cur)
            _limpar_sessoes(cur)
        conn.commit()
        print("Banco inicializado/migrado com sucesso.")
    finally:
        conn.close()


def _criar_tabelas(cur):
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
        )''')

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
        id SERIAL PRIMARY KEY, criado_em TEXT, usuario TEXT, acao TEXT,
        emenda_id INTEGER, numero_emenda TEXT, municipio TEXT, ano INTEGER,
        detalhe TEXT, mudancas JSONB)''')

    cur.execute('''CREATE TABLE IF NOT EXISTS lixeira (
        id SERIAL PRIMARY KEY, excluida_em TEXT, excluida_por TEXT, dados JSONB)''')


def _migrar_emendas(cur):
    colunas = [
        ('secretaria', 'TEXT'), ('lider', 'TEXT'), ('oficio', 'TEXT'),
        ('referencia', 'TEXT'), ('entidade', 'TEXT'), ('cnpj', 'TEXT'),
        ('regiao', 'TEXT'), ('numero_e', 'TEXT'), ('justificativa', 'TEXT'),
        ('situacao_bruta', 'TEXT'), ('pago_em', 'TEXT'), ('data_entrada', 'TEXT'),
        ('resp_nome', 'TEXT'), ('resp_contato', 'TEXT'), ('resp_email', 'TEXT'),
        ('pf_nome', 'TEXT'), ('pf_contato', 'TEXT'), ('pf_email', 'TEXT'),
    ]
    for col, tipo in colunas:
        cur.execute(f"ALTER TABLE emendas ADD COLUMN IF NOT EXISTS {col} {tipo}")

    cur.execute("SELECT 1 FROM pg_constraint WHERE conname = 'emendas_ano_numero_key'")
    if not cur.fetchone():
        cur.execute("SAVEPOINT add_unique")
        try:
            cur.execute("""
                ALTER TABLE emendas
                ADD CONSTRAINT emendas_ano_numero_key UNIQUE (ano, numero_emenda)""")
            cur.execute("RELEASE SAVEPOINT add_unique")
        except Exception:
            cur.execute("ROLLBACK TO SAVEPOINT add_unique")
            print("AVISO: duplicatas em (ano,numero_emenda). Constraint nao criada.")


def _criar_admin(cur):
    cur.execute("SELECT 1 FROM usuarios WHERE LOWER(usuario) = 'admin'")
    if not cur.fetchone():
        cur.execute('''INSERT INTO usuarios (nome, usuario, senha_hash, admin, criado_em)
                       VALUES ('Administrador','admin',%s,true,%s)''',
                    (_hash_senha('admin123'),
                     datetime.now().isoformat(timespec='seconds')))
        print("-> admin/admin123 criado. TROQUE A SENHA!")


def _limpar_sessoes(cur):
    cur.execute("DELETE FROM sessoes WHERE expira_em IS NOT NULL "
                "AND expira_em < NOW() - INTERVAL '30 days'")
