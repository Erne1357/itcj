from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from .config import get_settings

# Registra todos los modelos en el mapper de SQLAlchemy antes de la primera
# sesión para que las relaciones con referencias cruzadas (p. ej. User → Ticket)
# puedan resolverse correctamente.
import itcj2.models  # noqa: F401

# 2.2 Pool rebalanceado: la app NO debe demandar más conexiones de las que
# pgbouncer puede entregar. Antes pedía hasta 80 y 55 se encolaban dentro de
# pgbouncer (falsa capacidad).
# 2.1 El pool es POR PROCESO: con uvicorn --workers 4 el techo se multiplica
# por 4. Por eso el tamaño ya no está hardcodeado — cada servicio lo fija por
# env (DB_POOL_SIZE / DB_MAX_OVERFLOW en el compose):
#   backend HTTP (4 workers): 8+4  → 48 conexiones cliente
#   sockets (1 worker):       5+5  → 10
#   celery / CLI / dev:      20+20 → 40 (default, comportamiento previo)
# Todas son conexiones a pgbouncer (max_client_conn=500), que en transaction
# mode las multiplexa sobre 50 backends reales (default_pool_size 40 + 10 de
# reserva) < max_connections=100 de Postgres.
_settings = get_settings()

engine = create_engine(
    _settings.DATABASE_URL,
    pool_pre_ping=True,
    pool_size=_settings.DB_POOL_SIZE,
    max_overflow=_settings.DB_MAX_OVERFLOW,
    pool_timeout=10,
    pool_recycle=1800,
    pool_use_lifo=True,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    """Dependency que provee una sesión de DB por request.

    Uso en FastAPI:
        @router.get("/")
        def endpoint(db: Session = Depends(get_db)):
            ...

    Importante: hacemos rollback explícito antes de close() para garantizar
    que pgbouncer (transaction mode) libere la conexión del servidor. Sin
    esto, bajo cancelación de request (cliente desconecta, timeout, etc.)
    el reset_on_return del pool puede no ejecutarse y la conexión queda
    pinned "idle in transaction" hasta que postgres la mate. Si el endpoint
    ya hizo commit/rollback, este rollback final es no-op.
    """
    db = SessionLocal()
    try:
        yield db
        try:
            db.rollback()
        except Exception:
            pass
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        raise
    finally:
        try:
            db.close()
        except Exception:
            pass


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    """Context manager para usar fuera de dependencias FastAPI (CLI, middleware,
    handlers de pages que necesitan SessionLocal directo, tareas Celery, etc.).

    Mismas garantías que get_db(): rollback explícito antes de close() para
    liberar la conexión en pgbouncer transaction mode sin importar el camino
    de salida (success, exception, cancelación).

    Uso:
        from itcj2.database import session_scope
        with session_scope() as db:
            data = db.query(Model).all()
    """
    db = SessionLocal()
    try:
        yield db
        try:
            db.rollback()
        except Exception:
            pass
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        raise
    finally:
        try:
            db.close()
        except Exception:
            pass
