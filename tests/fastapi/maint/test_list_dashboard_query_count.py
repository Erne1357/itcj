"""Lista de tickets y dashboard de maint sin consultas por fila (perf 2026-10-07).

- `list_tickets` (lista y tablero): técnicos con su usuario, solicitante,
  categoría y coordinador se cargan con `selectinload` para toda la página;
  antes eran 1 consulta de técnicos por ticket + 1 por usuario/categoría
  distintos (38 consultas en una página de 20; 60 en el tablero).
- `get_dashboard`: la condición de visibilidad se arma UNA vez (antes una por
  KPI: 7 lecturas de las áreas del técnico) y la actividad reciente trae el
  ticket en el mismo join y los autores en una consulta.
Con BD real (`db_session`): el número de consultas no crece con las filas.
"""
from datetime import timedelta
from unittest.mock import patch

import pytest
from sqlalchemy import event

import itcj2.models  # noqa: F401
from itcj2.apps.maint.models import MaintTicketTechnician
from itcj2.apps.maint.models.action_log import MaintTicketActionLog
from itcj2.apps.maint.models.category import MaintCategory
from itcj2.apps.maint.models.ticket import MaintTicket
from itcj2.apps.maint.utils.timezone_utils import now_local
from itcj2.core.models.department import Department
from itcj2.core.models.user import User


def _commit(db, obj):
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@pytest.fixture()
def mundo(db_session):
    db = db_session
    dept = _commit(db, Department(code="mqc_dept", name="mqc", is_active=True))
    cat = _commit(db, MaintCategory(code="MQC_CAT", name="mqc"))
    users = [_commit(db, User(first_name="M", last_name=f"Q{i}", is_active=True))
             for i in range(6)]
    return {"dept": dept, "cat": cat, "users": users, "seq": [0]}


def _ticket(db, m):
    u = m["users"]
    m["seq"][0] += 1
    n = m["seq"][0]
    t = _commit(db, MaintTicket(
        ticket_number=f"MQC-{n:05d}", requester_id=u[n % 3].id,
        requester_department_id=m["dept"].id, category_id=m["cat"].id,
        title=f"t{n}", description="x", status="ASSIGNED",
        created_by_id=u[0].id, coordinator_id=u[5].id,
    ))
    for who in (u[3], u[4]):
        db.add(MaintTicketTechnician(ticket_id=t.id, user_id=who.id, assigned_by_id=u[5].id))
    db.add(MaintTicketActionLog(ticket_id=t.id, action="ASSIGNED",
                                performed_by_id=u[n % 6].id,
                                performed_at=now_local() + timedelta(minutes=n)))
    db.commit()
    return t


def _consultas(db, fn):
    cuenta = [0]

    def _contar(*_a, **_k):
        cuenta[0] += 1

    conn = db.connection()
    event.listen(conn, "before_cursor_execute", _contar)
    try:
        resultado = fn()
    finally:
        event.remove(conn, "before_cursor_execute", _contar)
    return cuenta[0], resultado


def _listar_y_serializar(db, m):
    from itcj2.apps.maint.services import ticket_service

    db.expire_all()      # mapa de identidad vacío: nada sale de memoria
    res = ticket_service.list_tickets(db, user_id=m["users"][5].id, user_roles=["admin"],
                                      category_id=m["cat"].id, per_page=50)
    return [ticket_service.serialize_ticket_summary(t) for t in res["tickets"]]


def test_la_lista_no_hace_consultas_por_ticket(db_session, mundo):
    for _ in range(3):
        _ticket(db_session, mundo)
    _listar_y_serializar(db_session, mundo)    # calienta cachés de proceso
    pocas, filas3 = _consultas(db_session, lambda: _listar_y_serializar(db_session, mundo))
    for _ in range(9):
        _ticket(db_session, mundo)
    muchas, filas12 = _consultas(db_session, lambda: _listar_y_serializar(db_session, mundo))

    assert (len(filas3), len(filas12)) == (3, 12)
    assert pocas == muchas, f"crece con los tickets: {pocas} -> {muchas}"
    assert muchas <= 10
    fila = filas12[0]
    assert len(fila["active_technicians"]) == 2 and fila["coordinator"]["name"]
    assert fila["category"]["code"] == "MQC_CAT" and fila["requester"]["name"]


def test_el_dashboard_arma_la_visibilidad_una_vez(db_session, mundo):
    from itcj2.apps.maint.services import dashboard_service

    _ticket(db_session, mundo)
    with patch.object(dashboard_service, "_visibility_cond",
                      wraps=dashboard_service._visibility_cond) as espia:
        dashboard_service.get_dashboard(db_session, user_id=mundo["users"][3].id,
                                        user_roles=["tech_maint"])
    assert espia.call_count == 1


def test_la_actividad_reciente_no_crece_con_las_filas(db_session, mundo):
    from itcj2.apps.maint.services import dashboard_service

    def _dash():
        db_session.expire_all()
        return dashboard_service.get_dashboard(db_session, user_id=mundo["users"][3].id,
                                               user_roles=["tech_maint"])

    _ticket(db_session, mundo)                 # el técnico 3 ve sus asignados
    _dash()                                    # calienta cachés de proceso (catálogos, authz)
    pocas, d1 = _consultas(db_session, _dash)
    for _ in range(8):
        _ticket(db_session, mundo)
    muchas, d9 = _consultas(db_session, _dash)

    assert (len(d1["recent_activity"]), len(d9["recent_activity"])) == (1, 9)
    assert pocas == muchas, f"crece con la actividad: {pocas} -> {muchas}"
    assert all(a["performed_by"] and a["ticket_number"].startswith("MQC-")
               for a in d9["recent_activity"])
