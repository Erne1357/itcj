"""
API de plantillas de notificación — SOLO edición de contenido (edit + toggle + preview).
No permite crear ni borrar plantillas (decisión de producto; las gestiona el seed).
Espejo de itcj2/apps/helpdesk/api/config/statuses.py.
"""
import logging

from fastapi import APIRouter, HTTPException, Request
from itcj2.dependencies import DbSession, require_perms
from itcj2.apps.helpdesk.schemas.config.notifications import (
    UpdateNotificationTemplateRequest,
    ToggleNotificationTemplateRequest,
    PreviewNotificationRequest,
)

router = APIRouter(tags=["helpdesk-config-notifications"])
logger = logging.getLogger(__name__)

# Datos dummy reutilizables para preview sin ticket real
_DUMMY_PREVIEW_CONTEXT: dict = {
    "ticket": {
        "ticket_number": "HD-2026-00042",
        "title": "Ejemplo de título de ticket",
        "description": "Descripción de ejemplo del problema reportado.",
        "status": "PENDING",
        "priority": "MEDIA",
        "area": "SOPORTE",
        "created_at": "2026-05-11T10:30:00",
    },
    "requester": {"id": 1, "name": "Juan Pérez", "email": "juan@ejemplo.com"},
    "assignee": {"id": 2, "name": "Ana Técnica", "email": "ana@ejemplo.com"},
    "previous_assignee": {"id": 3, "name": "Luis Previo"},
    "commenter": {"id": 4, "name": "María Comentarista"},
    "comment": {"content": "Texto del comentario de ejemplo."},
}


@router.get("")
def list_notification_templates(
    include_inactive: str = "false",
    user: dict = require_perms("helpdesk", ["helpdesk.config.notifications.api.read"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.models.notification_template import NotificationTemplate

    query = db.query(NotificationTemplate)
    if include_inactive.lower() != "true":
        query = query.filter_by(is_active=True)

    templates = query.order_by(NotificationTemplate.id).all()
    return {"templates": [t.to_dict() for t in templates], "total": len(templates)}


@router.get("/{template_id}")
def get_notification_template(
    template_id: int,
    user: dict = require_perms("helpdesk", ["helpdesk.config.notifications.api.read"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.models.notification_template import NotificationTemplate

    template = db.get(NotificationTemplate, template_id)
    if not template:
        raise HTTPException(
            404,
            detail={"error": "not_found", "message": "Plantilla de notificación no encontrada"},
        )

    return {"template": template.to_dict(include_updated_by=True)}


@router.patch("/{template_id}")
def update_notification_template(
    template_id: int,
    body: UpdateNotificationTemplateRequest,
    request: Request,
    user: dict = require_perms("helpdesk", ["helpdesk.config.notifications.api.update"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.models.notification_template import NotificationTemplate
    from itcj2.apps.helpdesk.services.config_audit_service import log_config_change
    from itcj2.apps.helpdesk.utils.catalog_cache import invalidate_notification_templates
    import jinja2

    user_id = int(user["sub"])
    template = db.get(NotificationTemplate, template_id)
    if not template:
        raise HTTPException(
            404,
            detail={"error": "not_found", "message": "Plantilla de notificación no encontrada"},
        )

    # Validar sintaxis Jinja del body_template antes de persistir
    if body.body_template is not None:
        try:
            jinja2.Environment().parse(body.body_template)
        except jinja2.TemplateSyntaxError as exc:
            raise HTTPException(
                400,
                detail={
                    "error": "invalid_template_syntax",
                    "message": f"Error de sintaxis en body_template (línea {exc.lineno}): {exc.message}",
                },
            )

    # Validar sintaxis Jinja del subject_template si se provee
    if body.subject_template is not None:
        try:
            jinja2.Environment().parse(body.subject_template)
        except jinja2.TemplateSyntaxError as exc:
            raise HTTPException(
                400,
                detail={
                    "error": "invalid_template_syntax",
                    "message": f"Error de sintaxis en subject_template (línea {exc.lineno}): {exc.message}",
                },
            )

    before = template.to_dict()

    changes = body.model_dump(exclude_none=True)
    for field, value in changes.items():
        setattr(template, field, value)
    template.updated_by_id = user_id

    log_config_change(
        db=db,
        user_id=user_id,
        entity_type="notification_template",
        entity_id=template.id,
        action="update",
        before=before,
        after=template.to_dict(),
        ip_address=request.client.host if request.client else None,
    )

    db.commit()
    db.refresh(template)
    invalidate_notification_templates()

    logger.info(
        f"Plantilla {template_id} ({template.code}) actualizada por usuario {user_id}"
    )
    return {
        "message": "Plantilla actualizada exitosamente",
        "template": template.to_dict(include_updated_by=True),
    }


@router.post("/{template_id}/toggle")
def toggle_notification_template(
    template_id: int,
    body: ToggleNotificationTemplateRequest,
    request: Request,
    user: dict = require_perms("helpdesk", ["helpdesk.config.notifications.api.update"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.models.notification_template import NotificationTemplate
    from itcj2.apps.helpdesk.services.config_audit_service import log_config_change
    from itcj2.apps.helpdesk.utils.catalog_cache import invalidate_notification_templates

    user_id = int(user["sub"])
    template = db.get(NotificationTemplate, template_id)
    if not template:
        raise HTTPException(
            404,
            detail={"error": "not_found", "message": "Plantilla de notificación no encontrada"},
        )

    before = template.to_dict()
    template.is_active = body.is_active
    template.updated_by_id = user_id

    log_config_change(
        db=db,
        user_id=user_id,
        entity_type="notification_template",
        entity_id=template.id,
        action="toggle",
        before=before,
        after=template.to_dict(),
        ip_address=request.client.host if request.client else None,
    )

    db.commit()
    db.refresh(template)
    invalidate_notification_templates()

    action_label = "activada" if body.is_active else "desactivada"
    logger.info(
        f"Plantilla {template_id} ({template.code}) {action_label} por usuario {user_id}"
    )
    return {
        "message": f"Plantilla {action_label} exitosamente",
        "template": template.to_dict(),
    }


@router.post("/{template_id}/preview")
def preview_notification_template(
    template_id: int,
    body: PreviewNotificationRequest,
    request: Request,
    user: dict = require_perms("helpdesk", ["helpdesk.config.notifications.api.preview"]),
    db: DbSession = None,
):
    """
    Renderiza la plantilla con Jinja2 contra datos reales, datos de muestra o datos dummy.
    Usa DebugUndefined para que variables no definidas se rendericen como placeholder
    literal '{{ variable }}' en lugar de lanzar excepción, y se reportan como warnings.
    """
    from itcj2.apps.helpdesk.models.notification_template import NotificationTemplate
    import jinja2
    import jinja2.meta

    template = db.get(NotificationTemplate, template_id)
    if not template:
        raise HTTPException(
            404,
            detail={"error": "not_found", "message": "Plantilla de notificación no encontrada"},
        )

    # Construir contexto de renderizado
    context: dict = {}
    warnings: list[str] = []

    if body.ticket_id is not None:
        # Cargar ticket real con joinedload de relaciones relevantes
        from itcj2.apps.helpdesk.models.ticket import Ticket
        from sqlalchemy.orm import joinedload

        ticket = (
            db.query(Ticket)
            .options(
                joinedload(Ticket.requester),
                joinedload(Ticket.assigned_to),
                joinedload(Ticket.category),
            )
            .filter(Ticket.id == body.ticket_id)
            .first()
        )
        if not ticket:
            raise HTTPException(
                404,
                detail={"error": "ticket_not_found", "message": f"Ticket #{body.ticket_id} no encontrado"},
            )

        context["ticket"] = {
            "ticket_number": ticket.ticket_number,
            "title": ticket.title,
            "description": ticket.description,
            "status": ticket.status,
            "priority": ticket.priority,
            "area": ticket.area,
            "created_at": ticket.created_at.isoformat() if ticket.created_at else None,
        }
        if ticket.requester:
            context["requester"] = {
                "id": ticket.requester.id,
                "name": ticket.requester.full_name,
                "email": ticket.requester.email,
            }
        if ticket.assigned_to:
            context["assignee"] = {
                "id": ticket.assigned_to.id,
                "name": ticket.assigned_to.full_name,
                "email": ticket.assigned_to.email,
            }

    elif body.sample_data is not None:
        # Override directo con datos proporcionados por el cliente
        context = body.sample_data

    else:
        # Datos dummy razonables para previsualización sin datos reales
        context = dict(_DUMMY_PREVIEW_CONTEXT)

    # ChainableUndefined permite encadenar atributos en variables no definidas
    # ({{ foo.bar.baz }}) sin lanzar UndefinedError; renderiza como "".
    # Las variables top-level faltantes se detectan via jinja2.meta antes de renderizar.
    env = jinja2.Environment(
        undefined=jinja2.ChainableUndefined,
        autoescape=False,
    )

    rendered_subject: str | None = None
    rendered_body: str = ""

    def _detect_missing(template_str: str) -> set[str]:
        try:
            ast = env.parse(template_str)
            return jinja2.meta.find_undeclared_variables(ast) - set(context.keys())
        except jinja2.TemplateError:
            return set()

    try:
        if template.subject_template:
            missing_subject = _detect_missing(template.subject_template)
            rendered_subject = env.from_string(template.subject_template).render(context)
            if missing_subject:
                warnings.append(
                    "subject_template: variables no definidas: "
                    + ", ".join(sorted(missing_subject))
                )

        missing_body = _detect_missing(template.body_template)
        rendered_body = env.from_string(template.body_template).render(context)
        if missing_body:
            warnings.append(
                "body_template: variables no definidas: "
                + ", ".join(sorted(missing_body))
            )

    except jinja2.TemplateError as exc:
        raise HTTPException(
            422,
            detail={
                "error": "render_error",
                "message": f"Error al renderizar la plantilla: {exc}",
            },
        )

    return {
        "subject": rendered_subject,
        "body": rendered_body,
        "channel": template.channel,
        "warnings": warnings,
    }
