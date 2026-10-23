import os
from datetime import datetime
import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Flask, request, jsonify, render_template, g, abort

app = Flask(__name__)

# A string de conexão virá do Render (Environment Variables)
DATABASE_URL = os.environ.get('DATABASE_URL')

SITUACOES = ['Aguardando', 'Empenhado', 'Em execução', 'Pago', 'Cancelada']

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
    """Cria a tabela e migra colunas novas. Roda na importacao."""
    if not DATABASE_URL:
        print("AVISO: DATABASE_URL nao configurada.")
        return
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    try:
        with conn.cursor() as cur:
            # Tabela base
            cur.execute('''
                CREATE TABLE IF NOT EXISTS emendas (
                    id SERIAL PRIMARY KEY,
                    numero_emenda TEXT NOT NULL,
                    ano INTEGER NOT NULL,
                    municipio TEXT NOT NULL,
                    objeto TEXT,
                    valor_empenhado NUMERIC(12, 2) DEFAULT 0,
                    valor_pago NUMERIC(12, 2) DEFAULT 0,
                    situacao TEXT DEFAULT 'Aguardando',
                    observacoes TEXT,
                    versao INTEGER DEFAULT 1,
                    atualizado_por TEXT,
                    atualizado_em TEXT
                )
            ''')
            
            # Migrações: adiciona as novas colunas se não existirem
            novas_colunas = [
                ('secretaria', 'TEXT'),
                ('lider', 'TEXT'),
                ('oficio', 'TEXT'),
                ('referencia', 'TEXT'),
                ('entidade', 'TEXT'),
                ('cnpj', 'TEXT'),
                ('regiao', 'TEXT'),
                ('numero_e', 'TEXT')
            ]
            for col, tipo in novas_colunas:
                cur.execute(f"ALTER TABLE emendas ADD COLUMN IF NOT EXISTS {col} {tipo}")
                
        conn.commit()
        print("Banco inicializado/migrado com sucesso.")
    finally:
        conn.close()

# Inicializa o banco ao importar
init_db()

@app.errorhandler(Exception)
def handle_exception(e):
    if request.path.startswith('/api/'):
        return jsonify({'erro': str(e), 'tipo': type(e).__name__}), 500
    return str(e), 500

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/favicon.ico')
def favicon():
    return '', 204

@app.route('/api/emendas', methods=['GET'])
def listar_emendas():
    q = request.args.get('q', '').strip()
    municipio = request.args.get('municipio', '').strip()
    situacao = request.args.get('situacao', '').strip()
    ano = request.args.get('ano', '').strip()

    sql = 'SELECT * FROM emendas WHERE 1=1'
    params = []
    if q:
        sql += ' AND (numero_emenda ILIKE %s OR objeto ILIKE %s OR municipio ILIKE %s OR entidade ILIKE %s OR lider ILIKE %s)'
        like = f'%{q}%'
        params += [like, like, like, like, like]
    if municipio:
        sql += ' AND municipio = %s'
        params.append(municipio)
    if situacao:
        sql += ' AND situacao = %s'
        params.append(situacao)
    if ano:
        sql += ' AND ano = %s'
        params.append(ano)
    sql += ' ORDER BY ano DESC, id DESC'

    db = get_db()
    with db.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    return jsonify([dict(r) for r in rows])

@app.route('/api/emendas/<int:eid>', methods=['GET'])
def obter_emenda(eid):
    db = get_db()
    with db.cursor() as cur:
        cur.execute('SELECT * FROM emendas WHERE id = %s', (eid,))
        row = cur.fetchone()
    if not row:
        abort(404)
    return jsonify(dict(row))

@app.route('/api/emendas', methods=['POST'])
def criar_emenda():
    d = request.get_json(silent=True) or {}
    obrigatorios = ['numero_emenda', 'ano', 'municipio']
    for campo in obrigatorios:
        if not str(d.get(campo, '')).strip():
            return jsonify({'erro': f'Campo obrigatorio ausente: {campo}'}), 400

    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute('''
                INSERT INTO emendas
                  (numero_emenda, ano, municipio, objeto, valor_empenhado, valor_pago, situacao, observacoes,
                   secretaria, lider, oficio, referencia, entidade, cnpj, regiao, numero_e,
                   atualizado_por, atualizado_em)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'gabinete', %s)
                RETURNING id
            ''', (
                d['numero_emenda'].strip(), int(d['ano']), d['municipio'].strip(), (d.get('objeto') or '').strip(),
                float(d.get('valor_empenhado') or 0), float(d.get('valor_pago') or 0), d.get('situacao', 'Aguardando'), (d.get('observacoes') or '').strip(),
                (d.get('secretaria') or '').strip(), (d.get('lider') or '').strip(), (d.get('oficio') or '').strip(),
                (d.get('referencia') or '').strip(), (d.get('entidade') or '').strip(), (d.get('cnpj') or '').strip(),
                (d.get('regiao') or '').strip(), (d.get('numero_e') or '').strip(),
                datetime.now().isoformat(timespec='seconds'),
            ))
            new_id = cur.fetchone()['id']
        db.commit()
        return jsonify({'id': new_id, 'mensagem': 'Emenda criada'}), 201
    except Exception as e:
        db.rollback()
        return jsonify({'erro': str(e), 'tipo': type(e).__name__}), 500

@app.route('/api/emendas/<int:eid>', methods=['PUT'])
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
                  numero_emenda = %s, ano = %s, municipio = %s, objeto = %s, valor_empenhado = %s, valor_pago = %s,
                  situacao = %s, observacoes = %s, secretaria = %s, lider = %s, oficio = %s, referencia = %s,
                  entidade = %s, cnpj = %s, regiao = %s, numero_e = %s, versao = versao + 1, atualizado_por = 'gabinete', atualizado_em = %s
                WHERE id = %s
            ''', (
                d.get('numero_emenda', row['numero_emenda']), int(d.get('ano') or row['ano']), d.get('municipio', row['municipio']),
                (d.get('objeto') or '').strip(), float(d.get('valor_empenhado') or 0), float(d.get('valor_pago') or 0),
                d.get('situacao', 'Aguardando'), (d.get('observacoes') or '').strip(),
                (d.get('secretaria') or '').strip(), (d.get('lider') or '').strip(), (d.get('oficio') or '').strip(),
                (d.get('referencia') or '').strip(), (d.get('entidade') or '').strip(), (d.get('cnpj') or '').strip(),
                (d.get('regiao') or '').strip(), (d.get('numero_e') or '').strip(),
                datetime.now().isoformat(timespec='seconds'), eid,
            ))
        db.commit()
        return jsonify({'ok': True})
    except Exception as e:
        db.rollback()
        return jsonify({'erro': str(e), 'tipo': type(e).__name__}), 500

@app.route('/api/emendas/<int:eid>', methods=['DELETE'])
def excluir_emenda(eid):
    db = get_db()
    with db.cursor() as cur:
        cur.execute('DELETE FROM emendas WHERE id = %s', (eid,))
    db.commit()
    return jsonify({'ok': True})

@app.route('/api/filtros', methods=['GET'])
def filtros():
    db = get_db()
    with db.cursor() as cur:
        cur.execute('SELECT DISTINCT municipio FROM emendas ORDER BY municipio')
        municipios = [r['municipio'] for r in cur.fetchall() if r['municipio']]
        cur.execute('SELECT DISTINCT ano FROM emendas ORDER BY ano DESC')
        anos = [r['ano'] for r in cur.fetchall() if r['ano']]
    return jsonify({'municipios': municipios, 'anos': anos, 'situacoes': SITUACOES})

if __name__ == '__main__':
    app.run(debug=True)
