"""
API de configuracion del motor de asignacion automatica (switch maestro + reglas).
Respuestas {"success": True, "data": ...}.
"""
import logging

from fastapi import APIRouter, Request
from itcj2.dependencies import DbSession, require_perms
from itcj2.apps.helpdesk.schemas.config.auto_assign import (
    AssignmentRuleCreate,
    AssignmentRuleUpdate,
    AutoAssignSettingsUpdate,
)

router = APIRouter(tags=["helpdesk-config-auto-assign"])
logger = logging.getLogger(__name__)

_READ = ["helpdesk.config.auto_assign.api.read"]
_UPDATE = ["helpdesk.config.auto_assign.api.update"]


def _ip(request: Request):
    return request.client.host if request.client else None


@router.get("")
def get_auto_assign(
    user: dict = require_perms("helpdesk", _READ),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.services.assignment_rule_service import AssignmentRuleService
    from itcj2.apps.helpdesk.services.helpdesk_settings_service import get_settings

    return {"success": True, "data": {
        "enabled": bool(get_settings(db).auto_assign_enabled),
        "rules": AssignmentRuleService.list_rules(db),
        "catalogs": AssignmentRuleService.catalogs(db),
    }}


@router.patch("/settings")
def update_auto_assign_settings(
    body: AutoAssignSettingsUpdate,
    request: Request,
    user: dict = require_perms("helpdesk", _UPDATE),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.services.config_audit_service import log_config_change
    from itcj2.apps.helpdesk.services.helpdesk_settings_service import get_settings, update_settings

    uid = int(user["sub"])
    before = {"enabled": bool(get_settings(db).auto_assign_enabled)}
    update_settings(db, user_id=uid, auto_assign_enabled=body.enabled)
    log_config_change(db, uid, "helpdesk_settings", 1, "update", before,
                      {"enabled": body.enabled}, _ip(request))
    db.commit()
    return {"success": True, "data": {"enabled": body.enabled}}


@router.post("/rules", status_code=201)
def create_rule(
    body: AssignmentRuleCreate,
    request: Request,
    user: dict = require_perms("helpdesk", _UPDATE),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.services.assignment_rule_service import AssignmentRuleService
    from itcj2.apps.helpdesk.services.config_audit_service import log_config_change

    uid = int(user["sub"])
    rule = AssignmentRuleService.create_rule(db, body.model_dump(), uid)
    log_config_change(db, uid, "assignment_rule", rule.id, "create", None, rule.to_dict(), _ip(request))
    db.commit()
    return {"success": True, "data": rule.to_dict()}


@router.patch("/rules/{rule_id}")
def update_rule(
    rule_id: int,
    body: AssignmentRuleUpdate,
    request: Request,
    user: dict = require_perms("helpdesk", _UPDATE),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.models.assignment_rule import AssignmentRule
    from itcj2.apps.helpdesk.services.assignment_rule_service import AssignmentRuleService
    from itcj2.apps.helpdesk.services.config_audit_service import log_config_change

    uid = int(user["sub"])
    existing = db.get(AssignmentRule, rule_id)
    before = existing.to_dict() if existing else None
    rule = AssignmentRuleService.update_rule(db, rule_id, body.model_dump(exclude_unset=True), uid)
    log_config_change(db, uid, "assignment_rule", rule.id, "update", before, rule.to_dict(), _ip(request))
    db.commit()
    return {"success": True, "data": rule.to_dict()}


@router.delete("/rules/{rule_id}")
def delete_rule(
    rule_id: int,
    request: Request,
    user: dict = require_perms("helpdesk", _UPDATE),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.models.assignment_rule import AssignmentRule
    from itcj2.apps.helpdesk.services.assignment_rule_service import AssignmentRuleService
    from itcj2.apps.helpdesk.services.config_audit_service import log_config_change

    uid = int(user["sub"])
    existing = db.get(AssignmentRule, rule_id)
    before = existing.to_dict() if existing else None
    AssignmentRuleService.delete_rule(db, rule_id)
    log_config_change(db, uid, "assignment_rule", rule_id, "delete", before, None, _ip(request))
    db.commit()
    return {"success": True, "message": "Regla eliminada"}
