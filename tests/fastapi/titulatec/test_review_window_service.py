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
from datetime import date, time

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


class TestModoDestino:
    """Ruling 2026-09-29 (revisión de T2, arrastrada a la Tarea 4 — spec §3.2).

    Pasar de franjas a sin horario con más vivas que el cupo total es un
    conflicto de MODO, no de horario: el horario no se tocó, es el cupo TOTAL
    del modo nuevo el que no las aguanta. Antes las dos ramas —esta y «bajar
    el cupo YA estando en sin horario»— disparaban la misma excepción
    (`WindowShrinkConflict`), y su frase («quedaría fuera del horario nuevo»)
    no describía lo que de verdad pasó aquí.
    """

    def test_pasar_a_walkin_con_mas_vivas_que_el_cupo_es_conflicto_de_modo(
            self, db_session, agenda_slots):
        esc = agenda_slots            # 09:00-11:00, franjas de 30, cupo 1
        SlotService.assign(db_session, esc["w"].id, time(9, 0),
                           esc["p1"].id, esc["off"].id)
        SlotService.assign(db_session, esc["w"].id, time(9, 30),
                           esc["p2"].id, esc["off"].id)

        with pytest.raises(err.WindowModeConflict) as exc:
            _update_igual(db_session, esc["w"], visibility="walkin", capacity=1)
        assert str(exc.value) == ("Este espacio tiene 1 cita que no cabe en el modo "
                                  "nuevo. Muévelas o cancélalas primero.")
        assert esc["w"].visibility == "private"

        _update_igual(db_session, esc["w"], visibility="walkin", capacity=2)
        assert esc["w"].visibility == "walkin"


class TestVariosDias:
    """D9 (spec §5, Tarea 4): crear o copiar el mismo espacio en varios días a
    la vez, saltando SOLO el día donde el dueño YA tiene algo que se ENCIMA.
    """

    def test_create_many_crea_en_varios_dias_y_salta_el_que_se_encima(
            self, db_session, make_program, make_cohort, make_review_day,
            make_officer, make_review_window):
        prog = make_program("Ingeniería de Varios Días")
        cohort = make_cohort()
        off, pos = make_officer([prog])
        d1 = make_review_day(cohort, day=date(2029, 6, 4))
        d2 = make_review_day(cohort, day=date(2029, 6, 5))
        d3 = make_review_day(cohort, day=date(2029, 6, 6))
        # El dueño YA tiene algo en d2 que se encima con el 09:00-11:00 nuevo.
        make_review_window(d2, off, start="10:00", end="12:00", position=pos)

        creados, saltados = ReviewWindowService.create_many(
            db_session, [d1.id, d2.id, d3.id], off.id, position_id=pos.id,
            actor_id=off.id, start_time="09:00", end_time="11:00",
            slot_minutes=30, capacity=1, location=None, visibility="private")

        assert [c.review_day_id for c in creados] == [d1.id, d3.id]
        assert saltados == [d2.date]

    def test_copy_to_days_copia_solo_a_los_elegidos_y_solo_salta_por_encimado(
            self, db_session, make_program, make_cohort, make_review_day,
            make_officer, make_review_window):
        """D9 (spec §0.2, el bug de origen): antes bastaba con que el dueño YA
        tuviera un espacio ese día, aunque no chocara. Ahora salta solo si el
        horario nuevo se ENCIMA de verdad — y solo copia a los días elegidos,
        no a «todos los que estén libres»."""
        from itcj2.apps.titulatec.models import ReviewWindow

        prog = make_program("Ingeniería de Copiar")
        cohort = make_cohort()
        off, pos = make_officer([prog])
        origen_dia = make_review_day(cohort, day=date(2029, 6, 18))
        origen = make_review_window(origen_dia, off, start="09:00", end="11:00",
                                    position=pos)

        sin_encimar = make_review_day(cohort, day=date(2029, 6, 19))
        # Otro espacio del mismo dueño, a OTRA hora: no choca con 09:00-11:00.
        make_review_window(sin_encimar, off, start="14:00", end="15:00",
                           position=pos)

        encimado = make_review_day(cohort, day=date(2029, 6, 20))
        make_review_window(encimado, off, start="10:00", end="12:00", position=pos)

        no_elegido = make_review_day(cohort, day=date(2029, 6, 21))  # libre, no se pasa

        creados, saltados = ReviewWindowService.copy_to_days(
            db_session, origen, [sin_encimar.id, encimado.id])

        assert [c.review_day_id for c in creados] == [sin_encimar.id]
        assert saltados == [encimado.date]
        assert (db_session.query(ReviewWindow)
               .filter_by(review_day_id=no_elegido.id).count()) == 0
