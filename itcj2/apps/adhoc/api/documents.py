"""API v2 de documentos del SGC (Adhoc / Calidad).

Monta en ``/api/adhoc/v2/documents`` — el prefijo lo pone el router padre, aquí
solo se declara ``APIRouter(tags=["adhoc-documents"])``.

Tres cosas que el legacy no hacía y aquí son obligatorias:

* **Permiso en todos los endpoints**, la descarga incluida. En el legacy
  ``GET /api/documentos/descargar/<id>`` era anónima: bastaba iterar ids para
  bajarse el SGC completo.
* **Errores de verdad.** ``raise HTTPException(status_code=..., detail="texto")``
  con ``detail`` **string**; el handler global lo envuelve como
  ``{"error": "<texto>", "status": N}``. El legacy respondía 302 "exitoso"
  después de tragarse la excepción, o ``success: false`` con HTTP 200.
* **Sobre de respuesta uniforme** (``schemas/common.ok_*``).

Sobre el ``PATCH``: es ``multipart/form-data`` como el ``POST``, y distingue
"campo no enviado" (``None`` de Python → no se toca) de "campo enviado vacío"
(``""`` → se limpia la columna). Por eso los ``Form`` son opcionales sin default
y el dict de cambios se arma con los que llegaron: es lo que hace que
``model_dump(exclude_unset=True)`` signifique algo en un PATCH.
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any, Optional, Sequence

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import ValidationError

from itcj2.apps.adhoc.schemas.documents import StartFlowIn
from itcj2.dependencies import DbSession, require_perms

router = APIRouter(tags=["adhoc-documents"])
logger = logging.getLogger(__name__)

#: Campos que acepta el PATCH (nombre del Form == nombre de la columna).
_PATCH_FIELDS = (
    "code", "title", "version", "status", "notes",
    "category_id", "area_id", "process_id", "classification_id",
)


# ==========================================================================
# Utilidades locales
# ==========================================================================

@contextmanager
def _domain_errors():
    """Traduce el contrato de excepciones de los services a HTTP.

    ``LookupError`` → 404 · ``AdhocConflict`` → 409 · ``PermissionError`` → 403 ·
    ``ValueError`` → 400. Siempre con ``detail`` **string**.
    """
    from itcj2.apps.adhoc.services.document_service import AdhocConflict

    try:
        yield
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc) or "No encontrado") from exc
    except AdhocConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _at(seq: Optional[Sequence[Any]], index: int) -> Any:
    """Elemento ``index`` de una lista de ``Form``, o ``None`` si no llegó."""
    if not seq or index >= len(seq):
        return None
    return seq[index]


def _validation_message(exc: ValidationError, *, row: Optional[int] = None) -> str:
    """Primer error de Pydantic en una línea legible (el ``detail`` es string)."""
    err = exc.errors()[0]
    campo = ".".join(str(p) for p in err.get("loc", ())) or "payload"
    prefijo = f"Fila {row}: " if row is not None else ""
    return f"{prefijo}{campo}: {err.get('msg', 'valor inválido')}"


# ==========================================================================
# Listado y detalle
# ==========================================================================

@router.get("")
def list_documents(
    request: Request,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=200),
    q: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    category_id: Optional[str] = Query(None),
    area_id: Optional[str] = Query(None),
    process_id: Optional[str] = Query(None),
    classification_id: Optional[str] = Query(None),
    flow_id: Optional[str] = Query(None),
    author_id: Optional[str] = Query(None),
    user: dict = require_perms("adhoc", ["adhoc.documents.api.read"]),
    db: DbSession = None,
):
    """Listado paginado con filtros.

    Los filtros llegan como strings crudos a propósito: el ``<select>`` manda
    ``""`` para "todos", y ``DocumentFilters`` lo coacciona a ``None``. Un
    ``status`` inventado es un **400 legible**, no un 500 por ``ValidationError``.
    """
    from itcj2.apps.adhoc.schemas.common import ok_page
    from itcj2.apps.adhoc.schemas.documents import DocumentFilters, document_out
    from itcj2.apps.adhoc.services.document_service import AdhocDocumentService

    try:
        filters = DocumentFilters(
            q=q, status=status, category_id=category_id, area_id=area_id,
            process_id=process_id, classification_id=classification_id,
            flow_id=flow_id, author_id=author_id,
        )
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=_validation_message(exc)) from exc

    with _domain_errors():
        result = AdhocDocumentService.list_documents(
            db, filters, page=page, per_page=per_page,
        )
    return ok_page([document_out(d) for d in result.items], result, page, per_page)


@router.get("/{document_id}")
def get_document(
    request: Request,
    document_id: int,
    user: dict = require_perms("adhoc", ["adhoc.documents.api.read"]),
    db: DbSession = None,
):
    """Detalle de un documento, con flujo y paso actual resueltos."""
    from itcj2.apps.adhoc.schemas.common import ok_item
    from itcj2.apps.adhoc.schemas.documents import document_out
    from itcj2.apps.adhoc.services.document_service import AdhocDocumentService

    with _domain_errors():
        doc = AdhocDocumentService.get(db, document_id)
    return ok_item(document_out(doc, detail=True))


# ==========================================================================
# Alta masiva
# ==========================================================================

@router.post("")
def create_documents(
    request: Request,
    titles: list[str] = Form(default=[]),
    codes: list[str] = Form(default=[]),
    versions: list[str] = Form(default=[]),
    notes: list[str] = Form(default=[]),
    category_ids: list[str] = Form(default=[]),
    area_ids: list[str] = Form(default=[]),
    process_ids: list[str] = Form(default=[]),
    classification_ids: list[str] = Form(default=[]),
    files: list[UploadFile] = File(default=[]),
    user: dict = require_perms("adhoc", ["adhoc.documents.api.create"]),
    db: DbSession = None,
):
    """Alta masiva ``multipart/form-data``; un archivo opcional por fila.

    Las listas son **paralelas por índice** (``titles[i]`` ↔ ``files[i]``). Las
    filas en blanco del formulario se descartan junto con su hueco de archivo,
    de modo que la alineación se conserva; si no queda ninguna fila útil es un
    400, no el "302 exitoso" del legacy con cero inserciones.
    """
    from itcj2.apps.adhoc.schemas.common import ok_list
    from itcj2.apps.adhoc.schemas.documents import DocumentCreate, document_out
    from itcj2.apps.adhoc.services.document_service import AdhocDocumentService

    total = max(len(titles), len(codes), len(versions), len(notes),
                len(category_ids), len(area_ids), len(process_ids),
                len(classification_ids))

    items: list[DocumentCreate] = []
    uploads: list[Any] = []
    for i in range(total):
        title = (_at(titles, i) or "").strip()
        if not title:
            continue
        raw = {
            "title": title,
            "code": _at(codes, i),
            "version": _at(versions, i),
            "notes": _at(notes, i),
            "category_id": _at(category_ids, i),
            "area_id": _at(area_ids, i),
            "process_id": _at(process_ids, i),
            "classification_id": _at(classification_ids, i),
        }
        try:
            items.append(DocumentCreate.model_validate(raw))
        except ValidationError as exc:
            raise HTTPException(
                status_code=422, detail=_validation_message(exc, row=i + 1),
            ) from exc
        uploads.append(_at(files, i))

    if not items:
        raise HTTPException(
            status_code=400, detail="No se recibió ningún documento para guardar",
        )

    with _domain_errors():
        docs = AdhocDocumentService.bulk_create(
            db, items, author_id=int(user["sub"]), uploads=uploads,
        )
    return ok_list([document_out(d) for d in docs])


# ==========================================================================
# Edición y borrado
# ==========================================================================

@router.patch("/{document_id}")
def update_document(
    request: Request,
    document_id: int,
    code: Optional[str] = Form(default=None),
    title: Optional[str] = Form(default=None),
    version: Optional[str] = Form(default=None),
    status: Optional[str] = Form(default=None),
    notes: Optional[str] = Form(default=None),
    category_id: Optional[str] = Form(default=None),
    area_id: Optional[str] = Form(default=None),
    process_id: Optional[str] = Form(default=None),
    classification_id: Optional[str] = Form(default=None),
    file: Optional[UploadFile] = File(default=None),
    user: dict = require_perms("adhoc", ["adhoc.documents.api.update"]),
    db: DbSession = None,
):
    """Edición parcial (``multipart/form-data``), con reemplazo opcional del archivo.

    Solo se aplican los campos **presentes** en el formulario; mandar un campo
    vacío limpia la columna. El archivo anterior se borra del disco cuando llega
    uno nuevo.
    """
    from itcj2.apps.adhoc.schemas.common import ok_item
    from itcj2.apps.adhoc.schemas.documents import DocumentUpdate, document_out
    from itcj2.apps.adhoc.services.document_service import AdhocDocumentService

    enviados = {
        "code": code, "title": title, "version": version, "status": status,
        "notes": notes, "category_id": category_id, "area_id": area_id,
        "process_id": process_id, "classification_id": classification_id,
    }
    changes = {k: v for k, v in enviados.items() if v is not None}

    if not changes and (file is None or not (file.filename or "").strip()):
        raise HTTPException(status_code=400, detail="No se envió ningún cambio")

    try:
        payload = DocumentUpdate.model_validate(changes)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=_validation_message(exc)) from exc

    with _domain_errors():
        doc = AdhocDocumentService.update(db, document_id, payload, upload=file)
    return ok_item(document_out(doc, detail=True))


@router.delete("/{document_id}")
def delete_document(
    request: Request,
    document_id: int,
    user: dict = require_perms("adhoc", ["adhoc.documents.api.delete"]),
    db: DbSession = None,
):
    """Elimina el documento, sus tareas (cascade) y su archivo adjunto."""
    from itcj2.apps.adhoc.schemas.common import ok_message
    from itcj2.apps.adhoc.services.document_service import AdhocDocumentService

    with _domain_errors():
        AdhocDocumentService.delete(db, document_id)
    return ok_message("Documento eliminado correctamente")


# ==========================================================================
# Descarga
# ==========================================================================

@router.get("/{document_id}/download")
def download_document(
    request: Request,
    document_id: int,
    user: dict = require_perms("adhoc", ["adhoc.documents.api.download"]),
    db: DbSession = None,
):
    """Descarga el archivo del documento.

    Exige ``adhoc.documents.api.download``: en el legacy esta ruta era anónima y
    permitía enumerar ids y bajarse todo el SGC.
    """
    from itcj2.apps.adhoc.services.document_service import AdhocDocumentService

    with _domain_errors():
        path, filename = AdhocDocumentService.resolve_download(db, document_id)
    return FileResponse(path, filename=filename)


# ==========================================================================
# Arranque del flujo de aprobación
# ==========================================================================

@router.post("/{document_id}/start-flow")
def start_document_flow(
    request: Request,
    document_id: int,
    payload: Optional[StartFlowIn] = None,
    user: dict = require_perms("adhoc", ["adhoc.documents.api.start_flow"]),
    db: DbSession = None,
):
    """Inicia el flujo de aprobación del documento (plan §10.b).

    Crea una tarea por paso con un *snapshot* de los validadores, deja la
    primera en ``En Revisión`` y notifica (in-app + correo, ambos fail-soft).
    El mensaje distingue si el correo salió, igual que el legacy.
    """
    from itcj2.apps.adhoc.schemas.common import ok_item
    from itcj2.apps.adhoc.schemas.documents import document_out
    from itcj2.apps.adhoc.services.document_flow_service import AdhocDocumentFlowService

    flow_id = payload.flow_id if payload is not None else None

    with _domain_errors():
        result = AdhocDocumentFlowService.start_flow(
            db, document_id, flow_id, actor_id=int(user["sub"]),
        )

    data = document_out(result["document"], detail=True)
    data["message"] = result["message"]
    data["email_sent"] = result["email_sent"]
    return ok_item(data)
