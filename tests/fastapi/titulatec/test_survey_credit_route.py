"""El camino del credito de punta a punta (spec 6.3 + criterio de aceptacion 3).

Se prueba por HTTP y no llamando al service, porque la mitad de lo que puede
salir mal esta en el cableado: que la pagina publica pase el `user_id`, que el
requisito se siembre para una convocatoria que nunca lo tuvo, y que el proceso
al que aterriza el cumplimiento sea EL MISMO que renderiza el checklist.

Archivo aparte de `test_survey_credit.py` (Tarea 10, nivel service) a proposito:
aquel prueba `SurveyService._credit` directamente, este prueba la ruta. Fundirlos
haria que la definicion posterior de `test_acredita_a_un_alumno_con_proceso_activo`
tapara a la anterior sin que pytest dijera nada.
"""
from __future__ import annotations

SURVEY_URL = "/titulatec/encuesta-egresados"
CITA_URL = "/titulatec/student/cita"

OK_PAYLOAD = {
    "website": "",
    "situacion_laboral": "empleado",
    "relacion_carrera": "4",
}


def _fulfillments(db_session):
    """Cumplimientos escritos por el camino de la encuesta.

    Filtra por `source="system"` (y no una consulta pelada sobre toda la
    tabla) porque esta BD de dev es compartida y ya trae cumplimientos
    `officer` reales de QA manual de otras tareas (el checklist que marca un
    encargado): sin el filtro, `assert _fulfillments(db_session) == []` nunca
    pasaria aqui aunque el camino de la encuesta estuviera perfecto. El
    credito de la encuesta SIEMPRE escribe `source="system"`
    (`SurveyService._credit`, Tarea 10), asi que el filtro no oculta nada que
    esta tarea deba ver.
    """
    from itcj2.apps.titulatec.models import RequirementFulfillment
    return (db_session.query(RequirementFulfillment)
            .filter_by(source="system")
            .all())


def _auto_req(db_session, cohort_id):
    from itcj2.apps.titulatec.models import CotejoRequirement
    from itcj2.apps.titulatec.services.survey_service import AUTO_SOURCE_SURVEY
    return (db_session.query(CotejoRequirement)
            .filter_by(cohort_id=cohort_id, auto_source=AUTO_SOURCE_SURVEY)
            .first())


def test_acredita_a_un_alumno_con_proceso_activo(
    client_as, make_student, make_process, make_cohort, make_survey_form, db_session,
):
    """Criterio 3: cumplimiento + ProcessEvent, y la tarjeta lo dice."""
    from itcj2.apps.titulatec.models import ProcessEvent
    from itcj2.apps.titulatec.services.cotejo_requirement_service import (
        CotejoRequirementService,
    )

    make_survey_form()
    cohort = make_cohort()
    CotejoRequirementService.seed_defaults(db_session, cohort.id)
    student = make_student()
    proc = make_process(student, cohort=cohort, current_phase=2)

    resp = client_as(student).post(SURVEY_URL, data=OK_PAYLOAD,
                                   headers={"X-Real-IP": "203.0.113.41"},
                                   follow_redirects=False)

    assert resp.status_code == 200, resp.text[:500]
    assert 'data-tt-credit="credited"' in resp.text
    filas = _fulfillments(db_session)
    assert len(filas) == 1
    assert filas[0].process_id == proc.id
    assert filas[0].requirement_id == _auto_req(db_session, cohort.id).id
    # `system` y no `self_service`: la fila la escribe el sistema por cuenta del
    # alumno. `self_service` es lo que captura la persona; `officer`, el
    # expediente. Es el valor que `SurveyService._credit` (Tarea 10) ya escribe.
    assert filas[0].source == "system"
    eventos = (db_session.query(ProcessEvent)
               .filter_by(process_id=proc.id, event_type="requirement_fulfilled").all())
    assert len(eventos) == 1


def test_acredita_en_fase_1_aunque_nunca_haya_abierto_la_pagina_de_la_cita(
    client_as, make_student, make_process, make_cohort, make_survey_form, db_session,
):
    """La regresion de la siembra perezosa.

    `list_or_seed` solo se disparaba desde una pagina gateada por la fase 2, asi
    que un alumno en fase 1 —la mayoria: la encuesta se promueve en publico— no
    tenia requisitos que acreditar y el credito se perdia EN SILENCIO. Aqui la
    convocatoria arranca con CERO requisitos a proposito.
    """
    from itcj2.apps.titulatec.models import CotejoRequirement

    make_survey_form()
    cohort = make_cohort()
    assert db_session.query(CotejoRequirement).filter_by(cohort_id=cohort.id).count() == 0
    student = make_student()
    proc = make_process(student, cohort=cohort, current_phase=1)

    resp = client_as(student).post(SURVEY_URL, data=OK_PAYLOAD,
                                   headers={"X-Real-IP": "203.0.113.42"},
                                   follow_redirects=False)

    assert resp.status_code == 200, resp.text[:500]
    assert 'data-tt-credit="credited"' in resp.text
    assert _auto_req(db_session, cohort.id) is not None      # se sembro al vuelo
    filas = _fulfillments(db_session)
    assert len(filas) == 1
    assert filas[0].process_id == proc.id


def test_sin_proceso_no_acredita_y_lo_dice_con_la_copia_de_no_process(
    client_as, make_student, make_survey_form, db_session,
):
    """Falla la regla 2 de 6.3. La copia es distinta a la de la regla 3 a proposito.

    El literal es el que de verdad renderiza `survey_thanks.html` (Tareas 12-13):
    "No encontramos..." con mayuscula porque abre oracion tras el punto de
    "Tu respuesta quedo registrada...". El brief de esta tarea citaba una version
    en minusculas que nunca coincidio con la plantilla ya cerrada.
    """
    make_survey_form()

    resp = client_as(make_student()).post(SURVEY_URL, data=OK_PAYLOAD,
                                          headers={"X-Real-IP": "203.0.113.43"},
                                          follow_redirects=False)

    assert resp.status_code == 200, resp.text[:500]
    assert 'data-tt-credit="no_process"' in resp.text
    assert "No encontramos un proceso de titulación activo a tu nombre" in resp.text
    assert _fulfillments(db_session) == []


def test_sin_requisito_auto_no_acredita_y_lo_dice_con_la_copia_de_no_requirement(
    client_as, make_student, make_process, make_cohort, make_survey_form, db_session,
):
    """Falla la regla 3 de 6.3.

    La convocatoria SI tiene requisitos —asi que seed-or-list no vuelve a
    sembrar— pero ninguno lleva `auto_source`. Si esta copia fuera la misma que
    la de exito, un fallo de configuracion seria invisible para todos.

    El literal es el que de verdad renderiza `survey_thanks.html` (Tareas 12-13):
    "todavia no tiene configurado el requisito de la encuesta", no el "aun no
    tiene configurado este requisito" que citaba el brief de esta tarea.
    """
    from itcj2.apps.titulatec.models import CotejoRequirement

    make_survey_form()
    cohort = make_cohort()
    db_session.add(CotejoRequirement(cohort_id=cohort.id, label="No adeudo de biblioteca",
                                     hint="Constancia vigente.", icon="book", order_index=0))
    db_session.flush()
    student = make_student()
    make_process(student, cohort=cohort, current_phase=2)

    resp = client_as(student).post(SURVEY_URL, data=OK_PAYLOAD,
                                   headers={"X-Real-IP": "203.0.113.44"},
                                   follow_redirects=False)

    assert resp.status_code == 200, resp.text[:500]
    assert 'data-tt-credit="no_requirement"' in resp.text
    assert "todavía no tiene configurado el requisito de la encuesta" in resp.text
    assert _fulfillments(db_session) == []


def test_contestar_dos_veces_no_duplica_el_cumplimiento(
    client_as, make_student, make_process, make_cohort, make_survey_form, db_session,
):
    """Regla 4 de 6.3. La segunda vez la tarjeta lo dice ('already')."""
    from itcj2.apps.titulatec.services.cotejo_requirement_service import (
        CotejoRequirementService,
    )

    make_survey_form()
    cohort = make_cohort()
    CotejoRequirementService.seed_defaults(db_session, cohort.id)
    student = make_student()
    make_process(student, cohort=cohort, current_phase=2)
    c = client_as(student)
    cabeceras = {"X-Real-IP": "203.0.113.45"}

    primera = c.post(SURVEY_URL, data=OK_PAYLOAD, headers=cabeceras, follow_redirects=False)
    segunda = c.post(SURVEY_URL, data=OK_PAYLOAD, headers=cabeceras, follow_redirects=False)

    assert 'data-tt-credit="credited"' in primera.text
    assert 'data-tt-credit="already"' in segunda.text
    assert len(_fulfillments(db_session)) == 1


def test_el_desempate_por_id_hace_total_el_orden_de_creditable_process(
    make_student, make_process, make_cohort, db_session,
):
    """`ORDER BY (created_at, id)`: el `id` es lo que lo vuelve determinista.

    `NOW()` en Postgres es la marca de la TRANSACCION, asi que dos procesos
    creados en el mismo test comparten `created_at` al milisegundo. Sin el
    desempate por `id`, cual gana depende del plan de Postgres y el credito
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


def test_con_dos_procesos_vivos_el_credito_aterriza_en_el_que_ve_el_alumno(
    client_as, make_student, make_process, make_cohort, make_survey_form,
    seed_phase_defs, db_session,
):
    """Invariante de 5.3: el checklist y el credito leen el MISMO helper.

    Dos convocatorias, dos procesos vivos, fechas de alta distintas para que el
    resultado no dependa del desempate. El cumplimiento tiene que caer en el
    mismo proceso cuyo folio imprime la pagina de la cita; si cada lado resuelve
    por su cuenta, el alumno ve una palomita que no es la suya.
    """
    from datetime import datetime

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

    assert 'data-tt-credit="credited"' in envio.text
    filas = _fulfillments(db_session)
    assert len(filas) == 1
    assert filas[0].process_id == nuevo.id

    assert cita.status_code == 200, cita.text[:500]
    assert 'data-tt-process="{}"'.format(nuevo.folio) in cita.text
    assert viejo.folio not in cita.text


def test_el_checklist_del_alumno_marca_el_requisito_ya_acreditado(
    client_as, make_student, make_process, make_cohort, make_survey_form,
    seed_phase_defs, db_session,
):
    """Criterio 3, la mitad que el alumno ve: la palomita aparece sola."""
    from itcj2.apps.titulatec.services.requirement_service import RequirementService

    seed_phase_defs()
    make_survey_form()
    cohort = make_cohort()
    student = make_student()
    proc = make_process(student, cohort=cohort, current_phase=2)
    c = client_as(student)

    c.post(SURVEY_URL, data=OK_PAYLOAD, headers={"X-Real-IP": "203.0.113.47"},
           follow_redirects=False)
    cita = c.get(CITA_URL, follow_redirects=False)

    assert cita.status_code == 200, cita.text[:500]
    assert 'data-tt-process="{}"'.format(proc.folio) in cita.text
    estados = RequirementService.list_with_status(db_session, proc.id)
    hechos = [r for r in estados if r["is_done"]]
    assert len(hechos) == 1
    assert hechos[0]["requirement"].auto_source == "graduate_survey"
