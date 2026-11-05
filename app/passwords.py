import hashlib
import hmac
import re
import secrets

PREFIXO = 'pbkdf2_sha256'
ITERACOES = 600_000
ITERACOES_LEGADO = 100_000

_COMUNS = {'admin123', '12345678', '123456789', 'senha123', 'password',
           'abc12345', 'qwerty123', 'admin1234', 'mudar123', 'senha1234'}

# hash sem correspondência, usado para gastar o mesmo tempo quando o usuário não existe
_HASH_FALSO = f'{PREFIXO}${ITERACOES}${"0" * 32}${"0" * 64}'


def _derivar(senha, salt, iteracoes):
    return hashlib.pbkdf2_hmac('sha256', senha.encode('utf-8'),
                               salt.encode('utf-8'), iteracoes).hex()


def _hash_senha(senha, salt=None):
    salt = salt or secrets.token_hex(16)
    return f'{PREFIXO}${ITERACOES}${salt}${_derivar(senha, salt, ITERACOES)}'


def _verifica_senha(senha, hashed):
    try:
        partes = (hashed or '').split('$')
        if len(partes) == 4 and partes[0] == PREFIXO:
            iteracoes, salt, esperado = int(partes[1]), partes[2], partes[3]
        elif len(partes) == 2:  # formato antigo: salt$hash (100k)
            iteracoes, (salt, esperado) = ITERACOES_LEGADO, partes
        else:
            return False
        if not (1 <= iteracoes <= 5_000_000):
            return False
        calculado = _derivar(senha, salt, iteracoes)
        return hmac.compare_digest(calculado.encode(), esperado.encode())
    except Exception:
        return False


def _precisa_rehash(hashed):
    partes = (hashed or '').split('$')
    if len(partes) != 4 or partes[0] != PREFIXO:
        return True
    try:
        return int(partes[1]) < ITERACOES
    except ValueError:
        return True


def verificar_falso(senha):
    _verifica_senha(senha, _HASH_FALSO)


def validar_senha(senha, usuario=None):
    """Retorna a mensagem de erro, ou None se a senha é aceitável."""
    if len(senha) < 8:
        return 'A senha deve ter ao menos 8 caracteres'
    if len(senha) > 128:
        return 'A senha deve ter no máximo 128 caracteres'
    if not re.search(r'[A-Za-z]', senha) or not re.search(r'\d', senha):
        return 'A senha deve conter letras e números'
    if senha.lower() in _COMUNS:
        return 'Esta senha é muito comum. Escolha outra'
    if usuario and senha.lower() == usuario.lower():
        return 'A senha não pode ser igual ao login'
    return None
