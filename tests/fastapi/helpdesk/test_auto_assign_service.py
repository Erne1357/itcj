"""Motor de asignación automática (`AutoAssignService`, plan T4).

Se fija:
1. motor apagado → 1 consulta y no asigna;
2. gana la regla más específica (categoría+prioridad > categoría > prioridad > área);
3. turnos 1 y 1 con puntero circular (puntero huérfano → el primero);
4. menor carga cuenta solo ASSIGNED/IN_PROGRESS; empate → orden de turnos;
5. técnicos inactivos o sin rol del área se saltan; sin elegibles → PENDING;
6. el motor nunca lanza y la regla se lee con `FOR UPDATE`;
7. el número de consultas no crece con reglas, técnicos ni tickets activos.

La base de CI está vacía: todo se siembra aquí (prefijo `aa4_`).
"""
import itertools
from unittest.mock import patch

import pytest
from sqlalchemy import event

import itcj2.models  # noqa: F401
from itcj2.apps.helpdesk.models.assignment import Assignment
from itcj2.apps.helpdesk.models.assignment_rule import AssignmentRule
from itcj2.apps.helpdesk.models.status_log import StatusLog
from itcj2.apps.helpdesk.models.ticket import Ticket
from itcj2.apps.helpdesk.services.auto_assign_service import AutoAssignService
from itcj2.apps.helpdesk.services.helpdesk_settings_service import update_settings
from itcj2.core.models.app import App
from itcj2.core.models.user import User
from itcj2.core.models.user_app_role import UserAppRole

from ._catalog import ensure_helpdesk_category, ensure_role

MAX_QUERIES = 15
_seq = itertools.count(1)


def _commit(db, obj):
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def _user(db, name, *, active=True):
    return _commit(db, User(first_name="aa4", last_name=f"aa4_{name}", is_active=active))


def _grant(db, app, user, role):
    db.add(UserAppRole(user_id=user.id, app_id=app.id, role_id=role.id))
    db.commit()


@pytest.fixture()
def mundo(db_session):
    db = db_session
    app = db.query(App).filter_by(key="helpdesk").first() or _commit(
        db, App(key="helpdesk", name="Help desk", is_active=True))
    dev = ensure_role(db, "tech_desarrollo")
    sop = ensure_role(db, "tech_soporte")
    admin = _user(db, "admin")
    req = _user(db, "req")
    techs = {k: _user(db, k) for k in ("A", "B", "C")}
    for t in techs.values():
        _grant(db, app, t, dev)
    sin_rol = _user(db, "sinrol")
    _grant(db, app, sin_rol, sop)  # técnico, pero de la otra área
    inactivo = _user(db, "inactivo", active=False)
    _grant(db, app, inactivo, dev)
    # Reglas reales de la base dev no deben interferir (se deshace al final).
    db.query(AssignmentRule).update({"is_active": False})
    update_settings(db, user_id=admin.id, auto_assign_enabled=True)
    db.commit()
    return {
        "app": app, "admin": admin, "req": req, **techs,
        "sinrol": sin_rol, "inactivo": inactivo,
        "sii": ensure_helpdesk_category(db, "aa4_sii", "DESARROLLO"),
        "correo": ensure_helpdesk_category(db, "aa4_correo", "DESARROLLO"),
    }


def _ticket(db, m, *, cat="sii", priority="MEDIA", status="PENDING", assigned=None,
            team=None, area="DESARROLLO"):
    return _commit(db, Ticket(
        ticket_number=f"AA4-{next(_seq):06d}", requester_id=m["req"].id, area=area,
        category_id=m[cat].id, priority=priority, title="aa4 ticket",
        description="aa4 descripcion", status=status, assigned_to_user_id=assigned,
        assigned_to_team=team, created_by_id=m["req"].id, updated_by_id=m["req"].id,
    ))


def _rule(db, m, techs, *, cat=None, priority=None, strategy="round_robin", area="DESARROLLO",
          active=True, last=None):
    return _commit(db, AssignmentRule(
        area=area, category_id=m[cat].id if cat else None, priority=priority,
        strategy=strategy, technician_ids=[m[t].id for t in techs],
        last_assigned_user_id=m[last].id if last else None, is_active=active,
        created_by_id=m["admin"].id,
    ))


def _sql(db, fn):
    """Sentencias SQL que corre `fn()` sobre la conexión de la sesión."""
    stmts = []

    def _capturar(_conn, _cur, statement, *_a):
        # Artefacto del arnés (commit = RELEASE SAVEPOINT); en prod es el COMMIT del DBAPI.
        if "SAVEPOINT" not in statement:
            stmts.append(statement)

    conn = db.connection()
    event.listen(conn, "before_cursor_execute", _capturar)
    try:
        res = fn()
    finally:
        event.remove(conn, "before_cursor_execute", _capturar)
    return stmts, res


def _medir(db, ticket):
    # Como en la petición real: todo lo de la sesión viene expirado del commit.
    db.expire_all()
    return _sql(db, lambda: AutoAssignService.try_auto_assign(db, ticket))


# ==================== MOTOR APAGADO ====================
def test_motor_apagado_no_asigna_y_hace_una_consulta(db_session, mundo):
    _rule(db_session, mundo, ["A"])
    update_settings(db_session, user_id=mundo["admin"].id, auto_assign_enabled=False)
    db_session.commit()
    t = _ticket(db_session, mundo)

    stmts, res = _medir(db_session, t)

    assert res is None
    assert len(stmts) == 1, stmts
    db_session.refresh(t)
    assert t.status == "PENDING" and t.assigned_to_user_id is None


# ==================== COINCIDENCIA ====================
def test_regla_mas_especifica_gana(db_session, mundo):
    m = mundo
    solo_area = _rule(db_session, m, ["A"])
    solo_prio = _rule(db_session, m, ["A"], priority="ALTA")
    solo_cat = _rule(db_session, m, ["A"], cat="sii")
    cat_prio = _rule(db_session, m, ["A"], cat="sii", priority="ALTA")
    # Nunca deben ganar: otra categoría, otra prioridad, otra área.
    _rule(db_session, m, ["A"], cat="correo", priority="ALTA")
    _rule(db_session, m, ["A"], cat="sii", priority="BAJA")
    _rule(db_session, m, ["sinrol"], area="SOPORTE")
    t = _ticket(db_session, m, cat="sii", priority="ALTA")

    for esperada in (cat_prio, solo_cat, solo_prio, solo_area):
        assert AutoAssignService.match_rule(db_session, t).id == esperada.id
        esperada.is_active = False
        db_session.commit()
    assert AutoAssignService.match_rule(db_session, t) is None


def test_regla_inactiva_se_ignora(db_session, mundo):
    _rule(db_session, mundo, ["A"], cat="sii", active=False)
    t = _ticket(db_session, mundo)

    assert AutoAssignService.try_auto_assign(db_session, t) is None
    db_session.refresh(t)
    assert t.status == "PENDING" and t.assigned_to_user_id is None


def test_la_regla_se_lee_con_for_update(db_session, mundo):
    _rule(db_session, mundo, ["A"], cat="sii")
    t = _ticket(db_session, mundo)

    stmts, res = _medir(db_session, t)

    assert res is not None
    lectura = [s for s in stmts
               if s.lstrip().upper().startswith("SELECT") and "helpdesk_assignment_rules" in s]
    assert len(lectura) == 1, lectura
    assert "FOR UPDATE" in lectura[0].upper()


# ==================== TURNOS ====================
def test_turnos_alternan_uno_y_uno(db_session, mundo):
    m = mundo
    regla = _rule(db_session, m, ["A", "B"], cat="sii")

    elegidos = []
    for _ in range(3):
        a = AutoAssignService.try_auto_assign(db_session, _ticket(db_session, m))
        elegidos.append(a.assigned_to_user_id)

    assert elegidos == [m["A"].id, m["B"].id, m["A"].id]
    db_session.refresh(regla)
    assert regla.last_assigned_user_id == m["A"].id


def test_puntero_huerfano_empieza_por_el_primero(db_session, mundo):
    m = mundo
    _rule(db_session, m, ["A", "B"], cat="sii", last="C")

    a = AutoAssignService.try_auto_assign(db_session, _ticket(db_session, m))

    assert a.assigned_to_user_id == m["A"].id


def test_asignacion_deja_status_log_y_motivo(db_session, mundo):
    m = mundo
    regla = _rule(db_session, m, ["B"], cat="sii")
    t = _ticket(db_session, m)

    a = AutoAssignService.try_auto_assign(db_session, t)

    db_session.refresh(t)
    assert t.status == "ASSIGNED" and t.assigned_to_user_id == m["B"].id
    assert a.reason.startswith("Asignación automática")
    assert "DESARROLLO · aa4_sii · cualquier prioridad" in a.reason
    assert a.assigned_by_id == regla.created_by_id
    log = db_session.query(StatusLog).filter_by(ticket_id=t.id, to_status="ASSIGNED").one()
    assert log.from_status == "PENDING"


# ==================== MENOR CARGA ====================
def test_menor_carga_elige_al_de_menos_activos(db_session, mundo):
    m = mundo
    _rule(db_session, m, ["A", "B", "C"], cat="sii", strategy="least_loaded")
    _ticket(db_session, m, status="ASSIGNED", assigned=m["A"].id)
    _ticket(db_session, m, status="IN_PROGRESS", assigned=m["A"].id)
    _ticket(db_session, m, status="IN_PROGRESS", assigned=m["B"].id)
    for st in ("CLOSED", "CLOSED", "RESOLVED_SUCCESS"):  # no cuentan
        _ticket(db_session, m, status=st, assigned=m["C"].id)

    a = AutoAssignService.try_auto_assign(db_session, _ticket(db_session, m))
    assert a.assigned_to_user_id == m["C"].id  # A: 2, B: 1, C: 0 (cerrados no cuentan)

    _ticket(db_session, m, status="ASSIGNED", assigned=m["C"].id)  # C: 2 (con el de arriba)
    a = AutoAssignService.try_auto_assign(db_session, _ticket(db_session, m))
    assert a.assigned_to_user_id == m["B"].id


def test_menor_carga_empate_sigue_turno(db_session, mundo):
    m = mundo
    _rule(db_session, m, ["A", "B", "C"], cat="sii", strategy="least_loaded", last="A")

    a = AutoAssignService.try_auto_assign(db_session, _ticket(db_session, m))
    assert a.assigned_to_user_id == m["B"].id  # todos en 0 → el turno tras A
    a = AutoAssignService.try_auto_assign(db_session, _ticket(db_session, m))
    assert a.assigned_to_user_id == m["C"].id  # A y C en 0 → el turno tras B es C


# ==================== ELEGIBLES ====================
def test_tecnico_inactivo_o_sin_rol_se_salta(db_session, mundo):
    m = mundo
    _rule(db_session, m, ["sinrol", "inactivo", "A"], cat="sii")

    a = AutoAssignService.try_auto_assign(db_session, _ticket(db_session, m))

    assert a.assigned_to_user_id == m["A"].id


def test_sin_elegibles_queda_pending(db_session, mundo):
    m = mundo
    regla = _rule(db_session, m, ["sinrol", "inactivo"], cat="sii")
    t = _ticket(db_session, m)

    assert AutoAssignService.try_auto_assign(db_session, t) is None

    db_session.refresh(t)
    db_session.refresh(regla)
    assert t.status == "PENDING" and t.assigned_to_user_id is None
    assert regla.last_assigned_user_id is None
    assert db_session.query(Assignment).filter_by(ticket_id=t.id).count() == 0


def test_ticket_ya_asignado_no_se_toca(db_session, mundo):
    m = mundo
    _rule(db_session, m, ["A"], cat="sii")
    asignado = _ticket(db_session, m, status="ASSIGNED", assigned=m["B"].id)
    a_equipo = _ticket(db_session, m, team="desarrollo")

    assert AutoAssignService.try_auto_assign(db_session, asignado) is None
    assert AutoAssignService.try_auto_assign(db_session, a_equipo) is None
    db_session.refresh(asignado)
    db_session.refresh(a_equipo)
    assert asignado.assigned_to_user_id == m["B"].id
    assert a_equipo.status == "PENDING" and a_equipo.assigned_to_user_id is None


def test_asignacion_manual_colada_no_se_pisa(db_session, mundo):
    """El objeto en memoria dice PENDING, pero en la base ya lo asignaron a mano
    (entre el broadcast de ticket_created y el motor): el motor relee y no toca."""
    from sqlalchemy import text
    m = mundo
    _rule(db_session, m, ["A"], cat="sii")
    t = _ticket(db_session, m)
    db_session.execute(
        text("UPDATE helpdesk_ticket SET status='ASSIGNED', assigned_to_user_id=:u WHERE id=:i"),
        {"u": m["B"].id, "i": t.id},
    )
    db_session.commit()
    assert t.status == "PENDING"  # foto vieja en el identity map

    assert AutoAssignService.try_auto_assign(db_session, t) is None
    db_session.refresh(t)
    assert t.assigned_to_user_id == m["B"].id
    assert db_session.query(Assignment).filter_by(ticket_id=t.id).count() == 0


def test_fallo_en_assign_no_lanza(db_session, mundo):
    m = mundo
    regla = _rule(db_session, m, ["A"], cat="sii")
    t = _ticket(db_session, m)

    with patch("itcj2.apps.helpdesk.services.assignment_service.assign_ticket",
               side_effect=RuntimeError("boom")):
        assert AutoAssignService.try_auto_assign(db_session, t) is None

    db_session.refresh(t)
    db_session.refresh(regla)
    assert t.status == "PENDING" and t.assigned_to_user_id is None
    assert regla.last_assigned_user_id is None  # el puntero no quedó a medias


# ==================== PRESUPUESTO ====================
def test_presupuesto_de_consultas_constante(db_session, mundo):
    m = mundo
    regla = _rule(db_session, m, ["A", "B"], cat="sii", strategy="least_loaded")
    pocas, res = _medir(db_session, _ticket(db_session, m))
    assert res is not None

    # 8 reglas (la ganadora sigue siendo la de categoría), 6 técnicos, 10 activos.
    for cat, prio, area, techs in (("sii", "ALTA", "DESARROLLO", ["A"]),
                                   ("sii", "BAJA", "DESARROLLO", ["B"]),
                                   (None, None, "DESARROLLO", ["C"]),
                                   (None, "MEDIA", "DESARROLLO", ["A"]),
                                   ("correo", None, "DESARROLLO", ["B"]),
                                   ("correo", "MEDIA", "DESARROLLO", ["C"]),
                                   (None, None, "SOPORTE", ["sinrol"])):
        _rule(db_session, m, techs, cat=cat, priority=prio, area=area)
    app = m["app"]
    dev = ensure_role(db_session, "tech_desarrollo")
    for k in ("D", "E", "F"):
        m[k] = _user(db_session, k)
        _grant(db_session, app, m[k], dev)
    regla.technician_ids = [m[k].id for k in ("A", "B", "C", "D", "E", "F")]
    db_session.commit()
    for i in range(10):
        tech = m["ABCDEF"[i % 6]]
        _ticket(db_session, m, status="ASSIGNED" if i % 2 else "IN_PROGRESS", assigned=tech.id)

    muchas, res = _medir(db_session, _ticket(db_session, m))
    assert res is not None

    assert len(muchas) == len(pocas), (
        f"crece: {len(pocas)} → {len(muchas)}\n" + "\n---\n".join(muchas))
    assert len(muchas) <= MAX_QUERIES, "\n---\n".join(muchas)
