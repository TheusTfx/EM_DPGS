import hashlib
import hmac
import secrets


def _hash_senha(senha, salt=None):
    salt = salt or secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac('sha256', senha.encode(), salt.encode(), 100_000).hex()
    return f'{salt}${h}'


def _verifica_senha(senha, hashed):
    try:
        salt, _ = hashed.split('$', 1)
        return hmac.compare_digest(_hash_senha(senha, salt), hashed)
    except Exception:
        return False
