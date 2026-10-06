"""Set de documentos de la fase 1 por perfil (spec 2026-09-30-titulatec-
posgrado-design.md §4.4, regla R-G §5, invariantes §6; Tarea 3).

Un egresado de POSGRADO (maestría o doctorado, `TrackService.TRACK_POSGRADO`)
sube 7 documentos en la fase 1 -- los 3 de siempre (`DocumentService.
BASE_INITIAL_DOCS`) más 4 extras (`DocumentService.POSGRADO_EXTRA_DOCS`):
cédula profesional, título, oficios de autorización de la DEPI y el
comprobante de e.firma/cita SAT. Licenciatura no cambia: sigue en 3.

Lo que se fija aquí:

1. `DocumentService.initial_doc_types` -- el set por perfil, único punto de
   verdad (invariante 1). `INITIAL_DOC_TYPES` (el literal viejo, sin perfil)
   ya no existe.
2. `initial_docs_summary`/`initial_docs_all_approved`/`sync_initial_phase`
   consumen ese set cuando no se les pasa `codes` explícito.
3. R-G (invariante 8, deriva de D9): un proceso de posgrado cuya fase 1 YA
   CERRÓ no se regresa por los extras que le falten -- los FALTANTES dejan de
   contar, pero uno que sí tiene fila debe estar aprobado igual que cualquier
   otro. Mientras la fase 1 sigue abierta se exigen los 7, sin excepción.
4. Los consumidores de servicio (`AppointmentService`, `MailReminders`)
   resuelven el set POR PROCESO, en lote (`initial_doc_types_by_process`), no
   uno fijo.
5. `storage.document_label` conoce los 4 códigos nuevos.

Lo que NO se toca aquí (Tareas 4/5): los literales `_INITIAL_DOC_TYPES` de
`pages/{documents,student,appointments,admin}.py` -- siguen en 3 hasta que esas
tareas los hagan consumir este servicio.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

import itcj2.models  # noqa: F401
from tests.fastapi.titulatec.conftest import INITIAL_DOC_TYPES, POSGRADO_DOC_TYPES


# ---------------------------------------------------------------------------
# Fixtures locales
# ---------------------------------------------------------------------------
@pytest.fixture()
def posgrado(seed_phase_defs, seed_document_types, make_program):
    """Siembra fases + los 7 tipos de documento (3 base + 4 extras) y
    devuelve una carrera de posgrado (`level="maestria"`)."""
    seed_phase_defs()
    seed_document_types(types=INITIAL_DOC_TYPES + POSGRADO_DOC_TYPES)
    return make_program("Maestria de Prueba DocumentService", level="maestria")


def _fase(db, process_id, numero):
    from itcj2.apps.titulatec.models import ProcessPhase

    return (db.query(ProcessPhase)
            .filter_by(process_id=process_id, phase_number=numero).one())


# ---------------------------------------------------------------------------
# 1. El set por perfil (`initial_doc_types`)
# ---------------------------------------------------------------------------
def test_initial_doc_types_licenciatura_son_los_3_de_siempre():
    from itcj2.apps.titulatec.services.document_service import DocumentService
    from itcj2.apps.titulatec.services.track_service import TRACK_LICENCIATURA

    assert DocumentService.initial_doc_types(TRACK_LICENCIATURA) == (
        "birth_certificate", "high_school_cert", "curp")


def test_initial_doc_types_posgrado_son_los_3_mas_los_4_extras_en_orden():
    from itcj2.apps.titulatec.services.document_service import DocumentService
    from itcj2.apps.titulatec.services.track_service import TRACK_POSGRADO

    assert DocumentService.initial_doc_types(TRACK_POSGRADO) == (
        "birth_certificate", "high_school_cert", "curp",
        "professional_license", "degree_title", "postgrad_authorization", "efirma_sat",
    )


# ---------------------------------------------------------------------------
# 2. `initial_docs_summary` -- total y nombres del catálogo
# ---------------------------------------------------------------------------
def test_initial_docs_summary_posgrado_total_7_y_faltan_4(
        db_session, posgrado, make_student, make_process, make_document):
    from itcj2.apps.titulatec.services.document_service import DocumentService

    proc = make_process(make_student(), program=posgrado, current_phase=1)
    for code in DocumentService.BASE_INITIAL_DOCS:
        make_document(proc, type_code=code)

    summary = DocumentService.initial_docs_summary(db_session, proc.id)

    assert summary["total"] == 7
    assert summary["counts"]["missing"] == 4
    nombres = {item["code"]: item["name"] for item in summary["items"]}
    assert nombres["professional_license"] == "Cédula profesional"
    assert nombres["degree_title"] == "Título"
    assert nombres["postgrad_authorization"] == (
        "Oficios de autorización de la División de Estudios de Posgrado")
    assert nombres["efirma_sat"] == "Comprobante de e.firma o cita con el SAT"


# ---------------------------------------------------------------------------
# 3. `initial_docs_all_approved` -- exige los 7 en posgrado, 3 en licenciatura
# ---------------------------------------------------------------------------
def test_all_approved_posgrado_con_solo_los_3_base_es_falso(
        db_session, posgrado, make_student, make_process, make_document):
    from itcj2.apps.titulatec.services.document_service import DocumentService

    proc = make_process(make_student(), program=posgrado, current_phase=1)
    for code in DocumentService.BASE_INITIAL_DOCS:
        make_document(proc, type_code=code, review_status="approved")

    assert DocumentService.initial_docs_all_approved(db_session, proc.id) is False


def test_all_approved_posgrado_con_los_7_es_verdadero(
        db_session, posgrado, make_student, make_process, make_document):
    from itcj2.apps.titulatec.services.document_service import DocumentService

    proc = make_process(make_student(), program=posgrado, current_phase=1)
    for code in DocumentService.BASE_INITIAL_DOCS + DocumentService.POSGRADO_EXTRA_DOCS:
        make_document(proc, type_code=code, review_status="approved")

    assert DocumentService.initial_docs_all_approved(db_session, proc.id) is True


def test_all_approved_licenciatura_sigue_exigiendo_solo_3(
        db_session, seed_phase_defs, seed_document_types, make_student, make_process,
        make_document):
    from itcj2.apps.titulatec.services.document_service import DocumentService

    seed_phase_defs()
    seed_document_types()
    proc = make_process(make_student(), current_phase=1)   # sin carrera -> licenciatura
    for code in DocumentService.BASE_INITIAL_DOCS:
        make_document(proc, type_code=code, review_status="approved")

    assert DocumentService.initial_docs_all_approved(db_session, proc.id) is True


# ---------------------------------------------------------------------------
# 4. R-G: una fase 1 ya cerrada no se regresa por extras FALTANTES (D9, §5)
# ---------------------------------------------------------------------------
def test_r_g_fase_1_cerrada_perdona_los_extras_faltantes(
        db_session, posgrado, make_student, make_process, make_document):
    from itcj2.apps.titulatec.services.document_service import DocumentService

    proc = make_process(make_student(), program=posgrado, current_phase=2)
    for code in DocumentService.BASE_INITIAL_DOCS:
        make_document(proc, type_code=code, review_status="approved")

    assert DocumentService.initial_docs_all_approved(db_session, proc.id) is True


def test_r_g_no_perdona_un_extra_que_existe_y_esta_rechazado(
        db_session, posgrado, make_student, make_process, make_document):
    from itcj2.apps.titulatec.services.document_service import DocumentService

    proc = make_process(make_student(), program=posgrado, current_phase=2)
    for code in DocumentService.BASE_INITIAL_DOCS:
        make_document(proc, type_code=code, review_status="approved")
    make_document(proc, type_code="professional_license", review_status="rejected")

    assert DocumentService.initial_docs_all_approved(db_session, proc.id) is False


# ---------------------------------------------------------------------------
# 5. `sync_initial_phase` cuenta contra `initial_doc_types_for`
# ---------------------------------------------------------------------------
def test_sync_initial_phase_posgrado_con_3_base_no_pasa_a_revision(
        db_session, posgrado, make_student, make_process, make_document):
    from itcj2.apps.titulatec.services.document_service import DocumentService

    proc = make_process(make_student(), program=posgrado, current_phase=1)
    for code in DocumentService.BASE_INITIAL_DOCS:
        make_document(proc, type_code=code)

    resultado = DocumentService.sync_initial_phase(db_session, proc)

    assert resultado is None
    assert _fase(db_session, proc.id, 1).status == "in_progress"


def test_sync_initial_phase_posgrado_con_los_7_pasa_a_revision(
        db_session, posgrado, make_student, make_process, make_document):
    from itcj2.apps.titulatec.services.document_service import DocumentService

    proc = make_process(make_student(), program=posgrado, current_phase=1)
    for code in DocumentService.BASE_INITIAL_DOCS + DocumentService.POSGRADO_EXTRA_DOCS:
        make_document(proc, type_code=code)

    resultado = DocumentService.sync_initial_phase(db_session, proc)

    assert resultado == "in_review"
    assert _fase(db_session, proc.id, 1).status == "in_review"


def test_sync_initial_phase_posgrado_en_revision_con_solo_3_regresa_a_en_curso(
        db_session, posgrado, make_student, make_process, make_document):
    from itcj2.apps.titulatec.services.document_service import DocumentService

    proc = make_process(make_student(), program=posgrado, current_phase=1)
    for code in DocumentService.BASE_INITIAL_DOCS:
        make_document(proc, type_code=code)
    fase1 = _fase(db_session, proc.id, 1)
    fase1.status = "in_review"
    db_session.flush()

    resultado = DocumentService.sync_initial_phase(db_session, proc)

    assert resultado == "in_progress"
    assert fase1.status == "in_progress"


def test_sync_initial_phase_nunca_toca_una_fase_aprobada_en_posgrado(
        db_session, posgrado, make_student, make_process, make_document):
    from itcj2.apps.titulatec.services.document_service import DocumentService

    proc = make_process(make_student(), program=posgrado, current_phase=1)
    for code in DocumentService.BASE_INITIAL_DOCS:
        make_document(proc, type_code=code)
    fase1 = _fase(db_session, proc.id, 1)
    fase1.status = "approved"
    db_session.flush()

    resultado = DocumentService.sync_initial_phase(db_session, proc)

    assert resultado is None
    assert fase1.status == "approved"


# ---------------------------------------------------------------------------
# 6. Candidatos de cotejo (`AppointmentService`): el set es el DEL PROCESO
# ---------------------------------------------------------------------------
def test_candidatos_de_cotejo_en_posgrado_exigen_los_7_mientras_la_fase_1_siga_abierta(
        db_session, posgrado, make_student, make_cohort, make_process, make_document,
        make_survey_review):
    from itcj2.apps.titulatec.services.appointment_service import AppointmentService
    from itcj2.apps.titulatec.services.document_service import DocumentService

    cohort = make_cohort()

    # Fase 1 abierta con solo los 3 base aprobados: le faltan 4 y R-G no
    # aplica (no ha pasado la fase) -> no es candidato.
    en_fase_1 = make_process(make_student(), cohort=cohort, program=posgrado,
                             current_phase=1)
    for code in DocumentService.BASE_INITIAL_DOCS:
        make_document(en_fase_1, type_code=code, review_status="approved")
    make_survey_review(en_fase_1, status="approved")

    # Fase 2 con los 7 aprobados y encuesta liberada -> SI es candidato.
    listo = make_process(make_student(), cohort=cohort, program=posgrado, current_phase=2)
    for code in DocumentService.BASE_INITIAL_DOCS + DocumentService.POSGRADO_EXTRA_DOCS:
        make_document(listo, type_code=code, review_status="approved")
    make_survey_review(listo, status="approved")

    pendientes = {p.id for p in AppointmentService.list_pending_processes(db_session)}

    assert listo.id in pendientes
    assert en_fase_1.id not in pendientes


# ---------------------------------------------------------------------------
# 7. `MailReminders._documentos` nombra los extras de posgrado
# ---------------------------------------------------------------------------
@pytest.fixture()
def _cadencia_docs(monkeypatch):
    """Cadencia determinista para que el primer barrido siempre toque
    (mismos valores que `test_mail_reminders.py::_correo_encendido`)."""
    from itcj2.apps.titulatec.services.student_mail import MailSettings

    for nombre, valor in (("first_days", 3), ("every_days", 7), ("max_reminders", 3)):
        monkeypatch.setattr(MailSettings, nombre, staticmethod(lambda v=valor: v))


def test_documentos_reminder_posgrado_nombra_la_cedula_profesional(
        db_session, _cadencia_docs, posgrado, make_student, make_process):
    from itcj2.apps.titulatec.services.mail_reminders import MailReminders
    from itcj2.core.models.notification import Notification

    now = datetime(2001, 2, 3, 9, 0)
    proc = make_process(make_student(), program=posgrado, current_phase=1)
    fase1 = _fase(db_session, proc.id, 1)
    fase1.started_at = now - timedelta(days=4)
    db_session.flush()

    n = MailReminders._documentos(db_session, now)

    assert n == 1
    aviso = (db_session.query(Notification)
             .filter_by(user_id=proc.student_id, app_name="titulatec",
                        type="DOCUMENTS_REMINDER")
             .one())
    assert "Cédula profesional" in aviso.body


def test_documentos_reminder_licenciatura_no_nombra_extras_de_posgrado(
        db_session, _cadencia_docs, seed_phase_defs, seed_document_types, make_student,
        make_process):
    from itcj2.apps.titulatec.services.mail_reminders import MailReminders
    from itcj2.core.models.notification import Notification

    seed_phase_defs()
    seed_document_types()
    now = datetime(2001, 2, 3, 9, 0)
    proc = make_process(make_student(), current_phase=1)   # sin carrera -> licenciatura
    fase1 = _fase(db_session, proc.id, 1)
    fase1.started_at = now - timedelta(days=4)
    db_session.flush()

    n = MailReminders._documentos(db_session, now)

    assert n == 1
    aviso = (db_session.query(Notification)
             .filter_by(user_id=proc.student_id, app_name="titulatec",
                        type="DOCUMENTS_REMINDER")
             .one())
    assert "Cédula profesional" not in aviso.body
    assert "Acta de nacimiento" in aviso.body


# ---------------------------------------------------------------------------
# 8. `storage.document_label` de los 4 extras
# ---------------------------------------------------------------------------
def test_document_label_de_los_4_extras_de_posgrado():
    from itcj2.apps.titulatec.utils import storage

    assert storage.document_label("professional_license") == "CEDULA"
    assert storage.document_label("degree_title") == "TITULO"
    assert storage.document_label("postgrad_authorization") == "OFICIOS"
    assert storage.document_label("efirma_sat") == "EFIRMA"
