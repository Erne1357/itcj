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


@pytest.fixture(autouse=True)
def _clear_authz_cache():
    """Limpia el caché de authz en Redis ANTES de cada test.

    Muchos tests parchean get_user_permissions_for_app / user_roles_in_app /
    has_any_assignment esperando que se llamen. Pero cached_* leen Redis primero;
    si un test previo dejó una entrada (kind, app, user), el patch se saltea por un
    HIT stale y el test falla de forma no-determinista. Vaciar authz:v1:* antes de
    cada test hace que cada uno vea un MISS y ejecute la función parcheada.

    Best-effort: si Redis no está disponible, no rompe el test (fail-open).
    """
    try:
        from itcj2.core.utils.redis_conn import get_redis
        r = get_redis()
        if r is not None:
            keys = list(r.scan_iter(match="authz:v1:*", count=1000))
            keys += list(r.scan_iter(match="rl:*", count=1000))
            keys += list(r.scan_iter(match="appstyle:*", count=100))
            if keys:
                r.delete(*keys)
    except Exception:
        pass
    yield


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
