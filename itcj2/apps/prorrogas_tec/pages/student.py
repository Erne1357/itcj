"""Vista del estudiante de Prórrogas (celular primero).

Rutas (bajo /prorrogas/estudiante):
  GET ""           → Mi prórroga: estado, documentos y cancelar
  GET "/solicitud" → formulario con firma en pantalla
Los datos los traen los JS desde /api/prorrogas/v2/estudiante.
"""
from fastapi import APIRouter, Depends, Request

from itcj2.apps.prorrogas_tec.services.identity import nombre_corto
from itcj2.core.models.user import User
from itcj2.dependencies import DbSession, require_page_app
from itcj2.templates import render

_VIEW = ["prorrogas_tec.student.page.view"]

router = APIRouter(
    prefix="/estudiante",
    tags=["prorrogas_tec-pages-estudiante"],
    dependencies=[Depends(require_page_app("prorrogas_tec", perms=_VIEW))],
)


def _render(request, db, template: str, title: str):
    u = db.query(User.first_name, User.last_name).filter_by(id=int(request.state.current_user["sub"])).first()
    return render(request, f"prorrogas_tec/estudiante/{template}",
                  {"title": title, "nombre_corto": nombre_corto(*u) if u else ""})


@router.get("", name="prorrogas_tec.pages.estudiante.home")
def estudiante_home(request: Request, db: DbSession):
    return _render(request, db, "mi_prorroga.html", "Mi prórroga")


@router.get("/solicitud", name="prorrogas_tec.pages.estudiante.solicitud")
def estudiante_solicitud(request: Request, db: DbSession):
    return _render(request, db, "solicitud.html", "Solicitar prórroga")
