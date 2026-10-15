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
# Liberar la fase 2 desde el panel (R13): la jefa de este archivo también lo tiene.
APPROVE_PHASE = "titulatec.process.api.approve_phase"
FULL = (READ_ALL, VIEW, ASK, APPROVE_DOC, APPROVE_PHASE)
CODE = "birth_certificate"
# R10: el aviso cuando el alumno cambió el archivo entre que se vio y se aprobó.
CAMBIO = "El alumno cambió el archivo: revísalo antes de aprobar."


def _msg(resp, header="X-Tt-Error") -> str:
    return unquote(resp.headers.get(header, ""))


def _nombre(db, code=CODE):
    from itcj2.apps.titulatec.models import DocumentType
    return db.query(DocumentType.name).filter_by(code=code).scalar()


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
        r = client_as(esc["jefa"]).post(_url(esc, "aprobar") + f"?v=atender&doc={CODE}",
                                        data={"version": str(esc["doc"].version)})
        assert r.status_code == 200
        assert "appt-shell" in r.text
        assert unquote(r.headers.get("X-Tt-Notice", ""))
        db_session.refresh(esc["doc"])
        assert esc["doc"].review_status == "approved"
        assert esc["doc"].replacement_requested_at is None
        assert "appt-docreplace-approve" not in r.text

    def test_aprobado_con_bandera_vieja_es_400_sin_reemplazo_pendiente(
            self, client_as, esc, db_session):
        """R7: un `approved` con la bandera vieja está CERRADO también aquí."""
        _abre_reemplazo(db_session, esc, "approved")
        r = client_as(esc["jefa"]).post(_url(esc, "aprobar"),
                                        data={"version": str(esc["doc"].version)})
        assert r.status_code == 400
        assert _msg(r) == "Ese documento no tiene un reemplazo pendiente."


# ---------------------------------------------------------------------------
# R10: «Aprobar reemplazo» aprueba el archivo que se VIO
# ---------------------------------------------------------------------------
class TestAprobarLaVersionVista:
    def _boton(self, html):
        return html.split('id="appt-docreplace-approve"')[1].split(">")[0]

    def test_el_boton_manda_la_version_que_pinto(self, client_as, esc, db_session):
        _abre_reemplazo(db_session, esc, "pending")
        esc["doc"].version = 3
        db_session.flush()
        boton = self._boton(_panel(client_as, esc).text)
        assert "hx-vals=" in boton and '"version":"3"' in boton

    def test_el_visor_pide_el_archivo_de_esa_version(self, client_as, esc, db_session):
        """Si el alumno cambia el archivo, el `src` del visor cambia y el morph
        lo recarga: sin esto el aviso de abajo mandaría a revisar el PDF viejo."""
        import re
        esc["doc"].version = 4
        db_session.flush()
        src = re.search(r'<iframe[^>]*src="([^"]+)"', _panel(client_as, esc).text).group(1)
        assert src.endswith("v=4"), src

    def test_si_el_alumno_cambio_el_archivo_avisa_y_no_aprueba(
            self, client_as, esc, db_session):
        _abre_reemplazo(db_session, esc, "pending")
        vista = esc["doc"].version
        esc["doc"].version = vista + 1            # el alumno subió otro mientras tanto
        db_session.flush()

        r = client_as(esc["jefa"]).post(_url(esc, "aprobar") + f"?v=atender&doc={CODE}",
                                        data={"version": str(vista)})

        assert r.status_code == 200, "htmx no hace swap en 4xx: el aviso va en un 200"
        assert _msg(r, "X-Tt-Notice") == CAMBIO
        assert r.headers.get("X-Tt-Notice-Kind") == "warning"
        assert not r.headers.get("X-Tt-Error")
        db_session.refresh(esc["doc"])
        assert esc["doc"].review_status == "pending"
        assert esc["doc"].replacement_requested_at is not None
        # El re-render ya trae el botón con la versión NUEVA.
        assert f'"version":"{vista + 1}"' in self._boton(r.text)

    @pytest.mark.parametrize("data", [{}, {"version": ""}, {"version": "x"}])
    def test_sin_version_valida_tampoco_aprueba(self, client_as, esc, db_session, data):
        """Sin la versión vista no se sabe QUÉ se vio: falla del lado seguro."""
        _abre_reemplazo(db_session, esc, "pending")
        r = client_as(esc["jefa"]).post(_url(esc, "aprobar"), data=data)
        assert r.status_code == 200
        assert _msg(r, "X-Tt-Notice") == CAMBIO
        db_session.refresh(esc["doc"])
        assert esc["doc"].review_status == "pending"


# ---------------------------------------------------------------------------
# R7 en el panel y R13: liberar la fase 2 con un reemplazo abierto
# ---------------------------------------------------------------------------
class TestLiberarConReemplazo:
    def _fase2(self, client_as, esc):
        return client_as(esc["jefa"]).post(
            f"/titulatec/admin/appointments/{esc['process'].id}/fase2/aprobar")

    @pytest.mark.parametrize("status", ["rejected", "pending"])
    def test_con_un_reemplazo_abierto_es_400_y_lo_nombra(self, client_as, esc,
                                                         db_session, status):
        from itcj2.apps.titulatec.models import TitulationProcess
        _abre_reemplazo(db_session, esc, status)

        r = self._fase2(client_as, esc)

        assert r.status_code == 400
        assert _msg(r) == ("No se puede liberar la fase 02: falta aprobar el reemplazo "
                           f"de: {_nombre(db_session)}.")
        db_session.expire_all()
        assert db_session.get(TitulationProcess, esc["process"].id).current_phase == 2

    def test_aprobado_el_reemplazo_la_fase_2_se_libera(self, client_as, esc, db_session):
        """Positivo del mismo actor y la misma ruta."""
        from itcj2.apps.titulatec.models import TitulationProcess
        _abre_reemplazo(db_session, esc, "pending")
        c = client_as(esc["jefa"])
        assert c.post(_url(esc, "aprobar"),
                      data={"version": str(esc["doc"].version)}).status_code == 200

        r = self._fase2(client_as, esc)

        assert r.status_code == 200, _msg(r)
        db_session.expire_all()
        assert db_session.get(TitulationProcess, esc["process"].id).current_phase == 3

    def test_aprobado_con_bandera_vieja_no_bloquea_ni_se_pinta(
            self, client_as, esc, db_session):
        """R7: la bandera vieja sobre un `approved` no traba la fase 2 ni pinta
        «Reemplazo pedido» en el panel."""
        _abre_reemplazo(db_session, esc, "approved")

        panel = _panel(client_as, esc).text
        assert "Reemplazo pedido" not in panel
        r = self._fase2(client_as, esc)
        assert r.status_code == 200, _msg(r)

    def test_el_contexto_marca_la_bandera_con_el_predicado_unico(self, db_session, esc):
        from itcj2.apps.titulatec.pages.appointments import _detail_ctx
        _abre_reemplazo(db_session, esc, "approved")
        ctx = _detail_ctx(db_session, esc["process"].id, user_id=esc["jefa"].id)
        [d] = [d for d in ctx["docs"] if d["type_code"] == CODE]
        assert d["replacement"] is False
        _abre_reemplazo(db_session, esc, "rejected")
        ctx = _detail_ctx(db_session, esc["process"].id, user_id=esc["jefa"].id)
        [d] = [d for d in ctx["docs"] if d["type_code"] == CODE]
        assert d["replacement"] is True
