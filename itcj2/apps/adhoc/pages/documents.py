"""Páginas de **Documentos y flujos de aprobación** (Adhoc / Calidad).

Seis rutas (plan §4), todas montadas por el router padre con ``prefix="/adhoc"``:

======================================  ===============================  ============================
URL                                     Origen legacy                    Permiso de página
======================================  ===============================  ============================
``/documentos``                         ``documents.py:7`` (consulta)    ``adhoc.documents.page.list``
``/documentos/panel``                   ``documentos_panel``             ``adhoc.documents.page.manage``
``/documentos/categorias``              ``config_doc_categorias``        ``adhoc.doc_catalogs.page.list``
``/documentos/clasificaciones``         ``config_doc_clasificacion``     ``adhoc.doc_catalogs.page.list``
``/documentos/flujos``                  ``config_doc_flujos``            ``adhoc.flows.page.list``
``/documentos/flujos/{id}/pasos``       ``config_flujo_pasos``           ``adhoc.flows.page.list``
======================================  ===============================  ============================

Qué hace este módulo y qué NO
-----------------------------
Estas rutas **solo arman contexto de render**: catálogos para los ``<select>``,
banderas de capacidad para ocultar botones y el bloque ``page_data`` que consume
el JS. Los datos de negocio (documentos, flujos, pasos) los pide el navegador a
``/api/adhoc/v2/...``; aquí no se reimplementa nada de esa lógica (plan §D5).

Tres arreglos del legacy que viven en este archivo:

* **Bug #28** — ``documents.html`` iteraba ``categorias``, ``areas``, ``procesos``
  y ``clasificaciones`` para sus cuatro ``<select>`` de filtro, pero la ruta solo
  pasaba ``documentos``: los cuatro salían vacíos **en silencio**. Aquí los cuatro
  catálogos se consultan y se pasan siempre.
* **Bug #25** — el legacy ponía ``@login_required`` *encima* de ``@route``, así que
  no protegía nada. Las seis rutas van con ``Depends(require_page_app(...))``.
* **Los ``<option>`` pre-renderizados como HTML crudo** (``DOC_CONFIG.categoriasHtml``
  y sus tres hermanos, siete vectores de XSS) desaparecen: los catálogos viajan como
  **JSON** dentro de ``page_data`` y el DOM lo construye el JS con ``escapeHtml``.

Nota sobre ``require_page_*``: devuelve la función pelada, hay que envolverla en
``Depends``. ``require_perms``/``require_app`` (los de la API) ya devuelven
``Depends(...)`` y no se envuelven — la asimetría es del repo, no de esta app.
"""
from __future__ import annotations

import logging
from typing import Any, Optional, Sequence

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from itcj2.apps.adhoc.pages.nav import nav_for_user
from itcj2.apps.adhoc.pages.render import render_adhoc
from itcj2.database import get_db
from itcj2.dependencies import require_page_app

logger = logging.getLogger(__name__)

#: El prefijo ``/adhoc`` lo pone ``pages/router.py`` en la fase de cableado.
router = APIRouter()

#: Destino del botón "Volver" de las pantallas de catálogo y de flujos.
#: Es ``/adhoc/documentos`` y **no** el panel a propósito: el rol ``consult``
#: llega a categorías, clasificaciones y flujos (tiene ``doc_catalogs.page.list``
#: y ``flows.page.list``) pero NO a ``/documentos/panel`` (``documents.page.manage``),
#: así que un "Volver" al panel lo mandaría a un 403.
_BACK_TO_DOCUMENTS = "/adhoc/documentos"


# ==========================================================================
# Helpers de contexto
# ==========================================================================

def _effective_perms(db: Session, user: Optional[dict]) -> Optional[set[str]]:
    """Permisos efectivos del usuario en ``adhoc``.

    Devuelve ``None`` para el admin **global** del JWT, que bypasea
    ``require_perms`` en la API: representarlo como "todo permitido" evita que
    la UI le esconda botones que el servidor sí le deja usar.

    Un fallo al calcular permisos devuelve el conjunto vacío (fail-closed):
    los botones se ocultan, pero la página sigue en pie. El gate de verdad ya
    lo puso ``require_page_app`` antes de llegar aquí.
    """
    if not user:
        return set()
    if user.get("role") == "admin":
        return None

    from itcj2.core.services.authz_cache import cached_perms

    try:
        return cached_perms(db, int(user["sub"]), "adhoc")
    except Exception as exc:  # pragma: no cover - defensivo
        logger.warning("adhoc/documentos: no se pudieron calcular permisos: %s", exc)
        return set()


def _can(perms: Optional[set[str]], code: str) -> bool:
    """``True`` si el usuario tiene *code* (o es el admin global, ``perms=None``)."""
    return perms is None or code in perms


def _rows(items: Sequence[Any]) -> list[dict]:
    """Catálogo de solo-nombre → ``[{"id", "name"}]`` listo para ``|tojson``."""
    return [{"id": item.id, "name": item.name} for item in items]


def _options(rows: Sequence[dict]) -> list[dict]:
    """``[{"id","name"}]`` → la forma que espera la macro ``select_field``."""
    return [{"value": row["id"], "label": row["name"]} for row in rows]


def _document_catalogs(db: Session) -> dict[str, list[dict]]:
    """Los cuatro catálogos que alimentan filtros y alta de documentos.

    Cuatro consultas fijas y ordenadas por nombre. Las áreas se filtran por
    ``is_active``; el resto no tiene bandera de baja.
    """
    from itcj2.apps.adhoc.models import (
        AdhocArea,
        AdhocDocumentCategory,
        AdhocDocumentClassification,
        AdhocProcess,
    )

    return {
        "categories": _rows(
            db.query(AdhocDocumentCategory).order_by(AdhocDocumentCategory.name.asc()).all()
        ),
        "areas": _rows(
            db.query(AdhocArea)
            .filter(AdhocArea.is_active.is_(True))
            .order_by(AdhocArea.name.asc())
            .all()
        ),
        "processes": _rows(
            db.query(AdhocProcess).order_by(AdhocProcess.name.asc()).all()
        ),
        "classifications": _rows(
            db.query(AdhocDocumentClassification)
            .order_by(AdhocDocumentClassification.name.asc())
            .all()
        ),
    }


# ==========================================================================
# 1. Consulta de documentos
# ==========================================================================

@router.get("/documentos")
async def documents_page(
    request: Request,
    user: dict = Depends(require_page_app("adhoc", perms=["adhoc.documents.page.list"])),
    db: Session = Depends(get_db),
):
    """Vista de consulta del SGC: tabla filtrable y paginada.

    Los filtros se resuelven **en el servidor** (``GET /api/adhoc/v2/documents``),
    no en el DOM. El legacy filtraba en JS por índice de columna sobre la tabla ya
    pintada: con paginación eso solo filtraría la página visible, y además añadir
    una ``<td>`` desalineaba todos los filtros de la pantalla.
    """
    from itcj2.apps.adhoc.utils.constants import DOCUMENT_STATUSES

    catalogs = _document_catalogs(db)
    perms = _effective_perms(db, user)

    return render_adhoc(request, "adhoc/documents/documents.html", {
        "nav": nav_for_user(db, user),
        "categoria_options": _options(catalogs["categories"]),
        "area_options": _options(catalogs["areas"]),
        "proceso_options": _options(catalogs["processes"]),
        "clasificacion_options": _options(catalogs["classifications"]),
        "status_options": list(DOCUMENT_STATUSES),
        "page_data": {
            "per_page": 25,
            "can_download": _can(perms, "adhoc.documents.api.download"),
        },
    })


# ==========================================================================
# 2. Panel de administración de documentos
# ==========================================================================

@router.get("/documentos/panel")
async def documents_panel_page(
    request: Request,
    user: dict = Depends(require_page_app("adhoc", perms=["adhoc.documents.page.manage"])),
    db: Session = Depends(get_db),
):
    """Alta masiva con archivo, arranque de flujo y mantenimiento del SGC.

    Dos bloques del legacy **no se portan** (plan §4): el "Historial de Versiones
    Anteriores" (un mockup con ``<td>2025-01-15</td>`` a pelo y la versión
    calculada como ``version|float - 1.0``) y la celda ``<td>ISO 9001</td>`` de la
    columna "Sist. Gestión", que no corresponde a ninguna columna del modelo.
    """
    from itcj2.apps.adhoc.models import AdhocApprovalFlow
    from itcj2.apps.adhoc.utils.constants import DOCUMENT_STATUSES
    from itcj2.config import get_settings

    catalogs = _document_catalogs(db)
    perms = _effective_perms(db, user)

    flows = _rows(
        db.query(AdhocApprovalFlow).order_by(AdhocApprovalFlow.name.asc()).all()
    )

    extensions = [
        ext.strip().lower()
        for ext in (get_settings().ADHOC_ALLOWED_EXTENSIONS or "").split(",")
        if ext.strip()
    ]

    return render_adhoc(request, "adhoc/documents/documents_panel.html", {
        "nav": nav_for_user(db, user),
        "categoria_options": _options(catalogs["categories"]),
        "area_options": _options(catalogs["areas"]),
        "proceso_options": _options(catalogs["processes"]),
        "clasificacion_options": _options(catalogs["classifications"]),
        "status_options": list(DOCUMENT_STATUSES),
        "can_create": _can(perms, "adhoc.documents.api.create"),
        "page_data": {
            "per_page": 25,
            # Catálogos como JSON: el JS construye los <option> del alta masiva
            # con escapeHtml. El legacy inyectaba aquí HTML crudo con backticks.
            "categories": catalogs["categories"],
            "areas": catalogs["areas"],
            "processes": catalogs["processes"],
            "classifications": catalogs["classifications"],
            "flows": flows,
            "accept": [f".{ext}" for ext in extensions],
            "can_create": _can(perms, "adhoc.documents.api.create"),
            "can_delete": _can(perms, "adhoc.documents.api.delete"),
            "can_download": _can(perms, "adhoc.documents.api.download"),
            "can_start_flow": _can(perms, "adhoc.documents.api.start_flow"),
        },
    })


# ==========================================================================
# 3 y 4. Catálogos de documento (macro compartida + shared/catalog-crud.js)
# ==========================================================================

@router.get("/documentos/categorias")
async def document_categories_page(
    request: Request,
    user: dict = Depends(require_page_app("adhoc", perms=["adhoc.doc_catalogs.page.list"])),
    db: Session = Depends(get_db),
):
    """Categorías de documento. CRUD genérico: cero JS propio (plan §6.5)."""
    perms = _effective_perms(db, user)
    return render_adhoc(request, "adhoc/documents/document_categories.html", {
        "nav": nav_for_user(db, user),
        "back_url": _BACK_TO_DOCUMENTS,
        "can_create": _can(perms, "adhoc.doc_catalogs.api.create"),
        "can_update": _can(perms, "adhoc.doc_catalogs.api.update"),
        "can_delete": _can(perms, "adhoc.doc_catalogs.api.delete"),
    })


@router.get("/documentos/clasificaciones")
async def document_classifications_page(
    request: Request,
    user: dict = Depends(require_page_app("adhoc", perms=["adhoc.doc_catalogs.page.list"])),
    db: Session = Depends(get_db),
):
    """Clasificaciones de documento. Misma macro y mismo módulo que categorías."""
    perms = _effective_perms(db, user)
    return render_adhoc(request, "adhoc/documents/document_classifications.html", {
        "nav": nav_for_user(db, user),
        "back_url": _BACK_TO_DOCUMENTS,
        "can_create": _can(perms, "adhoc.doc_catalogs.api.create"),
        "can_update": _can(perms, "adhoc.doc_catalogs.api.update"),
        "can_delete": _can(perms, "adhoc.doc_catalogs.api.delete"),
    })


# ==========================================================================
# 5. Flujos de aprobación
# ==========================================================================

@router.get("/documentos/flujos")
async def flows_page(
    request: Request,
    user: dict = Depends(require_page_app("adhoc", perms=["adhoc.flows.page.list"])),
    db: Session = Depends(get_db),
):
    """Listado de flujos de aprobación con su número de pasos."""
    perms = _effective_perms(db, user)
    return render_adhoc(request, "adhoc/documents/flows.html", {
        "nav": nav_for_user(db, user),
        "back_url": _BACK_TO_DOCUMENTS,
        "can_create": _can(perms, "adhoc.flows.api.create"),
        "page_data": {
            "can_create": _can(perms, "adhoc.flows.api.create"),
            "can_update": _can(perms, "adhoc.flows.api.update"),
            "can_delete": _can(perms, "adhoc.flows.api.delete"),
        },
    })


# ==========================================================================
# 6. Pasos de un flujo + asignación de validadores
# ==========================================================================

@router.get("/documentos/flujos/{flow_id}/pasos")
async def flow_steps_page(
    request: Request,
    flow_id: int,
    user: dict = Depends(require_page_app("adhoc", perms=["adhoc.flows.page.list"])),
    db: Session = Depends(get_db),
):
    """Diseño del flujo: pasos (upsert por ``step_order``) y sus validadores.

    El universo de validadores son los usuarios que **pueden entrar a Calidad**
    (``users_with_assignment_select``, el mismo criterio que ``require_app``), no
    ``User.query.filter_by(is_active=True).all()`` como hacía el legacy: eso
    listaba el instituto entero, alumnado incluido.

    La lista viaja server-side en ``page_data`` en vez de pedirse a
    ``GET /api/adhoc/v2/users`` porque ese endpoint exige
    ``adhoc.users.api.read``, permiso que ``supervisor_doc`` **no** tiene: el
    selector le habría salido vacío con un 403 en la consola.
    """
    from itcj2.apps.adhoc.models import AdhocApprovalFlow
    from itcj2.core.models.user import User
    from itcj2.core.services.authz_service import users_with_assignment_select

    flow = db.get(AdhocApprovalFlow, flow_id)
    if flow is None:
        raise HTTPException(status_code=404, detail="El flujo de aprobación no existe")

    users = (
        db.query(User)
        .filter(
            User.is_active.is_(True),
            User.id.in_(users_with_assignment_select(db, "adhoc")),
        )
        .order_by(User.last_name.asc(), User.first_name.asc(), User.id.asc())
        .all()
    )

    perms = _effective_perms(db, user)

    return render_adhoc(request, "adhoc/documents/flow_steps.html", {
        "nav": nav_for_user(db, user),
        "flow": {"id": flow.id, "name": flow.name, "description": flow.description},
        "back_url": "/adhoc/documentos/flujos",
        "can_update": _can(perms, "adhoc.flows.api.update"),
        "can_assign": _can(perms, "adhoc.flows.api.assign"),
        "page_data": {
            "flow_id": flow.id,
            "can_update": _can(perms, "adhoc.flows.api.update"),
            "can_assign": _can(perms, "adhoc.flows.api.assign"),
            "users": [
                {
                    "id": u.id,
                    "full_name": u.full_name,
                    "email": u.email,
                    "username": u.username,
                }
                for u in users
            ],
        },
    })
