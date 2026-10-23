import os
from datetime import datetime
from io import BytesIO

import pandas as pd
import psycopg2
from psycopg2.extras import RealDictCursor, execute_values
from flask import Flask, request, jsonify, render_template, g, abort

app = Flask(__name__)

DATABASE_URL = os.environ.get('DATABASE_URL')

# "Em execução" foi removida — só Aguardando, Empenhado, Pago, Cancelada
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

            novas_colunas = [
                ('secretaria', 'TEXT'),
                ('lider', 'TEXT'),
                ('oficio', 'TEXT'),
                ('referencia', 'TEXT'),
                ('entidade', 'TEXT'),
                ('cnpj', 'TEXT'),
                ('regiao', 'TEXT'),
                ('numero_e', 'TEXT'),
                ('justificativa', 'TEXT'),
                ('situacao_bruta', 'TEXT'),
            ]
            for col, tipo in novas_colunas:
                cur.execute(f"ALTER TABLE emendas ADD COLUMN IF NOT EXISTS {col} {tipo}")

            cur.execute("""
                SELECT 1 FROM pg_constraint WHERE conname = 'emendas_ano_numero_key'
            """)
            if not cur.fetchone():
                cur.execute("SAVEPOINT add_unique")
                try:
                    cur.execute("""
                        ALTER TABLE emendas
                        ADD CONSTRAINT emendas_ano_numero_key UNIQUE (ano, numero_emenda)
                    """)
                    cur.execute("RELEASE SAVEPOINT add_unique")
                except psycopg2.errors.UniqueViolation:
                    cur.execute("ROLLBACK TO SAVEPOINT add_unique")
                    print("AVISO: duplicatas em (ano, numero_emenda). Constraint nao criada.")
                except psycopg2.errors.DuplicateObject:
                    cur.execute("ROLLBACK TO SAVEPOINT add_unique")

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
# ROTAS CRUD
# ============================================================
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
                   secretaria, lider, oficio, referencia, entidade, cnpj, regiao, numero_e, justificativa,
                   atualizado_por, atualizado_em)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'gabinete', %s)
                RETURNING id
            ''', (
                d['numero_emenda'].strip(), int(d['ano']), d['municipio'].strip(), (d.get('objeto') or '').strip(),
                float(d.get('valor_empenhado') or 0), float(d.get('valor_pago') or 0), d.get('situacao', 'Aguardando'), (d.get('observacoes') or '').strip(),
                (d.get('secretaria') or '').strip(), (d.get('lider') or '').strip(), (d.get('oficio') or '').strip(),
                (d.get('referencia') or '').strip(), (d.get('entidade') or '').strip(), (d.get('cnpj') or '').strip(),
                (d.get('regiao') or '').strip(), (d.get('numero_e') or '').strip(), (d.get('justificativa') or '').strip(),
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
                  entidade = %s, cnpj = %s, regiao = %s, numero_e = %s, justificativa = %s,
                  versao = versao + 1, atualizado_por = 'gabinete', atualizado_em = %s
                WHERE id = %s
            ''', (
                d.get('numero_emenda', row['numero_emenda']), int(d.get('ano') or row['ano']), d.get('municipio', row['municipio']),
                (d.get('objeto') or '').strip(), float(d.get('valor_empenhado') or 0), float(d.get('valor_pago') or 0),
                d.get('situacao', 'Aguardando'), (d.get('observacoes') or '').strip(),
                (d.get('secretaria') or '').strip(), (d.get('lider') or '').strip(), (d.get('oficio') or '').strip(),
                (d.get('referencia') or '').strip(), (d.get('entidade') or '').strip(), (d.get('cnpj') or '').strip(),
                (d.get('regiao') or '').strip(), (d.get('numero_e') or '').strip(), (d.get('justificativa') or '').strip(),
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


# ============================================================
# IMPORTAÇÃO
# ============================================================
MAPA_2026 = {
    "SITUAÇÃO":      "situacao_bruta",
    "MUNICÍPIO":     "municipio",
    "SECRETARIA":    "secretaria",
    "Nº E":          "numero_emenda",
    "VALOR":         "valor_empenhado",
    "OFÍCIO":        "oficio",
    "ANO":           "ano",
    "OBJETO":        "objeto",
    "LÍDER":         "lider",
    "REFERÊNCIA":    "referencia",
    "ENTIDADE":      "entidade",
    "CNPJ":          "cnpj",
    "REGIÃO":        "regiao",
    "JUSTIFICATIVA": "justificativa",
}

ABAS_CONFIGURADAS = {
    "2026": MAPA_2026,
}


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


def _derivar_situacao(texto_bruto):
    """Mapeia o texto livre da planilha para o ENUM da app.
    'Em execução' foi eliminada — tudo que não é Pago/Cancelada/Liquidada vira Aguardando.
    """
    if not texto_bruto:
        return "Aguardando"
    t = str(texto_bruto).upper()
    if "PAGO" in t:
        return "Pago"
    if "CANCEL" in t:
        return "Cancelada"
    if "LIQUIDA" in t:
        return "Empenhado"
    return "Aguardando"


def _processar_dataframe(aba):
    mapa = ABAS_CONFIGURADAS[aba]

    arquivo = request.files.get('arquivo')
    if not arquivo or arquivo.filename == '':
        raise ValueError("Nenhum arquivo enviado")

    df = pd.read_excel(BytesIO(arquivo.read()), sheet_name=aba, engine='openpyxl')
    df = df.rename(columns=mapa)

    for col in ('numero_emenda', 'ano', 'municipio'):
        if col not in df.columns:
            raise ValueError(f"Coluna obrigatória ausente na planilha: {col}")

    df = df.dropna(subset=['numero_emenda', 'ano', 'municipio'])

    registros = []
    ignoradas = 0
    for _, row in df.iterrows():
        try:
            numero = _txt(row['numero_emenda'])
            municipio = _txt(row['municipio'])
            try:
                ano_val = int(row['ano'])
            except (ValueError, TypeError):
                ignoradas += 1
                continue
            if not numero or not municipio:
                ignoradas += 1
                continue

            situacao_bruta = _txt(row.get('situacao_bruta'))
            situacao = _derivar_situacao(situacao_bruta)

            try:
                valor = float(row.get('valor_empenhado') or 0)
            except (ValueError, TypeError):
                valor = 0.0

            valor_pago = valor if situacao == 'Pago' else 0.0

            registros.append((
                numero,
                ano_val,
                municipio,
                _txt(row.get('objeto')),
                valor,
                valor_pago,
                situacao,
                _txt(row.get('secretaria')),
                _txt(row.get('lider')),
                _txt(row.get('oficio')),
                _txt(row.get('referencia')),
                _txt(row.get('entidade')),
                _txt(row.get('cnpj')),
                _txt(row.get('regiao')),
                _txt(row.get('justificativa')),
                situacao_bruta,
                datetime.now().isoformat(timespec='seconds'),
            ))
        except Exception:
            ignoradas += 1
            continue

    colunas = [
        'numero_emenda', 'ano', 'municipio', 'objeto',
        'valor_empenhado', 'valor_pago', 'situacao',
        'secretaria', 'lider', 'oficio', 'referencia',
        'entidade', 'cnpj', 'regiao', 'justificativa',
        'situacao_bruta', 'atualizado_em',
    ]
    return registros, colunas, ignoradas


@app.route('/api/importar/preview', methods=['POST'])
def importar_preview():
    aba = request.form.get('aba', '2026')
    if aba not in ABAS_CONFIGURADAS:
        return jsonify({'erro': f'Aba {aba} ainda não configurada'}), 400
    try:
        registros, _, ignoradas = _processar_dataframe(aba)
        return jsonify({
            'aba': aba,
            'total_linhas': len(registros),
            'ignoradas': ignoradas,
            'amostra': [
                {
                    'numero_emenda': r[0], 'ano': r[1], 'municipio': r[2],
                    'valor_empenhado': r[4], 'situacao_bruta': r[15], 'situacao': r[6],
                }
                for r in registros[:5]
            ],
        })
    except Exception as e:
        return jsonify({'erro': str(e), 'tipo': type(e).__name__}), 500


@app.route('/api/importar', methods=['POST'])
def importar():
    aba = request.form.get('aba', '2026')
    if aba not in ABAS_CONFIGURADAS:
        return jsonify({'erro': f'Aba {aba} ainda não configurada'}), 400

    try:
        registros, colunas, ignoradas = _processar_dataframe(aba)
        if not registros:
            return jsonify({'erro': 'Nenhuma linha válida para importar'}), 400

        colunas_sql = ', '.join(colunas)
        updates_normais = ', '.join(
            f'{c} = EXCLUDED.{c}' for c in colunas
            if c not in ('numero_emenda', 'ano', 'valor_pago')
        )
        updates_sql = (
            f"{updates_normais}, "
            "valor_pago = GREATEST(emendas.valor_pago, EXCLUDED.valor_pago), "
            "versao = emendas.versao + 1"
        )

        query = f"""
            INSERT INTO emendas ({colunas_sql})
            VALUES %s
            ON CONFLICT (ano, numero_emenda) DO UPDATE SET
                {updates_sql}
        """

        db = get_db()
        try:
            with db.cursor() as cur:
                execute_values(cur, query, registros, page_size=500)
            db.commit()
        except Exception:
            db.rollback()
            raise

        return jsonify({
            'ok': True,
            'aba': aba,
            'importadas': len(registros),
            'ignoradas': ignoradas,
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'erro': str(e), 'tipo': type(e).__name__}), 500


if __name__ == '__main__':
    app.run(debug=True)
