"""Vista del alumno con el set de posgrado + guarda de subida por perfil
(spec 2026-09-30-titulatec-posgrado-design.md §4.4, §5, §6; Tarea 5).

`DocumentService`/`TrackService` (Tareas 2-3) ya saben que un egresado de
POSGRADO sube 7 documentos en la fase 1 (los 3 de siempre + 4 extras) en vez
de 3, y las vistas admin ya consumen ese set (Tarea 4). Lo que fija este
archivo es el lado del ALUMNO:

1. `GET /student/documents` pinta el set del PROPIO proceso, en orden, con la
   ayuda de cada uno de los 4 extras (`DocumentService.INITIAL_DOC_HINTS`).
2. El hueco cerrado (spec §4.4, invariante 4): `POST/DELETE
   /student/documents/{type_code}` con un código de fase 1 que NO está en el
   set del proceso -> 400 + `X-Tt-Error`, SIN fila `Document` y SIN archivo en
   disco. Aplica en las dos direcciones (licenciatura sube un extra de
   posgrado; cualquiera sube un tipo de fase 1 ajeno a las dos listas, p. ej.
   `egel_proof`) y a las dos rutas (subir y borrar).
3. Los textos dinámicos: el acordeón del dashboard (`_PHASE_INFO`/`_phase_info`)
   y el aviso de pie (`_docs_status.html`) dicen "7" en posgrado y "3" en
   licenciatura -- con licenciatura el HTML queda BYTE A BYTE como antes
   (Controller ruling R1): `documents.html:6` sigue diciendo EXACTAMENTE
   "Fase 01 · Acta · Certificado · CURP".

Lo que NO se toca aquí (Tarea 4, ya hecha): `pages/documents.py`,
`pages/appointments.py`, `pages/admin.py` y sus plantillas -- llevan su propio
archivo, `test_documents_posgrado_admin.py`.
"""
from __future__ import annotations

from urllib.parse import unquote

import pytest

from tests.fastapi.titulatec.conftest import INITIAL_DOC_TYPES, POSGRADO_DOC_TYPES

# Tipo de fase 1 que NO aplica a NINGÚN perfil (ni en `BASE_INITIAL_DOCS` ni en
# `POSGRADO_EXTRA_DOCS`): es el agujero que el spec §4.4 llama "hueco cerrado"
# -- hoy cualquier tipo activo de fase 1 se sube por POST directo aunque no
# esté en ninguna de las dos listas de `DocumentService`.
EGEL_DOC_TYPE = (("egel_proof", "Comprobante EGEL", 1),)
ALL_DOC_TYPES = INITIAL_DOC_TYPES + POSGRADO_DOC_TYPES + EGEL_DOC_TYPE

# Mismo set que `test_student_documents_status.py`/`test_initial_phase_sync.py`:
# el default de `conftest.py` no trae `.delete.own`, y aquí se necesitan las
# tres rutas (leer, subir, borrar).
STUDENT_PERMS = (
    "titulatec.dashboard.student",
    "titulatec.document.api.read.own",
    "titulatec.document.api.upload.own",
    "titulatec.document.api.delete.own",
)

PDF = ("documento.pdf", b"%PDF-1.4 documento de prueba", "application/pdf")

MENSAJE_NO_APLICA = "Este documento no aplica a tu proceso."


@pytest.fixture()
def esc(db_session, seed_phase_defs, seed_document_types, make_cohort, make_student,
        make_process, tmp_path, monkeypatch):
    """Alumno con proceso en fase 1. `program=None` (por omisión) -> licenciatura."""
    def _build(program=None, current_phase=1):
        monkeypatch.setattr("itcj2.apps.titulatec.utils.storage._base", lambda: tmp_path)
        seed_phase_defs()
        seed_document_types(types=ALL_DOC_TYPES)
        student = make_student(perm_codes=STUDENT_PERMS)
        proc = make_process(student, cohort=make_cohort(), program=program,
                            current_phase=current_phase)
        return student, proc
    return _build


def _doc(db, process_id, type_code):
    from itcj2.apps.titulatec.models import Document
    db.expire_all()
    return db.query(Document).filter_by(process_id=process_id, type_code=type_code).first()


def _files(root) -> list:
    return [p for p in root.rglob("*") if p.is_file()]


# ===========================================================================
# 1. GET /student/documents pinta el set del proceso, en orden, con la ayuda
# ===========================================================================
def test_licenciatura_ve_tres_espacios(esc, client_as):
    student, proc = esc()

    html = client_as(student).get("/titulatec/student/documents").text

    assert html.count('id="slot-') == 3
    for code in ("birth_certificate", "high_school_cert", "curp"):
        assert f'id="slot-{code}"' in html
    for code, _name, _fase in POSGRADO_DOC_TYPES:
        assert f'id="slot-{code}"' not in html


def test_posgrado_ve_siete_espacios_en_orden_con_las_cuatro_ayudas(
        esc, client_as, make_program):
    from itcj2.apps.titulatec.services.document_service import DocumentService

    pos = make_program("Maestria T5 Siete Espacios", level="maestria")
    student, proc = esc(program=pos)

    html = client_as(student).get("/titulatec/student/documents").text

    assert html.count('id="slot-') == 7
    orden_esperado = list(DocumentService.BASE_INITIAL_DOCS) + list(
        DocumentService.POSGRADO_EXTRA_DOCS)
    posiciones = [html.index(f'id="slot-{code}"') for code in orden_esperado]
    assert posiciones == sorted(posiciones), "los espacios no salen en el orden del perfil"
    for ayuda in DocumentService.INITIAL_DOC_HINTS.values():
        assert ayuda in html, f"falta la ayuda: {ayuda!r}"


def test_licenciatura_no_pinta_ninguna_ayuda_de_posgrado(esc, client_as):
    """Control del anterior: ninguna de las 4 ayudas se cuela en licenciatura
    (no hay `dtype` de esos códigos en sus slots)."""
    from itcj2.apps.titulatec.services.document_service import DocumentService

    student, proc = esc()

    html = client_as(student).get("/titulatec/student/documents").text

    for ayuda in DocumentService.INITIAL_DOC_HINTS.values():
        assert ayuda not in html


# ===========================================================================
# 2. Textos dinamicos: licenciatura identica a hoy; posgrado dice "7"
# ===========================================================================
def test_licenciatura_appbar_y_kicker_quedan_identicos_a_hoy(esc, client_as):
    student, proc = esc()

    html = client_as(student).get("/titulatec/student/documents").text

    assert "Fase 01 · Acta · Certificado · CURP" in html
    assert "Sube tus 3 documentos" in html
    assert "Fase 01 · 3 documentos" not in html


def test_posgrado_appbar_y_kicker_dicen_siete_documentos(esc, client_as, make_program):
    pos = make_program("Maestria T5 Appbar", level="maestria")
    student, proc = esc(program=pos)

    html = client_as(student).get("/titulatec/student/documents").text

    assert "Fase 01 · 7 documentos" in html
    assert "Sube tus 7 documentos" in html
    assert "Acta · Certificado · CURP" not in html


def test_docs_status_dice_tus_n_documentos_segun_perfil(
        esc, client_as, make_program, make_document):
    """`_docs_status.html:54` ("Tus N documentos...", estado "sent"): licenciatura
    sigue en 3, posgrado sube a 7. Los tres/siete deben estar SUBIDOS (pending)
    para caer en el estado "sent" -- con alguno faltante el aviso diría
    "Te faltan..." en su lugar (prioridad de `_docs_status_ctx`)."""
    from itcj2.apps.titulatec.services.document_service import DocumentService

    lic_student, lic_proc = esc()
    for code in DocumentService.BASE_INITIAL_DOCS:
        make_document(lic_proc, type_code=code)

    pos = make_program("Maestria T5 Docs Status", level="maestria")
    pos_student, pos_proc = esc(program=pos)
    for code in DocumentService.BASE_INITIAL_DOCS + DocumentService.POSGRADO_EXTRA_DOCS:
        make_document(pos_proc, type_code=code)

    html_lic = client_as(lic_student).get("/titulatec/student/documents").text
    html_pos = client_as(pos_student).get("/titulatec/student/documents").text

    assert "Tus 3 documentos" in html_lic
    assert "Tus 7 documentos" in html_pos


# ===========================================================================
# 3. Acordeon del dashboard: fase 1 de posgrado menciona "Cedula profesional"
# ===========================================================================
def test_acordeon_fase1_posgrado_menciona_cedula_profesional(
        db_session, seed_phase_defs, seed_document_types, make_program, make_cohort,
        make_student, make_process):
    from itcj2.apps.titulatec.pages.student import _phases_ctx

    seed_phase_defs()
    seed_document_types(types=ALL_DOC_TYPES)
    pos = make_program("Maestria T5 Acordeon", level="maestria")
    proc = make_process(make_student(), cohort=make_cohort(), program=pos, current_phase=1)

    ctx = _phases_ctx(db_session, proc)

    card = next(c for c in ctx["phases"] if c["code"] == "initial_docs")
    texto = card["desc"] + " " + " ".join(card["needs"])
    assert "Cédula profesional" in texto


def test_acordeon_fase1_licenciatura_no_cambia(
        db_session, seed_phase_defs, seed_document_types, make_cohort, make_student,
        make_process):
    """Control: sin programa (licenciatura), la card de `initial_docs` sigue
    siendo EXACTAMENTE `_PHASE_INFO["initial_docs"]` (nada de posgrado)."""
    from itcj2.apps.titulatec.pages.student import _PHASE_INFO, _phases_ctx

    seed_phase_defs()
    seed_document_types()
    proc = make_process(make_student(), cohort=make_cohort(), current_phase=1)

    ctx = _phases_ctx(db_session, proc)

    card = next(c for c in ctx["phases"] if c["code"] == "initial_docs")
    assert card["desc"] == _PHASE_INFO["initial_docs"]["desc"]
    assert "Cédula profesional" not in card["desc"]


def test_acordeon_sin_proceso_usa_la_variante_de_licenciatura(
        db_session, seed_phase_defs, seed_document_types):
    """Sin proceso no hay carrera que consultar: el acordeón (visitable sin
    login de proceso, p. ej. un alumno recién creado) debe caer a licenciatura,
    nunca reventar por `process is None`."""
    from itcj2.apps.titulatec.pages.student import _PHASE_INFO, _phases_ctx

    seed_phase_defs()
    seed_document_types()

    ctx = _phases_ctx(db_session, None)

    card = next(c for c in ctx["phases"] if c["code"] == "initial_docs")
    assert card["desc"] == _PHASE_INFO["initial_docs"]["desc"]


# ===========================================================================
# 4. Hueco cerrado -- subir
# ===========================================================================
def test_licenciatura_no_sube_un_extra_de_posgrado(esc, client_as, db_session, tmp_path):
    student, proc = esc()

    resp = client_as(student).post(
        "/titulatec/student/documents/professional_license", files={"archivo": PDF})

    assert resp.status_code == 400, resp.text[:300]
    assert unquote(resp.headers.get("X-Tt-Error", "")) == MENSAJE_NO_APLICA
    assert _doc(db_session, proc.id, "professional_license") is None
    assert _files(tmp_path) == []


def test_posgrado_si_sube_su_extra_y_queda_en_fase_1(esc, client_as, db_session, make_program):
    pos = make_program("Maestria T5 Sube Extra", level="maestria")
    student, proc = esc(program=pos)

    resp = client_as(student).post(
        "/titulatec/student/documents/professional_license", files={"archivo": PDF})

    assert resp.status_code == 200, resp.text[:300]
    assert 'id="slot-professional_license"' in resp.text
    assert "X-Tt-Error" not in resp.headers
    doc = _doc(db_session, proc.id, "professional_license")
    assert doc is not None
    assert doc.phase_number == 1


@pytest.mark.parametrize("con_posgrado", [False, True], ids=["licenciatura", "posgrado"])
def test_egel_proof_no_aplica_a_ningun_perfil(
        esc, client_as, db_session, tmp_path, make_program, con_posgrado):
    program = make_program("Maestria T5 Egel", level="maestria") if con_posgrado else None
    student, proc = esc(program=program)

    resp = client_as(student).post(
        "/titulatec/student/documents/egel_proof", files={"archivo": PDF})

    assert resp.status_code == 400, resp.text[:300]
    assert unquote(resp.headers.get("X-Tt-Error", "")) == MENSAJE_NO_APLICA
    assert _doc(db_session, proc.id, "egel_proof") is None
    assert _files(tmp_path) == []


def test_posgrado_sigue_subiendo_un_documento_base_sin_problema(esc, client_as, db_session,
                                                                 make_program):
    """Positivo de control: cerrar el hueco de los extras no le quita a
    posgrado sus 3 documentos base."""
    pos = make_program("Maestria T5 Base Sigue", level="maestria")
    student, proc = esc(program=pos)

    resp = client_as(student).post(
        "/titulatec/student/documents/curp", files={"archivo": PDF})

    assert resp.status_code == 200, resp.text[:300]
    assert _doc(db_session, proc.id, "curp") is not None


# ===========================================================================
# 5. Hueco cerrado -- borrar
# ===========================================================================
def test_licenciatura_no_borra_un_codigo_de_posgrado(esc, client_as, db_session, make_document):
    student, proc = esc()
    make_document(proc, type_code="professional_license", phase_number=1)

    resp = client_as(student).delete("/titulatec/student/documents/professional_license")

    assert resp.status_code == 400, resp.text[:300]
    assert unquote(resp.headers.get("X-Tt-Error", "")) == MENSAJE_NO_APLICA
    assert _doc(db_session, proc.id, "professional_license") is not None


def test_posgrado_si_borra_su_propio_extra(esc, client_as, db_session, make_program,
                                            make_document):
    pos = make_program("Maestria T5 Borra Extra", level="maestria")
    student, proc = esc(program=pos)
    make_document(proc, type_code="professional_license", phase_number=1)

    resp = client_as(student).delete("/titulatec/student/documents/professional_license")

    assert resp.status_code == 200, resp.text[:300]
    assert _doc(db_session, proc.id, "professional_license") is None
