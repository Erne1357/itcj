"""Bitácora de Cámaras: inmutable, sin FK (sobrevive al borrado de DVR y usuarios).

`detail` nunca lleva secretos. Trigger copiado de `titulatec_audit_log`: UPDATE
siempre falla; DELETE/TRUNCATE solo con `SET LOCAL cameras.audit_purge = 'on'`.
Se engancha a `after_create` para que la base del CI (`create_all`) lo tenga; la
migración `cam20261113a` lleva su propia copia literal.
"""
from sqlalchemy import BigInteger, Column, DDL, DateTime, Index, Integer, JSON, String, event
from sqlalchemy.sql import func

from itcj2.models.base import Base

IMMUTABILITY_SQL = """
CREATE OR REPLACE FUNCTION cameras_audit_log_guard() RETURNS trigger AS $fn$
BEGIN
    IF TG_OP = 'UPDATE' THEN
        RAISE EXCEPTION 'cameras_audit_log es inmutable: UPDATE no permitido';
    END IF;
    IF COALESCE(current_setting('cameras.audit_purge', true), '') = 'on' THEN
        IF TG_OP = 'DELETE' THEN
            RETURN OLD;
        END IF;
        RETURN NULL;
    END IF;
    RAISE EXCEPTION 'cameras_audit_log es inmutable: % no permitido', TG_OP;
END;
$fn$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_cameras_audit_log_no_update ON cameras_audit_log;
CREATE TRIGGER trg_cameras_audit_log_no_update
    BEFORE UPDATE ON cameras_audit_log
    FOR EACH ROW EXECUTE FUNCTION cameras_audit_log_guard();

DROP TRIGGER IF EXISTS trg_cameras_audit_log_no_delete ON cameras_audit_log;
CREATE TRIGGER trg_cameras_audit_log_no_delete
    BEFORE DELETE ON cameras_audit_log
    FOR EACH ROW EXECUTE FUNCTION cameras_audit_log_guard();

DROP TRIGGER IF EXISTS trg_cameras_audit_log_no_truncate ON cameras_audit_log;
CREATE TRIGGER trg_cameras_audit_log_no_truncate
    BEFORE TRUNCATE ON cameras_audit_log
    FOR EACH STATEMENT EXECUTE FUNCTION cameras_audit_log_guard();
"""

DROP_IMMUTABILITY_SQL = """
DROP TRIGGER IF EXISTS trg_cameras_audit_log_no_truncate ON cameras_audit_log;
DROP TRIGGER IF EXISTS trg_cameras_audit_log_no_delete ON cameras_audit_log;
DROP TRIGGER IF EXISTS trg_cameras_audit_log_no_update ON cameras_audit_log;
DROP FUNCTION IF EXISTS cameras_audit_log_guard();
"""


class CamerasAuditLog(Base):
    """action: reveal | create | update | password_update | pattern_update |
    deactivate | departments_update."""
    __tablename__ = "cameras_audit_log"

    id = Column(BigInteger, primary_key=True)
    dvr_id = Column(Integer)                       # sin FK
    dvr_name = Column(String(100))                 # snapshot
    actor_id = Column(BigInteger)                  # core_users.id, sin FK
    action = Column(String(30), nullable=False)
    detail = Column(JSON(none_as_null=True))
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_cameras_audit_log_dvr_id", "dvr_id"),
        Index("ix_cameras_audit_log_created_at", "created_at"),
    )


event.listen(CamerasAuditLog.__table__, "after_create", DDL(IMMUTABILITY_SQL.replace("%", "%%")))
