"""API v2 de los **seis catálogos simples** de Adhoc (Calidad).

======================================  ==========================================
Recurso                                 Permisos (``database/DML/adhoc/init/``)
======================================  ==========================================
``/areas``                              ``adhoc.areas.api.{read,create,update,delete}``
``/processes``                          ``adhoc.processes.api.{read,create,update,delete}``
``/document-categories``                ``adhoc.doc_catalogs.api.{read,create,update,delete}``
``/document-classifications``           ``adhoc.doc_catalogs.api.{read,create,update,delete}``
``/incident-categories``                ``adhoc.incident_categories.api.{read,create,update,delete}``
``/program-categories``                 ``adhoc.program_categories.api.{read,create,update,delete}``
======================================  ==========================================

Los seis exponen el mismo cuarteto — ``GET ""`` · ``POST ""`` (alta masiva) ·
``PATCH /{id}`` · ``DELETE /{id}`` — así que se generan desde una sola fábrica
(:func:`_build_router`) alimentada por la tabla :data:`_RESOURCES`. Es el
"colapso de duplicación" del plan §6.5 aplicado al backend: el legacy tenía
estas 18 rutas repartidas en cinco módulos con tres contratos distintos de
payload (``form nombres[]/colores[]``, ``form name``, ``json {"nombres": []}``)
y tres formas distintas de fallar (302 "exitoso", 404 JSON, 500 JSON).

Contrato de esta API (plan §3):

* lista → ``{"success": true, "data": [...], "total": N}``
* alta masiva → ``201`` con ``data`` = lo realmente creado, más ``skipped`` /
  ``skipped_count`` / ``message``. **Un nombre duplicado ya no tumba el lote**:
  se omite, se reporta y el resto entra.
* ítem → ``{"success": true, "data": {...}}``
* borrado → ``{"success": true, "message": "..."}``
* error → ``HTTPException(detail="texto")``; el handler global lo entrega como
  ``{"error": "texto", "status": N}``. Mapa de estados:
  :class:`CatalogNotFound` → 404, :class:`CatalogDuplicate` /
  :class:`CatalogInUse` → 409, el resto de :class:`CatalogError` → 400.

**Nota para la fase de cableado:** este módulo expone ``router`` sin prefijo
propio, ya compuesto por los seis sub-routers con su segmento de recurso.
Basta con ``adhoc_router.include_router(catalogs_router)`` — sin ``prefix`` —
para obtener ``/api/adhoc/v2/areas``, ``/api/adhoc/v2/processes``, etc. Los
seis sub-routers también se exportan sueltos por si se prefiere incluirlos uno
a uno con su propio ``prefix``.

Este módulo NO usa ``from __future__ import annotations`` a propósito: la
fábrica anota los parámetros con clases resueltas en tiempo de definición y
FastAPI necesita el objeto, no la cadena.
"""
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from itcj2.apps.adhoc.schemas.catalogs import (
    AreaBulkCreate,
    AreaOut,
    AreaUpdate,
    NamedCatalogBulkCreate,
    NamedCatalogOut,
    NamedCatalogUpdate,
    ProcessBulkCreate,
    ProcessOut,
    ProcessUpdate,
)
from itcj2.apps.adhoc.schemas.common import ok_item, ok_list, ok_message
from itcj2.apps.adhoc.services.catalog_service import (
    CatalogDuplicate,
    CatalogError,
    CatalogInUse,
    CatalogNotFound,
)
from itcj2.dependencies import DbSession, require_perms

logger = logging.getLogger(__name__)

__all__ = [
    "router",
    "areas_router",
    "processes_router",
    "document_categories_router",
    "document_classifications_router",
    "incident_categories_router",
    "program_categories_router",
]


# ==========================================================================
# Helpers
# ==========================================================================

def _http_error(exc: CatalogError) -> HTTPException:
    """Traduce el error del service al status HTTP correcto, con ``detail`` STRING."""
    if isinstance(exc, CatalogNotFound):
        status = 404
    elif isinstance(exc, (CatalogDuplicate, CatalogInUse)):
        status = 409
    else:
        status = 400
    return HTTPException(status_code=status, detail=str(exc))


def _dump(out_schema, obj) -> dict:
    return out_schema.model_validate(obj).model_dump(mode="json")


def _model(name: str):
    """Resuelve la clase del modelo. Import local (CLAUDE.md §5, gotcha 2)."""
    from itcj2.apps.adhoc import models as adhoc_models

    return getattr(adhoc_models, name)


def _service():
    from itcj2.apps.adhoc.services.catalog_service import AdhocCatalogService

    return AdhocCatalogService


# ==========================================================================
# Fábrica de routers
# ==========================================================================

def _build_router(
    *,
    key: str,
    tag: str,
    model_name: str,
    out_schema,
    bulk_schema,
    update_schema,
    perm_read: str,
    perm_create: str,
    perm_update: str,
    perm_delete: str,
    deleted_message: str,
    has_is_active: bool = False,
) -> APIRouter:
    """Genera el cuarteto CRUD de un catálogo. El prefijo lo pone el padre."""
    r = APIRouter(tags=[tag])

    # ------------------------------------------------------------ GET ""
    if has_is_active:
        def list_items(
            search: Optional[str] = Query(None, max_length=100, description="Filtra por nombre"),
            is_active: Optional[bool] = Query(
                None,
                description="Filtra por estado. Omitido = activos e inactivos.",
            ),
            user: dict = require_perms("adhoc", [perm_read]),
            db: DbSession = None,
        ):
            items = _service().list_items(
                db, _model(model_name), is_active=is_active, search=search
            )
            return ok_list([_dump(out_schema, i) for i in items])
    else:
        def list_items(
            search: Optional[str] = Query(None, max_length=100, description="Filtra por nombre"),
            user: dict = require_perms("adhoc", [perm_read]),
            db: DbSession = None,
        ):
            items = _service().list_items(db, _model(model_name), search=search)
            return ok_list([_dump(out_schema, i) for i in items])

    list_items.__name__ = f"list_{key}"
    list_items.__doc__ = f"Lista el catálogo completo ordenado por nombre. Permiso: ``{perm_read}``."
    r.get("", summary=f"Listar {key}")(list_items)

    # ----------------------------------------------------------- POST ""
    def bulk_create(
        body: bulk_schema,
        user: dict = require_perms("adhoc", [perm_create]),
        db: DbSession = None,
    ):
        try:
            result = _service().bulk_create(
                db,
                _model(model_name),
                [item.model_dump() for item in body.items],
            )
        except CatalogError as exc:
            raise _http_error(exc) from exc

        logger.info(
            "adhoc/%s: alta masiva por usuario %s — %d creado(s), %d omitido(s)",
            key, user.get("sub"), result.created_count, result.skipped_count,
        )
        return {
            "success": True,
            "data": [_dump(out_schema, obj) for obj in result.created],
            "total": result.created_count,
            "skipped": result.skipped,
            "skipped_count": result.skipped_count,
            "message": result.message,
        }

    bulk_create.__name__ = f"bulk_create_{key}"
    bulk_create.__doc__ = (
        f"Alta masiva deduplicada. Permiso: ``{perm_create}``.\n\n"
        "Los nombres que ya existen (sin distinguir mayúsculas) o que se repiten "
        "dentro del propio payload se **omiten** y se devuelven en ``skipped``; "
        "el resto se crea. El legacy revertía el lote completo por un solo duplicado."
    )
    r.post("", status_code=201, summary=f"Alta masiva de {key}")(bulk_create)

    # ------------------------------------------------------- PATCH /{id}
    def update_item(
        item_id: int,
        body: update_schema,
        user: dict = require_perms("adhoc", [perm_update]),
        db: DbSession = None,
    ):
        try:
            item = _service().update(
                db, _model(model_name), item_id, body.model_dump(exclude_unset=True)
            )
        except CatalogError as exc:
            raise _http_error(exc) from exc

        logger.info("adhoc/%s#%s actualizado por usuario %s", key, item_id, user.get("sub"))
        return ok_item(_dump(out_schema, item))

    update_item.__name__ = f"update_{key}"
    update_item.__doc__ = (
        f"Actualización parcial. Permiso: ``{perm_update}``.\n\n"
        "Solo se aplican los campos enviados. Un id inexistente responde 404 "
        "(el legacy lo convertía en un redirect \"exitoso\") y un nombre ya "
        "tomado responde 409."
    )
    r.patch("/{item_id}", summary=f"Actualizar {key}")(update_item)

    # ------------------------------------------------------ DELETE /{id}
    def delete_item(
        item_id: int,
        user: dict = require_perms("adhoc", [perm_delete]),
        db: DbSession = None,
    ):
        try:
            _service().delete(db, _model(model_name), item_id)
        except CatalogError as exc:
            raise _http_error(exc) from exc

        logger.info("adhoc/%s#%s eliminado por usuario %s", key, item_id, user.get("sub"))
        return ok_message(deleted_message)

    delete_item.__name__ = f"delete_{key}"
    delete_item.__doc__ = (
        f"Elimina un registro del catálogo. Permiso: ``{perm_delete}``.\n\n"
        "Si hay documentos, incidencias o eventos que lo referencian responde "
        "**409** con el desglose, en vez del ``IntegrityError`` tragado del legacy."
    )
    r.delete("/{item_id}", summary=f"Eliminar {key}")(delete_item)

    return r


# ==========================================================================
# Los seis catálogos
# ==========================================================================

areas_router = _build_router(
    key="areas",
    tag="adhoc-areas",
    model_name="AdhocArea",
    out_schema=AreaOut,
    bulk_schema=AreaBulkCreate,
    update_schema=AreaUpdate,
    perm_read="adhoc.areas.api.read",
    perm_create="adhoc.areas.api.create",
    perm_update="adhoc.areas.api.update",
    perm_delete="adhoc.areas.api.delete",
    deleted_message="Área eliminada",
    has_is_active=True,
)

processes_router = _build_router(
    key="processes",
    tag="adhoc-processes",
    model_name="AdhocProcess",
    out_schema=ProcessOut,
    bulk_schema=ProcessBulkCreate,
    update_schema=ProcessUpdate,
    perm_read="adhoc.processes.api.read",
    perm_create="adhoc.processes.api.create",
    perm_update="adhoc.processes.api.update",
    perm_delete="adhoc.processes.api.delete",
    deleted_message="Proceso eliminado",
)

document_categories_router = _build_router(
    key="document_categories",
    tag="adhoc-document-categories",
    model_name="AdhocDocumentCategory",
    out_schema=NamedCatalogOut,
    bulk_schema=NamedCatalogBulkCreate,
    update_schema=NamedCatalogUpdate,
    perm_read="adhoc.doc_catalogs.api.read",
    perm_create="adhoc.doc_catalogs.api.create",
    perm_update="adhoc.doc_catalogs.api.update",
    perm_delete="adhoc.doc_catalogs.api.delete",
    deleted_message="Categoría de documento eliminada",
)

document_classifications_router = _build_router(
    key="document_classifications",
    tag="adhoc-document-classifications",
    model_name="AdhocDocumentClassification",
    out_schema=NamedCatalogOut,
    bulk_schema=NamedCatalogBulkCreate,
    update_schema=NamedCatalogUpdate,
    perm_read="adhoc.doc_catalogs.api.read",
    perm_create="adhoc.doc_catalogs.api.create",
    perm_update="adhoc.doc_catalogs.api.update",
    perm_delete="adhoc.doc_catalogs.api.delete",
    deleted_message="Clasificación de documento eliminada",
)

incident_categories_router = _build_router(
    key="incident_categories",
    tag="adhoc-incident-categories",
    model_name="AdhocIncidentCategory",
    out_schema=NamedCatalogOut,
    bulk_schema=NamedCatalogBulkCreate,
    update_schema=NamedCatalogUpdate,
    perm_read="adhoc.incident_categories.api.read",
    perm_create="adhoc.incident_categories.api.create",
    perm_update="adhoc.incident_categories.api.update",
    perm_delete="adhoc.incident_categories.api.delete",
    deleted_message="Categoría de incidencia eliminada",
)

program_categories_router = _build_router(
    key="program_categories",
    tag="adhoc-program-categories",
    model_name="AdhocProgramCategory",
    out_schema=NamedCatalogOut,
    bulk_schema=NamedCatalogBulkCreate,
    update_schema=NamedCatalogUpdate,
    perm_read="adhoc.program_categories.api.read",
    perm_create="adhoc.program_categories.api.create",
    perm_update="adhoc.program_categories.api.update",
    perm_delete="adhoc.program_categories.api.delete",
    deleted_message="Categoría de programa eliminada",
)


#: Router agregado: los seis recursos ya con su segmento de URL. El padre lo
#: incluye **sin prefijo** (``adhoc_router.include_router(catalogs_router)``).
router = APIRouter()
router.include_router(areas_router, prefix="/areas")
router.include_router(processes_router, prefix="/processes")
router.include_router(document_categories_router, prefix="/document-categories")
router.include_router(document_classifications_router, prefix="/document-classifications")
router.include_router(incident_categories_router, prefix="/incident-categories")
router.include_router(program_categories_router, prefix="/program-categories")
