import hashlib
import os
import re
import unicodedata
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
NSC = "não consta na planilha"
PREFIXO_OBS = "Situação (planilha):"

# Cabeçalhos (em MAIÚSCULAS) -> campo do banco. Serve para todas as abas.
MAPA_COLUNAS = {
    "SITUAÇÃO":      "situacao_bruta",
    "MUNICÍPIO":     "municipio",
    "SECRETARIA":    "secretaria",
    "SEC":           "secretaria",
    "Nº E":          "numero_emenda",
    "Nº P":          "numero_emenda",   # 2025: nº do processo = nº da emenda
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

# tem_situacao=False: a aba não traz a coluna SITUAÇÃO (2024/2025).
# Nesses casos a reimportação NÃO mexe em situação/observações já existentes.
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

# Município -> Região (COREDES RS). Mesmo mapa usado no formulário.
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
    "TRABALHISTA DO PLANALTO": ["PASSO FUNDO", "CARAZINHO", "TAPEJARA", "CAMPO NOVO", "CIRÍACO",
                                "COXILHA", "SANTA CECÍLIA DO SUL", "NÃO-ME-TOQUE"],
    "ZONA SUL": ["PELOTAS", "RIO GRANDE", "CAMAQUÃ", "CANGUÇU", "SÃO JOSÉ DO NORTE", "CRISTAL",
                 "TAPES", "ARAMBARÉ", "DOM FELICIANO", "SENTINELA DO SUL", "CHUVISCA"],
    "FRONTEIRA OESTE": ["URUGUAIANA", "ALEGRETE", "SÃO BORJA", "ITAQUI", "BARRA DO QUARAÍ",
                        "QUARAÍ", "MANOEL VIANA", "MAÇAMBARÁ"],
    "FRONTEIRA NOROESTE - PAULO MADEIRA": ["SANTA ROSA", "SANTO CRISTO", "GIRUÁ", "TRÊS DE MAIO",
                                           "TUPARENDI", "BOA VISTA DO BURICÁ", "NOVO MACHADO"],
    "FRONTEIRA SUDESTE": ["BAGÉ", "DOM PEDRITO", "HERVAL", "PEDRAS ALTAS", "PINHEIRO MACHADO",
                          "ACEGUÁ", "CANDIOTA", "HULHA NEGRA"],
    "VALE DO JACUÍ": ["CACHOEIRA DO SUL", "RIO PARDO", "SOBRADINHO", "CERRO BRANCO",
                      "NOVO CABRAIS", "PANTANO GRANDE", "AGUDO", "PARAÍSO DO SUL"],
    "GRANDE CAXIAS": ["CAXIAS DO SUL", "FLORES DA CUNHA", "SÃO MARCOS", "NOVA PÁDUA", "FARROUPILHA"],
    "JOSÉ AMÉRICO FREIRE": ["SÃO JERÔNIMO", "CHARQUEADAS", "ARROIO DOS RATOS", "ELDORADO DO SUL"],
    "VALE DO ALTO TAQUARI": ["LAJEADO", "ARROIO DO MEIO", "ROCA SALES", "TRAVESSEIRO", "CAPITÃO",
                             "POUSO NOVO", "PROGRESSO", "FORQUETINHA"],
    "ALTO DA SERRA DO BOTUCARAÍ": ["SOLEDADE", "ESPUMOSO", "FONTOURA XAVIER", "NOVA PALMA", "TUNAS"],
    "GRANDE SANTA MARIA": ["SANTA MARIA", "JÚLIO DE CASTILHOS", "SÃO PEDRO DO SUL",
                           "RESTINGA SÉCA", "TOROPI", "SILVEIRA MARTINS"],
    "ALTO DA SERRA": ["VACARIA", "BOM JESUS", "MONTE ALEGRE DOS CAMPOS", "CAMPESTRE DA SERRA",
                      "SÃO JOSÉ DOS AUSENTES", "JAQUIRANA"],
    "MEDIO ALTO URUGUAI – JOÃO GOULART": ["VICENTE DUTRA", "SÃO PEDRO DAS MISSÕES", "TRINDADE DO SUL"],
    "GRANDE LAGOA": ["OSÓRIO", "TRAMANDAÍ", "IMBÉ", "XANGRI-LÁ", "MOSTARDAS", "PALMARES DO SUL",
                     "CIDREIRA", "CAPIVARI DO SUL"],
    "LITORAL NORTE": ["TORRES", "ARROIO DO SAL", "DOM PEDRO DE ALCÂNTARA", "TRÊS CACHOEIRAS",
                      "MAQUINÉ", "MORRINHOS DO SUL"],
    "VALE DO PARANHANA": ["TAQUARA", "IGREJINHA", "PAROBÉ", "ROLANTE", "TRÊS COROAS",
                          "SANTA MARIA DO HERVAL"],
    "MILTON GARCIA DUTRA": ["RONDA ALTA", "LIBERATO SALZANO"],
    "METROPOLITANO DELTA DO JACUÍ": ["PORTO ALEGRE", "GRAVATAÍ", "VIAMÃO", "ALVORADA"],
    "VALE DO RIO DOS SINOS": ["NOVO HAMBURGO", "SÃO LEOPOLDO", "ESTEIO"],
    "SERRA": ["GRAMADO", "CANELA", "NOVA PETRÓPOLIS"],
}


def _sem_acento(s):
    s = unicodedata.normalize('NFD', str(s))
    return ''.join(c for c in s if unicodedata.category(c) != 'Mn').upper().strip()


# chave sem acento -> região (assim "CATUIPE" e "CATUIPÉ" funcionam igual)
MAPA_REGIOES = {_sem_acento(m): reg for reg, muns in _REGIOES.items() for m in muns}


def _regiao_do_mapa(municipio):
    return MAPA_REGIOES.get(_sem_acento(municipio))


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
    """Só 'PAGO' vira Pago. Todo o resto (inclusive texto de acompanhamento) é Aguardando.
    'Cancelada' continua existindo, mas só por edição manual."""
    if texto_bruto and re.match(r'^\s*PAGO\b', str(texto_bruto).upper()):
        return "Pago"
    return "Aguardando"


def _codigo_sem_numero(ano, municipio, lider, objeto, valor, secretaria, ocorrencia):
    base = '|'.join([str(ano), _sem_acento(municipio), _sem_acento(lider or ''),
                     _sem_acento(objeto or ''), f'{valor:.2f}', _sem_acento(secretaria or '')])
    cod = 'S/N-' + hashlib.sha1(base.encode('utf-8')).hexdigest()[:8].upper()
    return cod if ocorrencia == 1 else f'{cod}-{ocorrencia}'


def _processar_dataframe(aba):
    cfg = ABAS_CONFIGURADAS[aba]

    arquivo = request.files.get('arquivo')
    if not arquivo or arquivo.filename == '':
        raise ValueError("Nenhum arquivo enviado")

    df = pd.read_excel(BytesIO(arquivo.read()), sheet_name=aba, engine='openpyxl')
    df.columns = [' '.join(str(c).split()).upper() for c in df.columns]
    df = df.rename(columns=MAPA_COLUNAS)
    df = df.dropna(how='all')

    if 'municipio' not in df.columns:
        raise ValueError("Coluna obrigatória ausente na planilha: MUNICÍPIO")

    registros = []
    ignoradas = 0
    resumo = {
        'pagas': 0, 'aguardando': 0, 'sem_numero': 0,
        'nao_consta': {c: 0 for c in CAMPOS_TEXTO},
    }
    ocorrencias = {}
    agora = datetime.now().isoformat(timespec='seconds')

    for _, row in df.iterrows():
        municipio = _txt(row.get('municipio'))
        if not municipio:
            ignoradas += 1
            continue

        ano_val = _ano(row.get('ano')) or int(aba)   # 2025 vem sem ANO -> usa o nome da aba
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
            chave = (ano_val, municipio, campos['lider'], campos['objeto'], valor, campos['secretaria'])
            ocorrencias[chave] = ocorrencias.get(chave, 0) + 1
            numero = _codigo_sem_numero(ano_val, municipio, campos['lider'], campos['objeto'],
                                        valor, campos['secretaria'], ocorrencias[chave])

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
            'objeto': campos['objeto'], 'valor_empenhado': valor, 'valor_pago': valor_pago,
            'situacao': situacao, 'secretaria': campos['secretaria'], 'lider': campos['lider'],
            'oficio': campos['oficio'], 'referencia': campos['referencia'],
            'entidade': campos['entidade'], 'cnpj': campos['cnpj'], 'regiao': campos['regiao'],
            'justificativa': campos['justificativa'], 'situacao_bruta': situacao_bruta,
            'observacoes': observacoes, 'atualizado_em': agora,
        })

    return registros, ignoradas, resumo


# Remove a linha "Situação (planilha): ..." antiga antes de gravar a nova,
# preservando qualquer outra observação digitada à mão.
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
    # "não consta na planilha" nunca apaga um dado já preenchido no sistema
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
            'amostra': [
                {
                    'numero_emenda': r['numero_emenda'], 'ano': r['ano'],
                    'municipio': r['municipio'], 'valor_empenhado': r['valor_empenhado'],
                    'situacao': r['situacao'], 'observacoes': r['observacoes'],
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

        return jsonify({
            'ok': True,
            'aba': aba,
            'importadas': len(registros),
            'ignoradas': ignoradas,
            'sem_numero': resumo['sem_numero'],
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'erro': str(e), 'tipo': type(e).__name__}), 500


if __name__ == '__main__':
    app.run(debug=True)
