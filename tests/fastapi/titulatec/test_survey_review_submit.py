"""Envio de la encuesta -> solicitud de liberacion; encuesta congelada (Tarea 3).

Sustituye a `test_survey_credit.py` (nivel servicio) y
`test_survey_credit_route.py` (nivel HTTP), borrados en esta tarea: el envio
de la encuesta YA NO acredita el requisito `graduate_survey` por si solo (eso lo hacia
`SurveyService._credit`, retirado). Ahora un envio con proceso acreditable
abre una solicitud `titulatec_survey_reviews` en `in_review` para que Gestion
Tecnologica y Vinculacion decida despues, desde su bandeja de Liberaciones, si
libera el requisito o deja observaciones (`SurveyReviewService`, Tarea 2). La
encuesta queda CONGELADA: quien ya tiene solicitud no puede volver a enviarla,
y `GET /encuesta-egresados`, `POST /encuesta-egresados/paso` y
`POST /encuesta-egresados/borrador` cortan ANTES del presupuesto y de la
validacion para pintar la tarjeta de estatus (o el "no escribe" del borrador)
en su lugar (spec `2026-09-15-titulatec-liberacion-gtv-design.md` 5.3, D6).

`credit_status` (dominio nuevo): `in_review | already_submitted | no_process |
anonymous`. Desaparecen `credited`, `already` y `no_requirement`.
"""
from __future__ import annotations

from itcj2.apps.titulatec.services.survey_service import SurveyService

SURVEY_URL = "/titulatec/encuesta-egresados"
SURVEY_STEP_URL = f"{SURVEY_URL}/paso"
SURVEY_DRAFT_URL = f"{SURVEY_URL}/borrador"
CITA_URL = "/titulatec/student/cita"

# Payload valido de `SURVEY_SCHEMA_V1` (conftest.py): `situacion_laboral`
# obligatorio y `relacion_carrera` (escala 1-5) visible solo si es "empleado".
ENVIO_OK = {"situacion_laboral": "empleado", "relacion_carrera": "5"}
OK_PAYLOAD = {"website": "", "situacion_laboral": "empleado", "relacion_carrera": "4"}


def _responses(db_session, **filtros):
    from itcj2.apps.titulatec.models import SurveyResponse
    return db_session.query(SurveyResponse).filter_by(**filtros).all()


def _reviews(db_session, **filtros):
    from itcj2.apps.titulatec.models import SurveyReview
    return db_session.query(SurveyReview).filter_by(**filtros).all()


def _drafts(db_session, **filtros):
    from itcj2.apps.titulatec.models import SurveyDraft
    return db_session.query(SurveyDraft).filter_by(**filtros).all()


def _make_requisito(db_session, cohort, auto_source="graduate_survey"):
    """El `CotejoRequirement` que la encuesta acreditaba ANTES de esta tarea.

    Vive aqui a proposito -no en `conftest.py`, que solo lo toca la Tarea 2-,
    igual que en el `test_survey_credit.py` borrado: sirve para probar que,
    aunque la convocatoria SI tenga el requisito bien configurado, el envio ya
    no lo `fulfill`-ea. Eso solo lo hace `SurveyReviewService.approve` cuando
    GTV libera (Tarea 2, fuera de esta tarea).
    """
    from itcj2.apps.titulatec.models import CotejoRequirement

    row = CotejoRequirement(
        cohort_id=cohort.id, icon="clipboard-check",
        label="Encuesta de egresados", hint="Comprobante de haberla contestado.",
        order_index=0, is_required=True, is_active=True,
        code="graduate_survey", auto_source=auto_source,
    )
    db_session.add(row)
    db_session.flush()
    return row


# ---------------------------------------------------------------------------
# `SurveyService.submit`: abre solicitud, NO acredita
# ---------------------------------------------------------------------------
def test_envio_con_proceso_abre_solicitud_in_review_sin_acreditar(
    db_session, make_survey_form, make_student, make_cohort, make_process,
):
    """1 respuesta + 1 solicitud `in_review` + 0 cumplimientos.

    `current_phase=1` a proposito -el caso MAYORITARIO, la encuesta se
    promueve en publico antes de que el egresado llegue a la fase 2- migrado
    de `test_acredita_en_fase_1_sin_haber_abierto_nunca_la_pagina_de_la_cita`:
    la encuesta no esta sujeta a la guarda de fase (spec 6.1), asi que abrir
    la solicitud tampoco deberia estarlo.
    """
    from itcj2.apps.titulatec.models import RequirementFulfillment

    form = make_survey_form(code="tt_test_in_review")
    student = make_student()
    cohort = make_cohort()
    proc = make_process(student, cohort=cohort, current_phase=1)
    req = _make_requisito(db_session, cohort)

    response, errors, credit = SurveyService.submit(
        db_session, form, ENVIO_OK, user_id=student.id,
        client_ip=None, user_agent=None)

    assert errors == {}
    assert credit == "in_review"
    assert response is not None
    assert response.process_id == proc.id
    assert response.cohort_id == cohort.id
    assert len(_responses(db_session, process_id=proc.id)) == 1

    solicitudes = _reviews(db_session, process_id=proc.id)
    assert len(solicitudes) == 1
    assert solicitudes[0].status == "in_review"
    assert solicitudes[0].response_id == response.id

    assert (db_session.query(RequirementFulfillment)
            .filter_by(process_id=proc.id, requirement_id=req.id).count() == 0)


def test_segundo_envio_no_escribe_y_dice_already_submitted(
    db_session, make_survey_form, make_student, make_cohort, make_process,
):
    """La encuesta CONGELADA (D6): el segundo envio no crea una segunda fila."""
    form = make_survey_form(code="tt_test_segundo")
    student = make_student()
    cohort = make_cohort()
    make_process(student, cohort=cohort)

    _r1, _e1, primero = SurveyService.submit(
        db_session, form, ENVIO_OK, user_id=student.id,
        client_ip=None, user_agent=None)
    r2, e2, segundo = SurveyService.submit(
        db_session, form, ENVIO_OK, user_id=student.id,
        client_ip=None, user_agent=None)

    assert primero == "in_review"
    assert segundo == "already_submitted"
    assert r2 is None
    assert e2 == {}
    assert len(_responses(db_session, user_id=student.id)) == 1


def test_sin_proceso_no_abre_solicitud_y_dice_no_process(
    db_session, make_survey_form, make_student,
):
    """Sin proceso acreditable: la respuesta se guarda (vale para estadistica)
    pero no nace ninguna solicitud."""
    form = make_survey_form(code="tt_test_sin_proceso")
    student = make_student()
    # `_reviews` barre la TABLA ENTERA, y la base de dev tiene liberaciones de
    # verdad: exigir `== []` daba por hecho que estaba vacía y se puso rojo el
    # día que un alumno real envió su encuesta (2026-09-18). Lo que este test
    # quiere decir es «no nació NINGUNA solicitud nueva», que es un delta.
    antes = {r.id for r in _reviews(db_session)}

    response, errors, credit = SurveyService.submit(
        db_session, form, ENVIO_OK, user_id=student.id,
        client_ip=None, user_agent=None)

    assert errors == {}
    assert credit == "no_process"
    assert response is not None
    assert response.process_id is None
    assert {r.id for r in _reviews(db_session)} == antes, (
        "sin proceso acreditable no puede nacer una solicitud de liberación"
    )


def test_commitea_UNA_sola_vez_y_la_solicitud_va_DENTRO(
    db_session, make_survey_form, make_student, make_cohort, make_process, monkeypatch,
):
    """Seccion 4.4 paso 7, adaptado de `test_survey_credit.py`: respuesta +
    filas + solicitud son UNA sola transaccion. Se espia `commit` porque
    `db_session` corre en savepoint (un commit de mas es invisible para
    cualquier asercion sobre filas): con un solo commit al final, la
    solicitud YA existe en ese momento.
    """
    from itcj2.apps.titulatec.models import SurveyReview

    form = make_survey_form(code="tt_test_1commit")
    student = make_student()
    cohort = make_cohort()
    proc = make_process(student, cohort=cohort)

    commits: list[bool] = []
    real_commit = db_session.commit

    def espia_commit():
        commits.append(
            db_session.query(SurveyReview).filter_by(process_id=proc.id).first() is not None)
        return real_commit()

    monkeypatch.setattr(db_session, "commit", espia_commit)

    _r, _e, credit = SurveyService.submit(
        db_session, form, ENVIO_OK, user_id=student.id,
        client_ip=None, user_agent=None)

    assert credit == "in_review"
    assert commits == [True], commits


def test_race_de_dos_envios_simultaneos_cae_a_already_submitted_por_integrity_error(
    db_session, make_survey_form, make_student, make_cohort, make_process,
    make_survey_review, monkeypatch,
):
    """Defensa en profundidad (spec 5.3), mitad 1 de 2: si dos envios pasaran
    los dos la comprobacion inicial -carrera real, aqui FORZADA parcheando
    `get_for_process` para que NUNCA la encuentre, en las DOS llamadas- el
    `UNIQUE(process_id)` frena al perdedor en el `flush()` de `open_for_
    submission` (la fila "ganadora" SI existe en BD, asi que Postgres
    rechaza el `INSERT` duplicado), y `submit` lo resuelve con `rollback` +
    `already_submitted`, nunca con un 500.

    El setup se COMMITEA antes de forzar la carrera: el `rollback()` de
    `submit` desanda hasta el ultimo commit (arnes de tests, `db_session`
    bajo savepoints) y no debe llevarse la solicitud "ganadora".

    Hermana de `test_race_de_dos_envios_simultaneos_cae_a_already_submitted_
    por_value_error`, mas abajo: esa fuerza la OTRA mitad de la misma carrera
    (ronda 1 de revision, hallazgo Important #2).
    """
    from itcj2.apps.titulatec.models import SurveyResponse, SurveyReview
    from itcj2.apps.titulatec.services.survey_review_service import SurveyReviewService

    form = make_survey_form(code="tt_test_race")
    student = make_student()
    cohort = make_cohort()
    proc = make_process(student, cohort=cohort)
    ganador = make_survey_review(proc)
    db_session.commit()

    monkeypatch.setattr(SurveyReviewService, "get_for_process",
                        staticmethod(lambda db, process_id: None))

    response, errors, credit = SurveyService.submit(
        db_session, form, ENVIO_OK, user_id=student.id,
        client_ip=None, user_agent=None)

    assert response is None
    assert errors == {}
    assert credit == "already_submitted"
    assert [r.id for r in _reviews(db_session, process_id=proc.id)] == [ganador.id]
    assert len(_responses(db_session, process_id=proc.id)) == 1


def test_race_de_dos_envios_simultaneos_cae_a_already_submitted_por_value_error(
    db_session, make_survey_form, make_student, make_cohort, make_process,
    monkeypatch,
):
    """Defensa en profundidad (spec 5.3), mitad 2 de 2 (hallazgo Important #2
    de la ronda 1 de revision): si el envio "ganador" commitea justo ENTRE la
    comprobacion propia de `submit` (linea ~238, ve `None`: todavia no hay
    solicitud) y la comprobacion INTERNA de `open_for_submission` (que
    entonces SI la encuentra), esa segunda comprobacion levanta `ValueError`
    -nunca llega a intentar el `INSERT`, asi que Postgres no interviene y no
    hay `IntegrityError`-. Antes de esta correccion, `submit` solo atrapaba
    `IntegrityError`: este `ValueError` se colaba hasta el `except Exception`
    generico de la ruta, que lo convertia en la tarjeta de error generica
    ("No pudimos guardar tu respuesta...") en vez de la de "ya la enviaste".

    Se fuerza la carrera con un `get_for_process` que responde `None` la
    PRIMERA vez que se le llama (el chequeo de `submit`) y algo verdadero la
    SEGUNDA (el de `open_for_submission`) -sin necesidad de una fila real en
    BD: lo que se prueba es que `submit` atrape el `ValueError` que la propia
    defensa de `open_for_submission` levanta, no el mecanismo de Postgres-.

    Sin fila "ganadora" real esta vez, no hace falta el `db_session.commit()`
    de la hermana `_por_integrity_error`: nada se escribe fuera de esta
    llamada a `submit`, y su propio `rollback` deshace unicamente lo que el
    intento fallido alcanzo a escribir (la `SurveyResponse`/`SurveyAnswer` de
    este mismo envio).
    """
    from itcj2.apps.titulatec.services.survey_review_service import SurveyReviewService

    form = make_survey_form(code="tt_test_race_ve")
    student = make_student()
    cohort = make_cohort()
    proc = make_process(student, cohort=cohort)

    llamadas = {"n": 0}

    def _get_for_process_carrera(db, process_id):
        llamadas["n"] += 1
        return None if llamadas["n"] == 1 else object()

    monkeypatch.setattr(SurveyReviewService, "get_for_process",
                        staticmethod(_get_for_process_carrera))

    response, errors, credit = SurveyService.submit(
        db_session, form, ENVIO_OK, user_id=student.id,
        client_ip=None, user_agent=None)

    assert response is None
    assert errors == {}
    assert credit == "already_submitted"
    assert llamadas["n"] == 2
    assert _reviews(db_session, process_id=proc.id) == []
    assert len(_responses(db_session, process_id=proc.id)) == 0


def test_el_desempate_por_id_hace_total_el_orden_de_creditable_process(
    make_student, make_process, make_cohort, db_session,
):
    """`ORDER BY (created_at, id)`: el `id` es lo que lo vuelve determinista.

    Migrado tal cual de `test_survey_credit_route.py`: no llama a `submit` -es
    puramente `ProcessService.creditable_process`-, pero sostiene el mismo
    invariante que usa la solicitud para saber a que proceso aterrizar.
    `NOW()` en Postgres es la marca de la TRANSACCION, asi que dos procesos
    creados en el mismo test comparten `created_at` al milisegundo. Sin el
    desempate por `id`, cual gana depende del plan de Postgres y la solicitud
    podria aterrizar en un proceso distinto en cada corrida.
    """
    from itcj2.apps.titulatec.services.process_service import ProcessService

    student = make_student()
    viejo = make_process(student, cohort=make_cohort(), current_phase=2)
    nuevo = make_process(student, cohort=make_cohort(), current_phase=2)
    assert viejo.created_at == nuevo.created_at
    assert nuevo.id > viejo.id

    elegido = ProcessService.creditable_process(db_session, student.id)

    assert elegido.id == nuevo.id
    assert ProcessService.creditable_process(db_session, student.id).id == nuevo.id


def test_con_dos_procesos_vivos_la_solicitud_aterriza_en_el_que_ve_el_alumno(
    client_as, make_student, make_process, make_cohort, make_survey_form,
    seed_phase_defs, db_session,
):
    """Invariante de 5.3, migrado de `test_survey_credit_route.py`: el
    checklist y la solicitud leen el MISMO helper (`ProcessService.
    creditable_process`). Dos convocatorias, dos procesos vivos, fechas de
    alta distintas para que el resultado no dependa del desempate. La
    solicitud tiene que caer en el mismo proceso cuyo folio imprime la pagina
    de la cita; si cada lado resuelve por su cuenta, el alumno ve una tarjeta
    de estatus que no es la suya.
    """
    from datetime import datetime

    from itcj2.apps.titulatec.models import SurveyReview

    seed_phase_defs()
    make_survey_form()
    student = make_student()
    viejo = make_process(student, cohort=make_cohort(), current_phase=2)
    nuevo = make_process(student, cohort=make_cohort(), current_phase=2)
    viejo.created_at = datetime(2029, 1, 15, 9, 0, 0)
    nuevo.created_at = datetime(2029, 6, 15, 9, 0, 0)
    db_session.flush()
    c = client_as(student)

    envio = c.post(SURVEY_URL, data=OK_PAYLOAD, headers={"X-Real-IP": "203.0.113.46"},
                   follow_redirects=False)
    cita = c.get(CITA_URL, follow_redirects=False)

    assert 'data-tt-credit="in_review"' in envio.text
    solicitudes = _reviews(db_session)
    assert len(solicitudes) == 1
    assert solicitudes[0].process_id == nuevo.id

    assert cita.status_code == 200, cita.text[:500]
    assert 'data-tt-process="{}"'.format(nuevo.folio) in cita.text
    assert viejo.folio not in cita.text
    # SurveyReview no es la unica fuente de verdad de por si: si el checklist
    # buscara por otro proceso, la fila de arriba pasaria inadvertida.
    assert db_session.query(SurveyReview).filter_by(process_id=viejo.id).count() == 0


# ---------------------------------------------------------------------------
# Rutas: encuesta CONGELADA (GET / paso / borrador / submit)
# ---------------------------------------------------------------------------
def test_GET_con_solicitud_pinta_tarjeta_de_estatus_sin_prellenado(
    client_as, make_student, make_process, make_cohort, make_survey_review,
    db_session,
):
    """GET con solicitud existente: tarjeta de estatus, no el formulario, y
    ninguna escritura (ni borrador, ni respuesta nueva)."""
    student = make_student()
    proc = make_process(student, cohort=make_cohort())
    make_survey_review(proc, status="rejected", reason="Debes Servicio Social.")
    db_session.commit()

    resp = client_as(student).get(SURVEY_URL, follow_redirects=False)

    assert resp.status_code == 200, resp.text[:500]
    assert 'id="tt-survey-status"' in resp.text
    assert 'id="tt-survey-form"' not in resp.text
    assert 'data-tt-review-status="rejected"' in resp.text
    assert "Debes Servicio Social." in resp.text
    assert _drafts(db_session, user_id=student.id) == []
    assert len(_responses(db_session, process_id=proc.id)) == 1   # la de la fixture


def test_POST_paso_con_solicitud_pinta_tarjeta_de_estatus_sin_validar_ni_escribir(
    client_as, make_student, make_process, make_cohort, make_survey_review,
    db_session,
):
    """`/paso` con solicitud existente: corta ANTES de validar -un payload
    vacio (que reventaria `validate_answers`) igual pinta la tarjeta- y no
    escribe nada."""
    student = make_student()
    proc = make_process(student, cohort=make_cohort())
    make_survey_review(proc, status="in_review")
    db_session.commit()

    resp = client_as(student).post(SURVEY_STEP_URL, data={"tt_step": "0"},
                                   follow_redirects=False)

    assert resp.status_code == 200, resp.text[:500]
    assert 'id="tt-survey-status"' in resp.text
    assert 'data-tt-error' not in resp.text
    assert len(_responses(db_session, process_id=proc.id)) == 1
    assert _drafts(db_session, user_id=student.id) == []


def test_POST_borrador_con_solicitud_responde_204_sin_guardar(
    client_as, make_student, make_process, make_cohort, make_survey_review,
    db_session,
):
    """`/borrador` con solicitud existente: mismo camino "no escribe" que sin
    sesion -204 sin `X-Tt-Draft-Saved`- y CERO filas de borrador."""
    student = make_student()
    proc = make_process(student, cohort=make_cohort())
    make_survey_review(proc, status="approved")
    db_session.commit()

    resp = client_as(student).post(
        SURVEY_DRAFT_URL, data={"situacion_laboral": "empleado"},
        follow_redirects=False)

    assert resp.status_code == 204, resp.text[:300]
    assert "X-Tt-Draft-Saved" not in resp.headers
    assert _drafts(db_session, user_id=student.id) == []


def test_POST_submit_con_solicitud_no_consume_presupuesto_ni_reescribe(
    client_as, make_student, make_process, make_cohort, make_survey_review,
    db_session, monkeypatch,
):
    """POST con solicitud existente (spec 5.3): la MISMA tarjeta de gracias,
    con `already_submitted`, sin tocar el limitador -ni `_puede_enviar` ni
    `_contar_envio`- y sin escribir una segunda respuesta."""
    from itcj2.apps.titulatec.pages import public as mod

    student = make_student()
    proc = make_process(student, cohort=make_cohort())
    make_survey_review(proc, status="in_review")
    db_session.commit()

    llamados = {"puede": 0, "cuenta": 0}

    def _puede_enviar_espia(user, ip):
        llamados["puede"] += 1
        return True, 0

    def _contar_envio_espia(user, ip):
        llamados["cuenta"] += 1

    monkeypatch.setattr(mod, "_puede_enviar", _puede_enviar_espia)
    monkeypatch.setattr(mod, "_contar_envio", _contar_envio_espia)

    resp = client_as(student).post(SURVEY_URL, data=OK_PAYLOAD,
                                   headers={"X-Real-IP": "203.0.113.66"},
                                   follow_redirects=False)

    assert resp.status_code == 200, resp.text[:500]
    assert 'id="tt-survey-thanks"' in resp.text
    assert 'data-tt-credit="already_submitted"' in resp.text
    assert llamados == {"puede": 0, "cuenta": 0}
    assert len(_responses(db_session, process_id=proc.id)) == 1


def test_fallo_transitorio_en_solicitud_existente_no_produce_500(
    client_as, make_student, make_process, make_cohort, make_survey_form,
    monkeypatch,
):
    """Hallazgo Important #1 de la ronda 1 de revision: `_solicitud_existente`
    (pages/public.py) llamaba a `ProcessService.creditable_process` /
    `SurveyReviewService.get_for_process` sin try/except -al reves de lo que
    el propio modulo declara como ley ("Ninguna entrada del visitante puede
    producir un 500") y de lo que ya hace `_back_link` para el MISMO tipo de
    riesgo (un gate que consulta BD/Redis y puede fallar)-. Antes de la
    correccion, un fallo transitorio ahi tiraba las CUATRO rutas publicas de
    la encuesta con un 500 -peor todavia en las tres POST, que van por htmx:
    "htmx no swappea en 4xx" (docstring del modulo) tampoco swappea en 5xx, y
    el formulario del visitante se queda a medias sin ningun aviso-.

    Se parchea `ProcessService.creditable_process` -la PRIMERA llamada dentro
    de `_solicitud_existente`- para que reviente siempre, y se comprueba que
    ninguna de las cuatro rutas responda 500. `SurveyService.submit` hace la
    MISMA comprobacion por su cuenta (fuera del alcance de este hallazgo: no
    es el gate de la ruta, es la defensa del propio `submit`), asi que el
    envio real (ultima asercion) sigue sin poder escribir con la BD "caida" -
    pero lo dice con la tarjeta de error de siempre (200), nunca con un
    stack trace.
    """
    from itcj2.apps.titulatec.services.process_service import ProcessService

    make_survey_form()
    student = make_student()
    make_process(student, cohort=make_cohort())

    def _revienta(db, user_id):
        raise RuntimeError("BD/Redis caidos (simulado)")

    monkeypatch.setattr(ProcessService, "creditable_process", staticmethod(_revienta))
    c = client_as(student)

    get_resp = c.get(SURVEY_URL, follow_redirects=False)
    assert get_resp.status_code == 200, get_resp.text[:300]
    assert 'id="tt-survey-form"' in get_resp.text          # degrado a "sin solicitud"

    paso_resp = c.post(SURVEY_STEP_URL, data={"tt_step": "0"}, follow_redirects=False)
    assert paso_resp.status_code == 200, paso_resp.text[:300]
    assert 'id="tt-survey-form"' in paso_resp.text

    draft_resp = c.post(SURVEY_DRAFT_URL, data={"situacion_laboral": "empleado"},
                        follow_redirects=False)
    assert draft_resp.status_code == 204, draft_resp.text[:300]
    assert draft_resp.headers.get("X-Tt-Draft-Saved") == "1"   # siguio el camino normal

    submit_resp = c.post(SURVEY_URL, data=OK_PAYLOAD,
                         headers={"X-Real-IP": "203.0.113.70"}, follow_redirects=False)
    assert submit_resp.status_code == 200, submit_resp.text[:300]   # nunca 500
