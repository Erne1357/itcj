"""Vista de secretaría de Prórrogas.

Rutas (todas bajo /prorrogas/secretaria):
  GET ""              → redirige a la primera pestaña con contenido (QR y solicitudes)
  GET /solicitudes    → QR, invitación manual y revisión de pendientes
  GET /documentos     → plantillas de los formatos
  GET /estudiantes    → lista de aceptadas por semestre y expediente (plan, recibos, documentos)
  GET /consulta       → todas las solicitudes con filtros e historial
  GET /estadisticas   → gráficas, cumplimiento de pago y detalle por carrera
  GET /configuracion  → periodo de cada semestre: ventana de solicitudes y fechas comunes de pago

Diseño: docs/design/prorrogas/secretaria-final.dc.html (barra = componente TopNav).
"""
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from itcj2.apps.prorrogas_tec.services.access import perms_of, require_tab
from itcj2.database import get_db
from itcj2.exceptions import PageForbidden, PageLoginRequired
from itcj2.templates import render

logger = logging.getLogger("itcj2.apps.prorrogas_tec.pages.secretaria")

# (clave, etiqueta, permiso). Los códigos van literales: la prueba de contrato los busca en el DML.
TABS = (
    ("estadisticas", "Estadísticas", "prorrogas_tec.secretaria.page.estadisticas"),
    ("solicitudes", "QR y solicitudes", "prorrogas_tec.secretaria.page.solicitudes"),
    ("estudiantes", "Estudiantes", "prorrogas_tec.secretaria.page.estudiantes"),
    ("consulta", "Consulta", "prorrogas_tec.secretaria.page.consulta"),
    ("documentos", "Documentos", "prorrogas_tec.secretaria.page.documentos"),
    ("configuracion", "Configuración", "prorrogas_tec.secretaria.page.configuracion"),
)
_PERM = {key: code for key, _, code in TABS}
_HOME_ORDER = ("solicitudes", "estudiantes", "estadisticas", "consulta", "documentos", "configuracion")

router = APIRouter(prefix="/secretaria", tags=["prorrogas_tec-pages-secretaria"])


def _contexto(request: Request, active: str, title: str) -> dict:
    perms = request.state.prorrogas_perms
    return {
        "title": title,
        "tabs": [(k, label) for k, label, code in TABS if "*" in perms or code in perms],
        "perms": perms,
        "active": active,
    }


@router.get("", name="prorrogas_tec.pages.secretaria.home")
async def secretaria_home(request: Request, db: Session = Depends(get_db)):
    user = getattr(request.state, "current_user", None)
    if not user:
        raise PageLoginRequired()
    perms = perms_of(db, user)
    for key in _HOME_ORDER:
        if "*" in perms or _PERM[key] in perms:
            return RedirectResponse(f"/prorrogas/secretaria/{key}", status_code=302)
    raise PageForbidden(has_app_access=False)


def _tab(key: str, template: str, title: str):
    @router.get(f"/{key}", name=f"prorrogas_tec.pages.secretaria.{key}",
                dependencies=[Depends(require_tab(_PERM[key]))])
    async def view(request: Request):
        return render(request, f"prorrogas_tec/secretaria/{template}.html", _contexto(request, key, title))

    return view


secretaria_solicitudes = _tab("solicitudes", "solicitudes", "Prórrogas · QR y solicitudes")
secretaria_documentos = _tab("documentos", "documentos", "Prórrogas · Documentos")
secretaria_estudiantes = _tab("estudiantes", "estudiantes", "Prórrogas · Estudiantes")
secretaria_configuracion = _tab("configuracion", "configuracion", "Prórrogas · Configuración")
secretaria_consulta = _tab("consulta", "consulta", "Prórrogas · Consulta")
secretaria_estadisticas = _tab("estadisticas", "estadisticas", "Prórrogas · Estadísticas")
