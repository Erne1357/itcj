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


def test_limite_por_ip_corta_al_undecimo_envio_y_no_arrastra_a_otra_ip(
    client, make_survey_form, db_session,
):
    """10/hora por IP. El 11 devuelve tarjeta (htmx no swappea 4xx) + Retry-After.

    La ultima peticion, desde OTRA IP, es la que prueba que el cubo es por
    visitante: `request.client.host` vale "testclient" para todos, asi que
    usarlo en vez de `client_ip()` meteria a todo internet en un solo cubo
    —inservible como defensa y trivial de agotar para los demas— y esa peticion
    saldria bloqueada.
    """
    make_survey_form()
    client.cookies.clear()
    cabeceras = {"X-Real-IP": "203.0.113.26"}

    for intento in range(10):
        r = client.post(SURVEY_URL, data=OK_PAYLOAD, headers=cabeceras,
                        follow_redirects=False)
        assert r.status_code == 200, f"envio {intento + 1}: {r.text[:200]}"
        assert 'id="tt-survey-thanks"' in r.text, f"envio {intento + 1} rechazado"

    resp = client.post(SURVEY_URL, data=OK_PAYLOAD, headers=cabeceras,
                       follow_redirects=False)

    assert resp.status_code == 200, resp.text[:300]
    assert 'data-tt-notice="rate_limited"' in resp.text
    assert int(resp.headers["Retry-After"]) > 0
    assert len(_responses(db_session)) == 10

    otra = client.post(SURVEY_URL, data=OK_PAYLOAD,
                       headers={"X-Real-IP": "203.0.113.99"}, follow_redirects=False)
    assert 'id="tt-survey-thanks"' in otra.text, "otra IP arrastrada por el cubo ajeno"
    assert len(_responses(db_session)) == 11


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
