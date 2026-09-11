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


# ---------------------------------------------------------------------------
# RULING R4 — 'sent'/'noop'/trampa se prueban byte a byte (contenido Y cabeceras)
# ---------------------------------------------------------------------------
# El brief trae `test_reenvio_que_no_casa_da_salida_identica_al_que_si_casa`
# (arriba), que solo compara `.content` y no incluye la trampa como tercera
# rama. R4 exige más: los MISMOS bytes Y las MISMAS cabeceras, y la trampa del
# formulario de reenvío es una tercera salida que también debe ser idéntica.
# Se replica el mecanismo de `test_e8_las_tres_ramas_son_identicas_byte_a_byte`
# y `test_la_trampa_no_escribe_nada_y_devuelve_la_tarjeta_generica`
# (`tests/fastapi/titulatec/test_enrollment_public.py:297,255`): capturar las
# respuestas en la MISMA corrida, con IP y control distintos por petición para
# que el limitador (R3) no contamine la comparación.
def _h(resp):
    """Cabeceras normalizadas, sin `date` (puede saltar de segundo entre peticiones)."""
    return {k.lower(): v for k, v in resp.headers.items() if k.lower() != "date"}


def test_sent_noop_y_trampa_del_reenvio_son_identicos_byte_a_byte(
    client, db_session, make_cohort,
):
    """R4: 'sent', 'noop' y la trampa del formulario de reenvío -tercera salida-
    tienen que devolver los MISMOS bytes y las MISMAS cabeceras. Si se
    distinguen en algo -una coma, un `Content-Length`- el endpoint es un
    oráculo anónimo de "¿existe este número de control en el ITCJ?".
    """
    cohort = make_cohort(status="open")
    _solo_esta_convocatoria(db_session, cohort)
    req, _tok = _make_req(db_session, cohort, control="99660020")
    client.cookies.clear()

    r_sent = client.post("/titulatec/inscripcion/reenviar",
                         data={"control_number": "99660020",
                               "contact_email": "alguien@example.invalid"},
                         headers={"X-Real-IP": "203.0.113.50"},
                         follow_redirects=False)
    r_noop = client.post("/titulatec/inscripcion/reenviar",
                         data={"control_number": "00000000",
                               "contact_email": "nadie@example.invalid"},
                         headers={"X-Real-IP": "203.0.113.51"},
                         follow_redirects=False)
    r_trampa = client.post("/titulatec/inscripcion/reenviar",
                           data={"control_number": "99660021",
                                 "contact_email": "otro@example.invalid",
                                 "website": "http://spam.example"},
                           headers={"X-Real-IP": "203.0.113.52"},
                           follow_redirects=False)

    assert r_sent.status_code == r_noop.status_code == r_trampa.status_code == 200, (
        r_sent.text[:200], r_noop.text[:200], r_trampa.text[:200])

    # Cuerpo idéntico BYTE A BYTE, no "parecido".
    assert r_sent.content == r_noop.content
    assert r_sent.content == r_trampa.content
    # Cabeceras idénticas también (lo que el test del brief NO comprueba).
    assert _h(r_sent) == _h(r_noop)
    assert _h(r_sent) == _h(r_trampa)

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
    """R3: el cubo se cobra EN LA PUERTA, siempre -nunca solo cuando `resend`
    manda de verdad-. Si solo cobrara el envío real, el tiempo de vaciado del
    cubo delataría si un número de control existe: dos 'noop' seguidos NUNCA
    agotarían un límite de 2 si el cobro dependiera del resultado.
    """
    from itcj2.apps.titulatec.pages import public as mod

    monkeypatch.setattr(mod, "ENROLL_RESEND_RL_LIMIT_IP", 2)
    cohort = make_cohort(status="open")
    _solo_esta_convocatoria(db_session, cohort)
    client.cookies.clear()
    headers = {"X-Real-IP": "203.0.113.53"}

    for _ in range(2):
        r = client.post("/titulatec/inscripcion/reenviar",
                        data={"control_number": "00000000",
                              "contact_email": "nadie@example.invalid"},
                        headers=headers, follow_redirects=False)
        assert r.status_code == 200

    r3 = client.post("/titulatec/inscripcion/reenviar",
                     data={"control_number": "00000000",
                           "contact_email": "nadie@example.invalid"},
                     headers=headers, follow_redirects=False)
    assert r3.headers.get("Retry-After") is not None, (
        "el cubo de IP no se agoto con puros 'noop': el presupuesto no se esta "
        "cobrando en la puerta (R3)")


# ---------------------------------------------------------------------------
# RULING R1 y refuerzo de cobertura de `confirm_contact`
# ---------------------------------------------------------------------------
def test_confirm_contact_usa_comparacion_en_tiempo_constante():
    """R1: `_compare` no existe, nunca existió. Mismo criterio que
    `test_verify_usa_comparacion_en_tiempo_constante`
    (`tests/fastapi/titulatec/test_enrollment_verify.py:337`): mutar esto a
    `==` no cambia ningún resultado observable -la query SQL ya filtró por
    igualdad exacta antes de llegar aquí-, así que ningún test de
    comportamiento puede detectar la regresión. Se lee la fuente.
    """
    import inspect

    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )

    src = inspect.getsource(EnrollmentRequestService.confirm_contact)
    assert "hmac.compare_digest(" in src
    assert "_compare(" not in src


def test_confirmar_dos_veces_con_el_mismo_token_sigue_funcionando(
    client, db_session, make_cohort, make_student,
):
    """Idempotente A PROPÓSITO, igual que `verify()` (mismo riesgo: un cliente
    de correo puede prefetchear la liga GET antes del clic humano -ver el
    docstring de `EnrollmentRequestService.verify`-). El token de contacto NO
    se invalida tras usarse una vez: dos aperturas de la MISMA liga deben
    confirmar las dos, no fallar la segunda.
    """
    from itcj2.core.models.student_profile import StudentProfile

    cohort = make_cohort(status="open")
    _solo_esta_convocatoria(db_session, cohort)
    student = make_student(control_number="99660013")
    req, _tok = _make_req(db_session, cohort, control="99660013",
                          email="personal4@example.invalid")
    raw = _con_token_de_contacto(db_session, req)
    client.cookies.clear()

    r1 = client.get(f"/titulatec/inscripcion/correo?t={raw}", follow_redirects=False)
    r2 = client.get(f"/titulatec/inscripcion/correo?t={raw}", follow_redirects=False)

    assert r1.status_code == r2.status_code == 200
    assert "no pudimos confirmar" not in r1.text.lower()
    assert "no pudimos confirmar" not in r2.text.lower()
    perfil = db_session.get(StudentProfile, student.id)
    assert perfil is not None
    assert perfil.contact_email_verified_at is not None


def test_token_de_contacto_vencido_no_se_acepta(
    client, db_session, make_cohort, make_student,
):
    """Un token de contacto VENCIDO no se acepta aunque el hash coincida.

    Distinto de la reutilización idempotente de arriba (que es intencional):
    esta es la guarda real contra una liga vieja. Sin `contact_expires_at`, una
    liga de confirmación de hace meses seguiría marcando el perfil como
    verificado hoy.
    """
    from itcj2.core.models.student_profile import StudentProfile

    cohort = make_cohort(status="open")
    _solo_esta_convocatoria(db_session, cohort)
    student = make_student(control_number="99660012")
    req, _tok = _make_req(db_session, cohort, control="99660012",
                          email="personal3@example.invalid")
    raw = _con_token_de_contacto(db_session, req)
    req.contact_expires_at = datetime.now() - timedelta(hours=1)
    db_session.flush()
    client.cookies.clear()

    resp = client.get(f"/titulatec/inscripcion/correo?t={raw}", follow_redirects=False)

    assert resp.status_code == 200, resp.text[:400]
    assert "no pudimos confirmar" in resp.text.lower()
    perfil = db_session.get(StudentProfile, student.id)
    assert perfil is None or perfil.contact_email_verified_at is None


def test_una_excepcion_en_confirm_contact_no_produce_500(client, db_session, monkeypatch):
    """Ninguna entrada del visitante puede producir un 500 (docstring del
    módulo). Se fuerza con `monkeypatch` porque el objetivo es "cualquier
    excepción", igual que
    `test_una_excepcion_en_create_no_produce_500_y_devuelve_la_tarjeta_generica`
    (`test_enrollment_public.py`).
    """
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )

    def _revienta(*a, **kw):
        raise ValueError("fallo simulado")

    client.cookies.clear()
    monkeypatch.setattr(EnrollmentRequestService, "confirm_contact",
                        staticmethod(_revienta))

    resp = client.get("/titulatec/inscripcion/correo?t=cualquier-cosa",
                      follow_redirects=False)

    assert resp.status_code == 200, resp.text[:400]
    assert "no pudimos confirmar" in resp.text.lower()
