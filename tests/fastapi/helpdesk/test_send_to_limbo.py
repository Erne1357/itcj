"""Enviar equipo al limbo tiene que dejarlo donde el limbo vive.

El "limbo" del sistema no es `department_id = NULL`: es
`status = 'PENDING_ASSIGNMENT'` en el departamento del Centro de Cómputo — así lo
consulta `InventoryPendingService.get_pending_items` y así lo devuelve
`assign_to_department`. `bulk-send-to-limbo` ponía el departamento en NULL y no
tocaba el estado, contra una columna `NOT NULL`: reventaba con IntegrityError y,
de no hacerlo, el equipo tampoco habría aparecido en Equipos Pendientes.
"""
from datetime import date, timedelta

import itcj2.models  # noqa: F401
from itcj2.apps.helpdesk.api.inventory.bulk_transfer import bulk_send_to_limbo
from itcj2.apps.helpdesk.models.inventory_item import InventoryItem
from itcj2.apps.helpdesk.services.inventory_pending_service import InventoryPendingService
from itcj2.core.models.department import Department
from itcj2.core.models.user import User

from ._catalog import ensure_comp_center, ensure_inventory_category


class _Req:
    client = None


def _category(db):
    """`database/DML/` (categorías reales de inventario) es gitignored y no
    llega al checkout de CI: se siembra get-or-create dentro de la
    transacción del test en vez de asumirla."""
    return ensure_inventory_category(db)


def _comp_center(db):
    """El limbo vive en el departamento del Centro de Cómputo (code
    `comp_center`); en dev ya existe (real, cargado por `database/DML/`), en
    CI (BD vacía) no — se siembra get-or-create."""
    return ensure_comp_center(db)


def _item(db, number, department, user):
    it = InventoryItem(
        inventory_number=number, category_id=_category(db).id,
        department_id=department.id, status="ACTIVE",
        registered_by_id=user.id, is_active=True,
    )
    db.add(it); db.commit(); db.refresh(it)
    return it


def test_send_to_limbo_lands_in_pending_assignment(db_session):
    _comp_center(db_session)  # el endpoint exige que exista antes de operar
    admin = User(first_name="L", last_name="Admin", is_active=True)
    db_session.add(admin); db_session.commit(); db_session.refresh(admin)
    dept = Department(code="lmb_dept", name="lmb", is_active=True)
    db_session.add(dept); db_session.commit(); db_session.refresh(dept)
    item = _item(db_session, "LMB-0001", dept, admin)

    result = bulk_send_to_limbo(
        request=_Req(),
        body={"item_ids": [item.id], "notes": "baja de resguardo"},
        user={"sub": str(admin.id), "role": "admin"},
        db=db_session,
    )

    assert result["errors"] == []
    assert result["sent_count"] == 1

    db_session.refresh(item)
    assert item.status == "PENDING_ASSIGNMENT"
    assert item.department_id == _comp_center(db_session).id
    assert item.assigned_to_user_id is None
    assert item.group_id is None

    pending = InventoryPendingService.get_pending_items(db_session)
    assert item.id in {p.id for p in pending}


def test_send_to_limbo_records_the_real_destination_in_history(db_session):
    """El historial debe reflejar a dónde fue, no un None que ya no ocurre."""
    from itcj2.apps.helpdesk.models.inventory_history import InventoryHistory

    _comp_center(db_session)  # el endpoint exige que exista antes de operar
    admin = User(first_name="L", last_name="Hist", is_active=True)
    db_session.add(admin); db_session.commit(); db_session.refresh(admin)
    dept = Department(code="lmb_hist", name="lmb_hist", is_active=True)
    db_session.add(dept); db_session.commit(); db_session.refresh(dept)
    item = _item(db_session, "LMB-0002", dept, admin)
    origin_id = dept.id

    bulk_send_to_limbo(
        request=_Req(),
        body={"item_ids": [item.id]},
        user={"sub": str(admin.id), "role": "admin"},
        db=db_session,
    )

    entry = (
        db_session.query(InventoryHistory)
        .filter_by(item_id=item.id, event_type="TRANSFERRED")
        .order_by(InventoryHistory.id.desc())
        .first()
    )
    assert entry is not None
    assert entry.old_value["department_id"] == origin_id
    assert entry.new_value["department_id"] == _comp_center(db_session).id
    assert entry.new_value["status"] == "PENDING_ASSIGNMENT"
