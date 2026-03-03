"""
Auth API v2 - Login, logout, me.

Comparte la misma cookie (itcj_token) con Flask para que la sesión
sea transparente entre ambos servidores.
"""
from fastapi import APIRouter, Response, HTTPException
from sqlalchemy.orm import Session

from itcj2.config import get_settings
from itcj2.dependencies import CurrentUser, DbSession
from itcj2.middleware import _decode_jwt, _encode_jwt
from itcj2.core.schemas.auth import LoginRequest, LoginResponse, MeResponse, UserInfo

router = APIRouter(prefix="/auth", tags=["auth"])

_settings = get_settings()


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest, response: Response, db: DbSession):
    """Autenticación por número de control (alumno) o username (staff)."""
    raw_id = body.control_number.strip()
    nip = body.nip.strip()

    if not raw_id:
        raise HTTPException(400, detail="invalid_format")

    from itcj2.core.services.auth_service import authenticate, authenticate_by_username

    is_student = raw_id.isdigit() and len(raw_id) == 8
    user = authenticate(db, raw_id, nip) if is_student else authenticate_by_username(db, raw_id, nip)

    if not user:
        raise HTTPException(401, detail="invalid_credentials")

    token = _encode_jwt(
        {
            "sub": str(user["id"]),
            "role": user["role"],
            "cn": user.get("control_number"),
            "name": user["full_name"],
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
    """Cierra la sesión eliminando la cookie JWT."""
    response.delete_cookie(
        "itcj_token",
        httponly=True,
        samesite=_settings.COOKIE_SAMESITE,
        secure=_settings.COOKIE_SECURE,
        path="/",
    )
