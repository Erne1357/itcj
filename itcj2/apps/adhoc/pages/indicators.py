"""Páginas de **indicadores** de Calidad (`adhoc`): años, tablero y seguimiento.

Tres rutas (plan §4), todas bajo el prefijo ``/adhoc`` que pone el router padre:

===================================================  ==============================
URL                                                  Permiso de página
===================================================  ==============================
``GET /adhoc/indicadores?mode=config|tracking``      ``adhoc.indicators.page.list``
``GET /adhoc/indicadores/{year_id}/tablero``         ``adhoc.indicators.page.manage``
``GET /adhoc/indicadores/{year_id}/seguimiento``     ``adhoc.indicators.page.tracking``
===================================================  ==============================

Qué se arregla respecto del legacy (``routes/pages/general.py:153-191`` y sus
tres plantillas):

* **El agujero de seguridad #26.** ``indicators_tracking`` pasaba
  ``is_admin=True`` *hardcodeado* al contexto, pisando el valor real del context
  processor: la plantilla usaba esa bandera para decidir si los inputs iban
  ``disabled`` y si se pintaba el ``<select>`` de color, así que **cualquier
  usuario autenticado podía reescribir todo el seguimiento del SGC**. Aquí
  ``can_edit`` sale de ``adhoc.indicators.api.tracking``, el mismo permiso que
  exige el endpoint que guarda — la UI y la API no pueden discrepar.
* **Los cuatro umbrales son cuatro campos.** El legacy los concatenaba en
  ``planned_value = "b-r-a-v"`` y la propia plantilla los desempaquetaba con
  ``ind.planned_value.split('-')``: un umbral con guion (``"1-2 días"``,
  ``"-5%"``) corrompía las cuatro celdas de la leyenda.
* **``'Semanal'`` es alcanzable.** El render reconocía la frecuencia semanal
  (52 periodos) pero el ``<select>`` del formulario solo ofrecía Mensual y
  Anual, así que era un valor que ninguna UI podía producir.
* **Nada de HTML crudo desde Jinja.** ``INDICADORES_BOARD_CONFIG.htmlProcesos``
  inyectaba ``<option>`` pre-renderizados dentro de un *template literal* de JS.
  Aquí los procesos viajan como JSON en el bloque ``page_data`` y el ``<select>``
  lo construye el módulo con ``escapeHtml()``.

Contrato con el JS: cada página emite un único ``<script type="application/json"
id="adhoc-page-data">`` (macro ``page_data_script``) que el módulo lee con
``AdhocUtils.pageData()``. Las mutaciones van todas a ``/api/adhoc/v2/…``.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from itcj2.database import get_db
from itcj2.dependencies import require_page_app

logger = logging.getLogger(__name__)

router = APIRouter()

__all__ = ["router"]


# ==========================================================================
# Constantes de presentación
# ==========================================================================

#: Los dos modos de la lista de años. ``config`` lleva al tablero de captura;
#: ``tracking`` al seguimiento por colores. Cualquier otro valor cae en
#: ``config`` (el legacy no validaba nada y arrastraba el string a la URL).
MODE_CONFIG = "config"
MODE_TRACKING = "tracking"
MODES = (MODE_CONFIG, MODE_TRACKING)

#: Permiso de página al que lleva cada modo. Si el usuario no lo tiene, la lista
#: cambia de modo sola en vez de ofrecerle un enlace que responderá 403.
MODE_PAGE_PERM = {
    MODE_CONFIG: "adhoc.indicators.page.manage",
    MODE_TRACKING: "adhoc.indicators.page.tracking",
}

#: Ruta de cada sub-página, colgando de ``/adhoc/indicadores/{year_id}``. Vive
#: junto al permiso porque las dos mitades del enlace —a dónde lleva y quién
#: puede entrar— tienen que decidirse a la vez; ver ``_mode_url``.
MODE_PATH_SUFFIX = {
    MODE_CONFIG: "/tablero",
    MODE_TRACKING: "/seguimiento",
}

#: Raíz de la lista de años, base de los enlaces de fila.
YEARS_URL = "/adhoc/indicadores"

#: Cómo se llama un periodo en la rejilla de seguimiento, según la frecuencia.
#: El número de periodos NO se decide aquí: sale de
#: ``TRACKING_PERIODS_BY_FREQUENCY`` (utils/constants.py), que es el mismo mapa
#: que usa ``IndicatorService.upsert_tracking`` para acotar ``period_index``.
#: Pintar más celdas de las que el service acepta sería regalar 400s.
PERIOD_LABEL = {
    "Semanal": "Semana",
    "Mensual": "Mes",
    "Anual": "Año",
}
PERIOD_LABEL_DEFAULT = "Periodo"

#: Cuántas celdas pintar cuando el indicador no declara frecuencia. El legacy
#: usaba 12 como caso por defecto de su cadena de ``{% if %}``; se conserva.
#: Es seguro: sin frecuencia el service acota ``period_index`` a 0-52.
PERIODS_FALLBACK = 12

#: Color del tracking → clase de estado de ``adhoc.css``. Las
#: ``.bg-blanco/.bg-rojo/.bg-amarillo/.bg-verde`` del legacy colisionaban con
#: las utilidades ``.bg-*`` de Bootstrap 5.3.
COLOR_CLASS = {
    "blanco": "adhoc-state-white",
    "rojo": "adhoc-state-red",
    "amarillo": "adhoc-state-yellow",
    "verde": "adhoc-state-green",
}

#: Etiqueta legible de cada color, para el ``<select>`` y la leyenda.
COLOR_LABEL = {
    "blanco": "Blanco",
    "rojo": "Rojo",
    "amarillo": "Amarillo",
    "verde": "Verde",
}


# ==========================================================================
# Helpers
# ==========================================================================

def _perm_checker(db: Session, user: dict | None):
    """Devuelve ``can(code) -> bool`` para los permisos de ``adhoc``.

    El admin global del JWT (``role == "admin"``) tiene todo, igual que en
    ``require_perms``. Si el cálculo revienta se devuelve *fail-closed*: sin
    permisos, la página se pinta en solo lectura en vez de ofrecer botones que
    después dan 403.
    """
    if not user:
        return lambda code: False
    if user.get("role") == "admin":
        return lambda code: True

    from itcj2.core.services.authz_cache import cached_perms

    try:
        perms = cached_perms(db, int(user["sub"]), "adhoc")
    except Exception as exc:  # pragma: no cover - defensivo
        logger.warning("adhoc indicadores: no se pudieron calcular permisos: %s", exc)
        perms = set()
    return lambda code: code in perms


def _puede_entrar(can, mode: str) -> bool:
    """¿*can* abre la sub-página de *mode*? **Única copia de la regla.**

    Las tres pantallas se enlazan entre sí y las tres preguntan lo mismo: si el
    usuario tiene el permiso de página del destino. Escribir el código del
    permiso a mano en cada una era la forma de que se desincronizaran (A27):
    la lista de años sí lo comprobaba y las dos sub-páginas se ofrecían la una
    a la otra sin preguntar.
    """
    return can(MODE_PAGE_PERM[mode])


def _swap_url(can, effective: str) -> str:
    """URL de la lista de años en el **otro** modo, o ``""`` si no puede entrar.

    El enlace que conmuta de modo es el TERCER enlace cruzado de indicadores, y
    hasta aquí era el único que se pintaba sin preguntar (A27): la plantilla
    miraba ``mode`` y nada más, así que a quien no tiene
    ``adhoc.indicators.page.manage`` —hoy todos menos ``admin``— se le ofrecía
    un "Ir a configuración" que volvía a la MISMA pantalla, porque
    ``indicator_years_page`` reconmuta el modo al entrar. Un botón que no hace
    nada dos veces seguidas es peor que no tenerlo.

    Mismo criterio y misma función que ``_mode_url``: sin permiso no hay
    enlace.
    """
    otro = MODE_TRACKING if effective == MODE_CONFIG else MODE_CONFIG
    if not _puede_entrar(can, otro):
        return ""
    return f"{YEARS_URL}?mode={otro}"


def _mode_url(can, mode: str, year_id: int) -> str:
    """URL de la sub-página de *mode* para *year_id*, o ``""`` si no puede entrar.

    Cadena vacía —y no la URL— porque es el mismo criterio de ``target_base``
    en la lista de años: **sin permiso no hay enlace**, ni en el HTML ni en el
    bloque ``page_data``. Un enlace a una página que responde 403 no se ve como
    un error: con ``hx-boost`` el 403 no intercambia nada, así que el botón
    simplemente no hace nada al pulsarlo.
    """
    if not _puede_entrar(can, mode):
        return ""
    return f"{YEARS_URL}/{year_id}{MODE_PATH_SUFFIX[mode]}"


def _get_year_or_404(db: Session, year_id: int):
    """El año del tablero, o un 404 que el handler global pinta como página."""
    from itcj2.apps.adhoc.services.indicator_service import IndicatorService

    year = IndicatorService.get_year(db, year_id)
    if year is None:
        raise HTTPException(status_code=404, detail="El año de indicadores no existe")
    return year


def _processes(db: Session) -> list[dict]:
    """Procesos del SGC para el ``<select>`` del formulario del tablero.

    Salen como JSON (id/nombre/color); el ``<option>`` lo construye el módulo JS
    escapando el nombre. El legacy los inyectaba como HTML crudo dentro de un
    *template literal* — uno de los siete vectores de XSS del plan §6.2.
    """
    from itcj2.apps.adhoc.models import AdhocProcess
    from itcj2.apps.adhoc.services.catalog_service import AdhocCatalogService

    return [
        {"id": p.id, "name": p.name, "color": p.color}
        for p in AdhocCatalogService.list_items(db, AdhocProcess)
    ]


def _tracking_cards(indicators) -> list[dict]:
    """Modela la rejilla de seguimiento: una tarjeta por indicador.

    El armado va aquí y no en Jinja a propósito: la plantilla del legacy
    calculaba el número de periodos con una cadena de ``{% set %}``/``{% if %}``,
    resolvía la celda de cada periodo con
    ``ind.trackings | selectattr('period_index','equalto', i) | first`` (O(n·m)
    dentro de un doble bucle) y desempaquetaba los umbrales con ``split('-')``.

    Numeración: **1..N**, la misma que ve el usuario y la misma que manda el JS
    como ``period_index``. Entra en el rango que valida el service (``0..N``).
    """
    from itcj2.apps.adhoc.utils.constants import (
        TRACKING_COLOR_DEFAULT,
        TRACKING_PERIODS_BY_FREQUENCY,
    )

    cards: list[dict] = []
    for ind in indicators:
        frequency = ind.frequency or ""
        periods = TRACKING_PERIODS_BY_FREQUENCY.get(frequency, PERIODS_FALLBACK)
        by_period = {t.period_index: t for t in (ind.trackings or [])}

        cells = []
        for index in range(1, periods + 1):
            tracking = by_period.get(index)
            color = getattr(tracking, "color", None) or TRACKING_COLOR_DEFAULT
            cells.append({
                "index": index,
                "value": getattr(tracking, "real_value", None) or "",
                "color": color,
                "color_class": COLOR_CLASS.get(color, COLOR_CLASS[TRACKING_COLOR_DEFAULT]),
            })

        process = getattr(ind, "process", None)
        cards.append({
            "id": ind.id,
            "process_name": getattr(process, "name", None) or "Sin proceso",
            "process_color": getattr(process, "color", None) or "#b2bec3",
            "objective": ind.objective or "",
            "responsible": ind.responsible or "",
            "frequency": ind.frequency or "",
            "unit_calc": ind.unit_calc or "",
            "criteria": ind.criteria or "",
            "plan_b": ind.plan_b or "",
            "has_document": bool(ind.document_url),
            # Los cuatro umbrales, cada uno en su columna (bug #16 del legacy).
            "planned_white": ind.planned_white or "",
            "planned_red": ind.planned_red or "",
            "planned_yellow": ind.planned_yellow or "",
            "planned_green": ind.planned_green or "",
            "period_label": PERIOD_LABEL.get(frequency, PERIOD_LABEL_DEFAULT),
            "periods": periods,
            "cells": cells,
        })
    return cards


# ==========================================================================
# GET /adhoc/indicadores
# ==========================================================================

@router.get("/indicadores")
async def indicator_years_page(
    request: Request,
    mode: str = Query(MODE_CONFIG, description="config = tablero · tracking = seguimiento"),
    user: dict = Depends(require_page_app("adhoc", perms=["adhoc.indicators.page.list"])),
    db: Session = Depends(get_db),
):
    """Lista de años del tablero de indicadores.

    ``?mode=config`` (por defecto) enlaza cada año con su **tablero** de
    captura; ``?mode=tracking`` con su **seguimiento** por colores — es el modo
    al que apunta el menú principal.

    Si el usuario no tiene el permiso de página del destino pedido pero sí el
    del otro, el modo se conmuta solo: enseñar un enlace que responde 403 es
    peor que llevar al usuario a donde sí puede entrar. Sin ninguno de los dos,
    los años se pintan sin enlace — y **tampoco se pinta el conmutador de
    modo** (``swap_url``), que si no sería un botón que devuelve a esta misma
    pantalla porque la conmutación de arriba lo deshace.
    """
    from itcj2.apps.adhoc.pages.nav import nav_for_user
    from itcj2.apps.adhoc.pages.render import render_adhoc
    from itcj2.apps.adhoc.schemas.indicators import IndicatorYearOut
    from itcj2.apps.adhoc.services.indicator_service import IndicatorService

    can = _perm_checker(db, user)

    requested = mode if mode in MODES else MODE_CONFIG
    other = MODE_TRACKING if requested == MODE_CONFIG else MODE_CONFIG
    if not _puede_entrar(can, requested) and _puede_entrar(can, other):
        effective = other
    else:
        effective = requested

    years = [
        IndicatorYearOut.from_model(year, count).model_dump(mode="json")
        for year, count in IndicatorService.list_years(db)
    ]

    page_data = {
        "mode": effective,
        # Base del enlace de cada fila. Vacía = filas no clicables.
        "target_base": f"{YEARS_URL}/" if _puede_entrar(can, effective) else "",
        "target_suffix": MODE_PATH_SUFFIX[effective],
        "years": years,
        "can_create": can("adhoc.indicators.api.create"),
        "can_delete": can("adhoc.indicators.api.delete"),
    }

    return render_adhoc(
        request,
        "adhoc/indicators/years.html",
        {
            "nav": nav_for_user(db, user),
            "mode": effective,
            # Destino ya resuelto, no el modo pelado: la plantilla no tiene con
            # qué preguntar por el permiso, así que si se le pasa solo `mode`
            # pinta el enlace contrario siempre. Vacío = no se pinta.
            "swap_url": _swap_url(can, effective),
            "page_data": page_data,
            "can_create": page_data["can_create"],
        },
    )


# ==========================================================================
# GET /adhoc/indicadores/{year_id}/tablero
# ==========================================================================

@router.get("/indicadores/{year_id}/tablero")
async def indicator_board_page(
    request: Request,
    year_id: int,
    user: dict = Depends(require_page_app("adhoc", perms=["adhoc.indicators.page.manage"])),
    db: Session = Depends(get_db),
):
    """Tablero de un año: alta, edición y baja de las fichas de indicador.

    Los **cuatro umbrales son cuatro campos** del formulario
    (``planned_white`` / ``planned_red`` / ``planned_yellow`` / ``planned_green``),
    no un string ``"b-r-a-v"``, y el ``<select>`` de frecuencia ofrece las tres
    frecuencias que el ``CheckConstraint`` admite — **``'Semanal'`` incluida**,
    que en el legacy era inalcanzable desde la UI.
    """
    from itcj2.apps.adhoc.pages.nav import nav_for_user
    from itcj2.apps.adhoc.pages.render import render_adhoc
    from itcj2.apps.adhoc.schemas.indicators import IndicatorOut
    from itcj2.apps.adhoc.services.indicator_service import IndicatorService
    from itcj2.apps.adhoc.utils.constants import INDICATOR_FREQUENCIES

    year = _get_year_or_404(db, year_id)
    can = _perm_checker(db, user)
    # Enlace al seguimiento: vacío si no puede entrar, igual que las filas de la
    # lista de años. La plantilla lo pinta bajo `can_track`, que es exactamente
    # "hay enlace" — no una segunda lectura del permiso que pueda discrepar.
    tracking_url = _mode_url(can, MODE_TRACKING, year.id)

    indicators = [
        IndicatorOut.from_model(row, include_trackings=False).model_dump(mode="json")
        for row in IndicatorService.list_indicators(db, year_id)
    ]

    page_data = {
        "year": {"id": year.id, "year": year.year},
        "indicators": indicators,
        "processes": _processes(db),
        "frequencies": list(INDICATOR_FREQUENCIES),
        "api": {
            "indicators": "/api/adhoc/v2/indicators",
            "download": "/api/adhoc/v2/indicators/{id}/download",
        },
        "tracking_url": tracking_url,
        "can_create": can("adhoc.indicators.api.create"),
        "can_update": can("adhoc.indicators.api.update"),
        "can_delete": can("adhoc.indicators.api.delete"),
        "can_download": can("adhoc.indicators.api.download"),
        "can_track": bool(tracking_url),
    }

    return render_adhoc(
        request,
        "adhoc/indicators/board.html",
        {
            "nav": nav_for_user(db, user),
            "year": year,
            "page_data": page_data,
            "can_create": page_data["can_create"],
            "can_track": page_data["can_track"],
            "tracking_url": page_data["tracking_url"],
        },
    )


# ==========================================================================
# GET /adhoc/indicadores/{year_id}/seguimiento
# ==========================================================================

@router.get("/indicadores/{year_id}/seguimiento")
async def indicator_tracking_page(
    request: Request,
    year_id: int,
    user: dict = Depends(require_page_app("adhoc", perms=["adhoc.indicators.page.tracking"])),
    db: Session = Depends(get_db),
):
    """Rejilla de seguimiento por colores de un año.

    ``can_edit`` decide si los inputs van habilitados y si se pinta el
    ``<select>`` de color, y sale del permiso **real**
    ``adhoc.indicators.api.tracking`` — el mismo que exige
    ``PUT /api/adhoc/v2/indicator-trackings``. El legacy pasaba
    ``is_admin=True`` hardcodeado en la ruta (bug #26 del plan), de modo que la
    plantilla habilitaba la edición para todo el mundo y el endpoint que
    guardaba era anónimo: cualquiera podía reescribir el seguimiento del SGC.
    """
    from itcj2.apps.adhoc.pages.nav import nav_for_user
    from itcj2.apps.adhoc.pages.render import render_adhoc
    from itcj2.apps.adhoc.services.indicator_service import IndicatorService
    from itcj2.apps.adhoc.utils.constants import TRACKING_COLORS

    year = _get_year_or_404(db, year_id)
    can = _perm_checker(db, user)
    can_edit = can("adhoc.indicators.api.tracking")
    # Vuelta al tablero, con el mismo criterio que el enlace de ida.
    board_url = _mode_url(can, MODE_CONFIG, year.id)

    cards = _tracking_cards(IndicatorService.list_indicators(db, year_id))

    page_data = {
        "year": {"id": year.id, "year": year.year},
        "can_edit": can_edit,
        "api": {"trackings": "/api/adhoc/v2/indicator-trackings"},
        # El JS necesita el mapa color → clase para repintar la celda al vuelo
        # sin duplicar la tabla (y sin resucitar las .bg-* del legacy).
        "color_classes": {color: COLOR_CLASS[color] for color in TRACKING_COLORS},
    }

    return render_adhoc(
        request,
        "adhoc/indicators/tracking.html",
        {
            "nav": nav_for_user(db, user),
            "year": year,
            "cards": cards,
            "can_edit": can_edit,
            "colors": [
                {"value": color, "label": COLOR_LABEL[color]} for color in TRACKING_COLORS
            ],
            "board_url": board_url,
            "can_manage": bool(board_url),
            # Enlace de descarga de la evidencia: funcionalidad NUEVA (el legacy
            # permitía subir el documento estándar pero no recuperarlo).
            "can_download": can("adhoc.indicators.api.download"),
            "page_data": page_data,
        },
    )
