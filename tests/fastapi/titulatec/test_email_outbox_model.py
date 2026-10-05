"""Contrato de `EmailOutbox` (Tarea 3 del plan
`2026-09-28-titulatec-correos-notificaciones`): SOLO tabla, modelo y
settings -- el servicio de encolado, el despachador y los recordatorios
son tareas aparte. El catálogo de `kind` creció de 11 a 15 con el no adeudo
de biblioteca (Tarea 10 del plan `2026-10-01-titulatec-biblioteca-caja`).

Patrón de `IntegrityError` bajo `begin_nested()` como en
`test_eligibility_check_model.py` / `test_review_window_model.py`.
"""
import pytest
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from itcj2.apps.titulatec.models import EmailOutbox
from itcj2.apps.titulatec.models.email_outbox import OUTBOX_KINDS, OUTBOX_STATUSES
from itcj2.models.base import Base


class TestTablaYDominios:
    def test_la_tabla_esta_en_base_metadata(self):
        assert "titulatec_email_outbox" in Base.metadata.tables

    def test_dominio_de_status_es_el_del_spec(self):
        assert OUTBOX_STATUSES == ("pending", "sent", "failed", "no_recipient", "obsolete")

    def test_dominio_de_kind_tiene_los_15_del_catalogo(self):
        """Los 11 del catálogo de 2026-09-28 y, al final y en este orden, los 4
        del no adeudo de biblioteca (spec 2026-10-01-titulatec-biblioteca-caja-
        design.md §4.11)."""
        assert OUTBOX_KINDS == (
            "docs_review",
            "phase_approved",
            "phase_rejected",
            "survey_approved",
            "survey_rejected",
            "survey_revoked",
            "appt_changed",
            "appt_reminder",
            "appt_no_show",
            "docs_reminder",
            "survey_reminder",
            "library_ready",
            "library_cleared",
            "library_reverted",
            "library_reminder",
            "library_observed",
            "library_reenabled",
        )

    def test_cada_kind_cabe_en_su_columna(self):
        assert all(len(k) <= EmailOutbox.__table__.c.kind.type.length for k in OUTBOX_KINDS)


@pytest.fixture()
def egresado(make_student, make_process):
    """Un egresado con proceso, para colgarle filas de la bandeja."""
    student = make_student()
    process = make_process(student)
    return {"student": student, "process": process}


class TestDefaults:
    def test_nace_pending_con_0_intentos_y_not_before_no_nulo_tras_flush(
        self, db_session, egresado,
    ):
        row = EmailOutbox(
            kind="docs_review",
            user_id=egresado["student"].id,
            process_id=egresado["process"].id,
            payload={"documentos": ["curp"]},
        )
        db_session.add(row)
        db_session.flush()

        assert row.id is not None
        assert row.status == "pending"
        assert row.attempts == 0
        assert row.not_before is not None
        assert row.created_at is not None
        assert row.sent_at is None

    def test_process_id_es_opcional(self, db_session, egresado):
        """`process_id` es NULL-able (spec §6 C1): no todo correo cuelga de
        un proceso (p. ej. futuros avisos sin proceso asociado)."""
        row = EmailOutbox(
            kind="docs_review",
            user_id=egresado["student"].id,
            payload={},
        )
        db_session.add(row)
        db_session.flush()

        assert row.process_id is None


class TestUserIdEsObligatorio:
    def test_sin_user_id_truena(self, db_session, egresado):
        with pytest.raises(IntegrityError):
            with db_session.begin_nested():
                db_session.add(EmailOutbox(
                    kind="docs_review",
                    process_id=egresado["process"].id,
                    payload={},
                ))
                db_session.flush()


class TestDedupeKeyUnico:
    """`dedupe_key` (nullable, UNIQUE): solo los recordatorios la usan."""

    def test_dos_filas_con_el_mismo_dedupe_key_no_nulo_truenan(self, db_session, egresado):
        db_session.add(EmailOutbox(
            kind="appt_reminder",
            user_id=egresado["student"].id,
            process_id=egresado["process"].id,
            payload={},
            dedupe_key=f"appt_reminder:{egresado['process'].id}",
        ))
        db_session.flush()

        with pytest.raises(IntegrityError):
            with db_session.begin_nested():
                db_session.add(EmailOutbox(
                    kind="appt_reminder",
                    user_id=egresado["student"].id,
                    process_id=egresado["process"].id,
                    payload={},
                    dedupe_key=f"appt_reminder:{egresado['process'].id}",
                ))
                db_session.flush()

    def test_varias_filas_con_dedupe_key_nulo_conviven(self, db_session, egresado):
        """Postgres permite múltiples NULL bajo un UNIQUE normal: el resto
        de los `kind` (que no reintentan) dejan `dedupe_key` en NULL."""
        for _ in range(3):
            db_session.add(EmailOutbox(
                kind="docs_review",
                user_id=egresado["student"].id,
                process_id=egresado["process"].id,
                payload={},
            ))
        db_session.flush()  # no debe tronar

        filas = (db_session.query(EmailOutbox)
                 .filter_by(process_id=egresado["process"].id, dedupe_key=None)
                 .count())
        assert filas == 3


class TestSettingsDeCorreo:
    """Spec §6 C6: `TITULATEC_EMAIL_*` / `TITULATEC_REMINDER_*` /
    `TITULATEC_APPT_REMINDER_DAYS_BEFORE`. Mismo patrón que
    `test_sii_config.py`: instanciar `Settings(...)` directo."""

    def test_los_defaults_son_los_del_spec(self, monkeypatch):
        from itcj2.config import Settings

        for var in (
            "TITULATEC_EMAIL_ENABLED",
            "TITULATEC_EMAIL_DIGEST_MINUTES",
            "TITULATEC_EMAIL_MAX_ATTEMPTS",
            "TITULATEC_REMINDER_FIRST_DAYS",
            "TITULATEC_REMINDER_EVERY_DAYS",
            "TITULATEC_REMINDER_MAX",
            "TITULATEC_APPT_REMINDER_DAYS_BEFORE",
        ):
            monkeypatch.delenv(var, raising=False)

        s = Settings(_env_file=None)
        assert s.TITULATEC_EMAIL_ENABLED is True
        assert s.TITULATEC_EMAIL_DIGEST_MINUTES == 10
        # Ruling 20: con 7, las 6 esperas (1+2+4+8+16+32 min) suman ~1 h de
        # reintentos; con 6 se daba por fallido a los ~31 min.
        assert s.TITULATEC_EMAIL_MAX_ATTEMPTS == 7
        assert s.TITULATEC_REMINDER_FIRST_DAYS == 3
        assert s.TITULATEC_REMINDER_EVERY_DAYS == 7
        assert s.TITULATEC_REMINDER_MAX == 3
        assert s.TITULATEC_APPT_REMINDER_DAYS_BEFORE == 1

    def test_digest_minutes_va_de_1_a_120(self):
        from itcj2.config import Settings

        with pytest.raises(ValidationError):
            Settings(TITULATEC_EMAIL_DIGEST_MINUTES=0)
        with pytest.raises(ValidationError):
            Settings(TITULATEC_EMAIL_DIGEST_MINUTES=121)
        for valido in (1, 10, 120):
            assert (Settings(TITULATEC_EMAIL_DIGEST_MINUTES=valido)
                    .TITULATEC_EMAIL_DIGEST_MINUTES == valido)

    def test_max_attempts_va_de_1_a_20(self):
        from itcj2.config import Settings

        with pytest.raises(ValidationError):
            Settings(TITULATEC_EMAIL_MAX_ATTEMPTS=0)
        with pytest.raises(ValidationError):
            Settings(TITULATEC_EMAIL_MAX_ATTEMPTS=21)
        for valido in (1, 6, 20):
            assert (Settings(TITULATEC_EMAIL_MAX_ATTEMPTS=valido)
                    .TITULATEC_EMAIL_MAX_ATTEMPTS == valido)

    def test_reminder_first_days_va_de_1_a_60(self):
        from itcj2.config import Settings

        with pytest.raises(ValidationError):
            Settings(TITULATEC_REMINDER_FIRST_DAYS=0)
        with pytest.raises(ValidationError):
            Settings(TITULATEC_REMINDER_FIRST_DAYS=61)
        for valido in (1, 3, 60):
            assert (Settings(TITULATEC_REMINDER_FIRST_DAYS=valido)
                    .TITULATEC_REMINDER_FIRST_DAYS == valido)

    def test_reminder_every_days_va_de_1_a_60(self):
        from itcj2.config import Settings

        with pytest.raises(ValidationError):
            Settings(TITULATEC_REMINDER_EVERY_DAYS=0)
        with pytest.raises(ValidationError):
            Settings(TITULATEC_REMINDER_EVERY_DAYS=61)
        for valido in (1, 7, 60):
            assert (Settings(TITULATEC_REMINDER_EVERY_DAYS=valido)
                    .TITULATEC_REMINDER_EVERY_DAYS == valido)

    def test_reminder_max_va_de_0_a_10(self):
        """0 = sin recordatorios de encuesta/documentos (spec)."""
        from itcj2.config import Settings

        assert Settings(TITULATEC_REMINDER_MAX=0).TITULATEC_REMINDER_MAX == 0
        with pytest.raises(ValidationError):
            Settings(TITULATEC_REMINDER_MAX=-1)
        with pytest.raises(ValidationError):
            Settings(TITULATEC_REMINDER_MAX=11)
        assert Settings(TITULATEC_REMINDER_MAX=10).TITULATEC_REMINDER_MAX == 10

    def test_appt_reminder_days_before_va_de_0_a_7(self):
        """0 = sin recordatorio de cita (spec)."""
        from itcj2.config import Settings

        assert (Settings(TITULATEC_APPT_REMINDER_DAYS_BEFORE=0)
                .TITULATEC_APPT_REMINDER_DAYS_BEFORE == 0)
        with pytest.raises(ValidationError):
            Settings(TITULATEC_APPT_REMINDER_DAYS_BEFORE=-1)
        with pytest.raises(ValidationError):
            Settings(TITULATEC_APPT_REMINDER_DAYS_BEFORE=8)
        assert (Settings(TITULATEC_APPT_REMINDER_DAYS_BEFORE=7)
                .TITULATEC_APPT_REMINDER_DAYS_BEFORE == 7)

    def test_email_enabled_es_booleano(self):
        from itcj2.config import Settings

        assert Settings(TITULATEC_EMAIL_ENABLED=False).TITULATEC_EMAIL_ENABLED is False
        assert Settings(TITULATEC_EMAIL_ENABLED=True).TITULATEC_EMAIL_ENABLED is True
