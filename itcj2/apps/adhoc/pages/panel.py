"""Páginas del **Panel de Control** de Adhoc / Calidad (plan §4, sección panel).

Seis rutas, todas ``GET`` y todas renderizadas con :func:`render_adhoc`:

=================================  ==================================
URL                                Permiso de página
=================================  ==================================
``/adhoc/panel``                   ``adhoc.panel.page.view``
``/adhoc/panel/procesos``          ``adhoc.processes.page.list``
``/adhoc/panel/areas``             ``adhoc.areas.page.list``
``/adhoc/panel/usuarios``          ``adhoc.users.page.list``
``/adhoc/panel/configuracion``     ``adhoc.panel.page.view``
``/adhoc/panel/correo``            ``adhoc.mail.page.view``
=================================  ==================================

El router se expone **sin prefijo propio**: lo monta ``pages/router.py`` en la
fase de cableado con ``include_router(panel_router)`` bajo el ``/adhoc`` del
padre.

Qué cambia respecto del legacy (``control_panel/*.html`` + ``js/control_panel/``):

* **El gate es real.** El legacy decoraba con ``@login_required`` *encima* de
  ``@route`` (no protegía nada) y escondía tarjetas con ``{% if is_admin %}``
  puramente cosmético: quien tecleaba la URL entraba. Aquí cada ruta lleva
  ``Depends(require_page_app("adhoc", perms=[...]))`` y las tarjetas se filtran
  con los permisos reales del usuario.
* **Las tarjetas son enlaces.** El legacy pintaba ``div.card`` con ``data-link``
  y los cableaba con ``document.querySelectorAll('.card')`` sin scope — el
  selector enganchaba también las tarjetas del layout. Aquí son anclas de
  verdad y ``/adhoc/panel`` no carga ni una línea de JS.
* **No se portan** las tarjetas "7 Herramientas" y "Soporte": no tenían destino
  y no hacían nada al pulsarlas.
* **Usuarios va recortado** (decisión D8): se listan los usuarios con acceso a
  Calidad y se les asigna rol de app y áreas. El alta de personas y el cambio de
  contraseña del legacy —anónimos y con ``role_id=4`` hardcodeado, o sea una
  escalada de privilegios— se sustituyen por un enlace a ``/itcj/config``.

Nota sobre ``require_page_app``: devuelve la función pelada, así que **hay que
envolverla en ``Depends``** (asimetría con ``require_perms``/``require_app``,
que ya devuelven ``Depends(...)``). Plan §4.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from itcj2.apps.adhoc.pages.nav import nav_for_user
from itcj2.apps.adhoc.pages.render import render_adhoc
from itcj2.database import get_db
from itcj2.dependencies import require_page_app

logger = logging.getLogger(__name__)

router = APIRouter()

__all__ = ["router", "PANEL_TILES", "CONFIG_GROUPS", "ADHOC_APP_ROLE_LABELS"]

_PANEL_URL = "/adhoc/panel"
#: Dueño del alta de personas, contraseñas y revocación de acceso (D8).
_CORE_CONFIG_URL = "/itcj/config"


# ==========================================================================
# Permisos del usuario para la UI
# ==========================================================================

class _EveryPermission:
    """Conjunto de permisos del **admin global** del JWT: lo contiene todo.

    Existe para que las plantillas y los filtros de tarjetas usen siempre la
    misma expresión (``code in perms``) sin ramificar por tipo de usuario. El
    admin global ya bypasea ``require_perms`` en la API (``dependencies.py``),
    así que ocultarle botones sería mentirle a la UI.
    """

    __slots__ = ()

    def __contains__(self, item: object) -> bool:  # noqa: D105
        return True

    def __bool__(self) -> bool:  # noqa: D105
        return True

    def __repr__(self) -> str:  # noqa: D105
        return "<todos los permisos>"


ALL_PERMS = _EveryPermission()


def user_perms(db: Session, user: dict | None):
    """Permisos efectivos del usuario en ``adhoc``, para decidir qué pintar.

    Fail-**closed** igual que ``pages/nav.py``: si el cálculo revienta se
    devuelve el conjunto vacío. Pintar el panel completo sería un fallo abierto
    (tarjetas que llevan a un 403). El admin global del JWT recibe
    :data:`ALL_PERMS`.

    Ojo: esto solo decide **presentación**. El gate real es
    ``require_page_app`` en cada página y ``require_perms`` en cada endpoint.
    """
    if not user:
        return frozenset()
    if user.get("role") == "admin":
        return ALL_PERMS

    from itcj2.core.services.authz_service import get_user_permissions_for_app

    try:
        return get_user_permissions_for_app(db, int(user["sub"]), "adhoc")
    except Exception as exc:  # pragma: no cover - defensivo
        logger.warning("adhoc panel: no se pudieron calcular permisos (%s)", exc)
        return frozenset()


def _allowed(perms, needed: set[str]) -> bool:
    """``True`` si el usuario tiene **alguno** de los permisos pedidos."""
    return any(code in perms for code in needed)


# ==========================================================================
# Tarjetas del panel
# ==========================================================================

#: (título, icono Font Awesome, url, descripción, permisos any-of).
#:
#: Es la rejilla de ``control_panel/control_panel.html`` menos las dos tarjetas
#: muertas ("7 Herramientas" y "Soporte", sin ``data-link``: no hacían nada).
#: El destino de "Indicadores" se corrige: el legacy apuntaba a
#: ``/app_prueba/indicators``, que no era ninguna de sus rutas registradas.
PANEL_TILES: list[tuple[str, str, str, str, set[str]]] = [
    (
        "Procesos",
        "fa-solid fa-cogs",
        "/adhoc/panel/procesos",
        "Catálogo de procesos del sistema de gestión.",
        {"adhoc.processes.page.list"},
    ),
    (
        "Áreas",
        "fa-solid fa-layer-group",
        "/adhoc/panel/areas",
        "Áreas a las que se adscriben documentos, incidencias y personas.",
        {"adhoc.areas.page.list"},
    ),
    (
        "Usuarios",
        "fa-solid fa-users",
        "/adhoc/panel/usuarios",
        "Rol dentro de Calidad y áreas de cada persona.",
        {"adhoc.users.page.list"},
    ),
    (
        "Documentos",
        "fa-solid fa-file-lines",
        "/adhoc/documentos/panel",
        "Administración documental y flujos de aprobación.",
        {"adhoc.documents.page.manage"},
    ),
    (
        "Incidencias",
        "fa-solid fa-fire-extinguisher",
        "/adhoc/incidencias",
        "Seguimiento de incidencias y sus tareas.",
        {"adhoc.incidents.page.list"},
    ),
    (
        "Programa",
        "fa-regular fa-calendar-days",
        "/adhoc/programas",
        "Eventos del programa de trabajo de Calidad.",
        {"adhoc.programs.page.list"},
    ),
    (
        "Indicadores",
        "fa-solid fa-gauge-high",
        "/adhoc/indicadores",
        "Indicadores anuales y tablero de seguimiento.",
        {"adhoc.indicators.page.list", "adhoc.indicators.page.manage"},
    ),
    (
        "Reportes",
        "fa-solid fa-file-circle-check",
        "/adhoc/reportes",
        "Reportes imprimibles del sistema.",
        {"adhoc.reports.page.view"},
    ),
    (
        "Configuración",
        "fa-solid fa-sliders",
        "/adhoc/panel/configuracion",
        "Catálogos, flujos y funciones de correo.",
        {"adhoc.panel.page.view"},
    ),
]


#: Tercer nivel: los enlaces de ``control_panel/advanced_config.html``, con las
#: URLs nuevas del plan §4. Un grupo sin enlaces visibles no se pinta.
CONFIG_GROUPS: list[dict] = [
    {
        "title": "Documentos",
        "icon": "fa-solid fa-file-lines",
        "links": [
            ("Categorías de documentos", "/adhoc/documentos/categorias",
             {"adhoc.doc_catalogs.page.list"}),
            ("Clasificación de documentos", "/adhoc/documentos/clasificaciones",
             {"adhoc.doc_catalogs.page.list"}),
            ("Flujos de aprobación", "/adhoc/documentos/flujos",
             {"adhoc.flows.page.list"}),
        ],
    },
    {
        "title": "Incidencias",
        "icon": "fa-solid fa-fire-extinguisher",
        "links": [
            ("Categorías de incidencias", "/adhoc/incidencias/categorias",
             {"adhoc.incident_categories.page.list"}),
        ],
    },
    {
        "title": "Programa",
        "icon": "fa-regular fa-calendar-days",
        "links": [
            ("Categorías del programa", "/adhoc/programas/categorias",
             {"adhoc.program_categories.page.list"}),
        ],
    },
    {
        "title": "Funciones",
        "icon": "fa-solid fa-toolbox",
        "links": [
            ("Correo electrónico", "/adhoc/panel/correo", {"adhoc.mail.page.view"}),
        ],
    },
]


#: Etiquetas legibles de los 5 roles de Calidad. El vocabulario cerrado vive en
#: ``schemas/admin.py::ADHOC_APP_ROLES``; aquí solo se traduce para la UI.
ADHOC_APP_ROLE_LABELS: dict[str, str] = {
    "admin": "Administrador",
    "supervisor_doc": "Supervisor de documentos",
    "supervisor_inc": "Supervisor de incidencias",
    "supervisor_prog": "Supervisor del programa",
    "consult": "Consulta",
}


def _tiles_for(perms) -> list[dict]:
    return [
        {"title": title, "icon": icon, "url": url, "text": text}
        for title, icon, url, text, needed in PANEL_TILES
        if _allowed(perms, needed)
    ]


def _config_groups_for(perms) -> list[dict]:
    out: list[dict] = []
    for group in CONFIG_GROUPS:
        links = [
            {"label": label, "url": url}
            for label, url, needed in group["links"]
            if _allowed(perms, needed)
        ]
        if links:
            out.append({"title": group["title"], "icon": group["icon"], "links": links})
    return out


def _base_ctx(db: Session, user: dict) -> dict:
    """Contexto común: nav filtrado + permisos del usuario para la UI."""
    return {"nav": nav_for_user(db, user), "perms": user_perms(db, user)}


# ==========================================================================
# /adhoc/panel — rejilla de navegación
# ==========================================================================

@router.get("/panel")
async def panel_home(
    request: Request,
    user: dict = Depends(require_page_app("adhoc", perms=["adhoc.panel.page.view"])),
    db: Session = Depends(get_db),
):
    """Rejilla de tarjetas del panel de control. **Sin JavaScript.**"""
    ctx = _base_ctx(db, user)
    return render_adhoc(
        request,
        "adhoc/panel/panel.html",
        {**ctx, "tiles": _tiles_for(ctx["perms"])},
    )


# ==========================================================================
# /adhoc/panel/procesos y /adhoc/panel/areas — catálogos con color
# ==========================================================================
#
# Las dos pantallas son el mismo template y el mismo módulo JS con distinta
# configuración (plan §6.5: `areas_conf.js` era una copia literal de
# `processes.js`). Diferencias reales: el área tiene `is_active` y el proceso
# tiene `description`. El color del proceso ahora es una columna de verdad: el
# legacy lo guardaba DENTRO de `description` y lo leía con una `@property`.

def _color_catalog_columns(*, has_active: bool, name_label: str) -> list[dict]:
    cols = [
        {"key": "name", "label": name_label, "filter": True},
        {"key": "color", "label": "Color", "align": "center"},
    ]
    if has_active:
        cols.append({"key": "is_active", "label": "Estado", "filter": True,
                     "placeholder": "Activa / Inactiva", "align": "center"})
    cols.append({"key": "actions", "label": "Acciones", "align": "end"})
    return cols


@router.get("/panel/areas")
async def panel_areas(
    request: Request,
    user: dict = Depends(require_page_app("adhoc", perms=["adhoc.areas.page.list"])),
    db: Session = Depends(get_db),
):
    """Gestión de áreas (``adhoc_areas``): nombre, color y estado."""
    ctx = _base_ctx(db, user)
    perms = ctx["perms"]
    return render_adhoc(request, "adhoc/panel/color_catalog.html", {
        **ctx,
        "page_title": "Gestión de Áreas",
        "icon": "fa-solid fa-layer-group",
        "resource": "areas",
        "api_path": "/api/adhoc/v2/areas",
        "singular": "área",
        "plural": "áreas",
        "name_label": "Nombre del área",
        "default_color": "#4834d4",
        "has_active": True,
        "has_description": False,
        "empty_message": "No hay áreas registradas.",
        "columns": _color_catalog_columns(has_active=True, name_label="Nombre del área"),
        "can_create": "adhoc.areas.api.create" in perms,
        "can_update": "adhoc.areas.api.update" in perms,
        "can_delete": "adhoc.areas.api.delete" in perms,
    })


@router.get("/panel/procesos")
async def panel_processes(
    request: Request,
    user: dict = Depends(require_page_app("adhoc", perms=["adhoc.processes.page.list"])),
    db: Session = Depends(get_db),
):
    """Gestión de procesos (``adhoc_processes``): nombre, color y descripción."""
    ctx = _base_ctx(db, user)
    perms = ctx["perms"]
    return render_adhoc(request, "adhoc/panel/color_catalog.html", {
        **ctx,
        "page_title": "Gestión de procesos",
        "icon": "fa-solid fa-cogs",
        "resource": "processes",
        "api_path": "/api/adhoc/v2/processes",
        "singular": "proceso",
        "plural": "procesos",
        "name_label": "Nombre del proceso",
        "default_color": "#b2bec3",
        "has_active": False,
        "has_description": True,
        "empty_message": "No hay procesos registrados.",
        "columns": _color_catalog_columns(has_active=False, name_label="Nombre del proceso"),
        "can_create": "adhoc.processes.api.create" in perms,
        "can_update": "adhoc.processes.api.update" in perms,
        "can_delete": "adhoc.processes.api.delete" in perms,
    })


# ==========================================================================
# /adhoc/panel/usuarios — módulo recortado (D8)
# ==========================================================================

@router.get("/panel/usuarios")
async def panel_users(
    request: Request,
    user: dict = Depends(require_page_app("adhoc", perms=["adhoc.users.page.list"])),
    db: Session = Depends(get_db),
):
    """Usuarios con acceso a Calidad: rol de la app y áreas.

    Lo que **no** hay aquí, a propósito: alta de personas, cambio de contraseña
    y borrado. En el legacy vivían en esta pantalla, sin autenticación y con el
    rol ``admin`` hardcodeado. Ese trabajo es del core y se enlaza a
    ``/itcj/config``.
    """
    ctx = _base_ctx(db, user)
    perms = ctx["perms"]
    can_assign_role = "adhoc.users.api.assign_role" in perms
    can_assign_areas = "adhoc.users.api.assign_areas" in perms

    columns = [
        {"key": "name", "label": "Nombre", "filter": True, "placeholder": "Buscar nombre"},
        {"key": "username", "label": "Usuario", "filter": True, "placeholder": "Buscar usuario"},
        {"key": "email", "label": "Correo", "filter": True, "placeholder": "Buscar correo"},
        {"key": "roles", "label": "Rol en Calidad", "filter": True, "placeholder": "Buscar rol"},
        {"key": "areas", "label": "Áreas", "filter": True, "placeholder": "Buscar área"},
        {"key": "is_active", "label": "Estatus", "filter": True,
         "placeholder": "Activo / Inactivo", "align": "center"},
    ]
    if can_assign_role or can_assign_areas:
        columns.append({"key": "actions", "label": "Acciones", "align": "end"})

    page_data = {
        "roles": [
            {"value": value, "label": label}
            for value, label in ADHOC_APP_ROLE_LABELS.items()
        ],
        "canAssignRole": can_assign_role,
        "canAssignAreas": can_assign_areas,
        "canReadAreas": "adhoc.areas.api.read" in perms,
    }

    return render_adhoc(request, "adhoc/panel/users.html", {
        **ctx,
        "columns": columns,
        "can_assign_role": can_assign_role,
        "can_assign_areas": can_assign_areas,
        "core_config_url": _CORE_CONFIG_URL,
        "page_data": page_data,
    })


# ==========================================================================
# /adhoc/panel/configuracion — enlaces a los catálogos
# ==========================================================================

@router.get("/panel/configuracion")
async def panel_advanced_config(
    request: Request,
    user: dict = Depends(require_page_app("adhoc", perms=["adhoc.panel.page.view"])),
    db: Session = Depends(get_db),
):
    """Tercer nivel de navegación: catálogos, flujos y correo. **Sin JS.**"""
    ctx = _base_ctx(db, user)
    return render_adhoc(request, "adhoc/panel/config.html", {
        **ctx,
        "groups": _config_groups_for(ctx["perms"]),
        "panel_url": _PANEL_URL,
    })


# ==========================================================================
# /adhoc/panel/correo — interruptor global de correo
# ==========================================================================

@router.get("/panel/correo")
async def panel_mail(
    request: Request,
    user: dict = Depends(require_page_app("adhoc", perms=["adhoc.mail.page.view"])),
    db: Session = Depends(get_db),
):
    """Prende o apaga el correo del SGC contra ``/api/adhoc/v2/mail-config``.

    Del legacy no se porta nada de la presentación: 132 líneas de ``<style>``
    inline (incluido un ``.main-container`` con ``!important`` que pisaba el
    layout), un modal casero de éxito y un ``alert()`` en el manejador de error.
    """
    ctx = _base_ctx(db, user)
    can_update = "adhoc.mail.api.update" in ctx["perms"]
    return render_adhoc(request, "adhoc/panel/mail.html", {
        **ctx,
        "can_update": can_update,
        "page_data": {"canUpdate": can_update},
    })
