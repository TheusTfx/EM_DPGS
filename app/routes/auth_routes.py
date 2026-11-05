import secrets
from datetime import datetime

from flask import Blueprint, request, jsonify

from ..database import get_db
from ..passwords import (_hash_senha, _verifica_senha, _precisa_rehash,
                         validar_senha, verificar_falso)
from ..auth import usuario_atual, token_atual, login_sem_troca, log_seguro
from ..config import SESSION_DAYS

bp = Blueprint('auth', __name__, url_prefix='/api')

MAX_TENTATIVAS = 5
BLOQUEIO_MIN = 15


def _invalido():
    return jsonify({'erro': 'Usuário ou senha inválidos'}), 401


def _registrar_falha(db, uid):
    with db.cursor() as cur:
        cur.execute(f'''
            UPDATE usuarios SET
              tentativas_falhas = CASE WHEN COALESCE(tentativas_falhas, 0) + 1 >= {MAX_TENTATIVAS}
                                       THEN 0 ELSE COALESCE(tentativas_falhas, 0) + 1 END,
              bloqueado_ate = CASE WHEN COALESCE(tentativas_falhas, 0) + 1 >= {MAX_TENTATIVAS}
                                   THEN NOW() + INTERVAL '{BLOQUEIO_MIN} minutes'
                                   ELSE bloqueado_ate END
            WHERE id = %s
            RETURNING (bloqueado_ate IS NOT NULL AND bloqueado_ate > NOW()) AS bloqueou
        ''', (uid,))
        bloqueou = cur.fetchone()['bloqueou']
    db.commit()
    if bloqueou:
        return jsonify({'erro': f'Muitas tentativas incorretas. Acesso bloqueado por '
                                f'{BLOQUEIO_MIN} minutos.'}), 429
    return _invalido()


@bp.route('/login', methods=['POST'])
def login():
    d = request.get_json(silent=True) or {}
    usuario = str(d.get('usuario') or '').strip().lower()
    senha = str(d.get('senha') or '')
    if not usuario or not senha:
        return jsonify({'erro': 'Informe usuário e senha'}), 400
    if len(usuario) > 100 or len(senha) > 200:
        return _invalido()

    db = get_db()
    with db.cursor() as cur:
        cur.execute('''
            SELECT *,
                   (bloqueado_ate IS NOT NULL AND bloqueado_ate > NOW()) AS bloqueado,
                   CEIL(EXTRACT(EPOCH FROM (bloqueado_ate - NOW())) / 60) AS minutos
            FROM usuarios WHERE LOWER(usuario) = %s
        ''', (usuario,))
        row = cur.fetchone()

    if not row:
        verificar_falso(senha)
        return _invalido()
    if row['bloqueado']:
        minutos = int(row['minutos'] or 1)
        return jsonify({'erro': f'Muitas tentativas incorretas. '
                                f'Tente novamente em {minutos} minuto(s).'}), 429
    if not _verifica_senha(senha, row['senha_hash']):
        return _registrar_falha(db, row['id'])
    if row.get('ativo') is False:
        return jsonify({'erro': 'Usuário desativado. Procure o administrador.'}), 403

    novo_hash = _hash_senha(senha) if _precisa_rehash(row['senha_hash']) else None
    token = secrets.token_hex(24)
    agora = datetime.now().isoformat(timespec='seconds')
    with db.cursor() as cur:
        cur.execute("DELETE FROM sessoes WHERE expira_em IS NOT NULL AND expira_em < NOW()")
        cur.execute('''UPDATE usuarios
                       SET tentativas_falhas = 0, bloqueado_ate = NULL, ultimo_login = %s,
                           senha_hash = COALESCE(%s, senha_hash)
                       WHERE id = %s''', (agora, novo_hash, row['id']))
        cur.execute(f'''INSERT INTO sessoes (token, usuario_id, expira_em)
                        VALUES (%s, %s, NOW() + INTERVAL '{SESSION_DAYS} days')''',
                    (token, row['id']))
    db.commit()
    return jsonify(id=row['id'], nome=row['nome'], usuario=row['usuario'],
                   admin=row['admin'], token=token,
                   deve_trocar_senha=bool(row.get('deve_trocar_senha')))


@bp.route('/logout', methods=['POST'])
@login_sem_troca
def logout():
    db = get_db()
    with db.cursor() as cur:
        cur.execute('DELETE FROM sessoes WHERE token = %s', (token_atual(),))
    db.commit()
    return jsonify({'ok': True})


@bp.route('/me', methods=['GET'])
@login_sem_troca
def me():
    u = usuario_atual()
    return jsonify(id=u['id'], nome=u['nome'], usuario=u['usuario'],
                   admin=u['admin'], deve_trocar_senha=u['deve_trocar_senha'])


@bp.route('/senha', methods=['PUT'])
@login_sem_troca
def alterar_senha():
    d = request.get_json(silent=True) or {}
    u = usuario_atual()
    atual = str(d.get('atual') or '')
    nova = str(d.get('nova') or '')
    db = get_db()
    with db.cursor() as cur:
        cur.execute('SELECT senha_hash FROM usuarios WHERE id = %s', (u['id'],))
        row = cur.fetchone()
        if not row or not _verifica_senha(atual, row['senha_hash']):
            return jsonify({'erro': 'Senha atual incorreta'}), 400
        if nova == atual:
            return jsonify({'erro': 'A nova senha deve ser diferente da atual'}), 400
        erro = validar_senha(nova, u['usuario'])
        if erro:
            return jsonify({'erro': erro}), 400
        cur.execute('''UPDATE usuarios SET senha_hash = %s, deve_trocar_senha = false
                       WHERE id = %s''', (_hash_senha(nova), u['id']))
        # a troca de senha derruba todas as outras sessões deste usuário
        cur.execute('DELETE FROM sessoes WHERE usuario_id = %s AND token <> %s',
                    (u['id'], token_atual()))
    db.commit()
    log_seguro('usuário', f"{u['usuario']} alterou a própria senha")
    return jsonify({'ok': True})


@bp.route('/sessoes/outras', methods=['DELETE'])
@login_sem_troca
def encerrar_outras():
    u = usuario_atual()
    db = get_db()
    with db.cursor() as cur:
        cur.execute('DELETE FROM sessoes WHERE usuario_id = %s AND token <> %s',
                    (u['id'], token_atual()))
        n = cur.rowcount
    db.commit()
    return jsonify({'ok': True, 'encerradas': n})
