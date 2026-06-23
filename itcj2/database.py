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
# pgbouncer puede entregar. pool_size 20 + max_overflow 20 = 40 máx, <= los
# 50 backends reales de pgbouncer (default_pool_size 40 + reserve 10), todo
# por debajo de Postgres max_connections=100. Antes pedía hasta 80 y 55 se
# encolaban dentro de pgbouncer (falsa capacidad).
# NOTA: al ir a múltiples workers (2.1), dividir pool_size entre el nº de
# workers (p.ej. 4 workers → pool_size=10, max_overflow=0).
engine = create_engine(
    get_settings().DATABASE_URL,
    pool_pre_ping=True,
    pool_size=20,
    max_overflow=20,
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
