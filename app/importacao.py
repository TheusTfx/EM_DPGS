import hashlib
import re
from datetime import datetime
from io import BytesIO

import pandas as pd

from .config import NSC, PREFIXO_OBS
from .regioes import _sem_acento, _regiao_do_mapa


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


def _processar_dataframe(aba, conteudo):
    cfg = ABAS_CONFIGURADAS[aba]
    if not conteudo:
        raise ValueError("Nenhum arquivo enviado")

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
