"""Fixtures compartidos para tests de FastAPI que necesitan BD Postgres real.

La mayoría del harness es mock-based (ver tests/conftest.py). Pero la lógica de
jerarquía de departamentos y resolución de scope depende de SQL específico de
Postgres (CTEs recursivos, joins de procedencia) que NO se puede testear con
mocks. Este `db_session` abre una conexión directa a Postgres (sin pgBouncer),
envuelve cada test en una transacción con SAVEPOINTs y hace rollback al final,
de modo que los `db.commit()` internos de los services no persisten nada.
"""
import os

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Eager import: resuelve todos los mappers de SQLAlchemy antes de instanciar modelos.
import itcj2.models  # noqa: F401


_DIRECT_PG_URL = "postgresql+psycopg2://postgres:password@postgres:5432/itcj"


@pytest.fixture(scope="session")
def _pg_engine():
    """Engine de sesión contra Postgres DIRECTO (no pgBouncer) para poder usar
    SAVEPOINTs en el patrón de rollback por test."""
    url = os.getenv("MIGRATE_DATABASE_URL") or _DIRECT_PG_URL
    engine = create_engine(url, future=True)
    yield engine
    engine.dispose()


@pytest.fixture()
def db_session(_pg_engine):
    """Session transaccional que hace rollback al terminar el test.

    `join_transaction_mode="create_savepoint"` hace que cada `session.commit()`
    (los services commitean internamente) libere un SAVEPOINT en vez de commitear
    la transacción externa; el `trans.rollback()` final limpia TODO. Nada se
    persiste en la BD dev.
    """
    connection = _pg_engine.connect()
    trans = connection.begin()
    SessionTest = sessionmaker(
        bind=connection,
        join_transaction_mode="create_savepoint",
        expire_on_commit=False,
        future=True,
    )
    session = SessionTest()
    try:
        yield session
    finally:
        session.close()
        trans.rollback()
        connection.close()
