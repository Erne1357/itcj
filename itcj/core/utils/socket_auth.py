# utils/socket_auth.py
from .jwt_tools import decode_jwt

def current_user_from_environ(environ):
    """
    Extrae el usuario actual desde la cookie 'itcj_token' en el handshake WS.
    Devuelve un dict {sub, role, cn, name} o None si no hay cookie válida.
    """
    # wsgi 'environ' trae las headers crudas (HTTP_COOKIE, etc)
    cookie_header = environ.get("HTTP_COOKIE", "") or ""
    token = None
    for part in cookie_header.split(";"):
        k, _, v = part.strip().partition("=")
        if k == "itcj_token":
            token = v
            break
    if not token:
        return None
    data = decode_jwt(token)
    if not data:
        return None
    return {
        "sub": data.get("sub"),
        "role": data.get("role"),
        "cn": data.get("cn"),
        "name": data.get("name"),
    }
