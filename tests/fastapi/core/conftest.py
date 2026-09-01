"""Fixtures locales de los tests de core."""
import pytest


@pytest.fixture()
def patched_session_local(db_session, monkeypatch):
    """Hace que el código que abre `SessionLocal()` use la sesión del test.

    `session_service` abre su propia sesión para leer/escribir `session_epoch`; sin
    esto vería la BD dev real en vez de las filas creadas dentro de la transacción
    del test. Mismo patrón que tests/fastapi/agendatec/conftest.py.

    El proxy deja pasar todo menos `close()` y `rollback()` — las dos operaciones
    de CICLO DE VIDA que el código ejecuta creyendo que la sesión es suya:

    - `close()`: cerrar la sesión del test rompería cualquier aserción posterior.
    - `rollback()`: `db_session` usa `join_transaction_mode="create_savepoint"`,
      así que un rollback vuelve al SAVEPOINT y BORRA las filas que creó la
      fixture (el usuario recién insertado). Lo llaman tanto
      `session_service._read_epoch_from_db` como el bloque de refresh de
      `middleware.py`, ambos con el patrón `rollback()` + `close()` sobre su
      propia sesión. Sin neutralizarlo, el `UPDATE ... WHERE id = :uid` posterior
      encuentra 0 filas y `bump_version` devuelve None.
    """
    class _NoClose:
        def __init__(self, inner):
            self._inner = inner

        def __getattr__(self, name):
            return getattr(self._inner, name)

        def close(self):
            pass

        def rollback(self):
            pass

    monkeypatch.setattr("itcj2.database.SessionLocal", lambda: _NoClose(db_session))
    return db_session
