import secrets
from flask import Blueprint, request, jsonify

from ..database import get_db
from ..passwords import _hash_senha, _verifica_senha
from ..auth import usuario_atual, login_obrigatorio
from ..config import SESSION_DAYS

bp = Blueprint('auth', __name__, url_prefix='/api')


@bp.route('/login', methods=['POST'])
def login():
    d = request.get_json(silent=True) or {}
    usuario = (d.get('usuario') or '').strip().lower()
    senha = d.get('senha') or ''
    db = get_db()
    with db.cursor() as cur:
        cur.execute('SELECT * FROM usuarios WHERE LOWER(usuario) = %s', (usuario,))
        row = cur.fetchone()
    if not row or not _verifica_senha(senha, row['senha_hash']):
        return jsonify({'erro': 'Usuário ou senha inválidos'}), 401
    token = secrets.token_hex(24)
    with db.cursor() as cur:
        cur.execute(f'''INSERT INTO sessoes (token, usuario_id, expira_em)
                        VALUES (%s, %s, NOW() + INTERVAL '{SESSION_DAYS} days')''',
                    (token, row['id']))
    db.commit()
    return jsonify(id=row['id'], nome=row['nome'], usuario=row['usuario'],
                   admin=row['admin'], token=token)


@bp.route('/senha', methods=['PUT'])
@login_obrigatorio
def alterar_senha():
    d = request.get_json(silent=True) or {}
    u = usuario_atual()
    db = get_db()
    with db.cursor() as cur:
        cur.execute('SELECT senha_hash FROM usuarios WHERE id = %s', (u['id'],))
        row = cur.fetchone()
        if not _verifica_senha(d.get('atual') or '', row['senha_hash']):
            return jsonify({'erro': 'Senha atual incorreta'}), 400
        nova = d.get('nova') or ''
        if len(nova) < 6:
            return jsonify({'erro': 'Senha nova deve ter ao menos 6 caracteres'}), 400
        cur.execute('UPDATE usuarios SET senha_hash = %s WHERE id = %s',
                    (_hash_senha(nova), u['id']))
    db.commit()
    return jsonify({'ok': True})
