"""Centro de Reportes de Calidad — 6 URLs, todas con ``adhoc.reports.page.view``.

    GET /adhoc/reportes           pantalla de selección (5 tarjetas + filtros)
    GET /adhoc/reportes/{tipo}    el reporte imprimible, con ``tipo`` ∈ los 5 del plan §4

**Esto es una página, no una API.** En el legacy los cinco reportes se servían
desde ``/api/reportes/generar/<tipo>`` devolviendo HTML (bug #21 del plan): un
endpoint de API que respondía ``text/html``, sin autenticación, y que además
podía devolver la cadena cruda ``"Reporte no encontrado"`` con un 404.

Aquí:

* el gate es ``require_page_app("adhoc", perms=["adhoc.reports.page.view"])`` —
  anónimo → redirección a ``/itcj/login``; sin permiso → página 403 de la app;
* un ``tipo`` desconocido es ``HTTPException(404)``, que para una ruta que no
  empieza por ``/api/`` el handler global de ``itcj2/main.py`` convierte en la
  **página** de error 404 (no en un JSON);
* toda la lógica vive en ``services/report_service.py``: la vista solo resuelve
  quién pregunta, cuándo, y con qué filtros.

Los nombres de los parámetros de query (``f_nombre``, ``f_apellidos``,
``f_area``, ``formato``) se conservan **literalmente** los del legacy: son los
que emite el formulario de selección y los que aparecen impresos en la cabecera
del reporte, y mantenerlos permite que un enlace guardado siga funcionando.
"""
from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from itcj2.apps.adhoc.pages.nav import nav_for_user
from itcj2.apps.adhoc.pages.render import render_adhoc
from itcj2.database import get_db
from itcj2.dependencies import require_page_app

logger = logging.getLogger(__name__)

#: Sin prefijo propio: lo pone ``pages/router.py`` (``prefix="/adhoc"``) en la
#: fase de cableado. Declararlo aquí duplicaría el segmento.
router = APIRouter()

#: Único permiso de la sección (plan §4). Las dos rutas comparten gate: el
#: listado no enseña nada que el reporte no enseñe.
REPORTS_PERM = "adhoc.reports.page.view"

_page_guard = require_page_app("adhoc", perms=[REPORTS_PERM])


def _requester(user: dict | None) -> str:
    """Nombre para la línea "Solicitado por" del encabezado impreso.

    Sale del JWT (``name``), que ya viaja en la cookie: el legacy hacía lo mismo
    con ``g.current_user`` y caía a "Administrador" cuando no había sesión —
    algo que aquí no puede pasar, porque la ruta está detrás del gate.
    """
    if not user:
        return "N/A"
    return (user.get("name") or user.get("username") or "N/A").strip() or "N/A"


@router.get("/reportes")
async def reports_index(
    request: Request,
    user: dict = Depends(_page_guard),
    db: Session = Depends(get_db),
):
    """Pantalla de selección: las 5 tarjetas + el modal de filtros.

    Las vistas previas (usuarios y documentos) se emiten como JSON dentro de
    ``<script type="application/json">`` y las pinta el módulo JS escapando cada
    celda. El legacy las renderizaba desde Jinja y, para el ``<select>`` de
    áreas, concatenaba ``<option>`` a mano dentro de un template literal — uno
    de los siete vectores de XSS del plan §6.2.
    """
    from itcj2.apps.adhoc.services.report_service import ReportService

    data = ReportService.get_selection_data(db)

    return render_adhoc(
        request,
        "adhoc/reports/reports.html",
        {
            "nav": nav_for_user(db, user),
            "reports": data["reports"],
            "areas": data["areas"],
            "page_data": data,
        },
    )


@router.get("/reportes/{tipo}")
async def report_view(
    request: Request,
    tipo: str,
    f_nombre: str = Query("", max_length=120),
    f_apellidos: str = Query("", max_length=120),
    f_area: str = Query("", max_length=120),
    formato: str = Query("sencillo", max_length=20),
    user: dict = Depends(_page_guard),
    db: Session = Depends(get_db),
):
    """Un reporte imprimible. ``tipo`` ∈ los 5 tipos de ``REPORT_META``.

    Se declara ``tipo: str`` y se valida contra el service en vez de tiparlo
    como ``Literal``: un ``Literal`` haría que ``/adhoc/reportes/loquesea``
    respondiera un **422 en JSON** (el handler de ``RequestValidationError`` no
    distingue páginas de API), cuando lo correcto para una página es la página
    de error 404.
    """
    from itcj2.apps.adhoc.services.report_service import ReportService

    try:
        report = ReportService.build_report(
            db,
            tipo,
            nombre=f_nombre,
            apellidos=f_apellidos,
            area=f_area,
            formato=formato,
        )
    except LookupError:
        logger.info("adhoc reports: tipo de reporte inexistente %r", tipo)
        raise HTTPException(status_code=404, detail="Reporte no encontrado")

    now = datetime.now()

    return render_adhoc(
        request,
        "adhoc/reports/view_report.html",
        {
            "nav": nav_for_user(db, user),
            "report": report,
            "requester": _requester(user),
            "issued_date": now.strftime("%d/%m/%Y"),
            "issued_time": now.strftime("%H:%M:%S"),
            # Lo mínimo que el módulo JS necesita para nombrar la hoja y el
            # archivo de Excel. Los 5 archivos del legacy eran el MISMO código
            # repetido solo para cambiar estos dos valores.
            "page_data": {
                "reportType": report["report_type"],
                "sheet": report["sheet"],
                "filePrefix": report["file_prefix"],
                "date": now.strftime("%d/%m/%Y"),
                "rows": report["total"],
            },
        },
    )
