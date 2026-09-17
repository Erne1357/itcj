"""Los CINCO cubos de la cola del encargado son mutuamente excluyentes (§6, D10).

Orden en PANTALLA (fijado 2026-09-17; el orden en este archivo no importa):

    1. Por agendar               sin cita vigente, fase 02 NUNCA rechazada, y
                                  todavia puede agendar solo. Prioridad visual.
    2. Fase 02 rechazada         fase 2 `rejected` + (vigente `attended` O SIN
                                  cita vigente en absoluto)                     <- ampliado
    3. Requieren que les agendes bloqueados por D9 (3 cancelaciones propias)
    4. Reagendar                 su cita vigente quedo en `no_show`
    5. Sin encuesta              sin `SurveyReview`

Por que la exclusion mutua es el invariante y no un detalle estetico
-------------------------------------------------------------------
Los cubos «Por agendar» y «Requieren que les agendes» salen del MISMO universo
(`_pending_candidates`) y se reparten con un solo predicado
(`is_blocked_by_cancellations`). Si `list_pending_processes` olvidara restar a
los bloqueados, el mismo alumno saldria en los dos y el encargado no sabria
cual mirar — ni cual de los dos contadores le dice la verdad. Es exactamente el
modo de fallo que D10 existe para cerrar: el cubo 3 solo sirve si es el UNICO
sitio donde aparece el bloqueado.

«Fase 02 rechazada» se reparte con «Reagendar» de otra manera, y mas fuerte:
los dos exigen "no hay cita viva que tape", pero uno lo resuelve por `no_show`
vigente y el otro por «`attended` vigente o ninguna cita en absoluto», que se
excluyen por construccion. Ahi no hay resta que olvidar.

D5 SE HABIA QUEDADO SIN BANDEJA, y este archivo no podia verlo
---------------------------------------------------------------
El fixture no construia ningun `attended`, asi que la disjuncion se afirmaba
sobre un universo donde el caso de D5 ni siquiera existia. Un proceso atendido
al que le RECHAZAN la fase 2 caia en CERO cubos: conserva cita vigente (fuera de
"Por agendar", "Requieren" y "Sin encuesta") y no es `no_show` (fuera de
"Reagendar"). Auto-agendarse si podia, pero solo si alguien habia publicado un
espacio `bookable`, y `private` es el `server_default` — o sea que el dia uno
no aparecia en ninguna lista de nadie.

Por eso el fixture trae TRES procesos con cita `attended`, que son los tres
desenlaces posibles de un cotejo atendido:

    rechazado   fase 2 `rejected`      -> "Fase 02 rechazada"
    dictamen    fase 2 sin dictaminar  -> CERO cubos, a proposito (no le falta
                                          cita: le falta que el encargado se
                                          pronuncie, que es otra pantalla)
    ausente     rechazado y luego falto -> solo "Reagendar" (manda la cita)

AMPLIACION 2026-09-17: la fase manda, no la cita
-------------------------------------------------
El predicado original exigia `status='attended'` en la vigente A SECAS, asi
que a quien se le CANCELABA esa cita tras el rechazo (D6: cancelar libera y
vuelve a "sin cita") le volvia a pasar lo mismo que a D5: cero cubos, y si
encima tenia docs+encuesta, reaparecia en "Por agendar" mezclado con quien
nunca tuvo cita. El fixture agrega tres procesos mas para cubrir esto y el
caso real que lo disparo (proceso #39 de dev: rechazado + `attended` + SIN
`SurveyReview`, que revienta `SurveyNotSubmitted` si se arrastra a un lugar):

    rech_sin_cita       fase 2 `rejected`, CERO citas          -> su cubo,
                                                                   NO "Por agendar"
    rech_sin_encuesta   fase 2 `rejected` + `attended` vigente, -> su cubo,
                        SIN `SurveyReview`                        fila SIN
                                                                   arrastre
    rech_con_encuesta   igual, CON `SurveyReview`               -> su cubo,
                                                                   fila arrastrable

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

    # --- AMPLIACION 2026-09-17: fase 2 rechazada, SIN cita vigente EN ABSOLUTO
    # El caso que el predicado original ("attended" a secas) se perdia: si se
    # cancela la `attended` que dejo el rechazo (D6 libera y vuelve a "sin
    # cita"), el proceso tiene que seguir en "Fase 02 rechazada" y NO
    # reaparecer en "Por agendar" como si fuera de primera vez. Se modela en
    # su forma minima -nunca llego a tener una cita- porque el predicado es
    # sobre la FASE, no sobre el historial de citas: da igual como se llegue a
    # "sin cita vigente", solo importa que se llegue.
    p_rech_sin_cita = _con_docs_y_encuesta(_proc("RECHAZADOSINCITA"), make_document,
                                           make_survey_review)
    _fase2(db_session, p_rech_sin_cita, "rejected")

    # --- el caso real de dev (proceso #39): rechazado + attended + SIN
    # SurveyReview. `create()` nunca deja que esto pase por el camino normal
    # (exige la encuesta ANTES que cualquier otra cosa), pero datos que no
    # pasaron por el service -import, fixtures, migraciones- si pueden
    # producirlo, y arrastrarlo a un lugar libre revienta con
    # `SurveyNotSubmitted`. NO se usa `_con_docs_y_encuesta`: a proposito, sin
    # encuesta.
    p_rech_sin_encuesta = _proc("RECHAZADOSINENCUESTA")
    make_appointment(p_rech_sin_encuesta, status="attended", is_current=True)
    _fase2(db_session, p_rech_sin_encuesta, "rejected")

    # --- el control positivo del anterior: mismo escenario, CON encuesta -----
    p_rech_con_encuesta = _proc("RECHAZADOCONENCUESTA")
    make_survey_review(p_rech_con_encuesta)
    make_appointment(p_rech_con_encuesta, status="attended", is_current=True)
    _fase2(db_session, p_rech_con_encuesta, "rejected")

    db_session.flush()
    return {"prog": prog, "cohort": cohort, "off": officer, "pos": pos,
            "pendiente": p_pendiente, "bloqueado": p_bloqueado,
            "reagendar": p_reagendar, "sin_encuesta": p_sin_encuesta,
            "ambos": p_ambos, "rechazado": p_rechazado,
            "dictamen": p_dictamen, "rech_ausente": p_rech_ausente,
            "rech_sin_cita": p_rech_sin_cita,
            "rech_sin_encuesta": p_rech_sin_encuesta,
            "rech_con_encuesta": p_rech_con_encuesta}


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
        # AMPLIACION 2026-09-17: fase 2 rechazada, SIN cita vigente en
        # absoluto -- sigue siendo "rechazados" y NO "por_agendar", aunque
        # tenga docs y encuesta como cualquier proceso de primera vez.
        cola["rech_sin_cita"].id: "rechazados",
        cola["rech_sin_encuesta"].id: "rechazados",
        cola["rech_con_encuesta"].id: "rechazados",
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
        "el atendido con la fase 2 rechazada no aparece en «Fase 02 "
        "rechazada»: vuelve a estar en cero cubos, que es el defecto que este "
        "cubo cierra")
    for otro in ("por_agendar", "bloqueados", "reagendar", "sin_encuesta"):
        assert pid not in cubos[otro], "tambien sale en %s" % otro
    # Positiva de control: el cubo 1 sigue teniendo a quien le toca.
    assert cola["pendiente"].id in cubos["por_agendar"]


def test_el_rechazado_sin_cita_vigente_tiene_bandeja_propia(cola, db_session):
    """Ampliacion 2026-09-17: el predicado es sobre la FASE, no sobre si hay
    una cita `attended` puntual.

    Antes de la ampliacion, este proceso -fase 02 rechazada pero SIN cita
    vigente en absoluto, p.ej. porque se cancelo la `attended` que dejo el
    rechazo (D6)- no encajaba en el predicado viejo (exigia `attended` a
    secas) y, si tenia docs y encuesta como cualquier proceso de primera vez,
    se colaba de vuelta en «Por agendar» mezclando dos historias distintas
    bajo el mismo contador.
    """
    cubos = _cubos(db_session, {cola["prog"].id})
    pid = cola["rech_sin_cita"].id

    assert pid in cubos["rechazados"], (
        "el rechazado SIN cita vigente no aparece en «Fase 02 rechazada»: la "
        "fase tiene que mandar, no si hay una cita puntual")
    assert pid not in cubos["por_agendar"], (
        "el rechazado SIN cita se colo en «Por agendar»: deja de ser 'solo "
        "primera vez'")
    for otro in ("bloqueados", "reagendar", "sin_encuesta"):
        assert pid not in cubos[otro], "tambien sale en %s" % otro
    # Positiva de control: quien SI es de primera vez sigue en su cubo.
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


def test_la_cola_pinta_el_cubo_de_fase_02_rechazada(cola, client_as):
    """D5 llega hasta la PANTALLA, que es donde el encargado lo necesita.

    El service puede tener el cubo y la cola no pintarlo: son dos capas, y la
    unica que le sirve al encargado es la segunda. El rotulo es «Fase 02
    rechazada» desde 2026-09-17 (antes «Cotejo rechazado»).
    """
    resp = client_as(cola["off"]).get(URL + "?date=" + _D.isoformat())
    assert resp.status_code == 200
    html = resp.text

    assert "Fase 02 rechazada" in html, "falta el cubo de D5 en la cola"
    assert "Cotejo rechazado" not in html, "se quedo el rotulo viejo"
    assert ('appt-rejected-%d"' % cola["rechazado"].id) in html
    # El que espera dictamen NO tiene fila: no es trabajo de agenda.
    assert ('appt-rejected-%d"' % cola["dictamen"].id) not in html


def test_el_orden_de_los_cubos_en_pantalla(cola, client_as):
    """Orden fijado 2026-09-17: Por agendar, Fase 02 rechazada, Requieren que
    les agendes, Reagendar, Sin encuesta.

    Los cinco rotulos aparecen UNA sola vez cada uno como titulo de seccion (el
    resto de sus menciones en el HTML vive en comentarios Jinja, que no llegan
    al render), asi que comparar sus posiciones en el texto basta.
    """
    resp = client_as(cola["off"]).get(URL + "?date=" + _D.isoformat())
    assert resp.status_code == 200
    html = resp.text

    i_agendar = html.index("Por agendar")
    i_rechazada = html.index("Fase 02 rechazada")
    i_bloqueados = html.index("Requieren que les agendes")
    i_reagendar = html.index("Reagendar")
    i_sin_encuesta = html.index("Sin encuesta")

    assert i_agendar < i_rechazada < i_bloqueados < i_reagendar < i_sin_encuesta, (
        "el orden de los cubos en pantalla no es el fijado: %r"
        % [i_agendar, i_rechazada, i_bloqueados, i_reagendar, i_sin_encuesta])


def _fila(html, anchor):
    """Recorta el `<a ...>...</a>` de UNA fila de la cola, por su ancla de id.

    Aislar la fila (y no buscar en el HTML entero) es lo que evita que la
    ausencia de `data-tt-drag` en ESTA fila se confunda con la de cualquier
    otra fila del mismo cubo.
    """
    inicio = html.index('id="%s"' % anchor)
    fin = html.index("</a>", inicio)
    return html[inicio:fin]


def test_el_rechazado_sin_encuesta_no_se_arrastra_pero_abre_ficha(cola, client_as):
    """El caso real de dev (proceso #39): rechazado + `attended` + SIN
    `SurveyReview`. Arrastrarlo revienta en `SurveyNotSubmitted` -un error que
    no explica nada en el contexto de "nada mas le rechazaron la fase"-, asi
    que la fila pierde el arrastre y avisa con la pildora, pero conserva la
    navegacion: se puede seguir viendo el motivo y dando seguimiento.
    """
    resp = client_as(cola["off"]).get(URL + "?date=" + _D.isoformat())
    assert resp.status_code == 200
    pid = cola["rech_sin_encuesta"].id
    fila = _fila(resp.text, "appt-rejected-%d" % pid)

    assert "data-tt-drag" not in fila, "sigue siendo arrastrable sin encuesta"
    assert "Falta encuesta" in fila
    # Sigue abriendo la ficha: `appt_nav` no depende de `sin_encuesta`.
    assert "hx-get=" in fila and ("selected=" + str(pid)) in fila


def test_el_rechazado_con_encuesta_se_arrastra_y_muestra_el_motivo(cola, db_session,
                                                                    client_as):
    """El control positivo de la prueba anterior (arrastrable, como siempre)
    MAS el motivo del rechazo, que tiene que verse sin abrir la ficha."""
    from itcj2.apps.titulatec.models import ProcessPhase
    from itcj2.apps.titulatec.services.phase_service import PhaseService

    pid = cola["rech_con_encuesta"].id
    fase = (db_session.query(ProcessPhase)
            .filter_by(process_id=pid, phase_number=PhaseService.PHASE_COTEJO)
            .first())
    fase.rejection_reason = "Falta la firma del padrino en el acta"
    db_session.flush()

    resp = client_as(cola["off"]).get(URL + "?date=" + _D.isoformat())
    assert resp.status_code == 200
    fila = _fila(resp.text, "appt-rejected-%d" % pid)

    assert ('data-tt-drag="%d"' % pid) in fila
    assert "Falta encuesta" not in fila
    assert "Falta la firma del padrino en el acta" in fila


def test_el_badge_por_atender_no_cuenta_al_rechazado_sin_encuesta(cola, client_as):
    """«Por atender» es lo que el encargado puede resolver HOY. El rechazado sin
    encuesta no se puede agendar (`SurveyNotSubmitted`), igual que el cubo «Sin
    encuesta», que tampoco suma.

    Del fixture: por agendar 1 + bloqueados 1 + reagendar 3 (ausente, ambos,
    rechazado-ausente) + rechazados CON encuesta 3 (rechazado, sin cita, con
    encuesta) = 8. Si contara al de #39 (sin encuesta) diria 9.
    """
    resp = client_as(cola["off"]).get(URL + "?date=" + _D.isoformat())
    assert resp.status_code == 200

    assert ", 8 por atender" in resp.text, (
        "el badge «por atender» no descuenta al rechazado sin encuesta")


def test_selected_de_un_rechazado_sin_cita_abre_la_ficha(cola, db_session, client_as):
    """`_shell_ctx` suma los rechazados a `visibles` a mano: quien de ellos no
    tiene cita vigente no entra por `agenda_process_ids`, asi que sin esa union
    `?selected=` lo descartaria y el cubo se veria pero no se podria abrir a
    nadie de el — justo lo que el cubo existe para permitir.
    """
    from itcj2.core.models.user import User

    proc = cola["rech_sin_cita"]
    student = db_session.get(User, proc.student_id)

    resp = client_as(cola["off"]).get(
        URL + "?v=atender&date=" + _D.isoformat() + "&selected=" + str(proc.id))

    assert resp.status_code == 200
    assert 'id="appt-subject"' in resp.text
    assert student.control_number in resp.text
    # Sin cita en absoluto: la ficha lo dice, no lo esconde.
    assert "Sin cita todavía" in resp.text


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
