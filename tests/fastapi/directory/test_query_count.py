"""Hace falsable el presupuesto de queries: antes eran 103 por render.

Se instrumenta el engine real; con MagicMock no hay nada que contar.
"""
from sqlalchemy import event

from itcj2.apps.directory.services import directory_service as svc

MAX_QUERIES = 10


def test_list_directory_query_budget(db_session):
    counter = {"n": 0}
    engine = db_session.get_bind()

    def _count(conn, cursor, statement, params, context, executemany):
        counter["n"] += 1

    event.listen(engine, "before_cursor_execute", _count)
    try:
        svc.list_directory(db_session, include_unofficial=False)
    finally:
        event.remove(engine, "before_cursor_execute", _count)

    assert counter["n"] <= MAX_QUERIES, f"{counter['n']} queries (presupuesto {MAX_QUERIES})"
