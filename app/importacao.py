# app/importacao.py
import hashlib
import re
import unicodedata
from datetime import datetime
from io import BytesIO

import pandas as pd

from .config import NSC, PREFIXO_OBS
from .regioes import _sem_acento, _regiao_do_mapa
from .utils import fmt_brl


class AbaAusente(ValueError):
    pass


def _norm_cab(c):
    s = str(c).replace('°', 'º')
    s = unicodedata.normalize('NFKD', s)
    s = ''.join(ch for ch in s if not unicodedata.combining(ch))
    return ' '.join(s.upper().split())


MAPA_COLUNAS = {
    "SITUAÇÃO": "situacao_bruta", "MUNICÍPIO": "municipio",
    "SECRETARIA": "secretaria", "SEC": "secretaria",
    "Nº E": "numero_emenda", "Nº P": "numero_emenda",
    "Nº EMENDA": "numero_emenda", "NÚMERO": "numero_emenda",
    "NÚMERO DA EMENDA": "numero_emenda",
    "VALOR": "valor_empenhado", "VALOR DA EMENDA": "valor_empenhado",
    "OFÍCIO": "oficio", "ANO": "ano",
    "OBJETO": "objeto", "LÍDER": "lider", "REFERÊNCIA": "referencia",
    "ENTIDADE": "entidade", "CNPJ": "cnpj", "REGIÃO": "regiao",
    "JUSTIFICATIVA": "justificativa",
}
MAPA_NORM = {_norm_cab(k): v for k, v in MAPA_COLUNAS.items()}

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

ROTULOS = {
    'municipio': 'Município', 'valor_empenhado': 'Valor da emenda',
    'valor_pago': 'Valor pago', 'situacao': 'Situação',
    'situacao_bruta': 'Situação (planilha)', 'objeto': 'Objeto',
    'secretaria': 'Secretaria', 'lider': 'Líder', 'oficio': 'Ofício',
    'referencia': 'Referência', 'entidade': 'Entidade', 'cnpj': 'CNPJ',
    'regiao': 'Região', 'justificativa': 'Justificativa',
}


# ---------- Conversões ----------
def _vazio(v):
    if v is None:
        return True
    try:
        if pd.isna(v):
            return True
    except (TypeError, ValueError):
        pass
    return isinstance(v, str) and not v.strip()


def _txt(v):
    if _vazio(v):
        return None
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, (int, float)):
        fv = float(v)
        return str(int(fv)) if fv.is_integer() else str(fv)
    s = str(v).strip()
    return s if s else None


def _valor_checado(v):
    """Retorna (valor, ok). ok=False quando o texto não é um número."""
    if _vazio(v):
        return 0.0, True
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v), True
    s = str(v).replace('R$', '').replace('\xa0', ' ').strip().replace(' ', '')
    # "1.234" ou "1.234.567,89" -> ponto é separador de milhar
    if re.fullmatch(r'-?\d{1,3}(\.\d{3})+(,\d+)?', s):
        s = s.replace('.', '').replace(',', '.')
    elif ',' in s:
        s = s.replace('.', '').replace(',', '.')
    try:
        return float(s), True
    except ValueError:
        return 0.0, False


def _valor(v):
    return _valor_checado(v)[0]


def _ano(v):
    try:
        if _vazio(v):
            return None
        return int(float(v))
    except (ValueError, TypeError):
        return None


def _derivar_situacao(texto_bruto):
    """Traduz situação bruta da planilha para uma das SITUACOES canônicas.
    Antes só reconhecia PAGO; agora também CANCELADA e EMPENHADO."""
    if not texto_bruto:
        return "Aguardando"
    t = str(texto_bruto).upper().strip()
    if re.match(r'^PAGO\b', t):
        return "Pago"
    if 'CANCELAD' in t:
        return "Cancelada"
    if 'EMPENHAD' in t:
        return "Empenhado"
    return "Aguardando"


def _codigo_sem_numero(ano, municipio, lider, objeto, valor, secretaria, ocorrencia):
    base = '|'.join([str(ano), _sem_acento(municipio), _sem_acento(lider or ''),
                     _sem_acento(objeto or ''), f'{valor:.2f}',
                     _sem_acento(secretaria or '')])
    cod = 'S/N-' + hashlib.sha1(base.encode('utf-8')).hexdigest()[:8].upper()
    return cod if ocorrencia == 1 else f'{cod}-{ocorrencia}'


# ---------- Leitura da planilha ----------
def _ler_planilha(aba, conteudo):
    """Retorna (nomes_presentes, [(linha_excel, dict), ...])."""
    try:
        raw = pd.read_excel(BytesIO(conteudo), sheet_name=aba, header=None,
                            dtype=object, engine='openpyxl')
    except ValueError as e:
        if 'not found' in str(e).lower() or 'worksheet' in str(e).lower():
            raise AbaAusente(f'Aba "{aba}" não encontrada na planilha')
        raise ValueError('Não foi possível ler o arquivo. Confirme que é um .xlsx válido.')
    except Exception:
        raise ValueError('Não foi possível ler o arquivo. Confirme que é um .xlsx válido.')

    header_idx = None
    for i in range(min(15, len(raw))):
        celulas = [_norm_cab(x) for x in raw.iloc[i].tolist() if not _vazio(x)]
        if 'MUNICIPIO' in celulas:
            header_idx = i
            break
    if header_idx is None:
        raise ValueError(f'Aba {aba}: coluna MUNICÍPIO não encontrada nas primeiras linhas')

    nomes = [None if _vazio(x) else MAPA_NORM.get(_norm_cab(x))
             for x in raw.iloc[header_idx].tolist()]
    presentes = {n for n in nomes if n}

    linhas = []
    for i in range(header_idx + 1, len(raw)):
        d = {}
        for nome, v in zip(nomes, raw.iloc[i].tolist()):
            if nome is None:
                continue
            if nome not in d or _vazio(d[nome]):
                d[nome] = v
        if all(_vazio(v) for v in d.values()):
            continue
        linhas.append((i + 1, d))
    return presentes, linhas


def _processar_dataframe(aba, conteudo):
    """Retorna (registros, ignoradas, resumo).
    ignoradas = [{'linha': n, 'motivo': texto}]"""
    cfg = ABAS_CONFIGURADAS[aba]
    if not conteudo:
        raise ValueError("Nenhum arquivo enviado")

    presentes, linhas = _ler_planilha(aba, conteudo)

    avisos = []
    if 'numero_emenda' not in presentes:
        avisos.append('Coluna do nº da emenda não encontrada: todas receberão código S/N')
    if 'valor_empenhado' not in presentes:
        avisos.append('Coluna VALOR não encontrada: valores serão R$ 0,00')

    ignoradas = []
    registros = []
    ocorrencias = {}
    valor_zerado = 0
    agora = datetime.now().isoformat(timespec='seconds')

    for linha, d in linhas:
        municipio = _txt(d.get('municipio'))
        if not municipio:
            ignoradas.append({'linha': linha, 'motivo': 'município vazio'})
            continue
        if municipio.upper() in ('TOTAL', 'TOTAIS', 'SUBTOTAL'):
            ignoradas.append({'linha': linha, 'motivo': 'linha de total'})
            continue

        ano_row = _ano(d.get('ano'))
        if ano_row is None or not (2000 <= ano_row <= 2100):
            ano_val = int(aba)
        else:
            ano_val = ano_row
            if ano_row != int(aba):
                avisos.append(f'Linha {linha}: ano {ano_row} diferente da aba {aba}')

        valor, ok = _valor_checado(d.get('valor_empenhado'))
        if not ok:
            avisos.append(f"Linha {linha}: valor inválido ('{_txt(d.get('valor_empenhado'))}'), assumido R$ 0,00")
        elif valor == 0:
            valor_zerado += 1

        campos = {}
        for c in CAMPOS_TEXTO:
            if c == 'regiao':
                v = _txt(d.get('regiao')) or _regiao_do_mapa(municipio)
            else:
                v = _txt(d.get(c))
            campos[c] = v or NSC

        numero = _txt(d.get('numero_emenda'))
        if not numero:
            chave = (ano_val, municipio, campos['lider'], campos['objeto'],
                     valor, campos['secretaria'])
            ocorrencias[chave] = ocorrencias.get(chave, 0) + 1
            numero = _codigo_sem_numero(ano_val, municipio, campos['lider'],
                                        campos['objeto'], valor,
                                        campos['secretaria'], ocorrencias[chave])

        situacao_bruta = _txt(d.get('situacao_bruta')) if cfg['tem_situacao'] else None
        situacao = _derivar_situacao(situacao_bruta)
        valor_pago = valor if situacao == 'Pago' else 0.0
        observacoes = None
        if situacao != 'Pago' and situacao_bruta:
            observacoes = f"{PREFIXO_OBS} {situacao_bruta}"

        registros.append({
            'linha': linha,
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

    if valor_zerado:
        avisos.append(f'{valor_zerado} linha(s) com valor zerado ou vazio')

    # Mesmo (ano, nº) repetido na planilha derrubaria o upsert: vale a última linha
    grupos = {}
    for r in registros:
        grupos.setdefault((r['ano'], r['numero_emenda']), []).append(r)
    finais = []
    duplicadas = 0
    for (ano, numero), grupo in grupos.items():
        if len(grupo) > 1:
            duplicadas += len(grupo) - 1
            avisos.append(f"Nº {numero}/{ano} repetido nas linhas "
                          f"{', '.join(str(g['linha']) for g in grupo)}: valeu a última")
        finais.append(grupo[-1])

    resumo = {
        'pagas': sum(1 for r in finais if r['situacao'] == 'Pago'),
        'aguardando': sum(1 for r in finais if r['situacao'] != 'Pago'),
        'sem_numero': sum(1 for r in finais if str(r['numero_emenda']).startswith('S/N-')),
        'nao_consta': {c: sum(1 for r in finais if r[c] == NSC) for c in CAMPOS_TEXTO},
        'avisos': avisos,
        'duplicadas': duplicadas,
    }
    return finais, ignoradas, resumo


# ---------- Comparação com o banco ----------
def _linhas_dict(cur):
    cols = [d[0] for d in cur.description]
    return [r if isinstance(r, dict) else dict(zip(cols, r)) for r in cur.fetchall()]


def _mud(campo, de, para):
    return {'campo': ROTULOS.get(campo, campo), 'de': de, 'para': para}


def comparar_com_banco(cur, aba, registros):
    """Reproduz em Python o que o upsert faria. Retorna (resumo, a_gravar):
    a_gravar = só as linhas novas ou realmente alteradas."""
    tem_sit = ABAS_CONFIGURADAS[aba]['tem_situacao']
    anos = sorted({r['ano'] for r in registros})
    existentes = {}
    if anos:
        cur.execute(
            "SELECT ano, numero_emenda, municipio, valor_empenhado, valor_pago, "
            "situacao, situacao_bruta, " + ', '.join(CAMPOS_TEXTO) +
            " FROM emendas WHERE ano = ANY(%s)", (anos,))
        for ex in _linhas_dict(cur):
            existentes[(ex['ano'], ex['numero_emenda'])] = ex

    novas, alteradas, a_gravar, iguais = [], [], [], 0
    for r in registros:
        ex = existentes.get((r['ano'], r['numero_emenda']))
        if ex is None:
            novas.append(r)
            a_gravar.append(r)
            continue

        mud = []
        if (ex['municipio'] or '') != r['municipio']:
            mud.append(_mud('municipio', ex['municipio'], r['municipio']))

        ve_antigo = round(float(ex['valor_empenhado'] or 0), 2)
        if ve_antigo != round(r['valor_empenhado'], 2):
            mud.append(_mud('valor_empenhado', fmt_brl(ve_antigo), fmt_brl(r['valor_empenhado'])))

        vp_antigo = round(float(ex['valor_pago'] or 0), 2)
        vp_novo = max(vp_antigo, round(r['valor_pago'], 2))
        if vp_novo != vp_antigo:
            mud.append(_mud('valor_pago', fmt_brl(vp_antigo), fmt_brl(vp_novo)))

        for c in CAMPOS_TEXTO:
            antigo = ex[c] or NSC
            novo = r[c]
            if novo == NSC:
                novo = antigo  # planilha sem informação: mantém o que já existe
            if novo != antigo:
                mud.append(_mud(c, None if antigo == NSC else antigo, novo))

        if tem_sit:
            if ex['situacao'] != 'Cancelada' and ex['situacao'] != r['situacao']:
                mud.append(_mud('situacao', ex['situacao'], r['situacao']))
            if (ex['situacao_bruta'] or None) != r['situacao_bruta']:
                mud.append(_mud('situacao_bruta', ex['situacao_bruta'], r['situacao_bruta']))

        if mud:
            alteradas.append({'numero': r['numero_emenda'], 'municipio': r['municipio'],
                              'ano': r['ano'], 'mudancas': mud})
            a_gravar.append(r)
        else:
            iguais += 1

    resumo = {
        'novas': len(novas),
        'alteradas': len(alteradas),
        'iguais': iguais,
        'exemplos_novas': [{'numero': r['numero_emenda'], 'municipio': r['municipio'],
                            'valor': r['valor_empenhado']} for r in novas[:15]],
        'lista_alteradas': alteradas[:200],
    }
    return resumo, a_gravar


# ---------- Upsert ----------
_SQL_OBS_SEM_LINHA_ANTIGA = (
    r"NULLIF(BTRIM(regexp_replace(COALESCE(emendas.observacoes, ''), "
    r"'(^|\n)Situação \(planilha\):[^\n]*', '', 'g'), ' ' || chr(10)), '')"
)


def _montar_upsert(tem_situacao, returning=False):
    sets = [
        "municipio = EXCLUDED.municipio",
        "valor_empenhado = EXCLUDED.valor_empenhado",
        "atualizado_em = EXCLUDED.atualizado_em",
    ]
    for c in CAMPOS_TEXTO:
        # NSC vindo da planilha não sobrescreve o que já existe no banco
        sets.append(
            f"{c} = CASE WHEN EXCLUDED.{c} = '{NSC}' "
            f"THEN COALESCE(NULLIF(emendas.{c}, ''), EXCLUDED.{c}) "
            f"ELSE EXCLUDED.{c} END"
        )
    if tem_situacao:
        # Cancelada nunca é revertida por importação; observações antigas de
        # "Situação (planilha)" são limpas antes de concatenar a nova
        sets += [
            "situacao = CASE WHEN emendas.situacao = 'Cancelada' "
            "THEN emendas.situacao ELSE EXCLUDED.situacao END",
            "situacao_bruta = EXCLUDED.situacao_bruta",
            "observacoes = NULLIF(BTRIM(CONCAT_WS(chr(10), "
            f"{_SQL_OBS_SEM_LINHA_ANTIGA}, EXCLUDED.observacoes), ' ' || chr(10)), '')",
        ]
    sets += [
        # Nunca reduz o valor pago já registrado
        "valor_pago = GREATEST(emendas.valor_pago, EXCLUDED.valor_pago)",
        "versao = emendas.versao + 1",
    ]
    sql = (
        f"INSERT INTO emendas ({', '.join(COLUNAS_INSERT)}) VALUES %s "
        f"ON CONFLICT (ano, numero_emenda) DO UPDATE SET {', '.join(sets)}"
    )
    if returning:
        sql += " RETURNING (xmax = 0) AS inserido"
    return sql
