# app/utils.py
from datetime import datetime

from .config import DATA_FORMAT, SITUACOES


def _dias_desde(iso):
    if not iso:
        return None
    try:
        d = datetime.fromisoformat(str(iso)[:10]).date()
        return (datetime.now().date() - d).days
    except Exception:
        return None


def fmt_brl(v):
    s = f'{float(v or 0):,.2f}'
    return 'R$ ' + s.replace(',', 'X').replace('.', ',').replace('X', '.')


def valida_data_iso(v):
    """True se vazio/None ou se está no formato YYYY-MM-DD."""
    if not v:
        return True
    try:
        datetime.strptime(str(v).strip(), DATA_FORMAT)
        return True
    except (ValueError, TypeError):
        return False


def valida_situacao(v):
    """True se vazio/None ou se está na lista SITUACOES."""
    if not v:
        return True
    return str(v).strip() in SITUACOES


def numero_display(numero_emenda, ano):
    """Se for S/N (sem número), exibe só o ano. Senão, o número original."""
    n = str(numero_emenda or '')
    if n.upper().startswith('S/N'):
        return str(ano or '')
    return n


def serializar_emenda(row):
    d = dict(row)
    d['valor_empenhado'] = float(d.get('valor_empenhado') or 0)
    d['valor_pago'] = float(d.get('valor_pago') or 0)
    d['dias_parada'] = _dias_desde(d.get('atualizado_em'))
    d['situacao_data'] = d.get('atualizado_em')
    d['numero_display'] = numero_display(d.get('numero_emenda'), d.get('ano'))
    return d
