"""
Users API v2 - Perfil del usuario actual, cambio de contraseña, actividad.

Reusa los servicios existentes de itcj/core/services/.
"""
import logging

from fastapi import APIRouter, HTTPException, Query

from itcj2.dependencies import CurrentUser, DbSession
from itcj2.core.schemas.user import (
    ChangePasswordRequest,
    FullProfileResponse,
    PasswordStateResponse,
    UpdateProfileRequest,
    UserProfileBasic,
    UserProfileResponse,
    PositionInfo,
)

router = APIRouter(prefix="/user", tags=["user"])
logger = logging.getLogger("itcj2.users")

DEFAULT_PASSWORD = "tecno#2K"


def _get_user(user_data: dict, db):
    """Helper: obtiene el modelo User desde la sesión FastAPI."""
    from itcj2.core.models.user import User

    return db.query(User).get(int(user_data["sub"]))


@router.get("/password-state", response_model=PasswordStateResponse)
def password_state(user: CurrentUser, db: DbSession):
    """Verifica si el usuario debe cambiar su contraseña (solo staff)."""
    from itcj2.core.services.authz_service import user_roles_in_app
    from itcj2.core.utils.security import verify_nip

    u = _get_user(user, db)
    if not u:
        raise HTTPException(404, detail="user_not_found")

    if "student" in user_roles_in_app(db, u.id, "itcj"):
        return PasswordStateResponse(must_change=False)

    must_change = verify_nip(DEFAULT_PASSWORD, u.password_hash)
    return PasswordStateResponse(must_change=must_change)


@router.post("/change-password")
def change_password(body: ChangePasswordRequest, user: CurrentUser, db: DbSession):
    """Cambia la contraseña del usuario (solo staff)."""
    from itcj2.core.services.authz_service import user_roles_in_app
    from itcj2.core.utils.security import hash_nip

    u = _get_user(user, db)
    if not u or "student" in user_roles_in_app(db, u.id, "itcj"):
        raise HTTPException(403, detail="unauthorized")

    if body.new_password == DEFAULT_PASSWORD:
        raise HTTPException(400, detail="No puedes usar la contraseña por defecto")

    u.password_hash = hash_nip(body.new_password)
    u.must_change_password = False
    db.commit()

    return {"message": "password_updated"}


@router.get("/me", response_model=UserProfileResponse)
def get_current_user_info(user: CurrentUser, db: DbSession):
    """Información detallada del usuario actual con roles y posiciones."""
    from itcj2.core.services.authz_service import user_roles_in_app
    from itcj2.core.models.app import App
    from itcj2.core.models.position import UserPosition

    u = _get_user(user, db)
    if not u:
        raise HTTPException(404, detail="user_not_found")

    # Rol global
    roles_itcj = user_roles_in_app(db, u.id, "itcj")
    global_role = list(roles_itcj)[0] if roles_itcj else "Usuario"

    # Roles por app
    app_keys = [a.key for a in db.query(App.key).all()]
    roles = {}
    for key in app_keys:
        app_roles = user_roles_in_app(db, u.id, key)
        roles[key] = list(app_roles) if isinstance(app_roles, set) else app_roles

    # Posiciones activas
    positions = []
    active_positions = (
        db.query(UserPosition)
        .filter_by(user_id=u.id, is_active=True)
        .all()
    )
    for p in active_positions:
        positions.append(
            PositionInfo(
                title=p.position.title,
                department=p.position.department.name if p.position.department else None,
            )
        )

    return UserProfileResponse(
        data=UserProfileBasic(
            id=u.id,
            username=u.username,
            full_name=u.full_name,
            email=u.email,
            role=global_role,
            roles=roles,
            positions=positions,
        )
    )


@router.get("/me/profile", response_model=FullProfileResponse)
def get_full_profile(user: CurrentUser):
    """Perfil completo con desglose de permisos."""
    from itcj2.database import SessionLocal
    from itcj2.core.services.profile_service import get_user_profile_data

    user_id = int(user["sub"])
    db = SessionLocal()
    try:
        profile = get_user_profile_data(db, user_id)
    finally:
        db.close()
    if not profile:
        raise HTTPException(404, detail="user_not_found")

    return FullProfileResponse(data=profile)


@router.get("/me/activity")
def get_activity(user: CurrentUser, limit: int = Query(10, ge=1, le=50)):
    """Actividad reciente del usuario."""
    from itcj2.database import SessionLocal
    from itcj2.core.services.profile_service import get_user_activity

    user_id = int(user["sub"])
    db = SessionLocal()
    try:
        return {"status": "ok", "data": get_user_activity(db, user_id, limit=limit)}
    finally:
        db.close()


@router.get("/me/notifications")
def get_notifications(
    user: CurrentUser,
    unread_only: bool = False,
    limit: int = Query(20, ge=1, le=100),
):
    """Notificaciones del usuario (acceso rápido desde perfil)."""
    from itcj2.database import SessionLocal
    from itcj2.core.services.profile_service import get_user_notifications

    user_id = int(user["sub"])
    db = SessionLocal()
    try:
        return {"status": "ok", "data": get_user_notifications(db, user_id, unread_only, limit)}
    finally:
        db.close()


@router.patch("/me/profile")
def update_profile(body: UpdateProfileRequest, user: CurrentUser, db: DbSession):
    """Actualiza campos no críticos del perfil (email)."""
    from itcj2.core.models.user import User

    u = db.query(User).get(int(user["sub"]))
    if not u:
        raise HTTPException(404, detail="user_not_found")

    if body.email is not None:
        u.email = body.email

    db.commit()
    return {"status": "ok", "message": "profile_updated"}
