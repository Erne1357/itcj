"""Contexto compartido de las páginas de *trabajo* de Calidad.

"Trabajo" = incidencias, eventos de programa, sus tareas y la pantalla de
asignación de responsables. Son las seis páginas que en el legacy vivían en
``routes/pages/incidents.py`` y ``routes/pages/programs.py`` y que compartían el
90 % del contexto (categorías, áreas, procesos y usuarios) copiado y pegado
cinco veces con criterios distintos: unas rutas filtraban ``is_active=True`` y
otras no, y todas mandaban ``User.query.all()`` a la plantilla para que Jinja
armara ``<option>`` **como HTML crudo dentro de un template literal**
(``htmlUsers``), que era el peor de los siete vectores de XSS del frontend.

Aquí ese contexto se calcula **una sola vez**, se devuelve como estructuras de
datos planas y viaja al navegador dentro del bloque ``page_data_script()``
(``|tojson``), nunca como markup.

Este módulo **no expone ``router``** a propósito: no es un módulo de páginas,
es la capa de contexto que consumen ``pages/incidents.py`` y
``pages/programs.py``. La fase de cableado no tiene que incluirlo.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any, Iterable, Optional, Sequence

from sqlalchemy.orm import Session

from itcj2.apps.adhoc.utils.constants import APP_KEY

logger = logging.getLogger(__name__)

__all__ = [
    "APP_KEY",
    "TASK_WRITE_PERMS",
    "catalog_options",
    "assignable_users",
    "granted",
    "page_context",
    "tasks_page_context",
    "task_assignee_ids",
    "task_notified_ids",
    "safe_return_to",
]

#: Permisos de escritura de la pantalla de tareas. Solo ocultan botones: el gate
#: real vive en ``require_perms`` de ``/api/adhoc/v2/tasks``.
TASK_WRITE_PERMS = (
    "adhoc.tasks.api.create",
    "adhoc.tasks.api.update",
    "adhoc.tasks.api.delete",
    "adhoc.tasks.api.assign",
)

#: Tope de usuarios que se serializan al ``page_data``. El picker filtra en
#: cliente, así que la lista entera viaja en el HTML; sin tope, una plantilla de
#: 8 000 usuarios pesaría megas. El SGC trabaja con la plantilla administrativa,
#: no con el alumnado, así que 500 sobra de largo.
MAX_USERS = 500


# ==========================================================================
# Catálogos
# ==========================================================================

def _named_rows(rows: Iterable[Any]) -> list[dict]:
    """``[{'id': …, 'name': …, 'color': …}]`` — solo campos serializables."""
    out: list[dict] = []
    for row in rows or []:
        item = {"id": row.id, "name": row.name}
        color = getattr(row, "color", None)
        if color:
            item["color"] = color
        out.append(item)
    return out


def catalog_options(db: Session, *, category_model: str) -> dict[str, list[dict]]:
    """Categorías + áreas + procesos, listos para los ``<select>``.

    ``category_model`` es el nombre de la clase del catálogo de categorías del
    dominio (``AdhocIncidentCategory`` o ``AdhocProgramCategory``): es lo único
    que cambia entre incidencias y eventos de programa.

    Las **áreas se filtran a las activas** (``is_active=True``). En el legacy la
    columna era nullable y las rutas de página mandaban ``Area.query.all()`` sin
    filtro mientras la API sí filtraba, así que un área dada de baja seguía
    ofreciéndose en el formulario.
    """
    from itcj2.apps.adhoc import models as adhoc_models
    from itcj2.apps.adhoc.services.catalog_service import AdhocCatalogService

    categories = AdhocCatalogService.list_items(db, getattr(adhoc_models, category_model))
    areas = AdhocCatalogService.list_items(db, adhoc_models.AdhocArea, is_active=True)
    processes = AdhocCatalogService.list_items(db, adhoc_models.AdhocProcess)

    return {
        "categories": _named_rows(categories),
        "areas": _named_rows(areas),
        "processes": _named_rows(processes),
    }


# ==========================================================================
# Usuarios asignables
# ==========================================================================

def assignable_users(db: Session) -> list[dict]:
    """Usuarios que pueden ser responsables o validadores dentro de Calidad.

    El criterio es **el mismo que deja entrar a la app**
    (``users_with_assignment_select``, las cuatro vías de ``require_app``:
    rol o permiso directo, rol o permiso heredado de un puesto vigente), no
    ``User.query.all()`` como hacía el legacy — que ofrecía los ~20 000 usuarios
    del padrón, alumnado incluido, para ser responsable de una incidencia del
    SGC.

    No se usa ``UserAdminService.list_users`` aquí a propósito: aquella solo ve
    los accesos **directos** (``core_user_app_roles``) porque su pantalla
    escribe en esa tabla, y dejaría fuera a quien entra por puesto.

    Devuelve dicts planos con la forma que consume ``shared/user-picker.js``
    (``id``, ``full_name``, ``email``, ``position``, ``department``).
    """
    from itcj2.core.models.department import Department
    from itcj2.core.models.position import Position, UserPosition
    from itcj2.core.models.user import User
    from itcj2.core.services.authz_service import users_with_assignment_select

    rows = (
        db.query(
            User.id,
            User.first_name,
            User.last_name,
            User.middle_name,
            User.email,
            Position.title.label("position_title"),
            Department.name.label("department_name"),
        )
        .outerjoin(
            UserPosition,
            (UserPosition.user_id == User.id) & (UserPosition.is_active.is_(True)),
        )
        .outerjoin(
            Position,
            (Position.id == UserPosition.position_id) & (Position.is_active.is_(True)),
        )
        .outerjoin(Department, Department.id == Position.department_id)
        .filter(
            User.is_active.is_(True),
            User.id.in_(users_with_assignment_select(db, APP_KEY)),
        )
        .order_by(User.last_name.asc(), User.first_name.asc(), User.id.asc())
        .all()
    )

    out: list[dict] = []
    seen: set[int] = set()
    for row in rows:
        # Un usuario con dos puestos vigentes aparece dos veces en el join.
        if row.id in seen:
            continue
        seen.add(row.id)
        nombre = " ".join(
            part for part in (row.first_name, row.last_name, row.middle_name) if part
        ).strip()
        out.append({
            "id": row.id,
            "full_name": nombre or f"#{row.id}",
            "email": row.email,
            "position": row.position_title,
            "department": row.department_name,
        })
        if len(out) >= MAX_USERS:
            break
    return out


# ==========================================================================
# Permisos (solo para ocultar botones)
# ==========================================================================

def granted(db: Session, user: Optional[dict], codes: Sequence[str]) -> dict[str, bool]:
    """``{code: bool}`` para los permisos de *escritura* de una pantalla.

    Sirve **solo para ocultar botones**: el gate real lo ponen
    ``require_page_app`` en la página y ``require_perms`` en la API. Un fallo al
    calcular permisos devuelve todo en ``False`` (fail-closed): enseñar un botón
    que después responde 403 es peor que no enseñarlo.

    El admin global del JWT (``role == "admin"``) ve todos los botones, igual
    que ``require_perms`` lo deja pasar por diseño.
    """
    codigos = list(codes or [])
    if not user:
        return {code: False for code in codigos}
    if user.get("role") == "admin":
        return {code: True for code in codigos}

    from itcj2.core.services.authz_cache import cached_perms

    try:
        efectivos = cached_perms(db, int(user["sub"]), APP_KEY)
    except Exception as exc:  # pragma: no cover — depende del estado de la BD
        logger.warning("adhoc: no se pudieron calcular permisos de UI (%s)", exc)
        return {code: False for code in codigos}

    return {code: code in efectivos for code in codigos}


# ==========================================================================
# Contexto base de página
# ==========================================================================

def page_context(db: Session, user: Optional[dict], **extra: Any) -> dict:
    """Contexto mínimo que TODA página de esta sección debe pasar a ``render_adhoc``.

    Hoy es el ``nav`` filtrado por permisos (regla 6 de las de templates), más
    lo que aporte cada página. Existe para que añadir algo transversal al shell
    no obligue a tocar las seis páginas.
    """
    from itcj2.apps.adhoc.pages.nav import nav_for_user

    ctx: dict = {"nav": nav_for_user(db, user), "today": date.today().isoformat()}
    ctx.update(extra)
    return ctx


def tasks_page_context(
    db: Session,
    user: Optional[dict],
    *,
    parent: Any,
    parent_type: str,
    back_url: str,
    parent_label: str,
) -> dict:
    """Contexto de ``adhoc/work/tasks.html`` — **idéntico para los dos padres**.

    En el legacy los dos consumidores del mismo template pasaban contextos
    distintos: la ruta de programas añadía un ``notified_map`` que la plantilla
    nunca leía, y la de incidencias no lo pasaba. Aquí hay una sola función, así
    que las dos pantallas no pueden divergir.
    """
    from itcj2.apps.adhoc.utils.constants import PRIORITIES, TASK_STATUSES

    permisos = granted(db, user, TASK_WRITE_PERMS)

    page_data = {
        "statuses": list(TASK_STATUSES),
        "priorities": list(PRIORITIES),
        "parent_type": parent_type,
        "parent_id": parent.id,
        "parent_title": parent.title,
        "parent_folio": parent.folio,
        "parent_status": parent.status,
        "api": "/api/adhoc/v2/tasks",
        "table_id": "adhoc-table-tasks",
        "assign_url": "/adhoc/asignaciones",
        "back_url": back_url,
        "users": assignable_users(db),
        "can": {
            "create": permisos["adhoc.tasks.api.create"],
            "update": permisos["adhoc.tasks.api.update"],
            "delete": permisos["adhoc.tasks.api.delete"],
            "assign": permisos["adhoc.tasks.api.assign"],
        },
        "labels": {"parent": parent_label},
    }

    articulo = "la" if parent_label.endswith("a") else "el"

    return {
        **page_context(db, user),
        "page_data": page_data,
        "page_title": f"Tareas de {articulo} {parent_label}",
        "parent": {
            "id": parent.id,
            "folio": parent.folio,
            "title": parent.title,
            "status": parent.status,
        },
        "parent_type": parent_type,
        "parent_label": parent_label,
        "back_url": back_url,
        "can_create": page_data["can"]["create"],
    }


# ==========================================================================
# Selección actual de la pantalla de asignación
# ==========================================================================

def task_assignee_ids(db: Session, task_id: int) -> list[int]:
    """Ids de los responsables actuales de la tarea, en orden estable."""
    from itcj2.apps.adhoc.models import adhoc_task_assignees

    rows = db.execute(
        adhoc_task_assignees.select()
        .where(adhoc_task_assignees.c.task_id == task_id)
        .order_by(adhoc_task_assignees.c.user_id)
    ).fetchall()
    return [row.user_id for row in rows]


def task_notified_ids(db: Session, task_id: int) -> list[int]:
    """Ids marcados para el aviso de vencimiento de la tarea.

    El legacy resolvía esto con una consulta a pelo repetida en dos rutas de
    página (``programs.py:56`` y su gemela), y la de incidencias directamente
    **no lo hacía**: abrir "Notificar atraso" desde una incidencia mostraba los
    responsables en vez de los ya notificados.
    """
    from itcj2.apps.adhoc.models import adhoc_task_assignees

    rows = db.execute(
        adhoc_task_assignees.select()
        .where(
            adhoc_task_assignees.c.task_id == task_id,
            adhoc_task_assignees.c.notified_overdue.is_(True),
        )
        .order_by(adhoc_task_assignees.c.user_id)
    ).fetchall()
    return [row.user_id for row in rows]


# ==========================================================================
# Vuelta segura
# ==========================================================================

def safe_return_to(value: Optional[str], fallback: str) -> str:
    """Valida el ``?return_to=`` de la pantalla de asignación.

    Solo se acepta una ruta **relativa dentro de la propia app** (``/adhoc/…``).
    Cualquier otra cosa —URL absoluta, ``//host`` protocol-relative, ``\\host``,
    o una ruta de otra app— cae al *fallback*. Sin esto la pantalla sería un
    redirector abierto: el legacy usaba ``history.back()``, que no se puede
    forzar desde fuera, así que introducir un parámetro de vuelta introduce un
    riesgo que hay que cerrar aquí.
    """
    ruta = (value or "").strip()
    if not ruta:
        return fallback
    # "//evil.com" y "/\evil.com" son URLs de host en los navegadores.
    if not ruta.startswith("/") or ruta.startswith("//") or ruta.startswith("/\\"):
        return fallback
    if not (ruta == "/adhoc" or ruta.startswith("/adhoc/")):
        return fallback
    return ruta
