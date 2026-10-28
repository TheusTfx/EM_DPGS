from datetime import datetime

from flask import Blueprint, request, jsonify
import psycopg2.errors

from ..database import get_db
from ..auth import admin_obrigatorio, usuario_atual
from ..passwords import _hash_senha

bp = Blueprint('usuarios', __name__, url_prefix='/api')


@bp.route('/usuarios', methods=['GET'])
@admin_obrigatorio
def listar():
    db = get_db()
    with db.cursor() as cur:
        cur.execute('SELECT id, nome, usuario, admin FROM usuarios ORDER BY nome')
        return jsonify([dict(r) for r in cur.fetchall()])


@bp.route('/usuarios', methods=['POST'])
@admin_obrigatorio
def criar():
    d = request.get_json(silent=True) or {}
    login = (d.get('usuario') or '').strip().lower()
    if not d.get('nome') or not login or len(d.get('senha') or '') < 6:
        return jsonify({'erro': 'Nome, usuário e senha (mín. 6) são obrigatórios'}), 400
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute('SELECT 1 FROM usuarios WHERE LOWER(usuario) = %s', (login,))
            if cur.fetchone():
                return jsonify({'erro': 'Este login já existe'}), 400
            cur.execute('''INSERT INTO usuarios (nome, usuario, senha_hash, admin, criado_em)
                           VALUES (%s,%s,%s,%s,%s) RETURNING id''',
                        (d['nome'].strip(), login, _hash_senha(d['senha']),
                         bool(d.get('admin')),
                         datetime.now().isoformat(timespec='seconds')))
            new_id = cur.fetchone()['id']
        db.commit()
        return jsonify({'id': new_id}), 201
    except psycopg2.errors.UniqueViolation:
        db.rollback()
        return jsonify({'erro': 'Este login já existe'}), 400
    except Exception as e:
        db.rollback()
        return jsonify({'erro': str(e)}), 500


@bp.route('/usuarios/<int:uid>/senha', methods=['PUT'])
@admin_obrigatorio
def redefinir_senha(uid):
    d = request.get_json(silent=True) or {}
    if len(d.get('nova') or '') < 6:
        return jsonify({'erro': 'Senha deve ter ao menos 6 caracteres'}), 400
    db = get_db()
    with db.cursor() as cur:
        cur.execute('UPDATE usuarios SET senha_hash = %s WHERE id = %s',
                    (_hash_senha(d['nova']), uid))
    db.commit()
    return jsonify({'ok': True})


@bp.route('/usuarios/<int:uid>', methods=['DELETE'])
@admin_obrigatorio
def remover(uid):
    u = usuario_atual()
    if uid == u['id']:
        return jsonify({'erro': 'Você não pode remover a si mesmo'}), 400
    db = get_db()
    with db.cursor() as cur:
        cur.execute('DELETE FROM usuarios WHERE id = %s', (uid,))
    db.commit()
    return jsonify({'ok': True})
