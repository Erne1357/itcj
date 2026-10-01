"""Router principal de páginas HTML de Sgc / Calidad (prefijo ``/sgi/sgc``).

Cablea las siete secciones de `pages/` en un único `APIRouter` con
``prefix="/sgi/sgc"``. **Ningún sub-router lleva prefijo propio**: cada módulo
declara la ruta completa bajo `/sgi/sgc` (`@router.get("/documentos")`), así que
el prefijo se pone aquí una sola vez y las URLs resultantes son literalmente las
de la tabla del plan §4.

26 rutas (30 URLs contando los 5 `{tipo}` de reportes):

| Sección      | Rutas |
|--------------|-------|
| `home`       | `/sgi/sgc`, `/sgi/sgc/` → 302 `/sgi/sgc/dashboard` |
| `dashboard`  | `/sgi/sgc/dashboard` |
| `panel`      | `/sgi/sgc/panel`, `.../areas`, `.../procesos`, `.../usuarios`, `.../configuracion`, `.../correo` |
| `documents`  | `/sgi/sgc/documentos`, `.../panel`, `.../categorias`, `.../clasificaciones`, `.../flujos`, `.../flujos/{flow_id}/pasos` |
| `incidents`  | `/sgi/sgc/incidencias`, `.../categorias`, `.../{id}/tareas`, `/sgi/sgc/asignaciones` |
| `programs`   | `/sgi/sgc/programas`, `.../categorias`, `.../{id}/tareas` |
| `indicators` | `/sgi/sgc/indicadores`, `.../{year_id}/tablero`, `.../{year_id}/seguimiento` |
| `reports`    | `/sgi/sgc/reportes`, `/sgi/sgc/reportes/{tipo}` |

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

sgc_pages_router = APIRouter(prefix="/sgi/sgc", tags=["sgi-pages"])

# /sgi/sgc (sin barra final). Va aquí y no dentro de home.py porque
# include_router() revienta con "Prefix and path cannot be both empty" si el
# sub-router trae una ruta de path "". Sobre el padre, el prefix="/sgi/sgc" de
# arriba completa la ruta.
sgc_pages_router.add_api_route("", root_no_slash, methods=["GET"], include_in_schema=False)

sgc_pages_router.include_router(home_router)
sgc_pages_router.include_router(dashboard_router)
sgc_pages_router.include_router(documents_router)
sgc_pages_router.include_router(incidents_router)
sgc_pages_router.include_router(programs_router)
sgc_pages_router.include_router(indicators_router)
sgc_pages_router.include_router(reports_router)
sgc_pages_router.include_router(panel_router)
