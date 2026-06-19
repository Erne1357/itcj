import asyncio
import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger("itcj2")


# ---------------------------------------------------------------------------
# Redis Pub/Sub — subscriber de eventos de tareas Celery
# ---------------------------------------------------------------------------

async def _handle_task_event(data: dict) -> None:
    """Procesa un evento recibido del canal Redis 'task_events' y lo
    retransmite por Socket.IO al usuario correspondiente.

    Tipos de evento:
        task_completed    — tarea finalizada (SUCCESS/FAILURE), emite 'task_event'
        user_notification — notificación individual,   emite 'notify'
    """
    from itcj2.sockets.notifications import push_notification

    event_type = data.get("type")
    user_id = data.get("user_id")

    if not user_id:
        return

    if event_type == "task_completed":
        await push_notification(user_id, {
            "type": "task_event",
            "task_run_id": data.get("task_run_id"),
            "task_name": data.get("task_name"),
            "status": data.get("status"),
        })

    elif event_type == "user_notification":
        notification = data.get("notification")
        if notification:
            await push_notification(user_id, notification)


async def _redis_task_subscriber() -> None:
    """Background task que escucha el canal 'task_events' de Redis y
    retransmite los mensajes por Socket.IO al usuario correcto.

    Se reconecta automáticamente ante fallos de conexión.
    """
    import redis.asyncio as aioredis
    from itcj2.config import get_settings

    settings = get_settings()

    while True:
        try:
            async with aioredis.from_url(settings.REDIS_URL) as r:
                async with r.pubsub() as pubsub:
                    await pubsub.subscribe("task_events")
                    logger.info("Redis Pub/Sub: suscrito al canal 'task_events'")

                    async for message in pubsub.listen():
                        if message["type"] != "message":
                            continue
                        try:
                            data = json.loads(message["data"])
                            await _handle_task_event(data)
                        except Exception as e:
                            logger.error(
                                f"Redis subscriber: error procesando mensaje: {e}"
                            )

        except asyncio.CancelledError:
            logger.info("Redis subscriber: detenido (shutdown)")
            break
        except Exception as e:
            logger.error(
                f"Redis subscriber: error de conexión, reintentando en 5s: {e}"
            )
            await asyncio.sleep(5)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup y shutdown de la aplicación."""
    logger.info("FastAPI ITCJ v2 iniciando...")

    # Capturar el event loop principal para que async_broadcast funcione
    # desde endpoints síncronos (que corren en el threadpool).
    from itcj2.utils import set_main_loop
    set_main_loop(asyncio.get_running_loop())

    # Iniciar subscriber de Redis Pub/Sub para eventos de tareas Celery.
    subscriber_task = asyncio.create_task(_redis_task_subscriber())

    yield

    # Shutdown: detener subscriber y cerrar pool de conexiones.
    subscriber_task.cancel()
    try:
        await subscriber_task
    except asyncio.CancelledError:
        pass

    from itcj2.database import engine
    engine.dispose()
    logger.info("FastAPI ITCJ v2 detenido.")


def create_app() -> FastAPI:
    app = FastAPI(
        title="ITCJ Platform API",
        version="2.0.0",
        description="API v2 de la plataforma ITCJ (FastAPI)",
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )

    # Middleware (JWT, CORS)
    from .middleware import setup_middleware
    setup_middleware(app)

    # Routers
    from .routers import register_routers
    register_routers(app)

    # Liveness — barato, solo confirma que el proceso responde.
    @app.get("/health", tags=["system"])
    async def health():
        return {"ok": True, "server": "fastapi", "version": "2.0.0"}

    # Readiness — confirma que PUEDE servir: DB (via pgbouncer) + Redis.
    # El healthcheck de Docker y el gate de promoción de deploy.sh apuntan aquí,
    # para que blue/green NO promueva un backend que booteó pero no conecta.
    @app.get("/ready", tags=["system"])
    def ready():
        from sqlalchemy import text
        errors = {}
        try:
            from itcj2.database import engine
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
        except Exception as e:  # pragma: no cover
            errors["db"] = str(e)
        try:
            from itcj2.core.utils.redis_conn import get_redis
            get_redis().ping()
        except Exception as e:  # pragma: no cover
            errors["redis"] = str(e)
        if errors:
            return JSONResponse(status_code=503, content={"ready": False, "errors": errors})
        return {"ready": True}

    # Error handlers
    _register_error_handlers(app)

    return app


def _register_error_handlers(app: FastAPI):
    """Manejo centralizado de errores (equivalente a register_error_handlers de Flask).

    Los exception handlers de FastAPI son globales (a nivel app, no por router).
    Para que cada app muestre su página de error con su propia estética, el
    renderizador elige el template según el prefijo de la ruta.
    """

    from fastapi.responses import RedirectResponse
    from .exceptions import PageForbidden, PageLoginRequired

    # ── Errores HTTP generales ────────────────────────────────────────────────
    ERROR_MESSAGES = {
        400: {"title": "Solicitud Incorrecta", "message": "La solicitud no pudo ser procesada."},
        401: {"title": "No Autorizado", "message": "Necesitas autenticarte para acceder a este recurso."},
        403: {"title": "Acceso Prohibido", "message": "No tienes permisos para acceder a este recurso."},
        404: {"title": "Página No Encontrada", "message": "El recurso que buscas no existe o ha sido movido."},
        405: {"title": "Método No Permitido", "message": "El método HTTP no está permitido para este recurso."},
        409: {"title": "Conflicto de Recurso", "message": "Conflicto con el estado actual del recurso."},
        413: {"title": "Carga Demasiado Grande", "message": "El archivo supera el tamaño máximo permitido."},
        422: {"title": "Entidad No Procesable", "message": "Los datos enviados no son válidos."},
        429: {"title": "Demasiadas Solicitudes", "message": "Has excedido el límite. Intenta de nuevo más tarde."},
        500: {"title": "Error Interno", "message": "Algo salió mal en nuestros servidores."},
    }

    _DASHBOARD_URL = "/itcj/dashboard"

    # Prefijo de ruta → app_key (orden no relevante: prefijos son únicos)
    _APP_BY_PREFIX = (
        ("/maint", "maint"),
        ("/help-desk", "helpdesk"),
        ("/agendatec", "agendatec"),
    )
    _APP_TEMPLATE = {
        "maint": "maint/errors/error.html",
        "helpdesk": "helpdesk/errors/error.html",
        "agendatec": "agendatec/errors/error.html",
        "core": "core/errors/core_error.html",
    }
    # Home de cada app (botón "Ir al inicio" en 404/500). core → dashboard hub.
    _APP_HOME = {
        "maint": "/maint",
        "helpdesk": "/help-desk/",
        "agendatec": "/agendatec/",
        "core": _DASHBOARD_URL,
    }

    def _is_page_request(request: Request) -> bool:
        """True si la petición es de una página (no de la API REST)."""
        return not request.url.path.startswith("/api/")

    def _app_for(path: str) -> str:
        """Determina la app por el prefijo de la ruta (core como fallback)."""
        for prefix, app_key in _APP_BY_PREFIX:
            if path.startswith(prefix):
                return app_key
        return "core"

    def _render_error_page(
        request: Request,
        status_code: int,
        *,
        forbidden: bool = False,
        has_app_access: bool = False,
    ):
        """Renderiza el template HTML de error de la app correspondiente.

        Destino del botón:

        - 403 SIN acceso a la app (``forbidden`` y no ``has_app_access``):
          "Ir al panel principal" → panel core. Dentro del iframe del
          dashboard cierra la ventana de la app (no hay inicio de la app).
        - 403 CON acceso a la app pero sin permiso de esta página
          (``forbidden`` y ``has_app_access``): "Ir al inicio" → inicio de
          la app, navegando dentro del iframe (sigue en la app).
        - resto (404/500/…): "Ir al inicio" → inicio de la app.

        Retorna ``None`` si el render falla (el handler cae a JSON).
        """
        try:
            info = ERROR_MESSAGES.get(
                status_code, {"title": "Error", "message": "Ocurrió un error inesperado."}
            )
            app_key = _app_for(request.url.path)
            template = _APP_TEMPLATE[app_key]

            # Solo SALE de la app cuando es 403 sin acceso a la app.
            exits_app = forbidden and not has_app_access

            if exits_app:
                button_url = _DASHBOARD_URL
                button_label = "Ir al panel principal"
            else:
                button_url = _APP_HOME[app_key]
                button_label = "Ir al inicio"

            ctx = {
                "error_code": status_code,
                "error_title": info["title"],
                "error_message": info["message"],
                "button_url": button_url,
                "button_label": button_label,
                # True → el botón SALE de la app. Dentro del iframe del
                # dashboard avisa al parent (postMessage CLOSE_APP) para
                # cerrar la ventana en vez de recargar todo. False →
                # navegación normal dentro del iframe (home de la app).
                "button_exits_app": exits_app,
            }

            if app_key == "maint":
                # maint usa su propia instancia de Jinja2 (no el loader global
                # de itcj2/templates.py). Import lazy: evita el circular en el
                # arranque y respeta el aislamiento de maint_templates.
                from itcj2.apps.maint.pages.nav import (
                    maint_templates,
                    sv as maint_sv,
                    sv_core as maint_sv_core,
                )

                ctx_maint = {
                    "request": request,
                    "current_user": getattr(request.state, "current_user", None),
                    "sv": maint_sv,
                    "sv_core": maint_sv_core,
                    **ctx,
                }
                return maint_templates.TemplateResponse(
                    request, template, ctx_maint, status_code=status_code
                )

            from itcj2.templates import render
            return render(request, template, ctx, status_code=status_code)
        except Exception as e:
            logger.exception("Error al renderizar página de error %d: %s", status_code, e)
            return None

    # ── Páginas: login redirige; forbidden ahora muestra página de error ─────
    @app.exception_handler(PageLoginRequired)
    async def page_login_required_handler(request: Request, exc: PageLoginRequired):
        """Redirige a login cuando una página requiere autenticación."""
        return RedirectResponse("/itcj/login", status_code=302)

    @app.exception_handler(PageForbidden)
    async def page_forbidden_handler(request: Request, exc: PageForbidden):
        """Muestra la página de error 403 de la app (antes redirigía al
        dashboard). El botón lleva al inicio de la app si el usuario tiene
        acceso a ella; si no tiene acceso, al panel core."""
        page = _render_error_page(
            request, 403,
            forbidden=True,
            has_app_access=getattr(exc, "has_app_access", False),
        )
        if page:
            return page
        # Fallback defensivo si el render falla.
        return RedirectResponse(_DASHBOARD_URL, status_code=302)

    from starlette.exceptions import HTTPException as StarletteHTTPException

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        if _is_page_request(request):
            page = _render_error_page(request, exc.status_code)
            if page:
                return page
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": exc.detail, "status": exc.status_code},
        )

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.exception("Unhandled exception: %s", exc)
        if _is_page_request(request):
            page = _render_error_page(request, 500)
            if page:
                return page
        return JSONResponse(
            status_code=500,
            content={"error": "internal_error", "status": 500},
        )

    from fastapi.exceptions import RequestValidationError

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError):
        if _is_page_request(request):
            page = _render_error_page(request, 422)
            if page:
                return page
        return JSONResponse(
            status_code=422,
            content={
                "error": "validation_error",
                "status": 422,
                "detail": exc.errors(),
            },
        )
