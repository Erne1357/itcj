"""Tablero de la jefa de Servicios Escolares (2026-10-14), SOLO LECTURA.

Permiso `titulatec.reports.page.view` (jefa de SE y `admin`). Rutas: `GET ""`
(página completa) y `GET /body` (solo `#tt-report-body`, para HTMX). Ambas `def`
(threadpool, convención R7). En esta tarea solo renderizan el esqueleto con la
pestaña normalizada; la fachada de datos se conecta después.
"""
import logging

from fastapi import APIRouter, Depends, Request

from itcj2.dependencies import require_page_app
from itcj2.apps.titulatec.pages.nav import render_titulatec

logger = logging.getLogger("itcj2.apps.titulatec.pages.reports_admin")
router = APIRouter(prefix="/admin/tablero", tags=["titulatec-pages-reports"])

_VIEW = ["titulatec.reports.page.view"]

TABS = (
    ("panorama", "Panorama"),
    ("ritmo", "Ritmo"),
    ("encargados", "Encargados"),
    ("carreras", "Carreras"),
    ("atorados", "Atorados"),
)
_TAB_CODES = tuple(code for code, _ in TABS)
_DEFAULT_TAB = "panorama"


def _tab(raw) -> str:
    """Pestaña normalizada; basura o vacío -> `panorama`."""
    value = raw.strip().lower() if isinstance(raw, str) else ""
    return value if value in _TAB_CODES else _DEFAULT_TAB


def _ctx(tab: str) -> dict:
    return {"tab": tab, "tabs": TABS}


@router.get("", name="titulatec.pages.reports.home")
def home(request: Request, tab: str = "",
         user: dict = Depends(require_page_app("titulatec", perms=_VIEW))):
    return render_titulatec(request, "titulatec/admin/reports.html", _ctx(_tab(tab)))


@router.get("/body", name="titulatec.pages.reports.body")
def body(request: Request, tab: str = "",
         user: dict = Depends(require_page_app("titulatec", perms=_VIEW))):
    return render_titulatec(request, "titulatec/admin/partials/reports/_body.html",
                            _ctx(_tab(tab)))
