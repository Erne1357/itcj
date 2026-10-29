"""
API de configuracion del correo al tecnico asignado (buzon + tecnicos con aviso).
Respuestas {"success": True, "data": ...}.
"""
import logging

from fastapi import APIRouter, HTTPException, Request
from itcj2.dependencies import DbSession, require_perms
from itcj2.apps.helpdesk.schemas.config.auto_assign import AssignmentEmailUpdate

router = APIRouter(tags=["helpdesk-config-assignment-email"])
logger = logging.getLogger(__name__)


def _technicians(db):
    """[(user, [areas])] de tecnicos activos de todas las areas, sin duplicados, por apellido."""
    from itcj2.apps.helpdesk.models.area import Area
    from itcj2.apps.helpdesk.services.assignment_service import get_technicians_by_area

    by_user: dict = {}
    for a in db.query(Area).filter_by(is_active=True).order_by(Area.display_order, Area.id).all():
        for u in get_technicians_by_area(db, a.code):
            by_user.setdefault(u.id, (u, []))[1].append(a.code)
    for _, areas in by_user.values():
        areas.sort()
    return sorted(by_user.values(), key=lambda t: (t[0].last_name or "", t[0].first_name or ""))


@router.get("")
def get_assignment_email(
    user: dict = require_perms("helpdesk", ["helpdesk.config.assignment_email.api.read"]),
    db: DbSession = None,
):
    from itcj2.core.utils import msgraph_mail
    from itcj2.apps.helpdesk.services.helpdesk_settings_service import get_settings

    info = msgraph_mail.read_account_info("helpdesk")
    enabled = set(get_settings(db).assignment_email_user_ids or [])
    return {"success": True, "data": {
        "connected": bool(info),
        "account": {"username": info.get("username"), "name": info.get("name")} if info else None,
        "config_url": "/itcj/config/email",
        "technicians": [
            {"id": u.id, "name": u.full_name, "email": u.email, "areas": areas,
             "enabled": u.id in enabled}
            for u, areas in _technicians(db)
        ],
    }}


@router.put("")
def update_assignment_email(
    body: AssignmentEmailUpdate,
    request: Request,
    user: dict = require_perms("helpdesk", ["helpdesk.config.assignment_email.api.update"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.services.config_audit_service import log_config_change
    from itcj2.apps.helpdesk.services.helpdesk_settings_service import get_settings, update_settings

    uid = int(user["sub"])
    ids = list(dict.fromkeys(body.user_ids))
    valid = {u.id for u, _ in _technicians(db)}
    if any(i not in valid for i in ids):
        raise HTTPException(status_code=400, detail="Todos los usuarios deben ser técnicos activos")
    before = {"user_ids": list(get_settings(db).assignment_email_user_ids or [])}
    update_settings(db, user_id=uid, assignment_email_user_ids=ids)
    log_config_change(db, uid, "assignment_email", 1, "update", before, {"user_ids": ids},
                      request.client.host if request.client else None)
    db.commit()
    return {"success": True, "data": {"user_ids": ids}}
