"""`ReviewWindowService`: encoger y borrar un espacio con historial detras.

Este service **no tenia ni un test** hasta ahora (`test_review_window_model.py`
cubre los CHECK y la UNIQUE de la tabla, nunca el service), y el historial de
intentos le rompio las dos comprobaciones que justifican su existencia: las dos
contaban FILAS CRUDAS de `titulatec_review_appointments`, justo al reves que
`SlotService.occupancy`, que filtra por estado.

El predicado correcto es el de `occupancy`, y es por ESTADO, nunca por
`is_current`:

  * `cancelled` y `superseded` NO ocupan — devolvieron su lugar al pozo (D12);
  * `no_show` SI ocupa aunque ya no sea la cita vigente (D10: «si no se
    presento es que ya paso»);
  * `attended` tambien: la franja se uso de verdad.
"""
from datetime import time

import pytest

from itcj2.apps.titulatec.services import appointment_errors as err
from itcj2.apps.titulatec.services.appointment_service import AppointmentService
from itcj2.apps.titulatec.services.review_window_service import ReviewWindowService
from itcj2.apps.titulatec.services.slot_service import SlotService


def _update_igual(db, w, **cambios):
    """Re-guarda la ventana con sus mismos valores salvo lo que se pise.

    Es el caso que de verdad importa: el encargado entra a cambiar SOLO la
    ubicacion y no deberia toparse con un conflicto de cupo.
    """
    datos = {"start_time": w.start_time, "end_time": w.end_time,
             "slot_minutes": w.slot_minutes, "capacity": w.capacity,
             "location": w.location}
    datos.update(cambios)
    return ReviewWindowService.update(db, w, **datos)


class TestEncoger:
    def test_una_cancelada_no_cuenta_contra_el_cupo(self, db_session, agenda_slots):
        """El caso alcanzable que rompia la edicion entera del espacio: el
        alumno cancela su 09:00 y se re-agenda en la MISMA 09:00 —legitimo,
        D12 libero el lugar—. Quedan 2 filas en esa hora contra un cupo de 1,
        y antes eso hacia estallar cualquier `update`, aunque solo cambiaras
        la ubicacion, con un mensaje que ademas mentia al contar.
        """
        esc = agenda_slots
        ap = SlotService.assign(db_session, esc["w"].id, time(9, 0),
                                esc["p1"].id, esc["off"].id)
        AppointmentService.cancel(db_session, ap, esc["off"].id)
        SlotService.assign(db_session, esc["w"].id, time(9, 0),
                           esc["p1"].id, esc["off"].id)

        _update_igual(db_session, esc["w"], location="Edificio B")

        assert esc["w"].location == "Edificio B"

    def test_una_superada_tampoco_cuenta(self, db_session, agenda_slots):
        """Reagendar dentro de la misma ventana deja la fila vieja
        `superseded`, que ya no ocupa: su lugar lo heredo el intento nuevo."""
        esc = agenda_slots
        SlotService.assign(db_session, esc["w"].id, time(9, 0),
                           esc["p1"].id, esc["off"].id)
        SlotService.assign(db_session, esc["w"].id, time(9, 0),
                           esc["p1"].id, esc["off"].id)

        _update_igual(db_session, esc["w"], location="Edificio C")

        assert esc["w"].location == "Edificio C"

    def test_el_no_show_no_vigente_SI_sigue_contando(self, db_session, agenda_slots):
        """D10, el regresor que protege al predicado de irse al otro extremo:
        filtrar por `is_current` en vez de por estado dejaria pasar este
        encogimiento y el `no_show` de las 09:00 quedaria huerfano en silencio.
        """
        esc = agenda_slots
        primera = SlotService.assign(db_session, esc["w"].id, time(9, 0),
                                     esc["p1"].id, esc["off"].id)
        primera.status = "no_show"
        db_session.flush()
        # Intento nuevo en otra franja: la fila de las 09:00 deja de ser la
        # vigente pero conserva su estado y su lugar.
        SlotService.assign(db_session, esc["w"].id, time(9, 30),
                           esc["p1"].id, esc["off"].id)

        with pytest.raises(err.WindowShrinkConflict):
            _update_igual(db_session, esc["w"], start_time=time(9, 30))

    def test_una_cita_viva_fuera_de_la_rejilla_sigue_bloqueando(
            self, db_session, agenda_slots):
        """La comprobacion no se ablando: lo vivo se sigue defendiendo."""
        esc = agenda_slots
        SlotService.assign(db_session, esc["w"].id, time(10, 30),
                           esc["p1"].id, esc["off"].id)

        with pytest.raises(err.WindowShrinkConflict):
            _update_igual(db_session, esc["w"], end_time=time(10, 0))

    def test_sin_citas_se_edita_sin_ruido(self, db_session, agenda_slots):
        _update_igual(db_session, agenda_slots["w"], location="Edificio D")
        assert agenda_slots["w"].location == "Edificio D"


class TestBorrar:
    def test_con_citas_vivas_dice_cuantas_y_que_las_muevas(
            self, db_session, agenda_slots):
        esc = agenda_slots
        SlotService.assign(db_session, esc["w"].id, time(9, 0),
                           esc["p1"].id, esc["off"].id)

        with pytest.raises(err.WindowInUse) as exc:
            ReviewWindowService.delete(db_session, esc["w"])

        assert "1 cita" in str(exc.value)
        assert "Muévelas" in str(exc.value)

    def test_el_conteo_no_incluye_el_historial_muerto(self, db_session, agenda_slots):
        """Antes decia «2 citas» cuando en el tablero solo habia una."""
        esc = agenda_slots
        ap = SlotService.assign(db_session, esc["w"].id, time(9, 0),
                                esc["p1"].id, esc["off"].id)
        AppointmentService.cancel(db_session, ap, esc["off"].id)
        SlotService.assign(db_session, esc["w"].id, time(9, 0),
                           esc["p2"].id, esc["off"].id)

        with pytest.raises(err.WindowInUse) as exc:
            ReviewWindowService.delete(db_session, esc["w"])

        assert "1 cita" in str(exc.value)

    def test_con_solo_historial_muerto_el_mensaje_manda_a_pausar(
            self, db_session, agenda_slots):
        """No se puede borrar igual —la FK es `ON DELETE RESTRICT`, asi que
        Postgres lo rechazaria y el encargado se llevaria un 500—, pero el
        mensaje ya no le manda a mover citas que no existen.
        """
        esc = agenda_slots
        ap = SlotService.assign(db_session, esc["w"].id, time(9, 0),
                                esc["p1"].id, esc["off"].id)
        AppointmentService.cancel(db_session, ap, esc["off"].id)

        with pytest.raises(err.WindowInUse) as exc:
            ReviewWindowService.delete(db_session, esc["w"])

        mensaje = str(exc.value)
        assert "historial" in mensaje
        assert "En pausa" in mensaje
        assert "Muévelas" not in mensaje

    def test_un_espacio_limpio_si_se_borra(self, db_session, agenda_slots,
                                           make_review_window):
        from itcj2.apps.titulatec.models import ReviewWindow
        esc = agenda_slots
        otra = make_review_window(esc["dia"], esc["off"], start="11:00", end="12:00")
        wid = otra.id

        ReviewWindowService.delete(db_session, otra)

        assert db_session.get(ReviewWindow, wid) is None
