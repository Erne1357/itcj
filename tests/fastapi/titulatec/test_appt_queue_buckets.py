"""Los CUATRO cubos de la cola del encargado son mutuamente excluyentes (§6, D10).

    1. Por agendar               sin cita vigente y todavia puede agendar solo
    2. Requieren que les agendes bloqueados por D9 (3 cancelaciones propias)  <- nuevo
    3. Reagendar                 su cita vigente quedo en `no_show`
    4. Sin encuesta              sin `SurveyReview`

Por que la exclusion mutua es el invariante y no un detalle estetico
-------------------------------------------------------------------
Los cubos 1 y 2 salen del MISMO universo (`_pending_candidates`) y se reparten
con un solo predicado (`is_blocked_by_cancellations`). Si `list_pending_processes`
olvidara restar a los bloqueados, el mismo alumno saldria en los dos y el
encargado no sabria cual mirar — ni cual de los dos contadores le dice la
verdad. Es exactamente el modo de fallo que D10 existe para cerrar: el cubo 2
solo sirve si es el UNICO sitio donde aparece el bloqueado.

REGLA DE ORO (heredada de `test_scope_guard.py`): ninguna asercion negativa va
sola. "El bloqueado no esta en Por agendar" viaja siempre con "y SI esta en su
propio cubo", para que un fixture roto —que dejaria los dos cubos vacios— salga
en rojo en vez de en verde.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

URL = "/titulatec/admin/appointments"

_D = date(2029, 5, 7)
_INITIAL_DOCS = ("birth_certificate", "high_school_cert", "curp")


def _con_docs_y_encuesta(proc, make_document, make_survey_review):
    """Los 3 documentos iniciales APROBADOS + la solicitud de liberacion.

    Es el minimo para entrar a `_pending_candidates`, el universo del que
    salen los cubos 1 y 2.
    """
    for code in _INITIAL_DOCS:
        make_document(proc, type_code=code, review_status="approved")
    make_survey_review(proc)
    return proc


@pytest.fixture()
def cola(seed_phase_defs, seed_document_types, make_program, make_cohort,
         make_review_day, make_student, make_process, make_document,
         make_appointment, make_officer, make_survey_review, db_session):
    """Un proceso por cubo, todos en la MISMA carrera y convocatoria.

    Que compartan carrera es deliberado: asi la exclusion mutua no puede pasar
    por accidente gracias al filtro de alcance. Los cuatro caen dentro del
    alcance del encargado y aun asi tienen que repartirse sin solaparse.
    """
    seed_phase_defs()
    seed_document_types()
    prog = make_program("Ingenieria de Cubos")
    cohort = make_cohort()
    make_review_day(cohort, day=_D)
    officer, pos = make_officer([prog])

    def _proc(nombre):
        student = make_student(first_name="ALUMNO", last_name=nombre)
        return make_process(student, cohort=cohort, program=prog, current_phase=2)

    # --- cubo 1: por agendar ------------------------------------------------
    p_pendiente = _con_docs_y_encuesta(_proc("PENDIENTE"), make_document,
                                       make_survey_review)

    # --- cubo 2: bloqueado por D9 -------------------------------------------
    # Tres cancelaciones SUYAS (`cancelled_by_id == student_id`, que es lo que
    # cuenta `SelfBookingService.cancellations`), ninguna vigente. Sin cita
    # vigente sigue estando "sin cita", que es lo que lo mantiene en el
    # universo de `_pending_candidates`.
    p_bloqueado = _con_docs_y_encuesta(_proc("BLOQUEADO"), make_document,
                                       make_survey_review)
    for n in range(1, 4):
        appt = make_appointment(
            p_bloqueado,
            when=datetime.combine(_D, datetime.min.time()).replace(hour=9) +
            timedelta(days=n),
            status="cancelled", is_current=False, attempt_no=n)
        appt.cancelled_by_id = p_bloqueado.student_id
    db_session.flush()

    # --- cubo 3: reagendar (no se presento) ---------------------------------
    p_reagendar = _con_docs_y_encuesta(_proc("AUSENTE"), make_document,
                                       make_survey_review)
    make_appointment(p_reagendar, status="no_show", is_current=True)

    # --- cubo 4: sin encuesta -----------------------------------------------
    p_sin_encuesta = _proc("SINENCUESTA")
    for code in _INITIAL_DOCS:
        make_document(p_sin_encuesta, type_code=code, review_status="approved")

    # --- el UNICO cruce plausible: no_show vigente Y 3 cancelaciones propias --
    # Es el solape real que puede darse entre «Reagendar» y «Requieren que les
    # agendes», y sin el en el fixture la prueba de disjuncion nunca lo mira.
    # Tiene que caer SOLO en «Reagendar»: conserva una cita vigente, asi que
    # `_unscheduled_query` lo saca del universo del que salen los cubos 1 y 2.
    p_ambos = _con_docs_y_encuesta(_proc("AMBOS"), make_document, make_survey_review)
    for n in range(1, 4):
        appt = make_appointment(p_ambos, status="cancelled", is_current=False,
                                attempt_no=n)
        appt.cancelled_by_id = p_ambos.student_id
    make_appointment(p_ambos, status="no_show", is_current=True, attempt_no=4)

    db_session.flush()
    return {"prog": prog, "cohort": cohort, "off": officer, "pos": pos,
            "pendiente": p_pendiente, "bloqueado": p_bloqueado,
            "reagendar": p_reagendar, "sin_encuesta": p_sin_encuesta,
            "ambos": p_ambos}


def _cubos(db_session, allowed):
    from itcj2.apps.titulatec.services.appointment_service import AppointmentService
    return {
        "por_agendar": {p.id for p in AppointmentService.list_pending_processes(
            db_session, allowed_program_ids=allowed)},
        "bloqueados": {p.id for p in AppointmentService.list_self_blocked_processes(
            db_session, allowed_program_ids=allowed)},
        "reagendar": {p.id for p in AppointmentService.list_reschedule_processes(
            db_session, allowed_program_ids=allowed)},
        "sin_encuesta": {p.id for p in AppointmentService.list_missing_survey_processes(
            db_session, allowed_program_ids=allowed)},
    }


# ---------------------------------------------------------------------------
# El reparto, en el servicio
# ---------------------------------------------------------------------------
def test_cada_proceso_cae_en_exactamente_un_cubo(cola, db_session):
    """El invariante entero en una asercion: ninguno en dos, ninguno en cero."""
    cubos = _cubos(db_session, {cola["prog"].id})

    esperado = {
        cola["pendiente"].id: "por_agendar",
        cola["bloqueado"].id: "bloqueados",
        cola["reagendar"].id: "reagendar",
        cola["sin_encuesta"].id: "sin_encuesta",
        # Cancelo 3 veces PERO tiene cita vigente: manda la cita.
        cola["ambos"].id: "reagendar",
    }
    for pid, cubo in esperado.items():
        donde = sorted(nombre for nombre, ids in cubos.items() if pid in ids)
        assert donde == [cubo], (
            "el proceso %d deberia estar SOLO en '%s' y esta en %s" % (pid, cubo, donde))


def test_los_cuatro_cubos_son_disjuntos_dos_a_dos(cola, db_session):
    """Formulado sobre los conjuntos, no sobre los procesos del fixture.

    Asi tambien caza un solape entre procesos que este fixture no fabrico.
    """
    cubos = _cubos(db_session, {cola["prog"].id})
    nombres = sorted(cubos)
    solapes = [(a, b, sorted(cubos[a] & cubos[b]))
               for i, a in enumerate(nombres) for b in nombres[i + 1:]
               if cubos[a] & cubos[b]]
    assert not solapes, "cubos que comparten procesos: %s" % (solapes,)


def test_el_bloqueado_sale_de_por_agendar_y_entra_al_suyo(cola, db_session):
    """D10 en su forma mas directa, con su asercion positiva al lado."""
    cubos = _cubos(db_session, {cola["prog"].id})

    assert cola["bloqueado"].id in cubos["bloqueados"], (
        "el bloqueado por D9 no aparece en «Requieren que les agendes»: si nadie "
        "sabe que espera, nadie le va a agendar")
    assert cola["bloqueado"].id not in cubos["por_agendar"]
    # La asercion positiva que impide que un fixture roto deje esto en verde:
    # el cubo 1 sigue teniendo a quien SI puede agendar solo.
    assert cola["pendiente"].id in cubos["por_agendar"]


def test_tener_una_cita_vigente_gana_al_tope_de_cancelaciones(cola, db_session):
    """Quien no se presento Y ademas cancelo 3 veces sale SOLO en «Reagendar».

    El cubo de D10 es para quien esta esperando que le agenden; este ya tiene
    lugar (un `no_show` conserva su franja, D10), asi que ponerlo tambien ahi le
    diria al encargado que agende a alguien que no lo necesita.
    """
    cubos = _cubos(db_session, {cola["prog"].id})
    pid = cola["ambos"].id

    assert pid in cubos["reagendar"]
    assert pid not in cubos["bloqueados"]
    assert pid not in cubos["por_agendar"]


def test_el_criterio_del_cubo_es_el_mismo_que_ve_el_alumno(cola, db_session):
    """El cubo y la pantalla del alumno comparten `is_blocked_by_cancellations`.

    Con dos implementaciones, el encargado veria a alguien esperando cita
    mientras el alumno sigue viendo el boton de agendar (o al reves).
    """
    from itcj2.apps.titulatec.services.self_booking_service import SelfBookingService

    assert SelfBookingService.cancellations(db_session, cola["bloqueado"]) == 3
    assert SelfBookingService.is_blocked_by_cancellations(db_session, cola["bloqueado"])
    assert not SelfBookingService.is_blocked_by_cancellations(db_session, cola["pendiente"])


def test_la_cancelacion_del_encargado_no_bloquea_al_alumno(cola, db_session,
                                                           make_appointment):
    """Solo cuentan las que cancelo EL: si no, el encargado lo bloquea sin querer."""
    from itcj2.apps.titulatec.services.self_booking_service import SelfBookingService

    proc = cola["pendiente"]
    for n in range(1, 4):
        appt = make_appointment(proc, status="cancelled", is_current=False,
                                attempt_no=n)
        appt.cancelled_by_id = cola["off"].id      # lo cancelo el ENCARGADO
    db_session.flush()

    assert SelfBookingService.cancellations(db_session, proc) == 0
    cubos = _cubos(db_session, {cola["prog"].id})
    assert proc.id in cubos["por_agendar"]
    assert proc.id not in cubos["bloqueados"]


# ---------------------------------------------------------------------------
# El reparto, en la pantalla
# ---------------------------------------------------------------------------
def test_la_cola_pinta_el_cuarto_cubo_con_su_conteo(cola, client_as):
    """El cubo tiene que DECIR por que esta ahi, no solo listar nombres.

    «3 cancelaciones · ya no puede agendar solo» es la frase que convierte una
    lista mas en una instruccion.
    """
    resp = client_as(cola["off"]).get(URL + "?date=" + _D.isoformat())
    assert resp.status_code == 200
    html = resp.text

    assert "Requieren que les agendes" in html, "falta el cubo de D10 en la cola"
    assert "3 cancelaciones" in html, "la fila no dice cuantas veces cancelo"
    assert "ya no puede agendar solo" in html


def test_en_la_pantalla_el_bloqueado_esta_en_un_solo_cubo(cola, client_as):
    """Se comprueba por los IDs de fila, no por el nombre.

    Los ids son estables a proposito (el swap es `morph:outerHTML` y sin id
    Idiomorph empareja por posicion), asi que son el ancla honesta: el nombre
    aparece dos veces por fila (texto y `title=`) y contarlo seria fragil.
    """
    resp = client_as(cola["off"]).get(URL + "?date=" + _D.isoformat())
    html = resp.text
    pid = cola["bloqueado"].id

    # Las anclas cierran la COMILLA final. Sin ella la negativa es una
    # subcadena: con el bloqueado en el id 12 y un 123 en «Por agendar»,
    # "appt-queue-12" existe en el HTML y el test falla sin que nada este roto.
    assert ('appt-blocked-%d"' % pid) in html, "el bloqueado no tiene fila en su cubo"
    assert ('appt-queue-%d"' % pid) not in html, (
        "el bloqueado sigue saliendo en «Por agendar»: los cubos dejaron de ser "
        "mutuamente excluyentes")
    # Positiva al lado: quien SI puede agendar solo conserva su fila del cubo 1.
    assert ('appt-queue-%d"' % cola["pendiente"].id) in html
