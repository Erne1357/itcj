"""`list_tickets` no hace consultas por ticket (rendimiento 2026-10-07).

`Ticket.to_dict(include_relations=True)` lee relaciones de uno (solicitante,
asignado, creó/actualizó/resolvió, categoría, departamento, `split_from`) y dos
relaciones `lazy='dynamic'` (colaboradores y equipos) que no admiten
`selectinload`. Antes eran ~5 consultas por ticket más una por equipo: el
dashboard del técnico hacía 375 consultas y tardaba ~370 ms en prod. Ahora
`list_tickets` las carga en lote (`_LIST_LOAD_OPTIONS` + `prefetch_for_dict`).

Se fija:
1. el número de consultas NO crece con el número de tickets;
2. la salida es la MISMA que la de `to_dict` sin precarga (mismo orden de
   colaboradores y equipos);
3. la foto de la precarga no se queda en los tickets al terminar.
"""
from datetime import date

import pytest
from sqlalchemy import event

import itcj2.models  # noqa: F401
from itcj2.apps.helpdesk.models.category import Category
from itcj2.apps.helpdesk.models.collaborator import TicketCollaborator
from itcj2.apps.helpdesk.models.inventory_category import InventoryCategory
from itcj2.apps.helpdesk.models.inventory_group import InventoryGroup
from itcj2.apps.helpdesk.models.inventory_item import InventoryItem
from itcj2.apps.helpdesk.models.ticket import Ticket
from itcj2.apps.helpdesk.models.ticket_inventory_item import TicketInventoryItem
from itcj2.apps.helpdesk.services.ticket_service import list_tickets
from itcj2.core.models.department import Department
from itcj2.core.models.user import User

# Holgura sobre lo medido (~13 con todo presente): lo que importa es la prueba
# de crecimiento; el tope solo atrapa un N+1 que se cuele en un caso pequeño.
MAX_QUERIES = 20


def _commit(db, obj):
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@pytest.fixture()
def mundo(db_session):
    """Departamento, categorías, grupo y cuatro usuarios para armar tickets."""
    db = db_session
    dept = _commit(db, Department(code="tlqc_dept", name="tlqc", is_active=True))
    users = [_commit(db, User(first_name="Q", last_name=f"C{i}", is_active=True))
             for i in range(4)]
    cat = db.query(Category).filter_by(code="tlqc_cat").first() or _commit(
        db, Category(area="SOPORTE", code="tlqc_cat", name="tlqc", is_active=True))
    inv_cat = _commit(db, InventoryCategory(code="tlqc_inv", name="Equipo",
                                            inventory_prefix="TQ", is_active=True,
                                            requires_specs=False))
    group = _commit(db, InventoryGroup(name="Aula Q", code="tlqc_grp", department_id=dept.id,
                                       is_active=True, created_by_id=users[0].id))
    return {"dept": dept, "users": users, "cat": cat, "inv_cat": inv_cat, "group": group,
            "seq": [0]}


def _ticket(db, m, *, split_from=None):
    """Ticket con DOS colaboradores y DOS equipos (uno asignado y en grupo),
    resuelto por otro usuario, y opcionalmente partido de `split_from`."""
    u = m["users"]
    m["seq"][0] += 1
    n = m["seq"][0]
    t = _commit(db, Ticket(
        ticket_number=f"TLQC-{n:04d}", requester_id=u[0].id,
        requester_department_id=m["dept"].id, area="SOPORTE", category_id=m["cat"].id,
        priority="MEDIA", title=f"t{n}", description="x", status="RESOLVED_SUCCESS",
        assigned_to_user_id=u[1].id, resolved_by_id=u[2].id,
        created_by_id=u[0].id, updated_by_id=u[3].id,
        split_from_ticket_id=split_from.id if split_from else None,
    ))
    for who, role in ((u[2], "LEAD"), (u[3], "COLLABORATOR")):
        db.add(TicketCollaborator(ticket_id=t.id, user_id=who.id, collaboration_role=role,
                                  added_by_id=u[1].id))
    for k in range(2):
        item = _commit(db, InventoryItem(
            inventory_number=f"TLQC-{n:04d}-{k}", category_id=m["inv_cat"].id,
            department_id=m["dept"].id, brand="Marca", model=f"M{k}",
            registered_by_id=u[0].id,
            assigned_to_user_id=u[3].id if k == 0 else None,
            group_id=m["group"].id if k == 1 else None,
        ))
        db.add(TicketInventoryItem(ticket_id=t.id, inventory_item_id=item.id))
    db.commit()
    return t


def _consultas(db, fn):
    """Cuántas sentencias SQL corre `fn()` sobre la conexión de la sesión."""
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


def _listar(db, m):
    # Mapa de identidad vacío: sin esto las relaciones de uno salen de memoria
    # y la prueba no vería un N+1 en ellas.
    db.expunge_all()
    return _consultas(db, lambda: list_tickets(
        db, user_id=m["users"][0].id, user_roles={"admin"},
        department_ids={m["dept"].id}, per_page=100))


def test_las_consultas_no_crecen_con_los_tickets(db_session, mundo):
    padre = _ticket(db_session, mundo)
    for _ in range(2):
        _ticket(db_session, mundo, split_from=padre)
    pocas, res3 = _listar(db_session, mundo)
    assert len(res3["tickets"]) == 3

    for _ in range(9):
        _ticket(db_session, mundo, split_from=padre)
    muchas, res12 = _listar(db_session, mundo)
    assert len(res12["tickets"]) == 12

    assert muchas == pocas, f"N+1: {pocas} consultas con 3 tickets, {muchas} con 12"
    assert muchas <= MAX_QUERIES


def test_la_salida_es_la_misma_que_sin_precarga(db_session, mundo):
    padre = _ticket(db_session, mundo)
    _ticket(db_session, mundo, split_from=padre)
    _, res = _listar(db_session, mundo)

    db_session.expunge_all()
    for d in res["tickets"]:
        t = db_session.get(Ticket, d["id"])
        assert d == t.to_dict(include_relations=True), d["ticket_number"]
    hijo = next(d for d in res["tickets"] if d["split_from"])
    assert hijo["collaborators_count"] == 2 and hijo["inventory_items_count"] == 2
    assert [c["collaboration_role"] for c in hijo["collaborators"]] == ["LEAD", "COLLABORATOR"]
    assert [i["model"] for i in hijo["inventory_items"]] == ["M0", "M1"]
    assert hijo["inventory_items"][0]["assigned_to_user"] is not None
    assert hijo["inventory_items"][1]["group"]["code"] == "tlqc_grp"
    assert hijo["resolved_by"]["id"] == mundo["users"][2].id


def test_la_precarga_no_se_queda_en_los_tickets(db_session, mundo):
    t = _ticket(db_session, mundo)
    _listar(db_session, mundo)

    vivo = db_session.get(Ticket, t.id)
    assert "_hd_prefetch" not in vivo.__dict__

    # Un colaborador nuevo después de listar se ve en el siguiente `to_dict`.
    db_session.add(TicketCollaborator(ticket_id=t.id, user_id=mundo["users"][0].id,
                                      collaboration_role="TRAINEE"))
    db_session.commit()
    assert vivo.to_dict(include_relations=True)["collaborators_count"] == 3
