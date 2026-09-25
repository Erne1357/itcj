"""Revocar una inscripción aprobada (spec 2026-09-25-titulatec-elegibilidad-sii §3.6).

`ProcessService.cancel` es la primera escritura de `TitulationProcess.status =
'cancelled'` en toda la app: hasta hoy ese valor solo existía en el comentario
del modelo. Por eso además del servicio se prueba el barrido de sus lectores:
qué listas lo excluyen, qué guardas lo bloquean y dónde se etiqueta.

Permiso: `titulatec.process.api.cancel` (ya declarado en el 02). Las fábricas
del harness crean la fila de `core_permissions` dentro de la transacción del
test, así que no se depende del DML (gitignored, no llega a CI).
"""
from __future__ import annotations

from urllib.parse import unquote

import pytest

import itcj2.models  # noqa: F401

CANCEL = "titulatec.process.api.cancel"
READ_ALL = "titulatec.process.api.read.all"
DETAIL = "titulatec.process.page.detail"
REVOCA_PERMS = (READ_ALL, DETAIL, CANCEL)


def _svc():
    from itcj2.apps.titulatec.services.process_service import ProcessService
    return ProcessService


def _events(db, process_id, tipo):
    from itcj2.apps.titulatec.models import ProcessEvent
    return (db.query(ProcessEvent)
            .filter_by(process_id=process_id, event_type=tipo).all())


def _msg(resp) -> str:
    return unquote(resp.headers.get("X-Tt-Error", ""))


@pytest.fixture()
def correos(monkeypatch):
    """Captura los avisos de revocación sin tocar Graph."""
    enviados = []

    def _fake(db, process):
        enviados.append(process.id)
        return True

    monkeypatch.setattr(
        "itcj2.apps.titulatec.services.email_helper.TitulaTecEmailHelper.send_process_cancelled",
        staticmethod(_fake))
    return enviados


@pytest.fixture()
def esc(seed_phase_defs, seed_document_types, make_program, make_cohort,
        make_student, make_process, make_head, make_user):
    seed_phase_defs()
    seed_document_types()
    prog = make_program("Ingenieria Ficticia Revocable")
    cohort = make_cohort()
    student = make_student()

    def _proc(status="active", current_phase=1, program=prog, cohort_=cohort, alumno=None):
        return make_process(alumno or student, cohort=cohort_, program=program,
                            current_phase=current_phase, status=status)

    return {"prog": prog, "cohort": cohort, "student": student, "proc": _proc,
            "actor": make_user(first_name="ESCOLARES", last_name="FICTICIA")}


# ===========================================================================
# 1. El servicio
# ===========================================================================
class TestCancelar:
    @pytest.mark.parametrize("status", ["active", "on_hold"])
    def test_revoca_un_proceso_vivo(self, status, db_session, esc, correos):
        proc = esc["proc"](status=status)

        ok, msg = _svc().cancel(db_session, proc.id, reason="Documentación falsa",
                                actor_id=esc["actor"].id)

        assert ok, msg
        db_session.refresh(proc)
        assert proc.status == "cancelled"
        evs = _events(db_session, proc.id, "process_cancelled")
        assert len(evs) == 1
        assert evs[0].actor_id == esc["actor"].id
        assert evs[0].payload["reason"] == "Documentación falsa"
        assert evs[0].payload["previous_status"] == status
        assert correos == [proc.id]

    def test_es_idempotente(self, db_session, esc, correos):
        proc = esc["proc"]()
        _svc().cancel(db_session, proc.id, reason="Motivo uno", actor_id=esc["actor"].id)

        ok, msg = _svc().cancel(db_session, proc.id, reason="Motivo dos",
                                actor_id=esc["actor"].id)

        assert not ok
        assert "revocada" in msg
        assert len(_events(db_session, proc.id, "process_cancelled")) == 1
        assert len(correos) == 1, "el segundo intento no puede volver a avisar"

    def test_un_proceso_completado_no_se_revoca(self, db_session, esc, correos):
        proc = esc["proc"](status="completed", current_phase=8)

        ok, msg = _svc().cancel(db_session, proc.id, reason="x", actor_id=esc["actor"].id)

        assert not ok and msg
        db_session.refresh(proc)
        assert proc.status == "completed"
        assert correos == []

    @pytest.mark.parametrize("motivo", ["", "   ", None])
    def test_el_motivo_es_obligatorio(self, motivo, db_session, esc, correos):
        proc = esc["proc"]()

        ok, msg = _svc().cancel(db_session, proc.id, reason=motivo, actor_id=esc["actor"].id)

        assert not ok and "motivo" in msg.lower()
        db_session.refresh(proc)
        assert proc.status == "active"

    def test_motivo_demasiado_largo(self, db_session, esc, correos):
        proc = esc["proc"]()

        ok, msg = _svc().cancel(db_session, proc.id, reason="x" * 2001,
                                actor_id=esc["actor"].id)

        assert not ok and "2000" in msg

    def test_proceso_inexistente(self, db_session, esc, correos):
        ok, msg = _svc().cancel(db_session, 987654321, reason="x", actor_id=esc["actor"].id)
        assert not ok and msg

    def test_el_correo_sale_despues_del_commit(self, db_session, esc, monkeypatch):
        proc = esc["proc"]()
        pasos = []
        commit_real = db_session.commit
        monkeypatch.setattr(db_session, "commit",
                            lambda: pasos.append("commit") or commit_real())
        monkeypatch.setattr(
            "itcj2.apps.titulatec.services.email_helper.TitulaTecEmailHelper.send_process_cancelled",
            staticmethod(lambda db, p: pasos.append("correo") or True))

        ok, _ = _svc().cancel(db_session, proc.id, reason="Motivo", actor_id=esc["actor"].id)

        assert ok
        assert pasos == ["commit", "correo"]

    def test_un_correo_caido_no_revierte_la_revocacion(self, db_session, esc, monkeypatch):
        proc = esc["proc"]()

        def _explota(db, p):
            raise RuntimeError("Graph caido")

        monkeypatch.setattr(
            "itcj2.apps.titulatec.services.email_helper.TitulaTecEmailHelper.send_process_cancelled",
            staticmethod(_explota))

        ok, _ = _svc().cancel(db_session, proc.id, reason="Motivo", actor_id=esc["actor"].id)

        assert ok
        db_session.refresh(proc)
        assert proc.status == "cancelled"

    def test_avisa_al_alumno_en_la_app(self, db_session, esc, correos):
        from itcj2.core.models.notification import Notification
        proc = esc["proc"]()

        _svc().cancel(db_session, proc.id, reason="Motivo", actor_id=esc["actor"].id)

        avisos = (db_session.query(Notification)
                  .filter_by(user_id=esc["student"].id, type="PROCESS_CANCELLED").all())
        assert len(avisos) == 1

    def test_cancellation_info_lee_el_ultimo_evento(self, db_session, esc, correos):
        proc = esc["proc"]()
        assert _svc().cancellation_info(db_session, proc) is None

        _svc().cancel(db_session, proc.id, reason="Motivo visible", actor_id=esc["actor"].id)

        info = _svc().cancellation_info(db_session, proc)
        assert info["reason"] == "Motivo visible"
        assert info["actor_id"] == esc["actor"].id
        assert info["at"] is not None


# ===========================================================================
# 2. La cita vigente
# ===========================================================================
class TestCita:
    @pytest.mark.parametrize("estado", ["scheduled", "confirmed"])
    def test_la_cita_viva_se_cancela_y_libera_su_lugar(self, estado, db_session, esc,
                                                      make_appointment, correos):
        from itcj2.apps.titulatec.services.appointment_service import AppointmentService
        proc = esc["proc"](current_phase=2)
        appt = make_appointment(proc, status=estado)

        ok, _ = _svc().cancel(db_session, proc.id, reason="Revocada", actor_id=esc["actor"].id)

        assert ok
        db_session.refresh(appt)
        assert appt.status == "cancelled"
        assert appt.is_current is False
        assert appt.cancelled_by_id == esc["actor"].id
        assert appt.cancel_reason == "Revocada"
        assert AppointmentService.get_for_process(db_session, proc.id) is None
        assert len(_events(db_session, proc.id, "appointment_cancelled")) == 1

    @pytest.mark.parametrize("estado", ["no_show", "attended", "in_progress"])
    def test_una_cita_que_no_se_puede_cancelar_se_deja_como_esta(
        self, estado, db_session, esc, make_appointment, correos,
    ):
        proc = esc["proc"](current_phase=2)
        appt = make_appointment(proc, status=estado)

        ok, _ = _svc().cancel(db_session, proc.id, reason="Revocada", actor_id=esc["actor"].id)

        assert ok
        db_session.refresh(appt)
        assert appt.status == estado

    def test_no_se_agenda_a_un_revocado(self, db_session, agenda_slots, make_survey_review):
        from datetime import time
        from itcj2.apps.titulatec.services.appointment_errors import AppointmentError
        from itcj2.apps.titulatec.services.appointment_service import AppointmentService
        proc = agenda_slots["p1"]
        make_survey_review(proc)
        proc.status = "cancelled"
        db_session.flush()

        with pytest.raises(AppointmentError) as exc:
            AppointmentService.create(db_session, proc.id, window_id=agenda_slots["w"].id,
                                      slot_start=time(9, 0),
                                      created_by_id=agenda_slots["off"].id)
        assert "revocada" in str(exc.value)

    def test_no_se_le_reagenda_a_un_revocado(self, db_session, agenda_slots,
                                             make_survey_review):
        """Reagendar tampoco sienta a un revocado. En secuencia lo para ya la
        guarda rápida de `reschedule`, antes de los locks; la carrera la cubre
        `TestCarreraConLaAgenda`."""
        from datetime import time
        from itcj2.apps.titulatec.services.appointment_errors import EnrollmentRevoked
        from itcj2.apps.titulatec.services.appointment_service import AppointmentService
        proc = agenda_slots["p1"]
        make_survey_review(proc)
        appt = AppointmentService.create(db_session, proc.id, window_id=agenda_slots["w"].id,
                                         slot_start=time(9, 0),
                                         created_by_id=agenda_slots["off"].id)
        proc.status = "cancelled"
        db_session.flush()

        with pytest.raises(EnrollmentRevoked):
            AppointmentService.reschedule(db_session, appt, window_id=agenda_slots["w"].id,
                                          slot_start=time(9, 30),
                                          actor_id=agenda_slots["off"].id)


# ===========================================================================
# 2b. La carrera revocar <-> agendar (TOCTOU, revisión de la T6)
# ===========================================================================
def _revoca_mientras_espera_el_lock(monkeypatch, db, process_id):
    """Simula que la revocación hizo commit MIENTRAS `assign` esperaba su lock.

    El escenario real: la guarda rápida de `create` lee `active`, el encargado
    se queda esperando el lock de la ventana y, entretanto, Servicios Escolares
    revoca y hace commit. Con una sola sesión de test no hay dos transacciones,
    así que se reproduce lo que la de la cita VE al conseguir el lock: la fila
    ya dice `cancelled` en la base, pero el objeto que la guarda rápida dejó en
    el mapa de identidad sigue diciendo `active`. Por eso el UPDATE va por SQL
    crudo y no por el ORM.
    """
    from sqlalchemy import text
    from itcj2.apps.titulatec.services.slot_service import SlotService

    original = SlotService._lock_window

    def _lock_y_revoca(db_, window_id):
        window = original(db_, window_id)
        db_.execute(text("UPDATE titulatec_processes SET status = 'cancelled' "
                         "WHERE id = :pid"), {"pid": process_id})
        return window

    monkeypatch.setattr(SlotService, "_lock_window", staticmethod(_lock_y_revoca))


class TestCarreraConLaAgenda:
    """Hallazgo Important de la revisión: `_assert_not_revoked` corre FUERA de
    los locks. Sin una comprobación DENTRO del advisory del proceso, un
    `create` que ya pasó la guarda sentaba en la agenda a un proceso que se
    revocó mientras esperaba, y el alumno recibía «Tu cita fue agendada»
    después de «inscripción cancelada»."""

    def test_agendar_no_sienta_a_quien_revocaron_mientras_esperaba(
            self, db_session, agenda_slots, make_survey_review, monkeypatch):
        from datetime import time
        from itcj2.apps.titulatec.services.appointment_errors import EnrollmentRevoked
        from itcj2.apps.titulatec.services.appointment_service import AppointmentService
        proc = agenda_slots["p1"]
        make_survey_review(proc)
        _revoca_mientras_espera_el_lock(monkeypatch, db_session, proc.id)

        with pytest.raises(EnrollmentRevoked):
            AppointmentService.create(db_session, proc.id, window_id=agenda_slots["w"].id,
                                      slot_start=time(9, 0),
                                      created_by_id=agenda_slots["off"].id)

        assert AppointmentService.get_for_process(db_session, proc.id) is None
        assert _events(db_session, proc.id, "appointment_scheduled") == []

    def test_reagendar_no_mueve_a_quien_revocaron_mientras_esperaba(
            self, db_session, agenda_slots, make_survey_review, monkeypatch):
        from datetime import time
        from itcj2.apps.titulatec.services.appointment_errors import EnrollmentRevoked
        from itcj2.apps.titulatec.services.appointment_service import AppointmentService
        proc = agenda_slots["p1"]
        make_survey_review(proc)
        appt = AppointmentService.create(db_session, proc.id, window_id=agenda_slots["w"].id,
                                         slot_start=time(9, 0),
                                         created_by_id=agenda_slots["off"].id)
        _revoca_mientras_espera_el_lock(monkeypatch, db_session, proc.id)

        with pytest.raises(EnrollmentRevoked):
            AppointmentService.reschedule(db_session, appt, window_id=agenda_slots["w"].id,
                                          slot_start=time(9, 30),
                                          actor_id=agenda_slots["off"].id)

        assert _events(db_session, proc.id, "appointment_rescheduled") == []

    def test_el_alumno_que_agenda_a_la_vez_lee_su_propio_mensaje(
            self, db_session, agenda_slots, make_survey_review, monkeypatch):
        """El auto-agendado delega en `create`, así que choca con la misma
        comprobación. Lo que le llega al alumno es lo que ya le decía el
        camino secuencial (`proceso_inactivo`), no el texto del encargado
        («La inscripción de este alumno…»)."""
        from datetime import time
        from itcj2.apps.titulatec.services.appointment_errors import SelfBookingNotAllowed
        from itcj2.apps.titulatec.services.self_booking_service import SelfBookingService
        proc = agenda_slots["p1"]
        make_survey_review(proc)
        agenda_slots["w"].visibility = "bookable"
        db_session.flush()
        _revoca_mientras_espera_el_lock(monkeypatch, db_session, proc.id)

        with pytest.raises(SelfBookingNotAllowed) as exc:
            SelfBookingService.book(db_session, proc.id, agenda_slots["w"].id,
                                    time(9, 30), proc.student_id)

        assert exc.value.reason == "proceso_inactivo"
        assert str(exc.value) == SelfBookingService.message_for("proceso_inactivo")

    def test_revocar_espera_a_la_cita_que_se_esta_agendando(
            self, db_session, esc, correos, _pg_engine):
        """Del otro lado: `cancel` tiene que esperar el advisory de las citas del
        proceso. Si no, lee «sin cita vigente» mientras un `create` que ya tiene
        el lock está insertando, y la cita nace sobre un proceso revocado.

        Aquí sí hay dos conexiones de verdad: la segunda solo sostiene el
        advisory (no lee nada de este test), y un `lock_timeout` corto convierte
        «se quedó esperando» en un error medible en vez de un test colgado.
        """
        from sqlalchemy import text
        from sqlalchemy.exc import OperationalError
        from itcj2.apps.titulatec.services.slot_service import _PROCESO_LOCK_NS
        proc = esc["proc"]()

        otra = _pg_engine.connect()
        tx = otra.begin()
        try:
            otra.execute(text("SELECT pg_advisory_xact_lock(:ns, :pid)"),
                         {"ns": _PROCESO_LOCK_NS, "pid": proc.id})
            db_session.execute(text("SET LOCAL lock_timeout = '300ms'"))

            with pytest.raises(OperationalError):
                _svc().cancel(db_session, proc.id, reason="Revocada",
                              actor_id=esc["actor"].id)
        finally:
            tx.rollback()
            otra.close()
            db_session.rollback()
        assert correos == []

    def test_revocar_toma_el_lock_de_citas_antes_que_la_fila_del_proceso(
            self, db_session, esc, correos):
        """El orden no es decorativo. `assign` toma ventana -> advisory, y al
        insertar la cita la FK pide `FOR KEY SHARE` sobre la fila del proceso.
        Si `cancel` tomara primero el `FOR UPDATE` de esa fila y después el
        advisory, cada uno esperaría al otro: deadlock."""
        from sqlalchemy import event
        proc = esc["proc"]()
        sentencias: list[str] = []

        def _captura(conn, cursor, statement, parameters, context, executemany):
            sentencias.append(" ".join(statement.split()))

        conn = db_session.connection()
        event.listen(conn, "before_cursor_execute", _captura)
        try:
            ok, _ = _svc().cancel(db_session, proc.id, reason="Revocada",
                                  actor_id=esc["actor"].id)
        finally:
            event.remove(conn, "before_cursor_execute", _captura)

        assert ok

        def _primera(pred):
            return next(i for i, s in enumerate(sentencias) if pred(s))

        advisory = _primera(lambda s: "pg_advisory_xact_lock" in s)
        fila = _primera(lambda s: "FROM titulatec_processes" in s and "FOR UPDATE" in s)
        citas = _primera(lambda s: "FROM titulatec_review_appointments" in s)
        assert advisory < fila < citas


# ===========================================================================
# 3. Guardas y listados que lo excluyen
# ===========================================================================
class TestLectores:
    def test_el_alumno_queda_bloqueado_por_la_guarda_de_fase(self, db_session, esc, correos):
        from itcj2.apps.titulatec.services.phase_service import PhaseService
        proc = esc["proc"]()
        _svc().cancel(db_session, proc.id, reason="Motivo", actor_id=esc["actor"].id)
        db_session.refresh(proc)

        assert not PhaseService.can_student_act(db_session, proc, 1)
        assert not PhaseService.can_transition(db_session, proc, 1)

    def test_no_es_proceso_acreditable(self, db_session, esc, correos):
        proc = esc["proc"]()
        _svc().cancel(db_session, proc.id, reason="Motivo", actor_id=esc["actor"].id)

        assert _svc().creditable_process(db_session, esc["student"].id) is None

    def test_sale_de_por_agendar(self, db_session, esc, correos, make_document):
        from itcj2.apps.titulatec.services.appointment_service import AppointmentService
        proc = esc["proc"](current_phase=2)
        for code in ("birth_certificate", "high_school_cert", "curp"):
            make_document(proc, type_code=code, review_status="approved")

        antes = {p.id for p in AppointmentService._unscheduled_query(
            db_session, program_id=None, allowed_program_ids=None).all()}
        _svc().cancel(db_session, proc.id, reason="Motivo", actor_id=esc["actor"].id)
        despues = {p.id for p in AppointmentService._unscheduled_query(
            db_session, program_id=None, allowed_program_ids=None).all()}

        assert proc.id in antes and proc.id not in despues

    def test_sale_de_liberados(self, db_session, esc, correos):
        from itcj2.apps.titulatec.services.handoff_service import HandoffService
        proc = esc["proc"](current_phase=3)   # fase 2 aprobada = liberado

        antes = {r.process_id for r in HandoffService.export_rows(
            db_session, allowed_program_ids="ALL")}
        _svc().cancel(db_session, proc.id, reason="Motivo", actor_id=esc["actor"].id)
        despues = {r.process_id for r in HandoffService.export_rows(
            db_session, allowed_program_ids="ALL")}

        assert proc.id in antes
        assert proc.id not in despues, "una inscripción revocada no se entrega a T-soft"

    def test_sale_de_la_bandeja_en_revision_de_gtv(self, db_session, esc, correos,
                                                   make_survey_review):
        from itcj2.apps.titulatec.services.survey_review_service import SurveyReviewService
        proc = esc["proc"](current_phase=2)
        make_survey_review(proc, status="in_review")

        def _ids():
            filas, _ = SurveyReviewService.list_for_inbox(db_session, status="in_review",
                                                         per_page=500)
            return {f["process_id"] for f in filas}

        antes_n = SurveyReviewService.counts_by_status(db_session)["in_review"]
        assert proc.id in _ids()
        _svc().cancel(db_session, proc.id, reason="Motivo", actor_id=esc["actor"].id)

        assert proc.id not in _ids()
        assert SurveyReviewService.counts_by_status(db_session)["in_review"] == antes_n - 1

    def test_el_resumen_de_la_convocatoria_no_lo_cuenta(self, db_session, esc, correos,
                                                       make_student):
        from itcj2.apps.titulatec.pages.admin import _cohort_summary_ctx
        vivo = esc["proc"](alumno=make_student())
        revocado = esc["proc"](alumno=make_student(), current_phase=2)
        _svc().cancel(db_session, revocado.id, reason="Motivo", actor_id=esc["actor"].id)

        res = _cohort_summary_ctx(db_session, esc["cohort"])

        assert res["total"] == 1
        assert res["cancelled"] == 1
        assert {r["number"]: r["count"] for r in res["phase_rows"]}.get(2, 0) == 0
        assert vivo.status == "active"


# ===========================================================================
# 4. D5: la revocada no cuenta como proceso vivo
# ===========================================================================
class TestReinscripcion:
    def _datos(self, control):
        return {"control_number": control, "first_name": "ALUMNO", "last_name": "FICTICIO",
                "phone": "6560000000", "contact_email": "otra@example.invalid",
                "has_efirma": False, "program_text": "Ingenieria Ficticia"}

    def test_puede_inscribirse_en_otra_convocatoria(self, db_session, esc, correos,
                                                    make_cohort, monkeypatch):
        from itcj2.apps.titulatec.services.enrollment_request_service import (
            EnrollmentRequestService,
        )
        monkeypatch.setattr(
            "itcj2.apps.titulatec.services.email_helper.TitulaTecEmailHelper.send_already_enrolled",
            staticmethod(lambda *a, **k: True))
        proc = esc["proc"]()
        _svc().cancel(db_session, proc.id, reason="Motivo", actor_id=esc["actor"].id)
        nueva = make_cohort(status="open")

        req, outcome = EnrollmentRequestService.create(
            db_session, nueva, self._datos(esc["student"].control_number), client_ip=None)

        assert outcome == "created" and req is not None

    def test_la_misma_convocatoria_no_lo_readmite_en_silencio(self, db_session, esc,
                                                             correos):
        """Una sola fila por (alumno, convocatoria): aprobarle otra solicitud en la
        MISMA convocatoria la «convertía» al proceso revocado y el alumno seguía
        cancelado sin que nadie se enterara."""
        from itcj2.apps.titulatec.models import EnrollmentRequest
        from itcj2.apps.titulatec.services.enrollment_request_service import (
            EnrollmentRequestService,
        )
        proc = esc["proc"]()
        _svc().cancel(db_session, proc.id, reason="Motivo", actor_id=esc["actor"].id)
        req = EnrollmentRequest(
            cohort_id=esc["cohort"].id, control_number=esc["student"].control_number,
            first_name="ALUMNO", last_name="FICTICIO", phone="6560000000",
            contact_email="otra@example.invalid", has_efirma=False,
            kind="known", status="pending_review")
        db_session.add(req)
        db_session.flush()

        ok, detalle, raw = EnrollmentRequestService._issue_link_for_account(
            db_session, req, esc["student"])

        assert not ok and raw is None
        assert "revocada" in detalle

        # La liga emitida ANTES de revocar tampoco lo reinscribe al abrirse.
        req.status = "approved"
        db_session.flush()
        ok, detalle = EnrollmentRequestService._convert(db_session, req)
        assert not ok and "revocada" in detalle
        db_session.refresh(proc)
        assert proc.status == "cancelled"


# ===========================================================================
# 5. Correo: personal + institucional, sin datos sensibles
# ===========================================================================
class TestCorreo:
    def test_va_al_personal_y_al_institucional(self, db_session, esc, monkeypatch):
        from itcj2.apps.titulatec.models import EnrollmentRequest
        from itcj2.apps.titulatec.services.email_helper import TitulaTecEmailHelper
        from itcj2.core.utils.email_tools import student_email

        enviados = []

        class _Resp:
            status_code = 202
            text = ""

        monkeypatch.setattr("itcj2.core.utils.msgraph_mail.acquire_token_silent",
                            lambda app_key: "token-de-prueba")
        monkeypatch.setattr(
            "itcj2.core.utils.msgraph_mail.graph_send_mail",
            lambda tok, subject, html, to, save_to_sent=True:
                enviados.append((subject, list(to), html)) or _Resp())
        proc = esc["proc"]()
        db_session.add(EnrollmentRequest(
            cohort_id=esc["cohort"].id, control_number=esc["student"].control_number,
            first_name="ALUMNO", last_name="FICTICIO", phone="6560000000",
            contact_email="personal@example.invalid", has_efirma=False,
            kind="known", status="converted", converted_process_id=proc.id))
        db_session.flush()

        ok = TitulaTecEmailHelper.send_process_cancelled(db_session, proc)

        assert ok
        destinos = sorted(d for _, to, _ in enviados for d in to)
        assert destinos == sorted(["personal@example.invalid", student_email(esc["student"])])
        for _, _, html in enviados:
            assert proc.folio not in html
            assert esc["student"].control_number not in html

    def test_sin_solicitud_solo_va_al_institucional(self, db_session, esc, monkeypatch):
        from itcj2.apps.titulatec.services import email_helper
        destinos = []
        monkeypatch.setattr(email_helper, "_deliver",
                            lambda **kw: destinos.append(kw["to"]) or True)
        proc = esc["proc"]()

        assert email_helper.TitulaTecEmailHelper.send_process_cancelled(
            db_session, proc)
        assert len(destinos) == 1

    def test_nunca_lanza(self, db_session, esc, monkeypatch):
        from itcj2.apps.titulatec.services import email_helper

        def _explota(**kw):
            raise RuntimeError("boom")

        monkeypatch.setattr(email_helper, "_deliver", _explota)
        proc = esc["proc"]()

        assert email_helper.TitulaTecEmailHelper.send_process_cancelled(
            db_session, proc) is False


# ===========================================================================
# 6. Ruta del expediente: permiso, alcance por carrera, motivo
# ===========================================================================
def _url(pid):
    return f"/titulatec/admin/processes/{pid}/cancelar"


class TestRuta:
    def test_revoca_y_devuelve_el_expediente(self, db_session, esc, make_head, client_as,
                                             correos):
        proc = esc["proc"]()
        jefa = make_head(perm_codes=REVOCA_PERMS)

        resp = client_as(jefa).post(_url(proc.id), data={"reason": "Documentación falsa"})

        assert resp.status_code == 200, resp.text[:300]
        assert 'id="exp-shell"' in resp.text
        assert "Documentación falsa" in resp.text
        db_session.refresh(proc)
        assert proc.status == "cancelled"

    def test_sin_el_permiso_es_403(self, db_session, esc, make_head, client_as, correos):
        proc = esc["proc"]()
        jefa = make_head(perm_codes=(READ_ALL, DETAIL))

        resp = client_as(jefa).post(_url(proc.id), data={"reason": "x"},
                                    follow_redirects=False)

        assert resp.status_code == 403
        db_session.refresh(proc)
        assert proc.status == "active"

    def test_fuera_de_su_carrera_es_404(self, db_session, esc, make_officer, make_program,
                                        client_as, correos):
        proc = esc["proc"]()
        otra = make_program("Ingenieria Ajena")
        encargado, _ = make_officer([otra], perm_codes=(DETAIL, CANCEL))

        resp = client_as(encargado).post(_url(proc.id), data={"reason": "x"})

        assert resp.status_code == 404
        assert "X-Tt-Error" not in resp.headers
        db_session.refresh(proc)
        assert proc.status == "active"

    def test_en_su_carrera_si_puede(self, db_session, esc, make_officer, client_as, correos):
        proc = esc["proc"]()
        encargado, _ = make_officer([esc["prog"]], perm_codes=(DETAIL, CANCEL))

        resp = client_as(encargado).post(_url(proc.id), data={"reason": "Motivo"})

        assert resp.status_code == 200, resp.text[:300]
        db_session.refresh(proc)
        assert proc.status == "cancelled"

    def test_sin_motivo_es_400(self, db_session, esc, make_head, client_as, correos):
        proc = esc["proc"]()
        jefa = make_head(perm_codes=REVOCA_PERMS)

        resp = client_as(jefa).post(_url(proc.id), data={"reason": "  "})

        assert resp.status_code == 400
        assert "motivo" in _msg(resp).lower()

    def test_ya_revocada_es_400(self, db_session, esc, make_head, client_as, correos):
        proc = esc["proc"]()
        jefa = make_head(perm_codes=REVOCA_PERMS)
        client_as(jefa).post(_url(proc.id), data={"reason": "Uno"})

        resp = client_as(jefa).post(_url(proc.id), data={"reason": "Dos"})

        assert resp.status_code == 400
        assert "revocada" in _msg(resp)
        assert len(correos) == 1


# ===========================================================================
# 7. Pantallas: expediente y dashboard del alumno
# ===========================================================================
class TestPantallas:
    def test_el_expediente_ofrece_revocar_solo_con_el_permiso(self, esc, make_head,
                                                              make_officer, client_as):
        proc = esc["proc"]()
        con = make_head(perm_codes=REVOCA_PERMS)
        # Otro rol ficticio (los de `make_head` comparten nombre y se suman).
        sin, _ = make_officer([esc["prog"]], perm_codes=(DETAIL,))

        html_con = client_as(con).get(f"/titulatec/admin/processes/{proc.id}").text
        html_sin = client_as(sin).get(f"/titulatec/admin/processes/{proc.id}").text

        assert 'id="exp-revocar-abrir"' in html_con
        assert 'id="exp-modal-revocar"' in html_con
        assert f"/titulatec/admin/processes/{proc.id}/cancelar" in html_con
        assert 'id="exp-revocar-abrir"' not in html_sin
        assert 'id="exp-modal-revocar"' not in html_sin

    def test_el_expediente_revocado_dice_por_que_y_ya_no_ofrece_revocar(
        self, db_session, esc, make_head, client_as, correos,
    ):
        proc = esc["proc"]()
        jefa = make_head(perm_codes=REVOCA_PERMS)
        _svc().cancel(db_session, proc.id, reason="Duplicado", actor_id=jefa.id)

        html = client_as(jefa).get(f"/titulatec/admin/processes/{proc.id}").text

        assert 'id="exp-revocada"' in html
        assert "Duplicado" in html
        assert 'id="exp-revocar-abrir"' not in html
        assert "Inscripción revocada" in html      # historial, no el código crudo
        assert ">cancelled<" not in html

    def test_el_checklist_de_una_revocada_es_de_solo_lectura(
        self, db_session, esc, make_head, client_as, correos,
    ):
        from itcj2.apps.titulatec.pages.admin import _detail_ctx
        proc = esc["proc"](current_phase=2)
        jefa = make_head(perm_codes=REVOCA_PERMS + ("titulatec.process.api.requirement.mark",))
        assert _detail_ctx(db_session, proc.id, user_id=jefa.id)["can_mark_reqs"] is True

        _svc().cancel(db_session, proc.id, reason="Motivo", actor_id=jefa.id)

        assert _detail_ctx(db_session, proc.id, user_id=jefa.id)["can_mark_reqs"] is False

    def test_el_alumno_ve_el_motivo(self, db_session, esc, client_as, correos):
        proc = esc["proc"]()
        _svc().cancel(db_session, proc.id, reason="Tu acta no es legible",
                      actor_id=esc["actor"].id)

        html = client_as(esc["student"]).get("/titulatec/student/dashboard").text

        assert 'id="tt-inscripcion-cancelada"' in html
        assert "Tu inscripción fue cancelada" in html
        assert "Tu acta no es legible" in html
        assert "data-tt-cta" not in html, "una inscripción cancelada no ofrece acciones"

    def test_el_alumno_activo_no_ve_el_aviso(self, esc, client_as):
        esc["proc"]()
        html = client_as(esc["student"]).get("/titulatec/student/dashboard").text
        assert 'id="tt-inscripcion-cancelada"' not in html

    def test_la_bandeja_de_procesos_lo_etiqueta(self, db_session, esc, make_head,
                                                client_as, correos):
        proc = esc["proc"]()
        jefa = make_head(perm_codes=REVOCA_PERMS + ("titulatec.process.page.list",))
        _svc().cancel(db_session, proc.id, reason="x", actor_id=jefa.id)

        html = client_as(jefa).get("/titulatec/admin/processes?status=cancelled").text

        assert proc.folio in html
        assert ">cancelled<" not in html
        assert "Revocad" in html
