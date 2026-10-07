"""Ganchos del catálogo de correos en los services (spec 2026-09-28 §5, Tarea 5;
y el no adeudo de biblioteca, spec 2026-10-01-titulatec-biblioteca-caja-design.md
§4.11, Tarea 10).

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
from decimal import Decimal
from types import SimpleNamespace

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
    espía por si algo intentara enviar: nada de aquí manda en la petición (la
    revocación también encola su aviso desde la spec 2026-10-05 §3.7)."""
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
    cupo 1) con la encuesta de egresados YA LIBERADA para `p1`: sin liberarla
    `AppointmentService.create` levanta `SurveyNotSubmitted`/`SurveyNotReleased`
    (D1, spec 2026-09-29-titulatec-cotejo-espacios-design.md §2, revierte D2
    del 2026-09-15)."""
    make_survey_review(agenda_slots["p1"], status="approved")
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
        ("survey_rejected", {"reason": "Debe Servicio Social", "origin": "submission"}, None),
        ("survey_approved", {"reason": None, "origin": "submission"}, None),
        ("survey_revoked", {"reason": "Se liberó por error", "origin": "submission"}, None),
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
    alumno es el de la revocación (la fila `process_cancelled`, que desde la
    spec 2026-10-05-titulatec-rendimiento §3.7 también se encola), no «tu cita
    fue cancelada»."""
    from itcj2.apps.titulatec.services.process_service import ProcessService

    p1 = cita_esc["p1"]
    appt = _agendar(db_session, cita_esc)

    ok, _msg = ProcessService.cancel(db_session, p1.id, reason="Documentación apócrifa",
                                     actor_id=cita_esc["off"].id)

    assert ok is True
    assert appt.status == "cancelled", "la revocación sí canceló la cita"
    filas = _outbox(db_session, p1.id, kind="appt_changed")
    assert [f.payload["event"] for f in filas] == ["scheduled"]
    assert [f.kind for f in _outbox(db_session, p1.id)] == ["appt_changed",
                                                           "process_cancelled"]
    assert _graph_espiado == []


@pytest.fixture()
def atender_esc(make_program, make_cohort, make_review_day, make_officer, make_student,
                make_process, make_review_window, make_survey_review):
    """El sin horario de HOY del encargado y dos egresados con la encuesta
    LIBERADA: «Atender ahora» (D7) solo existe en el espacio sin horario de hoy
    del propio encargado (spec 2026-09-29-titulatec-cotejo-espacios-design.md §4)."""
    from itcj2.core.utils.timezone import db_now

    prog = make_program("Ingenieria de Atender Ahora")
    cohort = make_cohort()
    dia = make_review_day(cohort, day=db_now().date())
    off, pos = make_officer([prog])
    w = make_review_window(dia, off, start="08:00", end="14:00", cap=5,
                           location="Ventanilla 2", position=pos, visibility="walkin")
    p1, p2 = (make_process(make_student(), cohort=cohort, program=prog, current_phase=2)
              for _ in range(2))
    for p in (p1, p2):
        make_survey_review(p, status="approved")
    return {"off": off, "w": w, "p1": p1, "p2": p2}


def test_atender_ahora_no_encola(db_session, atender_esc):
    """«Atender ahora» (D7): el egresado está enfrente, así que su cita nace
    `in_progress` SIN correo ni aviso in-app de «agendada». Es la rama sin
    correo de `AppointmentService.create` (`start_now=True`) que registra
    `RAMAS_SIN_CORREO`, y va por el camino real, `attend_now`.

    La segunda mitad es el control positivo: el MISMO espacio, agendado por la
    vía normal, sí encola y sí avisa. Sin ella, «cero filas» pasaría también
    con el correo apagado."""
    from itcj2.apps.titulatec.services.appointment_service import AppointmentService
    from itcj2.core.models.notification import Notification

    esc = atender_esc
    p1, p2 = esc["p1"], esc["p2"]

    appt = AppointmentService.attend_now(db_session, p1.id, window_id=esc["w"].id,
                                         actor_id=esc["off"].id)

    assert appt.status == "in_progress"
    assert _outbox(db_session, p1.id) == []
    assert (db_session.query(Notification)
            .filter_by(user_id=p1.student_id, app_name="titulatec").count()) == 0

    AppointmentService.create(db_session, p2.id, window_id=esc["w"].id,
                              slot_start=time(8, 0), created_by_id=esc["off"].id)
    (fila,) = _outbox(db_session, p2.id)
    assert fila.kind == "appt_changed"
    assert fila.payload["event"] == "scheduled"
    assert len(_avisos(db_session, p2.student_id, "APPOINTMENT_SCHEDULED")) == 1


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
# No adeudo de biblioteca (spec 2026-10-01 §4.11): cada transición de
# `LibraryClearanceService` encola su correo, en su misma transacción.
# ---------------------------------------------------------------------------
@pytest.fixture()
def biblio(db_session, make_user, make_cohort, make_student, make_process,
           make_library_clearance):
    """Fábrica: proceso en la fase 2 con su no adeudo `pending`, en una
    convocatoria con donación (`donation`, $800 por omisión) y el requisito
    automático de no adeudo. Actores de Biblioteca y Caja que existen en
    `core_users` (FK de los eventos)."""
    from itcj2.apps.titulatec.models import CotejoRequirement

    actores = SimpleNamespace(biblioteca=make_user(first_name="BIBLIOTECA"),
                              caja=make_user(first_name="CAJA"))

    def _make(donation=Decimal("800.00"), cohort=None):
        if cohort is None:
            cohort = make_cohort(book_donation_amount=donation)
            db_session.add(CotejoRequirement(
                cohort_id=cohort.id, label="Constancia de no adeudo de biblioteca", icon="book",
                code="library_clearance", auto_source="library_clearance",
                order_index=0))
            db_session.flush()
        proc = make_process(make_student(), cohort=cohort, current_phase=2,
                            library_clearance=None)
        fila = make_library_clearance(proc, status="pending")
        return SimpleNamespace(proc=proc, fila=fila, cohort=cohort, **vars(actores))

    return _make


def _filas_biblioteca(db, process_id):
    """(kind, payload, group_key, dedupe_key) de lo encolado, en orden."""
    return [(f.kind, f.payload, f.group_key, f.dedupe_key)
            for f in _outbox(db, process_id)]


def _listo(debt, donation, total, note=None, updated=False):
    return ("library_ready", {"debt": debt, "donation": donation, "total": total,
                              "note": note, "updated": updated}, None, None)


def test_pasar_a_caja_y_corregir_encolan_library_ready(db_session, biblio):
    from itcj2.apps.titulatec.services.library_clearance_service import (
        LibraryClearanceService,
    )

    esc = biblio()
    LibraryClearanceService.register(db_session, esc.fila.id, esc.biblioteca.id,
                                     debt_amount=Decimal("300.00"),
                                     note="  Debe 2 libros  ")
    LibraryClearanceService.register(db_session, esc.fila.id, esc.biblioteca.id,
                                     debt_amount=Decimal("500.00"), note="Eran 3 libros")

    assert _filas_biblioteca(db_session, esc.proc.id) == [
        _listo("300.00", "800.00", "1100.00", "Debe 2 libros"),
        _listo("500.00", "800.00", "1300.00", "Eran 3 libros", updated=True),
    ]
    assert {f.user_id for f in _outbox(db_session, esc.proc.id)} == {esc.proc.student_id}


def test_correccion_sin_cambios_no_encola(db_session, biblio):
    """Ruling R10 (b): una corrección idéntica (mismo adeudo, misma donación
    congelada, misma nota) es no-op: ni correo, ni aviso, ni evento. Es la rama
    SIN correo de `_mark_ready` (`RAMAS_SIN_CORREO`). El control positivo: con
    otra nota, la MISMA corrección sí encola."""
    from itcj2.apps.titulatec.services.library_clearance_service import (
        LibraryClearanceService,
    )

    esc = biblio()
    LibraryClearanceService.register(db_session, esc.fila.id, esc.biblioteca.id,
                                     debt_amount=Decimal("300.00"), note="Debe 2 libros")
    antes = _filas_biblioteca(db_session, esc.proc.id)
    avisos = len(_avisos(db_session, esc.proc.student_id, "LIBRARY_READY"))

    LibraryClearanceService.register(db_session, esc.fila.id, esc.biblioteca.id,
                                     debt_amount=Decimal("300"), note="  Debe 2 libros ")

    assert _filas_biblioteca(db_session, esc.proc.id) == antes
    assert len(_avisos(db_session, esc.proc.student_id, "LIBRARY_READY")) == avisos

    LibraryClearanceService.register(db_session, esc.fila.id, esc.biblioteca.id,
                                     debt_amount=Decimal("300.00"), note="Debe 1 libro")
    assert _filas_biblioteca(db_session, esc.proc.id)[-1] == _listo(
        "300.00", "800.00", "1100.00", "Debe 1 libro", updated=True)


def test_total_cero_encola_library_cleared_sin_cargo(db_session, biblio):
    from itcj2.apps.titulatec.services.library_clearance_service import (
        LibraryClearanceService,
    )

    esc = biblio(donation=Decimal("0.00"))
    LibraryClearanceService.register(db_session, esc.fila.id, esc.biblioteca.id,
                                     debt_amount=Decimal("0"), note=None)

    assert _filas_biblioteca(db_session, esc.proc.id) == [
        ("library_cleared", {"via": "no_charge"}, None, None)]


def test_lote_sin_adeudo_encola_uno_por_caso(db_session, biblio):
    """D10: el lote es UNA transacción, pero cada egresado recibe su correo."""
    from itcj2.apps.titulatec.services.library_clearance_service import (
        LibraryClearanceService,
    )

    a = biblio()
    b = biblio(cohort=a.cohort)
    LibraryClearanceService.register_no_debt_bulk(
        db_session, [a.fila.id, b.fila.id], a.biblioteca.id)

    for esc in (a, b):
        assert _filas_biblioteca(db_session, esc.proc.id) == [
            _listo("0.00", "800.00", "800.00")]


def test_caja_cobra_encola_library_cleared_por_pago(db_session, biblio):
    from itcj2.apps.titulatec.services.library_clearance_service import (
        LibraryClearanceService,
    )

    esc = biblio()
    LibraryClearanceService.register(db_session, esc.fila.id, esc.biblioteca.id,
                                     debt_amount=Decimal("300.00"), note=None)
    LibraryClearanceService.register_payment(db_session, esc.fila.id, esc.caja.id,
                                             receipt_number="R-1")

    assert [k for k, *_ in _filas_biblioteca(db_session, esc.proc.id)] == [
        "library_ready", "library_cleared"]
    assert _filas_biblioteca(db_session, esc.proc.id)[-1] == (
        "library_cleared", {"via": "payment"}, None, None)


def test_constancia_previa_encola_library_cleared_previa(db_session, biblio):
    """D9: Biblioteca, SE o la importación (`commit=False`): las tres encolan."""
    from itcj2.apps.titulatec.services.library_clearance_service import (
        LibraryClearanceService,
    )
    from itcj2.core.utils.timezone import db_now

    hoy = db_now().date()
    for by, commit in (("library", True), ("school_services", True), ("import", False)):
        esc = biblio()
        actor = None if by == "import" else esc.biblioteca.id
        LibraryClearanceService.register_prior(db_session, esc.fila.id, actor,
                                               issued_on=hoy, note=None, by=by,
                                               commit=commit)

        assert _filas_biblioteca(db_session, esc.proc.id) == [
            ("library_cleared", {"via": "prior"}, None, None)], by


def test_revertir_pago_encola_library_reverted_a_caja(db_session, biblio):
    from itcj2.apps.titulatec.services.library_clearance_service import (
        LibraryClearanceService,
    )

    esc = biblio()
    LibraryClearanceService.register(db_session, esc.fila.id, esc.biblioteca.id,
                                     debt_amount=Decimal("300.00"), note=None)
    LibraryClearanceService.register_payment(db_session, esc.fila.id, esc.caja.id)
    LibraryClearanceService.revert_payment(db_session, esc.fila.id, esc.caja.id,
                                           "  Se cobró a otra persona  ")

    assert _filas_biblioteca(db_session, esc.proc.id)[-1] == (
        "library_reverted", {"reason": "Se cobró a otra persona",
                             "to_status": "awaiting_payment"}, None, None)


def test_revertir_sin_cargo_y_deshacer_previa_encolan_library_reverted(db_session, biblio):
    from itcj2.apps.titulatec.services.library_clearance_service import (
        LibraryClearanceService,
    )
    from itcj2.core.utils.timezone import db_now

    sin_cargo = biblio(donation=Decimal("0.00"))
    LibraryClearanceService.register(db_session, sin_cargo.fila.id,
                                     sin_cargo.biblioteca.id,
                                     debt_amount=Decimal("0"), note=None)
    LibraryClearanceService.revert_clearance(db_session, sin_cargo.fila.id,
                                             sin_cargo.biblioteca.id, "Sí debía un libro")

    previa = biblio()
    LibraryClearanceService.register_prior(db_session, previa.fila.id,
                                           previa.biblioteca.id,
                                           issued_on=db_now().date(), note=None,
                                           by="library")
    LibraryClearanceService.undo_prior(db_session, previa.fila.id, previa.biblioteca.id,
                                       "No era de este año")

    assert _filas_biblioteca(db_session, sin_cargo.proc.id)[-1] == (
        "library_reverted", {"reason": "Sí debía un libro", "to_status": "pending"},
        None, None)
    assert _filas_biblioteca(db_session, previa.proc.id)[-1] == (
        "library_reverted", {"reason": "No era de este año", "to_status": "pending"},
        None, None)


def _con_adeudo_observado(db_session, esc):
    """Biblioteca observa CON ADEUDO (spec 2026-10-07 §2): $300 + la donación."""
    from itcj2.apps.titulatec.services.library_clearance_service import (
        LibraryClearanceService,
    )
    LibraryClearanceService.observe(db_session, esc.fila.id, reason="Entregar libro",
                                    actor_id=esc.biblioteca.id, kind="with_debt",
                                    debt_amount=Decimal("300.00"))


def test_cobro_retenido_no_encola_liberado(db_session, biblio):
    """Rama sin su correo del catálogo (`RAMAS_SIN_CORREO`): el cobro de una
    observación con adeudo escribe `library_payment_registered` pero NO
    libera; encola `library_payment_held`, nunca `library_cleared`."""
    from itcj2.apps.titulatec.services.library_clearance_service import (
        LibraryClearanceService,
    )

    esc = biblio()
    _con_adeudo_observado(db_session, esc)
    LibraryClearanceService.register_payment(db_session, esc.fila.id, esc.caja.id,
                                             receipt_number="R-1")

    assert [k for k, *_ in _filas_biblioteca(db_session, esc.proc.id)] == [
        "library_observed", "library_payment_held"]
    assert _filas_biblioteca(db_session, esc.proc.id)[-1] == (
        "library_payment_held", {"total": "1100.00", "receipt": "R-1"}, None, None)


def test_revertir_pago_retenido_no_encola(db_session, biblio):
    """Rama sin su correo del catálogo (`RAMAS_SIN_CORREO`): revertir un pago
    RETENIDO no encola `library_reverted` (nunca se liberó: «se revirtió tu
    Constancia» sería falso); queda solo el aviso in-app."""
    from itcj2.apps.titulatec.services.library_clearance_service import (
        LibraryClearanceService,
    )

    esc = biblio()
    _con_adeudo_observado(db_session, esc)
    LibraryClearanceService.register_payment(db_session, esc.fila.id, esc.caja.id)
    antes = _filas_biblioteca(db_session, esc.proc.id)
    LibraryClearanceService.revert_payment(db_session, esc.fila.id, esc.caja.id,
                                           "Se cobró a otra persona")

    assert _filas_biblioteca(db_session, esc.proc.id) == antes
    assert len(_avisos(db_session, esc.proc.student_id, "LIBRARY_PAYMENT_REVERTED")) == 1


def test_si_el_commit_del_cobro_falla_no_queda_correo(db_session, biblio, monkeypatch):
    """Review Focus 4 en Caja: el correo vive en la transacción del cobro. Si el
    COMMIT falla, se va con él (y el cobro también)."""
    from itcj2.apps.titulatec.models import EmailOutbox, LibraryClearance
    from itcj2.apps.titulatec.services.library_clearance_service import (
        LibraryClearanceService,
    )

    esc = biblio()
    LibraryClearanceService.register(db_session, esc.fila.id, esc.biblioteca.id,
                                     debt_amount=Decimal("300.00"), note=None)
    pid, cid, caja = esc.proc.id, esc.fila.id, esc.caja.id
    db_session.commit()

    def _commit_que_falla():
        db_session.flush()
        raise RuntimeError("se cayó el COMMIT")

    monkeypatch.setattr(db_session, "commit", _commit_que_falla)
    with pytest.raises(RuntimeError):
        LibraryClearanceService.register_payment(db_session, cid, caja)

    # La fila SÍ se escribió, en la MISMA transacción que el cobro.
    assert db_session.query(EmailOutbox).filter_by(
        process_id=pid, kind="library_cleared").count() == 1

    db_session.rollback()

    assert db_session.query(EmailOutbox).filter_by(
        process_id=pid, kind="library_cleared").count() == 0
    assert db_session.get(LibraryClearance, cid).status == "awaiting_payment"


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
