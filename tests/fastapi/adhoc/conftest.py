"""Conftest de tests de la app adhoc: resuelve mappers de SQLAlchemy."""
import itcj2.models  # noqa: F401

import pytest


@pytest.fixture()
def usuarios_de_los_jwt(db_session):
    """Garantiza en ``core_users`` los ids que firman los JWT de esta suite.

    Los endpoints que guardan autoría (``uploaded_by_id`` de los adjuntos de
    incidencia, FK a ``core_users``) rompen por llave ajena si la fila no existe.
    En la BD de desarrollo los ids 200/201 existen por herencia histórica, así
    que el fallo no se ve en local: solo en una BD construida con ``create_all``,
    que es exactamente como la levanta CI (ver `.github/workflows/deploy.yml`).

    Las filas se insertan en la transacción del test, así que el rollback de
    ``db_session`` las borra y no tocan la base de nadie.
    """
    from sqlalchemy import text

    for uid in (200, 201):
        db_session.execute(
            text("""
                INSERT INTO core_users (id, first_name, last_name, username, is_active)
                SELECT :id, 'Test', 'Adhoc', :username, true
                WHERE NOT EXISTS (SELECT 1 FROM core_users WHERE id = :id)
            """),
            {"id": uid, "username": f"test_adhoc_{uid}"},
        )
    db_session.flush()
    return (200, 201)
