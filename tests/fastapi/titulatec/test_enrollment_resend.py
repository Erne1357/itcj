"""Reenvío de la liga de activación: público y de bandeja.

La liga de contacto ("confirma tu correo") se retiró el 2026-09-15 con su ruta,
su método y su plantilla; lo que la fija ahora vive en
`test_enrollment_identity_chain.py` y `test_enrollment_request_service.py`.

Dos reenvíos con reglas opuestas, a propósito:

- PÚBLICO (`POST /titulatec/inscripcion/reenviar`, anónimo). La llave es
  (control, correo), nunca el `id` (secuencial y enumerable). Solo actúa sobre
  solicitudes `approved` y NO ROTA el token: rotarlo dejaría a un extraño matar
  la liga pendiente de otra persona. Reenvía el mismo claro, que vive en Redis
  (la BD guarda el sha256, E7). Presupuesto por solicitud, y la tarjeta es la
  misma case o no case (§6.8): cualquier diferencia sería un oráculo de
  existencia.
- BANDEJA (`POST /titulatec/admin/solicitudes/{id}/reenviar`). El actor está
  autenticado y acotado por carrera, así que SÍ ROTA: hash nuevo, vencimiento
  nuevo, la liga vieja deja de servir.
"""
from __future__ import annotations

import hashlib
import re
import secrets
from datetime import datetime, timedelta
from urllib.parse import unquote

import pytest

RESEND_URL = "/titulatec/inscripcion/reenviar"
ADMIN_URL = "/titulatec/admin/solicitudes"
TARJETA_REENVIO = ("Si esos datos corresponden a una solicitud aprobada, te reenviamos "
                   "la liga. Revisa también el correo no deseado.")

LIST_PERMS = (
    "titulatec.enrollment_request.page.list",
    "titulatec.enrollment_request.api.approve",
    "titulatec.enrollment_request.api.reject",
    "titulatec.process.api.read.all",
)


@pytest.fixture()
def correo_falso(monkeypatch):
    """Captura los envíos sin tocar Graph: `(asunto, destinatarios, html)`."""
    enviados = []

    class _Resp:
        status_code = 202
        text = ""

    def _fake_send(access_token, subject, content_html, to_list, save_to_sent=True):
        enviados.append((subject, list(to_list), content_html))
        return _Resp()

    monkeypatch.setattr("itcj2.core.utils.msgraph_mail.acquire_token_silent",
                        lambda app_key: "token-de-prueba")
    monkeypatch.setattr("itcj2.core.utils.msgraph_mail.graph_send_mail", _fake_send)
    return enviados


def _solo_esta_convocatoria(db_session, cohort):
    """Deja `cohort` como la ÚNICA abierta (ver test_enrollment_public.py)."""
    from itcj2.apps.titulatec.models import Cohort
    (db_session.query(Cohort)
     .filter(Cohort.id != cohort.id)
     .update({Cohort.status: "closed"}, synchronize_session=False))
    db_session.flush()


def _aprobada(db_session, cohort, *, control, status="approved",
              email="alguien@example.invalid", seed_cache=True, **kw):
    """Solicitud con liga emitida. `(req, token)`.

    `seed_cache` es un parámetro EXPLÍCITO, no un `**kw`: los `kw` se aplican
    con `setattr` sobre la fila y una columna con ese nombre no existe.
    """
    from itcj2.apps.titulatec.models import EnrollmentRequest
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        _token_cache_get, _token_cache_put,
    )

    token = secrets.token_urlsafe(32)
    row = EnrollmentRequest(
        cohort_id=cohort.id, control_number=control,
        first_name="ALUMNA", last_name="INVENTADA", middle_name=None,
        program_id=None, program_text="Ingenieria Ficticia",
        phone="6561234567", contact_email=email,
        has_efirma=False, kind="known", status=status,
        verify_token_hash=hashlib.sha256(token.encode("utf-8")).hexdigest(),
        verify_expires_at=datetime.now() + timedelta(days=6),
        verify_sent_at=datetime.now() - timedelta(hours=1),
        verify_send_count=1, verify_sent_to=email,
    )
    for k, v in kw.items():
        setattr(row, k, v)
    db_session.add(row)
    db_session.flush()
    if seed_cache:
        _token_cache_put(token)
        assert _token_cache_get(row.verify_token_hash) == token, (
            "Redis no guardó el claro del token: sin él el reenvío público no es "
            "verificable")
    return row, token


def _cuenta(db_session, control):
    from itcj2.core.models.user import User
    from itcj2.core.utils.security import hash_nip

    user = User(username=control, control_number=control, first_name="ALUMNA",
                last_name="REAL", password_hash=hash_nip("9999"), is_active=True)
    db_session.add(user)
    db_session.flush()
    return user


def _token_de_la_liga(html: str) -> str:
    return html.split("/inscripcion/verificar?t=", 1)[1].split('"', 1)[0]


# `x-request-id` lo añade ObservabilityMiddleware a toda respuesta: aleatorio
# por petición, con la MISMA distribución en todas las ramas (R26). Su valor no
# distingue nada, así que se compara solo su FORMA; que faltara en una rama (un
# 500 que sale por fuera del middleware, p. ej.) sí la delataría.
_REQUEST_ID = re.compile(r"[0-9a-f]{32}")


def _h(resp):
    """Cabeceras comparables byte a byte entre ramas: fuera `date` (puede
    saltar de segundo) y `x-request-id` reducido a su forma (ver arriba)."""
    return {
        k.lower(): (
            "<request-id>"
            if k.lower() == "x-request-id" and _REQUEST_ID.fullmatch(v)
            else v
        )
        for k, v in resp.headers.items()
        if k.lower() != "date"
    }


# ===========================================================================
# Reenvío PÚBLICO: solo `approved`, sin rotar, con presupuesto
# ===========================================================================
def test_el_reenvio_publico_de_una_aprobada_manda_la_misma_liga(
    client, db_session, make_cohort, correo_falso,
):
    cohort = make_cohort(status="open")
    _solo_esta_convocatoria(db_session, cohort)
    req, token = _aprobada(db_session, cohort, control="99660001")
    hash_antes, vence_antes = req.verify_token_hash, req.verify_expires_at
    client.cookies.clear()

    resp = client.post(RESEND_URL,
                       data={"control_number": "99660001",
                             "contact_email": "ALGUIEN@example.invalid"},
                       headers={"X-Real-IP": "203.0.113.31"}, follow_redirects=False)

    assert resp.status_code == 200, resp.text[:400]
    assert 'data-tt-notice="generic"' in resp.text
    assert TARJETA_REENVIO in " ".join(resp.text.split())
    db_session.refresh(req)
    assert req.verify_send_count == 2
    assert req.verify_token_hash == hash_antes, "el reenvío anónimo NUNCA rota"
    assert req.verify_expires_at == vence_antes, "ni alarga la vida de la liga"
    (_asunto, destinatarios, html), = correo_falso
    assert destinatarios == ["alguien@example.invalid"]
    assert _token_de_la_liga(html) == token


def test_sin_el_claro_en_redis_el_reenvio_falla_cerrado_y_no_rota(
    client, db_session, make_cohort, correo_falso,
):
    cohort = make_cohort(status="open")
    _solo_esta_convocatoria(db_session, cohort)
    req, _tok = _aprobada(db_session, cohort, control="99660007", seed_cache=False)
    hash_antes = req.verify_token_hash
    client.cookies.clear()

    resp = client.post(RESEND_URL,
                       data={"control_number": "99660007",
                             "contact_email": "alguien@example.invalid"},
                       headers={"X-Real-IP": "203.0.113.37"}, follow_redirects=False)

    assert resp.status_code == 200, resp.text[:400]
    assert 'data-tt-notice="generic"' in resp.text
    db_session.refresh(req)
    assert req.verify_token_hash == hash_antes
    assert req.verify_send_count == 1
    assert correo_falso == []


@pytest.mark.parametrize("status", ["pending_review", "converted", "rejected",
                                    "unverified", "verified"])
def test_el_reenvio_publico_ignora_lo_que_no_esta_aprobado(
    client, db_session, make_cohort, correo_falso, status,
):
    cohort = make_cohort(status="open")
    _solo_esta_convocatoria(db_session, cohort)
    req, _tok = _aprobada(db_session, cohort, control="99660004", status=status)
    client.cookies.clear()

    resp = client.post(RESEND_URL,
                       data={"control_number": "99660004",
                             "contact_email": "alguien@example.invalid"},
                       headers={"X-Real-IP": "203.0.113.35"}, follow_redirects=False)

    assert resp.status_code == 200, resp.text[:300]
    db_session.refresh(req)
    assert req.verify_send_count == 1
    assert req.status == status
    assert correo_falso == []


def test_con_tres_envios_el_reenvio_publico_ya_no_sale_y_no_manda_a_revision(
    client, db_session, make_cohort, correo_falso,
):
    """Antes, tres envíos sin respuesta mandaban la solicitud a la bandeja con una
    nota que el sistema escribía sobre sí mismo. Ya no: la bandeja reenvía."""
    cohort = make_cohort(status="open")
    _solo_esta_convocatoria(db_session, cohort)
    req, _tok = _aprobada(db_session, cohort, control="99660006", verify_send_count=3)
    client.cookies.clear()

    resp = client.post(RESEND_URL,
                       data={"control_number": "99660006",
                             "contact_email": "alguien@example.invalid"},
                       headers={"X-Real-IP": "203.0.113.36"}, follow_redirects=False)

    assert resp.status_code == 200, resp.text[:400]
    db_session.refresh(req)
    assert req.verify_send_count == 3
    assert req.status == "approved"
    assert req.review_note is None
    assert correo_falso == []


def test_el_reenvio_publico_respeta_el_minimo_entre_envios(
    db_session, make_cohort, correo_falso,
):
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )

    cohort = make_cohort(status="open")
    req, _tok = _aprobada(db_session, cohort, control="99660008",
                          verify_sent_at=datetime.now())

    assert EnrollmentRequestService.resend(
        db_session, "99660008", "alguien@example.invalid") == "noop"
    assert req.verify_send_count == 1
    assert correo_falso == []


def test_con_la_convocatoria_cerrada_el_reenvio_publico_no_sale(
    db_session, make_cohort, correo_falso,
):
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )

    cohort = make_cohort(status="closed")
    _aprobada(db_session, cohort, control="99660009")

    assert EnrollmentRequestService.resend(
        db_session, "99660009", "alguien@example.invalid") == "noop"
    assert correo_falso == []


def test_reenvio_que_no_casa_da_salida_identica_al_que_si_casa(
    client, db_session, make_cohort, correo_falso,
):
    cohort = make_cohort(status="open")
    _solo_esta_convocatoria(db_session, cohort)
    req, _tok = _aprobada(db_session, cohort, control="99660002")
    client.cookies.clear()

    r_casa = client.post(RESEND_URL,
                         data={"control_number": "99660002",
                               "contact_email": "alguien@example.invalid"},
                         headers={"X-Real-IP": "203.0.113.32"}, follow_redirects=False)
    r_no_casa = client.post(RESEND_URL,
                            data={"control_number": "99660002",
                                  "contact_email": "otro@example.invalid"},
                            headers={"X-Real-IP": "203.0.113.33"}, follow_redirects=False)

    assert r_casa.status_code == r_no_casa.status_code == 200
    assert r_casa.content == r_no_casa.content
    db_session.refresh(req)
    assert req.verify_send_count == 2      # el que NO casa no consumió envío


def test_el_id_de_la_solicitud_no_sirve_como_llave(
    client, db_session, make_cohort, correo_falso,
):
    cohort = make_cohort(status="open")
    _solo_esta_convocatoria(db_session, cohort)
    req, _tok = _aprobada(db_session, cohort, control="99660003")
    client.cookies.clear()

    resp = client.post(RESEND_URL, data={"request_id": str(req.id)},
                       headers={"X-Real-IP": "203.0.113.34"}, follow_redirects=False)

    assert resp.status_code == 200, resp.text[:400]
    db_session.refresh(req)
    assert req.verify_send_count == 1
    assert correo_falso == []


def test_sent_noop_y_trampa_del_reenvio_son_identicos_byte_a_byte(
    client, db_session, make_cohort, correo_falso,
):
    """R4: 'sent', 'noop' y la trampa -tercera salida- devuelven los MISMOS
    bytes y las MISMAS cabeceras."""
    cohort = make_cohort(status="open")
    _solo_esta_convocatoria(db_session, cohort)
    req, _tok = _aprobada(db_session, cohort, control="99660020")
    client.cookies.clear()

    r_sent = client.post(RESEND_URL,
                         data={"control_number": "99660020",
                               "contact_email": "alguien@example.invalid"},
                         headers={"X-Real-IP": "203.0.113.50"}, follow_redirects=False)
    r_noop = client.post(RESEND_URL,
                         data={"control_number": "00000000",
                               "contact_email": "nadie@example.invalid"},
                         headers={"X-Real-IP": "203.0.113.51"}, follow_redirects=False)
    r_trampa = client.post(RESEND_URL,
                           data={"control_number": "99660021",
                                 "contact_email": "otro@example.invalid",
                                 "website": "http://spam.example"},
                           headers={"X-Real-IP": "203.0.113.52"}, follow_redirects=False)

    assert r_sent.status_code == r_noop.status_code == r_trampa.status_code == 200
    assert r_sent.content == r_noop.content == r_trampa.content
    assert _h(r_sent) == _h(r_noop) == _h(r_trampa)
    db_session.refresh(req)
    assert req.verify_send_count == 2, "el envio que SI casa debio escribir"


def test_los_presupuestos_del_reenvio_son_los_acordados():
    """R3: 10/hora por IP (no 3 como traía el borrador del brief)."""
    from itcj2.apps.titulatec.pages import public as mod

    assert mod.ENROLL_RESEND_RL_LIMIT_IP == 10
    assert mod.ENROLL_RESEND_RL_WINDOW_IP == 3600


def test_el_presupuesto_por_ip_se_cobra_aunque_el_envio_sea_noop(
    client, db_session, make_cohort, monkeypatch,
):
    """R3: el cubo se cobra EN LA PUERTA, siempre. Si solo cobrara el envío real,
    el tiempo de vaciado del cubo delataría si un número de control existe."""
    from itcj2.apps.titulatec.pages import public as mod

    monkeypatch.setattr(mod, "ENROLL_RESEND_RL_LIMIT_IP", 2)
    cohort = make_cohort(status="open")
    _solo_esta_convocatoria(db_session, cohort)
    client.cookies.clear()
    headers = {"X-Real-IP": "203.0.113.53"}

    for _ in range(2):
        r = client.post(RESEND_URL, data={"control_number": "00000000",
                                          "contact_email": "nadie@example.invalid"},
                        headers=headers, follow_redirects=False)
        assert r.status_code == 200

    r3 = client.post(RESEND_URL, data={"control_number": "00000000",
                                       "contact_email": "nadie@example.invalid"},
                     headers=headers, follow_redirects=False)
    assert r3.headers.get("Retry-After") is not None


# ===========================================================================
# Reenvío desde la BANDEJA: solo `approved`, rota la liga
# ===========================================================================
def test_reenviar_desde_la_bandeja_rota_la_liga_y_la_vieja_deja_de_servir(
    client_as, db_session, make_head, make_cohort, seed_phase_defs, titulatec_app,
    correo_falso,
):
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService, _token_cache_get,
    )

    seed_phase_defs()
    head = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    _cuenta(db_session, "99660030")
    req, viejo = _aprobada(db_session, cohort, control="99660030",
                           email="personal@example.invalid",
                           verified_at=datetime.now() - timedelta(minutes=5))
    hash_viejo, vence_viejo = req.verify_token_hash, req.verify_expires_at

    resp = client_as(head).post(f"{ADMIN_URL}/{req.id}/reenviar")

    assert resp.status_code == 200, resp.headers.get("X-Tt-Error")
    db_session.refresh(req)
    assert req.status == "approved"
    assert req.verify_token_hash != hash_viejo
    assert req.verify_expires_at > vence_viejo
    assert req.verify_send_count == 2
    assert req.verified_at is None, "«abierta» habla de la liga vigente, no de la vieja"
    (_asunto, destinatarios, html), = correo_falso
    assert destinatarios == ["personal@example.invalid"]
    nuevo = _token_de_la_liga(html)
    assert hashlib.sha256(nuevo.encode("utf-8")).hexdigest() == req.verify_token_hash
    assert _token_cache_get(hash_viejo) is None
    assert _token_cache_get(req.verify_token_hash) == nuevo

    assert EnrollmentRequestService.verify(db_session, viejo)[1] == "invalid"
    assert EnrollmentRequestService.verify(db_session, nuevo)[1] == "converted"


@pytest.mark.parametrize("status", ["pending_review", "converted", "rejected",
                                    "unverified", "verified"])
def test_reenviar_desde_la_bandeja_solo_aplica_a_aprobadas(
    client_as, db_session, make_head, make_cohort, correo_falso, status,
):
    head = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    req, _tok = _aprobada(db_session, cohort, control="99660031", status=status)
    hash_antes = req.verify_token_hash

    resp = client_as(head).post(f"{ADMIN_URL}/{req.id}/reenviar")

    assert resp.status_code == 400
    assert (unquote(resp.headers["X-Tt-Error"])
            == "Solo se reenvía la liga de solicitudes aprobadas.")
    db_session.refresh(req)
    assert req.status == status
    assert req.verify_token_hash == hash_antes
    assert req.verify_send_count == 1
    assert correo_falso == []


def test_resend_link_toma_lock_y_refresca_antes_de_leer_status():
    import inspect

    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )

    src = inspect.getsource(EnrollmentRequestService.resend_link)
    _, _, cuerpo = src.partition('"""')
    _, _, cuerpo = cuerpo.partition('"""')
    lock_pos = cuerpo.index("pg_advisory_xact_lock")
    refresh_pos = cuerpo.index("db.refresh(req)")
    assert lock_pos < refresh_pos < cuerpo.index("req.status")
