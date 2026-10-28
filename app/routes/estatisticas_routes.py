from datetime import datetime

from flask import Blueprint, request, jsonify

from ..database import get_db
from ..auth import login_obrigatorio
from ..utils import _dias_desde

bp = Blueprint('estatisticas', __name__, url_prefix='/api')


@bp.route('/estatisticas', methods=['GET'])
@login_obrigatorio
def estatisticas():
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
