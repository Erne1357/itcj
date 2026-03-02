import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger("itcj2")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup y shutdown de la aplicación."""
    logger.info("FastAPI ITCJ v2 iniciando...")

    yield

    # Shutdown: cerrar pool de conexiones
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

    # Health check
    @app.get("/health", tags=["system"])
    async def health():
        return {"ok": True, "server": "fastapi", "version": "2.0.0"}

    # Error handlers
    _register_error_handlers(app)

    return app


def _register_error_handlers(app: FastAPI):
    """Manejo centralizado de errores (equivalente a register_error_handlers de Flask)."""

    # ── Páginas: redirecciones en lugar de JSON ──────────────────────────────
    from fastapi.responses import RedirectResponse
    from .exceptions import PageForbidden, PageLoginRequired

    @app.exception_handler(PageLoginRequired)
    async def page_login_required_handler(request: Request, exc: PageLoginRequired):
        """Redirige a login cuando una página requiere autenticación."""
        return RedirectResponse("/itcj/auth/login", status_code=302)

    @app.exception_handler(PageForbidden)
    async def page_forbidden_handler(request: Request, exc: PageForbidden):
        """Redirige al dashboard cuando el usuario no tiene permisos de página."""
        return RedirectResponse("/itcj/dashboard", status_code=302)

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

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.exception("Unhandled exception: %s", exc)
        return JSONResponse(
            status_code=500,
            content={"error": "internal_error", "status": 500},
        )

    from fastapi.exceptions import RequestValidationError

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=422,
            content={
                "error": "validation_error",
                "status": 422,
                "detail": exc.errors(),
            },
        )
