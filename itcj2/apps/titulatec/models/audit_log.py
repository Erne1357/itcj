"""Bitácora de TitulaTec: una fila por cosa que pasó, inmutable.

Spec `2026-10-07-titulatec-bitacora-design.md` §3. Sin `ForeignKey` a propósito
(D7): la bitácora sobrevive al borrado de usuarios/procesos y nunca bloquea un
`DELETE` de negocio. Por eso `actor_id`/`entity_id` son números sueltos.

Inmutabilidad: la protege un trigger de PostgreSQL (UPDATE siempre falla;
DELETE y TRUNCATE solo con `SET LOCAL titulatec.audit_purge = 'on'`). El SQL vive
en `IMMUTABILITY_SQL` y se engancha a `after_create` de la tabla para que la
base del CI (`create_all`, sin Alembic) también lo tenga. La migración
`tt20261007b` lleva su propia copia literal.
"""
from sqlalchemy import (
    BigInteger, Column, DDL, DateTime, Index, Integer, JSON, String, Text, event,
)
from sqlalchemy.sql import text

from itcj2.models.base import Base

# Función + 3 triggers. `CREATE OR REPLACE` y `DROP TRIGGER IF EXISTS` para que
# re-ejecutarlo sea inocuo.
IMMUTABILITY_SQL = """
CREATE OR REPLACE FUNCTION titulatec_audit_log_guard() RETURNS trigger AS $fn$
BEGIN
    IF TG_OP = 'UPDATE' THEN
        RAISE EXCEPTION 'titulatec_audit_log es inmutable: UPDATE no permitido';
    END IF;
    IF COALESCE(current_setting('titulatec.audit_purge', true), '') = 'on' THEN
        IF TG_OP = 'DELETE' THEN
            RETURN OLD;
        END IF;
        RETURN NULL;
    END IF;
    RAISE EXCEPTION 'titulatec_audit_log es inmutable: % no permitido', TG_OP;
END;
$fn$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_titulatec_audit_log_no_update ON titulatec_audit_log;
CREATE TRIGGER trg_titulatec_audit_log_no_update
    BEFORE UPDATE ON titulatec_audit_log
    FOR EACH ROW EXECUTE FUNCTION titulatec_audit_log_guard();

DROP TRIGGER IF EXISTS trg_titulatec_audit_log_no_delete ON titulatec_audit_log;
CREATE TRIGGER trg_titulatec_audit_log_no_delete
    BEFORE DELETE ON titulatec_audit_log
    FOR EACH ROW EXECUTE FUNCTION titulatec_audit_log_guard();

DROP TRIGGER IF EXISTS trg_titulatec_audit_log_no_truncate ON titulatec_audit_log;
CREATE TRIGGER trg_titulatec_audit_log_no_truncate
    BEFORE TRUNCATE ON titulatec_audit_log
    FOR EACH STATEMENT EXECUTE FUNCTION titulatec_audit_log_guard();
"""

DROP_IMMUTABILITY_SQL = """
DROP TRIGGER IF EXISTS trg_titulatec_audit_log_no_truncate ON titulatec_audit_log;
DROP TRIGGER IF EXISTS trg_titulatec_audit_log_no_delete ON titulatec_audit_log;
DROP TRIGGER IF EXISTS trg_titulatec_audit_log_no_update ON titulatec_audit_log;
DROP FUNCTION IF EXISTS titulatec_audit_log_guard();
"""


class TitulatecAuditLog(Base):
    """Una fila de la bitácora.

    OJO con el nombre: `agendatec` ya declara una clase `AuditLog` y el registro
    declarativo de SQLAlchemy es global por nombre (`User.relationship("AuditLog")`
    se rompería con dos). Por eso la clase se llama `TitulatecAuditLog`; el paquete
    `titulatec.models` la expone además como `AuditLog` (alias, fuera de `__all__`).

    `source`: action (llamada explícita) | process_event (espejo de
    `ProcessEvent`) | data (red ORM). `actor_kind`: user | public | system |
    cli | celery.
    """
    __tablename__ = "titulatec_audit_log"

    id = Column(BigInteger, primary_key=True)
    occurred_at = Column(DateTime, nullable=False, server_default=text("NOW()"))
    source = Column(String(16), nullable=False)
    action = Column(String(64), nullable=False)
    module = Column(String(24), nullable=False)

    actor_id = Column(BigInteger, nullable=True)       # core_users.id, sin FK (D7)
    actor_kind = Column(String(12), nullable=False)
    actor_label = Column(String(120), nullable=True)

    entity_type = Column(String(48), nullable=True)
    entity_id = Column(BigInteger, nullable=True)
    process_id = Column(Integer, nullable=True)        # sin FK (D7)
    subject_label = Column(String(160), nullable=True)

    reason = Column(Text, nullable=True)
    # `none_as_null=True`: `None` es el NULL de SQL, no el JSON `null` (con el
    # `JSON` a secas, `TitulatecAuditLog(before=None)` guardaba `'null'::json` y
    # `before IS NULL` dejaba de servir). Solo cambia el lado Python: el DDL es el
    # mismo, sin migración.
    before = Column(JSON(none_as_null=True), nullable=True)
    after = Column(JSON(none_as_null=True), nullable=True)
    payload = Column(JSON(none_as_null=True), nullable=True)

    request_id = Column(String(64), nullable=True)
    ip = Column(String(45), nullable=True)
    user_agent = Column(String(200), nullable=True)
    route = Column(String(160), nullable=True)

    __table_args__ = (
        Index("ix_titulatec_audit_log_occurred_at", "occurred_at"),
        Index("ix_titulatec_audit_log_module_occurred_at", "module", "occurred_at"),
        Index("ix_titulatec_audit_log_actor_id_occurred_at", "actor_id", "occurred_at"),
        Index("ix_titulatec_audit_log_process_id_occurred_at", "process_id", "occurred_at"),
        Index("ix_titulatec_audit_log_entity_type_entity_id", "entity_type", "entity_id"),
        Index("ix_titulatec_audit_log_request_id", "request_id"),
        Index("ix_titulatec_audit_log_action", "action"),
        # Filas SIN proceso (solicitud de inscripción previa a la cuenta): el filtro
        # «Alumno» y el expediente las buscan por prefijo del nº de control en
        # `subject_label`. Migración `tt20261007c`.
        Index("ix_titulatec_audit_log_subject_label_prefix", "subject_label",
              postgresql_ops={"subject_label": "text_pattern_ops"},
              postgresql_where=text("process_id IS NULL")),
    )

    def __repr__(self) -> str:
        return f"<TitulatecAuditLog {self.id} {self.action}>"


# `create_all` (CI) no corre migraciones: el trigger llega por aquí. DDL() interpola
# con `%`, así que el `%` literal del RAISE se duplica.
event.listen(TitulatecAuditLog.__table__, "after_create", DDL(IMMUTABILITY_SQL.replace("%", "%%")))
