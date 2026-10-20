"""Modelo `AuditLog` y su trigger de inmutabilidad (spec bitácora §3).

Cada sentencia que DEBE fallar va dentro de `begin_nested()`: la excepción de
PostgreSQL aborta la transacción y, sin SAVEPOINT, tumbaría la del arnés.
"""
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from itcj2.apps.titulatec.models import TitulatecAuditLog as AuditLog
from itcj2.apps.titulatec.models.audit_log import IMMUTABILITY_SQL


def _fila(db):
    row = AuditLog(source="action", action="cohort.window_changed",
                   module="cohorts", actor_kind="system")
    db.add(row)
    db.flush()
    return row


def _debe_fallar(db, sql, params=None):
    with pytest.raises(DBAPIError) as exc:
        with db.begin_nested():
            db.execute(text(sql), params or {})
    assert "inmutable" in str(exc.value)


def test_insert_minimo_puebla_occurred_at(db_session):
    row = _fila(db_session)
    db_session.refresh(row)
    assert row.id is not None
    assert row.occurred_at is not None


def test_update_siempre_falla(db_session):
    row = _fila(db_session)
    _debe_fallar(db_session, "UPDATE titulatec_audit_log SET reason='x' WHERE id=:i",
                 {"i": row.id})


def test_update_falla_incluso_con_purge_on(db_session):
    row = _fila(db_session)
    db_session.execute(text("SET LOCAL titulatec.audit_purge = 'on'"))
    _debe_fallar(db_session, "UPDATE titulatec_audit_log SET reason='x' WHERE id=:i",
                 {"i": row.id})


def test_delete_falla(db_session):
    row = _fila(db_session)
    _debe_fallar(db_session, "DELETE FROM titulatec_audit_log WHERE id=:i", {"i": row.id})


def test_truncate_falla(db_session):
    _fila(db_session)
    _debe_fallar(db_session, "TRUNCATE titulatec_audit_log")


def test_delete_con_purge_on_pasa(db_session):
    row = _fila(db_session)
    db_session.execute(text("SET LOCAL titulatec.audit_purge = 'on'"))
    res = db_session.execute(text("DELETE FROM titulatec_audit_log WHERE id=:i"),
                             {"i": row.id})
    assert res.rowcount == 1


def test_after_create_lleva_el_trigger_al_create_all(db_session):
    """La base del CI sale de `create_all`, no de Alembic: el listener
    `after_create` debe instalar función y triggers. Se crea la tabla en un
    esquema desechable (dentro de la transacción del arnés, que se revierte) y
    se leen los triggers del catálogo."""
    conn = db_session.connection()
    conn.execute(text("CREATE SCHEMA tt_audit_probe"))
    conn.execute(text("SET LOCAL search_path TO tt_audit_probe"))
    AuditLog.__table__.create(bind=conn)
    nombres = {r[0] for r in conn.execute(text(
        "SELECT t.tgname FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = 'tt_audit_probe' AND NOT t.tgisinternal"))}
    assert nombres == {"trg_titulatec_audit_log_no_update",
                       "trg_titulatec_audit_log_no_delete",
                       "trg_titulatec_audit_log_no_truncate"}


def test_la_constante_nombra_los_objetos_del_contrato():
    for nombre in ("titulatec_audit_log_guard", "trg_titulatec_audit_log_no_update",
                   "trg_titulatec_audit_log_no_delete", "trg_titulatec_audit_log_no_truncate",
                   "titulatec.audit_purge"):
        assert nombre in IMMUTABILITY_SQL


def test_alias_audit_log_y_sin_choque_con_agendatec():
    """`User.relationship("AuditLog")` (agendatec) exige UN solo nombre en el
    registro declarativo; el alias del paquete apunta a la clase de titulatec."""
    from itcj2.apps.titulatec import models as tt
    from itcj2.apps.agendatec.models import AuditLog as AgendaAuditLog
    from sqlalchemy.orm import configure_mappers
    assert tt.AuditLog is tt.TitulatecAuditLog is AuditLog
    assert AgendaAuditLog is not AuditLog
    configure_mappers()
