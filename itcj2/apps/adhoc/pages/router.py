"""Router principal de páginas HTML de Adhoc / Calidad (prefijo /adhoc)."""
from fastapi import APIRouter

from .home import root_no_slash
from .home import router as home_router

adhoc_pages_router = APIRouter(prefix="/adhoc", tags=["adhoc-pages"])

# /adhoc (sin barra final). Va aquí y no dentro de home.py porque
# include_router() revienta con "Prefix and path cannot be both empty" si el
# sub-router trae una ruta de path "". Sobre el padre, el prefix="/adhoc" de
# arriba completa la ruta.
adhoc_pages_router.add_api_route("", root_no_slash, methods=["GET"], include_in_schema=False)

adhoc_pages_router.include_router(home_router)
# TODO(F5): incluir aquí los routers de sección (documentos, incidencias,
# programas, indicadores, panel, reportes, asignaciones).
