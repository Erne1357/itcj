"""`DocumentService.sync_initial_phase`: la fase 1 pasa sola a revisión al
completar los 3 documentos iniciales (Tarea 1, 2026-09-28, plan
titulatec-correos-notificaciones).

Sustituye a `POST /student/phase/1/submit`, que ya NO EXISTE: subir el tercer
documento (o borrar uno de una fase que ya estaba en revisión) dispara
`sync_initial_phase` desde `DocumentService.save`/`delete`, sin acción
explícita del alumno -- no hay botón "Enviar a revisión" que probar.

Contrato completo en el docstring de `DocumentService.sync_initial_phase`
(`services/document_service.py`) y en
`docs/flows/phase1_student_upload_initial_docs.md`.
"""
from __future__ import annotations

import pytest

# Permisos REALES del rol `student`/`graduate` que esta suite necesita (ver
# `STUDENT_PERMS` de conftest.py) más el de borrar, que ese set no trae.
STUDENT_PERMS = (
    "titulatec.dashboard.student",
    "titulatec.document.api.read.own",
    "titulatec.document.api.upload.own",
    "titulatec.document.api.delete.own",
)

# Catálogo con un tipo de OTRA fase (anexo_iii, fase 6), para probar que
# guardar un documento que no es de `initial_docs` no dispara el sync -- ni
# siquiera con el proceso parado en la fase 1.
DOC_TYPES_OTRA_FASE = (
    ("birth_certificate", "Acta de nacimiento", 1),
    ("high_school_cert", "Certificado de bachillerato", 1),
    ("curp", "CURP certificada", 1),
    ("anexo_iii", "Anexo III firmado", 6),
)

PDF = ("documento.pdf", b"%PDF-1.4 documento de prueba", "application/pdf")


def _phase1(db_session, process_id) -> str:
    """Estado de `ProcessPhase(1)`, o 'pending' si la fila no existe todavía."""
    from itcj2.apps.titulatec.models import ProcessPhase
    db_session.expire_all()
    ph = (db_session.query(ProcessPhase)
          .filter_by(process_id=process_id, phase_number=1).first())
    return ph.status if ph else "pending"


@pytest.fixture()
def esc(db_session, seed_phase_defs, seed_document_types, make_cohort, make_student,
        make_process, tmp_path, monkeypatch):
    """Alumno con proceso en fase 1 (los 3 documentos iniciales), listo para
    subir/borrar por HTTP. Los archivos SÍ se escriben en disco (bajo
    `tmp_path`): `delete()` pasa por `storage.delete_document_file`.
    """
    def _build(current_phase=1, status="active"):
        monkeypatch.setattr("itcj2.apps.titulatec.utils.storage._base", lambda: tmp_path)
        seed_phase_defs()
        seed_document_types()
        student = make_student(perm_codes=STUDENT_PERMS)
        proc = make_process(student, cohort=make_cohort(),
                            current_phase=current_phase, status=status)
        return student, proc
    return _build


# ===========================================================================
# 1. Subir el documento que falta sincroniza la fase
# ===========================================================================
class TestSubirSincroniza:
    def test_subir_el_tercero_pone_la_fase_en_revision(self, esc, client_as, db_session,
                                                        make_document):
        student, proc = esc()
        make_document(proc, type_code="birth_certificate")
        make_document(proc, type_code="high_school_cert")
        assert _phase1(db_session, proc.id) == "in_progress"

        resp = client_as(student).post("/titulatec/student/documents/curp",
                                       files={"archivo": PDF})

        assert resp.status_code == 200, resp.text[:300]
        assert _phase1(db_session, proc.id) == "in_review"

    def test_dos_de_tres_sigue_en_curso(self, esc, client_as, db_session, make_document):
        student, proc = esc()
        make_document(proc, type_code="birth_certificate")

        resp = client_as(student).post("/titulatec/student/documents/curp",
                                       files={"archivo": PDF})

        assert resp.status_code == 200, resp.text[:300]
        assert _phase1(db_session, proc.id) == "in_progress"


# ===========================================================================
# 2. Borrar uno de los 3 regresa la fase a "en curso"
# ===========================================================================
class TestBorrarDescompletaLaFase:
    def test_borrar_uno_regresa_a_en_curso(self, esc, client_as, db_session):
        student, proc = esc()
        cli = client_as(student)
        for code in ("birth_certificate", "high_school_cert", "curp"):
            resp = cli.post(f"/titulatec/student/documents/{code}", files={"archivo": PDF})
            assert resp.status_code == 200, resp.text[:300]
        assert _phase1(db_session, proc.id) == "in_review"

        resp = cli.delete("/titulatec/student/documents/curp")

        assert resp.status_code == 200, resp.text[:300]
        assert _phase1(db_session, proc.id) == "in_progress"


# ===========================================================================
# 3. Una fase rechazada se completa y vuelve a revisión (reenvío = válido)
# ===========================================================================
class TestFaseRechazada:
    def test_fase_rechazada_vuelve_a_revision_al_completar(self, esc, client_as, db_session,
                                                            make_document):
        from itcj2.apps.titulatec.models import ProcessPhase
        student, proc = esc()
        make_document(proc, type_code="birth_certificate")
        make_document(proc, type_code="high_school_cert")
        ph = (db_session.query(ProcessPhase)
              .filter_by(process_id=proc.id, phase_number=1).one())
        ph.status = "rejected"
        db_session.flush()

        resp = client_as(student).post("/titulatec/student/documents/curp",
                                       files={"archivo": PDF})

        assert resp.status_code == 200, resp.text[:300]
        assert _phase1(db_session, proc.id) == "in_review"


# ===========================================================================
# 4. Lo que el sync NUNCA toca, visto directo desde el service
# ===========================================================================
class TestNuncaTocaAprobadaNiUnProcesoInactivo:
    def test_nunca_toca_una_fase_aprobada(self, db_session, seed_phase_defs,
                                          seed_document_types, make_cohort, make_student,
                                          make_process):
        from itcj2.apps.titulatec.services.document_service import DocumentService
        seed_phase_defs()
        seed_document_types()
        student = make_student()
        proc = make_process(student, cohort=make_cohort(), current_phase=2)
        assert _phase1(db_session, proc.id) == "approved"

        resultado = DocumentService.sync_initial_phase(db_session, proc)

        assert resultado is None
        assert _phase1(db_session, proc.id) == "approved"

    def test_proceso_en_pausa_no_se_toca(self, db_session, seed_phase_defs,
                                         seed_document_types, make_cohort, make_student,
                                         make_process, make_document):
        from itcj2.apps.titulatec.services.document_service import DocumentService
        seed_phase_defs()
        seed_document_types()
        student = make_student()
        proc = make_process(student, cohort=make_cohort(), current_phase=1, status="on_hold")
        for code in ("birth_certificate", "high_school_cert", "curp"):
            make_document(proc, type_code=code)
        assert _phase1(db_session, proc.id) == "in_progress"

        resultado = DocumentService.sync_initial_phase(db_session, proc)

        assert resultado is None
        assert _phase1(db_session, proc.id) == "in_progress"


# ===========================================================================
# 5. Un documento de OTRA fase no dispara el sync
# ===========================================================================
class TestDocumentoDeOtraFase:
    def test_documento_de_otra_fase_no_toca_la_fase_1(self, db_session, seed_phase_defs,
                                                       seed_document_types, make_cohort,
                                                       make_student, make_process, tmp_path,
                                                       monkeypatch):
        """`anexo_iii` es de la fase 6: la ruta HTTP ya bloquea esta subida con
        la guarda de fase de `pages/student.py` (`dtype.phase_number=6 !=
        current_phase=1`), así que la única forma de probar que `save()` no
        dispara el sync para OTRA fase es llamando al service directo,
        saltándose esa guarda a propósito."""
        from itcj2.apps.titulatec.services.document_service import DocumentService
        monkeypatch.setattr("itcj2.apps.titulatec.utils.storage._base", lambda: tmp_path)
        seed_phase_defs()
        seed_document_types(DOC_TYPES_OTRA_FASE)
        student = make_student()
        proc = make_process(student, cohort=make_cohort(), current_phase=1)
        assert _phase1(db_session, proc.id) == "in_progress"

        DocumentService.save(db_session, proc, "anexo_iii",
                             raw=b"%PDF-1.4 anexo", original_name="anexo.pdf",
                             content_type="application/pdf",
                             uploaded_by_id=student.id)

        assert _phase1(db_session, proc.id) == "in_progress"


# ===========================================================================
# 6. La ruta y el botón viejos desaparecieron
# ===========================================================================
class TestRutaYBotonRetirados:
    def test_la_ruta_de_enviar_ya_no_existe(self, esc, client_as):
        student, _proc = esc()

        resp = client_as(student).post("/titulatec/student/phase/1/submit")

        assert resp.status_code in (404, 405), resp.text[:300]

    def test_la_pagina_ya_no_ofrece_enviar_a_revision(self, esc, client_as, db_session):
        student, proc = esc()
        cli = client_as(student)
        for code in ("birth_certificate", "high_school_cert", "curp"):
            resp = cli.post(f"/titulatec/student/documents/{code}", files={"archivo": PDF})
            assert resp.status_code == 200, resp.text[:300]
        assert _phase1(db_session, proc.id) == "in_review"

        resp = cli.get("/titulatec/student/documents")

        assert resp.status_code == 200, resp.text[:300]
        assert "Enviar a revisión" not in resp.text
        assert "phase/1/submit" not in resp.text
