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
"campo no enviado" (no se toca) de "campo enviado vacío" (se limpia la columna).
Es lo que hace que ``model_dump(exclude_unset=True)`` signifique algo en un
PATCH… y lo que obliga a declarar sus ``Form`` como **listas**: ver
:func:`_first`. Con ``Optional[str]`` esa distinción no existe, porque FastAPI
convierte el campo vacío en el default antes de que el endpoint lo vea.
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from datetime import date
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
    "code", "title", "version", "status", "notes", "expiration_date",
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


def _first(values: Optional[list[str]]) -> Optional[str]:
    """Primer valor de un campo del PATCH, o ``None`` si el formulario no lo trajo.

    Los ``Form`` del PATCH se declaran ``Optional[list[str]]`` y no
    ``Optional[str]`` por una razón muy concreta, y no por gusto: FastAPI trata
    un campo de texto **vacío** como si no se hubiera enviado y lo sustituye por
    el default antes de llamar al endpoint
    (``fastapi/dependencies/utils.py``: ``isinstance(field_info, params.Form)
    and isinstance(value, str) and value == ""`` → ``deepcopy(field.default)``).
    Con ``Optional[str] = Form(default=None)`` los dos casos llegan como
    ``None`` y **es imposible limpiar una columna por PATCH**: mandar la
    vigencia vacía para decir "este documento no vence" no hacía nada, en
    silencio, aunque el docstring prometiera lo contrario.

    Esa comprobación de FastAPI lleva un ``isinstance(value, str)``, así que un
    campo declarado como secuencia se salva: ausente llega ``None`` y vacío
    llega ``[""]``. El formato en el alambre no cambia —el navegador sigue
    mandando ``expiration_date=``—; lo único que cambia es que ahora el
    endpoint lo ve.
    """
    if not values:
        return None
    return values[0]


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
    only_current: str = Query("true"),
    expiring: Optional[str] = Query(None),
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

    ``only_current`` es ``str`` por lo mismo, no ``bool``: declararlo booleano
    haría que FastAPI rechazara con 422 un ``?only_current=`` vacío, que es
    justo lo que manda un formulario cuyo checkbox nunca se tocó. La coacción
    la hace ``query_flag_to_bool`` dentro del schema, y su default —ausente ⇒
    ``True``— es lo que mantiene ocultas las versiones superadas mientras el
    checkbox "Ver versiones anteriores" siga sin marcarse.

    ``expiring`` acepta ``vencidos`` | ``por_vencer_30d`` | ``vigentes``;
    cualquier otra cosa es un 400 con el mismo mensaje que un ``status`` malo.

    El ``hoy`` se calcula **una vez** y viaja al service y a ``document_out``:
    son las dos implementaciones del mismo criterio de vigencia (el ``WHERE`` y
    la aritmética del badge), y con un reloj cada una una página servida a
    caballo de la medianoche podía traer una fila filtrada como vencida y
    pintada como "por vencer".
    """
    from itcj2.apps.adhoc.schemas.common import ok_page
    from itcj2.apps.adhoc.schemas.documents import DocumentFilters, document_out
    from itcj2.apps.adhoc.services.document_service import AdhocDocumentService

    try:
        filters = DocumentFilters(
            q=q, status=status, only_current=only_current, expiring=expiring,
            category_id=category_id, area_id=area_id,
            process_id=process_id, classification_id=classification_id,
            flow_id=flow_id, author_id=author_id,
        )
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=_validation_message(exc)) from exc

    hoy = date.today()
    with _domain_errors():
        result = AdhocDocumentService.list_documents(
            db, filters, page=page, per_page=per_page, today=hoy,
        )
    return ok_page([document_out(d, today=hoy) for d in result.items],
                   result, page, per_page)


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


@router.get("/{document_id}/versions")
def list_document_versions(
    request: Request,
    document_id: int,
    user: dict = require_perms("adhoc", ["adhoc.documents.api.read"]),
    db: DbSession = None,
):
    """Historial completo de la cadena de versiones del documento.

    Es el respaldo de la decisión de ocultar las superadas en las dos listas:
    si el listado solo enseña la punta, tiene que haber **un** sitio donde se
    vean las 58 versiones anteriores, y este es. Da igual con qué id de la
    cadena se entre —raíz o versión—, la respuesta es la misma: la raíz primero
    y después las versiones por id ascendente.

    Sin permiso propio a propósito: exige el mismo ``adhoc.documents.api.read``
    que el detalle, porque no revela nada que ``GET /documents/{id}`` no
    revelara ya de cada fila por separado.
    """
    from itcj2.apps.adhoc.schemas.common import ok_list
    from itcj2.apps.adhoc.schemas.documents import document_out
    from itcj2.apps.adhoc.services.document_service import AdhocDocumentService

    hoy = date.today()
    with _domain_errors():
        versions = AdhocDocumentService.list_versions(db, document_id)
    return ok_list([document_out(d, today=hoy) for d in versions])


@router.get("/{document_id}/acknowledgements")
def list_document_acknowledgements(
    request: Request,
    document_id: int,
    user: dict = require_perms("adhoc", ["adhoc.documents.api.read"]),
    db: DbSession = None,
):
    """Difusión del documento: destinatarios, quién acusó recibo y cuándo.

    Es el panel que le da salida a las dos tablas que el ETL del SGC trajo con
    datos y la app no leía en ningún sitio: ``adhoc_document_visibility`` (la
    lista de distribución, 9 390 filas) y ``adhoc_document_acknowledgements``
    (los acuses con fecha real, 987 filas entre 2019 y 2025). La ISO 9001:2015
    §7.5.3 exige controlar la **distribución** de la información documentada;
    hasta hoy esa evidencia estaba en la base y en ninguna pantalla.

    Es **consulta histórica y nada más**: aquí no se registran acuses nuevos.
    Esa función es otra decisión de producto y va con su propio plan; lo que
    esta ruta hace es enseñar lo que ya ocurrió.

    Sin permiso propio, igual que ``/versions``: exige el mismo
    ``adhoc.documents.api.read`` que el detalle —lo tienen ``admin``,
    ``consult`` y ``supervisor_doc``—. Lo que añade sobre el detalle es **a
    quién se le distribuyó**, y eso sí es información nueva: por sus otros
    permisos ``consult`` podía enumerar 3 autores distintos y 8 validadores de
    paso, y aquí aparecen las 55 personas de ``adhoc_document_visibility``. Que
    el permiso baste se sostiene sobre lo que la respuesta **no** lleva: el
    destinatario viaja con ``id`` y ``name``, sin correo
    (:func:`~itcj2.apps.adhoc.schemas.documents._recipient_brief`), así que lo
    que se expone son nombres de personal del SGC —los mismos que ya salen en
    los desplegables de asignación— y no un directorio de direcciones
    enumerable documento a documento. Si alguna vez hace falta el correo aquí,
    lo que toca es un permiso propio, no ampliar este.

    ``_app_user_ids`` se importa de ``api/tasks.py`` en vez de reescribir la
    regla: es ``users_with_assignment_select`` + ``is_active``, el criterio con
    el que ``/adhoc/asignaciones`` llena sus pickers, y ya vivía duplicado en
    dos módulos. Cuesta dos queries fijas y es lo que permite marcar a los 26
    de 55 destinatarios históricos que hoy ya no pueden entrar a Calidad. Si
    devuelve ``None`` (sin fila de ``adhoc`` en ``core_apps``) el panel se sirve
    igual, sin la marca — un acuse de 2021 no deja de ser evidencia porque el
    servidor no pueda decir quién entra hoy.
    """
    from itcj2.apps.adhoc.api.tasks import _app_user_ids
    from itcj2.apps.adhoc.schemas.common import ok_item
    from itcj2.apps.adhoc.schemas.documents import acknowledgement_panel_out
    from itcj2.apps.adhoc.services.document_service import AdhocDocumentService

    con_acceso = _app_user_ids(db)
    with _domain_errors():
        panel = AdhocDocumentService.acknowledgement_panel(
            db, document_id, app_user_ids=con_acceso,
        )
    return ok_item(acknowledgement_panel_out(panel))


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
    expiration_dates: list[str] = Form(default=[]),
    parent_ids: list[str] = Form(default=[]),
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

    ``parent_ids[i]`` convierte la fila ``i`` en **una versión nueva** del
    documento indicado: el service la cuelga de la raíz de esa cadena y deja
    todas las versiones anteriores superadas. Es el "Anexar nueva versión" del
    panel de gestión, que reutiliza este mismo endpoint en vez de tener uno
    propio: el alta y el anexado difieren en un campo, no en un flujo.
    """
    from itcj2.apps.adhoc.schemas.common import ok_list
    from itcj2.apps.adhoc.schemas.documents import DocumentCreate, document_out
    from itcj2.apps.adhoc.services.document_service import AdhocDocumentService

    total = max(len(titles), len(codes), len(versions), len(notes),
                len(expiration_dates), len(parent_ids),
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
            "expiration_date": _at(expiration_dates, i),
            "parent_id": _at(parent_ids, i),
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

    hoy = date.today()
    with _domain_errors():
        docs = AdhocDocumentService.bulk_create(
            db, items, author_id=int(user["sub"]), uploads=uploads,
        )
    return ok_list([document_out(d, today=hoy) for d in docs])


# ==========================================================================
# Edición y borrado
# ==========================================================================

@router.patch("/{document_id}")
def update_document(
    request: Request,
    document_id: int,
    code: Optional[list[str]] = Form(default=None),
    title: Optional[list[str]] = Form(default=None),
    version: Optional[list[str]] = Form(default=None),
    status: Optional[list[str]] = Form(default=None),
    notes: Optional[list[str]] = Form(default=None),
    expiration_date: Optional[list[str]] = Form(default=None),
    category_id: Optional[list[str]] = Form(default=None),
    area_id: Optional[list[str]] = Form(default=None),
    process_id: Optional[list[str]] = Form(default=None),
    classification_id: Optional[list[str]] = Form(default=None),
    file: Optional[UploadFile] = File(default=None),
    user: dict = require_perms("adhoc", ["adhoc.documents.api.update"]),
    db: DbSession = None,
):
    """Edición parcial (``multipart/form-data``), con reemplazo opcional del archivo.

    Solo se aplican los campos **presentes** en el formulario; mandar un campo
    vacío limpia la columna —incluida ``expiration_date``, que es la forma de
    decir "este documento no vence"—. El archivo anterior se borra del disco
    cuando llega uno nuevo.

    Los ``Form`` son listas porque es la única manera de que el campo vacío
    llegue hasta aquí; ver :func:`_first`. El cliente no se entera: sigue
    mandando un valor por campo.

    ``is_current`` y ``parent_id`` **no** son campos del PATCH: la cadena de
    versiones se mueve solo al anexar una versión nueva (``POST``).

    **409 si el estado del documento no admite la edición.** El gate lo impone
    ``AdhocDocumentService.update`` —una versión superada no se edita, y solo
    se edita desde 'Borrador' y 'Rechazado'; el archivo, solo desde
    'Borrador'—, y llega aquí como :class:`AdhocConflict`, que
    :func:`_domain_errors` traduce a un 409 con ``detail`` **string**. Es un
    conflicto de estado, no un error de entrada: por eso 409 y no 400. El panel
    pinta el botón "Editar" deshabilitado usando ``is_editable`` /
    ``file_replaceable`` de ``document_out``, pero eso es comodidad; quien
    decide es el service.
    """
    from itcj2.apps.adhoc.schemas.common import ok_item
    from itcj2.apps.adhoc.schemas.documents import DocumentUpdate, document_out
    from itcj2.apps.adhoc.services.document_service import AdhocDocumentService

    enviados = {
        "code": _first(code), "title": _first(title), "version": _first(version),
        "status": _first(status), "notes": _first(notes),
        "expiration_date": _first(expiration_date),
        "category_id": _first(category_id), "area_id": _first(area_id),
        "process_id": _first(process_id),
        "classification_id": _first(classification_id),
    }
    # `None` es "no vino en el formulario"; `""` es "vino vacío" y sí viaja al
    # schema, que lo vuelve `None` dejando el campo *set* — que es como
    # `exclude_unset` distingue limpiar una columna de no tocarla.
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
