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

Lo único que el tablero añade sobre el legacy es el **aviso de vigencia
documental** (``_expiry_notice``): dos conteos que no salen de las tareas del
usuario sino de ``adhoc_documents``. Está aquí y no en la API porque la página
ya se renderiza server-side y el aviso tiene que estar pintado en el primer
byte —un contador que aparece medio segundo tarde no lo ve nadie.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any, Optional

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func
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

#: Permiso de la consulta de documentos, que es a donde enlaza el aviso de
#: vigencia. Quien no lo tiene no ve el aviso **ni paga su query**: enseñarle
#: "45 documentos vencidos" a alguien que no puede abrir ni uno es filtrarle el
#: estado del SGC y mandarlo a un 403.
DOCUMENTS_PERM = "adhoc.documents.page.list"

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


def _can_list_documents(db: Session, user: dict) -> bool:
    """¿Puede este usuario abrir ``/adhoc/documentos``?

    Mismo patrón que `_action_flags` —admin global bypasea, el resto pasa por
    `cached_perms`— y deliberadamente **sin fusionarse** con él: sus dos flags
    son el contrato que el template y sus tests ya asumen, y este permiso no
    oculta un botón sino que decide si la query del aviso llega a ejecutarse.
    La segunda llamada no cuesta otra consulta: `cached_perms` sirve el mismo
    set desde su caché.
    """
    if user.get("role") == "admin":
        return True

    from itcj2.core.services.authz_cache import cached_perms

    try:
        return DOCUMENTS_PERM in cached_perms(db, int(user["sub"]), "adhoc")
    except Exception as exc:  # pragma: no cover - defensivo
        logger.warning("adhoc dashboard: no se pudo resolver %s: %s", DOCUMENTS_PERM, exc)
        return False


def _expiry_notice(db: Session, user: dict, today: date) -> Optional[dict]:
    """Documentos **vigentes** cuya vigencia ya caducó (y los que están por caducar).

    "Vigente" aquí es ``is_current``: la punta de la cadena de versiones, o sea
    el archivo que la gente se baja. Que esa punta tenga ``expiration_date`` en
    el pasado es el hallazgo más barato de levantar en una auditoría ISO 9001
    —control de documentos, cláusula 7.5.3— y hasta hoy no se veía desde
    ninguna pantalla: de 202 documentos hay 197 con vigencia, 47 ya vencidos y
    **45 de ellos siguen marcados como la versión vigente**.

    Devuelve ``None`` (el template no pinta nada) en tres casos, todos
    deliberados: sin permiso de consulta, si la query falla —igual que
    `_creator_names`, el tablero es lo que la gente viene a ver y no se cae por
    un contador— y cuando los dos conteos son cero, que es el estado sano.

    Es **una sola** query de conteo: dos agregados con ``FILTER (WHERE …)``
    sobre el mismo barrido, nunca las filas. Traerlas para hacer ``len()``
    costaría 202 documentos con sus catálogos para pintar dos números.
    """
    if not _can_list_documents(db, user):
        return None

    from itcj2.apps.adhoc.models import AdhocDocument
    from itcj2.apps.adhoc.utils.constants import DOCUMENT_EXPIRY_SOON_DAYS

    limite = today + timedelta(days=DOCUMENT_EXPIRY_SOON_DAYS)

    try:
        # Los dos predicados son los mismos cubos de `list_documents`
        # ('vencidos' y 'por_vencer_30d'), para que el número del aviso y el
        # número de filas que devuelve el enlace no puedan discrepar.
        row = (
            db.query(
                func.count()
                .filter(AdhocDocument.expiration_date < today)
                .label("vencidos"),
                func.count()
                .filter(
                    AdhocDocument.expiration_date >= today,
                    AdhocDocument.expiration_date <= limite,
                )
                .label("por_vencer"),
            )
            .select_from(AdhocDocument)
            .filter(
                AdhocDocument.is_current.is_(True),
                AdhocDocument.expiration_date.isnot(None),
            )
            .one()
        )
        vencidos = int(row.vencidos or 0)
        por_vencer = int(row.por_vencer or 0)
    except Exception as exc:  # pragma: no cover - defensivo
        logger.warning("adhoc dashboard: no se pudo contar la vigencia documental: %s", exc)
        return None

    if not vencidos and not por_vencer:
        return None

    # El número lo lleva la pastilla, así que el texto NO lo repite: solo
    # concuerda en singular/plural con ella.
    return {
        "expired": vencidos,
        "soon": por_vencer,
        "expired_text": (
            "documentos vigentes están vencidos" if vencidos != 1
            else "documento vigente está vencido"
        ),
        "soon_text": (
            f"documentos vigentes vencen en los próximos {DOCUMENT_EXPIRY_SOON_DAYS} días"
            if por_vencer != 1
            else f"documento vigente vence en los próximos {DOCUMENT_EXPIRY_SOON_DAYS} días"
        ),
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
            "expiry": _expiry_notice(db, user, today),
            "user_name": user.get("name") or "Usuario",
            "page_data": {
                "user_id": uid,
                "can_workflow": flags["can_workflow"],
                "can_comment": flags["can_comment"],
            },
        },
    )
