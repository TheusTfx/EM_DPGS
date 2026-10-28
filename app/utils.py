from datetime import datetime


def _dias_desde(iso):
    if not iso:
        return None
    try:
        d = datetime.fromisoformat(str(iso)[:10]).date()
        return (datetime.now().date() - d).days
    except Exception:
        return None


def serializar_emenda(row):
    d = dict(row)
    d['valor_empenhado'] = float(d.get('valor_empenhado') or 0)
    d['valor_pago'] = float(d.get('valor_pago') or 0)
    d['dias_parada'] = _dias_desde(d.get('atualizado_em'))
    d['situacao_data'] = d.get('atualizado_em')
    return d
