"""Ocupación de citas en lote: el carril de días y el tablero sin N+1 (spec
2026-10-05-titulatec-rendimiento-design.md §3.4, hallazgo H6, invariante 2).

El criterio de aceptación es la EQUIVALENCIA con el cálculo por ventana de
siempre, así que este archivo lleva un ORÁCULO congelado -- la copia literal
de `occupancy` / `window_occupancy` / `windows_for_day` / `out_of_grid` de
antes de esta tarea (`_viejo_*`) -- y compara contra él, igual que
`test_appt_queue_batch.py`:

* `SlotService.occupancy_map` contra `occupancy` por ventana: franjas con
  cupo 2, walkin (franja única, la de legado cuenta bajo la apertura), citas
  canceladas / superadas (liberan), no-show y atendidas NO vigentes (siguen
  ocupando: se filtra por ESTADO, nunca por `is_current`), fuera de la
  rejilla, ventanas sin citas, exclusión de un proceso y el modo DESTINO
  (`walkin` / `inicio` explícitos).
* `window_occupancy(_map)` y `day_occupancy(_map)` contra las sumas viejas.
* `windows_for_days` contra `windows_for_day` día por día (mismo ORDEN, con
  dueño y con pausadas).
* `out_of_grid_map` contra `out_of_grid`.
* Una sola implementación de la regla: las versiones singulares delegan.
* Presupuesto: la vista del día (`_dias_ctx`, `_board_ctx` y `_shell_ctx`)
  hace las MISMAS consultas con 3 días x 2 ventanas que con 6 días x 4.

Todo se siembra aquí (convocatoria, días, ventanas y citas propios): la base
de dev trae datos reales y nada de esto afirma totales de la base.
"""
from __future__ import annotations

import ast
from datetime import date, datetime, time, timedelta
from pathlib import Path

import pytest
from sqlalchemy import event

from itcj2.apps.titulatec.services.slot_service import SlotService

SRC = (Path(__file__).resolve().parents[3]
       / "itcj2/apps/titulatec/services/slot_service.py")

_D1 = date(2029, 6, 4)
_D2 = date(2029, 6, 5)
_D3 = date(2029, 6, 6)          # día habilitado SIN ventanas


def _t(hhmm: str) -> time:
    h, m = hhmm.split(":")
    return time(int(h), int(m))


# ---------------------------------------------------------------------------
# Oráculo congelado: el algoritmo POR VENTANA de antes de la Tarea R3, copiado
# tal cual (el set de estados que liberan va LITERAL: no importa nada que R3
# haya tocado).
# ---------------------------------------------------------------------------
def _viejo_occupancy(db, window, *, excluir_process_id=None, walkin=None, inicio=None):
    from itcj2.apps.titulatec.models import ReviewAppointment
    if not window or not window.id:
        return {}
    q = db.query(ReviewAppointment).filter(ReviewAppointment.window_id == window.id)
    q = q.filter(~ReviewAppointment.status.in_({"cancelled", "superseded"}))
    if excluir_process_id:
        q = q.filter(ReviewAppointment.process_id != excluir_process_id)
    if walkin is None:
        walkin = window.visibility == "walkin"
    apertura = inicio if inicio is not None else window.start_time
    salida = {}
    for a in q.all():
        if a.scheduled_at:
            hora = apertura if walkin else a.scheduled_at.time()
            salida[hora] = salida.get(hora, 0) + 1
    return salida


def _viejo_window_occupancy(db, window):
    franjas = SlotService.slots(window)
    ocupacion = _viejo_occupancy(db, window)
    ocupados = sum(n for hora, n in ocupacion.items() if hora in set(franjas))
    return ocupados, len(franjas) * int(window.capacity or 1)


def _viejo_day_occupancy(db, windows):
    o = c = 0
    for w in windows or []:
        wo, wc = _viejo_window_occupancy(db, w)
        o += wo
        c += wc
    return o, c


def _viejo_windows_for_day(db, review_day_id, *, owner_id=None, solo_abiertas=True):
    from itcj2.apps.titulatec.models import ReviewWindow
    q = db.query(ReviewWindow).filter(ReviewWindow.review_day_id == review_day_id)
    if owner_id is not None:
        q = q.filter(ReviewWindow.owner_user_id == owner_id)
    if solo_abiertas:
        q = q.filter(ReviewWindow.status == "open")
    return q.order_by(ReviewWindow.start_time, ReviewWindow.id).all()


def _viejo_out_of_grid(db, window):
    from itcj2.apps.titulatec.models import ReviewAppointment
    if window.visibility == "walkin":
        return []
    validas = set(SlotService.slots(window))
    q = db.query(ReviewAppointment).filter(ReviewAppointment.window_id == window.id)
    q = q.filter(~ReviewAppointment.status.in_({"cancelled", "superseded"}))
    return [a for a in q.all()
            if a.scheduled_at and a.scheduled_at.time() not in validas]


def _contar(db_session, fn):
    """Sentencias SQL que ejecuta `fn` sobre la conexión del test."""
    sentencias = []

    def _ver(_conn, _cursor, statement, *_a):
        sentencias.append(statement)

    conn = db_session.connection()
    event.listen(conn, "before_cursor_execute", _ver)
    try:
        fn()
    finally:
        event.remove(conn, "before_cursor_execute", _ver)
    return len(sentencias)


# ---------------------------------------------------------------------------
# Escenario de equivalencia: todos los casos de la regla
# ---------------------------------------------------------------------------
@pytest.fixture()
def esc(db_session, seed_phase_defs, seed_document_types, make_program, make_cohort,
        make_review_day, make_officer, make_student, make_process,
        make_review_window, make_appointment):
    seed_phase_defs()
    seed_document_types()
    prog = make_program("Ing. Ocupacion en Lote R3")
    cohort = make_cohort()
    d1 = make_review_day(cohort, day=_D1)
    d2 = make_review_day(cohort, day=_D2)
    d3 = make_review_day(cohort, day=_D3)
    off, _ = make_officer([prog])
    otro, _ = make_officer([prog], first_name="OTRA")

    w = {
        # 4 franjas (09:00..10:30) de 2 personas = 8 lugares.
        "franjas": make_review_window(d1, off, start="09:00", end="11:00", slot=30, cap=2),
        # Sin horario: UNA franja (08:00), cupo TOTAL 5.
        "walkin": make_review_window(d1, off, start="08:00", end="14:00", slot=30, cap=5,
                                     visibility="walkin"),
        # Sin citas: 12:00, 12:20, 12:40 = 3 lugares.
        "vacia": make_review_window(d1, otro, start="12:00", end="13:00", slot=20, cap=1,
                                    visibility="bookable"),
        # Pausada (solo sale con `solo_abiertas=False`).
        "pausada": make_review_window(d1, otro, start="07:00", end="08:00", slot=30, cap=1,
                                      status="paused"),
        # Misma hora de inicio que `franjas`, otro dueño: desempate por id.
        "empate": make_review_window(d1, otro, start="09:00", end="10:00", slot=30, cap=1),
        "dia2": make_review_window(d2, otro, start="09:00", end="10:00", slot=30, cap=1),
        "walkin2": make_review_window(d2, off, start="10:00", end="12:00", slot=30, cap=3,
                                      visibility="walkin"),
    }

    def proceso():
        return make_process(make_student(), cohort=cohort, program=prog, current_phase=2)

    def cita(ventana, hhmm, status="scheduled", is_current=True, proc=None):
        proc = proc or proceso()
        a = make_appointment(proc, when=datetime.combine(ventana.review_day.date, _t(hhmm)),
                             status=status, is_current=is_current)
        a.window_id = ventana.id
        db_session.flush()
        return a

    citas = {
        # --- franjas ------------------------------------------------------
        "f_0900_a": cita(w["franjas"], "09:00"),
        "f_0900_b": cita(w["franjas"], "09:00", status="confirmed"),
        "f_0930": cita(w["franjas"], "09:30", status="in_progress"),
        # D5 / D10: ya no son la vigente y SIGUEN ocupando.
        "f_1000_att": cita(w["franjas"], "10:00", status="attended", is_current=False),
        "f_1000_ns": cita(w["franjas"], "10:00", status="no_show", is_current=False),
        # Liberan: no cuentan.
        "f_1030_can": cita(w["franjas"], "10:30", status="cancelled", is_current=False),
        "f_1030_sup": cita(w["franjas"], "10:30", status="superseded", is_current=False),
        # Fuera de la rejilla: cuentan en `occupancy`, no en `window_occupancy`.
        "f_0915": cita(w["franjas"], "09:15"),
        "f_1045_ns": cita(w["franjas"], "10:45", status="no_show", is_current=False),
        # Fuera de la rejilla pero cancelada: asiento fantasma, no sale.
        "f_0945_can": cita(w["franjas"], "09:45", status="cancelled", is_current=False),
        # --- walkin: TODA viva cuenta bajo la apertura --------------------
        "w_0800": cita(w["walkin"], "08:00"),
        "w_1030_legado": cita(w["walkin"], "10:30"),
        "w_0900_ns": cita(w["walkin"], "09:00", status="no_show", is_current=False),
        "w_1200_att": cita(w["walkin"], "12:00", status="attended", is_current=False),
        "w_0800_can": cita(w["walkin"], "08:00", status="cancelled", is_current=False),
        "w_1100_sup": cita(w["walkin"], "11:00", status="superseded", is_current=False),
        # --- otras ventanas -----------------------------------------------
        "p_0700": cita(w["pausada"], "07:00"),
        "e_0930": cita(w["empate"], "09:30"),
        "d2_0930": cita(w["dia2"], "09:30"),
        "w2_1000": cita(w["walkin2"], "10:00"),
        "w2_1115_legado": cita(w["walkin2"], "11:15"),
    }
    # Un proceso con citas en DOS ventanas (una no vigente en `franjas`, la
    # vigente en `walkin2`): la exclusión tiene que pegar en las dos a la vez.
    doble = proceso()
    citas["x_franjas"] = cita(w["franjas"], "10:30", status="no_show", is_current=False,
                              proc=doble)
    citas["x_walkin2"] = cita(w["walkin2"], "10:00", proc=doble)

    return {"prog": prog, "cohort": cohort, "dias": (d1, d2, d3), "off": off,
            "otro": otro, "w": w, "citas": citas, "doble": doble}


# ---------------------------------------------------------------------------
# 1. El mapa ES la ocupación por ventana
# ---------------------------------------------------------------------------
def test_occupancy_map_equivale_al_calculo_por_ventana(db_session, esc):
    w = esc["w"]
    ventanas = list(w.values())
    mapa = SlotService.occupancy_map(db_session, ventanas)

    # El escenario prueba lo que dice (si no, el oráculo compararía vacíos).
    assert _viejo_occupancy(db_session, w["franjas"]) == {
        _t("09:00"): 2, _t("09:30"): 1, _t("10:00"): 2, _t("10:30"): 1,
        _t("09:15"): 1, _t("10:45"): 1}
    assert _viejo_occupancy(db_session, w["walkin"]) == {_t("08:00"): 4}
    assert _viejo_occupancy(db_session, w["walkin2"]) == {_t("10:00"): 3}
    assert _viejo_occupancy(db_session, w["vacia"]) == {}

    assert set(mapa) == {v.id for v in ventanas}
    for nombre, ventana in w.items():
        viejo = _viejo_occupancy(db_session, ventana)
        assert mapa[ventana.id] == viejo, nombre
        # La firma de siempre delega en el mapa y dice lo mismo.
        assert SlotService.occupancy(db_session, ventana) == viejo, nombre


def test_occupancy_map_con_exclusion_y_modo_destino(db_session, esc):
    w = esc["w"]
    doble = esc["doble"].id
    ventanas = [w["franjas"], w["walkin2"], w["walkin"]]

    mapa = SlotService.occupancy_map(db_session, ventanas, excluir_process_id=doble)
    for v in ventanas:
        viejo = _viejo_occupancy(db_session, v, excluir_process_id=doble)
        assert mapa[v.id] == viejo, v.id
        assert SlotService.occupancy(db_session, v, excluir_process_id=doble) == viejo
    # La exclusión pegó en las DOS ventanas del proceso.
    assert _t("10:30") not in mapa[w["franjas"].id]
    assert mapa[w["walkin2"].id] == {_t("10:00"): 2}

    # Modo DESTINO (`ReviewWindowService.update`): cada cita a su hora real,
    # o todas bajo un `inicio` que todavía no está escrito.
    for kw in ({"walkin": False}, {"walkin": True}, {"inicio": _t("09:00")},
               {"walkin": True, "inicio": _t("07:30")}):
        for v in (w["walkin"], w["franjas"]):
            viejo = _viejo_occupancy(db_session, v, **kw)
            assert SlotService.occupancy_map(db_session, [v], **kw)[v.id] == viejo, (kw, v.id)
            assert SlotService.occupancy(db_session, v, **kw) == viejo, (kw, v.id)
    assert SlotService.occupancy(db_session, w["walkin"], walkin=False) == {
        _t("08:00"): 1, _t("10:30"): 1, _t("09:00"): 1, _t("12:00"): 1}


def test_ventana_sin_id_o_lista_vacia_no_consulta(db_session, esc):
    from itcj2.apps.titulatec.models import ReviewWindow

    sin_id = ReviewWindow(start_time=_t("09:00"), end_time=_t("10:00"), slot_minutes=30,
                          capacity=1, visibility="private")
    assert _contar(db_session, lambda: SlotService.occupancy_map(db_session, [])) == 0
    assert SlotService.occupancy_map(db_session, []) == {}
    assert SlotService.occupancy_map(db_session, None) == {}
    assert SlotService.occupancy(db_session, None) == {}
    assert SlotService.occupancy(db_session, sin_id) == {}
    assert SlotService.window_occupancy(db_session, sin_id) == (0, 2)
    assert SlotService.windows_for_days(db_session, []) == {}
    assert _contar(db_session, lambda: SlotService.windows_for_days(db_session, [])) == 0
    assert SlotService.day_occupancy(db_session, []) == (0, 0)
    assert SlotService.out_of_grid(db_session, sin_id) == []


# ---------------------------------------------------------------------------
# 2. Totales por ventana y por día
# ---------------------------------------------------------------------------
def test_window_y_day_occupancy_equivalen(db_session, esc):
    w = esc["w"]
    d1, d2, d3 = esc["dias"]
    ventanas = list(w.values())

    # Sentido del escenario: en `franjas` las de 09:15 y 10:45 NO cuentan.
    assert _viejo_window_occupancy(db_session, w["franjas"]) == (6, 8)
    assert _viejo_window_occupancy(db_session, w["walkin"]) == (4, 5)
    assert _viejo_window_occupancy(db_session, w["vacia"]) == (0, 3)

    totales = SlotService.window_occupancy_map(db_session, ventanas)
    assert set(totales) == {v.id for v in ventanas}
    for nombre, v in w.items():
        viejo = _viejo_window_occupancy(db_session, v)
        assert totales[v.id] == viejo, nombre
        assert SlotService.window_occupancy(db_session, v) == viejo, nombre

    por_dia = {d.id: _viejo_windows_for_day(db_session, d.id) for d in (d1, d2, d3)}
    dias = SlotService.day_occupancy_map(db_session, por_dia)
    assert set(dias) == set(por_dia)
    for dia_id, ws in por_dia.items():
        viejo = _viejo_day_occupancy(db_session, ws)
        assert dias[dia_id] == viejo, dia_id
        assert SlotService.day_occupancy(db_session, ws) == viejo, dia_id
    assert dias[d3.id] == (0, 0)
    # Día 1 abierto: franjas (6/8) + walkin (4/5) + vacía (0/3) + empate (1/2).
    assert dias[d1.id] == (11, 18)


# ---------------------------------------------------------------------------
# 3. Ventanas de varios días
# ---------------------------------------------------------------------------
def test_windows_for_days_equivale_y_conserva_orden(db_session, esc):
    d1, d2, d3 = esc["dias"]
    ids = [d1.id, d2.id, d3.id]
    for kw in ({}, {"solo_abiertas": False}, {"owner_id": esc["off"].id},
               {"owner_id": esc["otro"].id, "solo_abiertas": False}):
        mapa = SlotService.windows_for_days(db_session, ids, **kw)
        assert set(mapa) == set(ids), kw
        for dia_id in ids:
            viejo = _viejo_windows_for_day(db_session, dia_id, **kw)
            assert [v.id for v in mapa[dia_id]] == [v.id for v in viejo], (kw, dia_id)
            assert [v.id for v in SlotService.windows_for_day(db_session, dia_id, **kw)] \
                == [v.id for v in viejo], (kw, dia_id)
        assert mapa[d3.id] == []

    w = esc["w"]
    # Orden por (start_time, id): la pausada solo sale cuando se pide.
    assert [v.id for v in SlotService.windows_for_day(db_session, d1.id)] == [
        w["walkin"].id, w["franjas"].id, w["empate"].id, w["vacia"].id]
    assert [v.id for v in SlotService.windows_for_day(db_session, d1.id,
                                                      solo_abiertas=False)] == [
        w["pausada"].id, w["walkin"].id, w["franjas"].id, w["empate"].id, w["vacia"].id]


def test_out_of_grid_map_equivale(db_session, esc):
    w = esc["w"]
    c = esc["citas"]
    ventanas = list(w.values())
    mapa = SlotService.out_of_grid_map(db_session, ventanas)
    assert set(mapa) == {v.id for v in ventanas}
    for nombre, v in w.items():
        viejo = sorted(a.id for a in _viejo_out_of_grid(db_session, v))
        assert sorted(a.id for a in mapa[v.id]) == viejo, nombre
        assert sorted(a.id for a in SlotService.out_of_grid(db_session, v)) == viejo, nombre
    assert sorted(a.id for a in mapa[w["franjas"].id]) == sorted(
        [c["f_0915"].id, c["f_1045_ns"].id])
    assert mapa[w["walkin"].id] == []


# ---------------------------------------------------------------------------
# 4. Un SELECT para cualquier número de ventanas, y una sola regla
# ---------------------------------------------------------------------------
def test_un_solo_select_por_mapa(db_session, esc):
    ventanas = list(esc["w"].values())
    ids = [d.id for d in esc["dias"]]
    por_dia = {d.id: [v for v in ventanas if v.review_day_id == d.id] for d in esc["dias"]}
    assert _contar(db_session, lambda: SlotService.occupancy_map(db_session, ventanas)) == 1
    assert _contar(db_session, lambda: SlotService.window_occupancy_map(db_session,
                                                                        ventanas)) == 1
    assert _contar(db_session, lambda: SlotService.day_occupancy_map(db_session,
                                                                     por_dia)) == 1
    assert _contar(db_session, lambda: SlotService.windows_for_days(db_session, ids)) == 1
    assert _contar(db_session, lambda: SlotService.out_of_grid_map(db_session,
                                                                   ventanas)) == 1


def _funciones(arbol):
    return {n.name: n for n in ast.walk(arbol) if isinstance(n, ast.FunctionDef)}


def test_la_regla_de_ocupacion_vive_en_un_solo_lugar():
    """Invariante 2: la versión en lote ES la regla; las singulares delegan.

    El filtro por estado (`_ESTADOS_QUE_LIBERAN`) se usa en UNA sola función
    del módulo, y ninguna versión singular arma su propia consulta.
    """
    arbol = ast.parse(SRC.read_text(encoding="utf-8"), filename=str(SRC))
    funcs = _funciones(arbol)

    duenas = {nombre for nombre, f in funcs.items()
              for n in ast.walk(f)
              if isinstance(n, ast.Name) and n.id == "_ESTADOS_QUE_LIBERAN"
              and isinstance(n.ctx, ast.Load)}
    assert len(duenas) == 1, duenas

    for nombre in ("occupancy", "window_occupancy", "day_occupancy",
                   "windows_for_day", "out_of_grid"):
        llamadas = {n.func.attr for n in ast.walk(funcs[nombre])
                    if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
        assert "query" not in llamadas, nombre


# ---------------------------------------------------------------------------
# 5. Presupuesto: la vista del día no crece con días ni ventanas
# ---------------------------------------------------------------------------
@pytest.fixture()
def presupuesto(db_session, seed_phase_defs, seed_document_types, make_program,
                make_cohort, make_review_day, make_officer, make_student, make_process,
                make_review_window, make_appointment):
    seed_phase_defs()
    seed_document_types()

    def construir(n_dias, n_ventanas, base):
        """`n_dias` días x `n_ventanas` ventanas, en una convocatoria NUEVA (la
        activa: la `open` más nueva).

        Patrón por ventana: 0 = mía con franjas, 1 = mía sin horario, 2 = mía
        con franjas, 3 = de otra persona con franjas. Con 2 ventanas el
        tablero tiene 2 espacios míos; con 4, 3 míos y 1 ajeno.

        Citas: en los días que NO se miran, una viva por ventana (escala con
        días x ventanas: es lo que paga el carril). En el día que se mira, el
        MISMO juego en los dos escenarios (las citas del tablero no son la
        variable): una en franja, una fuera de la rejilla, un apartado y una
        cancelada.
        """
        prog = make_program(f"Ing. Presupuesto R3 {n_dias}x{n_ventanas}")
        cohort = make_cohort()
        off, _ = make_officer([prog])
        otro, _ = make_officer([prog], first_name="OTRA")

        def cita(ventana, cuando, status="scheduled", is_current=True):
            proc = make_process(make_student(), cohort=cohort, program=prog,
                                current_phase=2)
            a = make_appointment(proc, when=cuando, status=status, is_current=is_current)
            a.window_id = ventana.id
            db_session.flush()

        dias = []
        for i in range(n_dias):
            fila = make_review_day(cohort, day=base + timedelta(days=i))
            ventanas = []
            for j in range(n_ventanas):
                ini, fin = f"{8 + 2 * j:02d}:00", f"{9 + 2 * j:02d}:00"
                if j == 1:
                    v = make_review_window(fila, off, start=ini, end=fin, slot=30, cap=5,
                                           visibility="walkin")
                else:
                    v = make_review_window(fila, otro if j == 3 else off, start=ini,
                                           end=fin, slot=30, cap=2)
                ventanas.append(v)
            dias.append((fila, ventanas))

        visto, ventanas_vistas = dias[0]
        for fila, ventanas in dias[1:]:
            for v in ventanas:
                cita(v, datetime.combine(fila.date, v.start_time))
        franjas, walkin = ventanas_vistas[0], ventanas_vistas[1]
        cita(franjas, datetime.combine(visto.date, franjas.start_time))
        cita(franjas, datetime.combine(visto.date, _t("08:15")))         # fuera de rejilla
        cita(walkin, datetime.combine(visto.date, walkin.start_time))    # apartado
        cita(walkin, datetime.combine(visto.date, walkin.start_time),
             status="cancelled", is_current=False)
        return {"prog": prog, "cohort": cohort, "off": off, "dias": dias,
                "visto": visto.date}

    return construir


def _medir_vista(db_session, s):
    from itcj2.apps.titulatec.pages.appointments import _board_ctx, _dias_ctx, _shell_ctx

    uid = s["off"].id
    cid = s["cohort"].id
    allowed = {s["prog"].id}
    dia = s["visto"]
    hoy = date(2029, 1, 1)

    def vista():
        return _shell_ctx(db_session, user_id=uid, v="agenda", date_raw=dia.isoformat())

    # Calentamiento: lo que se resuelve una vez (alcance, catálogos) no es por
    # día ni por ventana y no debe sesgar la cuenta.
    ctx = vista()
    assert ctx["modo"] == "dia" and ctx["day"] == dia.isoformat()
    cuentas = {}
    db_session.expire_all()
    cuentas["dias"] = _contar(db_session, lambda: _dias_ctx(db_session, cid, abierto=dia,
                                                            today=hoy))
    db_session.expire_all()
    cuentas["tablero"] = _contar(db_session, lambda: _board_ctx(
        db_session, dia, allowed, user_id=uid, cohort_id=cid))
    db_session.expire_all()
    cuentas["vista"] = _contar(db_session, vista)
    return cuentas, ctx


def test_vista_del_dia_no_crece_con_dias_ni_ventanas(db_session, presupuesto):
    chico = presupuesto(3, 2, date(2029, 3, 5))
    c_chico, ctx_chico = _medir_vista(db_session, chico)
    grande = presupuesto(6, 4, date(2029, 4, 2))
    c_grande, ctx_grande = _medir_vista(db_session, grande)
    print(f"\n[R3] consultas vista del dia: 3x2 -> {c_chico}, 6x4 -> {c_grande}")

    # El escenario de verdad pinta lo que dice: un chip por día, con la
    # ocupación de SU convocatoria, y los conteos del oráculo.
    for s, ctx, n_dias in ((chico, ctx_chico, 3), (grande, ctx_grande, 6)):
        assert len(ctx["dias"]) == n_dias
        for chip, (fila, ventanas) in zip(ctx["dias"], s["dias"]):
            assert chip["date"] == fila.date.isoformat()
            assert (chip["ocupados"], chip["capacidad"]) == \
                _viejo_day_occupancy(db_session, ventanas)
        # Día mirado: la de franja (1) + el apartado (1); la fuera de rejilla
        # y la cancelada no cuentan.
        assert ctx["dias"][0]["ocupados"] == 2
    assert ctx_chico["dias"][1]["ocupados"] == 2 and ctx_grande["dias"][1]["ocupados"] == 4
    assert [g["id"] for g in ctx_chico["board"]["grupos"]] == \
        [v.id for v in chico["dias"][0][1]]
    assert len(ctx_grande["board"]["grupos"]) == 3
    assert len(ctx_grande["board"]["ajenas"]) == 1

    assert c_chico == c_grande


def test_el_tablero_sigue_diciendo_lo_mismo(db_session, presupuesto):
    """`_board_ctx` con los mapas: cabeceras, ajenas y banda «fuera de la
    rejilla» idénticas al cálculo por ventana."""
    from itcj2.apps.titulatec.pages.appointments import _board_ctx

    s = presupuesto(2, 4, date(2029, 5, 14))
    fila, ventanas = s["dias"][0]
    board = _board_ctx(db_session, s["visto"], {s["prog"].id}, user_id=s["off"].id,
                       cohort_id=s["cohort"].id)
    mias = [v for v in ventanas if v.owner_user_id == s["off"].id]
    ajenas = [v for v in ventanas if v.owner_user_id != s["off"].id]

    assert [g["id"] for g in board["grupos"]] == [v.id for v in mias]
    for g, v in zip(board["grupos"], mias):
        assert (g["ocupados"], g["capacidad"]) == _viejo_window_occupancy(db_session, v)
        if g["modo"] == "franjas":
            assert sorted(f["appt_id"] for f in g["fuera"]) == sorted(
                a.id for a in _viejo_out_of_grid(db_session, v))
    assert board["ajenas"] == [
        {"horario": f"{v.start_time:%H:%M}–{v.end_time:%H:%M}",
         "ocupados": _viejo_window_occupancy(db_session, v)[0],
         "capacidad": _viejo_window_occupancy(db_session, v)[1]} for v in ajenas]
    franjas = board["grupos"][0]
    assert franjas["modo"] == "franjas" and len(franjas["fuera"]) == 1
    assert franjas["ocupados"] == 1
