"""D12 contra D10: cancelar libera la franja, no presentarse NO la libera.

Los dos tests viven en el mismo archivo **a propósito**: es una asimetría
deliberada y se entiende mejor junta. Cancelar a tiempo es un aviso y el lugar
vuelve al pozo; no presentarse ya consumió la franja («si no se presentó es que
ya pasó»). Lo implementa `SlotService._ESTADOS_QUE_LIBERAN`, donde está
`cancelled` y NO está `no_show`.

Aparte, lo que la capa del alumno aporta sobre `AppointmentService.cancel`
—la ventana de 2 h (D8) y que la cita sea suya—, que es lo ÚNICO que
`SelfBookingService.cancel` tiene de propio: todo lo demás lo delega (D13).
"""
from datetime import time, timedelta

import pytest

import itcj2.apps.titulatec.services.self_booking_service as sb_mod
from itcj2.apps.titulatec.services import appointment_errors as err
from itcj2.apps.titulatec.services.appointment_service import AppointmentService
from itcj2.apps.titulatec.services.self_booking_service import SelfBookingService
from itcj2.apps.titulatec.services.slot_service import SlotService


@pytest.fixture()
def esc(db_session, agenda_slots, make_survey_review):
    """`p1` sentado a las 09:00 en la única franja de esa hora (capacidad 1).

    `p2` lleva su encuesta enviada para poder medir lo que de verdad importa:
    que la franja quede **tomable por otro**, no solo que se pinte libre.
    """
    make_survey_review(agenda_slots["p1"])
    make_survey_review(agenda_slots["p2"])
    cita = AppointmentService.create(
        db_session, agenda_slots["p1"].id, window_id=agenda_slots["w"].id,
        slot_start=time(9, 0), created_by_id=agenda_slots["off"].id)
    salida = dict(agenda_slots)
    salida["cita"] = cita
    return salida


# =========================================================================
# La asimetría
# =========================================================================
def test_cancelar_libera_la_franja_para_otro_alumno(db_session, esc):
    """D12: canceló a tiempo, el lugar vuelve al pozo."""
    assert time(9, 0) not in SlotService.free_slots(db_session, esc["w"])

    SelfBookingService.cancel(db_session, esc["cita"], esc["p1"].student_id,
                              "Me salió trabajo")

    assert time(9, 0) in SlotService.free_slots(db_session, esc["w"])
    # Y se toma de verdad: «pintarse libre» y «poder sentarse» son dos cosas.
    otra = AppointmentService.create(db_session, esc["p2"].id, window_id=esc["w"].id,
                                     slot_start=time(9, 0), created_by_id=esc["off"].id)
    assert otra.scheduled_at.time() == time(9, 0)


def test_no_presentarse_no_libera_la_franja(db_session, esc):
    """D10, y el defecto de §0 de la spec: la franja del `no_show` se quedó
    consumida. `occupancy` filtra por ESTADO, nunca por vigencia."""
    AppointmentService.mark_no_show(db_session, esc["cita"], esc["off"].id)

    assert time(9, 0) not in SlotService.free_slots(db_session, esc["w"])
    with pytest.raises(err.SlotFull):
        AppointmentService.create(db_session, esc["p2"].id, window_id=esc["w"].id,
                                  slot_start=time(9, 0), created_by_id=esc["off"].id)


# =========================================================================
# Lo ÚNICO que aporta la capa del alumno (D13)
# =========================================================================
class TestLoQueAportaLaCapaDelAlumno:
    """`SelfBookingService.cancel` **envuelve** a `AppointmentService.cancel`.
    Si estas reglas se colaran a la capa compartida se le aplicarían también al
    encargado, que no tiene ventana de tiempo."""

    def test_el_alumno_no_cancela_faltando_menos_de_dos_horas(
            self, db_session, esc, monkeypatch):
        monkeypatch.setattr(sb_mod, "db_now",
                            lambda: esc["cita"].scheduled_at - timedelta(minutes=30))

        with pytest.raises(err.CancelTooLate):
            SelfBookingService.cancel(db_session, esc["cita"], esc["p1"].student_id)

        assert esc["cita"].status == "scheduled"
        assert esc["cita"].is_current is True

    def test_el_alumno_sí_cancela_faltando_mas_de_dos_horas(
            self, db_session, esc, monkeypatch):
        monkeypatch.setattr(sb_mod, "db_now",
                            lambda: esc["cita"].scheduled_at - timedelta(hours=5))

        SelfBookingService.cancel(db_session, esc["cita"], esc["p1"].student_id)

        assert esc["cita"].status == "cancelled"
        assert esc["cita"].cancelled_by_id == esc["p1"].student_id

    def test_el_encargado_no_tiene_ventana_de_tiempo(self, db_session, esc, monkeypatch):
        """La misma hora en la que el alumno ya no puede: el encargado sí."""
        monkeypatch.setattr(sb_mod, "db_now",
                            lambda: esc["cita"].scheduled_at - timedelta(minutes=30))

        AppointmentService.cancel(db_session, esc["cita"], esc["off"].id, "Sin luz")

        assert esc["cita"].status == "cancelled"

    def test_no_puede_cancelar_la_cita_de_otro(self, db_session, esc):
        """Defensa en profundidad: la ruta resuelve el proceso del usuario
        autenticado, pero el service no confía en eso."""
        with pytest.raises(err.NotYours):
            SelfBookingService.cancel(db_session, esc["cita"], esc["p2"].student_id)

        assert esc["cita"].status == "scheduled"
