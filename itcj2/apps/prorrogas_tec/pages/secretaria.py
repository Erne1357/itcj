"""Vista de secretaría de Prórrogas.

Rutas (todas bajo /prorrogas/secretaria):
  GET ""              → redirige a la primera pestaña con contenido (QR y solicitudes)
  GET /solicitudes    → QR, invitación manual y revisión de pendientes
  GET /documentos     → plantillas de los formatos
  GET /estudiantes    → lista de aceptadas por semestre y expediente (plan, recibos, documentos)
  GET /estadisticas   → gráficas, cumplimiento de pago y detalle por carrera

Diseño: docs/design/prorrogas/secretaria-final.dc.html (barra = componente TopNav).
"""
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse

from itcj2.dependencies import require_page_app
from itcj2.templates import render

logger = logging.getLogger("itcj2.apps.prorrogas_tec.pages.secretaria")

TABS = (
    ("estadisticas", "Estadísticas"),
    ("solicitudes", "QR y solicitudes"),
    ("estudiantes", "Estudiantes"),
    ("documentos", "Documentos"),
)

_VIEW = ["prorrogas_tec.secretaria.page.view"]

router = APIRouter(
    prefix="/secretaria",
    tags=["prorrogas_tec-pages-secretaria"],
    dependencies=[Depends(require_page_app("prorrogas_tec", perms=_VIEW))],
)


@router.get("", name="prorrogas_tec.pages.secretaria.home")
async def secretaria_home():
    return RedirectResponse("/prorrogas/secretaria/solicitudes", status_code=302)


@router.get("/solicitudes", name="prorrogas_tec.pages.secretaria.solicitudes")
async def secretaria_solicitudes(request: Request):
    return render(request, "prorrogas_tec/secretaria/solicitudes.html", {
        "title": "Prórrogas · QR y solicitudes",
        "tabs": TABS,
        "active": "solicitudes",
    })


@router.get("/documentos", name="prorrogas_tec.pages.secretaria.documentos")
async def secretaria_documentos(request: Request):
    return render(request, "prorrogas_tec/secretaria/documentos.html", {
        "title": "Prórrogas · Documentos",
        "tabs": TABS,
        "active": "documentos",
    })


@router.get("/estudiantes", name="prorrogas_tec.pages.secretaria.estudiantes")
async def secretaria_estudiantes(request: Request):
    return render(request, "prorrogas_tec/secretaria/estudiantes.html", {
        "title": "Prórrogas · Estudiantes",
        "tabs": TABS,
        "active": "estudiantes",
    })


@router.get("/estadisticas", name="prorrogas_tec.pages.secretaria.estadisticas")
async def secretaria_estadisticas(request: Request):
    return render(request, "prorrogas_tec/secretaria/estadisticas.html", {
        "title": "Prórrogas · Estadísticas",
        "tabs": TABS,
        "active": "estadisticas",
    })
