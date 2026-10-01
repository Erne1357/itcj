"""Páginas de **Documentos y flujos de aprobación** (Adhoc / Calidad).

Siete rutas (plan §4 + B4), todas montadas por el router padre con
``prefix="/adhoc"``:

======================================  ===============================  ============================
URL                                     Origen legacy                    Permiso de página
======================================  ===============================  ============================
``/documentos``                         ``documents.py:7`` (consulta)    ``adhoc.documents.page.list``
``/documentos/panel``                   ``documentos_panel``             ``adhoc.documents.page.manage``
``/documentos/categorias``              ``config_doc_categorias``        ``adhoc.doc_catalogs.page.list``
``/documentos/clasificaciones``         ``config_doc_clasificacion``     ``adhoc.doc_catalogs.page.list``
``/documentos/flujos``                  ``config_doc_flujos``            ``adhoc.flows.page.list``
``/documentos/flujos/{id}/pasos``       ``config_flujo_pasos``           ``adhoc.flows.page.list``
``/documentos/{id}/tareas``             — (no existía)                   ``adhoc.tasks.page.list``
======================================  ===============================  ============================

La última es de B4 y no tiene origen legacy: el flujo documental se cortaba a la
mitad. ``parent_type='document'`` lo soportan la API, ``task_service`` y
``GET /tasks``, pero la pantalla no existía, así que las tareas de aprobación de
un documento solo aparecían en el tablero personal de cada validador. Nadie
—supervisor documental ni admin— podía ver en qué paso va un documento ni
reasignar un paso atascado, porque a ``/adhoc/asignaciones`` solo se llega desde
una página de tareas.

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

Y una responsabilidad que no estaba: **las dos listas de documentos comparten
contexto**. ``/documentos`` y ``/documentos/panel`` son pantallas distintas con
permisos distintos, pero la tabla de las dos la pinta el mismo
``document-list.js``, así que el trozo de ``page_data`` que esa tabla consume
—paginación, capacidad de descarga, ventana de aviso de vigencia y los filtros
que vienen en la URL— lo arma un solo helper (``_document_list_page_data``) y no
dos bloques que se copian. Lo que cambia entre pantallas se añade encima.

Los **filtros de la URL** son lo que hace clicable el contador de documentos
vencidos del dashboard: ``/adhoc/documentos?expiring=vencidos`` llega con el
``<select>`` de vigencia ya puesto, y ``?only_current=false`` con la casilla
"Ver versiones anteriores" ya marcada. Se validan aquí contra el mismo
vocabulario que valida la API (``DOCUMENT_EXPIRY_FILTERS`` y
``query_flag_to_bool``): un valor inventado se **ignora**, no rompe la página ni
viaja al JS para que reviente allí.

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

#: Etiqueta visible de cada cubo de vigencia. La **clave** es el valor que viaja
#: en la query (``?expiring=``) y que el ``<select>`` devuelve tal cual a la API;
#: el texto es solo para el ojo. Vive aquí y no en ``utils/constants`` porque
#: allí está el vocabulario que replica la BD y alimenta los ``Literal`` de
#: Pydantic, no la redacción de la UI: ``por_vencer_30d`` es el contrato,
#: "Por vencer (30 días)" es la pantalla, y solo lo segundo se puede reescribir
#: sin tocar la API.
#: Rótulo de cada cubo de vigencia. El de "por vencer" lleva ``{dias}`` y no un
#: 30 escrito a mano porque el número es :data:`DOCUMENT_EXPIRY_SOON_DAYS`: el
#: contador de vencidos del dashboard, el ``WHERE`` de la API y estos tres
#: ``<option>`` cuentan la misma ventana, y una pantalla que diga "30 días"
#: cuando el servidor filtra con otra es de las incoherencias que nadie reporta
#: pero que hacen que se deje de creer lo que se ve.
_EXPIRY_LABELS: dict[str, str] = {
    "vencidos": "Vencidos",
    "por_vencer_30d": "Por vencer ({dias} días)",
    "vigentes": "Vigentes",
}


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


def _expiry_options() -> list[dict]:
    """Opciones del ``<select>`` de vigencia, en el orden del vocabulario.

    El orden y la pertenencia los manda ``DOCUMENT_EXPIRY_FILTERS`` —los tres
    cubos son disjuntos y exhaustivos, y ese es el sitio donde se declaran—;
    aquí solo se les pone nombre. Un cubo nuevo sin etiqueta sale con su propio
    código en vez de tumbar la pantalla con un ``KeyError``: el filtro se ve
    feo, pero el SGC se sigue consultando.

    Lo consumen **las dos** listas: la de consulta y la del panel iteran esta
    misma lista, así que renombrar un cubo o mover la ventana de aviso se hace
    en un solo sitio. Cuando el panel escribía sus tres ``<option>`` a mano, la
    pantalla de al lado podía quedarse mandando un valor que la API ya no
    reconoce —y un filtro que la API ignora devuelve la lista entera sin avisar.
    """
    from itcj2.apps.adhoc.utils.constants import (
        DOCUMENT_EXPIRY_FILTERS,
        DOCUMENT_EXPIRY_SOON_DAYS,
    )

    return [
        {
            "value": value,
            "label": _EXPIRY_LABELS.get(value, value).format(
                dias=DOCUMENT_EXPIRY_SOON_DAYS,
            ),
        }
        for value in DOCUMENT_EXPIRY_FILTERS
    ]


def _initial_filters(request: Request) -> dict[str, Optional[str]]:
    """Los filtros que llegan **en la URL**, validados y en formato de query.

    Las dos claves salen siempre, con ``None`` cuando el parámetro no venía: el
    JS las recorre y se salta los nulos, así que no tiene que preguntar si
    existen. El valor es el **string que la casilla o el ``<select>`` volverán a
    mandar** (``"vencidos"``, ``"false"``), no un booleano ni un enum: así
    aplicar el filtro inicial a un control es asignar, no traducir.

    Todo lo que no case con el vocabulario se descarta en silencio. Un
    ``?expiring=urgentes`` escrito a mano tiene que abrir la lista completa, no
    un 400 ni una pantalla en blanco: esta URL se comparte por correo, y el
    enlace mal copiado de un compañero no puede dejar a nadie sin consultar el
    SGC. La API vuelve a validar lo mismo cuando el JS le pide los datos, así
    que aquí no se está confiando en nadie.
    """
    from itcj2.apps.adhoc.schemas.documents import query_flag_to_bool
    from itcj2.apps.adhoc.utils.constants import DOCUMENT_EXPIRY_FILTERS

    params = request.query_params

    expiring: Optional[str] = (params.get("expiring") or "").strip() or None
    if expiring not in DOCUMENT_EXPIRY_FILTERS:
        expiring = None

    # ``query_flag_to_bool`` es el MISMO coercionador que usa ``DocumentFilters``
    # ("true/1/on/yes/si" contra "false/0/off/no"), para que la URL se lea igual
    # en la página que en la API. Devuelve el valor sin tocar cuando no reconoce
    # el token —de ahí el ``isinstance``—, y para él ``None`` significa "el
    # default"; aquí eso no vale, porque el default de la pantalla es "no toques
    # el control", así que el ausente se descarta antes de llamarlo.
    only_current: Optional[str] = None
    raw = params.get("only_current")
    if raw is not None and raw.strip():
        flag = query_flag_to_bool(raw)
        if isinstance(flag, bool):
            only_current = "true" if flag else "false"

    return {"expiring": expiring, "only_current": only_current}


def _document_list_page_data(request: Request, perms: Optional[set[str]]) -> dict:
    """El ``page_data`` que consume ``document-list.js``, igual en las dos listas.

    Consulta y panel son pantallas distintas —una lee, la otra administra— pero
    su tabla es el mismo módulo, así que lo que ese módulo necesita se arma una
    sola vez. El panel le añade encima sus catálogos y sus capacidades de
    escritura.

    Aquí NO viaja la ventana de aviso de vigencia: el JS no hace aritmética de
    fechas —el ``expiry_state`` de cada fila lo calcula el servidor, porque
    hacerlo en el navegador pintaría de rojo un documento vigente en cuanto un
    equipo tuviera mal la zona horaria— y el rótulo "(30 días)" del filtro lo
    arma ``_expiry_options`` a partir de la constante. Mandarla además por
    ``page_data`` era una segunda copia del mismo número sin nadie que la
    leyera.
    """
    return {
        "per_page": 25,
        "can_download": _can(perms, "adhoc.documents.api.download"),
        "initial_filters": _initial_filters(request),
    }


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


def _flow_document_counts(db: Session) -> dict[str, int]:
    """``{id de flujo: cuántos documentos lo usan}``, en **una sola** consulta.

    Es el dato que decide si la papelera de la fila se puede pulsar, y por eso
    lo cuenta el servidor: replica el guard **principal** de
    ``AdhocDocumentFlowService.delete_flow`` —documentos con ese ``flow_id``, en
    CUALQUIER estado, incluidos los aprobados hace diez años—, así que contar
    otra cosa (solo los activos, solo los de la página visible) volvería a
    ofrecer una papelera que responde 409. Medido hoy: 21 de los 43 flujos
    tienen documentos colgando, o sea que son indeletables para siempre y hasta
    ahora la pantalla los ofrecía igual, con su diálogo de confirmación incluido.

    **No es el guard entero, y eso es deliberado.** ``delete_flow`` llama además
    a ``_assert_steps_unreferenced``, que rechaza si algún documento está
    *posicionado* en uno de sus pasos (``current_step_id``) o si alguna tarea
    los referencia (``flow_step_id``). Esos dos casos siguen resolviéndose con
    el 409 del servidor, que el JS ya recoge y enseña como aviso. Medido sobre
    los 43 flujos reales: **0** caen solo por ellos —un documento posicionado en
    un paso trae el ``flow_id`` de ese flujo, y las tareas del documento mueren
    con él por ``ON DELETE CASCADE``—, así que ampliar la consulta añadiría dos
    predicados que hoy no apagan ni un botón y volvería mentira la línea "en uso
    por N documentos" de la fila, que cuenta documentos y no tareas.

    Un ``GROUP BY``, no un ``count()`` por flujo: la tabla pinta los 43 de una
    vez y la versión por fila serían 43 consultas para decorar una pantalla.

    Las claves salen como **string** porque así viajan en el JSON de todas
    formas (``json.dumps`` convierte las numéricas) y así el JS busca con
    ``String(flow.id)`` sin depender de esa coacción.

    Si la consulta falla, el mapa sale vacío y la pantalla se porta como hasta
    hoy: la papelera se ofrece y el 409 del servidor explica el resto. Apagar un
    botón es una cortesía de la UI —el guard de verdad está en el service, y no
    se relaja—, y no vale tumbar el listado de flujos por una cortesía.
    """
    from sqlalchemy import func

    from itcj2.apps.adhoc.models import AdhocDocument

    try:
        filas = (
            db.query(AdhocDocument.flow_id, func.count(AdhocDocument.id))
            .filter(AdhocDocument.flow_id.isnot(None))
            .group_by(AdhocDocument.flow_id)
            .all()
        )
    except Exception as exc:  # pragma: no cover - defensivo
        logger.warning(
            "adhoc/flujos: no se pudieron contar los documentos por flujo: %s", exc
        )
        return {}

    return {str(flow_id): int(total) for flow_id, total in filas}


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

    Acepta dos parámetros de URL, ``?expiring=`` y ``?only_current=``, que se
    reflejan en la barra de filtros **antes** de la primera consulta
    (``_initial_filters``). No son un adorno: son el destino del contador de
    documentos vencidos del dashboard.
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
        "expiry_options": _expiry_options(),
        "page_data": _document_list_page_data(request, perms),
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

    Del legacy sigue sin portarse la celda ``<td>ISO 9001</td>`` de la columna
    "Sist. Gestión", que no corresponde a ninguna columna del modelo. El otro
    bloque descartado en su día —el historial de versiones anteriores— **sí
    existe ahora**, pero no como aquel mockup (fecha escrita a mano y versión
    previa calculada restando 1.0): es el modal compartido que lee la cadena
    real con ``GET /documents/{id}/versions``. Hizo falta de verdad en cuanto
    las dos listas pasaron a ocultar por defecto las versiones superadas.
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
        "expiry_options": _expiry_options(),
        "can_create": _can(perms, "adhoc.documents.api.create"),
        "page_data": {
            # Lo que la tabla necesita en las DOS pantallas: paginación,
            # capacidad de descarga, ventana de aviso de vigencia y los filtros
            # que vengan en la URL.
            **_document_list_page_data(request, perms),
            # Catálogos como JSON: el JS construye los <option> del alta masiva
            # con escapeHtml. El legacy inyectaba aquí HTML crudo con backticks.
            "categories": catalogs["categories"],
            "areas": catalogs["areas"],
            "processes": catalogs["processes"],
            "classifications": catalogs["classifications"],
            "flows": flows,
            "accept": [f".{ext}" for ext in extensions],
            # Destino de la acción de fila "Tareas" (B4). Va como PLANTILLA en
            # el JSON y no cableada en el JS por la misma razón que en
            # incidencias y programas —`test_la_url_de_tareas_sale_del_json_no_
            # del_js`—: el legacy tenía `/app_prueba/extintor/tareas/${id}`
            # escrito dentro del módulo, así que renombrar una ruta obligaba a
            # buscarla en los estáticos.
            #
            # Solo en el PANEL. La lista de consulta (`/adhoc/documentos`) no
            # recibe esta clave: ver el avance de un flujo y reasignar un paso
            # atascado es administración del ciclo documental, y esa pantalla no
            # tiene ninguna acción de administración.
            #
            # Y solo si la puerta se abre. La clave es a la vez el DESTINO y el
            # gate —`documents-panel.js` pinta el botón si y solo si la recibe—,
            # así que emitirla sin comprobar el permiso de la página destino
            # convierte el botón en un callejón a la pantalla de prohibido: hoy
            # ningún rol del DML separa `documents.page.manage` de
            # `tasks.page.list`, pero un permiso directo o un override de puesto
            # sí puede, y entonces el icono sale en las 25 filas y ninguna
            # lleva a ningún sitio. La decisión la toma quien sabe si esa puerta
            # se abre, que es el servidor.
            "tasks_url": ("/adhoc/documentos/{id}/tareas"
                          if _can(perms, "adhoc.tasks.page.list") else None),
            "can_create": _can(perms, "adhoc.documents.api.create"),
            # `can_update` solo viaja en el PANEL, no en la lista de consulta:
            # el botón "Editar" es una acción de administración y
            # `/adhoc/documentos` no tiene ninguna. Que el permiso exista no lo
            # convierte en algo que pintar en una pantalla de lectura.
            #
            # Enciende el botón; NO decide si esa fila concreta se puede editar.
            # Eso lo dicen `is_editable` / `file_replaceable` de cada documento
            # (`document_out`), que es la regla de producto ya resuelta por el
            # servidor: sin `is_current` y sin un estatus de
            # DOCUMENT_STATUSES_EDITABLE no se edita ni con el permiso puesto.
            "can_update": _can(perms, "adhoc.documents.api.update"),
            "can_delete": _can(perms, "adhoc.documents.api.delete"),
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
    """Listado de flujos con su número de pasos y cuántos documentos los usan.

    Lo segundo no es adorno: es lo que decide si la papelera de la fila se
    ofrece. ``delete_flow`` rechaza con 409 cualquier flujo que tenga
    documentos, y como cuenta los de **cualquier** estado, un flujo que se usó
    una vez en 2016 ya no se borra nunca. La pantalla pintaba la papelera en los
    43 igual, así que en 21 de ellos el camino era pulsar, confirmar en el
    diálogo y comerse el error.

    El conteo viaja en ``page_data`` y no lo deduce el JS —no hay de dónde: la
    fila de flujo no sabe nada de documentos— ni lo trae ``GET /approval-flows``.
    Es **una** consulta agregada de más en toda la pantalla.
    """
    perms = _effective_perms(db, user)
    return render_adhoc(request, "adhoc/documents/flows.html", {
        "nav": nav_for_user(db, user),
        "back_url": _BACK_TO_DOCUMENTS,
        "can_create": _can(perms, "adhoc.flows.api.create"),
        "page_data": {
            "can_create": _can(perms, "adhoc.flows.api.create"),
            "can_update": _can(perms, "adhoc.flows.api.update"),
            "can_delete": _can(perms, "adhoc.flows.api.delete"),
            # Cuántos documentos usa cada flujo. La tabla la pinta el JS con la
            # lista de `GET /approval-flows`, que NO trae este dato; el mapa se
            # arma aquí una vez y la fila lo busca por su id. Un flujo que se
            # cree después de esta petición no está en el mapa: cuenta como
            # cero, que es exactamente lo que es.
            "document_counts": _flow_document_counts(db),
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


# ==========================================================================
# 7. Tareas de un documento  (B4)
#
# Va al final y no junto al panel por el orden de resolución de FastAPI: es la
# única ruta paramétrica de segundo nivel de este módulo. Hoy no compite con
# ninguna hermana —`/documentos/panel`, `/categorias`, `/clasificaciones` y
# `/flujos` son de un solo tramo, y `/flujos/{flow_id}/pasos` de tres—, pero
# declararla después de las literales es lo que garantiza que siga siendo así
# cuando alguien añada `/documentos/algo`: si la paramétrica fuera antes, se
# comería la literal nueva y `"algo"` llegaría como `document_id`.
# ==========================================================================

@router.get("/documentos/{document_id}/tareas")
async def document_tasks_page(
    request: Request,
    document_id: int,
    user: dict = Depends(require_page_app("adhoc", perms=["adhoc.tasks.page.list"])),
    db: Session = Depends(get_db),
):
    """Avance por pasos del flujo de aprobación de un documento.

    Es la **gemela** de ``/adhoc/incidencias/{id}/tareas`` y
    ``/adhoc/programas/{id}/tareas``: mismo permiso de página
    (``adhoc.tasks.page.list``), mismo template (``adhoc/work/tasks.html``) y el
    mismo ``tasks_page_context``, que es lo que impide que las tres diverjan.

    Lo propio del documento lo pone ese contexto, no esta ruta: la identidad del
    expediente (``code`` + ``version``, porque un documento no tiene ``folio``) y
    la bandera ``show_step_column``, que enciende la columna "Paso" —el nombre y
    el orden del paso al que pertenece cada tarea— y es lo que convierte la
    pantalla en "ver el avance del flujo" en vez de una lista suelta de tareas.

    Se llega por una acción de fila de ``/adhoc/documentos/panel``, junto a
    sellar / historial / editar / eliminar, y ahí vuelve el botón "Volver": es
    la pantalla desde la que se administra el ciclo documental. La lista de
    consulta (``/adhoc/documentos``) no tiene acciones de administración.
    """
    from itcj2.apps.adhoc.pages._work_context import tasks_page_context
    from itcj2.apps.adhoc.services.document_service import AdhocDocumentService

    try:
        documento = AdhocDocumentService.get(db, document_id)
    except LookupError as exc:
        # El service lanza LookupError; el contrato de la app lo traduce a 404.
        raise HTTPException(
            status_code=404, detail=f"No existe el documento {document_id}"
        ) from exc

    return render_adhoc(
        request,
        "adhoc/work/tasks.html",
        tasks_page_context(
            db,
            user,
            parent=documento,
            parent_type="document",
            back_url="/adhoc/documentos/panel",
            parent_label="documento",
        ),
    )
