"""Las solicitudes de baja del subárbol le tocan al jefe.

El listado solo distinguía "admin ve todas / el resto ve las suyas", así que un
jefe no veía las bajas que otra persona levantó con equipos de SU departamento,
que son justamente las que tiene que vigilar. La solicitud no tiene departamento
propio: el suyo se deriva de los equipos que contiene.
"""
from datetime import date, timedelta

import itcj2.models  # noqa: F401
from itcj2.apps.helpdesk.services.inventory_retirement_service import InventoryRetirementService
from itcj2.apps.helpdesk.models.inventory_category import InventoryCategory
from itcj2.apps.helpdesk.models.inventory_item import InventoryItem
from itcj2.apps.helpdesk.models.inventory_retirement_request import (
    InventoryRetirementRequest, InventoryRetirementRequestItem,
)
from itcj2.core.models.app import App
from itcj2.core.models.department import Department
from itcj2.core.models.permission import Permission
from itcj2.core.models.user import User
from itcj2.core.models.position import Position, UserPosition, PositionAppPerm

RETIREMENT_SUBTREE = "helpdesk.inventory.retirement.api.read.subtree"


def _dept(db, code, parent_id=None):
    d = Department(code=code, name=code, parent_id=parent_id, is_active=True)
    db.add(d); db.commit(); db.refresh(d)
    return d


def _user(db, last):
    u = User(first_name="R", last_name=last, is_active=True)
    db.add(u); db.commit(); db.refresh(u)
    return u


def _category(db):
    c = db.query(InventoryCategory).filter_by(is_active=True).first()
    assert c is not None
    return c


def _request_with_item(db, folio, requester, department, number):
    item = InventoryItem(
        inventory_number=number, category_id=_category(db).id,
        department_id=department.id, status="ACTIVE",
        registered_by_id=requester.id, is_active=True,
    )
    db.add(item); db.commit(); db.refresh(item)
    req = InventoryRetirementRequest(
        folio=folio, status="DRAFT", reason="obsoleto", requested_by_id=requester.id,
    )
    db.add(req); db.commit(); db.refresh(req)
    db.add(InventoryRetirementRequestItem(request_id=req.id, item_id=item.id))
    db.commit()
    return req


def _grant_retirement_subtree(db, user, department):
    app = db.query(App).filter_by(key="helpdesk").first()
    perm = db.query(Permission).filter_by(app_id=app.id, code=RETIREMENT_SUBTREE).first()
    if not perm:
        perm = Permission(app_id=app.id, code=RETIREMENT_SUBTREE, name=RETIREMENT_SUBTREE)
        db.add(perm); db.commit(); db.refresh(perm)
    pos = Position(code=f"ret_pos_{user.id}", title="Jefe", department_id=department.id,
                   is_active=True, allows_multiple=True)
    db.add(pos); db.commit(); db.refresh(pos)
    db.add(UserPosition(user_id=user.id, position_id=pos.id,
                        start_date=date.today() - timedelta(days=1), is_active=True))
    db.add(PositionAppPerm(position_id=pos.id, app_id=app.id, perm_id=perm.id, allow=True))
    db.commit()


def _folios(result):
    return {r["folio"] for r in result["requests"]}


def test_head_sees_subtree_requests_not_other_branch(db_session):
    root = _dept(db_session, "ret_root")
    mine = _dept(db_session, "ret_sub", root.id)
    leaf = _dept(db_session, "ret_leaf", mine.id)
    sibling = _dept(db_session, "ret_sibling", root.id)
    boss = _user(db_session, "Head")
    stranger = _user(db_session, "Ajeno")
    _grant_retirement_subtree(db_session, boss, mine)

    _request_with_item(db_session, "RET-MINE", stranger, mine, "RET-I-1")
    _request_with_item(db_session, "RET-LEAF", stranger, leaf, "RET-I-2")
    _request_with_item(db_session, "RET-SIB", stranger, sibling, "RET-I-3")

    visible = {mine.id, leaf.id}
    result = InventoryRetirementService.get_requests(
        db_session, boss.id, False, {}, visible_department_ids=visible
    )

    assert {"RET-MINE", "RET-LEAF"} <= _folios(result)
    assert "RET-SIB" not in _folios(result)


def test_own_requests_are_always_listed(db_session):
    """La propiedad suma: la solicitud propia sale aunque sus equipos
    ya no estén en el subárbol del solicitante."""
    mine = _dept(db_session, "ret_own_mine")
    elsewhere = _dept(db_session, "ret_own_other")
    boss = _user(db_session, "Owner")
    _grant_retirement_subtree(db_session, boss, mine)

    _request_with_item(db_session, "RET-OWN", boss, elsewhere, "RET-I-4")

    result = InventoryRetirementService.get_requests(
        db_session, boss.id, False, {}, visible_department_ids={mine.id}
    )

    assert "RET-OWN" in _folios(result)


def test_without_scope_only_own_requests(db_session):
    """Sin departamentos visibles, el comportamiento es el de siempre."""
    dept = _dept(db_session, "ret_none")
    boss = _user(db_session, "NoScope")
    stranger = _user(db_session, "Ajeno2")

    _request_with_item(db_session, "RET-FOREIGN", stranger, dept, "RET-I-5")

    result = InventoryRetirementService.get_requests(
        db_session, boss.id, False, {}, visible_department_ids=set()
    )

    assert _folios(result) == set()


def test_full_access_sees_everything(db_session):
    """`None` = ve todo (admin / centro de cómputo): sin filtro departamental."""
    dept = _dept(db_session, "ret_all")
    boss = _user(db_session, "Full")
    stranger = _user(db_session, "Ajeno3")

    _request_with_item(db_session, "RET-ANY", stranger, dept, "RET-I-6")

    result = InventoryRetirementService.get_requests(
        db_session, boss.id, False, {}, visible_department_ids=None
    )

    assert "RET-ANY" in _folios(result)


# ---------------------------------------------------------------------------
# Detalle: lo que el listado muestra, se abre
# ---------------------------------------------------------------------------

def test_detail_opens_for_a_subtree_request(db_session):
    import pytest
    from fastapi import HTTPException
    from itcj2.apps.helpdesk.api.inventory.retirement_requests import get_request

    root = _dept(db_session, "retd_root")
    mine = _dept(db_session, "retd_sub", root.id)
    leaf = _dept(db_session, "retd_leaf", mine.id)
    sibling = _dept(db_session, "retd_sibling", root.id)
    boss = _user(db_session, "DetailHead")
    stranger = _user(db_session, "DetailAjeno")
    _grant_retirement_subtree(db_session, boss, mine)

    ours = _request_with_item(db_session, "RETD-LEAF", stranger, leaf, "RETD-I-1")
    theirs = _request_with_item(db_session, "RETD-SIB", stranger, sibling, "RETD-I-2")

    user = {"sub": str(boss.id), "role": "x"}

    # La del subárbol abre.
    assert get_request(request_id=ours.id, user=user, db=db_session)["data"]["folio"] == "RETD-LEAF"

    # La de la rama hermana no.
    with pytest.raises(HTTPException) as exc:
        get_request(request_id=theirs.id, user=user, db=db_session)
    assert exc.value.status_code == 403
