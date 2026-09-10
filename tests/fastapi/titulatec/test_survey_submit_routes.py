"""POST publico de la encuesta: escritura, trampa, tope de tamano y limite.

Todas las peticiones llevan `X-Real-IP` propio: `client_ip()` lo prefiere sobre
`request.client.host`, que para el `TestClient` es siempre "testclient" y meteria
todos los tests en el MISMO cubo de `rl:survey:ip:*`. (El autouse
`_clear_authz_cache` barre `rl:*` antes y despues de cada test, asi que ademas
las corridas repetidas son idempotentes; las IPs distintas son el cinturon.)

El nivel SERVICIO lo cubre `test_survey_submit.py` (Tarea 10); aqui todo pasa
por HTTP, que es donde viven las defensas que el servicio no ve: el tope del
cuerpo, la trampa, el limitador y el contrato de codigos de respuesta.
"""
from __future__ import annotations

import re

import pytest

SURVEY_URL = "/titulatec/encuesta-egresados"

OK_PAYLOAD = {
    "website": "",
    "situacion_laboral": "empleado",
    "relacion_carrera": "4",
    "areas_fuertes": ["tecnica", "idiomas"],
    "comentarios": "Mas practicas profesionales.",
}


def _responses(db_session):
    from itcj2.apps.titulatec.models import SurveyResponse
    return db_session.query(SurveyResponse).all()


def orm_en(valor, _ruta="ctx", _visto=None):
    """Rutas del contexto que llevan una instancia ORM. Vacia == contexto plano.

    Vive aqui y lo importa tambien el archivo del GET: es la unica forma de
    medir la trampa de este arnes. `_TestSession.close()` es un no-op
    deliberado, asi que la sesion de la ruta nunca se cierra, nada se desasocia
    y un `DetachedInstanceError` NO puede reproducirse en pytest: pasar un
    `SurveyForm` a la plantilla renderiza verde aqui y revienta en produccion en
    cuanto el `finally` cierra de verdad. Por eso se mide la FORMA del contexto
    y no el HTML.
    """
    from itcj2.models.base import Base

    _visto = _visto if _visto is not None else set()
    if id(valor) in _visto:
        return []
    _visto.add(id(valor))

    if isinstance(valor, Base):
        return [f"{_ruta} -> {type(valor).__name__}"]
    if isinstance(valor, dict):
        malos = []
        for k, v in valor.items():
            if k in ("request", "sv", "sv_core"):     # los inyecta render_titulatec
                continue
            malos += orm_en(v, f"{_ruta}[{k!r}]", _visto)
        return malos
    if isinstance(valor, (list, tuple, set)):
        malos = []
        for i, v in enumerate(valor):
            malos += orm_en(v, f"{_ruta}[{i}]", _visto)
        return malos
    return []


@pytest.fixture()
def requisito_de_encuesta(db_session):
    """El requisito que la encuesta acredita, en la convocatoria que se le pase."""
    from itcj2.apps.titulatec.models import CotejoRequirement
    from itcj2.apps.titulatec.services.survey_service import AUTO_SOURCE_SURVEY

    def _make(cohort):
        row = CotejoRequirement(
            cohort_id=cohort.id, icon="clipboard-check",
            label="Encuesta de egresados",
            hint="Comprobante de haberla contestado.",
            order_index=0, is_required=True, is_active=True,
            code="graduate_survey", auto_source=AUTO_SOURCE_SURVEY,
        )
        db_session.add(row)
        db_session.flush()
        return row

    return _make


# ---------------------------------------------------------------------------
# Escritura
# ---------------------------------------------------------------------------
def test_anonimo_escribe_respuesta_sin_user_id(client, make_survey_form, db_session):
    """Criterio 1: fila con `user_id` NULL e `identity_source='anonymous'`."""
    make_survey_form()
    client.cookies.clear()

    resp = client.post(SURVEY_URL, data=OK_PAYLOAD,
                       headers={"X-Real-IP": "203.0.113.21"}, follow_redirects=False)

    assert resp.status_code == 200, resp.text[:500]
    assert 'id="tt-survey-thanks"' in resp.text
    filas = _responses(db_session)
    assert len(filas) == 1
    assert filas[0].user_id is None
    assert filas[0].identity_source == "anonymous"


def test_con_sesion_escribe_respuesta_con_user_id(
    client_as, make_student, make_survey_form, db_session,
):
    """Con sesion: `identity_source='session'` y el `user_id` real."""
    make_survey_form()
    student = make_student()

    resp = client_as(student).post(SURVEY_URL, data=OK_PAYLOAD,
                                   headers={"X-Real-IP": "203.0.113.22"},
                                   follow_redirects=False)

    assert resp.status_code == 200, resp.text[:500]
    filas = _responses(db_session)
    assert len(filas) == 1
    assert filas[0].user_id == student.id
    assert filas[0].identity_source == "session"


def test_el_multiselect_guarda_TODAS_las_opciones_marcadas(
    client, make_survey_form, db_session,
):
    """La trampa medida de la Tarea 10, en el nivel donde de verdad ocurre.

    `FormData` NO colapsa las llaves repetidas: para
    `[("areas_fuertes","tecnica"),("areas_fuertes","idiomas")]`, tanto
    `.get()` como `dict()` devuelven SOLO `'idiomas'`. Pasar el `FormData` a
    `submit` hace fallar TODO multiselect con "se esperaba una lista de
    opciones" —culpando a un campo que el visitante lleno bien— y aqui, con la
    llave marcada dos veces, guardaria una sola opcion. El puente
    (`form_to_dict`) usa `getlist()` para las llaves que el schema declara
    `multiselect`.
    """
    from itcj2.apps.titulatec.models import SurveyAnswer

    make_survey_form()
    client.cookies.clear()

    resp = client.post(SURVEY_URL, data=OK_PAYLOAD,
                       headers={"X-Real-IP": "203.0.113.27"}, follow_redirects=False)

    assert resp.status_code == 200, resp.text[:500]
    assert 'id="tt-survey-thanks"' in resp.text, "un multiselect valido fue rechazado"
    fila = _responses(db_session)[0]
    assert fila.answers["areas_fuertes"] == ["tecnica", "idiomas"]
    marcadas = (db_session.query(SurveyAnswer)
                .filter_by(response_id=fila.id, field_key="areas_fuertes").all())
    assert sorted(a.value_text for a in marcadas) == ["idiomas", "tecnica"]


def test_una_pregunta_opcional_en_blanco_no_rechaza_el_envio(
    client, make_survey_form, db_session,
):
    """Un grupo de casillas sin marcar NO manda su llave, y eso es legitimo.

    Es el caso mayoritario de la encuesta real —dos de los cuatro campos son
    opcionales— y el que se rompe en silencio: si el envio se rechaza, el error
    aparece colgado de una pregunta que nadie estaba obligado a contestar.
    """
    make_survey_form()
    client.cookies.clear()
    # Sin `areas_fuertes` y sin `comentarios`. `relacion_carrera` no viaja
    # porque su `visible_when` no se cumple: quien busca empleo no la ve.
    payload = {"website": "", "situacion_laboral": "buscando"}

    resp = client.post(SURVEY_URL, data=payload,
                       headers={"X-Real-IP": "203.0.113.28"}, follow_redirects=False)

    assert resp.status_code == 200, resp.text[:500]
    assert 'id="tt-survey-thanks"' in resp.text, (
        "un envio valido con opcionales en blanco fue rechazado: " + resp.text[:400])
    assert len(_responses(db_session)) == 1


def test_el_envio_de_un_alumno_con_proceso_acredita_y_lo_dice(
    client_as, make_student, make_survey_form, make_cohort, make_process,
    requisito_de_encuesta, db_session,
):
    """`credit_status='credited'`: la tarjeta lo dice y el cumplimiento existe."""
    from itcj2.apps.titulatec.models import RequirementFulfillment

    make_survey_form()
    student = make_student()
    cohort = make_cohort()
    proc = make_process(student, cohort=cohort, current_phase=1)
    req = requisito_de_encuesta(cohort)

    resp = client_as(student).post(SURVEY_URL, data=OK_PAYLOAD,
                                   headers={"X-Real-IP": "203.0.113.29"},
                                   follow_redirects=False)

    assert resp.status_code == 200, resp.text[:500]
    assert 'data-tt-credit="credited"' in resp.text
    assert (db_session.query(RequirementFulfillment)
            .filter_by(process_id=proc.id, requirement_id=req.id).count() == 1)


def test_el_envio_de_un_alumno_sin_proceso_lo_dice_distinto(
    client_as, make_student, make_survey_form,
):
    """`no_process` no puede leerse igual que `credited`: uno acredita y otro no."""
    make_survey_form()

    resp = client_as(make_student()).post(SURVEY_URL, data=OK_PAYLOAD,
                                          headers={"X-Real-IP": "203.0.113.30"},
                                          follow_redirects=False)

    assert resp.status_code == 200, resp.text[:500]
    assert 'data-tt-credit="no_process"' in resp.text


def test_la_tarjeta_de_gracias_tiene_copy_propio_para_los_cinco_creditos():
    """Los cinco valores del dominio, con texto distinto cada uno.

    Un `credit_status` sin rama renderiza un mensaje en blanco —o el de otro
    caso—, y entonces un fallo de configuracion (`no_requirement`) se vuelve
    indistinguible de un exito. Se renderiza el parcial directo porque provocar
    los cinco por HTTP costaria cinco escenarios de BD para medir cinco cadenas.
    """
    from itcj2.apps.titulatec.pages.nav import titulatec_templates

    tpl = titulatec_templates.env.get_template(
        "titulatec/public/partials/survey_thanks.html")

    textos = {}
    for estado in ("anonymous", "no_process", "no_requirement", "already", "credited"):
        html = tpl.render(credit_status=estado)
        assert f'data-tt-credit="{estado}"' in html
        plano = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()
        assert len(plano) > 40, f"{estado}: mensaje vacio o de relleno ({plano!r})"
        textos[estado] = plano

    assert len(set(textos.values())) == 5, (
        "dos estados de credito se leen igual: "
        + repr({k: v[:60] for k, v in textos.items()}))


# ---------------------------------------------------------------------------
# Trampa, tope y limite
# ---------------------------------------------------------------------------
def test_trampa_llena_devuelve_tarjeta_de_exito_y_no_escribe_nada(
    client, make_survey_form, db_session,
):
    """Honeypot: misma tarjeta generica, CERO filas."""
    make_survey_form()
    client.cookies.clear()
    payload = dict(OK_PAYLOAD, website="http://spam.example")

    resp = client.post(SURVEY_URL, data=payload,
                       headers={"X-Real-IP": "203.0.113.23"}, follow_redirects=False)

    assert resp.status_code == 200, resp.text[:500]
    assert 'id="tt-survey-thanks"' in resp.text
    assert _responses(db_session) == []


def test_cuerpo_por_encima_del_tope_se_rechaza_con_413(
    client, make_survey_form, db_session,
):
    """El tope va ANTES de `request.form()`, que bufferea el cuerpo entero."""
    from itcj2.apps.titulatec.services.survey_service import MAX_PUBLIC_BODY_BYTES

    make_survey_form()
    client.cookies.clear()
    payload = dict(OK_PAYLOAD, comentarios="x" * (MAX_PUBLIC_BODY_BYTES + 1024))

    resp = client.post(SURVEY_URL, data=payload,
                       headers={"X-Real-IP": "203.0.113.25"}, follow_redirects=False)

    assert resp.status_code == 413, resp.text[:200]
    assert "X-Tt-Error" in resp.headers
    assert _responses(db_session) == []


def test_los_presupuestos_del_limitador_son_los_acordados():
    """Los numeros van fijados porque cambiarlos tiene consecuencias visibles.

    El §8.1 del spec decia 10/hora por IP. El ITCJ entero sale a internet por UNA
    direccion publica, asi que ese numero deja sin encuesta —que es requisito de
    titulacion— a toda la generacion en cuanto la contestan diez personas desde
    el wifi del campus. Se subio a 60 y se abrio un cubo aparte para quien tiene
    sesion, que esta identificado y no tiene por que compartirlo con nadie.

    Este test no defiende un numero magico: defiende que bajarlo sea una
    decision visible en la revision y no un descuido.
    """
    from itcj2.apps.titulatec.pages import public as mod

    assert mod.SURVEY_RL_LIMIT_IP == 60
    assert mod.SURVEY_RL_LIMIT_USER == 30
    assert mod.SURVEY_RL_WINDOW == 3600


def test_un_envio_invalido_no_gasta_presupuesto(
    client, make_survey_form, db_session, monkeypatch,
):
    """Equivocarse no es atacar.

    `check_and_count` hace `INCR` ANTES de comparar, asi que ponerlo en la puerta
    cobra tambien los intentos que no escribieron nada: un egresado que se
    equivoca en un campo obligatorio tantas veces como diga el limite se queda
    fuera de una encuesta OBLIGATORIA durante una hora entera, sin haber
    guardado ni una respuesta. El presupuesto lo gasta lo que se escribio.

    El limite se baja a 2 con `monkeypatch` para no mandar 60 cuestionarios: lo
    que se mide es la SEMANTICA del contador, no su valor.
    """
    from itcj2.apps.titulatec.pages import public as mod

    make_survey_form()
    client.cookies.clear()
    monkeypatch.setattr(mod, "SURVEY_RL_LIMIT_IP", 2)
    cabeceras = {"X-Real-IP": "203.0.113.51"}
    invalido = {"website": "", "situacion_laboral": ""}

    for intento in range(3):
        r = client.post(SURVEY_URL, data=invalido, headers=cabeceras,
                        follow_redirects=False)
        assert r.status_code == 200, f"intento fallido {intento + 1}: {r.text[:200]}"
        assert 'id="tt-survey-form"' in r.text

    # Con el presupuesto intacto, los dos envios buenos entran.
    for intento in range(2):
        r = client.post(SURVEY_URL, data=OK_PAYLOAD, headers=cabeceras,
                        follow_redirects=False)
        assert 'id="tt-survey-thanks"' in r.text, (
            f"el envio bueno {intento + 1} se rechazo: las erratas previas "
            f"gastaron presupuesto")
    assert len(_responses(db_session)) == 2

    # Y el tercero, que si excede, se corta.
    corte = client.post(SURVEY_URL, data=OK_PAYLOAD, headers=cabeceras,
                        follow_redirects=False)
    assert 'data-tt-notice="rate_limited"' in corte.text
    assert len(_responses(db_session)) == 2


def test_al_agotar_el_presupuesto_no_se_borra_el_cuestionario(
    client, make_survey_form, db_session, monkeypatch,
):
    """El aviso va DENTRO del formulario, no en lugar del formulario.

    El destino del swap es `#tt-survey-form` con `outerHTML`: devolver solo la
    tarjeta sustituye el nodo del formulario y con el TODO lo que el visitante
    llevaba escrito, sin mas salida que recargar y empezar de cero. En un
    cuestionario de varias pantallas eso es perder la respuesta entera por haber
    pulsado Enviar una vez de mas.
    """
    from itcj2.apps.titulatec.pages import public as mod

    make_survey_form()
    client.cookies.clear()
    monkeypatch.setattr(mod, "SURVEY_RL_LIMIT_IP", 1)
    cabeceras = {"X-Real-IP": "203.0.113.52"}

    primero = client.post(SURVEY_URL, data=OK_PAYLOAD, headers=cabeceras,
                          follow_redirects=False)
    assert 'id="tt-survey-thanks"' in primero.text

    payload = dict(OK_PAYLOAD, comentarios="Me costo escribir esto.")
    resp = client.post(SURVEY_URL, data=payload, headers=cabeceras,
                       follow_redirects=False)

    assert resp.status_code == 200, resp.text[:300]
    assert 'data-tt-notice="rate_limited"' in resp.text
    assert 'id="tt-survey-form"' in resp.text, "el limite se llevo el formulario"
    assert "Me costo escribir esto." in resp.text, "el limite se llevo lo escrito"
    assert re.search(r'value="empleado"[^>]*\schecked', resp.text)
    assert int(resp.headers["Retry-After"]) > 0
    assert len(_responses(db_session)) == 1


def test_el_alumno_con_sesion_no_comparte_cubo_con_su_IP(
    client, client_as, make_student, make_survey_form, db_session, monkeypatch,
):
    """Un alumno identificado no puede quedarse fuera por culpa del campus.

    Todo el instituto sale por la misma direccion publica. Si quien inicia
    sesion cayera en el cubo de la IP, bastaria con que la sala de computo de al
    lado contestara la encuesta para dejarlo sin poder entregar la suya.
    """
    from itcj2.apps.titulatec.pages import public as mod

    make_survey_form()
    student = make_student()
    monkeypatch.setattr(mod, "SURVEY_RL_LIMIT_IP", 1)
    cabeceras = {"X-Real-IP": "203.0.113.53"}

    client.cookies.clear()
    anonimo = client.post(SURVEY_URL, data=OK_PAYLOAD, headers=cabeceras,
                          follow_redirects=False)
    assert 'id="tt-survey-thanks"' in anonimo.text
    # El cubo de la IP queda agotado.
    agotado = client.post(SURVEY_URL, data=OK_PAYLOAD, headers=cabeceras,
                          follow_redirects=False)
    assert 'data-tt-notice="rate_limited"' in agotado.text

    con_sesion = client_as(student).post(SURVEY_URL, data=OK_PAYLOAD,
                                         headers=cabeceras, follow_redirects=False)

    assert 'id="tt-survey-thanks"' in con_sesion.text, (
        "el alumno con sesion se quedo fuera por el cubo de su IP")
    filas = _responses(db_session)
    assert len(filas) == 2
    assert filas[-1].user_id == student.id


def test_dos_IPs_anonimas_no_comparten_cubo(
    client, make_survey_form, db_session, monkeypatch,
):
    """`request.client.host` vale "testclient" para todos.

    Usarlo en vez de `client_ip()` mete a todo internet en un solo cubo:
    inservible como defensa y trivial de agotar para los demas.
    """
    from itcj2.apps.titulatec.pages import public as mod

    make_survey_form()
    client.cookies.clear()
    monkeypatch.setattr(mod, "SURVEY_RL_LIMIT_IP", 1)

    for _ in range(2):
        client.post(SURVEY_URL, data=OK_PAYLOAD,
                    headers={"X-Real-IP": "203.0.113.54"}, follow_redirects=False)

    otra = client.post(SURVEY_URL, data=OK_PAYLOAD,
                       headers={"X-Real-IP": "203.0.113.55"}, follow_redirects=False)

    assert 'id="tt-survey-thanks"' in otra.text, "otra IP arrastrada por el cubo ajeno"
    assert len(_responses(db_session)) == 2


def test_check_only_lee_sin_contar_y_check_and_count_si_cuenta():
    """El contrato del que depende «solo se cobra lo que se escribio».

    Vive aqui, con su consumidor, y no en `test_rate_limit_public.py` (Tarea 2)
    para no reescribir el archivo de otra tarea. Sin esta distincion, mover la
    llamada de sitio no cambiaria nada.
    """
    import uuid

    from itcj2.core.utils import rate_limit

    key = uuid.uuid4().hex

    for _ in range(5):
        assert rate_limit.check_only("survey", key, limit=1, window=60) == (True, 0), \
            "check_only conto un intento"

    assert rate_limit.check_and_count("survey", key, limit=1, window=60)[0] is True
    permitido, retry = rate_limit.check_only("survey", key, limit=1, window=60)
    assert permitido is False, "con el presupuesto gastado, check_only debe negar"
    assert retry > 0


def test_con_redis_caido_el_envio_se_niega_y_no_escribe(
    client, make_survey_form, db_session, monkeypatch,
):
    """E2: `fail_open=False`. En una escritura ANONIMA, Redis es el unico control.

    Se parchea el modulo ORIGEN (`redis_conn.get_redis`), que es donde
    `rate_limit._redis()` resuelve el nombre en cada llamada.
    """
    def _boom():
        raise RuntimeError("redis caido")

    make_survey_form()
    client.cookies.clear()
    monkeypatch.setattr("itcj2.core.utils.redis_conn.get_redis", _boom)

    resp = client.post(SURVEY_URL, data=OK_PAYLOAD,
                       headers={"X-Real-IP": "203.0.113.31"}, follow_redirects=False)

    assert resp.status_code == 200, resp.text[:300]
    assert 'data-tt-notice="rate_limited"' in resp.text
    assert _responses(db_session) == []


# ---------------------------------------------------------------------------
# Validacion fallida: 200 con el formulario re-renderizado
# ---------------------------------------------------------------------------
def test_validacion_fallida_devuelve_200_con_el_formulario_re_renderizado(
    client, make_survey_form, db_session,
):
    """htmx SI swappea en 200: conservar lo capturado es del servidor (spec 6.1)."""
    make_survey_form()
    client.cookies.clear()
    payload = {"website": "", "situacion_laboral": "",
               "comentarios": "Sigo buscando trabajo."}

    resp = client.post(SURVEY_URL, data=payload,
                       headers={"X-Real-IP": "203.0.113.24"}, follow_redirects=False)

    assert resp.status_code == 200, resp.text[:500]
    assert 'id="tt-survey-form"' in resp.text          # formulario, no tarjeta
    assert "Sigo buscando trabajo." in resp.text       # valores conservados
    assert 'aria-invalid="true"' in resp.text          # error por campo
    assert 'data-tt-focus="1"' in resp.text            # foco al primero
    assert "data-tt-errors" in resp.text               # resumen arriba
    assert _responses(db_session) == []                # nada escrito


def test_el_re_render_conserva_radio_escala_y_multiselect(
    client, make_survey_form, db_session,
):
    """Conservar solo el texto libre es la mitad del trabajo.

    Un cuestionario que borra las casillas y los radios al fallar obliga a
    contestarlo entero otra vez, y el abandono se lo lleva completo. Se falla a
    proposito por `comentarios` (excede su `maxLength`) para que TODO lo demas
    sea valido y tenga que volver marcado.
    """
    make_survey_form()
    client.cookies.clear()
    payload = dict(OK_PAYLOAD, comentarios="y" * 2100)   # maxLength = 2000

    resp = client.post(SURVEY_URL, data=payload,
                       headers={"X-Real-IP": "203.0.113.33"}, follow_redirects=False)

    assert resp.status_code == 200, resp.text[:300]
    assert _responses(db_session) == []
    cuerpo = resp.text
    assert re.search(r'value="empleado"[^>]*\schecked', cuerpo), "el radio se perdio"
    assert re.search(r'name="relacion_carrera" value="4"[^>]*\schecked', cuerpo), \
        "la escala se perdio"
    assert re.search(r'value="tecnica"[^>]*\schecked', cuerpo), "el multiselect se perdio"
    assert re.search(r'value="idiomas"[^>]*\schecked', cuerpo), "el multiselect se perdio"
    assert not re.search(r'value="practicas"[^>]*\schecked', cuerpo), \
        "se marco una opcion que nadie marco"


def test_cada_campo_invalido_lleva_su_error_inline_con_su_llave(
    client, make_survey_form, db_session,
):
    """Un cuestionario largo falla en VARIOS campos a la vez.

    Un mensaje de cabecera no puede nombrarlos, y por eso el error va colgado de
    su campo con `data-tt-error="<llave>"` y `aria-invalid` en el control (o en
    su `role="radiogroup"`, cuando el campo es un grupo y no un input suelto).
    """
    make_survey_form()
    client.cookies.clear()
    # Dos errores a la vez: falta el obligatorio y la escala esta fuera de rango
    # (visible, porque `situacion_laboral` si dice "empleado").
    payload = {"website": "", "situacion_laboral": "empleado",
               "relacion_carrera": "9", "areas_fuertes": ["inventada"]}

    resp = client.post(SURVEY_URL, data=payload,
                       headers={"X-Real-IP": "203.0.113.34"}, follow_redirects=False)

    assert resp.status_code == 200, resp.text[:300]
    assert _responses(db_session) == []
    cuerpo = resp.text
    assert 'data-tt-error="relacion_carrera"' in cuerpo
    assert 'data-tt-error="areas_fuertes"' in cuerpo
    assert 'data-tt-error="situacion_laboral"' not in cuerpo, \
        "se marco como invalido un campo que se contesto bien"
    # Y el `aria-invalid` cuelga del grupo del campo que fallo.
    grupo = re.search(r'data-tt-field="areas_fuertes".*?</div>', cuerpo, flags=re.S)
    assert grupo and 'aria-invalid="true"' in grupo.group(0)


def test_el_foco_va_al_primer_campo_invalido_y_a_uno_solo(
    client, make_survey_form, db_session,
):
    """Con dos errores, el foco va al PRIMERO en el orden del cuestionario.

    Dos `data-tt-focus` significan que el navegador se queda con el ultimo, que
    es justo el que esta mas lejos de donde el visitante dejo de mirar.
    """
    make_survey_form()
    client.cookies.clear()
    payload = {"website": "", "situacion_laboral": "", "areas_fuertes": ["inventada"]}

    resp = client.post(SURVEY_URL, data=payload,
                       headers={"X-Real-IP": "203.0.113.35"}, follow_redirects=False)

    cuerpo = resp.text
    assert cuerpo.count('data-tt-focus="1"') == 1, "el foco no es unico"
    antes = cuerpo.split('data-tt-focus="1"')[0]
    assert antes.rfind('data-tt-field="situacion_laboral"') > \
        antes.rfind('data-tt-field="areas_fuertes"'), \
        "el foco no cayo en el primer campo invalido del cuestionario"


SCHEMA_TEXTO_ENORME = {
    "enabled": True,
    "sections": [{"key": "opinion", "title": "Tu opinion"}],
    "fields": [
        {"key": "comentarios", "section": "opinion", "type": "textarea",
         "label": "Que le cambiarias al Tec?", "required": False,
         "validation": {"maxLength": 300000}},
    ],
}


def test_un_error_de_formulario_completo_se_pinta_aunque_no_cuelgue_de_un_campo(
    client, make_survey_form, db_session,
):
    """`submit` devuelve el error de tamano bajo la llave `__form__`.

    No es la llave de ningun campo, asi que un formulario que solo sabe pintar
    errores en linea lo dejaria INVISIBLE: el visitante pulsa Enviar, la pagina
    se re-dibuja igual y no hay nada que leer.

    El cuerpo cabe bajo `MAX_PUBLIC_BODY_BYTES` (256 KB) a proposito —si no,
    saldria por el 413— y el `maxLength` del schema es enorme para que tampoco
    lo pare la validacion de texto: lo unico que sobra es la proyeccion
    serializada contra `MAX_ANSWERS_JSON_BYTES` (128 KB).
    """
    make_survey_form(schema=SCHEMA_TEXTO_ENORME)
    client.cookies.clear()
    payload = {"website": "", "comentarios": "z" * 140_000}

    resp = client.post(SURVEY_URL, data=payload,
                       headers={"X-Real-IP": "203.0.113.36"}, follow_redirects=False)

    assert resp.status_code == 200, resp.text[:300]
    assert _responses(db_session) == []
    assert 'id="tt-survey-form"' in resp.text
    assert "data-tt-errors" in resp.text
    assert "demasiado larga" in resp.text, (
        "el error de formulario completo no se pinta en ningun sitio")


def test_el_post_no_pasa_objetos_orm_a_la_plantilla(
    client, make_survey_form, monkeypatch,
):
    """Mismo motivo que en el GET, en los DOS caminos del POST.

    El de exito pinta la tarjeta y el de error re-pinta el formulario: si el
    segundo mete el `SurveyForm` en el contexto, el arnes no se entera (ver
    `orm_en`).
    """
    from itcj2.apps.titulatec.pages import public as mod

    make_survey_form()
    client.cookies.clear()
    vistos = []
    real = mod.render_titulatec

    def espia(request, template, context=None, *a, **kw):
        vistos.append(context)
        return real(request, template, context, *a, **kw)

    monkeypatch.setattr(mod, "render_titulatec", espia)

    malo = client.post(SURVEY_URL, data={"website": "", "situacion_laboral": ""},
                       headers={"X-Real-IP": "203.0.113.37"}, follow_redirects=False)
    bueno = client.post(SURVEY_URL, data=OK_PAYLOAD,
                        headers={"X-Real-IP": "203.0.113.38"}, follow_redirects=False)

    assert malo.status_code == 200 and bueno.status_code == 200
    assert len(vistos) == 2
    for ctx in vistos:
        sucios = orm_en(ctx)
        assert sucios == [], f"objetos ORM en el contexto: {sucios}"


# ---------------------------------------------------------------------------
# Entrada que el schema NO puede describir
# ---------------------------------------------------------------------------
# El punto ciego de la suite hasta la revision: todo lo de arriba manda campos
# que el `schema` conoce, con el tipo que el `schema` espera. Los tres fallos
# importantes vivian justo fuera de eso —un byte que Postgres prohibe, una parte
# de archivo donde se esperaba texto, un cuerpo sin `Content-Length`—, y ninguno
# necesita mas que un `curl`.
def test_un_NUL_en_una_respuesta_no_revienta_y_queda_limpio(
    client, make_survey_form, db_session,
):
    """`U+0000` es urlencodeable, invisible, y Postgres lo prohibe en `text`.

    Nadie lo escribe a mano: llega pegado desde otro programa. Sin limpiarlo,
    viajaba intacto hasta `db.commit()` y salia como `ValueError: A string
    literal cannot contain NUL (0x00) characters`, que el manejador global
    convierte en **500** con su stack trace. Y un 500 es lo peor que le puede
    pasar a este formulario: htmx tampoco swappea en 5xx, asi que el visitante
    ve un toast generico sobre una pantalla que no se movio y su cuestionario no
    esta en ningun sitio.
    """
    make_survey_form()
    client.cookies.clear()
    payload = dict(OK_PAYLOAD, comentarios="hola\x00mundo")

    resp = client.post(SURVEY_URL, data=payload,
                       headers={"X-Real-IP": "203.0.113.61"}, follow_redirects=False)

    assert resp.status_code == 200, resp.text[:300]
    assert 'id="tt-survey-thanks"' in resp.text
    filas = _responses(db_session)
    assert len(filas) == 1
    assert filas[0].answers["comentarios"] == "holamundo"
    assert "\x00" not in filas[0].answers["comentarios"]


def test_si_la_escritura_revienta_el_visitante_recupera_su_cuestionario(
    client, make_survey_form, db_session, monkeypatch,
):
    """Segunda capa: la que para el caracter que TODAVIA no conocemos.

    Limpiar el NUL cierra el agujero conocido; esto cierra la clase entera. Una
    ruta publica no puede producir un stack trace, y sobre todo no puede
    responder algo que htmx no swappee: el cuestionario tiene que volver con lo
    escrito y con un mensaje que se lea.

    Se fuerza con `monkeypatch` sobre `submit` porque el objetivo es «cualquier
    excepcion», no una en particular; provocar una de verdad exigiria un valor
    que pasara validacion Y reventara en la BD, o sea el agujero siguiente.
    """
    from itcj2.apps.titulatec.services.survey_service import SurveyService

    def _revienta(*a, **kw):
        raise ValueError("A string literal cannot contain NUL (0x00) characters")

    make_survey_form()
    client.cookies.clear()
    monkeypatch.setattr(SurveyService, "submit", staticmethod(_revienta))
    payload = dict(OK_PAYLOAD, comentarios="Tres anos de practicas.")

    resp = client.post(SURVEY_URL, data=payload,
                       headers={"X-Real-IP": "203.0.113.62"}, follow_redirects=False)

    assert resp.status_code == 200, resp.text[:300]
    assert 'id="tt-survey-form"' in resp.text, "no hay formulario que recuperar"
    assert "data-tt-errors" in resp.text
    assert "No pudimos guardar tu respuesta" in resp.text
    assert "Tres anos de practicas." in resp.text, "se perdio lo escrito"
    assert _responses(db_session) == []


def test_una_parte_de_archivo_no_entra_a_la_BD_como_repr(
    client, make_survey_form, db_session,
):
    """Un cuerpo multipart puede mandar CUALQUIER campo como archivo.

    `request.form()` devuelve entonces un `UploadFile`, y `_validate_text` hacia
    `str(value)`: en la columna quedaba
    `UploadFile(filename='evil.txt', size=100, headers=...)`, que ademas es lo
    que veria quien abra el export.
    """
    import json

    make_survey_form()
    client.cookies.clear()

    resp = client.post(
        SURVEY_URL,
        data={"website": "", "situacion_laboral": "empleado",
              "relacion_carrera": "4"},
        files={"comentarios": ("evil.txt", b"x" * 100, "text/plain")},
        headers={"X-Real-IP": "203.0.113.63"}, follow_redirects=False)

    assert resp.status_code == 200, resp.text[:300]
    assert 'id="tt-survey-thanks"' in resp.text
    filas = _responses(db_session)
    assert len(filas) == 1
    crudo = json.dumps(filas[0].answers)
    assert "UploadFile" not in crudo, crudo
    assert "evil.txt" not in crudo, crudo
    # La llave se descarta entera: era opcional y no habia nada que guardar.
    assert "comentarios" not in filas[0].answers


def test_un_archivo_vacio_llamado_website_no_dispara_la_trampa(
    client, make_survey_form, db_session,
):
    """El fallo mas caro de los dos que causaba el `str()` sobre un `UploadFile`.

    Un `UploadFile` es un objeto verdadero, asi que
    `str(data.get("website") or "").strip()` era NO VACIO para una parte de
    archivo vacia llamada `website`: la respuesta de un egresado se tiraba a la
    basura y el se iba con una tarjeta de exito. Silencioso por diseno —esa es
    la gracia de la trampa— y por tanto imposible de detectar desde fuera.
    """
    make_survey_form()
    client.cookies.clear()

    resp = client.post(
        SURVEY_URL,
        data={"situacion_laboral": "empleado", "relacion_carrera": "4"},
        files={"website": ("vacio.txt", b"", "text/plain")},
        headers={"X-Real-IP": "203.0.113.64"}, follow_redirects=False)

    assert resp.status_code == 200, resp.text[:300]
    assert 'id="tt-survey-thanks"' in resp.text
    assert len(_responses(db_session)) == 1, (
        "la trampa se trago un envio legitimo mandado como multipart")


def test_un_cuerpo_sin_content_length_se_rechaza_con_411(
    client, make_survey_form, db_session,
):
    """Sin `Content-Length` el tope no puede aplicarse ANTES de leer el cuerpo.

    Un cuerpo `chunked` no declara tamano, asi que la guarda no tenia nada que
    comparar y lo dejaba pasar entero a `request.form()`, que es exactamente lo
    que el tope existe para evitar. Hoy nginx re-enmarca todo con su propio
    `Content-Length` y el 8001 no esta publicado, pero la defensa no puede
    depender de la topologia.
    """
    make_survey_form()
    client.cookies.clear()

    def cuerpo():
        yield b"website=&situacion_laboral=empleado&relacion_carrera=4"

    resp = client.post(
        SURVEY_URL, content=cuerpo(),
        headers={"X-Real-IP": "203.0.113.65",
                 "Content-Type": "application/x-www-form-urlencoded"},
        follow_redirects=False)

    assert resp.status_code == 411, resp.text[:300]
    assert "X-Tt-Error" in resp.headers
    assert _responses(db_session) == []


def test_el_tamano_declarado_solo_acepta_enteros_no_negativos():
    """`.isdigit()` fallaba del lado peligroso.

    Es `False` tanto para `"1e9"` como para `"-1"`, asi que la guarda
    —`if declarado and declarado.isdigit() and int(...) > TOPE`— se saltaba
    entera y el cuerpo se leia SIN TOPE NINGUNO. Se prueba la funcion suelta
    porque por HTTP no se puede mandar un `Content-Length` invalido: httpx
    calcula el suyo.
    """
    from itcj2.apps.titulatec.pages.public import _declared_body_size

    assert _declared_body_size({}) is None                       # chunked
    assert _declared_body_size({"content-length": "1e9"}) is None
    assert _declared_body_size({"content-length": "-1"}) is None
    assert _declared_body_size({"content-length": ""}) is None
    assert _declared_body_size({"content-length": "0"}) == 0
    assert _declared_body_size({"content-length": " 120 "}) == 120
