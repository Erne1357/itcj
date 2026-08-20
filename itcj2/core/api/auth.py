"""
Auth API v2 - Login, logout, me.

Comparte la misma cookie (itcj_token) con Flask para que la sesión
sea transparente entre ambos servidores.
"""
from fastapi import APIRouter, Request, Response, HTTPException
from sqlalchemy.orm import Session

from itcj2.config import get_settings
from itcj2.dependencies import CurrentUser, DbSession
from itcj2.middleware import _decode_jwt, _encode_jwt
from itcj2.core.schemas.auth import LoginRequest, LoginResponse, MeResponse, UserInfo

router = APIRouter(prefix="/auth", tags=["auth"])

_settings = get_settings()


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest, request: Request, response: Response, db: DbSession):
    """Autenticación por número de control (alumno) o username (staff)."""
    raw_id = body.control_number.strip()
    nip = body.nip.strip()

    if not raw_id:
        raise HTTPException(400, detail="invalid_format")

    from itcj2.core.services.auth_service import authenticate, authenticate_by_username
    from itcj2.core.utils import rate_limit

    client_ip = request.client.host if request.client else "unknown"

    # Rate limit: demasiados fallos por IP o por cuenta → 429 (anti fuerza bruta).
    if not rate_limit.check_login_allowed(client_ip, raw_id):
        raise HTTPException(429, detail="too_many_attempts")

    is_student = raw_id.isdigit() and len(raw_id) == 8
    user = authenticate(db, raw_id, nip) if is_student else authenticate_by_username(db, raw_id, nip)

    if not user:
        rate_limit.note_login_failure(client_ip, raw_id)
        raise HTTPException(401, detail="invalid_credentials")

    rate_limit.reset_login_failures(client_ip, raw_id)

    from itcj2.core.services.session_service import current_version
    _sv = current_version(user["id"])
    if _sv is None:
        # Redis inalcanzable al emitir: se acuña 0. Si la versión real era mayor, el
        # token morirá cuando Redis vuelva y el usuario volverá a entrar — es la
        # dirección segura del error.
        _sv = 0
    token = _encode_jwt(
        {
            "sub": str(user["id"]),
            "role": user["role"],
            "cn": user.get("control_number"),
            "name": user["full_name"],
            "sv": _sv,
        },
        hours=_settings.JWT_EXPIRES_HOURS,
    )

    response.set_cookie(
        "itcj_token",
        token,
        httponly=True,
        samesite=_settings.COOKIE_SAMESITE,
        secure=_settings.COOKIE_SECURE,
        max_age=_settings.JWT_EXPIRES_HOURS * 3600,
        path="/",
    )

    return LoginResponse(
        user=UserInfo(
            id=user["id"],
            role=user["role"],
            full_name=user["full_name"],
        )
    )


@router.get("/me", response_model=MeResponse)
def me(user: CurrentUser):
    """Retorna información básica del usuario autenticado (desde el JWT)."""
    return MeResponse(
        user=UserInfo(
            id=int(user["sub"]),
            role=user.get("role"),
            control_number=user.get("cn"),
            full_name=user.get("name", ""),
        )
    )


@router.post("/logout", status_code=204)
def logout(user: CurrentUser, response: Response):
    """Cierra la sesión: elimina la cookie y revoca todos los tokens del usuario."""
    from itcj2.core.services.session_service import bump_version
    try:
        bump_version(int(user["sub"]))
    except Exception:
        pass
    response.delete_cookie(
        "itcj_token",
        httponly=True,
        samesite=_settings.COOKIE_SAMESITE,
        secure=_settings.COOKIE_SECURE,
        path="/",
    )
