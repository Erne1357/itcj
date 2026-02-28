"""
Coord Password API v2 — Gestión de contraseña del coordinador.
Fuente: itcj/apps/agendatec/routes/api/coord/password.py
"""
import logging

from fastapi import APIRouter, HTTPException

from itcj2.dependencies import DbSession, require_roles
from itcj2.apps.agendatec.schemas.coord import ChangePasswordBody
from itcj.apps.agendatec.config import DEFAULT_STAFF_PASSWORD
from itcj.core.models.coordinator import Coordinator
from itcj.core.models.user import User
from itcj.core.utils.security import hash_nip, verify_nip

router = APIRouter(tags=["agendatec-coord-password"])
logger = logging.getLogger(__name__)

CoordRole = require_roles("agendatec", ["coordinator"])


# ==================== GET /password-state ====================

@router.get("/password-state")
def coord_password_state(
    user: dict = CoordRole,
    db: DbSession = None,
):
    """Verifica si el coordinador debe cambiar su contraseña."""
    uid = int(user["sub"])
    u = db.query(User).get(uid)
    if not u:
        raise HTTPException(status_code=404, detail="user_not_found")

    must_change = verify_nip(DEFAULT_STAFF_PASSWORD, u.password_hash)
    return {"must_change": must_change}


# ==================== POST /change-password ====================

@router.post("/change-password")
def change_password(
    body: ChangePasswordBody,
    user: dict = CoordRole,
    db: DbSession = None,
):
    """Cambia la contraseña del coordinador."""
    uid = int(user["sub"])
    u = db.query(User).get(uid)
    if not u:
        raise HTTPException(status_code=404, detail="user_not_found")

    new_pw = (body.new_password or "").strip()
    if len(new_pw) < 4:
        raise HTTPException(status_code=400, detail="invalid_new_password")

    coord = db.query(Coordinator).filter_by(user_id=u.id).first()
    if coord:
        coord.must_change_pw = False

    u.password_hash = hash_nip(new_pw)
    db.commit()
    return {"ok": True}
