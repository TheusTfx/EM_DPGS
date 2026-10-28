from flask import Blueprint, request, jsonify

from ..database import get_db
from ..auth import login_obrigatorio

bp = Blueprint('logs', __name__, url_prefix='/api')


@bp.route('/logs', methods=['GET'])
@login_obrigatorio
def listar():
    q = request.args.get('q', '').strip()
    usuario = request.args.get('usuario', '').strip()
    acao = request.args.get('acao', '').strip()
    emenda_id = request.args.get('emenda_id', '').strip()
    limite = int(request.args.get('limite', 50))
    offset = int(request.args.get('offset', 0))

    where, params = '1=1', []
    if q:
        like = f'%{q}%'
        where += ' AND (numero_emenda ILIKE %s OR municipio ILIKE %s OR detalhe ILIKE %s)'
        params += [like, like, like]
    if usuario:
        where += ' AND usuario = %s'; params.append(usuario)
    if acao:
        where += ' AND acao = %s'; params.append(acao)
    if emenda_id:
        where += ' AND emenda_id = %s'; params.append(int(emenda_id))

    db = get_db()
    with db.cursor() as cur:
        cur.execute(f'SELECT COUNT(*) AS n FROM logs WHERE {where}', params)
        total = cur.fetchone()['n']
        cur.execute(f'SELECT * FROM logs WHERE {where} ORDER BY id DESC LIMIT %s OFFSET %s',
                    params + [limite, offset])
        itens = cur.fetchall()
        cur.execute('SELECT DISTINCT usuario FROM logs WHERE usuario IS NOT NULL ORDER BY usuario')
        usuarios = [r['usuario'] for r in cur.fetchall()]

    for it in itens:
        it['mudancas'] = it['mudancas'] or []
    return jsonify(itens=[dict(i) for i in itens], total=total, usuarios=usuarios)
