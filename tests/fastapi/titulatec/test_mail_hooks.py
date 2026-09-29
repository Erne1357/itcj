"""Ganchos del catálogo de correos en los services (spec 2026-09-28 §5, Tarea 5).

Cada evento del catálogo deja su fila en `titulatec_email_outbox` DENTRO de la
transacción del service que lo produce (`StudentMail.*`, sin commit propio).

Por qué cada prueba lee la FILA y no el resultado de la acción: `StudentMail.*`
es best-effort y nunca lanza. Un kwarg mal escrito, una firma cambiada o una
cita sin id devolverían `False` con un warning y la acción seguiría como si
nada; una prueba que solo mirara «la acción salió bien» pasaría igual. Aquí se
afirma `kind`, `group_key` y `payload` de lo que quedó encolado.

También se fijan los dos in-app nuevos (spec §5, #9: «no se presentó» y su
corrección) y que el in-app de siempre NO cambió: el alumno que agenda no
recibe aviso de su propio clic, pero sí el correo (D9, le sirve de comprobante).

Nada toca Graph: `_graph_espiado` corta el token y registra cualquier envío.
"""
from __future__ import annotations

from datetime import time, timedelta

import pytest

import itcj2.models  # noqa: F401

from tests.fastapi.titulatec.conftest import OFFICER_PERMS


# ---------------------------------------------------------------------------
# Andamiaje local
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _correo_encendido(monkeypatch):
    """Correo encendido y corte a T-soft en su valor por omisión (fase 3), sin
    depender del `.env` del contenedor. Se fijan los ATRIBUTOS del singleton de
    `get_settings()` (mismo molde que `_modo_oficial_por_defecto`)."""
    from itcj2.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "TITULATEC_EMAIL_ENABLED", True)
    monkeypatch.setattr(settings, "TITULATEC_HANDOFF_PHASE", 3)


@pytest.fixture(autouse=True)
def _graph_espiado(monkeypatch):
    """Graph sin cuenta conectada (el estado real de titulatec en dev) y un
    espía por si algo intentara enviar: la revocación sí llama a
    `send_process_cancelled` después de su commit."""
    enviados: list = []
    monkeypatch.setattr("itcj2.core.utils.msgraph_mail.acquire_token_silent",
                        lambda app_key: None)
    monkeypatch.setattr("itcj2.core.utils.msgraph_mail.graph_send_mail",
                        lambda *a, **k: enviados.append((a, k)))
    return enviados


def _outbox(db, process_id, kind=None):
    """Filas del outbox del proceso, en orden de llegada. El flush es EXPLÍCITO:
    en producción `SessionLocal` es autoflush=False y el arnés no."""
    from itcj2.apps.titulatec.models import EmailOutbox

    db.flush()
    q = db.query(EmailOutbox).filter_by(process_id=process_id)
    if kind is not None:
        q = q.filter_by(kind=kind)
    return q.order_by(EmailOutbox.id).all()


def _avisos(db, user_id, tipo):
    """Notificaciones in-app de titulatec de ese tipo para el usuario."""
    from itcj2.core.models.notification import Notification

    db.flush()
    return (db.query(Notification)
            .filter_by(user_id=user_id, app_name="titulatec", type=tipo)
            .order_by(Notification.id).all())


@pytest.fixture()
def revisor(make_user):
    """Persona de Servicios Escolares que EXISTE en `core_users` (FK de eventos)."""
    return make_user(first_name="REVISORA", last_name="DE PRUEBA")


@pytest.fixture()
def docs_esc(seed_phase_defs, seed_document_types, make_student, make_process,
             make_document):
    """Proceso en la fase 1 con dos documentos iniciales por dictaminar."""
    seed_phase_defs()
    seed_document_types()
    proc = make_process(make_student(), current_phase=1)
    make_document(proc, type_code="birth_certificate")
    make_document(proc, type_code="curp")
    return {"proc": proc}


@pytest.fixture()
def cita_esc(agenda_slots, make_survey_review):
    """`agenda_slots` (día 2029-05-07, ventana 09:00-11:00 de franjas de 30,
    cupo 1) con la encuesta de egresados YA ENVIADA para `p1`: sin ella
    `AppointmentService.create` levanta `SurveyNotSubmitted` (D2)."""
    make_survey_review(agenda_slots["p1"])
    return agenda_slots


def _agendar(db, esc, *, por_alumno=False, slot=time(9, 0), location="Ventanilla 3"):
    from itcj2.apps.titulatec.services.appointment_service import AppointmentService

    p1 = esc["p1"]
    return AppointmentService.create(
        db, p1.id, window_id=esc["w"].id, slot_start=slot,
        created_by_id=(p1.student_id if por_alumno else esc["off"].id),
        location=location, booked_by=("student" if por_alumno else "officer"))


def _cita_payload(event, by, appt, reason=None):
    """El payload EXACTO de `appt_changed` para una cita ya con id."""
    return {"event": event, "by": by, "reason": reason, "appt_id": appt.id,
            "scheduled_at": appt.scheduled_at.isoformat(),
            "location": appt.location}


# ---------------------------------------------------------------------------
# #1 / #1b — dictamen de documentos y avance de la fase 1 (grupo `docs:{pid}`)
# ---------------------------------------------------------------------------
def test_aprobar_y_rechazar_documento_encola_docs_review(db_session, docs_esc, revisor):
    from itcj2.apps.titulatec.services.document_service import DocumentService

    proc = docs_esc["proc"]
    DocumentService.review(db_session, proc.id, "birth_certificate", status="approved",
                           note=None, reviewer_id=revisor.id)
    DocumentService.review(db_session, proc.id, "curp", status="rejected",
                           note="La CURP no es legible", reviewer_id=revisor.id)

    filas = _outbox(db_session, proc.id)
    assert [f.kind for f in filas] == ["docs_review", "docs_review"]
    assert {f.group_key for f in filas} == {f"docs:{proc.id}"}
    assert {f.user_id for f in filas} == {proc.student_id}
    assert filas[0].payload == {"type_code": "birth_certificate",
                                "name": "Acta de nacimiento",
                                "status": "approved", "note": None}
    # El motivo viaja tal como estaba al dictaminar: `review_note` es un solo
    # hueco y la siguiente revisión lo pisa.
    assert filas[1].payload == {"type_code": "curp", "name": "CURP certificada",
                                "status": "rejected", "note": "La CURP no es legible"}


def test_documento_sin_tipo_en_el_catalogo_usa_el_codigo_como_nombre(
        db_session, docs_esc, make_document, revisor):
    """Respaldo del nombre: un tipo retirado del catálogo no deja el correo sin
    nombre (ni tumba el dictamen)."""
    from itcj2.apps.titulatec.services.document_service import DocumentService

    proc = docs_esc["proc"]
    make_document(proc, type_code="tipo_retirado", phase_number=1)

    assert DocumentService.review(db_session, proc.id, "tipo_retirado",
                                  status="approved", note=None,
                                  reviewer_id=revisor.id) is True

    (fila,) = _outbox(db_session, proc.id)
    assert fila.payload["name"] == "tipo_retirado"


def test_tercer_aprobado_encola_tambien_phase_approved_en_el_grupo(
        db_session, client_as, seed_phase_defs, seed_document_types, make_program,
        make_officer, make_student, make_process, make_document):
    """La ruta real de la bandeja: el 3.º aprobado auto-avanza la fase 1, y el
    aviso de ese avance va al MISMO grupo que los dictámenes (sale en un solo
    correo con ellos, D7)."""
    from itcj2.apps.titulatec.models import TitulationProcess

    seed_phase_defs()
    seed_document_types()
    prog = make_program("Ingenieria Ficticia de Correos")
    encargado, _ = make_officer(
        [prog], perm_codes=OFFICER_PERMS + ("titulatec.document.api.approve",))
    proc = make_process(make_student(), program=prog, current_phase=1)
    make_document(proc, type_code="birth_certificate", review_status="approved")
    make_document(proc, type_code="high_school_cert", review_status="approved")
    make_document(proc, type_code="curp")

    resp = client_as(encargado).post(
        f"/titulatec/admin/documents/{proc.id}/document/review",
        data={"type_code": "curp", "action": "approve"})

    assert resp.status_code == 200, resp.text[:400]
    assert db_session.get(TitulationProcess, proc.id).current_phase == 2
    filas = _outbox(db_session, proc.id)
    assert [f.kind for f in filas] == ["docs_review", "phase_approved"]
    assert {f.group_key for f in filas} == {f"docs:{proc.id}"}
    assert filas[0].payload == {"type_code": "curp", "name": "CURP certificada",
                                "status": "approved", "note": None}
    assert filas[1].payload == {"phase_number": 1,
                                "phase_name": "Fase 01 · Documentos iniciales",
                                "next_phase": 2,
                                "next_name": "Fase 02 · Cita de cotejo",
                                "handoff": False, "completed": False}


# ---------------------------------------------------------------------------
# #2 / #3 — avance y rechazo de fase (individuales)
# ---------------------------------------------------------------------------
def test_aprobar_fase_2_encola_handoff(db_session, seed_phase_defs, make_student,
                                       make_process, revisor):
    """Con el corte por omisión (fase 3), aprobar la 2 entrega el proceso a
    T-soft: el correo lo dice (`handoff=True`) y sale solo, sin grupo."""
    from itcj2.apps.titulatec.services.phase_service import PhaseService

    seed_phase_defs()
    proc = make_process(make_student(), current_phase=2)

    PhaseService.approve_phase(db_session, proc, 2, reviewer_id=revisor.id)

    (fila,) = _outbox(db_session, proc.id)
    assert fila.kind == "phase_approved"
    assert fila.group_key is None
    assert fila.payload == {"phase_number": 2,
                            "phase_name": "Fase 02 · Cita de cotejo",
                            "next_phase": 3, "next_name": "Fase 03 · Formato B",
                            "handoff": True, "completed": False}


def test_rechazar_fase_encola_con_motivo(db_session, seed_phase_defs, make_student,
                                         make_process, revisor):
    from itcj2.apps.titulatec.services.phase_service import PhaseService

    seed_phase_defs()
    proc = make_process(make_student(), current_phase=2)

    PhaseService.reject_phase(db_session, proc, 2, reviewer_id=revisor.id,
                              reason="El acta no coincide con la CURP")

    (fila,) = _outbox(db_session, proc.id)
    assert fila.kind == "phase_rejected"
    assert fila.group_key is None
    assert fila.payload == {"phase_number": 2,
                            "phase_name": "Fase 02 · Cita de cotejo",
                            "reason": "El acta no coincide con la CURP"}


# ---------------------------------------------------------------------------
# #4-#6 — dictamen de GTV sobre la encuesta
# ---------------------------------------------------------------------------
def test_gtv_liberar_observar_revocar_encolan(db_session, make_student, make_process,
                                              make_cohort, make_user,
                                              make_survey_review):
    from itcj2.apps.titulatec.services.survey_review_service import SurveyReviewService

    proc = make_process(make_student(), cohort=make_cohort(), current_phase=2)
    gtv = make_user(first_name="GTV", last_name="DE PRUEBA")
    review = make_survey_review(proc, status="in_review")

    SurveyReviewService.reject(db_session, review.id, gtv.id, "  Debe Servicio Social  ")
    SurveyReviewService.approve(db_session, review.id, gtv.id)
    SurveyReviewService.revoke(db_session, review.id, gtv.id, "Se liberó por error")

    filas = _outbox(db_session, proc.id)
    assert [(f.kind, f.payload, f.group_key) for f in filas] == [
        ("survey_rejected", {"reason": "Debe Servicio Social"}, None),
        ("survey_approved", {"reason": None}, None),
        ("survey_revoked", {"reason": "Se liberó por error"}, None),
    ]


# ---------------------------------------------------------------------------
# #7 — la cita de cotejo (grupo `cita:{pid}`)
# ---------------------------------------------------------------------------
def test_encargado_agenda_encola_y_notifica(db_session, cita_esc):
    p1 = cita_esc["p1"]

    appt = _agendar(db_session, cita_esc)

    assert appt.id is not None
    (fila,) = _outbox(db_session, p1.id)
    assert fila.kind == "appt_changed"
    assert fila.group_key == f"cita:{p1.id}"
    assert fila.payload == _cita_payload("scheduled", "officer", appt)
    assert len(_avisos(db_session, p1.student_id, "APPOINTMENT_SCHEDULED")) == 1


def test_alumno_agenda_encola_pero_sin_in_app(db_session, cita_esc):
    """D9: su propio clic no le genera aviso en la app (decisión del
    auto-agendado), pero SÍ el correo, que le sirve de comprobante."""
    p1 = cita_esc["p1"]

    appt = _agendar(db_session, cita_esc, por_alumno=True)

    (fila,) = _outbox(db_session, p1.id)
    assert fila.kind == "appt_changed"
    assert fila.group_key == f"cita:{p1.id}"
    assert fila.payload == _cita_payload("scheduled", "student", appt)
    assert _avisos(db_session, p1.student_id, "APPOINTMENT_SCHEDULED") == []


def test_reagendar_encola(db_session, cita_esc):
    from itcj2.apps.titulatec.services.appointment_service import AppointmentService

    p1 = cita_esc["p1"]
    primera = _agendar(db_session, cita_esc)

    nueva = AppointmentService.reschedule(db_session, primera, window_id=cita_esc["w"].id,
                                          slot_start=time(9, 30),
                                          actor_id=cita_esc["off"].id)

    filas = _outbox(db_session, p1.id)
    assert [f.payload["event"] for f in filas] == ["scheduled", "rescheduled"]
    assert {f.group_key for f in filas} == {f"cita:{p1.id}"}
    # La cita de la fila es la NUEVA (reagendar inserta otra), no la cerrada.
    assert nueva.id != primera.id
    assert filas[1].payload == _cita_payload("rescheduled", "officer", nueva)
    assert filas[1].payload["scheduled_at"].endswith("09:30:00")


def test_encargado_cancela_encola_con_motivo(db_session, cita_esc):
    from itcj2.apps.titulatec.services.appointment_service import AppointmentService

    p1 = cita_esc["p1"]
    appt = _agendar(db_session, cita_esc)

    AppointmentService.cancel(db_session, appt, cita_esc["off"].id,
                              "  El encargado no estará ese día  ")

    filas = _outbox(db_session, p1.id)
    assert [f.payload["event"] for f in filas] == ["scheduled", "cancelled"]
    assert filas[1].group_key == f"cita:{p1.id}"
    assert filas[1].payload == _cita_payload(
        "cancelled", "officer", appt, reason="El encargado no estará ese día")


def test_alumno_cancela_no_encola(db_session, cita_esc):
    """La cancelación del propio alumno no lleva correo (spec §5 «Sin correo»).
    Va por el camino real del alumno, `SelfBookingService.cancel`."""
    from itcj2.apps.titulatec.services.self_booking_service import SelfBookingService

    p1 = cita_esc["p1"]
    appt = _agendar(db_session, cita_esc, por_alumno=True)

    SelfBookingService.cancel(db_session, appt, p1.student_id, "ya no puedo ir")

    assert appt.status == "cancelled"
    filas = _outbox(db_session, p1.id)
    assert [f.payload["event"] for f in filas] == ["scheduled"]


def test_revocar_proceso_no_encola_cancelacion_de_cita(db_session, cita_esc,
                                                       _graph_espiado):
    """`ProcessService.cancel` cancela la cita con `notify=False`: el aviso al
    alumno es el de la revocación (`send_process_cancelled`), no «tu cita fue
    cancelada»."""
    from itcj2.apps.titulatec.services.process_service import ProcessService

    p1 = cita_esc["p1"]
    appt = _agendar(db_session, cita_esc)

    ok, _msg = ProcessService.cancel(db_session, p1.id, reason="Documentación apócrifa",
                                     actor_id=cita_esc["off"].id)

    assert ok is True
    assert appt.status == "cancelled", "la revocación sí canceló la cita"
    filas = _outbox(db_session, p1.id)
    assert [f.payload["event"] for f in filas] == ["scheduled"]
    assert _graph_espiado == []


# ---------------------------------------------------------------------------
# #9 — «no se presentó» (correo con gracia + in-app nuevo) y su corrección
# ---------------------------------------------------------------------------
def test_no_show_encola_con_gracia_y_crea_in_app(db_session, cita_esc, monkeypatch):
    from itcj2.apps.titulatec.services.appointment_service import AppointmentService
    from itcj2.apps.titulatec.services.student_mail import MailSettings
    from itcj2.core.utils.timezone import db_now

    monkeypatch.setattr(MailSettings, "digest_minutes", staticmethod(lambda: 15))
    p1 = cita_esc["p1"]
    appt = _agendar(db_session, cita_esc)

    antes = db_now()
    AppointmentService.mark_no_show(db_session, appt, cita_esc["off"].id)
    despues = db_now()

    (fila,) = _outbox(db_session, p1.id, kind="appt_no_show")
    assert fila.group_key is None
    assert fila.payload == {"appt_id": appt.id,
                            "scheduled_at": appt.scheduled_at.isoformat()}
    # D8: espera la gracia antes de salir; si se deshace dentro, no sale.
    assert antes + timedelta(minutes=15) <= fila.not_before <= despues + timedelta(minutes=15)

    (aviso,) = _avisos(db_session, p1.student_id, "APPOINTMENT_NO_SHOW")
    assert aviso.title == "No registramos tu asistencia a tu cita"
    assert aviso.body == "07 may 2029 · 09:00 · Ventanilla 3"
    assert aviso.data["process_id"] == p1.id
    assert aviso.data["phase_number"] == 2


def test_deshacer_no_show_crea_in_app(db_session, cita_esc):
    """El in-app de la corrección sale en el acto; correo NO: el `appt_no_show`
    que siga pendiente lo da por obsoleto el despachador al re-validar (D8)."""
    from itcj2.apps.titulatec.services.appointment_service import AppointmentService

    p1 = cita_esc["p1"]
    appt = _agendar(db_session, cita_esc)
    AppointmentService.mark_no_show(db_session, appt, cita_esc["off"].id)
    antes = [(f.id, f.kind) for f in _outbox(db_session, p1.id)]

    AppointmentService.undo_no_show(db_session, appt, cita_esc["off"].id)

    assert appt.status == "in_progress"
    assert [(f.id, f.kind) for f in _outbox(db_session, p1.id)] == antes
    (aviso,) = _avisos(db_session, p1.student_id, "APPOINTMENT_NO_SHOW_UNDONE")
    assert aviso.title == "Se corrigió tu asistencia a la cita"
    assert aviso.data["phase_number"] == 2


# ---------------------------------------------------------------------------
# Review Focus 4 — el evento se revierte después de encolar
# ---------------------------------------------------------------------------
def test_si_el_commit_falla_no_queda_correo(db_session, docs_esc, revisor, monkeypatch):
    """La fila vive en la transacción del evento: si su COMMIT falla, se va con
    él. Se hace `commit()` del setup primero porque el arnés es de savepoint y
    el `rollback()` de abajo se llevaría también lo que sembraron las fábricas.
    """
    from itcj2.apps.titulatec.models import Document, EmailOutbox
    from itcj2.apps.titulatec.services.document_service import DocumentService

    pid, uid = docs_esc["proc"].id, revisor.id
    db_session.commit()

    def _commit_que_falla():
        db_session.flush()                       # las filas llegan a la BD...
        raise RuntimeError("se cayó el COMMIT")  # ...y la transacción no se confirma

    monkeypatch.setattr(db_session, "commit", _commit_que_falla)

    with pytest.raises(RuntimeError):
        DocumentService.review(db_session, pid, "birth_certificate", status="approved",
                               note=None, reviewer_id=uid)

    # Sin esta línea, «0 filas tras el rollback» pasaría también sin gancho:
    # la fila SÍ se escribió, y en la MISMA transacción que el dictamen.
    assert db_session.query(EmailOutbox).filter_by(process_id=pid).count() == 1

    db_session.rollback()

    assert db_session.query(EmailOutbox).filter_by(process_id=pid).count() == 0
    doc = (db_session.query(Document)
           .filter_by(process_id=pid, type_code="birth_certificate").one())
    assert doc.review_status == "pending", "el dictamen se revirtió junto con el correo"
