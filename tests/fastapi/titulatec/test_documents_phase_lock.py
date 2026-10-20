"""Dictamen congelado tras aprobar la fase 1 (2026-10-04, decisión del usuario).

Antes, rechazar un documento de la fase 1 con el proceso ya en la fase 2 dejaba
al alumno trabado: el documento quedaba `rejected`, el proceso NO regresaba de
fase y el alumno no podía volver a subirlo (`assert_student_can_act` cierra las
fases anteriores). Ahora:

- `DocumentService.review` rechaza con `PHASE_CLOSED_MSG` el RECHAZO, y
  cualquier cambio sobre uno ya `approved`, cuando la fase del documento ya
  pasó. Aprobar uno pendiente sigue permitido (solo destraba).
- La bandeja marca `phase_closed` y, en la fase en curso, `closes_phase` en el
  único documento que falta: ese es el que lleva la re-confirmación.
"""
from __future__ import annotations

import unicodedata

import pytest

from itcj2.apps.titulatec.pages.documents import _annotate_phase_lock
from itcj2.apps.titulatec.services.document_service import DocumentService


@pytest.fixture()
def revisor(make_user):
    return make_user(first_name="REVISOR", last_name="DE PRUEBA")


# ───────────────────────────── guarda del service ─────────────────────────────

class TestGuardaDelService:
    def test_no_se_rechaza_un_documento_con_la_fase_ya_aprobada(
        self, db_session, seed_phase_defs, seed_document_types, make_student,
        make_process, make_document, revisor,
    ):
        seed_phase_defs()
        seed_document_types()
        process = make_process(make_student(), current_phase=2)
        doc = make_document(process, type_code="curp", phase_number=1,
                            review_status="approved")

        with pytest.raises(ValueError) as exc:
            DocumentService.review(db_session, process.id, "curp",
                                   status="rejected", note="Ilegible",
                                   reviewer_id=revisor.id)

        assert str(exc.value) == DocumentService.PHASE_CLOSED_MSG
        assert doc.review_status == "approved", "debe bloquear ANTES de escribir"

    def test_tampoco_se_rechaza_uno_pendiente_con_la_fase_ya_aprobada(
        self, db_session, seed_phase_defs, seed_document_types, make_student,
        make_process, make_document, revisor,
    ):
        """El alumno tampoco podría re-subirlo: mismo callejón sin salida."""
        seed_phase_defs()
        seed_document_types()
        process = make_process(make_student(), current_phase=2)
        doc = make_document(process, type_code="curp", phase_number=1,
                            review_status="pending")

        with pytest.raises(ValueError):
            DocumentService.review(db_session, process.id, "curp",
                                   status="rejected", note="Ilegible",
                                   reviewer_id=revisor.id)
        assert doc.review_status == "pending"

    def test_un_aprobado_no_se_vuelve_a_dictaminar_con_la_fase_cerrada(
        self, db_session, seed_phase_defs, seed_document_types, make_student,
        make_process, make_document, revisor,
    ):
        seed_phase_defs()
        seed_document_types()
        process = make_process(make_student(), current_phase=2)
        make_document(process, type_code="curp", phase_number=1,
                      review_status="approved")

        with pytest.raises(ValueError):
            DocumentService.review(db_session, process.id, "curp",
                                   status="approved", note=None,
                                   reviewer_id=revisor.id)

    def test_aprobar_tarde_uno_pendiente_sigue_permitido(
        self, db_session, seed_phase_defs, seed_document_types, make_student,
        make_process, make_document, revisor,
    ):
        seed_phase_defs()
        seed_document_types()
        process = make_process(make_student(), current_phase=2)
        doc = make_document(process, type_code="curp", phase_number=1,
                            review_status="pending")

        assert DocumentService.review(db_session, process.id, "curp",
                                      status="approved", note=None,
                                      reviewer_id=revisor.id) is True
        assert doc.review_status == "approved"

    def test_en_la_fase_en_curso_se_sigue_rechazando(
        self, db_session, seed_phase_defs, seed_document_types, make_student,
        make_process, make_document, revisor,
    ):
        seed_phase_defs()
        seed_document_types()
        process = make_process(make_student(), current_phase=1)
        doc = make_document(process, type_code="curp", phase_number=1,
                            review_status="approved")

        assert DocumentService.review(db_session, process.id, "curp",
                                      status="rejected", note="Ilegible",
                                      reviewer_id=revisor.id) is True
        assert doc.review_status == "rejected"

    def test_el_mensaje_es_ascii_puro(self):
        """Viaja por `X-Tt-Error` (latin-1 en Starlette, UTF-8 en el TestClient)."""
        msg = DocumentService.PHASE_CLOSED_MSG
        msg.encode("latin-1")
        assert msg == unicodedata.normalize("NFKD", msg).encode("ascii", "ignore").decode()


# ───────────────────────────── marcas de la bandeja ───────────────────────────

def _detail(current_phase, statuses):
    return {
        "current_phase": current_phase,
        "docs": [{"type_code": f"d{i}", "status": s, "has_file": s != "missing"}
                 for i, s in enumerate(statuses)],
    }


class TestMarcasDeLaBandeja:
    def test_el_ultimo_por_aprobar_cierra_la_fase(self, db_session, seed_phase_defs):
        seed_phase_defs()
        detail = _detail(1, ["approved", "approved", "pending"])

        _annotate_phase_lock(db_session, detail)

        assert detail["phase_closed"] is False
        assert [d["closes_phase"] for d in detail["docs"]] == [False, False, True]

    def test_con_dos_por_aprobar_ninguno_cierra(self, db_session, seed_phase_defs):
        seed_phase_defs()
        detail = _detail(1, ["approved", "rejected", "pending"])

        _annotate_phase_lock(db_session, detail)

        assert not any(d["closes_phase"] for d in detail["docs"])

    def test_si_el_que_falta_no_se_ha_subido_nadie_cierra(self, db_session, seed_phase_defs):
        seed_phase_defs()
        detail = _detail(1, ["approved", "approved", "missing"])

        _annotate_phase_lock(db_session, detail)

        assert not any(d["closes_phase"] for d in detail["docs"])

    def test_con_la_fase_aprobada_queda_cerrada_y_nada_cierra(self, db_session, seed_phase_defs):
        seed_phase_defs()
        detail = _detail(2, ["approved", "approved", "pending"])

        _annotate_phase_lock(db_session, detail)

        assert detail["phase_closed"] is True
        assert not any(d["closes_phase"] for d in detail["docs"])


# ───────────────────────────── por la ruta real ───────────────────────────────

REVIEW_PERMS = ("titulatec.document.api.approve", "titulatec.document.api.reject")


def _escenario(seed_phase_defs, seed_document_types, make_cohort, make_student,
               make_process, make_document, *, current_phase, statuses):
    seed_phase_defs()
    seed_document_types()
    proc = make_process(make_student(), cohort=make_cohort(), current_phase=current_phase)
    for code, st in zip(("birth_certificate", "high_school_cert", "curp"), statuses):
        make_document(proc, type_code=code, review_status=st)
    return proc


def test_la_bandeja_marca_el_ultimo_y_ofrece_rechazar(
        db_session, seed_phase_defs, seed_document_types, make_cohort, make_student,
        make_process, make_document, make_head, client_as):
    from tests.fastapi.titulatec.conftest import HEAD_PERMS

    proc = _escenario(seed_phase_defs, seed_document_types, make_cohort, make_student,
                      make_process, make_document, current_phase=1,
                      statuses=("approved", "approved", "pending"))
    jefa = make_head(perm_codes=HEAD_PERMS + REVIEW_PERMS)

    html = client_as(jefa).get(
        "/titulatec/admin/documents/body?selected=%d" % proc.id).text

    assert html.count('data-closes="1"') == 1
    assert 'data-phase-closed="0"' in html
    assert 'id="tt-inline-reject"' in html
    assert 'id="tt-review-locked"' not in html


def test_con_la_fase_aprobada_la_bandeja_no_ofrece_rechazar_y_la_ruta_lo_niega(
        db_session, seed_phase_defs, seed_document_types, make_cohort, make_student,
        make_process, make_document, make_head, client_as):
    from itcj2.apps.titulatec.models import Document
    from tests.fastapi.titulatec.conftest import HEAD_PERMS

    proc = _escenario(seed_phase_defs, seed_document_types, make_cohort, make_student,
                      make_process, make_document, current_phase=2,
                      statuses=("approved", "approved", "approved"))
    jefa = make_head(perm_codes=HEAD_PERMS + REVIEW_PERMS)
    client = client_as(jefa)

    html = client.get("/titulatec/admin/documents/body?selected=%d" % proc.id).text
    assert 'data-phase-closed="1"' in html
    assert 'id="tt-review-locked"' in html
    assert 'id="tt-inline-reject"' not in html
    assert 'data-closes="1"' not in html

    resp = client.post("/titulatec/admin/documents/%d/document/review" % proc.id,
                       data={"type_code": "curp", "action": "reject", "note": "Ilegible"})
    assert resp.status_code == 400
    assert resp.headers["X-Tt-Error"] == DocumentService.PHASE_CLOSED_MSG
    db_session.expire_all()
    doc = db_session.query(Document).filter_by(process_id=proc.id, type_code="curp").one()
    assert doc.review_status == "approved"
