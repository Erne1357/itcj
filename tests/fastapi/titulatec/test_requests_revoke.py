"""«Revocar inscripción» desde Solicitudes › Inscritas (spec 2026-09-25 §3.6).

`POST /titulatec/admin/solicitudes/{id}/revocar` revoca el proceso en que se
convirtió la solicitud (`converted_process_id`) con
`ProcessService.cancel(..., reason=, actor_id=)` y vuelve a pintar la bandeja.
Contrato que fija este archivo:

- UN código en `perms`: `titulatec.process.api.cancel` (globals).
- Mismo alcance por carrera que el resto de la bandeja: fuera de alcance = 404
  liso, sin `X-Tt-Error`, y el proceso sigue vivo.
- Motivo obligatorio (es lo que el alumno lee): vacío = 400 sin escribir.
- Solo una solicitud `converted` con proceso: sin proceso, o con el proceso ya
  revocado o concluido, 400 + `X-Tt-Error` con el motivo del servicio.
- En modo alterno la bandeja es de solo lectura: 400 y nada escrito.
- La fila ofrece el formulario solo a quien tiene el permiso y solo sobre un
  proceso revocable; una revocada dice «Inscripción revocada: motivo».
- Sin `hx-confirm` (no hay puente en esta bandeja).

La mecánica de la revocación (cita, evento, correo, idempotencia) vive en
`test_process_cancel.py`; aquí se prueba la ruta y lo que ve el oficial.
"""
from __future__ import annotations

import re
from urllib.parse import unquote

import pytest

URL = "/titulatec/admin/solicitudes"
CANCEL = "titulatec.process.api.cancel"

LIST_PERMS = (
    "titulatec.enrollment_request.page.list",
    "titulatec.enrollment_request.api.approve",
    "titulatec.enrollment_request.api.reject",
    "titulatec.process.api.read.all",
)
REVOKE_PERMS = LIST_PERMS + (CANCEL,)
# Acotado por carrera (sin `read.all`), pero con el permiso de revocar.
OFFICER_REVOKE_PERMS = (
    "titulatec.enrollment_request.page.list",
    CANCEL,
)


@pytest.fixture(autouse=True)
def correos(monkeypatch):
    """El aviso de revocación nunca toca Graph aquí; se registra cada envío."""
    enviados = []
    monkeypatch.setattr(
        "itcj2.apps.titulatec.services.email_helper.TitulaTecEmailHelper.send_process_cancelled",
        staticmethod(lambda db, p: enviados.append(p.id) or True))
    return enviados


@pytest.fixture()
def esc(seed_phase_defs, make_program, make_cohort, make_student, make_process, db_session):
    """Una solicitud `converted` con su proceso vivo, en una carrera propia."""
    seed_phase_defs()
    prog = make_program("Ingenieria Ficticia de Solicitudes Revocables")
    cohort = make_cohort(status="open")

    def _inscrita(control, *, proc_status="active", program=prog, with_process=True):
        proc = None
        if with_process:
            proc = make_process(make_student(control_number=control), cohort=cohort,
                                program=program, status=proc_status,
                                current_phase=8 if proc_status == "completed" else 1)
        req = _make_req(db_session, cohort, control=control, status="converted",
                        program=program,
                        converted_process_id=proc.id if proc is not None else None)
        return req, proc

    return {"prog": prog, "cohort": cohort, "inscrita": _inscrita}


def _make_req(db_session, cohort, *, control, status, program=None, **kw):
    from itcj2.apps.titulatec.models import EnrollmentRequest

    row = EnrollmentRequest(
        cohort_id=cohort.id, control_number=control,
        first_name="EGRESADA", last_name="REVOCABLE", middle_name=None,
        program_id=getattr(program, "id", program), program_text="Ingenieria Ficticia",
        phone="6561234567", contact_email="revocable@example.invalid",
        has_efirma=False, kind="unknown", status=status, verify_send_count=0,
    )
    for k, v in kw.items():
        setattr(row, k, v)
    db_session.add(row)
    db_session.flush()
    return row


def _post(c, req, *, reason="Documentación apócrifa", status="converted", cohort_id=""):
    return c.post(f"{URL}/{req.id}/revocar",
                  data={"reason": reason, "status": status, "cohort_id": cohort_id},
                  follow_redirects=False)


def _fila(html: str, req) -> str:
    marca = f'id="tt-req-{req.id}"'
    assert marca in html, f"no está la fila de la solicitud {req.id}"
    return html.split(marca, 1)[1].split("</tr>", 1)[0]


def _plano(html: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", html).split())


def _msg(resp) -> str:
    return unquote(resp.headers.get("X-Tt-Error", ""))


def _cancel_events(db, proc):
    from itcj2.apps.titulatec.models import ProcessEvent
    return (db.query(ProcessEvent)
            .filter_by(process_id=proc.id, event_type="process_cancelled").all())


# ---------------------------------------------------------------------------
# Lo que ve el oficial
# ---------------------------------------------------------------------------
def test_la_fila_inscrita_ofrece_revocar_con_motivo_a_quien_tiene_el_permiso(
    client_as, make_head, esc,
):
    req, proc = esc["inscrita"]("99660001")
    head = make_head(perm_codes=REVOKE_PERMS)

    fila = _fila(client_as(head).get(f"{URL}/body?status=converted").text, req)

    assert proc.folio in fila
    assert f'hx-post="/titulatec/admin/solicitudes/{req.id}/revocar"' in fila
    assert re.search(r'<input[^>]*name="reason"[^>]*required', fila)
    assert "Revocar inscripción" in fila
    # Vuelve a la pestaña donde estaba, como el resto de formularios de fila.
    assert 'name="status" value="converted"' in fila
    assert "hx-confirm" not in fila


def test_sin_el_permiso_la_fila_inscrita_no_ofrece_revocar(client_as, make_head, esc):
    req, _proc = esc["inscrita"]("99660002")
    head = make_head(perm_codes=LIST_PERMS)

    fila = _fila(client_as(head).get(f"{URL}/body?status=converted").text, req)

    assert "/revocar" not in fila
    assert "<form" not in fila


@pytest.mark.parametrize("proc_status", ["completed", "cancelled"])
def test_un_proceso_no_revocable_no_ofrece_el_formulario(
    client_as, make_head, esc, proc_status,
):
    req, _proc = esc["inscrita"]("99660003", proc_status=proc_status)
    head = make_head(perm_codes=REVOKE_PERMS)

    fila = _fila(client_as(head).get(f"{URL}/body?status=converted").text, req)

    assert "/revocar" not in fila


def test_en_modo_alterno_la_fila_no_ofrece_revocar(client_as, make_head, esc, modo_alterno):
    req, _proc = esc["inscrita"]("99660004")
    head = make_head(perm_codes=REVOKE_PERMS)

    fila = _fila(client_as(head).get(f"{URL}/body?status=converted").text, req)

    assert "<form" not in fila


# ---------------------------------------------------------------------------
# Revocar
# ---------------------------------------------------------------------------
def test_revocar_cancela_el_proceso_y_la_fila_dice_el_motivo(
    client_as, db_session, make_head, esc, correos,
):
    req, proc = esc["inscrita"]("99660005")
    head = make_head(perm_codes=REVOKE_PERMS)

    resp = _post(client_as(head), req, reason="Documentación apócrifa",
                 cohort_id=str(esc["cohort"].id))

    assert resp.status_code == 200, _msg(resp)
    db_session.refresh(proc)
    assert proc.status == "cancelled"
    evs = _cancel_events(db_session, proc)
    assert len(evs) == 1 and evs[0].actor_id == head.id
    assert evs[0].payload["reason"] == "Documentación apócrifa"
    assert correos == [proc.id]
    # Repinta la pestaña donde estaba el oficial, con la fila ya revocada.
    assert 'id="tt-requests-body"' in resp.text
    assert re.search(r'id="tt-req-tab-converted"[^>]*aria-current="true"', resp.text)
    fila = _fila(resp.text, req)
    assert "Inscripción revocada: Documentación apócrifa" in _plano(fila)
    assert "/revocar" not in fila


def test_la_revocada_se_ve_tambien_en_todas(client_as, db_session, make_head, make_user, esc):
    from itcj2.apps.titulatec.services.process_service import ProcessService

    req, proc = esc["inscrita"]("99660006")
    ok, msg = ProcessService.cancel(db_session, proc.id, reason="Duplicada en el padrón",
                                    actor_id=make_user().id)
    assert ok, msg
    head = make_head(perm_codes=REVOKE_PERMS)

    fila = _fila(client_as(head).get(f"{URL}/body?status=all").text, req)

    assert "Inscripción revocada: Duplicada en el padrón" in _plano(fila)


def test_el_motivo_escapa_el_marcado(client_as, db_session, make_head, esc):
    req, _proc = esc["inscrita"]("99660007")
    head = make_head(perm_codes=REVOKE_PERMS)

    resp = _post(client_as(head), req, reason="<b>falso</b>")

    assert resp.status_code == 200, _msg(resp)
    fila = _fila(resp.text, req)
    assert "<b>falso</b>" not in fila
    assert "&lt;b&gt;falso&lt;/b&gt;" in fila


@pytest.mark.parametrize("motivo", ["", "   "])
def test_el_motivo_es_obligatorio(client_as, db_session, make_head, esc, correos, motivo):
    req, proc = esc["inscrita"]("99660008")
    head = make_head(perm_codes=REVOKE_PERMS)

    resp = _post(client_as(head), req, reason=motivo)

    assert resp.status_code == 400
    assert "motivo" in _msg(resp).lower()
    db_session.refresh(proc)
    assert proc.status == "active"
    assert correos == []


def test_sin_el_permiso_es_403(client_as, db_session, make_head, esc):
    req, proc = esc["inscrita"]("99660009")
    head = make_head(perm_codes=LIST_PERMS)

    resp = _post(client_as(head), req)

    assert resp.status_code == 403
    db_session.refresh(proc)
    assert proc.status == "active"


def test_fuera_de_alcance_es_404_liso(
    client_as, db_session, make_officer, make_program, esc,
):
    ajena = make_program("Carrera ajena a la revocacion")
    officer, _pos = make_officer([ajena], perm_codes=OFFICER_REVOKE_PERMS)
    req, proc = esc["inscrita"]("99660010")

    resp = _post(client_as(officer), req)

    assert resp.status_code == 404
    assert "X-Tt-Error" not in resp.headers
    db_session.refresh(proc)
    assert proc.status == "active"


def test_dentro_del_alcance_el_encargado_revoca(
    client_as, db_session, make_officer, esc,
):
    officer, _pos = make_officer([esc["prog"]], perm_codes=OFFICER_REVOKE_PERMS)
    req, proc = esc["inscrita"]("99660011")

    resp = _post(client_as(officer), req)

    assert resp.status_code == 200, _msg(resp)
    db_session.refresh(proc)
    assert proc.status == "cancelled"


def test_una_solicitud_inexistente_es_404(client_as, make_head):
    head = make_head(perm_codes=REVOKE_PERMS)

    resp = client_as(head).post(f"{URL}/987654321/revocar", data={"reason": "x"})

    assert resp.status_code == 404


@pytest.mark.parametrize("estado", ["pending_review", "approved", "rejected"])
def test_una_solicitud_sin_inscripcion_no_se_revoca(
    client_as, db_session, make_head, esc, estado,
):
    req = _make_req(db_session, esc["cohort"], control="99660012", status=estado,
                    program=esc["prog"])
    head = make_head(perm_codes=REVOKE_PERMS)

    resp = _post(client_as(head), req, status=estado)

    assert resp.status_code == 400
    assert "inscripción" in _msg(resp)


def test_una_inscrita_sin_proceso_no_se_revoca(client_as, make_head, esc):
    req, _ = esc["inscrita"]("99660013", with_process=False)
    head = make_head(perm_codes=REVOKE_PERMS)

    resp = _post(client_as(head), req)

    assert resp.status_code == 400
    assert "inscripción" in _msg(resp)


def test_revocar_dos_veces_responde_400_sin_volver_a_avisar(
    client_as, db_session, make_head, esc, correos,
):
    req, proc = esc["inscrita"]("99660014")
    c = client_as(make_head(perm_codes=REVOKE_PERMS))

    assert _post(c, req, reason="Primera").status_code == 200
    resp = _post(c, req, reason="Segunda")

    assert resp.status_code == 400
    assert "ya estaba revocada" in _msg(resp)
    assert len(_cancel_events(db_session, proc)) == 1
    assert correos == [proc.id]


def test_un_proceso_concluido_no_se_revoca(client_as, db_session, make_head, esc):
    req, proc = esc["inscrita"]("99660015", proc_status="completed")

    resp = _post(client_as(make_head(perm_codes=REVOKE_PERMS)), req)

    assert resp.status_code == 400
    assert "concluyó" in _msg(resp)
    db_session.refresh(proc)
    assert proc.status == "completed"


def test_en_modo_alterno_revocar_responde_400_sin_escribir(
    client_as, db_session, make_head, esc, modo_alterno, correos,
):
    req, proc = esc["inscrita"]("99660016")

    resp = _post(client_as(make_head(perm_codes=REVOKE_PERMS)), req)

    assert resp.status_code == 400
    assert "Centro de Cómputo" in _msg(resp)
    db_session.refresh(proc)
    assert proc.status == "active"
    assert correos == []
