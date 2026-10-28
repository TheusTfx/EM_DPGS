from functools import wraps
from flask import request, jsonify

from .database import get_db


def usuario_atual():
    h = request.headers.get('Authorization', '')
    if not h.startswith('Bearer '):
        return None
    token = h[7:]
    db = get_db()
    with db.cursor() as cur:
        cur.execute('''
            SELECT u.id, u.nome, u.usuario, u.admin
            FROM sessoes s JOIN usuarios u ON u.id = s.usuario_id
            WHERE s.token = %s AND (s.expira_em IS NULL OR s.expira_em > NOW())
        ''', (token,))
        row = cur.fetchone()
    return dict(row) if row else None


def login_obrigatorio(f):
    @wraps(f)
    def w(*a, **k):
        if not usuario_atual():
            return jsonify({'erro': 'Não autorizado'}), 401
        return f(*a, **k)
    return w


def admin_obrigatorio(f):
    @wraps(f)
    def w(*a, **k):
        u = usuario_atual()
        if not u:
            return jsonify({'erro': 'Não autorizado'}), 401
        if not u.get('admin'):
            return jsonify({'erro': 'Apenas administradores'}), 403
        return f(*a, **k)
    return w
