"""Borrador automatico de la encuesta (spec 6.4).

D3 pide borradores automaticos que NO generen carga de escritura: una sola fila
por (formulario, usuario), UPDATE en sitio, sin historial y sin `ProcessEvent`.
El presupuesto de peticiones del cliente se mide en E2E; aqui se prueba el
contrato del servidor.

Nivel HTTP: se llama a la ruta con `client`/`client_as`. El nivel SERVICIO
—`open_form`, `get_draft` y `save_draft` contra `db_session`— vive en
`test_survey_drafts.py`, que crea la Tarea 10 y que esta tarea NO toca. Los dos
archivos llevan nombres distintos a proposito: con el mismo nombre, este bloque
borraria aquellas pruebas y `test_cuerpo_por_encima_del_tope_se_rechaza_con_413`
colisionaria por nombre con la de alla, que pytest resuelve en silencio
quedandose con la ultima definicion.
"""
from __future__ import annotations

DRAFT_URL = "/titulatec/encuesta-egresados/borrador"
SURVEY_URL = "/titulatec/encuesta-egresados"


def _drafts(db_session):
    from itcj2.apps.titulatec.models import SurveyDraft
    return db_session.query(SurveyDraft).all()


def test_la_pagina_carga_el_modulo_de_autosave(client_as, make_student, make_survey_form):
    """Paso 6: el script se carga UNA vez desde `public_scripts`, no del parcial.

    Si el bloque se perdiera -o el `<script>` quedara dentro del parcial que
    htmx reemplaza en cada envio fallido- el autoguardado dejaria de arrancar,
    o se duplicaria, sin que ninguna otra prueba de este archivo lo note: las
    demas hablan HTTP directo con la ruta del borrador y nunca miran el GET.

    Tarea 2: sesion real -este test solo mira el `<script>` del GET, que se
    emite igual con o sin sesion; no es el camino anonimo lo que se prueba
    aqui, y la fabrica ya es no-anonima por omision-.
    """
    make_survey_form()

    cuerpo = client_as(make_student()).get(SURVEY_URL, follow_redirects=False).text

    assert '<script src="/static/titulatec/js/public/survey.js?v=' in cuerpo


def test_sin_sesion_devuelve_204_y_no_escribe(client, make_survey_form, db_session):
    """Ninguna escritura a BD ocurre antes de que exista la sesion (spec 6.5.5)."""
    make_survey_form()
    client.cookies.clear()

    resp = client.post(DRAFT_URL, data={"situacion_laboral": "buscando"},
                       headers={"X-Real-IP": "203.0.113.31"}, follow_redirects=False)

    assert resp.status_code == 204, resp.text[:300]
    assert _drafts(db_session) == []


def test_con_sesion_crea_una_sola_fila_y_la_actualiza_en_sitio(
    client_as, make_student, make_survey_form, db_session,
):
    """UPSERT de UNA fila: dos autosaves no dejan dos borradores."""
    form = make_survey_form()
    student = make_student()
    c = client_as(student)

    assert c.post(DRAFT_URL, data={"situacion_laboral": "empleado"},
                  follow_redirects=False).status_code == 204
    assert c.post(DRAFT_URL, data={"situacion_laboral": "estudiando"},
                  follow_redirects=False).status_code == 204

    filas = _drafts(db_session)
    assert len(filas) == 1
    assert filas[0].form_id == form.id
    assert filas[0].user_id == student.id
    assert filas[0].answers["situacion_laboral"] == "estudiando"


def test_el_borrador_no_guarda_el_campo_trampa(
    client_as, make_student, make_survey_form, db_session,
):
    """`website` no es del schema: la llave desconocida se descarta."""
    make_survey_form()

    client_as(make_student()).post(
        DRAFT_URL, data={"situacion_laboral": "empleado", "website": "http://spam.example"},
        follow_redirects=False)

    assert "website" not in _drafts(db_session)[0].answers


def test_el_borrador_se_borra_al_enviar_la_encuesta(
    client_as, make_student, make_survey_form, db_session,
):
    """Enviar limpia la fila: el borrador no sobrevive a su propia respuesta."""
    make_survey_form()
    c = client_as(make_student())
    c.post(DRAFT_URL, data={"situacion_laboral": "empleado"}, follow_redirects=False)
    assert len(_drafts(db_session)) == 1

    resp = c.post(SURVEY_URL, headers={"X-Real-IP": "203.0.113.32"}, follow_redirects=False,
                  data={"website": "", "situacion_laboral": "empleado",
                        "relacion_carrera": "5"})

    assert resp.status_code == 200, resp.text[:400]
    assert _drafts(db_session) == []


def test_cuerpo_por_encima_del_tope_se_rechaza_con_413(
    client_as, make_student, make_survey_form, db_session,
):
    """El tope va antes de `request.form()`, igual que en el POST de envio."""
    from itcj2.apps.titulatec.services.survey_service import MAX_PUBLIC_BODY_BYTES

    make_survey_form()

    resp = client_as(make_student()).post(
        DRAFT_URL, data={"comentarios": "x" * (MAX_PUBLIC_BODY_BYTES + 1024)},
        follow_redirects=False)

    assert resp.status_code == 413, resp.text[:200]
    assert _drafts(db_session) == []


def test_cuerpo_por_encima_del_tope_sin_sesion_tambien_se_rechaza_con_413(
    client, make_survey_form, db_session,
):
    """La frontera de tamano aplica ANTES de mirar la sesion, igual que en el envio.

    Los otros tests del tope usan `client_as`: con sesion, el guard de tamano y
    el `if not user` caen en el mismo orden sin importar cual va primero, y no
    distinguen una cosa de la otra. Este test es el unico que fija el ORDEN: un
    anonimo con un cuerpo enorme tiene que recibir 413, no 204 -si el `if not
    user` se adelantara al tope, un cuerpo de 256+ KB de un visitante sin sesion
    pasaria de largo el guard de tamano sin que ningun otro test lo note-.
    """
    from itcj2.apps.titulatec.services.survey_service import MAX_PUBLIC_BODY_BYTES

    make_survey_form()
    client.cookies.clear()

    resp = client.post(DRAFT_URL, data={"comentarios": "x" * (MAX_PUBLIC_BODY_BYTES + 1024)},
                       follow_redirects=False)

    assert resp.status_code == 413, resp.text[:200]
    assert _drafts(db_session) == []


def test_dos_alumnos_con_borrador_en_el_mismo_formulario_no_se_mezclan(
    client_as, make_student, make_survey_form, db_session,
):
    """`save_draft` hace UPSERT por `(form_id, user_id)`, no solo por `form_id`.

    Los otros tests de upsert usan un solo alumno, asi que no distinguen un
    filtro correcto de uno que solo mire `form_id`: con un solo actor, las dos
    formas de filtrar encuentran la MISMA fila. Aqui hay DOS alumnos sobre el
    MISMO formulario: si el filtro fuera solo por `form_id`, el segundo POST
    encontraria la fila del primero y la sobreescribiria en vez de crear la
    suya -exactamente el "borrado que arrasa el borrador en curso de otro
    alumno" que este endpoint existe para evitar-.
    """
    make_survey_form()
    a = make_student()
    b = make_student()

    client_as(a).post(DRAFT_URL, data={"situacion_laboral": "empleado"},
                      follow_redirects=False)
    client_as(b).post(DRAFT_URL, data={"situacion_laboral": "buscando"},
                      follow_redirects=False)

    por_alumno = {fila.user_id: fila.answers.get("situacion_laboral")
                 for fila in _drafts(db_session)}
    assert por_alumno == {a.id: "empleado", b.id: "buscando"}, (
        "los borradores de dos alumnos distintos se mezclaron o se pisaron")


def test_si_save_draft_revienta_la_ruta_responde_204_y_no_escribe(
    client_as, make_student, make_survey_form, db_session, monkeypatch,
):
    """El fallo de escritura no es de la incumbencia de quien autoguarda.

    Un deadlock, una conexion caida o una violacion de constraint en
    `SurveyService.save_draft` no tienen nada que ver con las guardas de
    tamano de la ruta -esas ya pasaron- y hoy revientan sin capturar: rompe el
    contrato de la interfaz ("204 siempre, con y sin sesion") con un 500
    pelado, justo lo que el docstring del modulo promete que no puede pasar
    ("Ninguna entrada del visitante puede producir un 500"). Mismo patron que
    `test_si_la_escritura_revienta_el_visitante_recupera_su_cuestionario` de
    `test_survey_submit_routes.py`, adaptado: aqui no hay formulario que
    re-renderizar, asi que la respuesta correcta es 204 y cero filas, no un
    parcial de error.
    """
    from itcj2.apps.titulatec.services.survey_service import SurveyService

    def _revienta(*a, **kw):
        raise RuntimeError("conexion caida a mitad del commit")

    make_survey_form()
    monkeypatch.setattr(SurveyService, "save_draft", staticmethod(_revienta))

    resp = client_as(make_student()).post(
        DRAFT_URL, data={"situacion_laboral": "empleado"}, follow_redirects=False)

    assert resp.status_code == 204, resp.text[:300]
    assert _drafts(db_session) == []


def test_answers_por_encima_del_tope_serializado_se_rechaza_sin_truncar(
    client_as, make_student, make_survey_form, db_session,
):
    """`Content-Length` puede faltar bajo `chunked`: la proyeccion tambien se acota.

    Este cuerpo cabe holgado bajo `MAX_PUBLIC_BODY_BYTES` (256 KB) y sin embargo
    su `answers` serializado pasa de `MAX_ANSWERS_JSON_BYTES` (128 KB): es
    exactamente el hueco que la segunda cota tapa. Se RECHAZA, nunca se trunca.
    """
    from itcj2.apps.titulatec.services.survey_service import MAX_ANSWERS_JSON_BYTES

    make_survey_form()

    resp = client_as(make_student()).post(
        DRAFT_URL, data={"comentarios": "y" * (MAX_ANSWERS_JSON_BYTES + 2048)},
        follow_redirects=False)

    assert resp.status_code == 413, resp.text[:200]
    assert _drafts(db_session) == []
