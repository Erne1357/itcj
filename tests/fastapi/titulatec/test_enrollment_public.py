"""Formulario público de auto-inscripción: ventana, validación y E8.

Todo va con `follow_redirects=False` y `client.cookies.clear()`: estas rutas son
públicas y un 302 al login seguido devolvería 200 y la prueba pasaría por la
razón equivocada (§11.1 del diseño).

Cada POST lleva su propio `X-Real-IP`: `client_ip()` la prefiere sobre
`request.client.host`, que para el `TestClient` es siempre "testclient" y
metería todos los tests en el MISMO cubo de `rl:enroll:ip:*` (mismo motivo que
documenta `test_survey_submit_routes.py`). El autouse `_clear_authz_cache`
(`tests/fastapi/conftest.py`) barre `rl:*` antes y después de cada test.

Desde 2026-09-15 TODA solicitud pasa por la bandeja de Servicios Escolares: el
alta no manda correo ni emite liga, y la tarjeta lo dice. El nivel SERVICIO
(outcomes de `create()`, sin token, sin correo) vive en
`test_enrollment_request_service.py`; aquí todo pasa por HTTP, que es donde
viven las defensas que el servicio no ve: la ventana de la convocatoria, la
confirmación del correo, la trampa, el tope de tamaño y el limitador.
"""
from __future__ import annotations

import pytest

ENROLL_URL = "/titulatec/inscripcion"

TITULO_TARJETA = "Recibimos tu solicitud"
CUERPO_TARJETA = ("Servicios Escolares la revisará. Si se aprueba, te llegará un correo "
                  "con tu acceso. Revisa también la carpeta de correo no deseado.")
INTRO_PAGINA = ("Llena tus datos. Servicios Escolares revisará tu solicitud y, si se "
                "aprueba, te enviará tu acceso por correo.")


def _plano(html: str) -> str:
    """El texto de una plantilla viene partido en renglones: se compara plano."""
    return " ".join(html.split())


def _solo_esta_convocatoria(db_session, cohort):
    """Deja `cohort` como la ÚNICA convocatoria abierta.

    La BD de dev trae convocatorias reales con `status='open'` y fechas NULL
    (§6.6), y `public_enrollment_cohort` falla CERRADO con más de una: sin esto
    la ruta daría 503 por datos ajenos al test. Se revierte con la transacción
    del fixture.
    """
    from itcj2.apps.titulatec.models import Cohort
    (db_session.query(Cohort)
     .filter(Cohort.id != cohort.id)
     .update({Cohort.status: "closed"}, synchronize_session=False))
    db_session.flush()


def _form(**kw):
    base = {
        "control_number": "99880002",
        "first_name": "ALUMNA",
        "last_name": "INVENTADA",
        "middle_name": "",
        "program_id": "__other__",
        "program_text": "Ingenieria Ficticia",
        "phone": "6561234567",
        "contact_email": "alguien@example.invalid",
        "contact_email_confirm": "alguien@example.invalid",
        "has_efirma": "0",
        "has_english": "1",
        "website": "",
    }
    base.update(kw)
    return base


def _count(db_session, control_number):
    """Filas de `EnrollmentRequest` para UN número de control.

    A propósito SIN default ni variante "cuenta todo": la BD de dev compartida
    acumula filas de QA manual de otras tareas, y un `count()` sin filtro falla
    por un motivo que no tiene nada que ver con lo que cada test comprueba.
    """
    from itcj2.apps.titulatec.models import EnrollmentRequest
    return (db_session.query(EnrollmentRequest)
            .filter_by(control_number=control_number).count())


@pytest.fixture()
def sin_correo(monkeypatch):
    """Falla la prueba si algo intenta salir por Graph; devuelve los intentos
    de los métodos públicos del helper, que aquí no deberían ocurrir."""
    from itcj2.apps.titulatec.services.email_helper import TitulaTecEmailHelper

    intentos = []
    for nombre in ("send_verify_enrollment", "send_already_enrolled",
                   "send_enrollment_done", "send_enrollment_approved",
                   "send_enrollment_rejected"):
        monkeypatch.setattr(
            TitulaTecEmailHelper, nombre,
            staticmethod(lambda *a, _n=nombre, **k: intentos.append(_n) or False))
    return intentos


# ---------------------------------------------------------------------------
# GET: ventana de la convocatoria
# ---------------------------------------------------------------------------
def test_get_con_ventana_cerrada_muestra_la_tarjeta_de_cierre(
    client, db_session, make_cohort,
):
    cohort = make_cohort(status="closed")
    _solo_esta_convocatoria(db_session, cohort)
    db_session.query(type(cohort)).filter_by(id=cohort.id).update({"status": "closed"})
    db_session.flush()
    client.cookies.clear()

    resp = client.get(ENROLL_URL, follow_redirects=False)

    assert resp.status_code == 200, resp.text[:400]
    assert "inscripción está cerrada" in resp.text
    assert 'id="tt-enroll-form"' not in resp.text
    assert 'data-tt-page="public_enroll"' in resp.text


def test_get_con_ventana_abierta_muestra_el_formulario_y_la_trampa(
    client, db_session, make_cohort, make_program,
):
    make_program("Ingenieria Ficticia A")
    cohort = make_cohort(status="open")
    _solo_esta_convocatoria(db_session, cohort)
    client.cookies.clear()

    resp = client.get(ENROLL_URL, follow_redirects=False)

    assert resp.status_code == 200, resp.text[:400]
    assert 'id="tt-enroll-form"' in resp.text
    assert 'name="website"' in resp.text          # honeypot (E3)
    assert "Ingenieria Ficticia A" in resp.text    # select de core_programs
    assert 'value="__other__"' in resp.text        # "mi carrera no aparece"
    assert cohort.name not in resp.text            # sin nombre de convocatoria


def test_la_pagina_explica_que_la_solicitud_se_revisa_antes_de_dar_acceso(
    client, db_session, make_cohort,
):
    cohort = make_cohort(status="open")
    _solo_esta_convocatoria(db_session, cohort)
    client.cookies.clear()

    resp = client.get(ENROLL_URL, follow_redirects=False)

    assert resp.status_code == 200, resp.text[:400]
    assert INTRO_PAGINA in _plano(resp.text)
    assert "Sin ese clic" not in resp.text, "el texto de la liga de confirmación ya no aplica"


def test_el_formulario_pide_confirmar_el_correo_personal(client, db_session, make_cohort):
    import re

    cohort = make_cohort(status="open")
    _solo_esta_convocatoria(db_session, cohort)
    client.cookies.clear()

    resp = client.get(ENROLL_URL, follow_redirects=False)

    assert resp.status_code == 200, resp.text[:400]
    campo = re.search(r"<input[^>]*name=\"contact_email_confirm\"[^>]*>", resp.text)
    assert campo, "falta el campo de confirmación del correo personal"
    for atributo in ('type="email"', 'maxlength="150"', 'autocomplete="off"', "required"):
        assert atributo in campo.group(0), atributo
    assert "Confirma tu correo personal" in resp.text


def test_get_con_mas_de_una_convocatoria_abierta_falla_cerrado_503(
    client, db_session, make_cohort,
):
    """§6.6: NUNCA un desempate silencioso por id."""
    from itcj2.apps.titulatec.models import Cohort
    db_session.query(Cohort).update({"status": "closed"}, synchronize_session=False)
    db_session.flush()
    make_cohort(status="open")
    make_cohort(status="open")
    client.cookies.clear()

    resp = client.get(ENROLL_URL, follow_redirects=False)

    assert resp.status_code == 503, resp.text[:400]
    assert 'data-tt-page="public_enroll"' in resp.text


# ---------------------------------------------------------------------------
# POST: validación inline (200, nunca 400 — el visitante debe VER y CORREGIR)
# ---------------------------------------------------------------------------
def test_control_invalido_devuelve_200_con_el_formulario_y_error_inline(
    client, db_session, make_cohort,
):
    """No 400: es un resultado que el visitante debe VER y CORREGIR (§6.1)."""
    cohort = make_cohort(status="open")
    _solo_esta_convocatoria(db_session, cohort)
    client.cookies.clear()

    resp = client.post(ENROLL_URL,
                       data=_form(control_number="abc"),
                       headers={"X-Real-IP": "203.0.113.11"},
                       follow_redirects=False)

    assert resp.status_code == 200, resp.text[:400]
    assert 'id="tt-enroll-form"' in resp.text
    assert "número de control" in resp.text
    assert 'aria-invalid="true"' in resp.text
    # Se conserva lo capturado, normalizado a MAYÚSCULA (se normaliza ANTES de
    # validar, así que hasta un valor inválido se echa de vuelta en mayúscula).
    assert 'value="ABC"' in resp.text
    assert _count(db_session, "ABC") == 0
    assert _count(db_session, "abc") == 0


@pytest.mark.parametrize("control", ["99885910", "B21221523"])
def test_control_valido_ocho_digitos_o_letra_mas_ocho_queda_en_revision(
    client, db_session, make_cohort, sin_correo, control,
):
    """Formato vigente (2026-09-17): 8 dígitos, o una letra + 8 dígitos para
    quien viene de traslado. Los dos deben aceptarse igual.

    `99885910` (no `21111182`, el ejemplo del mensaje al visitante) a
    propósito: `99xxxxxx` es la convención sintética del harness (ver
    `test_import_scale.py`), y `21111182` con forma de matrícula real
    colisionó contra un `EnrollmentRequest` ya sembrado en la BD de dev
    compartida (`NoResultFound` al buscarlo de vuelta)."""
    from itcj2.apps.titulatec.models import EnrollmentRequest

    cohort = make_cohort(status="open")
    _solo_esta_convocatoria(db_session, cohort)
    client.cookies.clear()

    resp = client.post(ENROLL_URL, data=_form(control_number=control),
                       headers={"X-Real-IP": "203.0.113.94"}, follow_redirects=False)

    assert resp.status_code == 200, resp.text[:400]
    assert TITULO_TARJETA in resp.text
    fila = db_session.query(EnrollmentRequest).filter_by(control_number=control).one()
    assert fila.status == "pending_review"


def test_control_con_letra_minuscula_se_guarda_en_mayuscula(
    client, db_session, make_cohort, sin_correo,
):
    """`b21221523` se normaliza a `B21221523` ANTES de guardar: el lookup de
    `EnrollmentRequestService` es un filter_by exacto, y una letra en
    minúscula abriría una segunda solicitud para la misma persona."""
    from itcj2.apps.titulatec.models import EnrollmentRequest

    cohort = make_cohort(status="open")
    _solo_esta_convocatoria(db_session, cohort)
    client.cookies.clear()

    resp = client.post(ENROLL_URL, data=_form(control_number="b21221523"),
                       headers={"X-Real-IP": "203.0.113.95"}, follow_redirects=False)

    assert resp.status_code == 200, resp.text[:400]
    assert TITULO_TARJETA in resp.text
    assert _count(db_session, "b21221523") == 0
    fila = db_session.query(EnrollmentRequest).filter_by(control_number="B21221523").one()
    assert fila.status == "pending_review"


@pytest.mark.parametrize("bad", ["L1234567", "123456789", "M123456789"])
def test_formatos_viejos_de_control_ya_no_son_validos(
    client, db_session, make_cohort, bad,
):
    """El formato viejo (letra + 7 o 9 dígitos, o 9 dígitos puros de posgrado)
    se retiró el 2026-09-17: el visitante ve el mensaje nuevo y nada se guarda."""
    cohort = make_cohort(status="open")
    _solo_esta_convocatoria(db_session, cohort)
    client.cookies.clear()

    resp = client.post(ENROLL_URL, data=_form(control_number=bad),
                       headers={"X-Real-IP": "203.0.113.96"}, follow_redirects=False)

    assert resp.status_code == 200, resp.text[:400]
    assert 'id="tt-enroll-form"' in resp.text
    assert 'aria-invalid="true"' in resp.text
    assert ("Tu número de control son 8 dígitos, o una letra y 8 dígitos si "
           "vienes de traslado") in resp.text
    assert _count(db_session, bad) == 0
    assert _count(db_session, bad.upper()) == 0


def test_correo_invalido_devuelve_200_con_el_formulario_y_error_inline(
    client, db_session, make_cohort,
):
    cohort = make_cohort(status="open")
    _solo_esta_convocatoria(db_session, cohort)
    client.cookies.clear()

    resp = client.post(ENROLL_URL,
                       data=_form(contact_email="no-es-correo",
                                  contact_email_confirm="no-es-correo"),
                       headers={"X-Real-IP": "203.0.113.12"},
                       follow_redirects=False)

    assert resp.status_code == 200, resp.text[:400]
    assert 'id="tt-enroll-form"' in resp.text
    assert "correo personal válido" in resp.text
    assert 'data-tt-error="contact_email_confirm"' not in resp.text, (
        "dos correos iguales no se marcan como distintos aunque los dos estén mal")
    assert _count(db_session, "99880002") == 0


def test_correos_distintos_devuelven_200_con_el_error_en_la_confirmacion(
    client, db_session, make_cohort,
):
    """Una letra de más en el correo es la diferencia entre recibir el acceso y
    no recibirlo nunca: la persona no se entera de que se equivocó hasta que
    nadie le escribe. Por eso se teclea dos veces y el servidor lo compara."""
    cohort = make_cohort(status="open")
    _solo_esta_convocatoria(db_session, cohort)
    client.cookies.clear()

    resp = client.post(ENROLL_URL,
                       data=_form(control_number="99885801",
                                  contact_email="alguien@example.invalid",
                                  contact_email_confirm="alguien@exmple.invalid"),
                       headers={"X-Real-IP": "203.0.113.18"},
                       follow_redirects=False)

    assert resp.status_code == 200, resp.text[:400]
    assert 'id="tt-enroll-form"' in resp.text
    assert 'data-tt-error="contact_email_confirm"' in resp.text
    assert "Los dos correos no coinciden." in resp.text
    assert 'aria-describedby="tt-email-confirm-err"' in resp.text
    assert 'data-tt-error="contact_email"' not in resp.text
    assert 'value="alguien@example.invalid"' in resp.text   # lo capturado se conserva
    assert _count(db_session, "99885801") == 0


def test_la_confirmacion_no_distingue_mayusculas_ni_espacios(
    client, db_session, make_cohort,
):
    from itcj2.apps.titulatec.models import EnrollmentRequest

    cohort = make_cohort(status="open")
    _solo_esta_convocatoria(db_session, cohort)
    client.cookies.clear()

    resp = client.post(ENROLL_URL,
                       data=_form(control_number="99885802",
                                  contact_email="Alguien@Example.invalid",
                                  contact_email_confirm="  alguien@EXAMPLE.invalid "),
                       headers={"X-Real-IP": "203.0.113.19"},
                       follow_redirects=False)

    assert resp.status_code == 200, resp.text[:400]
    assert TITULO_TARJETA in resp.text
    fila = db_session.query(EnrollmentRequest).filter_by(control_number="99885802").one()
    assert fila.contact_email == "Alguien@Example.invalid"


def test_sin_nombre_devuelve_200_con_error_inline_en_ese_campo(
    client, db_session, make_cohort,
):
    cohort = make_cohort(status="open")
    _solo_esta_convocatoria(db_session, cohort)
    client.cookies.clear()

    resp = client.post(ENROLL_URL,
                       data=_form(first_name=""),
                       headers={"X-Real-IP": "203.0.113.13"},
                       follow_redirects=False)

    assert resp.status_code == 200, resp.text[:400]
    assert 'data-tt-error="first_name"' in resp.text
    assert _count(db_session, "99880002") == 0


def test_sin_carrera_y_sin_texto_libre_devuelve_error_de_programa(
    client, db_session, make_cohort,
):
    cohort = make_cohort(status="open")
    _solo_esta_convocatoria(db_session, cohort)
    client.cookies.clear()

    resp = client.post(ENROLL_URL,
                       data=_form(program_id="", program_text=""),
                       headers={"X-Real-IP": "203.0.113.14"},
                       follow_redirects=False)

    assert resp.status_code == 200, resp.text[:400]
    assert 'data-tt-error="program_id"' in resp.text
    assert _count(db_session, "99880002") == 0


# ---------------------------------------------------------------------------
# «¿Ya acreditaste el inglés?» (2026-09-17) — revierte D11 («el inglés no se
# pregunta»): el usuario pidió preguntarlo, obligatorio y SIN opción marcada, y
# que un «No» impida enviar la solicitud.
# ---------------------------------------------------------------------------
def test_el_formulario_pregunta_por_el_ingles_al_inicio_y_sin_respuesta_marcada(
    client, db_session, make_cohort,
):
    import re

    cohort = make_cohort(status="open")
    _solo_esta_convocatoria(db_session, cohort)
    client.cookies.clear()

    html = client.get(ENROLL_URL, follow_redirects=False).text

    assert "¿Ya acreditaste el inglés?" in html
    radios = re.findall(r'<input[^>]*name="has_english"[^>]*>', html)
    assert sorted(re.search(r'value="(\d)"', r).group(1) for r in radios) == ["0", "1"]
    assert not any("checked" in r for r in radios), "no debe venir ninguna opción marcada"
    assert any("required" in r for r in radios), "el navegador debe exigir una respuesta"
    # Es un requisito que BLOQUEA: va antes del resto de los datos.
    assert html.index('name="has_english"') < html.index('name="control_number"')


def test_sin_contestar_lo_del_ingles_no_se_crea_la_solicitud(
    client, db_session, make_cohort,
):
    cohort = make_cohort(status="open")
    _solo_esta_convocatoria(db_session, cohort)
    client.cookies.clear()
    datos = _form()
    datos.pop("has_english")

    resp = client.post(ENROLL_URL, data=datos,
                       headers={"X-Real-IP": "203.0.113.15"}, follow_redirects=False)

    assert resp.status_code == 200, resp.text[:400]
    assert 'data-tt-error="has_english"' in resp.text
    assert "Indica si ya acreditaste el inglés." in resp.text
    assert _count(db_session, "99880002") == 0


def test_sin_ingles_acreditado_no_se_crea_la_solicitud_y_conserva_lo_capturado(
    client, db_session, make_cohort,
):
    cohort = make_cohort(status="open")
    _solo_esta_convocatoria(db_session, cohort)
    client.cookies.clear()

    resp = client.post(ENROLL_URL, data=_form(has_english="0"),
                       headers={"X-Real-IP": "203.0.113.16"}, follow_redirects=False)

    assert resp.status_code == 200, resp.text[:400]
    assert 'id="tt-enroll-form"' in resp.text
    assert 'data-tt-error="has_english"' in resp.text
    assert ("Para inscribirte necesitas tener acreditado el inglés. Cuando lo "
            "acredites, vuelve a enviar tu solicitud.") in _plano(resp.text)
    assert TITULO_TARJETA not in resp.text
    assert 'value="ALUMNA"' in resp.text
    assert _count(db_session, "99880002") == 0


def test_ventana_cerrada_en_el_post_no_escribe_y_muestra_cerrada(
    client, db_session, make_cohort,
):
    from itcj2.apps.titulatec.models import Cohort
    db_session.query(Cohort).update({"status": "draft"}, synchronize_session=False)
    db_session.flush()
    client.cookies.clear()

    resp = client.post(ENROLL_URL, data=_form(),
                       headers={"X-Real-IP": "203.0.113.15"},
                       follow_redirects=False)

    assert resp.status_code == 200, resp.text[:400]
    assert "inscripción está cerrada" in resp.text
    assert _count(db_session, "99880002") == 0


def test_post_con_mas_de_una_convocatoria_abierta_manda_el_mensaje_en_la_cabecera(
    client, db_session, make_cohort,
):
    """§6.6, rama POST. htmx NO hace swap en un 5xx: el aviso tiene que viajar
    en la CABECERA, no en un cuerpo que nadie va a pintar."""
    from itcj2.apps.titulatec.models import Cohort
    db_session.query(Cohort).update({"status": "closed"}, synchronize_session=False)
    db_session.flush()
    make_cohort(status="open")
    make_cohort(status="open")
    client.cookies.clear()

    resp = client.post(ENROLL_URL, data=_form(control_number="99885701"),
                       headers={"X-Real-IP": "203.0.113.81"}, follow_redirects=False)

    assert resp.status_code == 503, resp.text[:300]
    assert "X-Tt-Error" in resp.headers, (
        "sin esta cabecera htmx descarta la respuesta y el visitante nunca ve "
        "el aviso: no hace swap en un 5xx"
    )
    assert _count(db_session, "99885701") == 0


# ---------------------------------------------------------------------------
# Alta válida: queda en revisión, sin liga ni correo
# ---------------------------------------------------------------------------
def test_un_alta_valida_queda_en_revision_sin_liga_ni_correo(
    client, db_session, make_cohort, sin_correo,
):
    from itcj2.apps.titulatec.models import EnrollmentRequest

    cohort = make_cohort(status="open")
    _solo_esta_convocatoria(db_session, cohort)
    client.cookies.clear()

    resp = client.post(ENROLL_URL, data=_form(control_number="99885803"),
                       headers={"X-Real-IP": "203.0.113.20"}, follow_redirects=False)

    assert resp.status_code == 200, resp.text[:400]
    assert 'data-tt-notice="generic"' in resp.text
    assert TITULO_TARJETA in resp.text
    assert CUERPO_TARJETA in _plano(resp.text)
    fila = db_session.query(EnrollmentRequest).filter_by(control_number="99885803").one()
    assert fila.status == "pending_review"
    assert fila.verify_token_hash is None
    assert sin_correo == [], "el alta ya no manda nada: el acceso llega tras la revisión"


# ---------------------------------------------------------------------------
# Trampa (E3) y E8 — las salidas indistinguibles
# ---------------------------------------------------------------------------
def test_la_trampa_no_escribe_nada_y_devuelve_la_tarjeta_generica(
    client, db_session, make_cohort,
):
    """La trampa es la CUARTA salida indistinguible: un bot que la llena tiene
    que recibir una respuesta idéntica BYTE A BYTE a la de un envío legítimo.
    Si se distinguiera aunque fuera por una coma, un bot sabría que fue
    detectado — exactamente la señal que la trampa existe para no dar.
    """
    cohort = make_cohort(status="open")
    _solo_esta_convocatoria(db_session, cohort)
    client.cookies.clear()

    r_ok = client.post(ENROLL_URL,
                       data=_form(control_number="99885601"),
                       headers={"X-Real-IP": "203.0.113.16"},
                       follow_redirects=False)
    r_trampa = client.post(ENROLL_URL,
                           data=_form(control_number="99885602",
                                     website="http://spam.example"),
                           headers={"X-Real-IP": "203.0.113.17"},
                           follow_redirects=False)

    assert r_ok.status_code == r_trampa.status_code == 200, r_trampa.text[:400]
    assert TITULO_TARJETA in r_trampa.text

    # Cuerpo idéntico BYTE A BYTE contra un envío legítimo real, no "parecido".
    assert r_trampa.content == r_ok.content

    def _h(resp):
        # `date` se excluye porque puede saltar de segundo entre peticiones.
        return {k.lower(): v for k, v in resp.headers.items() if k.lower() != "date"}

    assert _h(r_trampa) == _h(r_ok)

    assert _count(db_session, "99885601") == 1, "el envio legitimo SI debe escribir"
    assert _count(db_session, "99885602") == 0, "la trampa NO debe escribir nada"


def test_e8_las_tres_ramas_son_identicas_byte_a_byte(
    client, db_session, make_cohort, make_student, make_process, seed_phase_defs,
):
    """'nueva', 'ya hay solicitud viva' y 'ya tiene proceso' no se distinguen (E8).

    Si se distinguieran, el endpoint sería un oráculo anónimo de "¿existe este
    número de control?" y "¿esta persona se está titulando?".
    """
    seed_phase_defs()
    otra = make_cohort(status="closed")
    cohort = make_cohort(status="open")
    inscrito = make_student(control_number="99880001")
    make_process(inscrito, cohort=otra)
    _solo_esta_convocatoria(db_session, cohort)
    client.cookies.clear()

    r_ok = client.post(ENROLL_URL,
                       data=_form(control_number="99880002"),
                       headers={"X-Real-IP": "203.0.113.21"}, follow_redirects=False)
    r_dup = client.post(ENROLL_URL,
                        data=_form(control_number="99880002"),
                        headers={"X-Real-IP": "203.0.113.22"}, follow_redirects=False)
    r_proc = client.post(ENROLL_URL,
                         data=_form(control_number="99880001"),
                         headers={"X-Real-IP": "203.0.113.23"}, follow_redirects=False)

    assert r_ok.status_code == r_dup.status_code == r_proc.status_code == 200

    # Cuerpo idéntico BYTE A BYTE, no "parecido".
    assert r_ok.content == r_dup.content
    assert r_ok.content == r_proc.content

    def _h(resp):
        return {k.lower(): v for k, v in resp.headers.items() if k.lower() != "date"}

    assert _h(r_ok) == _h(r_dup)
    assert _h(r_ok) == _h(r_proc)
    assert cohort.name not in r_ok.text
    assert 'data-tt-notice="generic"' in r_ok.text
    assert TITULO_TARJETA in r_ok.text
    assert CUERPO_TARJETA in _plano(r_ok.text)
    assert _count(db_session, "99880002") == 1, "la segunda vuelta no crea otra fila"


def test_una_excepcion_en_create_no_produce_500_y_devuelve_la_tarjeta_generica(
    client, db_session, make_cohort, monkeypatch,
):
    """Ninguna entrada del visitante puede producir un 500 (docstring del módulo)."""
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )

    def _revienta(*a, **kw):
        raise ValueError("fallo de escritura simulado")

    cohort = make_cohort(status="open")
    _solo_esta_convocatoria(db_session, cohort)
    # El `except` de la ruta hace `db.rollback()`: sin este checkpoint el
    # rollback se llevaría también la convocatoria y el cierre de las demás.
    db_session.commit()
    client.cookies.clear()
    monkeypatch.setattr(EnrollmentRequestService, "create", staticmethod(_revienta))

    resp = client.post(ENROLL_URL, data=_form(control_number="99885001"),
                       headers={"X-Real-IP": "203.0.113.24"}, follow_redirects=False)

    assert resp.status_code == 200, resp.text[:400]
    assert TITULO_TARJETA in resp.text
    assert _count(db_session, "99885001") == 0


# ---------------------------------------------------------------------------
# RULING R1/R2 — leer antes / cobrar después, presupuestos y Retry-After
# ---------------------------------------------------------------------------
def test_los_presupuestos_del_limitador_son_los_acordados():
    """R1/R2 del controlador: 30/hora por IP (no 5), 3/día por control."""
    from itcj2.apps.titulatec.pages import public as mod

    assert mod.ENROLL_RL_LIMIT_IP == 30
    assert mod.ENROLL_RL_WINDOW_IP == 3600
    assert mod.ENROLL_RL_LIMIT_CN == 3
    assert mod.ENROLL_RL_WINDOW_CN == 86400


@pytest.mark.parametrize("errata", [
    {"control_number": "abc"},
    {"contact_email_confirm": "otro@example.invalid"},
    {"has_english": "0"},
], ids=["control-invalido", "correos-distintos", "sin-ingles"])
def test_un_envio_invalido_no_gasta_presupuesto_de_ip(
    client, db_session, make_cohort, monkeypatch, errata,
):
    """R1: `check_only` antes de trabajar, `check_and_count` solo tras éxito.

    Tres erratas de formulario desde la MISMA IP no deben gastar el cubo: si
    lo hicieran, un límite de 1 dejaría sin poder inscribirse a quien se
    equivocó llenando el formulario, que no es un atacante.
    """
    from itcj2.apps.titulatec.pages import public as mod

    cohort = make_cohort(status="open")
    _solo_esta_convocatoria(db_session, cohort)
    client.cookies.clear()
    monkeypatch.setattr(mod, "ENROLL_RL_LIMIT_IP", 1)
    headers = {"X-Real-IP": "203.0.113.31"}

    for _ in range(3):
        r = client.post(ENROLL_URL, data=_form(**errata),
                        headers=headers, follow_redirects=False)
        assert r.status_code == 200
        assert 'id="tt-enroll-form"' in r.text

    ok = client.post(ENROLL_URL, data=_form(control_number="99885002"),
                     headers=headers, follow_redirects=False)
    assert TITULO_TARJETA in ok.text, "las erratas previas gastaron presupuesto de IP"


def test_una_excepcion_en_create_no_gasta_presupuesto_de_ip_ni_de_cn(
    client, db_session, make_cohort, monkeypatch,
):
    """R1/R2: "que un create que falle no queme uno de los tres intentos"."""
    from itcj2.apps.titulatec.pages import public as mod
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )

    llamadas = {"n": 0}
    original = EnrollmentRequestService.create

    def _falla_una_vez(db, cohort, data, *, client_ip):
        llamadas["n"] += 1
        if llamadas["n"] == 1:
            raise RuntimeError("fallo simulado de escritura")
        return original(db, cohort, data, client_ip=client_ip)

    cohort = make_cohort(status="open")
    _solo_esta_convocatoria(db_session, cohort)
    # Checkpoint OBLIGATORIO antes de forzar el fallo: la ruta hace un
    # `db.rollback()` REAL, y bajo `join_transaction_mode="create_savepoint"`
    # eso deshace todo lo no confirmado desde el último `commit()` —la
    # convocatoria recién creada y el cierre de las demás incluidos—.
    db_session.commit()
    client.cookies.clear()
    monkeypatch.setattr(mod, "ENROLL_RL_LIMIT_IP", 1)
    monkeypatch.setattr(mod, "ENROLL_RL_LIMIT_CN", 1)
    monkeypatch.setattr(EnrollmentRequestService, "create", staticmethod(_falla_una_vez))
    headers = {"X-Real-IP": "203.0.113.32"}

    primero = client.post(ENROLL_URL, data=_form(control_number="99885003"),
                          headers=headers, follow_redirects=False)
    assert primero.status_code == 200, primero.text[:400]
    assert TITULO_TARJETA in primero.text

    segundo = client.post(ENROLL_URL, data=_form(control_number="99885003"),
                          headers=headers, follow_redirects=False)

    assert TITULO_TARJETA in segundo.text, (
        "el intento fallido gasto presupuesto: el reintento legitimo se topo "
        "con el limite"
    )
    assert llamadas["n"] == 2, "el reintento debe haber llegado a create()"


def test_limite_por_ip_corta_y_devuelve_retry_after(
    client, db_session, make_cohort, monkeypatch,
):
    from itcj2.apps.titulatec.pages import public as mod

    cohort = make_cohort(status="open")
    _solo_esta_convocatoria(db_session, cohort)
    client.cookies.clear()
    monkeypatch.setattr(mod, "ENROLL_RL_LIMIT_IP", 3)
    headers = {"X-Real-IP": "203.0.113.33"}

    for i in range(3):
        r = client.post(ENROLL_URL, data=_form(control_number=f"9988510{i}"),
                        headers=headers, follow_redirects=False)
        assert r.status_code == 200, r.text[:300]
        assert TITULO_TARJETA in r.text

    r4 = client.post(ENROLL_URL, data=_form(control_number="99885109"),
                     headers=headers, follow_redirects=False)

    assert r4.status_code == 200
    assert "Demasiados intentos" in r4.text
    assert int(r4.headers.get("Retry-After", "0")) > 0


def test_limite_por_numero_de_control_corta_al_cuarto_intento(
    client, db_session, make_cohort,
):
    """`enroll:cn` es 3/día: el control es el anti-abuso real (va por identidad).

    IPs DISTINTAS en cada intento para aislar el cubo bajo prueba del de IP.
    """
    cohort = make_cohort(status="open")
    _solo_esta_convocatoria(db_session, cohort)
    client.cookies.clear()
    control = "99885200"

    for i in range(3):
        r = client.post(ENROLL_URL, data=_form(control_number=control),
                        headers={"X-Real-IP": f"203.0.113.{40 + i}"},
                        follow_redirects=False)
        assert r.status_code == 200, r.text[:300]
        assert TITULO_TARJETA in r.text

    r4 = client.post(ENROLL_URL, data=_form(control_number=control),
                     headers={"X-Real-IP": "203.0.113.49"}, follow_redirects=False)

    assert r4.status_code == 200
    assert "Demasiados intentos" in r4.text
    assert int(r4.headers.get("Retry-After", "0")) > 0


def test_dos_IPs_anonimas_no_comparten_cubo(client, db_session, make_cohort, monkeypatch):
    from itcj2.apps.titulatec.pages import public as mod

    cohort = make_cohort(status="open")
    _solo_esta_convocatoria(db_session, cohort)
    client.cookies.clear()
    monkeypatch.setattr(mod, "ENROLL_RL_LIMIT_IP", 1)

    client.post(ENROLL_URL, data=_form(control_number="99885301"),
               headers={"X-Real-IP": "203.0.113.51"}, follow_redirects=False)

    otra = client.post(ENROLL_URL, data=_form(control_number="99885302"),
                       headers={"X-Real-IP": "203.0.113.52"}, follow_redirects=False)

    assert TITULO_TARJETA in otra.text, "otra IP arrastrada por el cubo ajeno"


def test_con_redis_caido_el_envio_se_niega_y_no_escribe(
    client, db_session, make_cohort, monkeypatch,
):
    """E2: `fail_open=False`. En una escritura ANONIMA, Redis es el único control."""
    def _boom():
        raise RuntimeError("redis caido")

    cohort = make_cohort(status="open")
    _solo_esta_convocatoria(db_session, cohort)
    client.cookies.clear()
    monkeypatch.setattr("itcj2.core.utils.redis_conn.get_redis", _boom)

    resp = client.post(ENROLL_URL, data=_form(control_number="99885401"),
                       headers={"X-Real-IP": "203.0.113.61"}, follow_redirects=False)

    assert resp.status_code == 200, resp.text[:300]
    assert "Demasiados intentos" in resp.text
    assert _count(db_session, "99885401") == 0


# ---------------------------------------------------------------------------
# RULING R3 — `_declared_body_size`, no un parser nuevo
# ---------------------------------------------------------------------------
def test_un_cuerpo_sin_content_length_se_rechaza_con_411(client, db_session, make_cohort):
    """Sin `Content-Length` (cuerpo `chunked`) el tope no puede aplicarse ANTES
    de leer el cuerpo, así que se rechaza en vez de dejarlo pasar SIN TOPE."""
    cohort = make_cohort(status="open")
    _solo_esta_convocatoria(db_session, cohort)
    client.cookies.clear()

    def cuerpo():
        yield b"website=&control_number=99885501&first_name=A"

    resp = client.post(
        ENROLL_URL, content=cuerpo(),
        headers={"X-Real-IP": "203.0.113.71",
                 "Content-Type": "application/x-www-form-urlencoded"},
        follow_redirects=False)

    assert resp.status_code == 411, resp.text[:300]
    assert "X-Tt-Error" in resp.headers
    assert _count(db_session, "99885501") == 0


def test_cuerpo_por_encima_del_tope_se_rechaza_con_413(client, db_session, make_cohort):
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        MAX_PUBLIC_BODY_BYTES,
    )

    cohort = make_cohort(status="open")
    _solo_esta_convocatoria(db_session, cohort)
    client.cookies.clear()
    payload = _form(program_text="x" * (MAX_PUBLIC_BODY_BYTES + 1024))

    resp = client.post(ENROLL_URL, data=payload,
                       headers={"X-Real-IP": "203.0.113.72"}, follow_redirects=False)

    assert resp.status_code == 413, resp.text[:200]
    assert "X-Tt-Error" in resp.headers
    assert _count(db_session, "99880002") == 0


def test_enroll_submit_no_define_su_propio_parser_de_tamano():
    """R3: `_enroll_too_big` debe estar BORRADO, no solo sin usar."""
    from itcj2.apps.titulatec.pages import public as mod

    assert not hasattr(mod, "_enroll_too_big"), (
        "R3 pide borrar `_enroll_too_big` por completo y reutilizar "
        "`_declared_body_size`, no dejarlo como codigo muerto al lado."
    )


# ---------------------------------------------------------------------------
# RULING R4 — la trampa es `.tt-public-hp`, sin una segunda clase CSS
# ---------------------------------------------------------------------------
def test_la_inscripcion_no_agrega_una_segunda_clase_de_trampa_en_css():
    """Dos clases para lo mismo dejan el campo A LA VISTA en cuanto un markup
    apunte a la que se quede sin regla."""
    import itcj2
    from pathlib import Path

    css = (Path(itcj2.__file__).resolve().parent / "apps" / "titulatec" / "static"
           / "css" / "public.css").read_text(encoding="utf-8")

    ocurrencias = css.count(".tt-public-hp {") + css.count(".tt-public-hp{")
    assert ocurrencias == 1, (
        f"`.tt-public-hp` debe declararse UNA sola vez en todo el archivo; "
        f"se encontraron {ocurrencias}."
    )
    for prohibida in (".tt-honeypot", ".tt-enroll-hp", ".tt-hp {"):
        assert prohibida not in css, f"clase de trampa duplicada: {prohibida!r}"


def test_el_formulario_usa_tt_public_hp_y_no_una_clase_propia(
    client, db_session, make_cohort,
):
    cohort = make_cohort(status="open")
    _solo_esta_convocatoria(db_session, cohort)
    client.cookies.clear()

    resp = client.get(ENROLL_URL, follow_redirects=False)

    assert resp.status_code == 200
    assert "tt-public-hp" in resp.text
    assert "tt-honeypot" not in resp.text
