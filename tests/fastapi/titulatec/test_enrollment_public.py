"""Formulario público de auto-inscripción: ventana, validación y E8.

Todo va con `follow_redirects=False` y `client.cookies.clear()`: estas rutas son
públicas y un 302 al login seguido devolvería 200 y la prueba pasaría por la
razón equivocada (§11.1 del diseño).

Cada POST lleva su propio `X-Real-IP`: `client_ip()` la prefiere sobre
`request.client.host`, que para el `TestClient` es siempre "testclient" y
metería todos los tests en el MISMO cubo de `rl:enroll:ip:*` (mismo motivo que
documenta `test_survey_submit_routes.py`). El autouse `_clear_authz_cache`
(`tests/fastapi/conftest.py`) barre `rl:*` antes y después de cada test.

El nivel SERVICIO (outcomes de `create()`, destinatario del token, presupuesto
de `_send_verify`) vive en `test_enrollment_request_service.py`; aquí todo pasa
por HTTP, que es donde viven las defensas que el servicio no ve: la ventana de
la convocatoria, la trampa, el tope de tamaño y el limitador.
"""
from __future__ import annotations


ENROLL_URL = "/titulatec/inscripcion"


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
        "has_efirma": "0",
        "website": "",
    }
    base.update(kw)
    return base


def _count(db_session, control_number):
    """Filas de `EnrollmentRequest` para UN número de control.

    A propósito SIN default ni variante "cuenta todo": la BD de dev compartida
    acumula filas de QA manual de otras tareas (misma advertencia que las
    restricciones del plan hacen sobre `database/`), y un `count()` sin filtro
    pasaba HOY solo porque nadie más escribía en esta tabla todavía. El primer
    QA manual contra el mismo contenedor deja una fila y las aserciones fallan
    por un motivo que no tiene nada que ver con lo que cada test comprueba.
    Cada llamada se acota por el número de control que ESE test mandó.
    """
    from itcj2.apps.titulatec.models import EnrollmentRequest
    return (db_session.query(EnrollmentRequest)
            .filter_by(control_number=control_number).count())


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
    assert "Inglés" not in resp.text               # el inglés NO se pregunta (D11)
    assert cohort.name not in resp.text            # sin nombre de convocatoria


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
    assert 'value="abc"' in resp.text              # el servidor conserva lo capturado
    assert _count(db_session, "abc") == 0


def test_correo_invalido_devuelve_200_con_el_formulario_y_error_inline(
    client, db_session, make_cohort,
):
    cohort = make_cohort(status="open")
    _solo_esta_convocatoria(db_session, cohort)
    client.cookies.clear()

    resp = client.post(ENROLL_URL,
                       data=_form(contact_email="no-es-correo"),
                       headers={"X-Real-IP": "203.0.113.12"},
                       follow_redirects=False)

    assert resp.status_code == 200, resp.text[:400]
    assert 'id="tt-enroll-form"' in resp.text
    assert "correo personal válido" in resp.text
    assert _count(db_session, "99880002") == 0


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
    """§6.6, rama POST. Ronda de arreglos 1, Important 2.

    `enroll_form.html` manda este POST con `hx-post` + `hx-swap="outerHTML"`, y
    htmx NO hace swap en un 5xx: un `render_titulatec(..., status_code=503)`
    con el aviso en el CUERPO se descarta en silencio y el visitante ve en su
    lugar el toast genérico de `tt-errors.js` ("No se pudo completar la
    acción..."), porque no hay `X-Tt-Error` que le dé el texto bueno. Mismo
    patrón que el 411/413 de arriba: `Response` SIN formulario, con el mensaje
    en la CABECERA, no en un cuerpo que nadie va a pintar.
    """
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
# Trampa (E3) y E8 — las salidas indistinguibles
# ---------------------------------------------------------------------------
def test_la_trampa_no_escribe_nada_y_devuelve_la_tarjeta_generica(
    client, db_session, make_cohort,
):
    """La trampa es la CUARTA salida indistinguible, no solo la de E8 (item 2
    de "lo que no puede fallar" en el despacho de la Tarea 19): un bot que la
    llena tiene que recibir una respuesta idéntica BYTE A BYTE a la de un
    envío legítimo, no solo "algo que también diga Revisa tu correo". Si se
    distinguiera aunque fuera por una coma, un bot sabría que fue detectado —
    exactamente la señal que la trampa existe para no dar.
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
    assert "Revisa tu correo" in r_trampa.text

    # Cuerpo idéntico BYTE A BYTE contra un envío legítimo real, no "parecido".
    assert r_trampa.content == r_ok.content

    def _h(resp):
        # `date` se excluye porque puede saltar de segundo entre peticiones; es
        # lo único que el servidor no controla. Mismo criterio que el test de
        # las otras tres ramas de E8, abajo.
        return {k.lower(): v for k, v in resp.headers.items() if k.lower() != "date"}

    assert _h(r_trampa) == _h(r_ok)

    assert _count(db_session, "99885601") == 1, "el envio legitimo SI debe escribir"
    assert _count(db_session, "99885602") == 0, "la trampa NO debe escribir nada"


def test_e8_las_tres_ramas_son_identicas_byte_a_byte(
    client, db_session, make_cohort, make_student, make_process, seed_phase_defs,
):
    """'ok', 'ya hay solicitud' y 'ya tiene proceso' no se distinguen (E8).

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
        # `date` se excluye porque puede saltar de segundo entre peticiones; es
        # lo único que el servidor no controla.
        return {k.lower(): v for k, v in resp.headers.items() if k.lower() != "date"}

    assert _h(r_ok) == _h(r_dup)
    assert _h(r_ok) == _h(r_proc)
    assert cohort.name not in r_ok.text


def test_una_excepcion_en_create_no_produce_500_y_devuelve_la_tarjeta_generica(
    client, db_session, make_cohort, monkeypatch,
):
    """Ninguna entrada del visitante puede producir un 500 (docstring del módulo).

    Se fuerza con `monkeypatch` sobre `create` porque el objetivo es «cualquier
    excepción», igual que el equivalente de la encuesta
    (`test_si_la_escritura_revienta_el_visitante_recupera_su_cuestionario`).
    """
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )

    def _revienta(*a, **kw):
        raise ValueError("fallo de escritura simulado")

    cohort = make_cohort(status="open")
    _solo_esta_convocatoria(db_session, cohort)
    client.cookies.clear()
    monkeypatch.setattr(EnrollmentRequestService, "create", staticmethod(_revienta))

    resp = client.post(ENROLL_URL, data=_form(control_number="99885001"),
                       headers={"X-Real-IP": "203.0.113.24"}, follow_redirects=False)

    assert resp.status_code == 200, resp.text[:400]
    assert "Revisa tu correo" in resp.text
    assert _count(db_session, "99885001") == 0


# ---------------------------------------------------------------------------
# RULING R1/R2 — leer antes / cobrar después, presupuestos y Retry-After
# ---------------------------------------------------------------------------
def test_los_presupuestos_del_limitador_son_los_acordados():
    """R1/R2 del controlador: 30/hora por IP (no 5), 3/día por control.

    Este test no defiende un número mágico: defiende que bajarlo del brief
    original (5/hora) sea una decisión visible en la revisión y no un
    descuido — el brief traía 5/hora, que deja fuera a una generación entera
    de egresados saliendo por la única IP pública del ITCJ.
    """
    from itcj2.apps.titulatec.pages import public as mod

    assert mod.ENROLL_RL_LIMIT_IP == 30
    assert mod.ENROLL_RL_WINDOW_IP == 3600
    assert mod.ENROLL_RL_LIMIT_CN == 3
    assert mod.ENROLL_RL_WINDOW_CN == 86400


def test_un_envio_invalido_no_gasta_presupuesto_de_ip(
    client, db_session, make_cohort, monkeypatch,
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
        r = client.post(ENROLL_URL, data=_form(control_number="abc"),
                        headers=headers, follow_redirects=False)
        assert r.status_code == 200
        assert 'id="tt-enroll-form"' in r.text

    ok = client.post(ENROLL_URL, data=_form(control_number="99885002"),
                     headers=headers, follow_redirects=False)
    assert "Revisa tu correo" in ok.text, "las erratas previas gastaron presupuesto de IP"


def test_una_excepcion_en_create_no_gasta_presupuesto_de_ip_ni_de_cn(
    client, db_session, make_cohort, monkeypatch,
):
    """R1/R2: "que un create que falle no queme uno de los tres intentos".

    Se fuerza UNA excepción en `create` con los cubos en 1 (IP) y 1 (CN). Si el
    intento fallido hubiera cobrado, el reintento —MISMOS ip y control— se
    encontraria el cubo agotado y veria la tarjeta de "demasiados intentos" en
    vez de la generica.
    """
    from itcj2.apps.titulatec.pages import public as mod
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )

    llamadas = {"n": 0}
    # `create` es un @staticmethod: leído desde la CLASE ya es la función
    # plana (sin `self`/`cls`), así que no lleva `__func__` que desenvolver.
    original = EnrollmentRequestService.create

    def _falla_una_vez(db, cohort, data, *, client_ip):
        llamadas["n"] += 1
        if llamadas["n"] == 1:
            raise RuntimeError("fallo simulado de escritura")
        return original(db, cohort, data, client_ip=client_ip)

    cohort = make_cohort(status="open")
    _solo_esta_convocatoria(db_session, cohort)
    # Checkpoint OBLIGATORIO antes de forzar el fallo (hallazgo de la Tarea 27,
    # ronda de arreglos contra base vacía). `make_cohort` y
    # `_solo_esta_convocatoria` solo hacen `flush()`, nunca `commit()` -viven
    # sin confirmar en la MISMA transacción que el resto del test-. Esta
    # prueba, a diferencia de sus vecinas, dispara un `db.rollback()` REAL de
    # la aplicación (`pages/public.py`, correcto y necesario en producción)
    # a mitad del test: bajo `join_transaction_mode="create_savepoint"`
    # (`tests/fastapi/conftest.py`), ese rollback deshace TODO lo no
    # confirmado desde el último `commit()`, y sin este `commit()` explícito
    # eso incluye la convocatoria recién creada y el cierre de las demás.
    # Contra una base vacía (`itcj_ci`, sin DML) el segundo POST no encontraba
    # NINGUNA convocatoria abierta y caía en la tarjeta de "cerrada"; contra
    # el `itcj` de dev el mismo rollback también reabría la convocatoria REAL
    # del DML, y el segundo POST pasaba igual pero usando esa convocatoria
    # ajena -la prueba pasaba por la razón equivocada, enmascarada por datos
    # sembrados que nada tienen que ver con lo que aquí se afirma-. El
    # `commit()` de abajo libera el SAVEPOINT de la fixture (queda protegido
    # incluso de un `rollback()` posterior en la MISMA sesión) sin comprometer
    # nada fuera de la transacción del test: `trans.rollback()` al final del
    # fixture `db_session` sigue limpiando todo. Deliberadamente NO se mueve
    # este `commit()` a `make_cohort`/`_solo_esta_convocatoria`: son fábricas
    # compartidas por decenas de pruebas de este archivo y de otros, y
    # commitear ahí de forma general cambiaría el punto de rollback de
    # CUALQUIER prueba que las use, no solo de la que aquí fuerza un fallo de
    # escritura real.
    db_session.commit()
    client.cookies.clear()
    monkeypatch.setattr(mod, "ENROLL_RL_LIMIT_IP", 1)
    monkeypatch.setattr(mod, "ENROLL_RL_LIMIT_CN", 1)
    monkeypatch.setattr(EnrollmentRequestService, "create", staticmethod(_falla_una_vez))
    headers = {"X-Real-IP": "203.0.113.32"}

    primero = client.post(ENROLL_URL, data=_form(control_number="99885003"),
                          headers=headers, follow_redirects=False)
    assert primero.status_code == 200, primero.text[:400]
    assert "Revisa tu correo" in primero.text

    segundo = client.post(ENROLL_URL, data=_form(control_number="99885003"),
                          headers=headers, follow_redirects=False)

    assert "Revisa tu correo" in segundo.text, (
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
        assert "Revisa tu correo" in r.text

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
        assert "Revisa tu correo" in r.text

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

    assert "Revisa tu correo" in otra.text, "otra IP arrastrada por el cubo ajeno"


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
    de leer el cuerpo, así que se rechaza en vez de dejarlo pasar SIN TOPE.

    Es el hueco concreto que R3 cierra: `_enroll_too_big` del brief devolvía
    `False` (no toca el límite) cuando la cabecera faltaba, y entonces
    `await request.form()` bufferaba el cuerpo entero sin ningún tope.
    """
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
    """El propio `public.css` advierte por escrito: dos clases para lo mismo
    dejan el campo A LA VISTA en cuanto un markup apunte a la que se quede sin
    regla. Esta tarea NO debe añadir `.tt-honeypot`, `.tt-enroll-hp` ni
    ninguna otra; el honeypot del formulario de inscripción usa la MISMA
    `.tt-public-hp` que ya vive en la capa de la base pública (T11/T12).
    """
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
