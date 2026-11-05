from functools import wraps
from flask import request, jsonify, g

from .database import get_db


def token_atual():
    h = request.headers.get('Authorization', '')
    return h[7:].strip() if h.startswith('Bearer ') else None


def _carregar_usuario():
    token = token_atual()
    if not token:
        return None
    db = get_db()
    with db.cursor() as cur:
        cur.execute('''
            SELECT u.id, u.nome, u.usuario, u.admin,
                   COALESCE(u.deve_trocar_senha, false) AS deve_trocar_senha
            FROM sessoes s JOIN usuarios u ON u.id = s.usuario_id
            WHERE s.token = %s
              AND (s.expira_em IS NULL OR s.expira_em > NOW())
              AND COALESCE(u.ativo, true)
        ''', (token,))
        row = cur.fetchone()
    return dict(row) if row else None


def usuario_atual():
    if 'usuario_atual' not in g:
        g.usuario_atual = _carregar_usuario()
    return g.usuario_atual


def log_seguro(acao, detalhe):
    """Registra no log de auditoria sem nunca quebrar a requisição."""
    try:
        from .log import registrar_log
        registrar_log(acao, detalhe=detalhe)
    except Exception as e:
        print('AVISO: falha ao registrar log:', e)
        try:
            get_db().rollback()
        except Exception:
            pass


def _protegido(admin=False, permite_troca=False):
    def deco(f):
        @wraps(f)
        def w(*a, **k):
            u = usuario_atual()
            if not u:
                return jsonify({'erro': 'Não autorizado'}), 401
            if u['deve_trocar_senha'] and not permite_troca:
                return jsonify({'erro': 'Defina uma nova senha antes de continuar',
                                'trocar_senha': True}), 403
            if admin and not u.get('admin'):
                return jsonify({'erro': 'Apenas administradores'}), 403
            return f(*a, **k)
        return w
    return deco


login_obrigatorio = _protegido()
login_sem_troca = _protegido(permite_troca=True)
admin_obrigatorio = _protegido(admin=True)
