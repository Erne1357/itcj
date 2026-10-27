"""Reactivar una inscripción revocada (`ProcessService.reactivate`).

La reversa de `test_process_cancel.py`: el proceso vuelve al estado que tenía
al revocarse (o a `active` si hoy hay convocatoria abierta), queda el evento
`process_reactivated`, se avisa en la app y por correo, y se niega si el
alumno ya tiene otro proceso vivo. Rutas: expediente
(`/processes/{id}/reactivar`) y Solicitudes › Inscritas
(`/solicitudes/{id}/reactivar`), con el permiso de revocar.
"""
from __future__ import annotations

from urllib.parse import unquote

import pytest

import itcj2.models  # noqa: F401

CANCEL = "titulatec.process.api.cancel"
READ_ALL = "titulatec.process.api.read.all"
DETAIL = "titulatec.process.page.detail"
PERMS = (READ_ALL, DETAIL, CANCEL)
REQ_PERMS = (
    "titulatec.enrollment_request.page.list",
    "titulatec.enrollment_request.api.approve",
    "titulatec.enrollment_request.api.reject",
    READ_ALL,
    CANCEL,
)


def _svc():
    from itcj2.apps.titulatec.services.process_service import ProcessService
    return ProcessService


def _events(db, process_id, tipo):
    from itcj2.apps.titulatec.models import ProcessEvent
    return db.query(ProcessEvent).filter_by(process_id=process_id, event_type=tipo).all()


def _msg(resp) -> str:
    return unquote(resp.headers.get("X-Tt-Error", ""))


@pytest.fixture()
def correos(monkeypatch):
    """Correo apagado: los dos avisos salen en línea y se cuentan aquí."""
    from itcj2.apps.titulatec.services.student_mail import MailSettings

    monkeypatch.setattr(MailSettings, "enabled", staticmethod(lambda: False))
    enviados = []
    base = "itcj2.apps.titulatec.services.email_helper.TitulaTecEmailHelper."
    monkeypatch.setattr(base + "send_process_cancelled",
                        staticmethod(lambda db, p: enviados.append(("revocada", p.id)) or True))
    monkeypatch.setattr(base + "send_process_reactivated",
                        staticmethod(lambda db, p: enviados.append(("reactivada", p.id)) or True))
    return enviados


@pytest.fixture()
def esc(db_session, seed_phase_defs, seed_document_types, make_program, make_cohort,
        make_student, make_process, make_user):
    seed_phase_defs()
    seed_document_types()
    prog = make_program("Ingenieria Ficticia Reactivable")
    cohort = make_cohort()
    student = make_student()
    actor = make_user(first_name="ESCOLARES", last_name="REACTIVA")

    def _revocado(status="active"):
        proc = make_process(student, cohort=cohort, program=prog,
                            current_phase=1, status=status)
        ok, msg = _svc().cancel(db_session, proc.id, reason="Por error", actor_id=actor.id)
        assert ok, msg
        return proc

    return {"prog": prog, "cohort": cohort, "student": student, "actor": actor,
            "revocado": _revocado}


@pytest.fixture()
def revocado(esc, correos):
    return esc["revocado"]


# ===========================================================================
# 1. El servicio
# ===========================================================================
class TestReactivar:
    def test_vuelve_a_active_con_evento_y_avisos(self, db_session, esc, revocado, correos):
        from itcj2.core.models.notification import Notification
        proc = revocado()

        ok, msg = _svc().reactivate(db_session, proc.id, actor_id=esc["actor"].id)

        assert ok, msg
        db_session.refresh(proc)
        assert proc.status == "active"
        (ev,) = _events(db_session, proc.id, "process_reactivated")
        assert ev.actor_id == esc["actor"].id and ev.payload == {"status": "active"}
        assert _svc().cancellation_info(db_session, proc) is None
        assert ("reactivada", proc.id) in correos
        avisos = (db_session.query(Notification)
                  .filter_by(user_id=esc["student"].id, type="PROCESS_REACTIVATED").all())
        assert [a.title for a in avisos] == ["Tu inscripción a titulación fue reactivada"]

    def test_pausado_sin_convocatoria_abierta_vuelve_pausado(self, db_session, esc,
                                                              revocado, correos):
        from itcj2.apps.titulatec.models import Cohort
        proc = revocado(status="on_hold")
        db_session.query(Cohort).filter(Cohort.status == "open").update({"status": "closed"})
        db_session.flush()

        assert _svc().reactivate(db_session, proc.id, actor_id=esc["actor"].id)[0]

        db_session.refresh(proc)
        assert proc.status == "on_hold"

    def test_pausado_con_convocatoria_abierta_vuelve_activo(self, db_session, esc, revocado,
                                                             correos, make_cohort):
        proc = revocado(status="on_hold")
        make_cohort(status="open")

        assert _svc().reactivate(db_session, proc.id, actor_id=esc["actor"].id)[0]

        db_session.refresh(proc)
        assert proc.status == "active"

    def test_uno_no_revocado_no_se_toca(self, db_session, esc, make_process, correos):
        proc = make_process(esc["student"], cohort=esc["cohort"], program=esc["prog"],
                            current_phase=1, status="active")

        ok, msg = _svc().reactivate(db_session, proc.id, actor_id=esc["actor"].id)

        assert not ok and "no está revocada" in msg
        assert _events(db_session, proc.id, "process_reactivated") == []
        assert correos == []

    def test_se_niega_si_ya_tiene_otro_proceso_vivo(self, db_session, esc, revocado,
                                                    make_cohort, make_process, correos):
        proc = revocado()
        otro = make_process(esc["student"], cohort=make_cohort(), program=esc["prog"],
                            current_phase=1, status="active")

        ok, msg = _svc().reactivate(db_session, proc.id, actor_id=esc["actor"].id)

        assert not ok and otro.folio in msg
        db_session.refresh(proc)
        assert proc.status == "cancelled"

    def test_se_puede_volver_a_revocar(self, db_session, esc, revocado, correos):
        proc = revocado()
        assert _svc().reactivate(db_session, proc.id, actor_id=esc["actor"].id)[0]

        ok, msg = _svc().cancel(db_session, proc.id, reason="Ahora sí",
                                actor_id=esc["actor"].id)

        assert ok, msg
        assert _svc().cancellation_info(db_session, proc)["reason"] == "Ahora sí"

    def test_proceso_inexistente(self, db_session, esc, correos):
        ok, msg = _svc().reactivate(db_session, 987654321, actor_id=esc["actor"].id)
        assert not ok and msg


# ===========================================================================
# 2. Expediente
# ===========================================================================
def _url(pid):
    return f"/titulatec/admin/processes/{pid}/reactivar"


class TestExpediente:
    def test_reactiva_y_devuelve_el_expediente(self, db_session, revocado, make_head,
                                               client_as, correos):
        proc = revocado()
        jefa = make_head(perm_codes=PERMS)

        resp = client_as(jefa).post(_url(proc.id))

        assert resp.status_code == 200, resp.text[:300]
        assert 'id="exp-shell"' in resp.text
        assert 'id="exp-revocada"' not in resp.text
        assert "Inscripción reactivada" in resp.text      # historial
        db_session.refresh(proc)
        assert proc.status == "active"

    def test_sin_el_permiso_es_403(self, db_session, revocado, make_head, client_as, correos):
        proc = revocado()
        jefa = make_head(perm_codes=(READ_ALL, DETAIL))

        resp = client_as(jefa).post(_url(proc.id), follow_redirects=False)

        assert resp.status_code == 403
        db_session.refresh(proc)
        assert proc.status == "cancelled"

    def test_fuera_de_su_carrera_es_404(self, db_session, revocado, make_officer,
                                        make_program, client_as, correos):
        proc = revocado()
        encargado, _ = make_officer([make_program("Ingenieria Ajena")],
                                    perm_codes=(DETAIL, CANCEL))

        resp = client_as(encargado).post(_url(proc.id))

        assert resp.status_code == 404
        db_session.refresh(proc)
        assert proc.status == "cancelled"

    def test_no_revocada_es_400(self, esc, make_process, make_head, client_as, correos):
        proc = make_process(esc["student"], cohort=esc["cohort"], program=esc["prog"],
                            current_phase=1, status="active")
        jefa = make_head(perm_codes=PERMS)

        resp = client_as(jefa).post(_url(proc.id))

        assert resp.status_code == 400
        assert "no está revocada" in _msg(resp)

    def test_el_boton_sale_solo_en_una_revocada_y_con_el_permiso(
        self, esc, revocado, make_head, make_officer, client_as, correos,
    ):
        proc = revocado()
        con = make_head(perm_codes=PERMS)
        sin, _ = make_officer([esc["prog"]], perm_codes=(DETAIL,))

        html_con = client_as(con).get(f"/titulatec/admin/processes/{proc.id}").text
        html_sin = client_as(sin).get(f"/titulatec/admin/processes/{proc.id}").text

        assert 'id="exp-reactivar"' in html_con
        assert f'hx-post="/titulatec/admin/processes/{proc.id}/reactivar' in html_con
        assert 'hx-confirm="Reactivar inscripción|' in html_con
        assert 'id="exp-reactivar"' not in html_sin

    def test_un_proceso_vivo_no_ofrece_reactivar(self, esc, make_process, make_head,
                                                 client_as):
        proc = make_process(esc["student"], cohort=esc["cohort"], program=esc["prog"],
                            current_phase=1, status="active")
        html = client_as(make_head(perm_codes=PERMS)).get(
            f"/titulatec/admin/processes/{proc.id}").text
        assert 'id="exp-reactivar"' not in html


# ===========================================================================
# 3. Solicitudes › Inscritas
# ===========================================================================
@pytest.fixture()
def inscrita(db_session, esc, revocado):
    """Solicitud `converted` cuyo proceso está revocado."""
    from itcj2.apps.titulatec.models import EnrollmentRequest

    proc = revocado()
    req = EnrollmentRequest(
        cohort_id=esc["cohort"].id, control_number=esc["student"].control_number,
        first_name="EGRESADA", last_name="REACTIVABLE", program_id=esc["prog"].id,
        program_text="Ingenieria Ficticia", phone="6561234567",
        contact_email="reactivable@example.invalid", has_efirma=False, kind="unknown",
        status="converted", verify_send_count=0, converted_process_id=proc.id)
    db_session.add(req)
    db_session.flush()
    return req, proc


def _fila(html, req):
    marca = f'id="tt-req-{req.id}"'
    assert marca in html, f"no está la fila de la solicitud {req.id}"
    return html.split(marca, 1)[1].split("</tr>", 1)[0]


class TestSolicitudes:
    def test_la_fila_revocada_ofrece_reactivar_con_confirmacion(self, inscrita, make_head,
                                                                client_as):
        req, _proc = inscrita
        html = client_as(make_head(perm_codes=REQ_PERMS)).get(
            "/titulatec/admin/solicitudes/body?status=converted").text

        fila = _fila(html, req)
        assert f'hx-post="/titulatec/admin/solicitudes/{req.id}/reactivar"' in fila
        assert 'hx-confirm="Reactivar inscripción|' in fila

    def test_sin_el_permiso_no_hay_boton(self, inscrita, make_head, client_as):
        req, _proc = inscrita
        html = client_as(make_head(perm_codes=REQ_PERMS[:-1])).get(
            "/titulatec/admin/solicitudes/body?status=converted").text
        assert "/reactivar" not in _fila(html, req)

    def test_reactiva_y_repinta_la_bandeja(self, db_session, inscrita, make_head, client_as,
                                           correos):
        req, proc = inscrita

        resp = client_as(make_head(perm_codes=REQ_PERMS)).post(
            f"/titulatec/admin/solicitudes/{req.id}/reactivar",
            data={"status": "converted", "cohort_id": ""}, follow_redirects=False)

        assert resp.status_code == 200, resp.text[:300]
        fila = _fila(resp.text, req)
        assert "Reactivar inscripción" not in fila
        assert f"/solicitudes/{req.id}/revocar" in fila
        db_session.refresh(proc)
        assert proc.status == "active"

    def test_sin_proceso_revocado_es_400(self, db_session, inscrita, make_head, client_as,
                                         correos):
        req, proc = inscrita
        _svc().reactivate(db_session, proc.id, actor_id=None)

        resp = client_as(make_head(perm_codes=REQ_PERMS)).post(
            f"/titulatec/admin/solicitudes/{req.id}/reactivar", follow_redirects=False)

        assert resp.status_code == 400
        assert "no está revocada" in _msg(resp)
