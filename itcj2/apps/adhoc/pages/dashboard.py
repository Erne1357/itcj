"""Página del **tablero de tareas** de Calidad — ``GET /adhoc/dashboard``.

Es la landing de la app y la puerta al workflow (plan §3.b), así que se
renderiza **server-side**: el tablero sale de
``AdhocTaskService.get_dashboard_tasks(db, user_id)`` y llega al template ya
convertido en dicts planos. El modal de workflow sí consume la API
(``GET /api/adhoc/v2/tasks/{id}/workflow`` y sus tres acciones).

Por qué dicts y no objetos ORM en el template: ``get_dashboard_tasks`` hace
``selectinload`` de ``assignees``, ``comments``, ``document``, ``incident``,
``program`` y ``flow_step``, pero **no** de ``created_by``. Tocar
``task.created_by`` dentro del bucle de Jinja dispararía un SELECT por tarjeta
—exactamente el N+1 del legacy (bug #8)—, así que los nombres de los
solicitantes se resuelven aquí con **una sola** query en lote y el template no
navega ninguna relación.

Origen legacy: ``routes/pages/general.py:47-84`` +
``templates/app_prueba/dashboard/dashboard.html`` (260 líneas de JS inline, 110
de ``<style>``, 10 ``onclick=`` y 3 modales caseros; todo eso vive ahora en
``static/js/dashboard/dashboard.js``, ``static/css/dashboard/dashboard.css`` y
``{% block modals %}``).
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any, Optional

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from itcj2.apps.adhoc.pages.nav import nav_for_user
from itcj2.apps.adhoc.pages.render import render_adhoc
from itcj2.database import get_db
from itcj2.dependencies import require_page_app

logger = logging.getLogger(__name__)

#: Sin prefijo propio: lo pone `pages/router.py` (`prefix="/adhoc"`).
router = APIRouter()

#: Permiso de la página (plan §4).
DASHBOARD_PERM = "adhoc.dashboard.page.view"

#: Permisos que solo **ocultan botones**. El gate real lo ponen
#: `require_page_app` aquí y `require_perms` en cada endpoint de la API.
WORKFLOW_PERM = "adhoc.tasks.api.workflow"
COMMENT_PERM = "adhoc.tasks.api.comment"

#: Abreviaturas de mes en español. `strftime('%b')` depende del locale del
#: proceso (en el contenedor es "C" → "Aug"), y el legacy lo usaba a pelo.
_MONTHS = ("ene", "feb", "mar", "abr", "may", "jun",
           "jul", "ago", "sep", "oct", "nov", "dic")

#: Etiqueta visible del padre de la tarea. Las tres FK son excluyentes por
#: `ck_adhoc_tasks_single_parent`, así que no hay ambigüedad posible.
_PARENT_LABELS = {
    "document": "Documento ISO",
    "program": "Programa",
    "incident": "Incidencia",
}

#: Estados en los que una fecha vencida ya no reclama atención: la tarea o está
#: cerrada o está en manos de otro.
_SETTLED_STATUSES = ("Completada", "En Revisión")


def _format_date(value: Optional[date]) -> str:
    """``12 ago 2026`` — o el texto del legacy cuando no hay fecha."""
    if value is None:
        return "Sin fecha"
    return f"{value.day:02d} {_MONTHS[value.month - 1]} {value.year}"


def _creator_names(db: Session, tasks: list) -> dict[int, str]:
    """``{user_id: nombre}`` de los solicitantes, en **una** query.

    Devuelve ``{}`` si ninguna tarea tiene creador (así no se lanza la query) o
    si la consulta falla: la tarjeta cae a "Sistema", que es lo que el legacy
    pintaba cuando `creator` era ``None``.
    """
    ids = {int(t.created_by_id) for t in tasks if getattr(t, "created_by_id", None)}
    if not ids:
        return {}

    from itcj2.core.models.user import User

    try:
        rows = db.query(User).filter(User.id.in_(ids)).all()
    except Exception as exc:  # pragma: no cover - defensivo
        logger.warning("adhoc dashboard: no se pudieron cargar los solicitantes: %s", exc)
        return {}

    return {int(u.id): (getattr(u, "full_name", None) or "Sistema") for u in rows}


def _parent_of(task: Any) -> tuple[Optional[str], Optional[Any]]:
    """``(kind, parent)`` según cuál de las tres FK está poblada."""
    if getattr(task, "incident_id", None):
        return "incident", getattr(task, "incident", None)
    if getattr(task, "program_id", None):
        return "program", getattr(task, "program", None)
    if getattr(task, "document_id", None):
        return "document", getattr(task, "document", None)
    return None, None


def build_card(task: Any, creators: dict[int, str], today: date) -> dict:
    """View-model de una tarjeta del tablero.

    Todo lo que el template necesita, ya resuelto: sin `strftime` con locale,
    sin navegar relaciones y sin lógica de negocio en Jinja.
    """
    kind, parent = _parent_of(task)
    status = task.status
    due = task.due_date

    vencida = bool(due and due < today and status not in _SETTLED_STATUSES)

    return {
        "id": task.id,
        "description": task.description,
        "status": status,
        "priority": task.priority,
        "due_label": _format_date(due),
        "is_overdue": vencida,
        # El legacy resaltaba la tarjeta por vencimiento O por prioridad urgente.
        "needs_attention": vencida or task.priority == "Urgente",
        "is_rejected": status == "Rechazada",
        "is_review": status == "En Revisión",
        "is_locked": status == "En Espera",
        "parent_kind": kind,
        "parent_label": _PARENT_LABELS.get(kind or "", "Sin origen"),
        "parent_title": getattr(parent, "title", None),
        "parent_version": getattr(parent, "version", None) if kind == "document" else None,
        "creator_name": creators.get(int(task.created_by_id or 0), "Sistema"),
        "comments_count": len(task.comments or []),
    }


def _action_flags(db: Session, user: dict) -> dict[str, bool]:
    """Flags de UI para los botones del modal (no son el gate, solo la vista)."""
    if user.get("role") == "admin":
        return {"can_workflow": True, "can_comment": True}

    from itcj2.core.services.authz_cache import cached_perms

    try:
        perms = cached_perms(db, int(user["sub"]), "adhoc")
    except Exception as exc:  # pragma: no cover - defensivo
        logger.warning("adhoc dashboard: no se pudieron calcular permisos: %s", exc)
        perms = set()

    return {
        "can_workflow": WORKFLOW_PERM in perms,
        "can_comment": COMMENT_PERM in perms,
    }


@router.get("/dashboard")
def dashboard(
    request: Request,
    user: dict = Depends(require_page_app("adhoc", perms=[DASHBOARD_PERM])),
    db: Session = Depends(get_db),
):
    """Tablero de "mis tareas" + modal de workflow.

    El legacy tenía aquí ``@login_required`` **encima** de ``@bp.route``, o sea
    ningún gate en absoluto (bug #25): la página era pública.
    """
    from itcj2.apps.adhoc.services.task_service import AdhocTaskService

    uid = int(user["sub"])
    tasks = AdhocTaskService.get_dashboard_tasks(db, uid)

    today = date.today()
    creators = _creator_names(db, tasks)
    cards = [build_card(t, creators, today) for t in tasks]

    flags = _action_flags(db, user)

    return render_adhoc(
        request,
        "adhoc/dashboard/dashboard.html",
        {
            "nav": nav_for_user(db, user),
            "cards": cards,
            "user_name": user.get("name") or "Usuario",
            "page_data": {
                "user_id": uid,
                "can_workflow": flags["can_workflow"],
                "can_comment": flags["can_comment"],
            },
        },
    )
