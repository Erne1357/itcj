"""Reemplazo de documentos en el cotejo desde el panel «Atender» de Citas.

Spec 2026-10-15-titulatec-reemplazo-cotejo §7.1 y Ruling R5: bajo el visor del
documento abierto, «Pedir reemplazo» (modo por URL `&reemplazo=<type_code>`,
como `&rechazar=`) y «Aprobar reemplazo». Las dos rutas hermanas devuelven
`#appt-shell`, no el expediente ni la bandeja de Documentos.

El visor solo lista documentos con archivo en disco (`missing`), y el harness
no escribe archivos: `storage.abs_path` se redirige a un archivo real de
`tmp_path`, igual que `test_expediente_proceso.py`.
"""
from __future__ import annotations

from urllib.parse import unquote

import pytest

import itcj2.models  # noqa: F401

READ_ALL = "titulatec.process.api.read.all"
VIEW = "titulatec.appointment.page.list"
ASK = "titulatec.document.api.request_replacement"
APPROVE_DOC = "titulatec.document.api.approve"
FULL = (READ_ALL, VIEW, ASK, APPROVE_DOC)
CODE = "birth_certificate"


def _msg(resp) -> str:
    return unquote(resp.headers.get("X-Tt-Error", ""))


def _url(esc, suffix):
    return f"/titulatec/admin/appointments/{esc['process'].id}/documents/{CODE}/{suffix}"


@pytest.fixture()
def esc(db_session, seed_phase_defs, seed_document_types, make_head, make_student,
        make_cohort, make_process, make_program, make_document, make_appointment, monkeypatch, tmp_path):
    from itcj2.apps.titulatec.utils import storage

    seed_phase_defs()
    seed_document_types()
    cohort = make_cohort()
    student = make_student()
    program = make_program("Ingenieria Ficticia R")
    process = make_process(student, cohort=cohort, program=program, current_phase=2)
    make_appointment(process, status="attended")
    doc = make_document(process, CODE, review_status="approved")
    archivo = tmp_path / "doc.pdf"
    archivo.write_bytes(b"%PDF-1.4 prueba")
    monkeypatch.setattr(storage, "abs_path", lambda _rel: archivo)
    jefa = make_head(perm_codes=FULL)
    return {"process": process, "doc": doc, "jefa": jefa, "program": program}


def _panel(client_as, esc, user=None, extra=""):
    return (client_as(user or esc["jefa"]).get(
        f"/titulatec/admin/appointments/body?v=atender"
        f"&selected={esc['process'].id}&doc={CODE}{extra}",
        follow_redirects=False))


def _abre_reemplazo(db_session, esc, status="rejected", note="Falta legible"):
    from itcj2.core.utils.timezone import db_now
    esc["doc"].replacement_requested_at = db_now()
    esc["doc"].review_status = status
    esc["doc"].review_note = note if status == "rejected" else None
    db_session.flush()


class TestFicha:
    def test_con_el_permiso_en_cotejo_ofrece_pedir_reemplazo(self, client_as, esc):
        r = _panel(client_as, esc)
        assert r.status_code == 200
        assert 'id="appt-docreplace-ask"' in r.text
        assert f"reemplazo={CODE}" in r.text
        assert 'name="note"' not in r.text
        assert "appt-docreplace-approve" not in r.text

    def test_sin_permiso_de_pedir_no_hay_boton(self, client_as, esc,
                                               make_app_user_without_perms):
        otro = make_app_user_without_perms((READ_ALL, VIEW, APPROVE_DOC))
        r = _panel(client_as, esc, user=otro)
        assert r.status_code == 200
        assert "appt-docreplace-ask" not in r.text

    def test_fuera_de_cotejo_no_ofrece_pedir(self, client_as, esc, db_session):
        esc["process"].current_phase = 3
        db_session.flush()
        r = _panel(client_as, esc)
        assert "appt-docreplace-ask" not in r.text

    def test_reemplazo_rechazado_muestra_el_motivo_y_no_aprobar(
            self, client_as, esc, db_session):
        _abre_reemplazo(db_session, esc, "rejected", "Foto borrosa")
        r = _panel(client_as, esc)
        assert "Reemplazo pedido" in r.text
        assert "Foto borrosa" in r.text
        assert "appt-docreplace-approve" not in r.text

    def test_reemplazo_subido_ofrece_aprobar_con_confirmacion(
            self, client_as, esc, db_session):
        _abre_reemplazo(db_session, esc, "pending")
        r = _panel(client_as, esc)
        assert "Reemplazo subido" in r.text
        assert "appt-docreplace-approve" in r.text
        assert _url(esc, "aprobar") in r.text
        assert "data-tt-confirm-ok" in r.text and "hx-confirm=" in r.text

    def test_aprobar_oculto_sin_el_permiso_de_aprobar(
            self, client_as, esc, db_session, make_app_user_without_perms):
        _abre_reemplazo(db_session, esc, "pending")
        otro = make_app_user_without_perms((READ_ALL, VIEW, ASK))
        r = _panel(client_as, esc, user=otro)
        assert "appt-docreplace-approve" not in r.text

    def test_reemplazo_en_la_url_pinta_el_form(self, client_as, esc):
        r = _panel(client_as, esc, extra=f"&reemplazo={CODE}")
        assert 'name="note"' in r.text
        assert "required" in r.text
        assert _url(esc, "reemplazo") in r.text

    def test_el_iframe_no_cambia_con_el_modo(self, client_as, esc):
        import re
        sin = re.search(r'<iframe[^>]*src="([^"]+)"', _panel(client_as, esc).text)
        con = re.search(r'<iframe[^>]*src="([^"]+)"',
                        _panel(client_as, esc, extra=f"&reemplazo={CODE}").text)
        assert sin and con and sin.group(1) == con.group(1)

    def test_contexto_plano_y_banderas(self, db_session, esc):
        from itcj2.apps.titulatec.pages.appointments import _detail_ctx
        ctx = _detail_ctx(db_session, esc["process"].id, user_id=esc["jefa"].id)
        assert ctx["can_request_replacement"] is True
        assert ctx["can_approve_docs"] is True
        assert ctx["in_cotejo"] is True
        for d in ctx["docs"]:
            assert isinstance(d["replacement"], bool)
            assert "review_note" in d
            for v in d.values():
                assert not hasattr(v, "_sa_instance_state")


class TestPedir:
    def test_sin_permiso_403(self, client_as, esc, make_app_user_without_perms):
        otro = make_app_user_without_perms((READ_ALL, VIEW, APPROVE_DOC))
        r = client_as(otro).post(_url(esc, "reemplazo"), data={"note": "x"},
                                 follow_redirects=False)
        assert r.status_code == 403

    def test_fuera_de_alcance_404(self, client_as, esc, make_officer):
        from tests.fastapi.titulatec.conftest import OFFICER_PERMS
        oficial, _pos = make_officer(programs=[], perm_codes=OFFICER_PERMS + (ASK,))
        r = client_as(oficial).post(_url(esc, "reemplazo"), data={"note": "x"},
                                    follow_redirects=False)
        assert r.status_code == 404
        assert not r.headers.get("X-Tt-Error")

    def test_motivo_vacio_400_y_no_escribe(self, client_as, esc, db_session):
        r = client_as(esc["jefa"]).post(_url(esc, "reemplazo"), data={"note": "   "})
        assert r.status_code == 400 and _msg(r)
        db_session.refresh(esc["doc"])
        assert esc["doc"].replacement_requested_at is None
        assert esc["doc"].review_status == "approved"

    def test_exito_rerenderiza_y_avisa(self, client_as, esc, db_session):
        r = client_as(esc["jefa"]).post(
            _url(esc, "reemplazo") + f"?v=atender&doc={CODE}&reemplazo={CODE}",
            data={"note": "Sube el acta certificada."})
        assert r.status_code == 200
        assert "appt-shell" in r.text and "exp-shell" not in r.text
        assert unquote(r.headers.get("X-Tt-Notice", ""))
        assert 'name="note"' not in r.text, "el modo reemplazo debe descartarse"
        assert "Sube el acta certificada." in r.text
        db_session.refresh(esc["doc"])
        assert esc["doc"].review_status == "rejected"
        assert esc["doc"].replacement_requested_at is not None

    def test_fuera_de_cotejo_400_con_mensaje(self, client_as, esc, db_session):
        esc["process"].current_phase = 3
        db_session.flush()
        r = client_as(esc["jefa"]).post(_url(esc, "reemplazo"), data={"note": "x"})
        assert r.status_code == 400 and _msg(r)


class TestAprobar:
    def test_sin_permiso_403(self, client_as, esc, db_session, make_app_user_without_perms):
        _abre_reemplazo(db_session, esc, "pending")
        otro = make_app_user_without_perms((READ_ALL, VIEW, ASK))
        r = client_as(otro).post(_url(esc, "aprobar"), follow_redirects=False)
        assert r.status_code == 403

    def test_fuera_de_alcance_404(self, client_as, esc, db_session, make_officer):
        from tests.fastapi.titulatec.conftest import OFFICER_PERMS
        _abre_reemplazo(db_session, esc, "pending")
        oficial, _pos = make_officer(programs=[], perm_codes=OFFICER_PERMS + (APPROVE_DOC,))
        r = client_as(oficial).post(_url(esc, "aprobar"), follow_redirects=False)
        assert r.status_code == 404

    def test_sin_reemplazo_abierto_400(self, client_as, esc, db_session):
        esc["doc"].review_status = "pending"
        db_session.flush()
        r = client_as(esc["jefa"]).post(_url(esc, "aprobar"))
        assert r.status_code == 400
        assert _msg(r) == "Ese documento no tiene un reemplazo pendiente."
        db_session.refresh(esc["doc"])
        assert esc["doc"].review_status == "pending"

    def test_con_reemplazo_pending_aprueba_y_limpia_la_bandera(
            self, client_as, esc, db_session):
        _abre_reemplazo(db_session, esc, "pending")
        r = client_as(esc["jefa"]).post(_url(esc, "aprobar") + f"?v=atender&doc={CODE}")
        assert r.status_code == 200
        assert "appt-shell" in r.text
        assert unquote(r.headers.get("X-Tt-Notice", ""))
        db_session.refresh(esc["doc"])
        assert esc["doc"].review_status == "approved"
        assert esc["doc"].replacement_requested_at is None
        assert "appt-docreplace-approve" not in r.text
