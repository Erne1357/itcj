"""«Pedir reemplazo» en la bandeja Documentos (spec 2026-10-15-titulatec-
reemplazo-cotejo-design.md, §4 y §7.1).

Con el proceso ya en la cita de cotejo (fase 2) el dictamen de la fase 1 está
congelado (`DocumentService.review`); la jefatura de Servicios Escolares tiene
una vía APARTE, con el permiso `titulatec.document.api.request_replacement`:
`POST /titulatec/admin/documents/{process_id}/document/reemplazo`. Aprobar el
reemplazo subido usa el Aprobar de siempre.
"""
from __future__ import annotations

from urllib.parse import unquote

import pytest

from itcj2.core.utils.timezone import db_now

REPLACE_PERM = "titulatec.document.api.request_replacement"
REVIEW_PERMS = ("titulatec.document.api.approve", "titulatec.document.api.reject")
URL = "/titulatec/admin/documents/%d/document/reemplazo"


@pytest.fixture()
def escenario(seed_phase_defs, seed_document_types, make_cohort, make_student,
              make_process, make_document):
    def _nuevo(current_phase=2, statuses=("approved", "approved", "approved"),
               program=None, abiertos=()):
        seed_phase_defs()
        seed_document_types()
        proc = make_process(make_student(), cohort=make_cohort(), program=program,
                            current_phase=current_phase)
        docs = {}
        for code, st in zip(("birth_certificate", "high_school_cert", "curp"), statuses):
            docs[code] = make_document(
                proc, type_code=code, review_status=st,
                replacement_requested_at=db_now() if code in abiertos else None)
        return proc, docs

    return _nuevo


@pytest.fixture()
def jefa(make_head):
    from tests.fastapi.titulatec.conftest import HEAD_PERMS
    return make_head(perm_codes=HEAD_PERMS + REVIEW_PERMS + (REPLACE_PERM,))


def _body(client, proc):
    return client.get("/titulatec/admin/documents/body?selected=%d" % proc.id).text


# ───────────────────────────── permiso, alcance, motivo ───────────────────────

def test_sin_el_permiso_nuevo_la_ruta_se_niega(escenario, make_head, client_as, db_session):
    from itcj2.apps.titulatec.models import Document
    from tests.fastapi.titulatec.conftest import HEAD_PERMS

    proc, _ = escenario()
    sin = make_head(perm_codes=HEAD_PERMS + REVIEW_PERMS)

    resp = client_as(sin).post(URL % proc.id,
                               data={"type_code": "curp", "note": "Otro acta"})

    assert resp.status_code == 403
    db_session.expire_all()
    doc = db_session.query(Document).filter_by(process_id=proc.id, type_code="curp").one()
    assert doc.review_status == "approved" and doc.replacement_requested_at is None


def test_fuera_de_alcance_es_404(escenario, make_officer, make_program, client_as):
    from tests.fastapi.titulatec.conftest import OFFICER_PERMS

    ajena = make_program("CARRERA AJENA T3A")
    propia = make_program("CARRERA PROPIA T3A")
    proc, _ = escenario(program=ajena)
    oficial, _pos = make_officer([propia], perm_codes=OFFICER_PERMS + (REPLACE_PERM,))

    resp = client_as(oficial).post(URL % proc.id,
                                   data={"type_code": "curp", "note": "Otro"})

    assert resp.status_code == 404
    assert "X-Tt-Error" not in resp.headers


def test_motivo_vacio_es_400_y_no_escribe(escenario, jefa, client_as, db_session):
    from itcj2.apps.titulatec.models import Document

    proc, _ = escenario()
    client = client_as(jefa)

    for note in ("", "   "):
        resp = client.post(URL % proc.id, data={"type_code": "curp", "note": note})
        assert resp.status_code == 400
        assert resp.headers["X-Tt-Error"]
    db_session.expire_all()
    doc = db_session.query(Document).filter_by(process_id=proc.id, type_code="curp").one()
    assert doc.review_status == "approved" and doc.replacement_requested_at is None


def test_sin_tipo_de_documento_es_400(escenario, jefa, client_as):
    proc, _ = escenario()

    resp = client_as(jefa).post(URL % proc.id, data={"note": "Otro"})

    assert resp.status_code == 400
    assert resp.headers["X-Tt-Error"]


def test_fuera_de_la_cita_de_cotejo_es_400_con_el_mensaje_del_service(
        escenario, jefa, client_as):
    from itcj2.apps.titulatec.services.document_service import DocumentService

    proc, _ = escenario(current_phase=1)

    resp = client_as(jefa).post(URL % proc.id, data={"type_code": "curp", "note": "Otro"})

    assert resp.status_code == 400
    assert resp.headers["X-Tt-Error"] == DocumentService.REPLACEMENT_NOT_COTEJO_MSG


# ───────────────────────────── éxito ──────────────────────────────────────────

def test_exito_rechaza_abre_el_reemplazo_y_repinta(escenario, jefa, client_as, db_session):
    from itcj2.apps.titulatec.models import Document

    proc, _ = escenario()

    resp = client_as(jefa).post(
        URL % proc.id,
        data={"type_code": "curp", "note": "Presento otra CURP", "status": ""})

    assert resp.status_code == 200
    # R12: acentuado y percent-encoded con el `_hdr` del módulo, como sus hermanos,
    # y con su tono de éxito (sin `Kind` el toast sale como advertencia).
    assert unquote(resp.headers["X-Tt-Notice"]) == (
        "Se pidió el reemplazo del documento al egresado.")
    assert resp.headers["X-Tt-Notice"].isascii()
    assert resp.headers.get("X-Tt-Notice-Kind") == "success"
    db_session.expire_all()
    doc = db_session.query(Document).filter_by(process_id=proc.id, type_code="curp").one()
    assert doc.review_status == "rejected"
    assert doc.review_note == "Presento otra CURP"
    assert doc.replacement_requested_at is not None
    # Re-render del contenedor con el documento ya marcado.
    assert 'id="tt-doc-review"' in resp.text
    assert 'data-replacement="1"' in resp.text


# ───────────────────────────── UI de la bandeja ───────────────────────────────

def test_el_boton_aparece_con_permiso_cotejo_y_fase_cerrada(escenario, jefa, client_as):
    proc, _ = escenario(current_phase=2)

    html = _body(client_as(jefa), proc)

    assert 'data-phase-closed="1"' in html
    assert 'id="tt-inline-replace"' in html
    assert 'id="tt-review-form"' in html
    # Y el «Rechazar» normal sigue sin ofrecerse con la fase cerrada.
    assert 'id="tt-inline-reject"' not in html


def test_el_boton_no_aparece_sin_el_permiso(escenario, make_head, client_as):
    from tests.fastapi.titulatec.conftest import HEAD_PERMS

    proc, _ = escenario(current_phase=2)
    sin = make_head(perm_codes=HEAD_PERMS + REVIEW_PERMS)

    html = _body(client_as(sin), proc)

    assert 'id="tt-inline-replace"' not in html
    assert 'id="tt-review-form"' in html


def test_el_boton_no_aparece_en_la_fase_1(escenario, jefa, client_as):
    proc, _ = escenario(current_phase=1, statuses=("approved", "approved", "pending"))

    html = _body(client_as(jefa), proc)

    assert 'data-phase-closed="0"' in html
    assert 'id="tt-inline-replace"' not in html


def test_el_boton_no_aparece_pasada_la_fase_de_cotejo(escenario, jefa, client_as):
    proc, _ = escenario(current_phase=3)

    html = _body(client_as(jefa), proc)

    assert 'data-phase-closed="1"' in html
    assert 'id="tt-inline-replace"' not in html


def test_solo_con_el_permiso_nuevo_el_form_existe(escenario, make_head, client_as):
    """El form del dictamen debe existir también sin `approve/reject`."""
    from tests.fastapi.titulatec.conftest import HEAD_PERMS

    proc, _ = escenario(current_phase=2)
    solo = make_head(perm_codes=HEAD_PERMS + (REPLACE_PERM,))

    html = _body(client_as(solo), proc)

    assert 'id="tt-review-form"' in html
    assert 'id="tt-inline-replace"' in html
    assert 'id="tt-inline-approve"' not in html


def test_la_pildora_marca_solo_el_documento_con_reemplazo_abierto(
        escenario, jefa, client_as):
    proc, _ = escenario(current_phase=2, statuses=("approved", "rejected", "approved"),
                        abiertos=("high_school_cert",))

    html = _body(client_as(jefa), proc)

    assert html.count("Reemplazo en cotejo") == 1
    assert html.count('data-replacement="1"') == 1
    assert html.count('data-replacement="0"') == 2


def test_un_aprobado_con_bandera_vieja_no_es_reemplazo_abierto(escenario, jefa, client_as):
    """R7: la bandera que el código viejo dejó sobre un `approved` (reversa de la
    spec §9) es un reemplazo CERRADO; la bandeja no lo anuncia."""
    proc, _ = escenario(current_phase=2, abiertos=("high_school_cert",))   # los 3 approved

    html = _body(client_as(jefa), proc)

    assert "Reemplazo en cotejo" not in html
    assert html.count('data-replacement="0"') == 3
    assert 'id="tt-inline-replace"' in html, "pedir uno nuevo sí sigue disponible"


def test_las_filas_marcan_la_bandera_con_el_predicado_unico(escenario, db_session):
    from itcj2.apps.titulatec.pages.documents import _doc_states
    from itcj2.apps.titulatec.services.document_service import DocumentService

    proc, docs = escenario(current_phase=2, statuses=("approved", "pending", "rejected"),
                           abiertos=("birth_certificate", "high_school_cert", "curp"))

    [estado] = _doc_states(db_session, [proc])

    assert {d["type_code"]: d["replacement"] for d in estado["docs"]} == {
        code: DocumentService.replacement_open(doc.review_status,
                                               doc.replacement_requested_at)
        for code, doc in docs.items()}
    assert [d["replacement"] for d in estado["docs"]] == [False, True, True]
