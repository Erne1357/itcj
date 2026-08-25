"""Router principal de páginas HTML de Adhoc / Calidad (prefijo ``/adhoc``).

Cablea las siete secciones de `pages/` en un único `APIRouter` con
``prefix="/adhoc"``. **Ningún sub-router lleva prefijo propio**: cada módulo
declara la ruta completa bajo `/adhoc` (`@router.get("/documentos")`), así que
el prefijo se pone aquí una sola vez y las URLs resultantes son literalmente las
de la tabla del plan §4.

26 rutas (30 URLs contando los 5 `{tipo}` de reportes):

| Sección      | Rutas |
|--------------|-------|
| `home`       | `/adhoc`, `/adhoc/` → 302 `/adhoc/dashboard` |
| `dashboard`  | `/adhoc/dashboard` |
| `panel`      | `/adhoc/panel`, `.../areas`, `.../procesos`, `.../usuarios`, `.../configuracion`, `.../correo` |
| `documents`  | `/adhoc/documentos`, `.../panel`, `.../categorias`, `.../clasificaciones`, `.../flujos`, `.../flujos/{flow_id}/pasos` |
| `incidents`  | `/adhoc/incidencias`, `.../categorias`, `.../{id}/tareas`, `/adhoc/asignaciones` |
| `programs`   | `/adhoc/programas`, `.../categorias`, `.../{id}/tareas` |
| `indicators` | `/adhoc/indicadores`, `.../{year_id}/tablero`, `.../{year_id}/seguimiento` |
| `reports`    | `/adhoc/reportes`, `/adhoc/reportes/{tipo}` |

Orden de inclusión: no hay dos secciones que compitan por la misma forma de
ruta, así que el orden es solo de lectura (raíz → secciones de trabajo →
panel). Dentro de cada módulo sí importa, y ahí las rutas literales
(`/incidencias/categorias`) ya van declaradas antes que las paramétricas
(`/incidencias/{incident_id}/tareas`).
"""
from fastapi import APIRouter

from .dashboard import router as dashboard_router
from .documents import router as documents_router
from .home import root_no_slash
from .home import router as home_router
from .incidents import router as incidents_router
from .indicators import router as indicators_router
from .panel import router as panel_router
from .programs import router as programs_router
from .reports import router as reports_router

adhoc_pages_router = APIRouter(prefix="/adhoc", tags=["adhoc-pages"])

# /adhoc (sin barra final). Va aquí y no dentro de home.py porque
# include_router() revienta con "Prefix and path cannot be both empty" si el
# sub-router trae una ruta de path "". Sobre el padre, el prefix="/adhoc" de
# arriba completa la ruta.
adhoc_pages_router.add_api_route("", root_no_slash, methods=["GET"], include_in_schema=False)

adhoc_pages_router.include_router(home_router)
adhoc_pages_router.include_router(dashboard_router)
adhoc_pages_router.include_router(documents_router)
adhoc_pages_router.include_router(incidents_router)
adhoc_pages_router.include_router(programs_router)
adhoc_pages_router.include_router(indicators_router)
adhoc_pages_router.include_router(reports_router)
adhoc_pages_router.include_router(panel_router)
