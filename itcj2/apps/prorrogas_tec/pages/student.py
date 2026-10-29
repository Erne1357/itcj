"""Vista del estudiante de Prórrogas (celular primero).

Rutas (bajo /prorrogas/estudiante):
  GET ""           → Mi prórroga: estado, documentos y cancelar
  GET "/solicitud" → formulario con firma en pantalla
Los datos los traen los JS desde /api/prorrogas/v2/estudiante.
"""
from fastapi import APIRouter, Depends, Request

from itcj2.dependencies import require_page_app
from itcj2.templates import render

_VIEW = ["prorrogas_tec.student.page.view"]

router = APIRouter(
    prefix="/estudiante",
    tags=["prorrogas_tec-pages-estudiante"],
    dependencies=[Depends(require_page_app("prorrogas_tec", perms=_VIEW))],
)


@router.get("", name="prorrogas_tec.pages.estudiante.home")
async def estudiante_home(request: Request):
    return render(request, "prorrogas_tec/estudiante/mi_prorroga.html", {"title": "Mi prórroga"})


@router.get("/solicitud", name="prorrogas_tec.pages.estudiante.solicitud")
async def estudiante_solicitud(request: Request):
    return render(request, "prorrogas_tec/estudiante/solicitud.html", {"title": "Solicitar prórroga"})
