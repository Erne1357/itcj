"""Encuesta por perfil, con respaldo en la de licenciatura (Tarea 6).

Spec `2026-09-30-titulatec-posgrado-design.md` seccion 4.5, decision D3, invariante
5: el formulario de encuesta se resuelve POR REQUEST con
`SurveyService.form_for_user`, nunca por la constante `SURVEY_CODE` sola.
Mientras no exista una version `open` de `egresados_posgrado` (su contenido
aun no existe), posgrado contesta la de licenciatura -exactamente lo que ya
prueban `test_public_survey_routes.py`/`test_survey_drafts.py`/
`test_survey_steps.py` para licenciatura, que esta tarea NO debe romper-.

Dos niveles, como el resto de la suite de encuesta:

  * SERVICIO: `SurveyService.form_for_user` contra `db_session` directo.
  * HTTP: las 4 rutas publicas, con `client`/`client_as`, y el default de la
    bandeja de Encuestas (`surveys_admin._resolve_form`).

Ninguna prueba depende del formulario `egresados` sembrado en dev
(`11_seed_survey_form.sql`): `make_survey_form` cierra las versiones abiertas
del mismo `code` antes de insertar (indice parcial `uq_titulatec_survey_forms_
open`), asi que esta suite corre igual en la BD de dev y en una base vacia
tipo CI.
"""
from __future__ import annotations

SURVEY_URL = "/titulatec/encuesta-egresados"
DRAFT_URL = f"{SURVEY_URL}/borrador"
ADMIN_URL = "/titulatec/admin/encuestas"

# `situacion_laboral="buscando"` deja `relacion_carrera` (el otro obligatorio
# de "empleo") INVISIBLE -su `visible_when` pide "empleado"-, asi que el envio
# es valido sin contestarla. Copiado del mismo patron que ya usan
# `test_public_survey_routes.py::OK_PAYLOAD_TAREA_F` y
# `test_survey_submit_routes.py::OK_PAYLOAD` a proposito: los archivos de
# encuesta son independientes entre si.
OK_PAYLOAD = {
    "website": "",
    "situacion_laboral": "buscando",
    "areas_fuertes": ["tecnica"],
    "comentarios": "Ninguno.",
}


# ---------------------------------------------------------------------------
# Nivel SERVICIO: SurveyService.form_for_user
# ---------------------------------------------------------------------------
def test_form_for_user_licenciatura_resuelve_egresados(
    db_session, make_program, make_student, make_process, make_survey_form,
):
    from itcj2.apps.titulatec.services.survey_service import SurveyService

    egresados = make_survey_form(code="egresados")
    prog = make_program("Ingenieria en Sistemas de Prueba Track", level="licenciatura")
    student = make_student()
    make_process(student, program=prog)

    form = SurveyService.form_for_user(db_session, student.id)

    assert form is not None
    assert form.id == egresados.id


def test_form_for_user_posgrado_sin_formulario_propio_cae_a_egresados(
    db_session, make_program, make_student, make_process, make_survey_form,
):
    """D3: mientras `egresados_posgrado` no exista (o no este abierto),
    posgrado contesta la de licenciatura."""
    from itcj2.apps.titulatec.services.survey_service import SurveyService

    egresados = make_survey_form(code="egresados")
    prog = make_program("Maestria en Prueba Track", level="maestria")
    student = make_student()
    make_process(student, program=prog)

    form = SurveyService.form_for_user(db_session, student.id)

    assert form is not None
    assert form.id == egresados.id


def test_form_for_user_posgrado_con_formulario_propio_abierto_gana(
    db_session, make_program, make_student, make_process, make_survey_form,
):
    """En cuanto se publique `egresados_posgrado` (status='open'), el cambio
    es automatico: gana sobre `egresados` para el perfil de posgrado."""
    from itcj2.apps.titulatec.services.survey_service import SurveyService

    make_survey_form(code="egresados")
    posgrado_form = make_survey_form(code="egresados_posgrado")
    prog = make_program("Doctorado en Prueba Track", level="doctorado")
    student = make_student()
    make_process(student, program=prog)

    form = SurveyService.form_for_user(db_session, student.id)

    assert form is not None
    assert form.id == posgrado_form.id


def test_form_for_user_ignora_egresados_posgrado_en_draft(
    db_session, make_program, make_student, make_process, make_survey_form,
):
    from itcj2.apps.titulatec.services.survey_service import SurveyService

    egresados = make_survey_form(code="egresados")
    make_survey_form(code="egresados_posgrado", status="draft")
    prog = make_program("Maestria Draft de Prueba Track", level="maestria")
    student = make_student()
    make_process(student, program=prog)

    form = SurveyService.form_for_user(db_session, student.id)

    assert form is not None
    assert form.id == egresados.id


def test_form_for_user_ignora_egresados_posgrado_cerrado(
    db_session, make_program, make_student, make_process, make_survey_form,
):
    from itcj2.apps.titulatec.services.survey_service import SurveyService

    egresados = make_survey_form(code="egresados")
    make_survey_form(code="egresados_posgrado", status="closed")
    prog = make_program("Maestria Cerrada de Prueba Track", level="maestria")
    student = make_student()
    make_process(student, program=prog)

    form = SurveyService.form_for_user(db_session, student.id)

    assert form is not None
    assert form.id == egresados.id


def test_form_for_user_sin_usuario_resuelve_licenciatura(db_session, make_survey_form):
    """Visitante anonimo (`user_id=None`): cadena de licenciatura, igual que
    antes de esta tarea."""
    from itcj2.apps.titulatec.services.survey_service import SurveyService

    egresados = make_survey_form(code="egresados")

    form = SurveyService.form_for_user(db_session, None)

    assert form is not None
    assert form.id == egresados.id


def test_form_for_user_sin_proceso_acreditable_resuelve_licenciatura(
    db_session, make_student, make_survey_form,
):
    from itcj2.apps.titulatec.services.survey_service import SurveyService

    egresados = make_survey_form(code="egresados")
    student = make_student()   # sin TitulationProcess

    form = SurveyService.form_for_user(db_session, student.id)

    assert form is not None
    assert form.id == egresados.id


def test_form_for_user_fallo_resolviendo_el_proceso_degrada_a_licenciatura(
    db_session, make_program, make_student, make_process, make_survey_form, monkeypatch,
):
    """Ronda de revision R10: un `ProcessService.creditable_process` que
    revienta -mismo riesgo que ya cubre `_solicitud_existente` en
    `pages/public.py` para el mismo gate- no debe propagar. Un posgrado con
    `egresados_posgrado` abierto (que en el camino normal GANARIA) cae a
    `egresados` en vez de tirar un 500: la ley del modulo ("Ninguna entrada
    del visitante puede producir un 500") tambien aplica dentro del service.
    """
    from itcj2.apps.titulatec.services.process_service import ProcessService
    from itcj2.apps.titulatec.services.survey_service import SurveyService

    egresados = make_survey_form(code="egresados")
    make_survey_form(code="egresados_posgrado")
    prog = make_program("Maestria Fallo Transitorio de Prueba Track", level="maestria")
    student = make_student()
    make_process(student, program=prog)

    def _revienta(db, user_id):
        raise RuntimeError("BD/Redis caidos (simulado)")

    monkeypatch.setattr(ProcessService, "creditable_process", staticmethod(_revienta))

    form = SurveyService.form_for_user(db_session, student.id)

    assert form is not None
    assert form.id == egresados.id


# ---------------------------------------------------------------------------
# Nivel HTTP: las 4 rutas publicas
# ---------------------------------------------------------------------------
def test_get_encuesta_como_posgrado_con_formulario_propio_muestra_su_titulo(
    client_as, make_program, make_student, make_process, make_survey_form,
):
    make_survey_form(code="egresados")
    posgrado_form = make_survey_form(code="egresados_posgrado")
    prog = make_program("Maestria GET de Prueba Track", level="maestria")
    student = make_student()
    make_process(student, program=prog)

    resp = client_as(student).get(SURVEY_URL, follow_redirects=False)

    assert resp.status_code == 200, resp.text[:500]
    assert posgrado_form.title in resp.text
    # El de licenciatura NO debe aparecer: confirma que gano el de posgrado y
    # no un remanente del "mas reciente" de antes de esta tarea.
    assert "Encuesta de prueba egresados v1" not in resp.text


def test_post_encuesta_como_posgrado_guarda_en_su_formulario_y_abre_revision(
    client_as, db_session, make_program, make_student, make_process, make_survey_form,
):
    """El envio de un posgrado con `egresados_posgrado` abierto escribe la
    `SurveyResponse` contra ESE formulario y abre la `SurveyReview` de
    siempre para su proceso (Tarea 3, D6): la liberacion de GTV no cambia."""
    from itcj2.apps.titulatec.models import SurveyResponse, SurveyReview

    make_survey_form(code="egresados")
    posgrado_form = make_survey_form(code="egresados_posgrado")
    prog = make_program("Maestria POST de Prueba Track", level="maestria")
    student = make_student()
    process = make_process(student, program=prog)

    resp = client_as(student).post(
        SURVEY_URL, data=OK_PAYLOAD,
        headers={"X-Real-IP": "203.0.113.210"}, follow_redirects=False)

    assert resp.status_code == 200, resp.text[:500]
    assert 'data-tt-credit="in_review"' in resp.text

    response = (db_session.query(SurveyResponse)
                .filter_by(process_id=process.id).one())
    assert response.form_id == posgrado_form.id

    review = db_session.query(SurveyReview).filter_by(process_id=process.id).one()
    assert review.response_id == response.id
    assert review.status == "in_review"


def test_post_borrador_como_posgrado_usa_su_formulario(
    client_as, db_session, make_program, make_student, make_process, make_survey_form,
):
    from itcj2.apps.titulatec.models import SurveyDraft

    make_survey_form(code="egresados")
    posgrado_form = make_survey_form(code="egresados_posgrado")
    prog = make_program("Doctorado Borrador de Prueba Track", level="doctorado")
    student = make_student()
    make_process(student, program=prog)

    resp = client_as(student).post(
        DRAFT_URL, data={"situacion_laboral": "empleado"}, follow_redirects=False)

    assert resp.status_code == 204, resp.text[:300]
    assert resp.headers.get("X-Tt-Draft-Saved") == "1"

    draft = db_session.query(SurveyDraft).filter_by(user_id=student.id).one()
    assert draft.form_id == posgrado_form.id


def test_get_encuesta_posgrado_con_revision_abierta_muestra_tarjeta_congelada(
    client_as, make_program, make_student, make_process, make_survey_form, make_survey_review,
):
    """Revision Focus 4: con una `SurveyReview` ya abierta, la tarjeta
    congelada no cambia -ni siquiera cuando el perfil es posgrado y tiene su
    propio formulario abierto, que en otra rama SI ganaria."""
    make_survey_form(code="egresados_posgrado")
    prog = make_program("Maestria Congelada de Prueba Track", level="maestria")
    student = make_student()
    process = make_process(student, program=prog)
    make_survey_review(process)

    resp = client_as(student).get(SURVEY_URL, follow_redirects=False)

    assert resp.status_code == 200, resp.text[:500]
    assert 'data-tt-review-status="in_review"' in resp.text
    assert 'id="tt-survey-form"' not in resp.text


# ---------------------------------------------------------------------------
# Bandeja de Encuestas (Servicios Escolares/GTV): default sin `form_id`
# ---------------------------------------------------------------------------
def test_admin_encuestas_sin_form_id_muestra_egresados_aunque_haya_uno_de_posgrado_mas_nuevo(
    client_as, make_head, make_survey_form,
):
    egresados = make_survey_form(code="egresados")
    posgrado = make_survey_form(code="egresados_posgrado")

    resp = client_as(make_head(perm_codes=("titulatec.survey.page.list",))).get(ADMIN_URL)

    assert resp.status_code == 200, resp.text[:500]
    assert f'value="{egresados.id}" selected' in resp.text
    assert f'value="{posgrado.id}" selected' not in resp.text
