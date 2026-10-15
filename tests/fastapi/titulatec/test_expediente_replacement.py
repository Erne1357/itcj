"""Reemplazo de documento pedido desde el EXPEDIENTE (spec 2026-10-15 §7.1).

`POST /titulatec/admin/processes/{id}/documents/{code}/reemplazo`: la jefatura
pide, desde la lista de documentos de la fase 1 del expediente, que el egresado
vuelva a subir un documento estando en la cita de cotejo. La lógica (y su matriz
de negativas) es de `DocumentService.request_replacement`
(`test_document_replacement.py`); aquí se prueba SOLO la ruta y su pintado:

* el permiso propio (`titulatec.document.api.request_replacement`) y el alcance
  por carrera (404), la guarda de vista completa (403);
* motivo vacío / el service que niega -> 400 + `X-Tt-Error`, sin escribir;
* éxito -> el expediente re-renderizado (`#exp-shell`) + `X-Tt-Notice`, el
  documento `rejected` con su bandera;
* el `<details>` «Pedir reemplazo» aparece SOLO con permiso + proceso en cotejo,
  y la píldora «Reemplazo pedido en cotejo» con el reemplazo abierto.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from urllib.parse import unquote

import pytest

from tests.fastapi.titulatec.conftest import OFFICER_PERMS

PERM = "titulatec.document.api.request_replacement"
URL = "/titulatec/admin/processes"
_BASE = ("birth_certificate", "curp", "high_school_cert")

EXPEDIENTE_PERMS = OFFICER_PERMS + (
    "titulatec.process.api.approve_phase",
    "titulatec.process.api.reject_phase",
)


def _msg(resp, header="X-Tt-Error") -> str:
    return unquote(resp.headers.get(header, ""))


def _doc(db, process_id, code="curp"):
    from itcj2.apps.titulatec.models import Document
    db.flush()
    db.expire_all()
    return db.query(Document).filter_by(process_id=process_id, type_code=code).one()


def _panel1(html: str) -> str:
    """Solo el panel de la fase 1 del acordeón."""
    return html.split('id="exp-panel-1"')[1].split('id="exp-fase-2"')[0]


@pytest.fixture()
def caso(db_session, seed_phase_defs, seed_document_types, make_program, make_cohort,
         make_officer, make_student, make_process, make_document, en_disco):
    """Proceso en cotejo (fase 2) con los 3 documentos base aprobados.

    `con_permiso=False` arma al encargado SIN el permiso del reemplazo (el rol de
    prueba es compartido por nombre dentro de la transacción: un solo encargado
    por prueba).

    `abiertos`: documentos con un reemplazo ABIERTO de verdad -- `rejected` con
    la bandera (R7: un `approved` con la bandera puesta está CERRADO). El resto
    queda `approved` sin bandera.
    """
    def _build(current_phase=2, con_permiso=True, status="active", abiertos=()):
        seed_phase_defs()
        seed_document_types()
        prog = make_program("Ingenieria del Reemplazo")
        cohort = make_cohort()
        perms = EXPEDIENTE_PERMS + ((PERM,) if con_permiso else ())
        officer, _pos = make_officer([prog], perm_codes=perms)
        student = make_student(first_name="ANA", last_name="REEMPLAZO")
        proc = make_process(student, cohort=cohort, program=prog,
                            current_phase=current_phase, status=status)
        for code in _BASE:
            make_document(
                proc, type_code=code,
                review_status=("rejected" if code in abiertos else "approved"),
                replacement_requested_at=(datetime(2026, 10, 1) if code in abiertos else None))
        return {"officer": officer, "student": student, "proc": proc, "program": prog}
    return _build


@pytest.fixture()
def en_disco(monkeypatch):
    """Todo `file_path` existe (el expediente resuelve `missing` en disco)."""
    from pathlib import Path
    from itcj2.apps.titulatec.utils import storage
    aqui = Path(__file__).resolve()
    monkeypatch.setattr(storage, "abs_path", lambda _rel: aqui)


def _post(client_as, esc, code="curp", note="El acta fisica es otra", **extra):
    return client_as(esc["officer"]).post(
        f"{URL}/{esc['proc'].id}/documents/{code}/reemplazo",
        data={"note": note, **extra})


# ===========================================================================
# La ruta
# ===========================================================================
class TestRuta:
    def test_exito_re_renderiza_el_expediente_y_deja_el_doc_rechazado(
            self, caso, client_as, db_session):
        esc = caso()
        resp = _post(client_as, esc)

        assert resp.status_code == 200, resp.text[:300]
        assert 'id="exp-shell"' in resp.text
        assert "reemplazo" in _msg(resp, "X-Tt-Notice").lower()
        assert resp.headers.get("X-Tt-Notice-Kind") == "success"
        doc = _doc(db_session, esc["proc"].id)
        assert doc.review_status == "rejected"
        assert doc.review_note == "El acta fisica es otra"
        assert doc.replacement_requested_at is not None
        assert doc.reviewed_by_id == esc["officer"].id

    def test_el_expediente_devuelto_ya_muestra_la_pildora(self, caso, client_as):
        esc = caso()
        html = _post(client_as, esc).text
        assert "Reemplazo pedido en cotejo" in _panel1(html)

    def test_sin_el_permiso_es_403_y_no_escribe(self, caso, client_as, db_session):
        esc = caso(con_permiso=False)
        resp = _post(client_as, esc)
        assert resp.status_code == 403
        assert _doc(db_session, esc["proc"].id).replacement_requested_at is None

    def test_fuera_de_alcance_es_404_y_no_escribe(
            self, caso, client_as, db_session, make_program, make_officer):
        esc = caso()
        otra = make_program("Otra Carrera Ajena")
        ajeno, _ = make_officer([otra], perm_codes=EXPEDIENTE_PERMS + (PERM,),
                                first_name="AJENO", last_name="OTRA")
        resp = client_as(ajeno).post(
            f"{URL}/{esc['proc'].id}/documents/curp/reemplazo", data={"note": "x"})
        assert resp.status_code == 404
        assert "X-Tt-Error" not in resp.headers
        assert _doc(db_session, esc["proc"].id).replacement_requested_at is None

    def test_el_resumen_sin_vista_completa_es_403(
            self, caso, client_as, db_session, monkeypatch):
        """`_exigir_vista_completa`: quien solo tiene el resumen no pasa, aunque
        conserve el permiso de la acción."""
        from itcj2.apps.titulatec.pages import admin as admin_pages
        esc = caso()
        monkeypatch.setattr(admin_pages, "_vista_completa", lambda _perms: False)
        resp = _post(client_as, esc)
        assert resp.status_code == 403
        assert _doc(db_session, esc["proc"].id).replacement_requested_at is None

    @pytest.mark.parametrize("nota", ["", "   ", None])
    def test_motivo_vacio_es_400_y_no_escribe(self, caso, client_as, db_session, nota):
        esc = caso()
        resp = client_as(esc["officer"]).post(
            f"{URL}/{esc['proc'].id}/documents/curp/reemplazo",
            data={} if nota is None else {"note": nota})
        assert resp.status_code == 400
        assert "motivo" in _msg(resp).lower()
        doc = _doc(db_session, esc["proc"].id)
        assert doc.review_status == "approved"
        assert doc.replacement_requested_at is None

    def test_fuera_de_cotejo_el_service_niega_con_400(self, caso, client_as, db_session):
        from itcj2.apps.titulatec.services.document_service import DocumentService
        esc = caso(current_phase=3)
        resp = _post(client_as, esc)
        assert resp.status_code == 400
        assert _msg(resp) == DocumentService.REPLACEMENT_NOT_COTEJO_MSG
        assert _doc(db_session, esc["proc"].id).replacement_requested_at is None

    def test_un_tipo_que_no_es_de_la_fase_1_es_400(self, caso, client_as):
        esc = caso()
        resp = _post(client_as, esc, code="no_existe_este_tipo")
        assert resp.status_code == 400


# ===========================================================================
# R13: liberar la fase 2 («Aprobar» / «Mover de fase») con un reemplazo abierto
# ===========================================================================
class TestLiberarFase2:
    def _aprobar(self, client_as, esc):
        return client_as(esc["officer"]).post(f"{URL}/{esc['proc'].id}/phase/2/approve")

    def test_con_un_reemplazo_abierto_es_400_y_nombra_el_documento(
            self, caso, client_as, db_session):
        from itcj2.apps.titulatec.models import DocumentType, TitulationProcess
        esc = caso(abiertos=("curp",))
        nombre = db_session.query(DocumentType.name).filter_by(code="curp").scalar()

        resp = self._aprobar(client_as, esc)

        assert resp.status_code == 400
        assert _msg(resp) == ("No se puede liberar la fase 02: falta aprobar el "
                              f"reemplazo de: {nombre}.")
        db_session.expire_all()
        assert db_session.get(TitulationProcess, esc["proc"].id).current_phase == 2

    def test_sin_reemplazo_abierto_la_misma_ruta_libera(self, caso, client_as,
                                                        db_session):
        """Positivo del mismo actor y la misma ruta (incluye la bandera vieja
        sobre un `approved`, R7)."""
        from itcj2.apps.titulatec.models import TitulationProcess
        esc = caso()
        _doc(db_session, esc["proc"].id).replacement_requested_at = datetime(2026, 10, 1)
        db_session.flush()

        resp = self._aprobar(client_as, esc)

        assert resp.status_code == 200, _msg(resp)
        db_session.expire_all()
        assert db_session.get(TitulationProcess, esc["proc"].id).current_phase == 3


# ===========================================================================
# El pintado de la lista de documentos de la fase 1
# ===========================================================================
class TestPintado:
    def test_el_details_aparece_con_permiso_y_cotejo(self, caso, client_as):
        esc = caso()
        html = client_as(esc["officer"]).get(f"{URL}/{esc['proc'].id}?fase=1").text
        panel = _panel1(html)
        assert "Pedir reemplazo" in panel
        assert f"{URL}/{esc['proc'].id}/documents/curp/reemplazo" in panel
        assert 'name="note"' in panel and "required" in panel
        assert "data-tt-confirm-ok" in panel and "hx-confirm" in panel
        # un form por documento, con id estable (morph)
        for code in _BASE:
            assert f'id="exp-repl-{code}"' in panel

    def test_sin_el_permiso_no_hay_form(self, caso, client_as):
        esc = caso(con_permiso=False)
        panel = _panel1(client_as(esc["officer"]).get(
            f"{URL}/{esc['proc'].id}?fase=1").text)
        assert "Pedir reemplazo" not in panel
        assert "/reemplazo" not in panel

    @pytest.mark.parametrize("fase", [1, 3])
    def test_fuera_de_cotejo_no_hay_form(self, caso, client_as, fase):
        esc = caso(current_phase=fase)
        panel = _panel1(client_as(esc["officer"]).get(
            f"{URL}/{esc['proc'].id}?fase=1").text)
        assert "Pedir reemplazo" not in panel

    def test_proceso_revocado_no_ofrece_el_form(self, caso, client_as):
        esc = caso(status="cancelled")
        panel = _panel1(client_as(esc["officer"]).get(
            f"{URL}/{esc['proc'].id}?fase=1").text)
        assert "Pedir reemplazo" not in panel

    def test_el_documento_sin_subir_no_ofrece_el_form(
            self, caso, client_as, db_session):
        from itcj2.apps.titulatec.models import Document
        esc = caso()
        db_session.query(Document).filter_by(
            process_id=esc["proc"].id, type_code="curp").delete()
        db_session.flush()
        panel = _panel1(client_as(esc["officer"]).get(
            f"{URL}/{esc['proc'].id}?fase=1").text)
        assert 'id="exp-repl-curp"' not in panel
        assert 'id="exp-repl-birth_certificate"' in panel

    def test_la_pildora_sale_solo_en_el_documento_con_reemplazo_abierto(
            self, caso, client_as):
        esc = caso(abiertos=("curp",))
        panel = _panel1(client_as(esc["officer"]).get(
            f"{URL}/{esc['proc'].id}?fase=1").text)
        assert panel.count("Reemplazo pedido en cotejo") == 1
        fila_curp = panel.split('id="exp-doc-curp"')[1].split('id="exp-doc-')[0]
        assert "Reemplazo pedido en cotejo" in fila_curp

    def test_rechazado_muestra_el_motivo_y_pendiente_dice_por_aprobar(
            self, caso, client_as, db_session):
        esc = caso(abiertos=("curp", "birth_certificate"))
        curp = _doc(db_session, esc["proc"].id, "curp")
        curp.review_status, curp.review_note = "rejected", "Esta borroso"
        acta = _doc(db_session, esc["proc"].id, "birth_certificate")
        acta.review_status, acta.review_note = "pending", None
        db_session.flush()

        panel = _panel1(client_as(esc["officer"]).get(
            f"{URL}/{esc['proc'].id}?fase=1").text)
        fila_curp = panel.split('id="exp-doc-curp"')[1].split('id="exp-doc-')[0]
        fila_acta = panel.split('id="exp-doc-birth_certificate"')[1].split('id="exp-doc-')[0]
        assert "Esta borroso" in fila_curp
        assert "por aprobar" in fila_acta
        assert "Esta borroso" not in fila_acta

    def test_un_encargado_sin_el_permiso_ve_la_pildora_pero_no_el_form(
            self, caso, client_as):
        esc = caso(con_permiso=False, abiertos=("curp",))
        panel = _panel1(client_as(esc["officer"]).get(
            f"{URL}/{esc['proc'].id}?fase=1").text)
        assert "Reemplazo pedido en cotejo" in panel
        assert "Pedir reemplazo" not in panel

    def test_un_aprobado_con_bandera_vieja_no_lleva_la_pildora(
            self, caso, client_as, db_session):
        """R7: la bandera que dejó el código viejo sobre un `approved` es un
        reemplazo CERRADO; el expediente no lo anuncia como pedido."""
        esc = caso()
        _doc(db_session, esc["proc"].id).replacement_requested_at = datetime(2026, 10, 1)
        db_session.flush()
        panel = _panel1(client_as(esc["officer"]).get(
            f"{URL}/{esc['proc'].id}?fase=1").text)
        assert "Reemplazo pedido en cotejo" not in panel
        assert 'id="exp-repl-curp"' in panel, "el form de pedir sí sigue ahí"

    def test_el_comentario_de_cabecera_ya_no_dice_solo_lectura(self):
        import pathlib
        import itcj2.apps.titulatec as pkg
        src = (pathlib.Path(pkg.__file__).resolve().parent / "templates" / "titulatec"
               / "partials" / "processes" / "_exp_phase.html").read_text(encoding="utf-8")
        cabecera = src.split("{% from", 1)[0]
        assert "SOLO LECTURA" not in cabecera
