"""Servicios Escolares deshace el rechazo de una solicitud (2026-10-06).

La persona va a ventanilla, aclara lo que motivó el rechazo y SE la regresa a
«Por revisar» con una nota de lo que se aclaró; desde ahí se aprueba por el
camino normal. Transición que fija este archivo:

    reopen() [SE]  rejected -> pending_review   (reopen_note, sin correo)

Lo del correo de rechazo que seguía en cola vive en `test_outbox_inscripcion.py`.
"""
from __future__ import annotations

import inspect
import re
from datetime import datetime, timedelta

import pytest

URL = "/titulatec/admin/solicitudes"
LIST_PERMS = (
    "titulatec.enrollment_request.page.list",
    "titulatec.enrollment_request.api.approve",
    "titulatec.enrollment_request.api.reject",
    "titulatec.process.api.read.all",
)
MSG_NOTA = "Escribe qué se aclaró con la persona."
MSG_NOTA_LARGA = "La nota no puede pasar de 2000 caracteres."
MSG_NO_RECHAZADA = "Esa solicitud ya no está rechazada."
MSG_OTRA_VIVA = "Esa persona ya tiene otra solicitud en curso en esta convocatoria; atiende esa."
MSG_OTRA_INSCRITA = "Esa persona ya quedó inscrita en esta convocatoria con otra solicitud."
MSG_CERRADA = "Esa convocatoria está cerrada."


def _svc():
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )
    return EnrollmentRequestService


@pytest.fixture()
def espia_helper(monkeypatch):
    """Ningún `send_*` del helper debe llamarse al deshacer."""
    from itcj2.apps.titulatec.services.email_helper import TitulaTecEmailHelper

    llamadas = []
    for nombre in [n for n in dir(TitulaTecEmailHelper) if n.startswith("send_")]:
        monkeypatch.setattr(
            TitulaTecEmailHelper, nombre,
            staticmethod(lambda *a, _n=nombre, **k: llamadas.append(_n) or True))
    return llamadas


def _make_req(db_session, cohort, *, control, status="rejected", **kw):
    from itcj2.apps.titulatec.models import EnrollmentRequest

    row = EnrollmentRequest(
        cohort_id=cohort.id, control_number=control,
        first_name="EGRESADA", last_name="DE VENTANILLA", middle_name=None,
        program_id=None, program_text="Ingenieria Ficticia",
        phone="6561234567", contact_email="ventanilla@example.invalid",
        has_efirma=True, kind="unknown", status=status, verify_send_count=0,
    )
    if status == "rejected":
        kw.setdefault("review_note", "No aparece en el padrón.")
        kw.setdefault("reviewed_at", datetime.now() - timedelta(days=1))
    for k, v in kw.items():
        setattr(row, k, v)
    db_session.add(row)
    db_session.flush()
    return row


# ---------------------------------------------------------------------------
# Servicio
# ---------------------------------------------------------------------------
def test_deshacer_regresa_a_por_revisar_con_la_nota_y_sin_correo(
    db_session, make_cohort, make_user, espia_helper,
):
    rechazo = make_user(first_name="QUIEN", last_name="RECHAZO")
    req = _make_req(db_session, make_cohort(status="open"), control="99607001",
                    reviewed_by_id=rechazo.id, rejection_sent_at=datetime.now())
    rechazado_en = req.reviewed_at
    se = make_user()

    ok = _svc().reopen(db_session, req.id, note="  Trajo su constancia de no adeudo.  ",
                       actor_id=se.id)

    assert ok == (True, "")
    db_session.refresh(req)
    assert req.status == "pending_review"
    assert req.reopen_note == "Trajo su constancia de no adeudo."
    assert req.reopened_by_id == se.id and req.reopened_at is not None
    # El rechazo deshecho se queda escrito hasta la siguiente resolución.
    assert req.review_note == "No aparece en el padrón."
    assert (req.reviewed_by_id, req.reviewed_at) == (rechazo.id, rechazado_en)
    assert req.rejection_sent_at is None, "el sello es del rechazo vigente"
    assert espia_helper == [], "la persona está en ventanilla: no se le avisa"


@pytest.mark.parametrize("nota", ["", "   ", None])
def test_deshacer_exige_nota(db_session, make_cohort, make_user, espia_helper, nota):
    req = _make_req(db_session, make_cohort(status="open"), control="99607002")

    assert _svc().reopen(db_session, req.id, note=nota,
                         actor_id=make_user().id) == (False, MSG_NOTA)
    db_session.refresh(req)
    assert req.status == "rejected" and req.reopened_at is None


def test_deshacer_rechaza_una_nota_de_mas_de_2000(db_session, make_cohort, make_user):
    req = _make_req(db_session, make_cohort(status="open"), control="99607003")

    assert _svc().reopen(db_session, req.id, note="x" * 2001,
                         actor_id=make_user().id) == (False, MSG_NOTA_LARGA)
    db_session.refresh(req)
    assert req.status == "rejected"


def test_deshacer_acepta_2000_exactos_tras_quitar_espacios(db_session, make_cohort,
                                                           make_user):
    req = _make_req(db_session, make_cohort(status="open"), control="99607004")

    ok, _ = _svc().reopen(db_session, req.id, note="  " + "x" * 2000 + "  ",
                          actor_id=make_user().id)

    assert ok is True and req.reopen_note == "x" * 2000


@pytest.mark.parametrize("status", ["pending_review", "approved", "awaiting_access",
                                    "converted"])
def test_solo_se_deshace_una_rechazada(db_session, make_cohort, make_user, status):
    req = _make_req(db_session, make_cohort(status="open"), control="99607005",
                    status=status)

    assert _svc().reopen(db_session, req.id, note="Aclaró.",
                         actor_id=make_user().id) == (False, MSG_NO_RECHAZADA)
    db_session.refresh(req)
    assert req.status == status and req.reopened_at is None


def test_no_se_deshace_con_la_convocatoria_cerrada(db_session, make_cohort, make_user):
    req = _make_req(db_session, make_cohort(status="closed"), control="99607006")

    assert _svc().reopen(db_session, req.id, note="Aclaró.",
                         actor_id=make_user().id) == (False, MSG_CERRADA)
    db_session.refresh(req)
    assert req.status == "rejected"


@pytest.mark.parametrize("viva", ["pending_review", "approved", "awaiting_access"])
def test_no_se_deshace_si_ya_mando_otra_solicitud(db_session, make_cohort, make_user, viva):
    """Tras el rechazo la persona volvió a solicitar: esa es la que se atiende.
    Reabrir la vieja chocaría con el índice parcial de solicitudes vivas."""
    cohort = make_cohort(status="open")
    vieja = _make_req(db_session, cohort, control="99607007")
    _make_req(db_session, cohort, control="99607007", status=viva)

    assert _svc().reopen(db_session, vieja.id, note="Aclaró.",
                         actor_id=make_user().id) == (False, MSG_OTRA_VIVA)
    db_session.refresh(vieja)
    assert vieja.status == "rejected" and vieja.reopened_at is None


def test_no_se_deshace_si_ya_quedo_inscrita_con_otra(db_session, make_cohort, make_user):
    cohort = make_cohort(status="open")
    vieja = _make_req(db_session, cohort, control="99607008")
    _make_req(db_session, cohort, control="99607008", status="converted")

    assert _svc().reopen(db_session, vieja.id, note="Aclaró.",
                         actor_id=make_user().id) == (False, MSG_OTRA_INSCRITA)
    db_session.refresh(vieja)
    assert vieja.status == "rejected"


def test_otra_rechazada_o_de_otra_convocatoria_no_estorba(db_session, make_cohort,
                                                          make_user):
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99607009")
    _make_req(db_session, cohort, control="99607009")                       # rechazada
    _make_req(db_session, make_cohort(status="open"), control="99607009",
              status="pending_review")                                     # otra conv.

    assert _svc().reopen(db_session, req.id, note="Aclaró.",
                         actor_id=make_user().id) == (True, "")


def test_reopen_toma_lock_y_refresca_antes_de_leer_status():
    src = inspect.getsource(_svc().reopen)
    _, _, cuerpo = src.partition('"""')
    _, _, cuerpo = cuerpo.partition('"""')
    lock_pos = cuerpo.index("pg_advisory_xact_lock")
    refresh_pos = cuerpo.index("db.refresh(req)")
    assert lock_pos < refresh_pos < cuerpo.index("req.status")


def test_la_migracion_declara_las_columnas_del_modelo():
    from pathlib import Path

    from itcj2.apps.titulatec.models import EnrollmentRequest

    cols = EnrollmentRequest.__table__.c
    assert {"reopened_by_id", "reopened_at", "reopen_note"} <= set(cols.keys())
    fk, = cols.reopened_by_id.foreign_keys
    assert fk.target_fullname == "core_users.id"
    src = (Path(__file__).resolve().parents[3] / "migrations" / "versions"
           / "tt20261006a_titulatec_enrollment_reopen.py").read_text(encoding="utf-8")
    for col in ("reopened_by_id", "reopened_at", "reopen_note"):
        assert f'"{col}"' in src
    assert 'down_revision = "tt20261005d"' in src


# ---------------------------------------------------------------------------
# Bandeja (ruta y plantilla)
# ---------------------------------------------------------------------------
def _fila(html: str, req) -> str:
    marca = f'id="tt-req-{req.id}"'
    assert marca in html, f"no está la fila de la solicitud {req.id}"
    return html.split(marca, 1)[1].split("</tr>", 1)[0]


def test_la_rechazada_ofrece_deshacer_el_rechazo(client_as, db_session, make_head,
                                                 make_cohort):
    head = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99607020")

    fila = _fila(client_as(head).get(
        f"{URL}/body?status=rejected&cohort_id={cohort.id}").text, req)

    assert f'hx-post="/titulatec/admin/solicitudes/{req.id}/reabrir"' in fila
    assert 'name="note"' in fila and "Deshacer rechazo" in fila


def test_deshacer_desde_la_bandeja_la_manda_a_por_revisar_con_la_nota(
    client_as, db_session, make_head, make_cohort, espia_helper,
):
    head = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99607021")
    c = client_as(head)

    resp = c.post(f"{URL}/{req.id}/reabrir",
                  data={"note": "Aclaró en ventanilla su carrera.", "status": "rejected",
                        "cohort_id": str(cohort.id)})

    assert resp.status_code == 200, resp.headers.get("X-Tt-Error")
    assert f'id="tt-req-{req.id}"' not in resp.text, "se va de la pestaña Rechazadas"
    assert resp.headers.get("X-Tt-Notice-Kind") == "success"
    pendientes = c.get(f"{URL}/body?status=pending_review&cohort_id={cohort.id}").text
    fila = _fila(pendientes, req)
    assert "Rechazo deshecho" in fila
    assert "Aclaró en ventanilla su carrera." in fila
    assert f'hx-post="/titulatec/admin/solicitudes/{req.id}/aprobar"' in fila
    db_session.refresh(req)
    assert req.status == "pending_review" and req.reopened_by_id == head.id
    assert espia_helper == []


def test_deshacer_sin_nota_responde_400_sin_escribir(client_as, db_session, make_head,
                                                     make_cohort):
    head = make_head(perm_codes=LIST_PERMS)
    req = _make_req(db_session, make_cohort(status="open"), control="99607022")

    resp = client_as(head).post(f"{URL}/{req.id}/reabrir", data={"note": "  "})

    assert resp.status_code == 400
    assert resp.headers.get("X-Tt-Error")
    db_session.refresh(req)
    assert req.status == "rejected"


def test_el_motivo_del_servicio_llega_al_oficial(client_as, db_session, make_head,
                                                 make_cohort):
    head = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    vieja = _make_req(db_session, cohort, control="99607023")
    _make_req(db_session, cohort, control="99607023", status="pending_review")

    resp = client_as(head).post(f"{URL}/{vieja.id}/reabrir", data={"note": "Aclaró."})

    assert resp.status_code == 400
    from urllib.parse import unquote
    assert unquote(resp.headers["X-Tt-Error"]) == MSG_OTRA_VIVA


def test_sin_permiso_de_rechazar_no_se_deshace(client_as, db_session, make_head,
                                               make_cohort):
    solo_ve = make_head(perm_codes=("titulatec.enrollment_request.page.list",
                                    "titulatec.process.api.read.all"))
    req = _make_req(db_session, make_cohort(status="open"), control="99607024")

    resp = client_as(solo_ve).post(f"{URL}/{req.id}/reabrir", data={"note": "Aclaró."})

    assert resp.status_code in (302, 303, 403)
    db_session.refresh(req)
    assert req.status == "rejected"


def test_en_modo_alterno_no_se_deshace(client_as, db_session, make_head, make_cohort,
                                       modo_alterno):
    head = make_head(perm_codes=LIST_PERMS)
    req = _make_req(db_session, make_cohort(status="open"), control="99607025")

    resp = client_as(head).post(f"{URL}/{req.id}/reabrir", data={"note": "Aclaró."})

    assert resp.status_code == 400
    db_session.refresh(req)
    assert req.status == "rejected"
