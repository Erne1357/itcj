"""Los CINCO cubos de la cola del encargado son mutuamente excluyentes (§6, D10).

    1. Por agendar               sin cita vigente y todavia puede agendar solo
    2. Requieren que les agendes bloqueados por D9 (3 cancelaciones propias)
    3. Reagendar                 su cita vigente quedo en `no_show`
    4. Cotejo rechazado          vigente `attended` + fase 2 `rejected` (D5)  <- nuevo
    5. Sin encuesta              sin `SurveyReview`

Por que la exclusion mutua es el invariante y no un detalle estetico
-------------------------------------------------------------------
Los cubos 1 y 2 salen del MISMO universo (`_pending_candidates`) y se reparten
con un solo predicado (`is_blocked_by_cancellations`). Si `list_pending_processes`
olvidara restar a los bloqueados, el mismo alumno saldria en los dos y el
encargado no sabria cual mirar — ni cual de los dos contadores le dice la
verdad. Es exactamente el modo de fallo que D10 existe para cerrar: el cubo 2
solo sirve si es el UNICO sitio donde aparece el bloqueado.

El cubo 4 se reparte con el 3 de otra manera, y mas fuerte: los dos exigen cita
VIGENTE, pero uno la exige `no_show` y el otro `attended`, que se excluyen por
construccion. Ahi no hay resta que olvidar.

D5 SE HABIA QUEDADO SIN BANDEJA, y este archivo no podia verlo
---------------------------------------------------------------
El fixture no construia ningun `attended`, asi que la disjuncion se afirmaba
sobre un universo donde el caso de D5 ni siquiera existia. Un proceso atendido
al que le RECHAZAN la fase 2 caia en CERO cubos: conserva cita vigente (fuera de
1, 2 y 5) y no es `no_show` (fuera de 3). Auto-agendarse si podia, pero solo si
alguien habia publicado un espacio `bookable`, y `private` es el `server_default`
— o sea que el dia uno no aparecia en ninguna lista de nadie.

Por eso el fixture trae ahora TRES procesos con cita `attended`, que son los tres
desenlaces posibles de un cotejo atendido:

    rechazado   fase 2 `rejected`      -> cubo 4
    dictamen    fase 2 sin dictaminar  -> CERO cubos, a proposito (no le falta
                                          cita: le falta que el encargado se
                                          pronuncie, que es otra pantalla)
    ausente     rechazado y luego falto -> solo cubo 3 (manda la cita vigente)

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


def _fase2(db_session, proc, estado):
    """Deja la fase 2 del proceso en `estado`.

    `make_process(current_phase=2)` la crea en `in_progress`; el cubo 4 la
    necesita en `rejected`. Se resuelve por `PhaseService.PHASE_COTEJO` y no por
    un `2` literal, que es la misma constante que usan el service del cubo y
    `SelfBookingService._fase_cotejo_aprobada`.
    """
    from itcj2.apps.titulatec.models import ProcessPhase
    from itcj2.apps.titulatec.services.phase_service import PhaseService

    fila = (db_session.query(ProcessPhase)
            .filter_by(process_id=proc.id, phase_number=PhaseService.PHASE_COTEJO)
            .first())
    assert fila is not None, "el proceso nacio sin fase 2: el fixture no prueba nada"
    fila.status = estado
    db_session.flush()
    return fila


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

    # --- cubo 4: se le atendio y le RECHAZARON la fase 2 (D5) ----------------
    # El caso que no tenia bandeja. Cita vigente `attended`, asi que el universo
    # «sin cita» no lo ve; no es `no_show`, asi que «Reagendar» tampoco.
    p_rechazado = _con_docs_y_encuesta(_proc("RECHAZADO"), make_document,
                                       make_survey_review)
    make_appointment(p_rechazado, status="attended", is_current=True)
    _fase2(db_session, p_rechazado, "rejected")

    # --- CERO cubos a proposito: atendido y esperando DICTAMEN ---------------
    # No le falta cita, le falta que el encargado se pronuncie. Si saliera en el
    # cubo 4 le estariamos pidiendo al encargado que agende a alguien que quiza
    # ya termino.
    p_dictamen = _con_docs_y_encuesta(_proc("DICTAMEN"), make_document,
                                      make_survey_review)
    make_appointment(p_dictamen, status="attended", is_current=True)

    # --- el cruce real entre los cubos 3 y 4 ---------------------------------
    # Atendido -> fase 2 rechazada -> se le reagendo -> falto. La fase SIGUE
    # rechazada, asi que un cubo 4 formulado solo sobre la fase lo listaria a la
    # vez que «Reagendar». Manda la cita VIGENTE, que es `no_show`.
    p_rech_ausente = _con_docs_y_encuesta(_proc("RECHAZADOAUSENTE"), make_document,
                                          make_survey_review)
    make_appointment(p_rech_ausente, status="attended", is_current=False,
                     attempt_no=1)
    make_appointment(p_rech_ausente, status="no_show", is_current=True,
                     attempt_no=2)
    _fase2(db_session, p_rech_ausente, "rejected")

    db_session.flush()
    return {"prog": prog, "cohort": cohort, "off": officer, "pos": pos,
            "pendiente": p_pendiente, "bloqueado": p_bloqueado,
            "reagendar": p_reagendar, "sin_encuesta": p_sin_encuesta,
            "ambos": p_ambos, "rechazado": p_rechazado,
            "dictamen": p_dictamen, "rech_ausente": p_rech_ausente}


def _cubos(db_session, allowed):
    from itcj2.apps.titulatec.services.appointment_service import AppointmentService
    return {
        "por_agendar": {p.id for p in AppointmentService.list_pending_processes(
            db_session, allowed_program_ids=allowed)},
        "bloqueados": {p.id for p in AppointmentService.list_self_blocked_processes(
            db_session, allowed_program_ids=allowed)},
        "reagendar": {p.id for p in AppointmentService.list_reschedule_processes(
            db_session, allowed_program_ids=allowed)},
        "rechazados": {p.id for p in AppointmentService.list_rejected_cotejo_processes(
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
        # D5: atendido y con la fase 2 rechazada.
        cola["rechazado"].id: "rechazados",
        # Fase 2 rechazada PERO la vigente es `no_show`: manda la cita.
        cola["rech_ausente"].id: "reagendar",
    }
    for pid, cubo in esperado.items():
        donde = sorted(nombre for nombre, ids in cubos.items() if pid in ids)
        assert donde == [cubo], (
            "el proceso %d deberia estar SOLO en '%s' y esta en %s" % (pid, cubo, donde))


def test_los_cinco_cubos_son_disjuntos_dos_a_dos(cola, db_session):
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


def test_el_cotejo_rechazado_tiene_bandeja_propia(cola, db_session):
    """D5, en su forma mas directa: atendido + fase 2 rechazada = otra cita.

    Antes de este cubo, este proceso no salia en NINGUNA lista del encargado.
    La negativa («no esta en los otros cuatro») viaja con su positiva («si esta
    en el suyo»), o un fixture roto dejaria los cinco cubos vacios y el test en
    verde.
    """
    cubos = _cubos(db_session, {cola["prog"].id})
    pid = cola["rechazado"].id

    assert pid in cubos["rechazados"], (
        "el atendido con la fase 2 rechazada no aparece en «Cotejo rechazado»: "
        "vuelve a estar en cero cubos, que es el defecto que este cubo cierra")
    for otro in ("por_agendar", "bloqueados", "reagendar", "sin_encuesta"):
        assert pid not in cubos[otro], "tambien sale en %s" % otro
    # Positiva de control: el cubo 1 sigue teniendo a quien le toca.
    assert cola["pendiente"].id in cubos["por_agendar"]


def test_el_atendido_que_espera_dictamen_no_es_trabajo_de_agenda(cola, db_session):
    """Atendido y SIN dictaminar no va a ningun cubo, y eso es correcto.

    A ese no le falta cita: le falta que el encargado apruebe o rechace la fase
    2, que es otro trabajo y otra pantalla. Formular el cubo 4 sobre `attended`
    a secas —en vez de sobre `attended` + fase `rejected`— lo metaria aqui y le
    pediria al encargado que agendara a alguien que quiza ya termino.

    Va con su positiva al lado: el que SI fue rechazado esta en su cubo, asi que
    un predicado que no encontrara nunca nada no pasaria este test.
    """
    cubos = _cubos(db_session, {cola["prog"].id})
    pid = cola["dictamen"].id

    donde = sorted(nombre for nombre, ids in cubos.items() if pid in ids)
    assert donde == [], "el que espera dictamen salio en %s" % (donde,)
    assert cola["rechazado"].id in cubos["rechazados"]


def test_la_fase_aprobada_no_pide_otra_cita(cola, db_session):
    """El tercer desenlace de un `attended`: la fase 2 APROBADA.

    Es el caso terminal de §3 (`fase_aprobada`) — ya no necesita nada—, asi que
    tampoco puede aparecer en el cubo de D5. Se mide moviendo al rechazado, que
    es la unica forma de probar que lo que decide es la FASE y no el `attended`.
    """
    assert cola["rechazado"].id in _cubos(db_session, {cola["prog"].id})["rechazados"]

    _fase2(db_session, cola["rechazado"], "approved")

    cubos = _cubos(db_session, {cola["prog"].id})
    assert cola["rechazado"].id not in cubos["rechazados"], (
        "con la fase 2 aprobada ya no necesita otra cita")
    assert not any(cola["rechazado"].id in ids for ids in cubos.values())


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


def test_la_cola_pinta_el_cubo_de_cotejo_rechazado(cola, client_as):
    """D5 llega hasta la PANTALLA, que es donde el encargado lo necesita.

    El service puede tener el cubo y la cola no pintarlo: son dos capas, y la
    unica que le sirve al encargado es la segunda.
    """
    resp = client_as(cola["off"]).get(URL + "?date=" + _D.isoformat())
    assert resp.status_code == 200
    html = resp.text

    assert "Cotejo rechazado" in html, "falta el cubo de D5 en la cola"
    assert ('appt-rejected-%d"' % cola["rechazado"].id) in html
    # El que espera dictamen NO tiene fila: no es trabajo de agenda.
    assert ('appt-rejected-%d"' % cola["dictamen"].id) not in html


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
