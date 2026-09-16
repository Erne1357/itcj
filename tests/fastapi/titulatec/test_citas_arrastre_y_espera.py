"""Arrastrar un alumno a un lugar libre, y «Atender» como destino propio.

Dos añadidos del 2026-09-03, y sus dos invariantes:

1. **El arrastre es un AÑADIDO, nunca el único camino.** El arrastre nativo del
   navegador no existe en táctil y no se puede hacer con teclado, así que todo
   lo que se pueda arrastrar tiene que poder hacerse también pulsando. Este
   archivo lo comprueba en el markup: si alguien quita el camino de clic
   «porque ya se arrastra», sale en rojo.

2. **«Atender» sin alumno es una pantalla de verdad.** Antes esa combinación
   caía de vuelta a la Agenda, así que la pestaña era un destino falso: solo se
   llegaba a ella eligiendo a alguien primero, y al volver no había forma de
   saber por quién ibas.
"""
from datetime import date, datetime
from pathlib import Path

import pytest

import itcj2.apps.titulatec as _tt_pkg

TEMPLATES = Path(_tt_pkg.__file__).resolve().parent / "templates" / "titulatec"
JS = Path(_tt_pkg.__file__).resolve().parent / "static" / "js" / "admin" / "appointments.js"
URL = "/titulatec/admin/appointments"

_D = date(2029, 5, 7)


@pytest.fixture()
def dia_con_citas(seed_phase_defs, seed_document_types, make_program, make_cohort,
                  make_review_day, make_officer, make_student, make_process,
                  make_document, make_review_window, make_appointment,
                  make_survey_review):
    """Un día con espacio, dos citas y un pendiente en la cola.

    "pend" lleva la encuesta de egresados ya enviada (Tarea 4, D2): sin
    solicitud, `AppointmentService.list_pending_processes` ya no lo cuenta
    como "Por agendar" y estos tests de arrastre — que necesitan una fila
    arrastrable en la cola — dejarian de tener con que medir.
    """
    def _build():
        seed_phase_defs()
        seed_document_types()
        prog = make_program("Ingenieria de Arrastre")
        cohort = make_cohort()
        dia = make_review_day(cohort, day=_D)
        officer, pos = make_officer([prog])
        make_review_window(dia, officer, start="09:00", end="12:00", slot=30,
                           cap=1, position=pos)
        procs = {}
        for key, hora in (("a", 9), ("b", 10), ("pend", None)):
            st = make_student(last_name="ARRASTRE" + key.upper())
            proc = make_process(st, cohort=cohort, program=prog, current_phase=2)
            for code in ("birth_certificate", "high_school_cert", "curp"):
                make_document(proc, type_code=code, review_status="approved")
            if hora is not None:
                make_appointment(proc, when=datetime.combine(
                    _D, datetime.min.time()).replace(hour=hora))
            else:
                make_survey_review(proc)
            procs[key] = proc
        return {"officer": officer, "cohort": cohort, "dia": dia, "procs": procs}
    return _build


# ---------------------------------------------------------------------------
# 1. El arrastre nunca es el unico camino
# ---------------------------------------------------------------------------
def test_todo_lo_arrastrable_tambien_se_puede_pulsar(dia_con_citas, client_as):
    """Cada `[data-tt-drag]` es a la vez un enlace o un boton.

    Si alguien convirtiera una fila en «solo arrastrable», dejaria fuera a quien
    usa el teclado, a quien usa lector de pantalla y a cualquiera en un movil.
    """
    import re
    esc = dia_con_citas()
    html = client_as(esc["officer"]).get(URL + "?date=" + _D.isoformat()).text

    etiquetas = re.findall(r"<(\w+)[^>]*\bdata-tt-drag=", html)
    assert etiquetas, "ninguna fila es arrastrable: se perdio la funcion"
    assert all(t in ("a", "button") for t in etiquetas), (
        "hay elementos arrastrables que NO son enlace ni boton, o sea que solo "
        "se pueden usar con raton: " + ", ".join(sorted(set(etiquetas))))


def test_los_lugares_libres_son_destino_de_arrastre(dia_con_citas, client_as):
    """Y lo son SIEMPRE, no solo cuando hay algo «armado»: si el hueco solo
    aceptara al soltar en modo mover, arrastrar desde la cola no funcionaria."""
    esc = dia_con_citas()
    html = client_as(esc["officer"]).get(URL + "?date=" + _D.isoformat()).text

    assert 'data-tt-drop=' in html, "los lugares libres no aceptan que suelten nada"
    assert 'data-tt-drop-url=' in html
    assert "@PID@" in html, (
        "la URL del destino tiene que traer el hueco del alumno: el lugar no "
        "sabe a quien va a recibir hasta que alguien lo suelta")


def test_el_camino_de_clic_sigue_existiendo(dia_con_citas, client_as):
    """«Mover de franja» en la ficha es el camino accesible equivalente."""
    esc = dia_con_citas()
    html = client_as(esc["officer"]).get(
        URL + "?v=atender&date=" + _D.isoformat()
        + "&selected=" + str(esc["procs"]["a"].id)).text
    assert "Mover de franja" in html


def test_el_arrastre_reusa_el_mismo_endpoint_que_el_clic():
    """Estructural: el JS no puede tener su propia ruta.

    Con dos caminos distintos hacia dos endpoints distintos, uno de los dos
    acabaria sin la validacion de cupo.
    """
    src = JS.read_text(encoding="utf-8")
    assert "data-tt-drop-url" in src, "el arrastre no lee la URL del destino"
    assert "htmx.ajax" in src, "el arrastre no pasa por htmx, asi que no swappea el shell"
    assert "'#appt-shell'" in src or '"#appt-shell"' in src


def test_el_resaltado_del_destino_no_se_quita_en_dragleave():
    """`dragenter`/`dragleave` tambien se disparan al cruzar entre los HIJOS del
    destino. Quitar la clase en cada `dragleave` la hacia parpadear y, medido en
    Chromium, al soltar `.is-drop-over` estaba en CERO elementos: el usuario
    arrastraba a ciegas."""
    src = JS.read_text(encoding="utf-8")
    assert "dragleave" not in src.split("// ————")[-1] or "_marcar" in src, (
        "el resaltado tiene que llevarse en una variable, no quitandolo en dragleave")
    assert "_marcar" in src


# ---------------------------------------------------------------------------
# 2. «Atender» es un destino propio
# ---------------------------------------------------------------------------
def test_atender_sin_alumno_no_cae_a_la_agenda(dia_con_citas, client_as):
    esc = dia_con_citas()
    html = client_as(esc["officer"]).get(URL + "?v=atender&date=" + _D.isoformat()).text

    assert 'id="appt-attend"' in html, "Atender sin alumno cayo de vuelta a la Agenda"
    assert 'id="appt-agenda"' not in html


def test_atender_sin_alumno_dice_por_quien_vas(dia_con_citas, client_as):
    """En una manana de treinta alumnos, lo que se necesita al volver a esta
    pantalla es «por quien iba»."""
    esc = dia_con_citas()
    html = client_as(esc["officer"]).get(URL + "?v=atender&date=" + _D.isoformat()).text

    assert "El que sigue" in html
    assert "Citas del día" in html


def test_atender_sin_alumno_lista_el_dia_acotado(dia_con_citas, client_as,
                                                 make_program, make_student,
                                                 make_process, make_appointment):
    """La sala de espera es una consulta de listado mas: tiene que acotarse por
    carrera como todas las demas."""
    esc = dia_con_citas()
    ajena = make_program("Carrera Ajena")
    otro = make_process(make_student(last_name="AJENO"), cohort=esc["cohort"],
                        program=ajena, current_phase=2)
    make_appointment(otro, when=datetime.combine(_D, datetime.min.time()).replace(hour=11))

    html = client_as(esc["officer"]).get(URL + "?v=atender&date=" + _D.isoformat()).text
    assert "AJENO" not in html, "la sala de espera enseña alumnos de otra carrera"


def test_el_segmento_marca_atender_como_activo(dia_con_citas, client_as):
    """Sin esto la pestaña se pulsa y no parece que haya pasado nada."""
    import re
    esc = dia_con_citas()
    html = client_as(esc["officer"]).get(URL + "?v=atender&date=" + _D.isoformat()).text
    activos = re.findall(r'class="seg is-active"[^>]*>\s*(?:<[^>]+>\s*)*([A-Za-zÁÉÍÓÚáéíóú]+)', html)
    assert activos and activos[0] == "Atender", f"activo: {activos}"


def test_terminado_el_dia_lo_dice(dia_con_citas, client_as, db_session):
    """Regla del pico y el final: cerrar el día tiene que sentirse cerrado."""
    from itcj2.apps.titulatec.services.appointment_service import AppointmentService
    esc = dia_con_citas()
    for key in ("a", "b"):
        ap = AppointmentService.get_for_process(db_session, esc["procs"][key].id)
        AppointmentService.start(db_session, ap, esc["officer"].id)
        AppointmentService.mark_attended(db_session, ap, esc["officer"].id)

    html = client_as(esc["officer"]).get(URL + "?v=atender&date=" + _D.isoformat()).text
    assert "Terminaste el día" in html


# ---------------------------------------------------------------------------
# 3. Re-sentar desde el tablero a quien ya se atendio (D5)
# ---------------------------------------------------------------------------
# `move` elegia entre `create` y `reschedule` con `appt is None` como proxy de
# «no hay cita activa». Con el historial de intentos el proxy se rompe: una cita
# `attended` SIGUE siendo la vigente, asi que caia en `reschedule` ->
# `InvalidTransition` (terminal), y el encargado NO podia volver a sentar a
# quien atendio y le faltaron papeles — que es literalmente D5, la regla que el
# usuario pidio. El criterio correcto es el complemento exacto de la guarda de
# `create`: hay cita VIVA que mover, o se abre un intento nuevo.


@pytest.fixture()
def alumno_atendido(seed_phase_defs, seed_document_types, make_program, make_cohort,
                    make_review_day, make_officer, make_student, make_process,
                    make_document, make_review_window, make_appointment,
                    make_survey_review):
    """Un alumno con cita `attended` a las 09:00 y la rejilla con lugares libres.

    Lleva la encuesta enviada a proposito: `AppointmentService.create` exige la
    solicitud ANTES que cualquier otra guarda (D2), asi que sin ella este test
    fallaria por `SurveyNotSubmitted` y no por lo que viene a medir.
    """
    # `OFFICER_PERMS` es el set de BANDEJA (solo lectura): el resto de este
    # archivo hace GETs de markup, asi que nunca necesito un permiso de
    # escritura. `move` exige `appointment.api.reschedule` y sin el la ruta
    # contesta 403 — un rojo que NO habla de D5 y que tapa lo que se mide.
    from tests.fastapi.titulatec.conftest import OFFICER_PERMS
    _PERMS = OFFICER_PERMS + ("titulatec.appointment.api.reschedule",)

    def _build(status="attended"):
        seed_phase_defs()
        seed_document_types()
        prog = make_program("Ingenieria de Resentado")
        cohort = make_cohort()
        dia = make_review_day(cohort, day=_D)
        officer, pos = make_officer([prog], perm_codes=_PERMS)
        ventana = make_review_window(dia, officer, start="09:00", end="12:00",
                                     slot=30, cap=1, position=pos)
        st = make_student(last_name="RESENTADO")
        proc = make_process(st, cohort=cohort, program=prog, current_phase=2)
        for code in ("birth_certificate", "high_school_cert", "curp"):
            make_document(proc, type_code=code, review_status="approved")
        make_survey_review(proc)
        appt = make_appointment(proc, when=datetime.combine(
            _D, datetime.min.time()).replace(hour=9), status=status)
        return {"officer": officer, "proc": proc, "w": ventana, "appt": appt}
    return _build


def _intentos(db_session, proc):
    from itcj2.apps.titulatec.models import ReviewAppointment
    db_session.expire_all()
    return (db_session.query(ReviewAppointment)
            .filter_by(process_id=proc.id)
            .order_by(ReviewAppointment.attempt_no).all())


def test_el_encargado_puede_resentar_a_quien_ya_atendio(alumno_atendido, client_as,
                                                        db_session):
    """D5: atendido pero con faltantes -> se le abre un INTENTO NUEVO.

    Y la evidencia del cotejo que si ocurrio no se toca: la fila `attended`
    conserva su estado y su franja; solo deja de ser la vigente.
    """
    esc = alumno_atendido()
    resp = client_as(esc["officer"]).post(
        URL + "/%d/move?window_id=%d&slot=10:00" % (esc["proc"].id, esc["w"].id))

    assert resp.status_code == 200, resp.text[:300]
    assert not resp.headers.get("X-Tt-Error"), resp.headers.get("X-Tt-Error")

    filas = _intentos(db_session, esc["proc"])
    assert len(filas) == 2, "no se abrio un intento nuevo: %s" % [f.status for f in filas]

    vieja, nueva = filas
    assert vieja.status == "attended", "se borro la evidencia de que el cotejo ocurrio"
    assert vieja.is_current is False
    assert vieja.scheduled_at.hour == 9, "la atendida no conserva su franja"

    assert nueva.attempt_no == 2
    assert nueva.is_current is True
    assert nueva.status == "scheduled"
    assert nueva.scheduled_at.hour == 10


def test_mover_una_cita_VIVA_sigue_siendo_una_reagenda(alumno_atendido, client_as,
                                                       db_session):
    """La asercion positiva que acompana a la de arriba.

    Sin ella, mandar TODO a `create` pasaria el test anterior y romperia en
    silencio el camino normal: una cita viva tiene que SUPERARSE
    (`superseded`, que libera su franja), no conservar su estado como hace la
    atendida. Es la diferencia entre mover a alguien y darle una cita mas.
    """
    esc = alumno_atendido(status="scheduled")
    resp = client_as(esc["officer"]).post(
        URL + "/%d/move?window_id=%d&slot=10:00" % (esc["proc"].id, esc["w"].id))

    assert resp.status_code == 200, resp.text[:300]

    filas = _intentos(db_session, esc["proc"])
    assert len(filas) == 2
    vieja, nueva = filas
    assert vieja.status == "superseded", (
        "mover una cita viva tiene que superarla, no dejarla como estaba")
    assert vieja.is_current is False
    assert nueva.is_current is True and nueva.scheduled_at.hour == 10
