"""La tarjeta «todavía no tienes cita» dice lo que el alumno PUEDE hacer.

EL DEFECTO, reportado con una captura (2026-09-18). La pantalla enseñaba, de
arriba abajo y a la vez:

    [Pendiente de agenda]
    Servicios Escolares agendará tu cita de cotejo. Te avisaremos cuando
    tenga fecha.
    ---
    AGENDAR MI CITA — Elige el día y toca la hora que te acomode.
    [09:00] [09:30] [10:00] ...
    ---
    ATENCIÓN SIN CITA — Estos encargados atienden por orden de llegada.

Es decir: le prometía que se la iban a asignar mientras tenía el selector de
horas delante. La rama `not appt` de `cita_card.html` era UNA sola y venía de
antes del auto-agendado, cuando la única via era que Servicios Escolares
asignara la fecha.

Ahora son tres caras, decididas por lo mismo que decide qué secciones se pintan
debajo (`agenda.can_book`/`agenda.dias` y `agenda.can_walkin`/`agenda.walkins`),
para que la tarjeta y el cuerpo de la pantalla no puedan volver a contradecirse.

Estos tests se escriben por las TRES caras y por la contradicción: cada caso
positivo viene con la negación del texto que sobra. Sin esa negación, la copia
vieja seguiria pasando.

Andamiaje reusado de `test_cita_fase_rechazada.py` (alumno en fase 2 con
encuesta enviada) y `test_self_booking_routes.py` (ventana publicada).
"""
from __future__ import annotations

import pytest

import itcj2.models  # noqa: F401

URL = "/titulatec/student/cita"

ASIGNA = "Servicios Escolares agendará tu cita"
TE_TOCA = "Te toca agendar"
SIN_CITA = "Atención sin cita"
PENDIENTE = "Pendiente de agenda"


@pytest.fixture()
def esc(db_session, seed_phase_defs, make_student, make_cohort, make_process,
        make_survey_review, make_program):
    """Alumno en fase 2, SIN cita, con la encuesta ya enviada y con carrera.

    La encuesta hace falta o `eligibility` se para en la regla 3 y `can_book`
    sería `False` por un motivo ajeno a lo que aquí se prueba. La carrera hace
    falta o `offer()` nunca encuentra la ventana del encargado (`_owners_serving`).
    """
    seed_phase_defs()
    cohort = make_cohort()
    student = make_student()
    process = make_process(student, cohort=cohort, current_phase=2)
    prog = make_program("Ingenieria de la Tarjeta Sin Cita")
    process.program_id = prog.id
    make_survey_review(process)
    db_session.flush()
    return {"student": student, "cohort": cohort, "process": process, "program": prog}


def _publicar(db_session, esc, make_officer, make_review_day, make_review_window,
              visibility):
    officer, pos = make_officer([esc["program"]])
    dia = make_review_day(esc["cohort"])
    ventana = make_review_window(dia, officer, position=pos)
    ventana.visibility = visibility
    db_session.flush()
    return ventana


# ---------------------------------------------------------------------------
# Cara 1: puede agendar
# ---------------------------------------------------------------------------
def test_con_espacio_bookable_la_tarjeta_dice_que_le_toca_a_el(
        db_session, esc, client_as, make_officer, make_review_day, make_review_window):
    _publicar(db_session, esc, make_officer, make_review_day, make_review_window,
              "bookable")

    cuerpo = client_as(esc["student"]).get(URL, follow_redirects=False).text

    assert TE_TOCA in cuerpo
    assert "Agéndala aquí abajo" in cuerpo
    # LA contradicción del reporte: con el selector en pantalla, la tarjeta no
    # puede seguir prometiendo que se la asignan.
    assert ASIGNA not in cuerpo
    assert PENDIENTE not in cuerpo
    # Y el selector sí está: si no, este test pasaría por la razón equivocada.
    assert 'name="slot"' in cuerpo


# ---------------------------------------------------------------------------
# Cara 2: solo atención sin cita
# ---------------------------------------------------------------------------
def test_con_solo_walkin_la_tarjeta_dice_que_no_hace_falta_agendar(
        db_session, esc, client_as, make_officer, make_review_day, make_review_window):
    _publicar(db_session, esc, make_officer, make_review_day, make_review_window,
              "walkin")

    cuerpo = client_as(esc["student"]).get(URL, follow_redirects=False).text

    assert SIN_CITA in cuerpo
    assert "No necesitas agendar" in cuerpo
    assert ASIGNA not in cuerpo
    assert TE_TOCA not in cuerpo
    # D2: una ventana `walkin` es anuncio, no agenda — no publica franjas.
    assert 'name="slot"' not in cuerpo


# ---------------------------------------------------------------------------
# Cara 3: las dos vías a la vez (el caso EXACTO de la captura)
# ---------------------------------------------------------------------------
def test_con_bookable_y_walkin_la_tarjeta_ofrece_las_dos(
        db_session, esc, client_as, make_officer, make_review_day, make_review_window):
    # Dos ventanas del MISMO encargado el MISMO dia necesitan horas distintas:
    # `uq_titulatec_review_windows_day_user_start` es (dia, encargado, inicio).
    # Es exactamente como se ve en produccion: la manana agendable y la tarde
    # por orden de llegada.
    officer, pos = make_officer([esc["program"]])
    dia = make_review_day(esc["cohort"])
    v1 = make_review_window(dia, officer, position=pos, start="09:00", end="12:00")
    v1.visibility = "bookable"
    v2 = make_review_window(dia, officer, position=pos, start="12:00", end="14:00")
    v2.visibility = "walkin"
    db_session.flush()

    cuerpo = client_as(esc["student"]).get(URL, follow_redirects=False).text

    assert TE_TOCA in cuerpo, "con espacio agendable, agendar es la acción principal"
    assert "o preséntate sin cita" in cuerpo, "la segunda vía tiene que nombrarse"
    assert ASIGNA not in cuerpo


# ---------------------------------------------------------------------------
# Cara 4: sin ninguna vía, el texto de siempre SIGUE siendo el correcto
# ---------------------------------------------------------------------------
def test_sin_espacios_publicados_se_conserva_el_texto_de_siempre(esc, client_as):
    """No se cambia por cambiar: cuando de verdad nadie publicó nada, que
    Servicios Escolares asignará la fecha es lo único cierto que se puede decir."""
    cuerpo = client_as(esc["student"]).get(URL, follow_redirects=False).text

    assert PENDIENTE in cuerpo
    assert ASIGNA in cuerpo
    assert TE_TOCA not in cuerpo
    assert 'name="slot"' not in cuerpo


# ---------------------------------------------------------------------------
# Cara 5: no puede agendar por un requisito SUYO, y el motivo ya esta debajo
# ---------------------------------------------------------------------------
def test_bloqueado_por_un_requisito_la_tarjeta_no_promete_una_asignacion(
        db_session, seed_phase_defs, make_student, make_cohort, make_process,
        make_program, client_as, make_officer, make_review_day, make_review_window):
    """Visto en dev: un alumno con la encuesta sin enviar leía «Servicios
    Escolares agendará tu cita» arriba y «Primero envía la encuesta de
    egresados» abajo. Lo primero es falso —no se la van a asignar hasta que él
    cumpla— y además tapaba la causa real con una espera inventada.

    Este escenario NO llama a `make_survey_review`: esa ausencia es justo lo que
    hace que `eligibility` se pare y llene `agenda.message`.
    """
    seed_phase_defs()
    cohort = make_cohort()
    student = make_student()
    process = make_process(student, cohort=cohort, current_phase=2)
    prog = make_program("Ingenieria de la Encuesta Pendiente")
    process.program_id = prog.id
    db_session.flush()
    # Con espacio publicado: sin el, este test pasaria por «no hay nada que
    # ofrecer» y no por «no puedes todavia», que es lo que se quiere probar.
    officer, pos = make_officer([prog])
    dia = make_review_day(cohort)
    ventana = make_review_window(dia, officer, position=pos)
    ventana.visibility = "bookable"
    db_session.flush()

    cuerpo = client_as(student).get(URL, follow_redirects=False).text

    assert "Todavía no tienes cita de cotejo" in cuerpo
    assert "qué falta para" in cuerpo
    assert ASIGNA not in cuerpo, "le prometió una asignación que no va a llegar"
    assert TE_TOCA not in cuerpo, "no puede agendar todavía"
    # Y el motivo real sigue a la vista, que es a donde la tarjeta manda.
    assert "encuesta de egresados" in cuerpo


# ---------------------------------------------------------------------------
# El parcial no puede depender de quién lo incluya
# ---------------------------------------------------------------------------
def test_la_tarjeta_sola_trae_su_agenda(db_session, esc):
    """`_cita_card_ctx` es lo que responden los dos POST que swappean SOLO la
    tarjeta (`/cita/confirmar` y `/cita/solicitar-cambio`). Si `agenda` solo
    viniera del panel, esos swaps caerían a la cara conservadora y la tarjeta
    volvería a mentir en cuanto alguien pulsara un botón."""
    from itcj2.apps.titulatec.pages.student import _cita_card_ctx

    ctx = _cita_card_ctx(db_session, esc["student"].id)

    assert "agenda" in ctx, "la tarjeta se quedó sin el dato que decide qué dice"
    assert set(ctx["agenda"]) >= {"can_book", "can_walkin", "dias", "walkins"}


def test_el_panel_no_calcula_la_agenda_dos_veces(db_session, esc, monkeypatch):
    """`_agenda_ctx` recorre las jornadas de la convocatoria con `offer()`. La
    tarjeta y el selector necesitan el mismo dato, así que el panel lo calcula
    UNA vez y se lo presta."""
    from itcj2.apps.titulatec.pages import student as mod

    llamadas = {"n": 0}
    original = mod._agenda_ctx

    def _contar(*a, **kw):
        llamadas["n"] += 1
        return original(*a, **kw)

    monkeypatch.setattr(mod, "_agenda_ctx", _contar)
    mod._cita_panel_ctx(db_session, esc["student"].id)

    assert llamadas["n"] == 1, f"se calculó {llamadas['n']} veces"


# ---------------------------------------------------------------------------
# La descripción de la fase 02 en el dashboard
# ---------------------------------------------------------------------------
def test_la_fase_02_no_promete_que_se_la_asignan(esc, client_as):
    """El dashboard lee un texto ESTÁTICO para las 9 fases, así que no puede
    consultar la agenda: tiene que ser una frase que valga en los tres casos.

    Antes decía «Servicios Escolares te asigna fecha, hora y lugar del cotejo»,
    que es falso en cuanto la convocatoria abre auto-agendado o atención sin
    cita.
    """
    from itcj2.apps.titulatec.pages.student import _PHASE_INFO

    desc = _PHASE_INFO["review_appointment"]["desc"]

    assert "te asigna fecha, hora y lugar" not in desc
    assert "agendas tú" in desc, "la vía del auto-agendado tiene que aparecer"
    # El cotejo no es solo lo que el alumno subió: la lista `needs` de esa misma
    # fase trae fotografías, no-adeudo de biblioteca, IMSS, e.firma y el pago.
    assert "demás requisitos" in desc
