import re
from datetime import datetime
from functools import wraps

from flask import Blueprint, request, jsonify
import psycopg2.errors

from ..database import get_db
from ..auth import admin_obrigatorio, usuario_atual, token_atual, log_seguro
from ..passwords import _hash_senha, validar_senha

bp = Blueprint('usuarios', __name__, url_prefix='/api')

LOGIN_RE = re.compile(r'^[a-z0-9._-]{3,30}$')


def _seguro(f):
    @wraps(f)
    def w(*a, **k):
        try:
            return f(*a, **k)
        except psycopg2.errors.UniqueViolation:
            get_db().rollback()
            return jsonify({'erro': 'Este login já existe'}), 400
        except Exception as e:
            get_db().rollback()
            print('ERRO usuarios:', repr(e))
            return jsonify({'erro': 'Erro interno ao processar a solicitação'}), 500
    return w


def _nome_valido(nome):
    nome = str(nome or '').strip()
    return nome if 2 <= len(nome) <= 80 else None


def _outros_admins_ativos(cur, uid):
    cur.execute('''SELECT COUNT(*) AS n FROM usuarios
                   WHERE admin AND COALESCE(ativo, true) AND id <> %s''', (uid,))
    return cur.fetchone()['n']


def _buscar(cur, uid):
    cur.execute('''SELECT id, nome, usuario, admin, COALESCE(ativo, true) AS ativo
                   FROM usuarios WHERE id = %s''', (uid,))
    return cur.fetchone()


@bp.route('/usuarios', methods=['GET'])
@admin_obrigatorio
def listar():
    db = get_db()
    with db.cursor() as cur:
        cur.execute('''
            SELECT id, nome, usuario, admin, criado_em, ultimo_login,
                   COALESCE(ativo, true) AS ativo,
                   COALESCE(deve_trocar_senha, false) AS deve_trocar_senha,
                   (bloqueado_ate IS NOT NULL AND bloqueado_ate > NOW()) AS bloqueado
            FROM usuarios ORDER BY LOWER(nome)''')
        return jsonify([dict(r) for r in cur.fetchall()])


@bp.route('/usuarios', methods=['POST'])
@admin_obrigatorio
@_seguro
def criar():
    d = request.get_json(silent=True) or {}
    nome = _nome_valido(d.get('nome'))
    login = str(d.get('usuario') or '').strip().lower()
    senha = str(d.get('senha') or '')
    admin = bool(d.get('admin'))
    if not nome:
        return jsonify({'erro': 'Informe o nome (2 a 80 caracteres)'}), 400
    if not LOGIN_RE.match(login):
        return jsonify({'erro': 'Login inválido: use 3 a 30 caracteres entre letras, '
                                'números, ponto, hífen e sublinhado'}), 400
    erro = validar_senha(senha, login)
    if erro:
        return jsonify({'erro': erro}), 400

    db = get_db()
    with db.cursor() as cur:
        cur.execute('SELECT 1 FROM usuarios WHERE LOWER(usuario) = %s', (login,))
        if cur.fetchone():
            return jsonify({'erro': 'Este login já existe'}), 400
        cur.execute('''INSERT INTO usuarios
                         (nome, usuario, senha_hash, admin, criado_em, ativo, deve_trocar_senha)
                       VALUES (%s, %s, %s, %s, %s, true, true) RETURNING id''',
                    (nome, login, _hash_senha(senha), admin,
                     datetime.now().isoformat(timespec='seconds')))
        new_id = cur.fetchone()['id']
    db.commit()
    log_seguro('usuário', f"criou o usuário {login} "
                          f"({'administrador' if admin else 'usuário comum'})")
    return jsonify({'id': new_id}), 201


@bp.route('/usuarios/<int:uid>', methods=['PUT'])
@admin_obrigatorio
@_seguro
def atualizar(uid):
    d = request.get_json(silent=True) or {}
    eu = usuario_atual()
    db = get_db()
    with db.cursor() as cur:
        alvo = _buscar(cur, uid)
        if not alvo:
            return jsonify({'erro': 'Usuário não encontrado'}), 404

        nome, admin, ativo = alvo['nome'], alvo['admin'], alvo['ativo']
        if 'nome' in d:
            nome = _nome_valido(d['nome'])
            if not nome:
                return jsonify({'erro': 'Informe o nome (2 a 80 caracteres)'}), 400
        if 'admin' in d:
            admin = bool(d['admin'])
        if 'ativo' in d:
            ativo = bool(d['ativo'])

        if uid == eu['id'] and (admin != alvo['admin'] or ativo != alvo['ativo']):
            return jsonify({'erro': 'Você não pode alterar o próprio perfil '
                                    'nem desativar a si mesmo'}), 400
        if (alvo['admin'] and alvo['ativo'] and not (admin and ativo)
                and _outros_admins_ativos(cur, uid) == 0):
            return jsonify({'erro': 'Precisa existir ao menos um administrador ativo'}), 400

        cur.execute('UPDATE usuarios SET nome = %s, admin = %s, ativo = %s WHERE id = %s',
                    (nome, admin, ativo, uid))
        if alvo['ativo'] and not ativo:
            cur.execute('DELETE FROM sessoes WHERE usuario_id = %s', (uid,))
    db.commit()

    mud = []
    if nome != alvo['nome']:
        mud.append(f"nome '{alvo['nome']}' → '{nome}'")
    if admin != alvo['admin']:
        mud.append('perfil → ' + ('administrador' if admin else 'usuário comum'))
    if ativo != alvo['ativo']:
        mud.append('ativado' if ativo else 'desativado')
    if mud:
        log_seguro('usuário', f"alterou {alvo['usuario']}: " + '; '.join(mud))
    return jsonify({'ok': True})


@bp.route('/usuarios/<int:uid>/senha', methods=['PUT'])
@admin_obrigatorio
@_seguro
def redefinir_senha(uid):
    d = request.get_json(silent=True) or {}
    eu = usuario_atual()
    nova = str(d.get('nova') or '')
    db = get_db()
    with db.cursor() as cur:
        alvo = _buscar(cur, uid)
        if not alvo:
            return jsonify({'erro': 'Usuário não encontrado'}), 404
        erro = validar_senha(nova, alvo['usuario'])
        if erro:
            return jsonify({'erro': erro}), 400
        # senha definida por outra pessoa: o dono precisa trocá-la no próximo acesso
        cur.execute('''UPDATE usuarios
                       SET senha_hash = %s, deve_trocar_senha = %s,
                           tentativas_falhas = 0, bloqueado_ate = NULL
                       WHERE id = %s''', (_hash_senha(nova), uid != eu['id'], uid))
        if uid == eu['id']:
            cur.execute('DELETE FROM sessoes WHERE usuario_id = %s AND token <> %s',
                        (uid, token_atual()))
        else:
            cur.execute('DELETE FROM sessoes WHERE usuario_id = %s', (uid,))
    db.commit()
    log_seguro('usuário', f"redefiniu a senha de {alvo['usuario']}")
    return jsonify({'ok': True})


@bp.route('/usuarios/<int:uid>/desbloquear', methods=['POST'])
@admin_obrigatorio
@_seguro
def desbloquear(uid):
    db = get_db()
    with db.cursor() as cur:
        alvo = _buscar(cur, uid)
        if not alvo:
            return jsonify({'erro': 'Usuário não encontrado'}), 404
        cur.execute('UPDATE usuarios SET tentativas_falhas = 0, bloqueado_ate = NULL '
                    'WHERE id = %s', (uid,))
    db.commit()
    log_seguro('usuário', f"desbloqueou {alvo['usuario']}")
    return jsonify({'ok': True})


@bp.route('/usuarios/<int:uid>', methods=['DELETE'])
@admin_obrigatorio
@_seguro
def remover(uid):
    eu = usuario_atual()
    if uid == eu['id']:
        return jsonify({'erro': 'Você não pode remover a si mesmo'}), 400
    db = get_db()
    with db.cursor() as cur:
        alvo = _buscar(cur, uid)
        if not alvo:
            return jsonify({'erro': 'Usuário não encontrado'}), 404
        if alvo['admin'] and alvo['ativo'] and _outros_admins_ativos(cur, uid) == 0:
            return jsonify({'erro': 'Precisa existir ao menos um administrador ativo'}), 400
        cur.execute('DELETE FROM usuarios WHERE id = %s', (uid,))
    db.commit()
    log_seguro('usuário', f"removeu o usuário {alvo['usuario']}")
    return jsonify({'ok': True})
