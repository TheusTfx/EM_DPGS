import psycopg2
from psycopg2.extras import RealDictCursor
from flask import g
from datetime import datetime

from .config import DATABASE_URL
from .passwords import _hash_senha, _verifica_senha


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
            _migrar_logs(cur)
            _migrar_usuarios(cur)
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

    cur.execute('''CREATE TABLE IF NOT EXISTS demandas (
        id SERIAL PRIMARY KEY,
        ano INTEGER NOT NULL,
        secretaria TEXT,
        municipio TEXT,
        destinatario TEXT,
        objeto TEXT,
        valor NUMERIC(12,2) DEFAULT 0,
        proposta_fpe TEXT,
        status TEXT DEFAULT 'Aguardando',
        observacoes TEXT,
        convenio TEXT,
        proa_sei TEXT,
        data_pagto TEXT,
        versao INTEGER DEFAULT 1,
        atualizado_por TEXT,
        atualizado_em TEXT,
        criado_em TEXT)''')


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


def _migrar_logs(cur):
    """Adiciona a coluna demanda_id na tabela logs (para rastrear ações de demandas)."""
    cur.execute("ALTER TABLE logs ADD COLUMN IF NOT EXISTS demanda_id INTEGER")


def _migrar_usuarios(cur):
    """Controle de acesso: ativação, troca obrigatória de senha e bloqueio por tentativas."""
    cur.execute("ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS ativo BOOLEAN DEFAULT true")
    cur.execute("ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS deve_trocar_senha BOOLEAN DEFAULT false")
    cur.execute("ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS tentativas_falhas INTEGER DEFAULT 0")
    cur.execute("ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS bloqueado_ate TIMESTAMP")
    cur.execute("ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS ultimo_login TEXT")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_sessoes_usuario ON sessoes (usuario_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_sessoes_expira ON sessoes (expira_em)")


def _criar_admin(cur):
    cur.execute('''SELECT id, senha_hash, COALESCE(deve_trocar_senha, false) AS deve
                   FROM usuarios WHERE LOWER(usuario) = 'admin' ''')
    row = cur.fetchone()
    if not row:
        cur.execute('''INSERT INTO usuarios
                         (nome, usuario, senha_hash, admin, criado_em, ativo, deve_trocar_senha)
                       VALUES ('Administrador','admin',%s,true,%s,true,true)''',
                    (_hash_senha('admin123'),
                     datetime.now().isoformat(timespec='seconds')))
        print("-> admin/admin123 criado. A troca de senha sera exigida no primeiro acesso.")
    elif not row['deve'] and _verifica_senha('admin123', row['senha_hash']):
        cur.execute("UPDATE usuarios SET deve_trocar_senha = true WHERE id = %s", (row['id'],))
        print("AVISO: admin ainda usa a senha padrao. Troca obrigatoria ativada.")


def _limpar_sessoes(cur):
    cur.execute("DELETE FROM sessoes WHERE expira_em IS NOT NULL AND expira_em < NOW()")
