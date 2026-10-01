"""Schemas Pydantic v2 de documentos y flujos de aprobación (Adhoc / Calidad).

Dos bloques:

* **Entrada** — lo que valida la API antes de tocar el ORM. Todo campo con
  ``CheckConstraint`` detrás se declara con el ``Literal`` de
  ``utils/constants.py`` (regla 1 del plan §2.8), y los ``""`` del ``<select>``
  placeholder se coaccionan a ``None`` heredando de :class:`AdhocSchema`
  (regla 2). Los campos ``NOT NULL`` con default (``version``, ``days_limit``)
  usan ``blank_to_default`` porque un ``""`` entrante los dejaría en ``None`` y
  ``None`` no satisface el tipo (regla 4).
* **Salida** — funciones puras ``*_out`` que convierten una fila del ORM en el
  dict que viaja dentro de ``{"success": True, "data": ...}``. Viven aquí, y no
  en el service, para que ``api/documents.py`` y ``api/flows.py`` compartan
  exactamente el mismo contrato sin importarse entre sí.

Nota sobre ``StartFlowIn.flow_id``: es **opcional a propósito**. El plan §10.b
paso 1 exige responder **400** ("Debe enviar flow_id.") cuando falta, no el 422
que produciría un campo requerido de Pydantic; la validación de presencia la
hace ``document_flow_service.start_flow``.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any, Optional

from pydantic import BeforeValidator, Field

from itcj2.apps.adhoc.schemas.common import (
    AdhocSchema,
    OptInt,
    OptStr,
    blank_to_default,
)
from itcj2.apps.adhoc.utils.constants import (
    DOCUMENT_EXPIRY_SOON_DAYS,
    DOCUMENT_STATUSES_EDITABLE,
    DOCUMENT_STATUSES_FILE_REPLACEABLE,
    DocumentExpiryFilter,
    DocumentStatus,
)

__all__ = [
    # Entrada — documentos
    "DocumentCreate",
    "DocumentUpdate",
    "DocumentFilters",
    "StartFlowIn",
    "query_flag_to_bool",
    "QueryFlag",
    # Entrada — flujos y pasos
    "FlowCreate",
    "FlowUpdate",
    "FlowStepIn",
    "FlowStepsUpsert",
    "StepUsersIn",
    # Salida
    "acknowledgement_panel_out",
    "document_out",
    "flow_out",
    "step_out",
    "step_details_out",
    "user_brief",
]


# ==========================================================================
# Coerción de banderas de query string
# ==========================================================================

#: Lo que un query string puede traer por un ``bool``. Se compara en minúsculas
#: y sin espacios; ``"si"`` está para el JS que arma el filtro en español.
_FLAG_TRUE: frozenset[str] = frozenset({"true", "1", "on", "yes", "si", "sí"})
_FLAG_FALSE: frozenset[str] = frozenset({"false", "0", "off", "no"})


def query_flag_to_bool(value: Any) -> Any:
    """Validador ``mode="before"`` para una bandera booleana de query string.

    Existe por una colisión concreta entre dos piezas ya escritas:
    :class:`AdhocSchema` coacciona todo string vacío a ``None``
    (``empty_to_none``), y ``None`` **no satisface** un campo ``bool`` — así
    que un ``?only_current=`` reventaría con un 422 y un ``?only_current=false``
    ni siquiera llegaría a evaluarse como falso, porque el valor entra como el
    string ``"false"``, que Pydantic sí sabe convertir pero que primero pasa por
    aquí para uniformar el vocabulario.

    Tres casos, en este orden:

    * ``None`` (parámetro ausente o vacío) → ``True``. Es lo mismo que no pedir
      nada: la lista sigue ocultando las versiones superadas por defecto.
    * un string de :data:`_FLAG_TRUE` / :data:`_FLAG_FALSE` → ``True`` /
      ``False``.
    * cualquier otra cosa (un ``bool`` de verdad, un ``1``) se deja pasar tal
      cual para que la valide Pydantic.
    """
    if value is None:
        return True
    if isinstance(value, str):
        token = value.strip().lower()
        if token in _FLAG_TRUE:
            return True
        if token in _FLAG_FALSE:
            return False
    return value


#: Anotación lista para componer en un campo de filtros: ``QueryFlag = True``.
QueryFlag = Annotated[bool, BeforeValidator(query_flag_to_bool)]


# ==========================================================================
# Entrada — documentos
# ==========================================================================

class DocumentCreate(AdhocSchema):
    """Una fila del alta masiva de ``POST /documents`` (multipart).

    El legacy (``api_docs.save_documents``) exigía ``code`` **y** ``title`` y
    descartaba la fila en silencio si faltaba alguno. Aquí ``title`` es
    obligatorio de verdad (422 si falta) y ``code`` es opcional, como declara la
    columna (``nullable=True``).

    ``parent_id`` significa **"esta fila es una versión nueva de X"**: no es una
    jerarquía de carpetas ni un documento "padre" en sentido documental, es el
    puntero a la cadena de versiones del mismo ``code``. El service lo normaliza
    a la **raíz** de esa cadena (``parent.parent_id or parent.id``, ver
    ``bulk_create``), que es la forma que tienen los 202 documentos migrados:
    plana, de profundidad 1, con una sola punta ``is_current`` por cadena.
    """

    code: Annotated[Optional[str], Field(max_length=50)] = None
    title: str = Field(min_length=1, max_length=200)
    version: Annotated[str, blank_to_default("1.0"), Field(max_length=10)] = "1.0"
    notes: OptStr = None
    expiration_date: Optional[date] = None
    parent_id: OptInt = None
    category_id: OptInt = None
    area_id: OptInt = None
    process_id: OptInt = None
    classification_id: OptInt = None


class DocumentUpdate(AdhocSchema):
    """``PATCH /documents/{id}``. Se aplica con ``model_dump(exclude_unset=True)``.

    Un ``""`` entrante se vuelve ``None`` (limpia la columna); por eso ``title``
    es ``Optional`` aquí y su vacío lo rechaza el service con un 400 legible en
    vez de dejar un documento sin título. En ``expiration_date`` ese vaciado
    **sí** es lo correcto: quitarle la vigencia a un documento es una edición
    legítima, no un error.

    Deliberadamente **no** hay aquí ``is_current`` ni ``parent_id``: la cadena
    de versiones solo la mueve ``bulk_create`` al anexar una versión nueva. Un
    PATCH que pudiera escribirlos dejaría cadenas con dos puntas o con ninguna,
    y la lista —que oculta las superadas— pasaría a mentir.
    """

    code: Annotated[Optional[str], Field(max_length=50)] = None
    title: Annotated[Optional[str], Field(max_length=200)] = None
    version: Annotated[Optional[str], Field(max_length=10)] = None
    status: Optional[DocumentStatus] = None
    notes: OptStr = None
    expiration_date: Optional[date] = None
    category_id: OptInt = None
    area_id: OptInt = None
    process_id: OptInt = None
    classification_id: OptInt = None


class DocumentFilters(AdhocSchema):
    """Filtros de ``GET /documents``. Se construye desde los query params.

    El endpoint los recibe como strings crudos y arma este modelo dentro de un
    ``try``: un ``status`` inventado tiene que ser un 400 legible, no un 500 por
    ``ValidationError`` suelta.

    ``only_current`` es el **único filtro con default activo**: sin él las dos
    listas devuelven las 58 versiones superadas mezcladas con las 144 vigentes
    (54 códigos aparecen 2 o 3 veces) y quien busca "el procedimiento" no sabe
    cuál de los tres resultados es el bueno. Se apaga con
    ``?only_current=false``, que es lo que manda el checkbox "Ver versiones
    anteriores" de la barra de filtros.
    """

    q: OptStr = None
    status: Optional[DocumentStatus] = None
    only_current: QueryFlag = True
    expiring: Optional[DocumentExpiryFilter] = None
    category_id: OptInt = None
    area_id: OptInt = None
    process_id: OptInt = None
    classification_id: OptInt = None
    flow_id: OptInt = None
    author_id: OptInt = None


class StartFlowIn(AdhocSchema):
    """``POST /documents/{id}/start-flow``. Ver nota del docstring del módulo."""

    flow_id: OptInt = None


# ==========================================================================
# Entrada — flujos de aprobación y pasos
# ==========================================================================

class FlowCreate(AdhocSchema):
    name: str = Field(min_length=1, max_length=100)
    description: Annotated[Optional[str], Field(max_length=255)] = None


class FlowUpdate(AdhocSchema):
    name: Annotated[Optional[str], Field(max_length=100)] = None
    description: Annotated[Optional[str], Field(max_length=255)] = None


class FlowStepIn(AdhocSchema):
    """Un paso del ``PUT /approval-flows/{id}/steps``.

    ``step_order`` es la **clave del upsert**: si se omite, el service asigna
    ``índice + 1``. Mandarlo explícitamente permite reordenar el payload sin
    que los pasos existentes se borren y se recreen con ids nuevos (el bug #3
    del legacy, que dejaba ``adhoc_tasks.flow_step_id`` y
    ``adhoc_documents.current_step_id`` apuntando a filas muertas).
    """

    name: str = Field(min_length=1, max_length=100)
    days_limit: Annotated[int, blank_to_default(3), Field(ge=1, le=365)] = 3
    step_order: OptInt = None


class FlowStepsUpsert(AdhocSchema):
    steps: list[FlowStepIn] = Field(default_factory=list)


class StepUsersIn(AdhocSchema):
    """Body de ``PUT /steps/{id}/validators`` y ``/steps/{id}/overdue-notifications``."""

    user_ids: list[int] = Field(default_factory=list)


# ==========================================================================
# Salida
# ==========================================================================

def _iso(value: Any) -> Optional[str]:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return None


def _recipient_brief(user: Any) -> Optional[dict]:
    """``{"id", "name"}`` de un destinatario de la difusión. **Sin ``email``.**

    Deliberadamente más pobre que :func:`user_brief`, y no por ahorro de bytes.
    ``GET /documents/{id}/acknowledgements`` se sirve con
    ``adhoc.documents.api.read``, que también tiene ``consult``. Con el correo
    dentro, recorrer los 202 ids de documento enumera las **55 personas** de
    ``adhoc_document_visibility`` con su dirección —entre ellas 30 que ya no
    tienen acceso a la app, con direcciones personales de gente que se fue—.
    Lo que ese mismo rol podía enumerar por sus otros permisos es otro orden de
    magnitud: 3 autores distintos en ``adhoc_documents`` y 8 validadores en
    ``adhoc_flow_step_assignees``, 11 en total. Y ``consult`` no tiene
    ``adhoc.documents.page.manage``, así que ni siquiera puede abrir el panel
    donde vive el modal: la exposición sería solo por API, sin pantalla que la
    acompañe.

    Quitar la columna no le cuesta nada a la pantalla: la propia hoja de la
    sección ya la escondía en móvil por ser "la única que no participa en
    ninguna lectura" —no dice si acusó, ni cuándo, ni si conserva el acceso— y
    la app **no registra acuses nuevos**, así que tampoco hay un flujo que
    necesite escribirle a nadie desde aquí. El nombre completo identifica a la
    persona, que es lo que la evidencia ISO pide.

    Si algún día hace falta el correo aquí, lo que toca es un permiso propio
    (``adhoc.documents.api.diffusion``) para admin y ``supervisor_doc``, no
    devolver :func:`user_brief`.
    """
    if user is None:
        return None
    name = getattr(user, "full_name", None) or getattr(user, "username", None)
    return {"id": getattr(user, "id", None), "name": name or "Sin nombre"}


def user_brief(user: Any) -> Optional[dict]:
    """``{"id", "name", "email"}`` de un ``core_users`` (o ``None``)."""
    if user is None:
        return None
    name = getattr(user, "full_name", None) or getattr(user, "username", None)
    return {
        "id": getattr(user, "id", None),
        "name": name or "Sin nombre",
        "email": getattr(user, "email", None),
    }


def _as_date(value: Any) -> Optional[date]:
    """``date`` de una columna de vigencia, sea ``Date`` o ``DateTime``.

    La columna es ``Date``, pero el ETL del SGC legacy trajo fechas con parte
    horaria (``FOR JSON`` de SQL Server las emite con ``T``) y un ``datetime``
    comparado contra un ``date`` explota. Aquí se normaliza una sola vez.
    """
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return None


def _expiry(doc: Any, today: Optional[date] = None) -> tuple[bool, Optional[int], Optional[str]]:
    """``(is_expired, days_to_expire, expiry_state)`` de un documento.

    Un solo sitio con la aritmética, para que la columna "Vigencia" de las dos
    tablas, el badge y el contador del dashboard no puedan discrepar por un
    ``<`` contra un ``<=``. Los tres cubos son los de
    :data:`~itcj2.apps.adhoc.utils.constants.DocumentExpiryFilter`, y coinciden
    exactamente con los predicados SQL de ``list_documents``:

    * ``days < 0``  → ``'vencido'``   (``expiration_date < hoy``)
    * ``0 <= days <= DOCUMENT_EXPIRY_SOON_DAYS`` → ``'por_vencer'``
    * el resto      → ``'vigente'``

    Sin ``expiration_date`` devuelve ``(False, None, None)``: no hay vigencia
    que controlar, y ``None`` es lo que distingue "no vence" de "vence hoy".
    ``today`` se recibe de fuera para calcular ``date.today()`` una sola vez por
    respuesta (una lista de 200 filas no debe consultar el reloj 200 veces, y
    peor: cruzar la medianoche a mitad de la página).
    """
    fecha = _as_date(getattr(doc, "expiration_date", None))
    if fecha is None:
        return False, None, None

    dias = (fecha - (today or date.today())).days
    if dias < 0:
        return True, dias, "vencido"
    if dias <= DOCUMENT_EXPIRY_SOON_DAYS:
        return False, dias, "por_vencer"
    return False, dias, "vigente"


def _editable(doc: Any) -> tuple[bool, bool]:
    """``(is_editable, file_replaceable)`` de un documento.

    La regla de edición vive en **un solo sitio del módulo**, igual que la
    aritmética de vigencia vive en :func:`_expiry`, y por el mismo motivo: son
    dos capas las que la necesitan —el service, que la impone, y el panel, que
    pinta o deshabilita el botón "Editar"— y una regla escrita dos veces es una
    regla que acaba divergiendo. Aquí se calcula; el JS solo la lee.

    Los dos flags espejan exactamente los tres guards de
    ``AdhocDocumentService.update``:

    * ``is_editable`` = la fila es la **punta** de su cadena (``is_current``)
      **y** su ``status`` está en
      :data:`~itcj2.apps.adhoc.utils.constants.DOCUMENT_STATUSES_EDITABLE`. Una
      versión superada no se edita nunca, aunque su estado sí estuviera en la
      lista: es histórico del SGC.
    * ``file_replaceable`` = además, el ``status`` admite **cambiar el
      adjunto** **y** el documento no ha entrado nunca a un flujo (``flow_id`` /
      ``current_step_id`` vacíos: los escribe ``start_flow`` y nadie los limpia,
      así que son la marca de que *ese* binario circuló). Es estrictamente más
      estrecho: un ``'Rechazado'`` es editable pero su archivo no se toca,
      porque sus validadores rechazaron *ese* archivo por escrito. La condición
      del flujo no es un cinturón de más: el ``status`` de entrada lo puede
      escribir el propio ``PATCH`` —``'Rechazado'`` es editable y ``'Borrador'``
      es un valor permitido—, así que sin ella dos llamadas seguidas devolvían
      el reemplazo que este flag dice negar.

    El ``and is_editable`` del segundo no es redundante defensiva: mantiene la
    implicación ``file_replaceable ⇒ is_editable``, de la que depende el panel
    para no ofrecer un ``<input type=file>`` dentro de un formulario que el
    servidor va a rechazar entero.
    """
    is_current = bool(getattr(doc, "is_current", False))
    status = getattr(doc, "status", None)
    ha_circulado = (
        getattr(doc, "flow_id", None) is not None
        or getattr(doc, "current_step_id", None) is not None
    )
    is_editable = is_current and status in DOCUMENT_STATUSES_EDITABLE
    file_replaceable = (
        is_editable
        and status in DOCUMENT_STATUSES_FILE_REPLACEABLE
        and not ha_circulado
    )
    return is_editable, file_replaceable


def _named(obj: Any, *extra: str) -> Optional[dict]:
    if obj is None:
        return None
    out = {"id": getattr(obj, "id", None), "name": getattr(obj, "name", None)}
    for field in extra:
        out[field] = getattr(obj, field, None)
    return out


def document_out(doc: Any, *, detail: bool = False, today: Optional[date] = None) -> dict:
    """Fila de documento para la API.

    ``detail=True`` añade el flujo y el paso actual resueltos; el listado los
    omite para no forzar dos joins más en cada página.

    ``today`` es el "hoy" de **toda la respuesta**, y por eso se recibe de fuera:
    calcularlo aquí dentro significa una llamada a ``date.today()`` por fila —50
    en una página de 50— y, lo que importa de verdad, que una página renderizada
    a caballo de la medianoche pueda devolver dos filas con la MISMA
    ``expiration_date`` y distinto ``expiry_state``. Los endpoints lo calculan
    una vez y se lo pasan también a ``list_documents``, de modo que el ``WHERE``
    de ``?expiring=vencidos`` y el badge que se pinta no puedan discrepar nunca.
    Omitirlo sigue siendo válido (``date.today()``) para el uso suelto.

    Las seis claves de versionado y vigencia (``is_current``, ``parent_id``,
    ``expiration_date``, ``is_expired``, ``days_to_expire``, ``expiry_state``)
    van **siempre**, también en el listado: el badge rojo/ámbar de la columna
    "Vigencia" se pinta desde ``expiry_state`` sin que el JS tenga que volver a
    hacer aritmética de fechas —que además la haría contra el reloj del cliente,
    y el navegador de un usuario con la zona horaria mal puesta cambiaría de
    color un documento vencido.

    Y por la misma razón viajan ``is_editable`` y ``file_replaceable`` (ver
    :func:`_editable`): son la regla de edición ya resuelta por el servidor, que
    es quien la impone en ``AdhocDocumentService.update``. Si el panel la
    reimplementara —"``status`` es Borrador o Rechazado y además
    ``is_current``"—, habría dos copias de la misma decisión de producto en dos
    lenguajes, y la del navegador se quedaría atrás el día que cambie la lista
    de estados.
    """
    hoy = today or date.today()
    is_expired, days_to_expire, expiry_state = _expiry(doc, hoy)
    is_editable, file_replaceable = _editable(doc)
    data = {
        "id": doc.id,
        "code": doc.code,
        "title": doc.title,
        "version": doc.version,
        "status": doc.status,
        "notes": doc.notes,
        "approval_date": _iso(doc.approval_date),
        "expiration_date": _iso(_as_date(doc.expiration_date)),
        "is_expired": is_expired,
        "days_to_expire": days_to_expire,
        "expiry_state": expiry_state,
        "is_current": bool(doc.is_current),
        "parent_id": doc.parent_id,
        "is_editable": is_editable,
        "file_replaceable": file_replaceable,
        "file_url": doc.file_url,
        "has_file": bool(doc.file_url),
        "category": _named(doc.category),
        "area": _named(doc.area, "color"),
        "process": _named(doc.process, "color"),
        "classification": _named(doc.classification),
        "author": user_brief(doc.author),
        "flow_id": doc.flow_id,
        "current_step_id": doc.current_step_id,
        "created_at": _iso(doc.created_at),
        "updated_at": _iso(doc.updated_at),
    }
    if detail:
        data["flow"] = _named(doc.flow, "description")
        data["current_step"] = step_out(doc.current_step) if doc.current_step else None
    return data


def acknowledgement_panel_out(panel: dict) -> dict:
    """``GET /documents/{id}/acknowledgements`` — la difusión ya cruzada.

    Recibe lo que devuelve
    :meth:`~itcj2.apps.adhoc.services.document_service.AdhocDocumentService.acknowledgement_panel`
    y le da forma JSON. Tres bloques y ni uno más:

    * ``document`` — un **brief** (``id``, ``code``, ``title``, ``version``,
      ``status``, ``is_current``), no un :func:`document_out` completo. El modal
      se abre desde una fila del panel de gestión que ya trae el documento
      entero, y ``document_out`` arrastraría los cinco catálogos: cinco
      ``SELECT`` perezosos por abrir una ventana que solo necesita el
      encabezado.
    * ``summary`` — los cuatro números ya sumados por el servidor, que es quien
      tiene la colección completa. ``coverage_pct`` va aquí y no en el JS
      porque una división en el navegador es también una división entre cero el
      día que un documento no tenga destinatarios (4 de los 202).
    * ``recipients`` — un destinatario por fila, con ``acknowledged`` como
      booleano además de la fecha: la tabla pinta un badge, y ``acknowledged_at
      !== null`` es una comprobación que el JS no tiene por qué repetir. El
      usuario va con :func:`_recipient_brief`, **sin correo** — ver ahí el
      porqué.

    ``has_app_access`` y ``without_access`` **se omiten cuando el service no
    pudo resolver el conjunto de usuarios con acceso** (``None``), igual que
    ``serialize_task`` omite ``thread_readable`` y ``assignees_without_access``
    sin contexto. Ausente, el JS lo lee como ``undefined`` —falsy, así que la
    UI se calla— sin que el JSON haya afirmado que esa persona sí puede entrar.
    Un ``False`` de verdad sí viaja: es la marca, y es el dato.
    """
    doc = panel["document"]
    resumen = panel["summary"]

    salida_resumen = {
        "assigned": resumen["assigned"],
        "acknowledged": resumen["acknowledged"],
        "pending": resumen["pending"],
        "coverage_pct": resumen["coverage_pct"],
    }
    if resumen.get("without_access") is not None:
        salida_resumen["without_access"] = resumen["without_access"]

    destinatarios = []
    for fila in panel["recipients"]:
        acusado_el = fila.get("acknowledged_at")
        out = {
            "user": _recipient_brief(fila["user"]),
            "acknowledged": acusado_el is not None,
            "acknowledged_at": _iso(acusado_el),
        }
        if fila.get("has_app_access") is not None:
            out["has_app_access"] = fila["has_app_access"]
        destinatarios.append(out)

    return {
        "document": {
            "id": doc.id,
            "code": doc.code,
            "title": doc.title,
            "version": doc.version,
            "status": doc.status,
            "is_current": bool(doc.is_current),
        },
        "summary": salida_resumen,
        "recipients": destinatarios,
    }


def step_out(step: Any, *, assignee_count: Optional[int] = None) -> dict:
    out = {
        "id": step.id,
        "flow_id": step.flow_id,
        "name": step.name,
        "days_limit": step.days_limit,
        "step_order": step.step_order,
    }
    if assignee_count is not None:
        out["assignee_count"] = assignee_count
    return out


def flow_out(flow: Any, *, step_count: Optional[int] = None) -> dict:
    out = {
        "id": flow.id,
        "name": flow.name,
        "description": flow.description,
        "created_at": _iso(flow.created_at),
        "updated_at": _iso(flow.updated_at),
    }
    if step_count is not None:
        out["step_count"] = step_count
    return out


def step_details_out(step: Any, assigned: list, notify_ids: set) -> dict:
    """``GET /approval-flows/steps/{id}`` — validadores y quién recibe la alerta.

    Espeja la forma del legacy (``assigned`` / ``notify``) porque la UI del
    modal de asignación la consume tal cual; lo que cambia es el sobre
    (``{"success": True, "data": {...}}``) y que ahora exige permiso.
    """
    return {
        "step": step_out(step),
        "assigned": [user_brief(u) for u in assigned],
        "notify": [user_brief(u) for u in assigned if getattr(u, "id", None) in notify_ids],
    }
