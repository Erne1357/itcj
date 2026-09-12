"""`EnrollmentRequestService` a nivel de servicio: alta, outcomes y reenvío.

El nivel HTTP (ventana pública, trampa, límite por IP/CN, tamaño del cuerpo, E8
sobre bytes) vive en `test_enrollment_public.py`. Aquí se prueba el CONTRATO del
servicio en aislamiento: qué `outcome` devuelve cada rama, a qué buzón va cada
correo (RULING R5 del controlador) y el presupuesto de `_send_verify` (§6.8).

RULING R5, el motivo de que este archivo exista antes que la ruta:
`send_verify_enrollment(db, req, *, to, link)` recibe el destinatario como
parámetro, así que nada dentro del helper impide pasarle `req.contact_email`
directo. Es exactamente la fuga que D17 existe para evitar: la liga de
verificación de un egresado CONOCIDO llegando a la dirección que otra persona
escribió en el formulario público. El destinatario SIEMPRE tiene que salir de
`TitulaTecEmailHelper.verify_recipient(db, req)`, nunca calculado a mano en el
servicio. `test_create_conocido_manda_el_token_al_institucional_no_al_del_formulario`
y `test_send_verify_conocido_sin_usuario_en_bd_falla_cerrado_sin_mutar` son los
que fijan esto en rojo si un refactor futuro reintroduce el atajo.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest


# ---------------------------------------------------------------------------
# Captura de correo, calcada de test_email_helper.py::correo_falso (Tarea 18).
# Local a este archivo a propósito: no se importa de un módulo de otra tarea.
# ---------------------------------------------------------------------------
@pytest.fixture()
def correo_falso(monkeypatch):
    """Captura los envíos de TitulaTecEmailHelper sin tocar Graph.

    Devuelve la lista de `(asunto, destinatarios, html)`, en el ORDEN en que se
    mandaron.
    """
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


def _data(**kw):
    base = dict(control_number="99000001", first_name="EGRESADA", last_name="FICTICIA",
               middle_name="", program_id=None, program_text="Ingenieria Ficticia",
               phone="6561234567", contact_email="personal@example.invalid",
               has_efirma=False)
    base.update(kw)
    return base


# ---------------------------------------------------------------------------
# Constantes del contrato (interfaz que consumen T20/T21/T22)
# ---------------------------------------------------------------------------
def test_constantes_del_contrato():
    from itcj2.apps.titulatec.services import enrollment_request_service as mod
    from itcj2.apps.titulatec.services.import_service import CONTROL_NUMBER_RE as re_original

    assert mod.VERIFY_TTL_HOURS == 48
    assert mod.CONTACT_TTL_HOURS == 168
    assert mod.MAX_VERIFY_SENDS == 3
    assert mod.MIN_SECONDS_BETWEEN_SENDS == 300
    assert mod.MAX_PUBLIC_BODY_BYTES == 256 * 1024
    assert mod.STATUSES == (
        "unverified", "verified", "pending_review", "approved", "rejected", "converted")
    assert mod.CONTROL_NUMBER_RE is re_original, (
        "CONTROL_NUMBER_RE debe ser el MISMO objeto que import_service.py: dos "
        "regex que divergen validarian numeros de control distinto segun la "
        "ruta que se tome."
    )


def test_links_usan_public_base_url_y_query_t():
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        PUBLIC_BASE_URL, _contact_link, _verify_link,
    )

    assert _verify_link("abc") == f"{PUBLIC_BASE_URL}/titulatec/inscripcion/verificar?t=abc"
    assert _contact_link("xyz") == f"{PUBLIC_BASE_URL}/titulatec/inscripcion/correo?t=xyz"


def test_token_cache_put_get_redondea():
    """E7: la BD solo guarda el sha256; el claro vive en Redis con la MISMA llave.

    `raw` lleva un `uuid4` a propósito: la llave de Redis es `sha256(raw)` y el
    TTL es de `VERIFY_TTL_HOURS` (48h), así que un literal fijo sobrevive entre
    corridas de la suite -esta prueba paso SOLA y fallo dentro de la suite
    completa la primera vez que la escribi, precisamente por eso- y la primera
    asercion ("no deberia haber nada cacheado aun") deja de ser cierta.
    """
    import uuid

    from itcj2.apps.titulatec.services.enrollment_request_service import (
        _sha256, _token_cache_get, _token_cache_put,
    )

    raw = f"token-de-prueba-{uuid.uuid4().hex}"
    digest = _sha256(raw)

    assert _token_cache_get(digest) is None, "no deberia haber nada cacheado aun"
    _token_cache_put(raw)
    assert _token_cache_get(digest) == raw


# ---------------------------------------------------------------------------
# create(): outcome 'created'
# ---------------------------------------------------------------------------
def test_create_desconocido_crea_fila_unverified_y_manda_al_correo_declarado(
    db_session, make_cohort, correo_falso,
):
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )

    cohort = make_cohort()

    req, outcome = EnrollmentRequestService.create(
        db_session, cohort, _data(control_number="99000001"), client_ip="203.0.113.1")

    assert outcome == "created"
    assert req is not None
    assert req.kind == "unknown"
    assert req.status == "unverified"
    assert req.verify_sent_to == "personal@example.invalid"
    assert req.verify_send_count == 1
    assert req.verify_sent_at is not None
    asunto, destinatarios, _html = correo_falso[0]
    assert destinatarios == ["personal@example.invalid"]
    assert "Confirma tu inscripci" in asunto


def test_create_conocido_manda_el_token_al_institucional_no_al_del_formulario(
    db_session, make_cohort, make_student, correo_falso,
):
    """RULING R5. Es el test central de esta tarea.

    `alumno` YA existe en `core_users` (control "99880001"). El formulario
    público trae un `contact_email` DISTINTO al institucional. La liga de
    VERIFICACION tiene que llegar al institucional -lo unico que prueba que es
    el-, nunca al correo que se tecleo: ese numero de control son 8 digitos
    publicos y adivinables, y por D5 inscribir a un tercero lo deja bloqueado
    para inscribirse de verdad.
    """
    from itcj2.core.utils.email_tools import student_email
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )

    alumno = make_student(control_number="99880001")
    cohort = make_cohort()
    institucional = student_email(alumno)

    req, outcome = EnrollmentRequestService.create(
        db_session, cohort,
        _data(control_number="99880001", contact_email="otro.correo@example.invalid"),
        client_ip="203.0.113.2")

    assert outcome == "created"
    assert req.kind == "known"
    assert req.verify_sent_to == institucional
    assert req.verify_sent_to != "otro.correo@example.invalid"
    assert req.contact_email == "otro.correo@example.invalid", (
        "el correo personal SI se guarda en la fila -solo no recibe el token de "
        "verificacion-"
    )

    # CAMBIO DELIBERADO (B1 de la revision final). Este assert decia
    # `len(correo_falso) == 2` -- "verify_enrollment + confirm_contact
    # (conocido)" -- y fijaba que `create()` mandara TAMBIEN la liga de contacto
    # a `req.contact_email`. Esa expectativa era la vulnerabilidad escrita como
    # contrato: el correo de este test lo escribio un DESCONOCIDO por la alumna
    # 99880001, y esa segunda liga es canjeable contra el
    # `core_student_profile` de ella. La liga de contacto ahora se emite al
    # ABRIR la institucional (`verify()`), asi que aqui sale UN solo correo.
    # Que la de contacto si vaya al personal -su unico trabajo, D17- lo fija
    # ahora `test_al_abrir_la_liga_institucional_sale_la_liga_de_contacto...`
    # (tests/fastapi/titulatec/test_enrollment_identity_chain.py).
    assert len(correo_falso) == 1, (
        "solo la liga de VERIFICACION; la de contacto no se emite hasta que se "
        "abra esta")
    asunto_verify, dest_verify, _h1 = correo_falso[0]
    assert dest_verify == [institucional], (
        "la liga de VERIFICACION (la que convierte la solicitud) debe ir al "
        "institucional, nunca al correo del formulario"
    )
    assert "Confirma tu inscripci" in asunto_verify
    assert req.contact_token_hash is None, (
        "ni siquiera se emite el token: un token que no existe no se puede "
        "canjear contra el perfil de la duena del numero de control")


def test_create_con_solicitud_viva_reenvia_y_no_duplica(
    db_session, make_cohort, correo_falso,
):
    from itcj2.apps.titulatec.models import EnrollmentRequest
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )

    cohort = make_cohort()

    primero, outcome1 = EnrollmentRequestService.create(
        db_session, cohort, _data(control_number="99000002"), client_ip="203.0.113.3")
    assert outcome1 == "created"
    correo_falso.clear()
    # El presupuesto de _send_verify exige >=300s entre envios; sin esto el
    # reenvio de abajo se negaria por el techo, no por logica de negocio.
    primero.verify_sent_at = datetime.now() - timedelta(seconds=400)
    db_session.flush()

    segundo, outcome2 = EnrollmentRequestService.create(
        db_session, cohort,
        _data(control_number="99000002", contact_email="otro@example.invalid"),
        client_ip="203.0.113.4")

    assert outcome2 == "existing_request"
    assert segundo is not None and segundo.id == primero.id
    assert (db_session.query(EnrollmentRequest)
            .filter_by(cohort_id=cohort.id, control_number="99000002").count()) == 1, (
        "no debe crear una segunda fila"
    )
    assert len(correo_falso) == 1, "el reenvio SI escribe correo (el token seguia vivo)"
    assert correo_falso[0][1] == ["personal@example.invalid"], (
        "reenvia al buzon YA GUARDADO en la solicitud, no al 'otro@' que trae "
        "este segundo intento -ese es justo el vector que D17 cierra"
    )


def test_create_con_proceso_activo_avisa_y_no_crea_fila(
    db_session, make_cohort, make_student, make_process, seed_phase_defs,
    correo_falso,
):
    """D5: proceso vivo en CUALQUIER convocatoria bloquea, sin crear solicitud."""
    from itcj2.apps.titulatec.models import EnrollmentRequest
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )

    seed_phase_defs()
    otra = make_cohort()
    cohort = make_cohort()
    alumno = make_student(control_number="99880002")
    make_process(alumno, cohort=otra)

    req, outcome = EnrollmentRequestService.create(
        db_session, cohort, _data(control_number="99880002"), client_ip="203.0.113.5")

    assert outcome == "existing_process"
    assert req is None
    assert (db_session.query(EnrollmentRequest)
            .filter_by(control_number="99880002").count()) == 0
    assert len(correo_falso) == 1, "send_already_enrolled, al institucional"


def test_created_ip_hash_nunca_guarda_la_ip_en_claro(db_session, make_cohort, correo_falso):
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )

    cohort = make_cohort()

    req, _outcome = EnrollmentRequestService.create(
        db_session, cohort, _data(control_number="99000005"), client_ip="198.51.100.7")

    assert req.created_ip_hash is not None
    assert "198.51.100.7" not in req.created_ip_hash
    assert len(req.created_ip_hash) == 64  # hexdigest sha256


def test_created_ip_hash_es_none_sin_ip(db_session, make_cohort, correo_falso):
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )

    cohort = make_cohort()

    req, _outcome = EnrollmentRequestService.create(
        db_session, cohort, _data(control_number="99000006"), client_ip=None)

    assert req.created_ip_hash is None


# ---------------------------------------------------------------------------
# _send_verify(): presupuesto y no-rotación (§6.8)
# ---------------------------------------------------------------------------
def _req_pelado(db_session, cohort, *, control_number, kind, token_hash,
                verify_send_count=0, verify_sent_at=None,
                contact_email="personal@example.invalid"):
    from itcj2.apps.titulatec.models import EnrollmentRequest

    req = EnrollmentRequest(
        cohort_id=cohort.id, control_number=control_number,
        first_name="X", last_name="Y", phone="6560000000",
        contact_email=contact_email, has_efirma=False,
        kind=kind, status="unverified",
        verify_token_hash=token_hash,
        verify_expires_at=datetime.now() + timedelta(hours=1),
        verify_send_count=verify_send_count,
        verify_sent_at=verify_sent_at,
    )
    db_session.add(req)
    db_session.flush()
    return req


def test_send_verify_sin_claro_en_cache_falla_cerrado_sin_mutar(db_session, make_cohort):
    """§6.8: sin el texto claro en Redis, NO hay reenvio posible. Nada se toca."""
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService, _sha256,
    )

    cohort = make_cohort()
    req = _req_pelado(db_session, cohort, control_number="99000003", kind="unknown",
                      token_hash=_sha256("token-que-nunca-se-cacheo"))
    hash_antes, expira_antes = req.verify_token_hash, req.verify_expires_at

    ok = EnrollmentRequestService._send_verify(db_session, req)

    assert ok is False
    assert req.verify_send_count == 0
    assert req.verify_sent_at is None
    assert req.verify_token_hash == hash_antes, "NUNCA debe rotar el token"
    assert req.verify_expires_at == expira_antes, "NUNCA debe extender la ventana"


def test_send_verify_con_claro_en_cache_reenvia_sin_rotar_el_hash(
    db_session, make_cohort, correo_falso,
):
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService, _sha256, _token_cache_put,
    )

    cohort = make_cohort()
    raw = "raw-token-de-prueba-reenvio"
    _token_cache_put(raw)
    req = _req_pelado(db_session, cohort, control_number="99000004", kind="unknown",
                      token_hash=_sha256(raw), verify_send_count=1,
                      verify_sent_at=datetime.now() - timedelta(seconds=400))
    hash_antes = req.verify_token_hash

    ok = EnrollmentRequestService._send_verify(db_session, req)

    assert ok is True
    assert req.verify_token_hash == hash_antes, "el reenvio NUNCA rota el token"
    assert req.verify_send_count == 2
    assert req.verify_sent_at is not None
    assert correo_falso[0][1] == ["personal@example.invalid"]


def test_send_verify_respeta_el_tope_de_reenvios(db_session, make_cohort):
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        MAX_VERIFY_SENDS, EnrollmentRequestService, _sha256, _token_cache_put,
    )

    cohort = make_cohort()
    raw = "raw-token-tope-de-reenvios"
    _token_cache_put(raw)
    req = _req_pelado(db_session, cohort, control_number="99000007", kind="unknown",
                      token_hash=_sha256(raw), verify_send_count=MAX_VERIFY_SENDS,
                      verify_sent_at=datetime.now() - timedelta(seconds=400))

    ok = EnrollmentRequestService._send_verify(db_session, req)

    assert ok is False
    assert req.verify_send_count == MAX_VERIFY_SENDS, "no debe seguir subiendo"


def test_send_verify_respeta_el_minimo_entre_envios(db_session, make_cohort):
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService, _sha256, _token_cache_put,
    )

    cohort = make_cohort()
    raw = "raw-token-minimo-entre-envios"
    _token_cache_put(raw)
    req = _req_pelado(db_session, cohort, control_number="99000008", kind="unknown",
                      token_hash=_sha256(raw), verify_send_count=1,
                      verify_sent_at=datetime.now())  # recien mandado

    ok = EnrollmentRequestService._send_verify(db_session, req)

    assert ok is False
    assert req.verify_send_count == 1, "no debe cobrar un envio que no ocurrio"


def test_send_verify_conocido_sin_usuario_en_bd_falla_cerrado_sin_mutar(
    db_session, make_cohort,
):
    """RULING R5, la otra mitad. Sin `correo_falso`: si esto llegara a intentar
    mandar, `send_verify_enrollment` fallaria por falta de token de Graph, pero
    lo que se prueba aqui es que NUNCA debe llegar a intentarlo -el guard de
    `verify_recipient` devolviendo `None` tiene que cortar ANTES-, y por tanto
    tampoco debe mutar nada. Si algun dia el codigo cae de vuelta a
    `req.verify_sent_to or req.contact_email`, este `kind='known'` con usuario
    inexistente ya no fallaria cerrado: mandaria (intentaria mandar) al
    `contact_email` de la fila, que es EXACTAMENTE la fuga de D17.
    """
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService, _sha256, _token_cache_put,
    )

    cohort = make_cohort()
    raw = "raw-token-conocido-sin-user"
    _token_cache_put(raw)
    req = _req_pelado(db_session, cohort, control_number="99999997", kind="known",
                      token_hash=_sha256(raw), verify_send_count=0,
                      contact_email="personal@example.invalid")
    hash_antes = req.verify_token_hash

    ok = EnrollmentRequestService._send_verify(db_session, req)

    assert ok is False
    assert req.verify_send_count == 0
    assert req.verify_sent_at is None
    assert req.verify_token_hash == hash_antes
