"""Adhoc (Calidad) — router de API (v2).

Ensamblado de los sub-routers de ``itcj2/apps/adhoc/api/``. La regla del plan
(§3) es que **el prefijo del recurso lo pone el padre**: el hijo declara solo
``APIRouter(tags=["adhoc-{recurso}"])`` y aquí se monta con
``include_router(x, prefix="/y")``.

Dos excepciones deliberadas:

* ``catalogs.router`` ya es un router **agregado** que trae dentro sus seis
  segmentos (``/areas``, ``/processes``, ``/document-categories``,
  ``/document-classifications``, ``/incident-categories``,
  ``/program-categories``), así que se incluye **sin prefijo**.
* Los pasos de flujo cuelgan del router de flujos: dentro de ``flows.py`` se
  declaran como ``/steps/{step_id}`` y la URL final queda
  ``/api/adhoc/v2/approval-flows/steps/{step_id}``.
"""
from fastapi import APIRouter

from itcj2.apps.adhoc.api.catalogs import router as catalogs_router
from itcj2.apps.adhoc.api.documents import router as documents_router
from itcj2.apps.adhoc.api.flows import router as flows_router
from itcj2.apps.adhoc.api.incidents import router as incidents_router
from itcj2.apps.adhoc.api.indicators import router as indicators_router
from itcj2.apps.adhoc.api.indicators import trackings_router as indicator_trackings_router
from itcj2.apps.adhoc.api.indicators import years_router as indicator_years_router
from itcj2.apps.adhoc.api.mail import router as mail_router
from itcj2.apps.adhoc.api.programs import router as programs_router
from itcj2.apps.adhoc.api.tasks import router as tasks_router
from itcj2.apps.adhoc.api.users import router as users_router

adhoc_router = APIRouter(prefix="/api/adhoc/v2", tags=["adhoc"])

# Catálogos (agregado: trae sus propios segmentos) ---------------------------
adhoc_router.include_router(catalogs_router)

# Documentos y flujos de aprobación -----------------------------------------
adhoc_router.include_router(flows_router, prefix="/approval-flows")
adhoc_router.include_router(documents_router, prefix="/documents")

# Incidencias ----------------------------------------------------------------
adhoc_router.include_router(incidents_router, prefix="/incidents")

# Programa (calendario) ------------------------------------------------------
adhoc_router.include_router(programs_router, prefix="/program-events")

# Tareas y workflow ----------------------------------------------------------
adhoc_router.include_router(tasks_router, prefix="/tasks")

# Indicadores ----------------------------------------------------------------
adhoc_router.include_router(indicator_years_router, prefix="/indicator-years")
adhoc_router.include_router(indicators_router, prefix="/indicators")
adhoc_router.include_router(indicator_trackings_router, prefix="/indicator-trackings")

# Configuración de correo ----------------------------------------------------
adhoc_router.include_router(mail_router, prefix="/mail-config")

# Administración de usuarios de la app ---------------------------------------
adhoc_router.include_router(users_router, prefix="/users")
