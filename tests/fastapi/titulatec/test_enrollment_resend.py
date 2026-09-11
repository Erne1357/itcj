"""Reenvío de la liga y confirmación del correo personal (§6.8, D17).

La llave del reenvío es SIEMPRE (control_number, contact_email). El `id` de la
solicitud es un BigInteger secuencial: aceptarlo dejaría a cualquiera enumerar
1..N y bombardear buzones ajenos desde el buzón del instituto.

§6.8 exige además que el reenvío **no rote el token**: rotarlo dejaría a un
extraño invalidar la liga pendiente de un solicitante real. La BD guarda solo el
`sha256` (E7), así que el claro vive en Redis mientras dura su ventana; por eso
`_make_req` lo siembra ahí. La rama sin caché es fallo cerrado —no reenvía, no
consume envío, no rota— y sale con la MISMA tarjeta genérica que el reenvío que
sí sale: cualquier tarjeta distinta sería un oráculo de existencia.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta


def _solo_esta_convocatoria(db_session, cohort):
    """Deja `cohort` como la ÚNICA abierta (ver test_enrollment_public.py)."""
    from itcj2.apps.titulatec.models import Cohort
    (db_session.query(Cohort)
     .filter(Cohort.id != cohort.id)
     .update({Cohort.status: "closed"}, synchronize_session=False))
    db_session.flush()


def _make_req(db_session, cohort, *, control, kind="known", status="unverified",
              email="alguien@example.invalid", seed_cache=True, **kw):
    """Solicitud a mano. `seed_cache=False` deja a `_send_verify` sin el claro.

    `seed_cache` es un parámetro EXPLÍCITO, no un `**kw`: los `kw` se aplican con
    `setattr` sobre la fila y una columna llamada así no existe.

    HALLAZGO PROPIO (no es uno de los 4 rulings del despacho, pero toca la misma
    familia — destinatario del token): para `kind="known"` (el default),
    `_send_verify` solo reenvía si `TitulaTecEmailHelper.verify_recipient`
    resuelve un institucional CONTRA LA BD (RULING R5 de la Tarea 19 — el
    destinatario de un `known` nunca sale de `req.contact_email`, que es
    precisamente el hueco que D17 existe para cerrar). El borrador del brief no
    creaba el `User` correspondiente: con él ausente, TODO reenvío de un
    `known` fallaba cerrado por falta de destinatario, no por lo que cada test
    dice estar ejerciendo (verificado corriendo
    `test_reenvio_que_casa_incrementa_el_contador_sin_rotar_el_token` contra el
    borrador literal: `assert 1 == 2`, el envío nunca salía). Se crea aquí,
    idempotente por `control_number` -algunos tests además llaman a
    `make_student` con el MISMO control-, para que los tests que esperan un
    envío exitoso ejerzan de verdad esa rama.
    """
    from itcj2.apps.titulatec.models import EnrollmentRequest
    from itcj2.apps.titulatec.services.enrollment_request_service import VERIFY_TTL_HOURS

    if kind == "known":
        from itcj2.core.models.user import User
        if db_session.query(User).filter_by(control_number=control).first() is None:
            db_session.add(User(
                first_name="ALUMNA", last_name="INVENTADA",
                username=f"tt_test_resend_{control}", control_number=control,
                email=f"tt.test.resend.{control}@example.invalid", is_active=True,
            ))
            db_session.flush()

    token = secrets.token_urlsafe(32)
    row = EnrollmentRequest(
        cohort_id=cohort.id, control_number=control,
        first_name="ALUMNA", last_name="INVENTADA", middle_name=None,
        program_id=None, program_text=None,
        phone="6561234567", contact_email=email,
        has_efirma=False, kind=kind, status=status,
        verify_token_hash=hashlib.sha256(token.encode("utf-8")).hexdigest(),
        verify_expires_at=datetime.now() + timedelta(hours=VERIFY_TTL_HOURS),
        verify_sent_at=datetime.now() - timedelta(seconds=3600),
        verify_send_count=1, verify_sent_to="alumna@cdjuarez.tecnm.mx",
    )
    for k, v in kw.items():
        setattr(row, k, v)
    db_session.add(row)
    db_session.flush()

    if seed_cache:
        # §6.8: «el reenvío NO rota el token». `_send_verify` reenvía EL MISMO
        # claro, que solo vive en Redis (la BD guarda el sha256, E7). Sin esta
        # siembra toda llamada caería en la rama de fallo cerrado y la prueba
        # mediría el camino equivocado. Se relee para que una caída de Redis
        # falle como error de PREPARACIÓN y no como un desconcertante desajuste
        # de hashes: `_token_cache_put` se traga cualquier excepción.
        from itcj2.apps.titulatec.services.enrollment_request_service import (
            _token_cache_get, _token_cache_put,
        )
        _token_cache_put(token)
        assert _token_cache_get(row.verify_token_hash) == token, (
            "Redis no guardo el claro del token: el invariante «el reenvio no "
            "rota» (§6.8) no es verificable sin el cache"
        )
    return row, token


def test_reenvio_que_casa_incrementa_el_contador_sin_rotar_el_token(
    client, db_session, make_cohort,
):
    """No rota: rotarlo dejaría a un extraño invalidar la liga de un solicitante real."""
    cohort = make_cohort(status="open")
    _solo_esta_convocatoria(db_session, cohort)
    req, _tok = _make_req(db_session, cohort, control="99660001")
    hash_antes = req.verify_token_hash
    expira_antes = req.verify_expires_at
    client.cookies.clear()

    resp = client.post("/titulatec/inscripcion/reenviar",
                       data={"control_number": "99660001",
                             "contact_email": "alguien@example.invalid"},
                       headers={"X-Real-IP": "203.0.113.31"},
                       follow_redirects=False)

    assert resp.status_code == 200, resp.text[:400]
    db_session.refresh(req)
    assert req.verify_send_count == 2
    assert req.verify_token_hash == hash_antes
    assert req.verify_expires_at > expira_antes


def test_sin_el_claro_en_redis_el_reenvio_falla_cerrado_y_no_rota(
    client, db_session, make_cohort,
):
    """Sin el claro en Redis NO hay reenvío, y la salida es la MISMA tarjeta.

    `_send_verify` devuelve `False` en la falta de caché (§6.8: rotar el token
    dejaría a un extraño invalidar la liga pendiente de un solicitante real), y
    `resend` lo convierte en `'noop'`. La respuesta sigue siendo `_RESEND_CARD`
    (`notice_key="generic"`), idéntica a la del reenvío que sí sale: §6.8 exige
    salida indistinguible y una tarjeta propia para este caso sería un oráculo
    de existencia.
    """
    cohort = make_cohort(status="open")
    _solo_esta_convocatoria(db_session, cohort)
    req, _tok = _make_req(db_session, cohort, control="99660007", seed_cache=False)
    hash_antes = req.verify_token_hash
    client.cookies.clear()

    resp = client.post("/titulatec/inscripcion/reenviar",
                       data={"control_number": "99660007",
                             "contact_email": "alguien@example.invalid"},
                       headers={"X-Real-IP": "203.0.113.37"},
                       follow_redirects=False)

    assert resp.status_code == 200, resp.text[:400]
    assert 'data-tt-notice="generic"' in resp.text
    db_session.refresh(req)
    assert req.verify_token_hash == hash_antes    # no rotó
    assert req.verify_send_count == 1             # no consumió el envío


def test_reenvio_que_no_casa_da_salida_identica_al_que_si_casa(
    client, db_session, make_cohort,
):
    cohort = make_cohort(status="open")
    _solo_esta_convocatoria(db_session, cohort)
    req, _tok = _make_req(db_session, cohort, control="99660002")
    client.cookies.clear()

    r_casa = client.post("/titulatec/inscripcion/reenviar",
                         data={"control_number": "99660002",
                               "contact_email": "alguien@example.invalid"},
                         headers={"X-Real-IP": "203.0.113.32"},
                         follow_redirects=False)
    r_no_casa = client.post("/titulatec/inscripcion/reenviar",
                            data={"control_number": "99660002",
                                  "contact_email": "otro@example.invalid"},
                            headers={"X-Real-IP": "203.0.113.33"},
                            follow_redirects=False)

    assert r_casa.status_code == r_no_casa.status_code == 200
    assert r_casa.content == r_no_casa.content
    db_session.refresh(req)
    assert req.verify_send_count == 2      # el que NO casa no consumió envío


def test_el_id_de_la_solicitud_no_sirve_como_llave(client, db_session, make_cohort):
    cohort = make_cohort(status="open")
    _solo_esta_convocatoria(db_session, cohort)
    req, _tok = _make_req(db_session, cohort, control="99660003")
    client.cookies.clear()

    resp = client.post("/titulatec/inscripcion/reenviar",
                       data={"request_id": str(req.id)},
                       headers={"X-Real-IP": "203.0.113.34"},
                       follow_redirects=False)

    assert resp.status_code == 200, resp.text[:400]
    db_session.refresh(req)
    assert req.verify_send_count == 1      # nada se envió


def test_convertida_y_en_revision_no_consumen_envio(client, db_session, make_cohort):
    cohort = make_cohort(status="open")
    _solo_esta_convocatoria(db_session, cohort)
    conv, _t1 = _make_req(db_session, cohort, control="99660004", status="converted")
    rev, _t2 = _make_req(db_session, cohort, control="99660005", status="pending_review")
    client.cookies.clear()

    for control in ("99660004", "99660005"):
        r = client.post("/titulatec/inscripcion/reenviar",
                        data={"control_number": control,
                              "contact_email": "alguien@example.invalid"},
                        headers={"X-Real-IP": "203.0.113.35"},
                        follow_redirects=False)
        assert r.status_code == 200, r.text[:300]

    db_session.refresh(conv)
    db_session.refresh(rev)
    assert conv.verify_send_count == 1
    assert rev.verify_send_count == 1


def test_tras_tres_envios_sin_verificar_un_conocido_cae_a_revision(
    client, db_session, make_cohort,
):
    """El token NUNCA se manda al correo personal de un `known` (D17)."""
    cohort = make_cohort(status="open")
    _solo_esta_convocatoria(db_session, cohort)
    req, _tok = _make_req(db_session, cohort, control="99660006",
                          verify_send_count=3, verified_at=None)
    client.cookies.clear()

    resp = client.post("/titulatec/inscripcion/reenviar",
                       data={"control_number": "99660006",
                             "contact_email": "alguien@example.invalid"},
                       headers={"X-Real-IP": "203.0.113.36"},
                       follow_redirects=False)

    assert resp.status_code == 200, resp.text[:400]
    db_session.refresh(req)
    assert req.verify_send_count == 3      # no consumió un cuarto
    assert req.status == "pending_review"


def _con_token_de_contacto(db_session, req):
    """Le pone a `req` un token de contacto y devuelve el claro."""
    from itcj2.apps.titulatec.services.enrollment_request_service import CONTACT_TTL_HOURS

    raw = secrets.token_urlsafe(32)
    req.contact_token_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    req.contact_expires_at = datetime.now() + timedelta(hours=CONTACT_TTL_HOURS)
    db_session.flush()
    return raw


def test_confirmar_el_correo_personal_marca_el_perfil_sin_tocar_core_users(
    client, db_session, make_cohort, make_student,
):
    """D12: `core_users.email` NO se toca; el correo personal vive en el perfil."""
    from itcj2.core.models.student_profile import StudentProfile

    cohort = make_cohort(status="open")
    _solo_esta_convocatoria(db_session, cohort)
    student = make_student(control_number="99660010")
    email_original = student.email
    req, _tok = _make_req(db_session, cohort, control="99660010",
                          email="personal@example.invalid")
    raw = _con_token_de_contacto(db_session, req)
    client.cookies.clear()

    resp = client.get(f"/titulatec/inscripcion/correo?t={raw}", follow_redirects=False)

    assert resp.status_code == 200, resp.text[:400]
    perfil = db_session.get(StudentProfile, student.id)
    assert perfil is not None
    assert perfil.contact_email == "personal@example.invalid"
    assert perfil.contact_email_verified_at is not None

    db_session.refresh(student)
    assert student.email == email_original


def test_confirmar_el_correo_no_bloquea_ni_cambia_el_estado_de_la_inscripcion(
    client, db_session, make_cohort, make_student,
):
    cohort = make_cohort(status="open")
    _solo_esta_convocatoria(db_session, cohort)
    make_student(control_number="99660011")
    req, _tok = _make_req(db_session, cohort, control="99660011",
                          email="personal2@example.invalid")
    raw = _con_token_de_contacto(db_session, req)
    client.cookies.clear()

    resp = client.get(f"/titulatec/inscripcion/correo?t={raw}", follow_redirects=False)

    assert resp.status_code == 200
    db_session.refresh(req)
    assert req.status == "unverified"      # la inscripción sigue su curso aparte
    assert req.verify_send_count == 1


def test_token_de_contacto_invalido_muestra_error(client, db_session, make_cohort):
    cohort = make_cohort(status="open")
    _solo_esta_convocatoria(db_session, cohort)
    client.cookies.clear()

    resp = client.get("/titulatec/inscripcion/correo?t=no-existe", follow_redirects=False)

    assert resp.status_code == 200, resp.text[:400]
    assert "no pudimos confirmar" in resp.text.lower()
