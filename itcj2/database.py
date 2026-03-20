from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from .config import get_settings

# Registra todos los modelos en el mapper de SQLAlchemy antes de la primera
# sesión para que las relaciones con referencias cruzadas (p. ej. User → Ticket)
# puedan resolverse correctamente.
import itcj2.models  # noqa: F401

engine = create_engine(
    get_settings().DATABASE_URL,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    """Dependency que provee una sesión de DB por request.

    Uso en FastAPI:
        @router.get("/")
        def endpoint(db: Session = Depends(get_db)):
            ...
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
