import logging
import time

import jwt
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.concurrency import run_in_threadpool
from starlette.middleware.base import BaseHTTPMiddleware

from .config import get_settings
from .observability.middleware import ObservabilityMiddleware

logger = logging.getLogger("itcj2")

# ---------------------------------------------------------------------------
# JWT helpers (independientes de Flask, usan misma SECRET que itcj/)
# ---------------------------------------------------------------------------
_settings = get_settings()
_JWT_SECRET = _settings.SECRET_KEY
_JWT_ALGO = "HS256"


def _decode_jwt(token: str | None) -> dict | None:
    """Decodifica un JWT sin depender de Flask (current_app)."""
    if not token:
        return None
    try:
        return jwt.decode(
            token,
            _JWT_SECRET,
            algorithms=[_JWT_ALGO],
            options={"verify_aud": False},
            leeway=30,
        )
    except jwt.ExpiredSignatureError:
        logger.debug("JWT expired")
    except jwt.InvalidSignatureError:
        logger.warning("JWT bad signature")
    except jwt.DecodeError:
        logger.warning("JWT decode error")
    except jwt.PyJWTError as e:
        logger.warning("JWT error: %s", e)
    return None


def _encode_jwt(payload: dict, hours: int = 12) -> str:
    """Genera un JWT idéntico al de Flask (misma SECRET, mismo algoritmo)."""
    now = int(time.time())
    body = {**payload, "iat": now, "exp": now + hours * 3600}
    token = jwt.encode(body, _JWT_SECRET, algorithm=_JWT_ALGO)
    return token.decode("utf-8") if isinstance(token, bytes) else token


def _refresh_claims(user_id: int) -> tuple[str | None, int] | None:
    """`(rol_global, sv)` para re-acuñar la cookie, o `None` si NO hay que rotar.

    SÍNCRONA a propósito: se llama con `run_in_threadpool`, nunca desde el loop.
    Agrupa la consulta del usuario y la época para que el refresh cueste un solo
    salto al threadpool.
    """
    from itcj2.core.models.user import User
    from itcj2.core.services.session_service import current_version
    from itcj2.database import session_scope

    # El claim `role` debe conservar el ROL GLOBAL string (como en login), no la
    # lista de roles de la app 'itcj'. Muchos checks hacen
    # `user.get("role") == "admin"`; una lista los rompía a mitad de sesión.
    # `session_scope` hace el rollback antes del close que PgBouncer en
    # transaction mode necesita para liberar la conexión.
    try:
        with session_scope() as db:
            u = db.get(User, user_id)
            if u is None or not u.is_active:
                # Usuario inexistente o inactivo: no rotamos.
                return None
            global_role = u.role.name if u.role else None
    except Exception as e:
        logger.warning("JWT refresh user query failed: %s", e)
        return None

    cur = current_version(user_id)
    if cur is None:
        # Época indeterminable: rotar la cookie con un sv inventado revocaría al
        # usuario en cuanto Redis vuelva. Mejor no rotar; el token sigue vivo.
        return None
    return global_role, cur


# ---------------------------------------------------------------------------
# Middleware: inyecta current_user y refresca cookie JWT
# ---------------------------------------------------------------------------
class JWTMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        token = request.cookies.get("itcj_token")
        data = _decode_jwt(token)

        # Revocación de sesión: si el token trae claim `sv` y no coincide con la
        # versión vigente del usuario, está revocado (logout/desactivación/cambio de
        # rol). Tokens viejos sin `sv` no se revisan (compat). Fail-open si Redis cae.
        if data and "sv" in data:
            try:
                from itcj2.core.services.session_service import current_version_async
                _cur = await current_version_async(int(data["sub"]))
                if _cur is not None and int(data.get("sv", 0)) != _cur:
                    data = None
            except Exception:
                pass

        request.state.current_user = data
        request.state.suppress_refresh = False

        # Detectar si el token necesita refresh
        needs_refresh = False
        if data:
            now = int(time.time())
            if data.get("exp", 0) - now < _settings.JWT_REFRESH_THRESHOLD_SECONDS:
                needs_refresh = True

        response: Response = await call_next(request)

        # Refrescar cookie si es necesario (misma lógica que Flask)
        if needs_refresh and data and not getattr(request.state, "suppress_refresh", False):
            # Al threadpool: son E/S síncronas (Postgres y Redis) y `dispatch`
            # corre en el loop del worker para TODA petición; aquí bloqueaban
            # todas las peticiones en vuelo (alerta ItcjEventLoopBloqueosLargos).
            claims = await run_in_threadpool(_refresh_claims, int(data["sub"]))
            if claims is None:
                return response
            _global_role, _cur = claims
            new_token = _encode_jwt(
                {
                    "sub": data["sub"],
                    "role": _global_role,
                    "cn": data.get("cn"),
                    "name": data.get("name"),
                    "sv": _cur,
                },
                hours=_settings.JWT_EXPIRES_HOURS,
            )
            response.set_cookie(
                "itcj_token",
                new_token,
                httponly=True,
                samesite=_settings.COOKIE_SAMESITE,
                secure=_settings.COOKIE_SECURE,
                max_age=_settings.JWT_EXPIRES_HOURS * 3600,
                path="/",
            )

        return response


# ---------------------------------------------------------------------------
# Setup: registra todos los middleware en la app
# ---------------------------------------------------------------------------
def setup_middleware(app: FastAPI):
    settings = get_settings()

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.get_cors_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.add_middleware(JWTMiddleware)

    # El ÚLTIMO a propósito: add_middleware inserta en el índice 0, así que el
    # último registrado queda el más externo de los de usuario. Por fuera del
    # JWT cronometra también su trabajo y ve las excepciones que salgan de él.
    app.add_middleware(ObservabilityMiddleware)
