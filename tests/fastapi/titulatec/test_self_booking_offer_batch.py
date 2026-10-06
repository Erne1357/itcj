"""«Mi cita» sin N+1: alcance de los dueños y ocupación de la oferta en lote
(spec 2026-10-05-titulatec-rendimiento-design.md §3.5, hallazgo H10 y su
Ampliación del Ruling tras R3).

El criterio de aceptación es la EQUIVALENCIA con lo de antes, así que este
archivo lleva un ORÁCULO congelado -- la copia literal del algoritmo por dueño
y por ventana de antes de esta tarea (`_viejo_*`; no llama a nada que R4 haya
tocado) -- y compara contra él, igual que `test_slot_occupancy_batch.py`:

* `scope_service._program_ids_for_users` contra el join por usuario de
  siempre: por rol, por permiso con `allow`, permiso negado, rol de OTRA app,
  puesto vencido / futuro / apagado, asignación apagada, varios puestos,
  puesto compartido por dos usuarios, sin puesto y rol directo (sin ancla).
* La singular DELEGA en la plural (AST): una sola implementación del join.
* `SelfBookingService._owners_serving` y `offer` contra el oráculo, con tres
  relojes (antes del día, a media atención, minutos antes del cierre) para
  que salgan «lleno», «cierra_pronto» y las franjas recortadas por D8.
* Presupuesto: `offer` hace las MISMAS consultas con 2 que con 5 dueños y con
  2 que con 6 ventanas, y consulta las citas UNA sola vez.

Todo se siembra aquí (convocatoria, días, puestos y citas propios): la base de
dev trae datos reales y nada de esto afirma totales de la base.
"""
from __future__ import annotations

import ast
import itertools
from datetime import date, datetime, time, timedelta
from pathlib import Path

import pytest
from sqlalchemy import event

import itcj2.apps.titulatec.services.self_booking_service as sb_mod
from itcj2.apps.titulatec.services.self_booking_service import SelfBookingService
from itcj2.apps.titulatec.services.slot_service import SlotService

_ROOT = Path(__file__).resolve().parents[3] / "itcj2/apps/titulatec/services"
_SEQ = itertools.count(1)

_D1 = date(2029, 6, 4)
_D2 = date(2029, 6, 5)
_D3 = date(2029, 6, 6)           # día CERRADO
_VISIBLES = ("bookable", "walkin")


def _t(hhmm: str) -> time:
    h, m = hhmm.split(":")
    return time(int(h), int(m))


def _contar(db_session, fn, filtro=None):
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
    if filtro is not None:
        return sum(1 for s in sentencias if filtro in s)
    return len(sentencias)


# ---------------------------------------------------------------------------
# Oráculo congelado (alcance): el join POR USUARIO de antes de R4.
# ---------------------------------------------------------------------------
def _viejo_program_ids(db, user_id):
    from itcj2.core.models.position import (
        Position, PositionAppPerm, PositionAppRole, ProgramPosition, UserPosition,
    )
    from itcj2.core.services.authz_service import _active_position_filter, get_or_404_app

    app = get_or_404_app(db, "titulatec")
    base = (
        db.query(ProgramPosition.program_id)
        .join(Position, Position.id == ProgramPosition.position_id)
        .join(UserPosition, UserPosition.position_id == ProgramPosition.position_id)
        .filter(UserPosition.user_id == user_id, _active_position_filter(),
                Position.is_active.is_(True))
    )
    via_role = (base.join(PositionAppRole,
                          PositionAppRole.position_id == ProgramPosition.position_id)
                .filter(PositionAppRole.app_id == app.id))
    via_perm = (base.join(PositionAppPerm,
                          PositionAppPerm.position_id == ProgramPosition.position_id)
                .filter(PositionAppPerm.app_id == app.id,
                        PositionAppPerm.allow.is_(True)))
    rows = via_role.distinct().all() + via_perm.distinct().all()
    return {r[0] for r in rows}


def _viejo_owners_serving(db, owner_ids, program_id):
    if not owner_ids or not program_id:
        return set()
    return {uid for uid in owner_ids if program_id in _viejo_program_ids(db, uid)}


# ---------------------------------------------------------------------------
# Oráculo congelado (oferta): `offer` con una consulta por ventana.
# ---------------------------------------------------------------------------
def _viejo_occupancy(db, window):
    from itcj2.apps.titulatec.models import ReviewAppointment
    q = db.query(ReviewAppointment).filter(ReviewAppointment.window_id == window.id)
    q = q.filter(~ReviewAppointment.status.in_({"cancelled", "superseded"}))
    walkin = window.visibility == "walkin"
    salida = {}
    for a in q.all():
        if a.scheduled_at:
            hora = window.start_time if walkin else a.scheduled_at.time()
            salida[hora] = salida.get(hora, 0) + 1
    return salida


def _viejo_free_slots(db, window):
    ocupacion = _viejo_occupancy(db, window)
    cupo = int(window.capacity or 1)
    return [h for h in SlotService.slots(window) if ocupacion.get(h, 0) < cupo]


def _viejo_offerable_slots(db, window, ahora):
    from itcj2.config import get_settings
    minimo = ahora + timedelta(minutes=get_settings().TITULATEC_SELF_BOOK_MIN_LEAD_MINUTES)
    dia = window.review_day.date
    libres = _viejo_free_slots(db, window)
    if window.visibility == "walkin":
        if not libres or datetime.combine(dia, window.end_time) < minimo:
            return []
        return libres
    return [h for h in libres if datetime.combine(dia, h) >= minimo]


def _viejo_offerable_windows(db, proc, ahora):
    from itcj2.apps.titulatec.models import CohortReviewDay, ReviewWindow
    if proc is None or proc.program_id is None:
        return []
    dias = (db.query(CohortReviewDay)
            .filter(CohortReviewDay.cohort_id == proc.cohort_id,
                    CohortReviewDay.is_closed.is_(False),
                    CohortReviewDay.date >= ahora.date())
            .order_by(CohortReviewDay.date).all())
    if not dias:
        return []
    por_id = {d.id: d for d in dias}
    ventanas = (db.query(ReviewWindow)
                .filter(ReviewWindow.review_day_id.in_(list(por_id)),
                        ReviewWindow.status == "open",
                        ReviewWindow.visibility.in_(_VISIBLES))
                .order_by(ReviewWindow.start_time, ReviewWindow.id).all())
    if not ventanas:
        return []
    atienden = _viejo_owners_serving(
        db, {w.owner_user_id for w in ventanas}, proc.program_id)
    return [(por_id[w.review_day_id], w) for w in ventanas
            if w.owner_user_id in atienden]


def _viejo_offer(db, process_id, ahora):
    from itcj2.apps.titulatec.models import TitulationProcess
    from itcj2.core.models.user import User

    proc = db.get(TitulationProcess, int(process_id))
    pares = _viejo_offerable_windows(db, proc, ahora)
    if not pares:
        return []
    duenos = {w.owner_user_id for _, w in pares}
    nombres = {u.id: u for u in db.query(User).filter(User.id.in_(duenos)).all()}

    por_dia: dict = {}
    for dia, w in pares:
        item = {"window_id": w.id, "visibility": w.visibility,
                "start_time": w.start_time, "end_time": w.end_time,
                "location": w.location, "slots": []}
        if w.visibility == "bookable":
            item["slots"] = _viejo_offerable_slots(db, w, ahora)
            if not item["slots"]:
                continue
        else:
            if datetime.combine(dia.date, w.end_time) <= ahora:
                continue
            item["slots"] = _viejo_offerable_slots(db, w, ahora)
            capacidad = int(w.capacity or 1)
            ocupados = _viejo_occupancy(db, w).get(w.start_time, 0)
            item["capacity"] = capacidad
            item["places_left"] = max(0, capacidad - ocupados)
            item["reservable"] = bool(item["slots"])
            item["motivo"] = None if item["reservable"] else (
                "lleno" if item["places_left"] <= 0 else "cierra_pronto")
        por_dia.setdefault(dia.date, {}).setdefault(w.owner_user_id, []).append(item)

    def _nombre(user):
        return (getattr(user, "full_name", None) or "").strip() or "Servicios Escolares"

    salida = []
    for fecha in sorted(por_dia):
        grupos = por_dia[fecha]
        orden = sorted(grupos, key=lambda uid: _nombre(nombres.get(uid)))
        salida.append({
            "date": fecha,
            "owners": [{"owner_id": uid, "owner_name": _nombre(nombres.get(uid)),
                        "windows": grupos[uid]} for uid in orden],
        })
    return salida


# ===========================================================================
# 1. Alcance en lote: `_program_ids_for_users`
# ===========================================================================
@pytest.fixture()
def alcance(db_session, titulatec_app, make_program, make_user, make_role,
            make_position, assign_position, link_programs, bind_position_role,
            make_perms, grant_user_role):
    """Un usuario por cada rama del predicado de alcance."""
    from itcj2.core.models.app import App
    from itcj2.core.models.position import PositionAppPerm, PositionAppRole

    n = next(_SEQ)
    A = make_program(f"Ing. Alcance A R4 {n}")
    B = make_program(f"Ing. Alcance B R4 {n}")
    C = make_program(f"Ing. Alcance C R4 {n}")
    rol = make_role(f"tt_test_alcance_r4_{n}", ("titulatec.process.page.list",))
    perm = make_perms(["titulatec.process.page.list"])["titulatec.process.page.list"]
    ayer = date.today() - timedelta(days=1)
    manana = date.today() + timedelta(days=1)

    def con_puesto(programas, *, via="rol", **kw):
        user = make_user(first_name="ALC", last_name=f"R4{next(_SEQ)}")
        pos = make_position(title="Puesto de alcance R4")
        link_programs(pos, programas)
        if via == "rol":
            bind_position_role(pos, rol)
        elif via == "perm":
            db_session.add(PositionAppPerm(position_id=pos.id, app_id=titulatec_app.id,
                                           perm_id=perm.id, allow=True))
        elif via == "perm_negado":
            db_session.add(PositionAppPerm(position_id=pos.id, app_id=titulatec_app.id,
                                           perm_id=perm.id, allow=False))
        elif via == "otra_app":
            otra = App(key=f"tt_otra_app_r4_{n}", name="Otra app R4", is_active=True,
                       visible_to_students=True, mobile_enabled=True)
            db_session.add(otra)
            db_session.flush()
            db_session.add(PositionAppRole(position_id=pos.id, app_id=otra.id,
                                           role_id=rol.id))
        db_session.flush()
        assign_position(user, pos, **{k: v for k, v in kw.items()
                                      if k in ("start_date", "end_date", "is_active")})
        if kw.get("puesto_apagado"):
            pos.is_active = False
            db_session.flush()
        return user, pos

    u = {}
    u["rol"], _ = con_puesto([A])
    u["perm"], _ = con_puesto([B], via="perm")
    u["perm_negado"], _ = con_puesto([C], via="perm_negado")
    u["otra_app"], _ = con_puesto([A], via="otra_app")
    u["vencido"], _ = con_puesto([A], end_date=ayer)
    u["futuro"], _ = con_puesto([A], start_date=manana)
    u["puesto_apagado"], _ = con_puesto([A], puesto_apagado=True)
    u["asignacion_apagada"], _ = con_puesto([A], is_active=False)

    # Varios puestos: rol con A y B, permiso con C y B (repite B), y un puesto
    # con rol pero SIN carreras.
    u["varios"], p1 = con_puesto([A, B])
    p2 = make_position(title="Segundo puesto R4")
    link_programs(p2, [C, B])
    db_session.add(PositionAppPerm(position_id=p2.id, app_id=titulatec_app.id,
                                   perm_id=perm.id, allow=True))
    p3 = make_position(title="Tercer puesto R4 sin carreras")
    bind_position_role(p3, rol)
    db_session.flush()
    assign_position(u["varios"], p2)
    assign_position(u["varios"], p3)

    # Un puesto COMPARTIDO por dos usuarios: las dos filas salen de un mismo
    # `ProgramPosition`, así que el reparto por usuario no puede mezclarlos.
    u["comp_1"], pc = con_puesto([A, C])
    u["comp_2"] = make_user(first_name="ALC", last_name=f"R4{next(_SEQ)}")
    assign_position(u["comp_2"], pc)

    u["sin_puesto"] = make_user(first_name="ALC", last_name=f"R4{next(_SEQ)}")
    u["directo"] = make_user(first_name="ALC", last_name=f"R4{next(_SEQ)}")
    grant_user_role(u["directo"], rol)
    return {"u": u, "A": A, "B": B, "C": C}


def test_la_version_en_lote_es_igual_al_join_por_usuario(db_session, alcance):
    from itcj2.apps.titulatec.services.scope_service import _program_ids_for_users

    u, A, B, C = alcance["u"], alcance["A"], alcance["B"], alcance["C"]
    ids = [x.id for x in u.values()]

    mapa = _program_ids_for_users(db_session, ids)

    esperado = {uid: _viejo_program_ids(db_session, uid) for uid in ids}
    assert mapa == esperado
    # Que el oráculo no compare vacíos: las ramas que SÍ dan carreras.
    assert esperado[u["rol"].id] == {A.id}
    assert esperado[u["perm"].id] == {B.id}
    assert esperado[u["varios"].id] == {A.id, B.id, C.id}
    assert esperado[u["comp_1"].id] == esperado[u["comp_2"].id] == {A.id, C.id}
    # Y las que NO: fail-closed.
    for rama in ("perm_negado", "otra_app", "vencido", "futuro", "puesto_apagado",
                 "asignacion_apagada", "sin_puesto", "directo"):
        assert mapa[u[rama].id] == set(), rama


def test_la_version_en_lote_devuelve_todos_los_pedidos_y_tolera_basura(
        db_session, alcance):
    from itcj2.apps.titulatec.services.scope_service import _program_ids_for_users

    u = alcance["u"]
    # Repetidos, un id que no existe y una colección que no es lista.
    mapa = _program_ids_for_users(
        db_session, [u["rol"].id, u["rol"].id, -12345, u["perm"].id])
    assert set(mapa) == {u["rol"].id, -12345, u["perm"].id}
    assert mapa[-12345] == set()
    assert mapa[u["rol"].id] == {alcance["A"].id}

    assert _program_ids_for_users(db_session, {u["perm"].id}) == {
        u["perm"].id: {alcance["B"].id}}
    assert _contar(db_session, lambda: _program_ids_for_users(db_session, [])) == 0
    assert _program_ids_for_users(db_session, []) == {}


def test_la_singular_devuelve_lo_mismo_que_siempre(db_session, alcance):
    from itcj2.apps.titulatec.services.scope_service import _program_ids_for_user

    for nombre, usuario in alcance["u"].items():
        assert (_program_ids_for_user(db_session, usuario.id)
                == _viejo_program_ids(db_session, usuario.id)), nombre


def test_las_consultas_del_alcance_no_crecen_con_los_usuarios(db_session, alcance):
    from itcj2.apps.titulatec.services.scope_service import _program_ids_for_users

    ids = [x.id for x in alcance["u"].values()]
    uno = _contar(db_session, lambda: _program_ids_for_users(db_session, ids[:1]))
    todos = _contar(db_session, lambda: _program_ids_for_users(db_session, ids))
    assert len(ids) >= 10
    assert uno == todos


def _funcion(path: Path, nombre: str) -> ast.FunctionDef:
    arbol = ast.parse(path.read_text(encoding="utf-8"))
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.FunctionDef) and nodo.name == nombre:
            return nodo
    raise AssertionError(f"{nombre} no existe en {path.name}")


def _llamadas(fn: ast.FunctionDef) -> set[str]:
    out = set()
    for nodo in ast.walk(fn):
        if isinstance(nodo, ast.Call):
            f = nodo.func
            out.add(f.id if isinstance(f, ast.Name) else getattr(f, "attr", ""))
    return out


def test_una_sola_implementacion_del_join_la_singular_delega():
    """El join `ProgramPosition ⋈ Position ⋈ UserPosition ⋈ PositionApp*` vive
    UNA vez. La singular no arma ninguna consulta; `_owners_serving` ya no
    pregunta dueño por dueño."""
    scope = _ROOT / "scope_service.py"
    singular = _funcion(scope, "_program_ids_for_user")
    plural = _funcion(scope, "_program_ids_for_users")
    assert "query" not in _llamadas(singular)
    assert "_program_ids_for_users" in _llamadas(singular)
    assert "query" in _llamadas(plural)

    owners = _funcion(_ROOT / "self_booking_service.py", "_owners_serving")
    llamadas = _llamadas(owners)
    assert "_program_ids_for_users" in llamadas
    assert "_program_ids_for_user" not in llamadas


# ===========================================================================
# 2. `_owners_serving`
# ===========================================================================
def test_owners_serving_es_igual_al_viejo(db_session, alcance):
    u, A, B, C = alcance["u"], alcance["A"], alcance["B"], alcance["C"]
    duenos = {x.id for x in u.values()} | {-777}

    for programa in (A, B, C):
        assert (SelfBookingService._owners_serving(db_session, duenos, programa.id)
                == _viejo_owners_serving(db_session, duenos, programa.id))
    sirven_a = SelfBookingService._owners_serving(db_session, duenos, A.id)
    assert {u["rol"].id, u["varios"].id, u["comp_1"].id, u["comp_2"].id} <= sirven_a
    assert not ({u["perm"].id, u["vencido"].id, u["otra_app"].id} & sirven_a)

    assert SelfBookingService._owners_serving(db_session, set(), A.id) == set()
    assert SelfBookingService._owners_serving(db_session, duenos, None) == set()
    assert SelfBookingService._owners_serving(db_session, duenos, 0) == set()
    assert _contar(db_session, lambda: SelfBookingService._owners_serving(
        db_session, set(), A.id)) == 0


# ===========================================================================
# 3. `offer`: equivalencia con el oráculo por ventana
# ===========================================================================
@pytest.fixture()
def oferta_esc(db_session, seed_phase_defs, seed_document_types, make_program,
               make_cohort, make_review_day, make_officer, make_student, make_process,
               make_review_window, make_appointment, assign_position):
    """Todos los casos de la oferta en una convocatoria propia."""
    seed_phase_defs()
    seed_document_types()
    n = next(_SEQ)
    A = make_program(f"Ing. Oferta A R4 {n}")
    B = make_program(f"Ing. Oferta B R4 {n}")
    cohort = make_cohort()
    d1 = make_review_day(cohort, day=_D1)
    d2 = make_review_day(cohort, day=_D2)
    d3 = make_review_day(cohort, day=_D3)
    d3.is_closed = True
    db_session.flush()

    o1, pos1 = make_officer([A], first_name="ANA")
    o2, pos2 = make_officer([A], first_name="BETO")
    o_b, pos_b = make_officer([B], first_name="CARLA")      # otra carrera
    o_v, pos_v = make_officer([A], first_name="DANI")       # puesto vencido
    o_m, pos_m = make_officer([A, B], first_name="ELIA")    # atiende las dos
    from itcj2.core.models.position import UserPosition
    (db_session.query(UserPosition)
     .filter_by(user_id=o_v.id, position_id=pos_v.id)
     .update({"end_date": date.today() - timedelta(days=1)}))
    db_session.flush()

    def ventana(dia, dueno, pos, ini, fin, *, slot=30, cap=1, vis="bookable",
                status="open"):
        return make_review_window(dia, dueno, start=ini, end=fin, slot=slot, cap=cap,
                                  visibility=vis, status=status, position=pos,
                                  location=f"Edif {ini}")

    w = {
        "f_parcial": ventana(d1, o1, pos1, "09:00", "11:00", cap=2),
        "w_con_lugar": ventana(d1, o1, pos1, "12:00", "14:00", cap=3, vis="walkin"),
        "f_llena": ventana(d1, o1, pos1, "16:00", "16:30", cap=1),
        "w_lleno": ventana(d1, o2, pos2, "08:00", "09:00", cap=1, vis="walkin"),
        "f_vacia": ventana(d1, o2, pos2, "15:00", "16:00", slot=20, cap=1),
        "privada": ventana(d2, o2, pos2, "09:00", "10:00", vis="private"),
        "pausada": ventana(d2, o2, pos2, "10:00", "11:00", status="paused"),
        "f_d2": ventana(d2, o2, pos2, "11:00", "12:00"),
        "f_otra_carrera": ventana(d1, o_b, pos_b, "09:00", "10:00"),
        "f_vencido": ventana(d1, o_v, pos_v, "10:00", "11:00"),
        "w_multi": ventana(d2, o_m, pos_m, "10:00", "12:00", cap=2, vis="walkin"),
        "f_cerrado": ventana(d3, o1, pos1, "09:00", "10:00"),
    }

    def proceso(programa=A):
        return make_process(make_student(), cohort=cohort, program=programa,
                            current_phase=2)

    def cita(ventana_, hhmm, status="scheduled", is_current=True):
        a = make_appointment(proceso(),
                             when=datetime.combine(ventana_.review_day.date, _t(hhmm)),
                             status=status, is_current=is_current)
        a.window_id = ventana_.id
        db_session.flush()
        return a

    # f_parcial (cupo 2): 09:00 llena, 09:30 con uno, 10:00 llena por un no_show NO
    # vigente (sigue ocupando) + una viva, 10:30 con una cancelada (libera), 09:15
    # fuera de la rejilla.
    cita(w["f_parcial"], "09:00")
    cita(w["f_parcial"], "09:00", status="confirmed")
    cita(w["f_parcial"], "09:30", status="in_progress")
    cita(w["f_parcial"], "10:00", status="no_show", is_current=False)
    cita(w["f_parcial"], "10:00")
    cita(w["f_parcial"], "10:30", status="cancelled", is_current=False)
    cita(w["f_parcial"], "09:15")
    # w_con_lugar (cupo total 3): dos vivas (una legada a las 13:00) y una cancelada.
    cita(w["w_con_lugar"], "12:00")
    cita(w["w_con_lugar"], "13:00")
    cita(w["w_con_lugar"], "12:00", status="cancelled", is_current=False)
    # w_lleno (cupo 1) y f_llena (1 franja, cupo 1).
    cita(w["w_lleno"], "08:00")
    cita(w["f_llena"], "16:00")
    cita(w["w_multi"], "10:00", status="attended", is_current=False)

    return {"proc": proceso(), "w": w, "A": A, "B": B, "cohort": cohort,
            "duenos": {"o1": o1, "o2": o2, "o_b": o_b, "o_v": o_v, "o_m": o_m}}


_RELOJES = {
    "antes_del_dia": datetime.combine(_D1 - timedelta(days=1), time(8, 0)),
    "a_media_atencion": datetime.combine(_D1, time(10, 15)),
    "minutos_antes_del_cierre": datetime.combine(_D1, time(13, 30)),
    "segundo_dia": datetime.combine(_D2, time(8, 0)),
}


@pytest.mark.parametrize("reloj", list(_RELOJES))
def test_la_oferta_en_lote_es_igual_a_la_de_ventana_por_ventana(
        db_session, oferta_esc, monkeypatch, reloj):
    ahora = _RELOJES[reloj]
    monkeypatch.setattr(sb_mod, "db_now", lambda: ahora)

    nueva = SelfBookingService.offer(db_session, oferta_esc["proc"].id)
    vieja = _viejo_offer(db_session, oferta_esc["proc"].id, ahora)

    assert nueva == vieja
    assert nueva, "el escenario tiene que ofrecer algo en cada reloj"


def test_la_oferta_cubre_los_casos_que_importan(db_session, oferta_esc, monkeypatch):
    """El oráculo no compara vacíos: salen los casos que justifican la prueba."""
    w = oferta_esc["w"]

    def ventanas(oferta):
        return {x["window_id"]: x for d in oferta for o in d["owners"]
                for x in o["windows"]}

    monkeypatch.setattr(sb_mod, "db_now", lambda: _RELOJES["antes_del_dia"])
    v = ventanas(SelfBookingService.offer(db_session, oferta_esc["proc"].id))
    # 09:00 llena (cupo 2); 09:30 con uno; 10:00 llena (no_show + viva); 10:30 libre
    # (la cancelada libera).
    assert v[w["f_parcial"].id]["slots"] == [time(9, 30), time(10, 30)]
    assert v[w["w_con_lugar"].id]["places_left"] == 1
    assert v[w["w_con_lugar"].id]["reservable"] is True
    assert v[w["w_lleno"].id]["motivo"] == "lleno"
    assert v[w["f_vacia"].id]["slots"] == [time(15, 0), time(15, 20), time(15, 40)]
    assert v[w["w_multi"].id]["capacity"] == 2
    assert w["f_llena"].id not in v, "sin franjas libres no es oferta"
    for fuera in ("privada", "pausada", "f_otra_carrera", "f_vencido", "f_cerrado"):
        assert w[fuera].id not in v, fuera

    monkeypatch.setattr(sb_mod, "db_now", lambda: _RELOJES["minutos_antes_del_cierre"])
    v = ventanas(SelfBookingService.offer(db_session, oferta_esc["proc"].id))
    assert v[w["w_con_lugar"].id]["motivo"] == "cierra_pronto"
    assert v[w["w_con_lugar"].id]["places_left"] == 1
    assert w["w_lleno"].id not in v, "el sin horario que ya terminó no se anuncia"


def test_las_franjas_libres_con_ocupacion_ya_leida_son_las_de_siempre(
        db_session, oferta_esc, monkeypatch):
    """`free_slots_from` (la comparación contra el cupo, sin BD) y
    `_offerable_slots` con la ocupación ya leída dan lo mismo que leerla ventana
    por ventana: `free_slots` delega en la primera, y `_offerable_slots` sin
    `ocupacion` sigue funcionando para quien lo llame con una sola ventana."""
    ahora = _RELOJES["antes_del_dia"]
    monkeypatch.setattr(sb_mod, "db_now", lambda: ahora)
    ventanas = list(oferta_esc["w"].values())
    mapa = SlotService.occupancy_map(db_session, ventanas)

    for nombre, w in oferta_esc["w"].items():
        oraculo = _viejo_free_slots(db_session, w)
        assert SlotService.free_slots(db_session, w) == oraculo, nombre
        assert SlotService.free_slots_from(w, mapa[w.id]) == oraculo, nombre
        if w.visibility in _VISIBLES:
            assert (SelfBookingService._offerable_slots(db_session, w, ahora=ahora)
                    == SelfBookingService._offerable_slots(
                        db_session, w, ahora=ahora, ocupacion=mapa[w.id])
                    == _viejo_offerable_slots(db_session, w, ahora)), nombre


# ===========================================================================
# 4. Presupuesto de consultas de `offer`
# ===========================================================================
@pytest.fixture()
def armar_oferta(db_session, seed_phase_defs, seed_document_types, make_program,
                 make_cohort, make_review_day, make_officer, make_student,
                 make_process, make_review_window, make_appointment):
    """`armar(n_duenos, n_ventanas)` -> proceso con una oferta de ese tamaño.

    Cada ventana nace con franjas libres y con citas vivas y no vigentes, así
    que ninguna se omite de la oferta y la ocupación SÍ tiene filas que leer.
    Se alternan franjas y sin horario (el sin horario pagaba DOS consultas).
    """
    seed_phase_defs()
    seed_document_types()

    def _armar(n_duenos: int, n_ventanas: int):
        n = next(_SEQ)
        programa = make_program(f"Ing. Presupuesto Oferta R4 {n}")
        cohort = make_cohort()
        dia = make_review_day(cohort, day=date(2029, 7, 2))
        duenos = [make_officer([programa], first_name=f"DUENO{i}")
                  for i in range(n_duenos)]
        proc = make_process(make_student(), cohort=cohort, program=programa,
                            current_phase=2)
        for i in range(n_ventanas):
            usuario, pos = duenos[i % n_duenos]
            walkin = i % 2 == 1
            w = make_review_window(
                dia, usuario, start=f"{7 + i:02d}:00", end=f"{7 + i:02d}:50",
                slot=10, cap=3 if walkin else 2, position=pos,
                visibility="walkin" if walkin else "bookable")
            for status, vig in (("scheduled", True), ("no_show", False),
                                ("cancelled", False)):
                a = make_appointment(
                    make_process(make_student(), cohort=cohort, program=programa,
                                 current_phase=2),
                    when=datetime.combine(dia.date, time(7 + i, 0)),
                    status=status, is_current=vig)
                a.window_id = w.id
            db_session.flush()
        return proc

    return _armar


def _medir_oferta(db_session, proc, filtro=None):
    db_session.expire_all()          # como una petición nueva: nada en caché
    resultado = {}

    def _correr():
        resultado["oferta"] = SelfBookingService.offer(db_session, proc.id)

    n = _contar(db_session, _correr, filtro)
    ventanas = [x for d in resultado["oferta"] for o in d["owners"]
                for x in o["windows"]]
    return n, ventanas, resultado["oferta"]


def test_la_oferta_hace_las_mismas_consultas_con_2_que_con_5_duenos(
        db_session, armar_oferta):
    dos, v2, o2 = _medir_oferta(db_session, armar_oferta(2, 6))
    cinco, v5, o5 = _medir_oferta(db_session, armar_oferta(5, 6))

    assert len(v2) == len(v5) == 6, "ninguna ventana se omite: la prueba no es vacía"
    assert [len(d["owners"]) for d in o2] == [2]
    assert [len(d["owners"]) for d in o5] == [5]
    assert dos == cinco


def test_la_oferta_hace_las_mismas_consultas_con_2_que_con_6_ventanas(
        db_session, armar_oferta):
    dos, v2, _ = _medir_oferta(db_session, armar_oferta(2, 2))
    seis, v6, _ = _medir_oferta(db_session, armar_oferta(2, 6))

    assert len(v2) == 2 and len(v6) == 6
    assert dos == seis


def test_la_oferta_lee_las_citas_una_sola_vez(db_session, armar_oferta):
    n, ventanas, _ = _medir_oferta(
        db_session, armar_oferta(3, 6), filtro="titulatec_review_appointments")

    assert len(ventanas) == 6
    assert n == 1, "una consulta de ocupación para TODAS las ventanas"


def test_la_oferta_lee_el_alcance_de_los_duenos_una_sola_vez(db_session, armar_oferta):
    """Dos consultas de `core_program_positions` (por rol y por permiso), sin
    importar cuántos dueños: antes eran dos POR dueño."""
    n, _, _ = _medir_oferta(
        db_session, armar_oferta(5, 6), filtro="core_program_positions")

    assert n == 2
