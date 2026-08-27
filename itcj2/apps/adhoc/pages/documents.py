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
            "can_create": _can(perms, "adhoc.documents.api.create"),
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
