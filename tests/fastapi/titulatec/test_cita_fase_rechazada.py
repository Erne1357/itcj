"""«Mi cita» del alumno cuando la fase 02 quedó con observaciones (Tarea B2).

Antes: una `ReviewAppointment` `attended` con la fase 02 `rejected` seguía
mostrando la píldora verde «Cotejo realizado», y si Servicios Escolares
todavía no publicaba ningún espacio, la pantalla no decía nada de qué hacer.
El hueco era puramente de PANTALLA: `SelfBookingService.eligibility` (regla 2)
ya deja agendar de nuevo con la fase 02 rechazada -el corte real es la fase
APROBADA, no `attended`, ver `phase2_student_self_booking.md`-, así que
`agenda.can_book` es `True` y ni el selector (pide `agenda.dias`) ni la cara 4
(pide `agenda.message`, y `message_for(None)` es `None`) tenían nada que
pintar.

Reusa el andamiaje de `test_self_booking_routes.py` (oferta con ventana
`bookable`) y `test_cita_checklist.py` (alumno en fase 2 con `client_as`).
"""
from __future__ import annotations

import pytest

import itcj2.models  # noqa: F401

URL = "/titulatec/student/cita"


def _rechazar_fase_2(db_session, process, motivo):
    """Deja la fase 02 en `rejected` con `motivo`, el mismo dato que escribe
    `PhaseService.reject_phase`. Se manipula el `ProcessPhase` directo -y no el
    service- porque aquí solo importa el dato que lee `_cita_card_ctx`, no el
    resto de los efectos del dictamen (notificación, `current_phase`, etc.)."""
    from itcj2.apps.titulatec.models import ProcessPhase

    ph2 = (db_session.query(ProcessPhase)
           .filter_by(process_id=process.id, phase_number=2).one())
    ph2.status = "rejected"
    ph2.rejection_reason = motivo
    db_session.flush()
    return ph2


@pytest.fixture()
def esc(db_session, seed_phase_defs, make_student, make_cohort, make_process,
       make_survey_review, make_appointment):
    """Alumno en fase 2, cotejo `attended`, encuesta ya enviada.

    La encuesta hace falta para que `eligibility` no se pare antes en la regla
    3 (`sin_encuesta`): sin ella, cualquier escenario de este archivo vería
    esa frase en vez de la de "quedó con observaciones".

    La fase NO se marca rechazada aquí: no todos los tests de este archivo la
    quieren así (el de regresión la deja intacta).
    """
    seed_phase_defs()
    cohort = make_cohort()
    student = make_student()
    process = make_process(student, cohort=cohort, current_phase=2)
    make_survey_review(process)
    appt = make_appointment(process, status="attended")
    return {"student": student, "cohort": cohort, "process": process, "appt": appt}


class TestFaseRechazadaSinEspaciosPublicados:
    def test_aviso_motivo_y_te_agendara_sin_cotejo_realizado(self, db_session, esc, client_as):
        """`agenda.can_book` es `True` (nadie la bloquea) y `agenda.dias` está
        vacío (nadie publicó nada): el hueco que este archivo cierra."""
        _rechazar_fase_2(db_session, esc["process"], "Le faltó el acta certificada.")

        resp = client_as(esc["student"]).get(URL, follow_redirects=False)

        assert resp.status_code == 200, resp.text[:300]
        assert "quedó con observaciones" in resp.text
        assert "Le faltó el acta certificada." in resp.text
        assert "Cotejo con observaciones" in resp.text
        assert "Cotejo realizado" not in resp.text
        assert "te agendará una nueva cita" in resp.text
        assert 'name="slot"' not in resp.text, "sin espacios publicados no hay selector"

    def test_sin_motivo_el_aviso_no_inventa_texto(self, db_session, esc, client_as):
        """`rejection_reason` puede venir vacío/None; el aviso no debe fabricar
        un motivo que nadie escribió."""
        _rechazar_fase_2(db_session, esc["process"], None)

        resp = client_as(esc["student"]).get(URL, follow_redirects=False)

        assert resp.status_code == 200, resp.text[:300]
        assert "quedó con observaciones" in resp.text
        assert "Necesitas otra cita de cotejo" in resp.text


class TestFaseRechazadaConVentanaBookable:
    def test_el_selector_sale_si_hay_espacio_publicado(
            self, db_session, esc, client_as, make_program, make_officer,
            make_review_day, make_review_window):
        """Con una ventana `bookable` de SU carrera, la cara 2 (selector) gana
        a la tarjeta "te agendará" -son mutuamente excluyentes por
        `agenda.dias`-, y el aviso de arriba sigue como recordatorio."""
        _rechazar_fase_2(db_session, esc["process"], "Faltaron fotografías.")
        # El proceso necesita CARRERA para que la ventana del encargado le
        # llegue en la oferta (`_owners_serving`, D3): sin ella `offer()`
        # nunca la encuentra y este test probaría lo mismo que el de arriba,
        # por accidente.
        prog = make_program("Ingenieria de Cotejo Rechazado")
        esc["process"].program_id = prog.id
        officer, pos = make_officer([prog])
        dia = make_review_day(esc["cohort"])
        ventana = make_review_window(dia, officer, position=pos)
        ventana.visibility = "bookable"
        db_session.flush()

        resp = client_as(esc["student"]).get(URL, follow_redirects=False)

        assert resp.status_code == 200, resp.text[:300]
        assert 'name="slot"' in resp.text, "con espacio publicado el selector tiene que salir"
        assert "quedó con observaciones" in resp.text, (
            "el aviso no desaparece: sigue como recordatorio del motivo")
        assert "te agendará una nueva cita" not in resp.text, (
            "con selector presente no hace falta la tarjeta de espera")


class TestFaseNoRechazada:
    def test_attended_sin_rechazo_sigue_diciendo_cotejo_realizado(self, esc, client_as):
        """Regresión: sin rechazo, el comportamiento de siempre no cambia."""
        resp = client_as(esc["student"]).get(URL, follow_redirects=False)

        assert resp.status_code == 200, resp.text[:300]
        assert "Cotejo realizado" in resp.text
        assert "quedó con observaciones" not in resp.text
        assert "Cotejo con observaciones" not in resp.text
