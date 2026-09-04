"""Franjas, cupo duro y las dos guardas de concurrencia.

Lo que se prueba aquí es el motor: derivar franjas de (inicio, fin, duración),
contar ocupación, rechazar cuando no cabe, y no perder el lock por commitear a
destiempo. La UI llega en fases posteriores.
"""
from datetime import date, datetime, time
from pathlib import Path

import pytest

from itcj2.apps.titulatec.services import appointment_errors as err
from itcj2.apps.titulatec.services.slot_service import SlotService

_D = date(2029, 5, 7)
SRC = (Path(__file__).resolve().parents[3]
       / "itcj2/apps/titulatec/services/slot_service.py")


# ---------------------------------------------------------------- derivación
def test_las_franjas_se_derivan_del_horario_y_la_duracion(agenda_slots):
    """09:00-11:00 en pasos de 30 son cuatro franjas."""
    assert SlotService.slots(agenda_slots["w"]) == [
        time(9, 0), time(9, 30), time(10, 0), time(10, 30)]


def test_la_ultima_franja_no_desborda_el_fin(db_session, agenda_slots):
    """Solo cuenta la franja que cabe ENTERA: 09:00-10:20 en pasos de 30 da dos,
    no tres, porque la de 10:00 se saldría a las 10:30."""
    w = agenda_slots["w"]
    w.end_time = time(10, 20)
    db_session.flush()
    assert SlotService.slots(w) == [time(9, 0), time(9, 30)]


def test_una_ventana_sin_duracion_no_genera_franjas_infinitas(db_session, agenda_slots):
    """Guarda del propio algoritmo: sin ella el `while` no termina."""
    w = agenda_slots["w"]
    w.slot_minutes = 0
    assert SlotService.slots(w) == []


def test_los_defaults_del_dia_se_heredan_de_la_convocatoria(
        db_session, agenda_slots, set_cohort_defaults):
    esc = agenda_slots
    set_cohort_defaults(esc["cohort"], start="08:00", end="13:00", slot=20, cap=2,
                        location="Edificio B")
    d = SlotService.day_defaults(db_session, esc["dia"])
    assert d["start_time"] == time(8, 0)
    assert d["slot_minutes"] == 20
    assert d["capacity"] == 2
    assert d["location"] == "Edificio B"


def test_el_override_del_dia_gana_al_default_de_la_convocatoria(
        db_session, agenda_slots, set_cohort_defaults):
    esc = agenda_slots
    set_cohort_defaults(esc["cohort"], slot=20)
    esc["dia"].slot_minutes = 45
    db_session.flush()
    assert SlotService.day_defaults(db_session, esc["dia"])["slot_minutes"] == 45


# ----------------------------------------------------------------- ocupación
def test_la_ocupacion_cuenta_por_franja(db_session, agenda_slots):
    esc = agenda_slots
    SlotService.assign(db_session, esc["w"].id, time(9, 0), esc["p1"].id, esc["off"].id)
    ocup = SlotService.occupancy(db_session, esc["w"])
    assert ocup == {time(9, 0): 1}


def test_la_ocupacion_cuenta_los_no_show(db_session, agenda_slots):
    """Decisión del usuario: «si no se presentó es que ya pasó». La franja se
    consumió y su lugar no se reabre."""
    esc = agenda_slots
    ap = SlotService.assign(db_session, esc["w"].id, time(9, 0), esc["p1"].id, esc["off"].id)
    ap.status = "no_show"
    db_session.flush()

    assert SlotService.occupancy(db_session, esc["w"])[time(9, 0)] == 1
    with pytest.raises(err.SlotFull):
        SlotService.assign(db_session, esc["w"].id, time(9, 0), esc["p2"].id, esc["off"].id)


def test_window_occupancy_da_ocupados_sobre_capacidad(db_session, agenda_slots):
    esc = agenda_slots                     # 4 franjas x capacidad 1
    SlotService.assign(db_session, esc["w"].id, time(9, 0), esc["p1"].id, esc["off"].id)
    assert SlotService.window_occupancy(db_session, esc["w"]) == (1, 4)


def test_day_occupancy_suma_las_ventanas_del_dia(db_session, agenda_slots,
                                                 make_officer, make_review_window):
    esc = agenda_slots
    otro, _ = make_officer([esc["prog"]], first_name="OTRA")
    w2 = make_review_window(esc["dia"], otro, start="12:00", end="13:00", slot=30, cap=1)
    SlotService.assign(db_session, esc["w"].id, time(9, 0), esc["p1"].id, esc["off"].id)
    assert SlotService.day_occupancy(db_session, [esc["w"], w2]) == (1, 6)


def test_free_slots_excluye_las_llenas(db_session, agenda_slots):
    esc = agenda_slots
    SlotService.assign(db_session, esc["w"].id, time(9, 30), esc["p1"].id, esc["off"].id)
    assert SlotService.free_slots(db_session, esc["w"]) == [
        time(9, 0), time(10, 0), time(10, 30)]


# ---------------------------------------------------------------- asignación
def test_el_cupo_es_duro(db_session, agenda_slots):
    esc = agenda_slots                     # capacidad 1
    SlotService.assign(db_session, esc["w"].id, time(9, 0), esc["p1"].id, esc["off"].id)
    with pytest.raises(err.SlotFull):
        SlotService.assign(db_session, esc["w"].id, time(9, 0), esc["p2"].id, esc["off"].id)


def test_con_capacidad_dos_caben_dos_y_no_tres(
        db_session, agenda_slots, make_student, make_process):
    """Capacidad 1 por defecto, pero configurable a más (decisión del usuario)."""
    esc = agenda_slots
    esc["w"].capacity = 2
    db_session.flush()
    p3 = make_process(make_student(), cohort=esc["cohort"], program=esc["prog"],
                      current_phase=2)
    SlotService.assign(db_session, esc["w"].id, time(9, 0), esc["p1"].id, esc["off"].id)
    SlotService.assign(db_session, esc["w"].id, time(9, 0), esc["p2"].id, esc["off"].id)
    with pytest.raises(err.SlotFull):
        SlotService.assign(db_session, esc["w"].id, time(9, 0), p3.id, esc["off"].id)


def test_una_hora_fuera_de_la_rejilla_se_rechaza(db_session, agenda_slots):
    esc = agenda_slots
    with pytest.raises(err.InvalidSlot):
        SlotService.assign(db_session, esc["w"].id, time(9, 17), esc["p1"].id, esc["off"].id)


def test_sin_ventana_o_sin_franja_es_un_error_explicito(db_session, agenda_slots):
    """Antes esto era un `if dt:` que devolvía 200 y no escribía nada."""
    esc = agenda_slots
    with pytest.raises(err.MissingSchedule):
        SlotService.assign(db_session, esc["w"].id, None, esc["p1"].id, esc["off"].id)
    with pytest.raises(err.MissingSchedule):
        SlotService.assign(db_session, None, time(9, 0), esc["p1"].id, esc["off"].id)


def test_asignar_pone_la_fecha_del_dia_y_el_lugar_de_la_ventana(db_session, agenda_slots):
    esc = agenda_slots
    esc["w"].location = "Edificio A"
    db_session.flush()
    ap = SlotService.assign(db_session, esc["w"].id, time(10, 0), esc["p1"].id, esc["off"].id)
    assert ap.scheduled_at == datetime.combine(_D, time(10, 0))
    assert ap.window_id == esc["w"].id
    assert ap.location == "Edificio A"
    assert ap.status == "scheduled"


def test_mover_al_mismo_alumno_no_choca_consigo_mismo(db_session, agenda_slots):
    """Al recolocar, su propia cita no puede contar contra el cupo destino."""
    esc = agenda_slots
    SlotService.assign(db_session, esc["w"].id, time(9, 0), esc["p1"].id, esc["off"].id)
    ap = SlotService.assign(db_session, esc["w"].id, time(9, 30), esc["p1"].id, esc["off"].id)
    assert ap.scheduled_at.time() == time(9, 30)
    assert SlotService.occupancy(db_session, esc["w"]) == {time(9, 30): 1}


def test_un_proceso_no_acumula_dos_citas(db_session, agenda_slots):
    from itcj2.apps.titulatec.models import ReviewAppointment
    esc = agenda_slots
    SlotService.assign(db_session, esc["w"].id, time(9, 0), esc["p1"].id, esc["off"].id)
    SlotService.assign(db_session, esc["w"].id, time(10, 0), esc["p1"].id, esc["off"].id)
    n = (db_session.query(ReviewAppointment)
         .filter_by(process_id=esc["p1"].id).count())
    assert n == 1


# ------------------------------------------------------------------- reparto
def test_el_reparto_sienta_en_franjas_consecutivas(db_session, agenda_slots):
    esc = agenda_slots
    ok, fuera = SlotService.assign_batch(
        db_session, esc["w"].id, [esc["p1"].id, esc["p2"].id], esc["off"].id)
    assert [h for h, _ in ok] == [time(9, 0), time(9, 30)]
    assert fuera == []


def test_el_reparto_se_detiene_en_el_limite_duro(db_session, agenda_slots_lleno):
    """Dos lugares, cuatro procesos: caben dos y los otros dos se reportan."""
    esc = agenda_slots_lleno
    ok, fuera = SlotService.assign_batch(
        db_session, esc["w"].id, [p.id for p in esc["procesos"]], esc["off"].id)
    assert len(ok) == 2
    assert len(fuera) == 2
    assert set(fuera) == {p.id for p in esc["procesos"][2:]}


def test_el_reparto_respeta_lo_ya_ocupado(db_session, agenda_slots):
    esc = agenda_slots
    SlotService.assign(db_session, esc["w"].id, time(9, 0), esc["p1"].id, esc["off"].id)
    ok, _ = SlotService.assign_batch(db_session, esc["w"].id, [esc["p2"].id], esc["off"].id)
    assert ok == [(time(9, 30), esc["p2"].id)]


def test_el_reparto_puede_arrancar_desde_una_franja(db_session, agenda_slots):
    esc = agenda_slots
    ok, _ = SlotService.assign_batch(db_session, esc["w"].id, [esc["p1"].id],
                                     esc["off"].id, desde=time(10, 0))
    assert ok == [(time(10, 0), esc["p1"].id)]


def test_la_propuesta_no_toca_la_base(db_session, agenda_slots):
    """El encargado confirma o descarta; hasta entonces no hay nada escrito.

    Se cuentan solo las citas de ESTE escenario: la suite corre contra la BD de
    dev, que ya tiene citas reales, asi que un `count()` a secas no probaria nada.
    """
    from itcj2.apps.titulatec.models import ReviewAppointment
    esc = agenda_slots
    mios = [esc["p1"].id, esc["p2"].id]

    propuesta, fuera = SlotService.propose_batch(db_session, esc["w"], mios)

    assert len(propuesta) == 2 and fuera == []
    escritas = (db_session.query(ReviewAppointment)
                .filter(ReviewAppointment.process_id.in_(mios)).count())
    assert escritas == 0, "la propuesta escribio en la base"


def test_la_propuesta_coincide_con_lo_que_hara_el_reparto(db_session, agenda_slots):
    esc = agenda_slots
    propuesta, _ = SlotService.propose_batch(
        db_session, esc["w"], [esc["p1"].id, esc["p2"].id])
    ok, _ = SlotService.assign_batch(
        db_session, esc["w"].id, [esc["p1"].id, esc["p2"].id], esc["off"].id)
    assert propuesta == ok


# --------------------------------------------------- fuera de rejilla y locks
def test_las_citas_fuera_de_rejilla_se_pueden_listar(db_session, agenda_slots):
    """Cambiar `slot_minutes` con citas dentro deja horas huérfanas. Se muestran
    en su propia banda en vez de esconderse."""
    esc = agenda_slots
    SlotService.assign(db_session, esc["w"].id, time(9, 30), esc["p1"].id, esc["off"].id)
    esc["w"].slot_minutes = 60
    db_session.flush()
    fuera = SlotService.out_of_grid(db_session, esc["w"])
    assert [a.process_id for a in fuera] == [esc["p1"].id]


def test_el_service_no_commitea():
    """Un commit liberaría el FOR UPDATE antes del INSERT y el lock no serviría
    de nada. El dueño de la transacción es quien llama.

    Se recorre el AST y no el texto: el propio docstring del módulo explica la
    regla nombrando `db.commit()`, así que un `in` sobre el fuente se acusaría
    a sí mismo.
    """
    import ast

    arbol = ast.parse(SRC.read_text(encoding="utf-8"), filename=str(SRC))
    culpables = [
        f"linea {n.lineno}"
        for n in ast.walk(arbol)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "commit"
    ]
    assert not culpables, (
        "SlotService no puede commitear: rompe el lock que sostiene el cupo duro. "
        + ", ".join(culpables))


def test_el_lock_es_sobre_la_ventana_y_sobre_el_proceso():
    """Lección de AgendaTec: FOR UPDATE sobre cero filas no bloquea, y el caso
    normal aquí es insertar la PRIMERA cita de una franja vacía."""
    src = SRC.read_text(encoding="utf-8")
    assert "titulatec_review_windows" in src and "FOR UPDATE" in src, \
        "falta el lock sobre la fila de la ventana"
    assert "pg_advisory_xact_lock" in src, \
        "falta el lock del proceso: el de ventana no serializa dos ventanas distintas"
    assert "pg_advisory_lock(" not in src, \
        "el lock tiene que ser de TRANSACCION: PgBouncer esta en modo transaction"


def test_el_lock_timeout_es_local():
    """Un `SET` de sesion se le queda pegado a otro cliente del pool."""
    src = SRC.read_text(encoding="utf-8")
    assert "SET LOCAL lock_timeout" in src


def test_el_timeout_del_lock_se_traduce_a_mensaje_de_ventanilla(
        db_session, agenda_slots, monkeypatch):
    """Si otro encargado tiene la ventana tomada mas de 3 s, el usuario tiene
    que leer que hacer, no un traceback de Postgres.

    No se levantan dos conexiones de verdad: el harness corre todo dentro de UNA
    transaccion con savepoint, asi que la segunda se quedaria bloqueada contra
    la primera, que nunca commitea. Lo que se prueba es la TRADUCCION.
    """
    from sqlalchemy.exc import OperationalError
    from itcj2.apps.titulatec.services import slot_service as mod

    real = db_session.execute

    def _execute(stmt, *a, **kw):
        if "FOR UPDATE" in str(stmt):
            raise OperationalError("SELECT ... FOR UPDATE", {}, Exception("lock timeout"))
        return real(stmt, *a, **kw)

    monkeypatch.setattr(db_session, "execute", _execute)

    esc = agenda_slots
    with pytest.raises(err.SlotLockTimeout) as e:
        mod.SlotService.assign(db_session, esc["w"].id, time(9, 0),
                               esc["p1"].id, esc["off"].id)
    assert "Vuelve a intentar" in str(e.value)
