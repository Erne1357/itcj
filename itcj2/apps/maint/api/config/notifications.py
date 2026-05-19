"""
Config API — Plantillas de Notificación (maint).

CRUD parcial (sin create ni delete) para MaintNotificationTemplate con
auditoría en MaintConfigChangeLog e invalidación de cache tras escritura.

Rutas reales (montado en /api/maint/v2/config/notifications):
  GET    /              → lista todas las plantillas
  GET    /{tpl_id}      → obtiene una plantilla por id
  PATCH  /{tpl_id}      → actualiza parcialmente (valida sintaxis Jinja)
  PATCH  /{tpl_id}/toggle → activa/desactiva
  POST   /{tpl_id}/preview → renderiza con ticket real o dummy
"""
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy.orm import Session

from itcj2.dependencies import DbSession, require_perms
from itcj2.apps.maint.schemas.config.notifications import (
    UpdateNotificationTemplate,
    ToggleNotificationTemplate,
    PreviewNotificationTemplate,
)
from itcj2.apps.maint.services.config_audit_service import log_config_change, client_ip
from itcj2.apps.maint.utils.catalog_cache import invalidate_notification_templates

router = APIRouter(tags=["maint-config-notifications"])
logger = logging.getLogger(__name__)


# ==================== HELPERS ====================

def _tpl_to_dict(t) -> dict:
    return {
        "id": t.id,
        "code": t.code,
        "name": t.name,
        "channel": t.channel,
        "subject_template": t.subject_template,
        "title_template": t.title_template,
        "body_template": t.body_template,
        "variables": t.variables,
        "is_active": t.is_active,
        "updated_at": t.updated_at.isoformat() if t.updated_at else None,
        "updated_by_id": t.updated_by_id,
    }


def _validate_jinja_syntax(field_name: str, template_str: Optional[str]) -> None:
    """
    Valida la sintaxis Jinja2 de un string de plantilla.
    Lanza HTTPException 422 si la sintaxis es inválida.
    Ignorado si template_str es None o vacío.
    """
    if not template_str:
        return
    import jinja2
    try:
        jinja2.Environment().parse(template_str)
    except jinja2.TemplateSyntaxError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Sintaxis Jinja2 inválida en '{field_name}': {exc.message} (línea {exc.lineno})",
        )


def _build_dummy_ticket():
    """Construye un objeto dummy con campos típicos de un ticket para preview."""
    from types import SimpleNamespace

    requester = SimpleNamespace(
        id=1,
        full_name='Juan Pérez (preview)',
        email='jperez@itcj.edu.mx',
    )
    technician = SimpleNamespace(
        id=2,
        full_name='Técnico Ejemplo (preview)',
        email='tecnico@itcj.edu.mx',
    )
    category = SimpleNamespace(name='Eléctrico')

    ticket = SimpleNamespace(
        id=999,
        ticket_number='MANT-2026-000001',
        title='Falla en contacto eléctrico del taller A-101',
        status='IN_PROGRESS',
        priority='ALTA',
        category=category,
        requester=requester,
        requester_id=1,
        cancel_reason=None,
        rating_attention=4,
        rating_speed=5,
        rating_efficiency=4,
        due_at=None,
        active_technicians=[
            SimpleNamespace(user_id=2),
        ],
        resolved_by_id=2,
    )
    return ticket, requester, technician


# ==================== ENDPOINTS ====================

@router.get("")
def list_notification_templates(
    request: Request,
    user: dict = require_perms("maint", [
        "maint.config.notifications.api.read",
        "maint.admin.api.categories",
    ]),
    db: DbSession = None,
):
    """Lista todas las plantillas de notificación."""
    from itcj2.apps.maint.models.notification_template import MaintNotificationTemplate

    templates = (
        db.query(MaintNotificationTemplate)
        .order_by(MaintNotificationTemplate.id)
        .all()
    )
    return {
        "success": True,
        "data": [_tpl_to_dict(t) for t in templates],
        "total": len(templates),
    }


@router.get("/{tpl_id}")
def get_notification_template(
    tpl_id: int,
    request: Request,
    user: dict = require_perms("maint", [
        "maint.config.notifications.api.read",
        "maint.admin.api.categories",
    ]),
    db: DbSession = None,
):
    """Obtiene una plantilla de notificación por id."""
    from itcj2.apps.maint.models.notification_template import MaintNotificationTemplate

    tpl = db.get(MaintNotificationTemplate, tpl_id)
    if not tpl:
        raise HTTPException(status_code=404, detail="Plantilla de notificación no encontrada")
    return {"success": True, "data": _tpl_to_dict(tpl)}


@router.patch("/{tpl_id}")
def update_notification_template(
    tpl_id: int,
    request: Request,
    body: UpdateNotificationTemplate,
    user: dict = require_perms("maint", ["maint.config.notifications.api.update"]),
    db: DbSession = None,
):
    """
    Actualiza parcialmente una plantilla. El campo `code` no se puede editar.
    Valida la sintaxis Jinja2 de cada *_template antes de persistir.
    """
    from itcj2.apps.maint.models.notification_template import MaintNotificationTemplate

    tpl = db.get(MaintNotificationTemplate, tpl_id)
    if not tpl:
        raise HTTPException(status_code=404, detail="Plantilla de notificación no encontrada")

    updates = body.model_dump(exclude_none=True)

    # Validar sintaxis Jinja2 en los campos de plantilla antes de tocar la BD
    _validate_jinja_syntax("subject_template", updates.get("subject_template"))
    _validate_jinja_syntax("title_template", updates.get("title_template"))
    _validate_jinja_syntax("body_template", updates.get("body_template"))

    before = _tpl_to_dict(tpl)

    for key, val in updates.items():
        setattr(tpl, key, val)
    tpl.updated_by_id = int(user["sub"])

    after = _tpl_to_dict(tpl)
    log_config_change(
        db=db,
        user_id=int(user["sub"]),
        entity_type="notification",
        entity_id=tpl_id,
        action="update",
        before=before,
        after=after,
        ip=client_ip(request),
    )

    try:
        db.commit()
        db.refresh(tpl)
        invalidate_notification_templates()
        logger.info(
            "Plantilla de notificación '%s' (id=%s) actualizada por usuario %s",
            tpl.code, tpl_id, user["sub"],
        )
        return {"success": True, "data": _tpl_to_dict(tpl)}
    except Exception as exc:
        db.rollback()
        logger.error("Error actualizando plantilla %s: %r", tpl_id, exc)
        raise HTTPException(status_code=500, detail="Error interno al actualizar plantilla")


@router.patch("/{tpl_id}/toggle")
def toggle_notification_template(
    tpl_id: int,
    request: Request,
    body: ToggleNotificationTemplate,
    user: dict = require_perms("maint", ["maint.config.notifications.api.update"]),
    db: DbSession = None,
):
    """Activa o desactiva una plantilla de notificación."""
    from itcj2.apps.maint.models.notification_template import MaintNotificationTemplate

    tpl = db.get(MaintNotificationTemplate, tpl_id)
    if not tpl:
        raise HTTPException(status_code=404, detail="Plantilla de notificación no encontrada")

    before = _tpl_to_dict(tpl)
    tpl.is_active = body.is_active
    tpl.updated_by_id = int(user["sub"])
    after = _tpl_to_dict(tpl)

    log_config_change(
        db=db,
        user_id=int(user["sub"]),
        entity_type="notification",
        entity_id=tpl_id,
        action="toggle",
        before=before,
        after=after,
        ip=client_ip(request),
    )

    try:
        db.commit()
        db.refresh(tpl)
        invalidate_notification_templates()
        estado = "activada" if body.is_active else "desactivada"
        logger.info(
            "Plantilla '%s' (id=%s) %s por usuario %s",
            tpl.code, tpl_id, estado, user["sub"],
        )
        return {"success": True, "data": _tpl_to_dict(tpl)}
    except Exception as exc:
        db.rollback()
        logger.error("Error en toggle de plantilla %s: %r", tpl_id, exc)
        raise HTTPException(status_code=500, detail="Error interno al cambiar estado de plantilla")


@router.post("/{tpl_id}/preview")
def preview_notification_template(
    tpl_id: int,
    request: Request,
    body: PreviewNotificationTemplate,
    user: dict = require_perms("maint", ["maint.config.notifications.api.preview"]),
    db: DbSession = None,
):
    """
    Renderiza la plantilla con un ticket real (si ticket_id se provee) o con datos dummy.
    Nunca lanza por variable faltante — usa ChainableUndefined.
    Devuelve 'warnings' con las variables declaradas en el template pero no presentes
    en el contexto de preview.
    """
    from itcj2.apps.maint.models.notification_template import MaintNotificationTemplate
    from jinja2 import ChainableUndefined, meta
    from jinja2.sandbox import SandboxedEnvironment

    tpl = db.get(MaintNotificationTemplate, tpl_id)
    if not tpl:
        raise HTTPException(status_code=404, detail="Plantilla de notificación no encontrada")

    # Construir contexto de renderizado
    if body.ticket_id is not None:
        from itcj2.apps.maint.models.ticket import MaintTicket
        ticket = db.get(MaintTicket, body.ticket_id)
        if not ticket:
            raise HTTPException(status_code=404, detail=f"Ticket id={body.ticket_id} no encontrado")
        requester = getattr(ticket, 'requester', None)
        technician = None
        active_tech_ids = [t.user_id for t in getattr(ticket, 'active_technicians', [])]
        if active_tech_ids:
            from itcj2.core.models.user import User
            technician = db.get(User, active_tech_ids[0])
        context = {
            'ticket': ticket,
            'requester': requester,
            'technician': technician,
        }
    else:
        ticket, requester, technician = _build_dummy_ticket()
        context = {
            'ticket': ticket,
            'requester': requester,
            'technician': technician,
        }

    # SandboxedEnvironment + autoescape: preview no debe permitir SSTI→RCE
    # ni emitir HTML sin escapar (paridad con render_notification).
    env = SandboxedEnvironment(undefined=ChainableUndefined, autoescape=True)

    def _render_safe(template_str):
        if not template_str:
            return None
        try:
            return env.from_string(template_str).render(**context)
        except Exception as exc:
            logger.warning("preview: error renderizando plantilla id=%s: %s", tpl_id, exc)
            return f"[Error de render: {exc}]"

    def _find_undeclared(template_str):
        """Retorna variables usadas en la plantilla que no están en el contexto."""
        if not template_str:
            return []
        try:
            ast = env.parse(template_str)
            undeclared = meta.find_undeclared_variables(ast)
            return [v for v in undeclared if v not in context]
        except Exception:
            return []

    # Recopilar advertencias (variables en plantillas no provistas en el contexto)
    warnings = []
    for field_label, field_val in [
        ("subject_template", tpl.subject_template),
        ("title_template", tpl.title_template),
        ("body_template", tpl.body_template),
    ]:
        undeclared = _find_undeclared(field_val)
        for var in undeclared:
            msg = f"Variable '{var}' usada en {field_label} no está en el contexto de preview"
            if msg not in warnings:
                warnings.append(msg)

    return {
        "success": True,
        "data": {
            "subject": _render_safe(tpl.subject_template),
            "title": _render_safe(tpl.title_template),
            "body": _render_safe(tpl.body_template),
            "warnings": warnings,
        },
    }
