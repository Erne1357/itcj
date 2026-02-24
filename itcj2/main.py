import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger("itcj2")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup y shutdown de la aplicación."""
    logger.info("FastAPI ITCJ v2 iniciando...")

    # Inicializar Flask-SQLAlchemy para que los servicios compartidos
    # de itcj/ (auth_service, notification_service, etc.) funcionen.
    # Ellos usan db.session de Flask-SQLAlchemy internamente.
    _init_flask_db()

    yield

    # Shutdown: cerrar pool de conexiones de FastAPI
    from itcj2.database import engine
    engine.dispose()
    logger.info("FastAPI ITCJ v2 detenido.")


def _init_flask_db():
    """Crea una mini-app Flask headless para que db.session funcione.

    Los servicios en itcj/core/services/ usan ``db.session`` de
    Flask-SQLAlchemy. Para que funcionen sin levantar Flask completo
    creamos una app mínima que solo inicializa la extensión de DB.
    """
    from flask import Flask
    from itcj.core.extensions import db, migrate
    from itcj2.config import get_settings

    settings = get_settings()

    flask_app = Flask(__name__)
    flask_app.config["SQLALCHEMY_DATABASE_URI"] = settings.DATABASE_URL
    flask_app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    flask_app.config["SECRET_KEY"] = settings.SECRET_KEY
    flask_app.config["JWT_EXPIRES_HOURS"] = settings.JWT_EXPIRES_HOURS
    flask_app.config["COOKIE_SAMESITE"] = settings.COOKIE_SAMESITE
    flask_app.config["COOKIE_SECURE"] = settings.COOKIE_SECURE

    db.init_app(flask_app)

    # Pushear el contexto para que db.session esté disponible globalmente
    ctx = flask_app.app_context()
    ctx.push()

    logger.info("Flask-SQLAlchemy inicializado para servicios compartidos.")


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
