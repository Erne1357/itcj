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
            from itcj.core.services.authz_service import user_roles_in_app

            new_token = _encode_jwt(
                {
                    "sub": data["sub"],
                    "role": list(user_roles_in_app(int(data["sub"]), "itcj")),
                    "cn": data.get("cn"),
                    "name": data.get("name"),
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
