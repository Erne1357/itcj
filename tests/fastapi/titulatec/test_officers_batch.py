"""Encargados sin N+1 (spec 2026-10-05-titulatec-rendimiento-design.md §3.5,
hallazgo H10): `OfficerService.list_officers` y `pages.officers._body_ctx`
cargan usuarios y carreras en lote, no una consulta por puesto / por usuario.

El criterio de aceptación es la EQUIVALENCIA, así que este archivo lleva un
ORÁCULO congelado -- la copia literal de `list_officers` y del armado de
`dept_users` de `_body_ctx` de antes de esta tarea (`_viejo_*`) -- y compara
contra él, igual que `test_slot_occupancy_batch.py`:

* puesto con dos usuarios y dos carreras, uno sin carreras, uno sin usuarios,
  un usuario en DOS puestos, una cuenta con `is_active` apagado (sigue en la
  lista, marcada), una asignación apagada (no cuenta), un puesto apagado y uno
  con otro prefijo de código (no salen) y el `code_prefix` explícito;
* `dept_users` ordenado por nombre con el desempate por id de siempre.

Presupuesto: las MISMAS consultas con 2 que con 5 encargados, en el servicio
y en el contexto de la pantalla completa.

Todo se siembra en un departamento propio: la base de dev trae datos reales y
nada de esto afirma totales de la base.
"""
from __future__ import annotations

import itertools

import pytest
from sqlalchemy import event

from itcj2.apps.titulatec.services.officer_service import OfficerService

_SEQ = itertools.count(1)


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
# Oráculo congelado: lo de antes de R4, una consulta por puesto / por usuario.
# ---------------------------------------------------------------------------
def _viejo_list_officers(db, department_id, *, code_prefix="se_officer_"):
    from itcj2.core.models.position import Position, ProgramPosition, UserPosition
    from itcj2.core.models.program import Program
    from itcj2.core.models.user import User

    out = []
    positions = (
        db.query(Position)
        .filter(Position.department_id == department_id,
                Position.code.like(f"{code_prefix}%"), Position.is_active.is_(True))
        .all()
    )
    for pos in positions:
        users = (
            db.query(User).join(UserPosition, UserPosition.user_id == User.id)
            .filter(UserPosition.position_id == pos.id,
                    UserPosition.is_active.is_(True)).all()
        )
        progs = (
            db.query(Program).join(ProgramPosition, ProgramPosition.program_id == Program.id)
            .filter(ProgramPosition.position_id == pos.id).all()
        )
        out.append({
            "id": pos.id, "name": pos.title,
            "users": [{"id": u.id, "name": u.full_name,
                       "is_active": bool(u.is_active)} for u in users],
            "programs": [{"id": p.id, "name": p.name} for p in progs],
        })
    return out


def _viejo_dept_users(db, department_id):
    from itcj2.core.models.user import User

    usuarios = []
    for uid in sorted(OfficerService.department_user_ids(db, department_id)):
        u = db.get(User, uid)
        if u is None:
            continue
        usuarios.append({"id": uid, "name": u.full_name,
                         "is_active": bool(u.is_active)})
    usuarios.sort(key=lambda x: x["name"] or "")
    return usuarios


def _normalizar(officers):
    """El servicio nunca prometió un orden: se compara por id."""
    return sorted(
        ({"id": o["id"], "name": o["name"],
          "users": sorted(o["users"], key=lambda x: x["id"]),
          "programs": sorted(o["programs"], key=lambda x: x["id"])}
         for o in officers),
        key=lambda o: o["id"])


# ---------------------------------------------------------------------------
# Escenarios
# ---------------------------------------------------------------------------
@pytest.fixture()
def armar_depto(db_session, make_department, make_position, make_user, assign_position,
                make_program, link_programs):
    """`armar(n)` -> (departamento, [(puesto, [usuarios], [carreras])]).

    Cada encargado nace con 2 usuarios y 2 carreras, así que el costo del N+1
    viejo crecía con puestos, usuarios y carreras a la vez.
    """
    def _armar(n_encargados: int):
        n = next(_SEQ)
        dept = make_department(name=f"Depto Encargados R4 {n}")
        progs = [make_program(f"Ing. Encargados R4 {n}-{i}") for i in range(3)]
        out = []
        for i in range(n_encargados):
            pos = make_position(code=f"se_officer_r4_{n}_{i}", title=f"Encargado {i}",
                                department=dept)
            usuarios = [make_user(first_name=f"ENC{i}{j}", last_name=f"R4{n}")
                        for j in range(2)]
            for u in usuarios:
                assign_position(u, pos)
            carreras = [progs[i % 3], progs[(i + 1) % 3]]
            link_programs(pos, carreras)
            out.append((pos, usuarios, carreras))
        return dept, out

    return _armar


@pytest.fixture()
def depto_esc(db_session, make_department, make_position, make_user, assign_position,
              make_program, link_programs):
    """Todos los casos de `list_officers` en un departamento propio."""
    n = next(_SEQ)
    dept = make_department(name=f"Depto Casos R4 {n}")
    A = make_program(f"Ing. Casos A R4 {n}")
    B = make_program(f"Ing. Casos B R4 {n}")

    def puesto(codigo, **kw):
        return make_position(code=f"{codigo}_{n}", title=f"Puesto {codigo}",
                             department=dept, **kw)

    u1 = make_user(first_name="LAURA", last_name="UNO")
    u2 = make_user(first_name="MARIO", last_name="DOS", is_active=False)
    u3 = make_user(first_name="NORA", last_name="TRES")
    # Mismo nombre que u3: el desempate del listado de usuarios es por id.
    u4 = make_user(first_name="NORA", last_name="TRES")
    u5 = make_user(first_name="OMAR", last_name="CINCO")

    off1 = puesto("se_officer_a")
    assign_position(u1, off1)
    assign_position(u2, off1)
    link_programs(off1, [A, B])

    off2 = puesto("se_officer_b")
    assign_position(u1, off2)                  # u1 también aquí
    assign_position(u3, off2)
    assign_position(u4, off2, is_active=False)  # asignación apagada: no cuenta

    off3 = puesto("se_officer_c")              # sin usuarios
    link_programs(off3, [A])

    off4 = puesto("se_officer_d")              # puesto apagado: no sale
    assign_position(u5, off4)
    link_programs(off4, [B])
    off4.is_active = False
    db_session.flush()

    off5 = puesto("otro_prefijo")              # otro prefijo: no sale por defecto
    assign_position(u5, off5)
    link_programs(off5, [A, B])

    # u4 sí está en el departamento por una asignación vigente de OTRO puesto.
    otro = puesto("puesto_compartido")
    assign_position(u4, otro)
    return {"dept": dept, "A": A, "B": B, "off": (off1, off2, off3, off4, off5),
            "users": (u1, u2, u3, u4, u5)}


# ===========================================================================
# Equivalencia
# ===========================================================================
def test_list_officers_en_lote_es_igual_al_oraculo(db_session, depto_esc):
    dept = depto_esc["dept"]

    nuevo = OfficerService.list_officers(db_session, dept.id)
    viejo = _viejo_list_officers(db_session, dept.id)

    assert _normalizar(nuevo) == _normalizar(viejo)
    # Que el oráculo no compare vacíos.
    por_id = {o["id"]: o for o in nuevo}
    off1, off2, off3, off4, off5 = depto_esc["off"]
    u1, u2, u3, u4, u5 = depto_esc["users"]
    assert set(por_id) == {off1.id, off2.id, off3.id}
    assert {u["id"] for u in por_id[off1.id]["users"]} == {u1.id, u2.id}
    assert [u["is_active"] for u in sorted(por_id[off1.id]["users"],
                                           key=lambda x: x["id"])] == [True, False]
    assert {p["id"] for p in por_id[off1.id]["programs"]} == {
        depto_esc["A"].id, depto_esc["B"].id}
    assert {u["id"] for u in por_id[off2.id]["users"]} == {u1.id, u3.id}
    assert por_id[off2.id]["programs"] == []
    assert por_id[off3.id]["users"] == []
    assert [p["id"] for p in por_id[off3.id]["programs"]] == [depto_esc["A"].id]


def test_list_officers_respeta_el_prefijo_de_codigo(db_session, depto_esc):
    dept = depto_esc["dept"]
    off5 = depto_esc["off"][4]

    nuevo = OfficerService.list_officers(db_session, dept.id, code_prefix="otro_prefijo")
    viejo = _viejo_list_officers(db_session, dept.id, code_prefix="otro_prefijo")

    assert _normalizar(nuevo) == _normalizar(viejo)
    assert [o["id"] for o in nuevo] == [off5.id]


def test_list_officers_sin_puestos_devuelve_lista_vacia_sin_mas_consultas(
        db_session, make_department):
    dept = make_department(name=f"Depto Vacio R4 {next(_SEQ)}")

    assert OfficerService.list_officers(db_session, dept.id) == []
    assert _contar(db_session,
                   lambda: OfficerService.list_officers(db_session, dept.id)) == 1


def test_la_pantalla_trae_el_mismo_contexto_que_antes(db_session, depto_esc):
    from itcj2.apps.titulatec.pages.officers import _body_ctx
    from itcj2.core.models.program import Program

    dept = depto_esc["dept"]

    ctx = _body_ctx(db_session, dept.id)

    assert _normalizar(ctx["officers"]) == _normalizar(
        _viejo_list_officers(db_session, dept.id))
    esperado = _viejo_dept_users(db_session, dept.id)
    assert ctx["dept_users"] == esperado
    assert ctx["programs"] == [{"id": p.id, "name": p.name} for p in
                               db_session.query(Program).order_by(Program.name).all()]
    assert ctx["reactivated"] == []
    # El empate de nombre (NORA TRES x2) se resuelve por id, como siempre.
    u1, u2, u3, u4, u5 = depto_esc["users"]
    nombres = [x["id"] for x in ctx["dept_users"]]
    assert nombres.index(u3.id) < nombres.index(u4.id)
    # u5 solo está en el puesto apagado y en el de otro prefijo: el último es
    # del departamento, así que SÍ sale en el selector (como antes).
    assert u5.id in nombres
    assert {u1.id, u2.id, u3.id, u4.id, u5.id} == set(nombres)


def test_la_pantalla_conserva_las_cuentas_inactivas_marcadas(db_session, depto_esc):
    from itcj2.apps.titulatec.pages.officers import _body_ctx

    u2 = depto_esc["users"][1]
    ctx = _body_ctx(db_session, depto_esc["dept"].id)

    marcadas = {x["id"]: x["is_active"] for x in ctx["dept_users"]}
    assert marcadas[u2.id] is False
    assert sum(1 for v in marcadas.values() if not v) == 1


def test_la_pantalla_reenvia_las_cuentas_reactivadas(db_session, depto_esc):
    from itcj2.apps.titulatec.pages.officers import _body_ctx

    ctx = _body_ctx(db_session, depto_esc["dept"].id,
                    reactivated=[{"id": 1, "name": "X"}])
    assert ctx["reactivated"] == [{"id": 1, "name": "X"}]


# ===========================================================================
# Presupuesto de consultas
# ===========================================================================
def _medir(db_session, fn):
    db_session.expire_all()          # como una petición nueva: nada en caché
    return _contar(db_session, fn)


def test_list_officers_hace_las_mismas_consultas_con_2_que_con_5_encargados(
        db_session, armar_depto):
    dept2, filas2 = armar_depto(2)
    dept5, filas5 = armar_depto(5)

    dos = _medir(db_session, lambda: OfficerService.list_officers(db_session, dept2.id))
    cinco = _medir(db_session, lambda: OfficerService.list_officers(db_session, dept5.id))

    assert len(OfficerService.list_officers(db_session, dept2.id)) == 2
    assert len(OfficerService.list_officers(db_session, dept5.id)) == 5
    assert dos == cinco


def test_la_pantalla_hace_las_mismas_consultas_con_2_que_con_5_encargados(
        db_session, armar_depto):
    from itcj2.apps.titulatec.pages.officers import _body_ctx

    dept2, _ = armar_depto(2)
    dept5, _ = armar_depto(5)

    dos = _medir(db_session, lambda: _body_ctx(db_session, dept2.id))
    cinco = _medir(db_session, lambda: _body_ctx(db_session, dept5.id))

    ctx2 = _body_ctx(db_session, dept2.id)
    ctx5 = _body_ctx(db_session, dept5.id)
    assert len(ctx2["officers"]) == 2 and len(ctx2["dept_users"]) == 4
    assert len(ctx5["officers"]) == 5 and len(ctx5["dept_users"]) == 10
    assert dos == cinco


def test_los_usuarios_y_las_carreras_se_leen_una_sola_vez(db_session, armar_depto):
    dept, _ = armar_depto(5)

    db_session.expire_all()
    usuarios = _contar(db_session,
                       lambda: OfficerService.list_officers(db_session, dept.id),
                       filtro="core_user_positions")
    db_session.expire_all()
    carreras = _contar(db_session,
                       lambda: OfficerService.list_officers(db_session, dept.id),
                       filtro="core_program_positions")

    assert usuarios == 1
    assert carreras == 1
