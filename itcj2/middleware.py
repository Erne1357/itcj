import logging
import time

import jwt
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from .config import get_settings

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
                from itcj2.core.services.session_service import current_version
                if int(data.get("sv", 0)) != current_version(int(data["sub"])):
                    data = None
            except Exception:
                pass

        request.state.current_user = data

        # Detectar si el token necesita refresh
        needs_refresh = False
        if data:
            now = int(time.time())
            if data.get("exp", 0) - now < _settings.JWT_REFRESH_THRESHOLD_SECONDS:
                needs_refresh = True

        response: Response = await call_next(request)

        # Refrescar cookie si es necesario (misma lógica que Flask)
        if needs_refresh and data:
            from itcj2.core.models.user import User
            from itcj2.database import SessionLocal

            # El claim `role` debe conservar el ROL GLOBAL string (como en login),
            # no la lista de roles de la app 'itcj'. Muchos checks hacen
            # `user.get("role") == "admin"`; una lista los rompía a mitad de sesión.
            _global_role: str | None = None
            _user_active = False
            _db = SessionLocal()
            try:
                _u = _db.get(User, int(data["sub"]))
                if _u is not None:
                    _user_active = bool(_u.is_active)
                    _global_role = _u.role.name if _u.role else None
                _db.rollback()
            except Exception as e:
                logger.warning("JWT refresh user query failed: %s", e)
                try:
                    _db.rollback()
                except Exception:
                    pass
            finally:
                try:
                    _db.close()
                except Exception:
                    pass

            if not _user_active:
                # Usuario inexistente/inactivo o consulta fallida: no rotamos.
                return response

            from itcj2.core.services.session_service import current_version
            new_token = _encode_jwt(
                {
                    "sub": data["sub"],
                    "role": _global_role,
                    "cn": data.get("cn"),
                    "name": data.get("name"),
                    "sv": current_version(int(data["sub"])),
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
