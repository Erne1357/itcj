"""Scope por subárbol aplicado a las ESCRITURAS de inventario.

Antes de este fix, los endpoints de escritura (transferencias, asignación,
ubicación, equipos pendientes, altas a solicitudes de baja, validación de
campañas) solo comprobaban el permiso plano — nunca que el equipo/departamento
tocado estuviera dentro del subárbol visible del usuario
(`visible_department_ids`). Un jefe con el permiso podía operar sobre
inventario de una rama hermana.

Cubre como mínimo:
  (a) transferir un equipo de la rama hermana falla / entra en errors
  (b) transferir HACIA un departamento fuera del subárbol falla
  (c) add_items (solicitud de baja) rechaza un equipo ajeno
  (d) validate_campaign rechaza una campaña de otro departamento
  (e) control positivo: dentro del subárbol SÍ funciona

Además cubre puntualmente bulk-send-to-limbo, /transfer individual,
assign/unassign/update-location y assign-to-department (limbo), que reciben
el mismo tipo de fix.
"""
from datetime import date, timedelta
from unittest.mock import patch

import pytest
from fastapi import HTTPException

import itcj2.models  # noqa: F401  (mappers)
from itcj2.core.models.app import App
from itcj2.core.models.department import Department
from itcj2.core.models.permission import Permission
from itcj2.core.models.position import Position, UserPosition, PositionAppPerm
from itcj2.core.models.user import User

from itcj2.apps.helpdesk.models.inventory_category import InventoryCategory
from itcj2.apps.helpdesk.models.inventory_item import InventoryItem

from ._catalog import ensure_comp_center

SUBTREE = "helpdesk.inventory.api.read.subtree"


# ---------------------------------------------------------------------------
# Helpers de factory (mismo estilo que test_inventory_scope.py / test_ticket_list_scope.py)
# ---------------------------------------------------------------------------

def _dept(db, code, parent_id=None):
    d = Department(code=code, name=code, parent_id=parent_id, is_active=True)
    db.add(d)
    db.commit()
    db.refresh(d)
    return d


def _user(db, last):
    u = User(first_name="T", last_name=last, is_active=True)
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _category(db):
    c = db.query(InventoryCategory).filter_by(code="iws_cat").first()
    if not c:
        c = InventoryCategory(code="iws_cat", name="iws", inventory_prefix="IWS")
        db.add(c)
        db.commit()
        db.refresh(c)
    return c


_seq = [0]


def _item(db, department, registered_by, status="ACTIVE", assigned_to_user_id=None):
    _seq[0] += 1
    item = InventoryItem(
        inventory_number=f"IWS-{_seq[0]:06d}",
        category_id=_category(db).id,
        department_id=department.id,
        registered_by_id=registered_by.id,
        status=status,
        is_active=True,
        assigned_to_user_id=assigned_to_user_id,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def _grant_subtree(db, user, department, perm_code=SUBTREE):
    """Ancla al usuario en `department` con un puesto que otorga `perm_code`."""
    app = db.query(App).filter_by(key="helpdesk").first()
    perm = db.query(Permission).filter_by(app_id=app.id, code=perm_code).first()
    if not perm:
        perm = Permission(app_id=app.id, code=perm_code, name=perm_code)
        db.add(perm)
        db.commit()
        db.refresh(perm)
    pos = Position(code=f"iws_pos_{user.id}", title="Jefe", department_id=department.id,
                   is_active=True, allows_multiple=True)
    db.add(pos)
    db.commit()
    db.refresh(pos)
    db.add(UserPosition(user_id=user.id, position_id=pos.id,
                        start_date=date.today() - timedelta(days=1), is_active=True))
    db.add(PositionAppPerm(position_id=pos.id, app_id=app.id, perm_id=perm.id, allow=True))
    db.commit()


class _FakeRequest:
    """Sustituye a `Request`: los endpoints solo leen `.client` para el IP de auditoría."""
    client = None


def _boss_dict(boss):
    return {"sub": str(boss.id), "role": "department_head"}


def _tree(db):
    """root → mine → leaf ; root → sibling. El jefe se ancla en `mine`."""
    root = _dept(db, "iws_root")
    mine = _dept(db, "iws_mine", root.id)
    leaf = _dept(db, "iws_leaf", mine.id)
    sibling = _dept(db, "iws_sibling", root.id)
    return root, mine, leaf, sibling


# ---------------------------------------------------------------------------
# (a)/(b)/(e) bulk-transfer
# ---------------------------------------------------------------------------

def test_bulk_transfer_item_from_sibling_branch_goes_to_errors(db_session):
    from itcj2.apps.helpdesk.api.inventory.bulk_transfer import bulk_transfer_items

    root, mine, leaf, sibling = _tree(db_session)
    boss = _user(db_session, "Boss")
    _grant_subtree(db_session, boss, mine)

    item = _item(db_session, sibling, boss)

    result = bulk_transfer_items(
        request=_FakeRequest(),
        body={"item_ids": [item.id], "target_department_id": mine.id, "notes": "prueba"},
        user=_boss_dict(boss),
        db=db_session,
    )

    assert result["transferred_count"] == 0
    assert len(result["errors"]) == 1
    db_session.refresh(item)
    assert item.department_id == sibling.id  # no se movió


def test_bulk_transfer_target_outside_subtree_goes_to_errors(db_session):
    from itcj2.apps.helpdesk.api.inventory.bulk_transfer import bulk_transfer_items

    root, mine, leaf, sibling = _tree(db_session)
    boss = _user(db_session, "Boss2")
    _grant_subtree(db_session, boss, mine)

    item = _item(db_session, mine, boss)  # origen SÍ visible

    result = bulk_transfer_items(
        request=_FakeRequest(),
        body={"item_ids": [item.id], "target_department_id": sibling.id, "notes": "prueba"},
        user=_boss_dict(boss),
        db=db_session,
    )

    assert result["transferred_count"] == 0
    assert len(result["errors"]) == 1
    db_session.refresh(item)
    assert item.department_id == mine.id  # no se movió


def test_bulk_transfer_within_subtree_succeeds(db_session):
    from itcj2.apps.helpdesk.api.inventory.bulk_transfer import bulk_transfer_items

    root, mine, leaf, sibling = _tree(db_session)
    boss = _user(db_session, "Boss3")
    _grant_subtree(db_session, boss, mine)

    item = _item(db_session, leaf, boss)  # leaf está en el subárbol de mine

    result = bulk_transfer_items(
        request=_FakeRequest(),
        body={"item_ids": [item.id], "target_department_id": mine.id, "notes": "prueba"},
        user=_boss_dict(boss),
        db=db_session,
    )

    assert result["transferred_count"] == 1
    assert result["errors"] == []
    db_session.refresh(item)
    assert item.department_id == mine.id


# ---------------------------------------------------------------------------
# bulk-send-to-limbo (mismo endpoint, mismo bug: vaciaba cualquier depto)
# ---------------------------------------------------------------------------

def test_bulk_send_to_limbo_outside_subtree_goes_to_errors(db_session):
    from itcj2.apps.helpdesk.api.inventory.bulk_transfer import bulk_send_to_limbo

    # El endpoint exige que exista el departamento del Centro de Cómputo
    # (code `comp_center`, destino real del "limbo") antes de tocar el scope
    # que este test ejercita; en dev ya existe, en CI (BD vacía) se siembra.
    ensure_comp_center(db_session)

    root, mine, leaf, sibling = _tree(db_session)
    boss = _user(db_session, "Boss4")
    _grant_subtree(db_session, boss, mine)

    item = _item(db_session, sibling, boss)

    result = bulk_send_to_limbo(
        request=_FakeRequest(),
        body={"item_ids": [item.id]},
        user=_boss_dict(boss),
        db=db_session,
    )

    assert result["sent_count"] == 0
    assert len(result["errors"]) == 1
    db_session.refresh(item)
    assert item.department_id == sibling.id  # sigue perteneciendo a su depto


# NOTA: no hay caso positivo para bulk-send-to-limbo aquí. `helpdesk_inventory_items
# .department_id` es NOT NULL en la BD real (confirmado vía information_schema),
# pero el endpoint pone `item.department_id = None` a propósito para "vaciar" el
# equipo al limbo — un bug pre-existente, independiente de este fix de scope, que
# hace que la ruta exitosa de este endpoint truene con IntegrityError en cualquier
# escenario (no solo en tests). Ver reporte final: NO se corrige aquí (fuera de
# alcance del brief de scope-check; requeriría decidir la solución correcta —
# ¿migración a nullable=True, o una columna/estado de "limbo" separado?).
# El caso negativo de abajo SÍ es válido: un item bloqueado por scope nunca llega
# al `db.commit()`, así que no dispara el bug de columna NOT NULL.


# ---------------------------------------------------------------------------
# /transfer individual (assignments.py) — InventoryValidators.validate_department
# abre su PROPIA sesión (SessionLocal) cuando no se le pasa `db`, así que no ve
# los departamentos recién creados en la transacción de este test. Se parchea
# para devolver el objeto ya resuelto en la sesión del test (el propio fix de
# scope no depende de esa función).
# ---------------------------------------------------------------------------

def test_transfer_single_item_destination_outside_subtree_denied(db_session):
    from itcj2.apps.helpdesk.api.inventory import assignments as assignments_api

    root, mine, leaf, sibling = _tree(db_session)
    boss = _user(db_session, "Boss6")
    _grant_subtree(db_session, boss, mine)

    item = _item(db_session, mine, boss)  # origen visible

    with patch(
        "itcj2.apps.helpdesk.utils.inventory_validators.InventoryValidators.validate_department",
        return_value=(True, "OK", sibling),
    ):
        with pytest.raises(HTTPException) as exc:
            assignments_api.transfer_between_departments(
                body={
                    "item_id": item.id,
                    "new_department_id": sibling.id,
                    "notes": "Motivo con más de diez caracteres",
                },
                request=_FakeRequest(),
                user=_boss_dict(boss),
                db=db_session,
            )
    assert exc.value.status_code == 403
    db_session.refresh(item)
    assert item.department_id == mine.id


def test_transfer_single_item_origin_outside_subtree_denied(db_session):
    from itcj2.apps.helpdesk.api.inventory import assignments as assignments_api

    root, mine, leaf, sibling = _tree(db_session)
    boss = _user(db_session, "Boss7")
    _grant_subtree(db_session, boss, mine)

    item = _item(db_session, sibling, boss)  # origen FUERA del subárbol

    with patch(
        "itcj2.apps.helpdesk.utils.inventory_validators.InventoryValidators.validate_department",
        return_value=(True, "OK", mine),
    ):
        with pytest.raises(HTTPException) as exc:
            assignments_api.transfer_between_departments(
                body={
                    "item_id": item.id,
                    "new_department_id": mine.id,
                    "notes": "Motivo con más de diez caracteres",
                },
                request=_FakeRequest(),
                user=_boss_dict(boss),
                db=db_session,
            )
    assert exc.value.status_code == 403


def test_transfer_single_item_within_subtree_succeeds(db_session):
    from itcj2.apps.helpdesk.api.inventory import assignments as assignments_api

    root, mine, leaf, sibling = _tree(db_session)
    boss = _user(db_session, "Boss8")
    _grant_subtree(db_session, boss, mine)

    item = _item(db_session, leaf, boss)

    with patch(
        "itcj2.apps.helpdesk.utils.inventory_validators.InventoryValidators.validate_department",
        return_value=(True, "OK", mine),
    ):
        result = assignments_api.transfer_between_departments(
            body={
                "item_id": item.id,
                "new_department_id": mine.id,
                "notes": "Motivo con más de diez caracteres",
            },
            request=_FakeRequest(),
            user=_boss_dict(boss),
            db=db_session,
        )

    assert result["success"] is True
    db_session.refresh(item)
    assert item.department_id == mine.id


# ---------------------------------------------------------------------------
# assign / unassign / update-location (assignments.py) — antes `== user_dept.id`
# plano, ahora migrado a `visible_department_ids`.
# ---------------------------------------------------------------------------

def test_assign_to_user_outside_subtree_denied(db_session):
    from itcj2.apps.helpdesk.api.inventory import assignments as assignments_api

    root, mine, leaf, sibling = _tree(db_session)
    boss = _user(db_session, "Boss9")
    target = _user(db_session, "Target9")
    _grant_subtree(db_session, boss, mine)

    item = _item(db_session, sibling, boss, status="ACTIVE")

    with pytest.raises(HTTPException) as exc:
        assignments_api.assign_to_user(
            body={"item_id": item.id, "user_id": target.id},
            request=_FakeRequest(),
            user=_boss_dict(boss),
            db=db_session,
        )
    assert exc.value.status_code == 403
    db_session.refresh(item)
    assert item.assigned_to_user_id is None


def test_unassign_from_user_outside_subtree_denied(db_session):
    from itcj2.apps.helpdesk.api.inventory import assignments as assignments_api

    root, mine, leaf, sibling = _tree(db_session)
    boss = _user(db_session, "Boss10")
    target = _user(db_session, "Target10")
    _grant_subtree(db_session, boss, mine)

    item = _item(db_session, sibling, boss, status="ACTIVE", assigned_to_user_id=target.id)

    with pytest.raises(HTTPException) as exc:
        assignments_api.unassign_from_user(
            body={"item_id": item.id},
            request=_FakeRequest(),
            user=_boss_dict(boss),
            db=db_session,
        )
    assert exc.value.status_code == 403
    db_session.refresh(item)
    assert item.assigned_to_user_id == target.id  # no se liberó


def test_unassign_from_user_within_subtree_succeeds(db_session):
    from itcj2.apps.helpdesk.api.inventory import assignments as assignments_api

    root, mine, leaf, sibling = _tree(db_session)
    boss = _user(db_session, "Boss11")
    target = _user(db_session, "Target11")
    _grant_subtree(db_session, boss, mine)

    item = _item(db_session, leaf, boss, status="ACTIVE", assigned_to_user_id=target.id)

    result = assignments_api.unassign_from_user(
        body={"item_id": item.id},
        request=_FakeRequest(),
        user=_boss_dict(boss),
        db=db_session,
    )
    assert result["success"] is True
    db_session.refresh(item)
    assert item.assigned_to_user_id is None


def test_update_location_outside_subtree_denied(db_session):
    from itcj2.apps.helpdesk.api.inventory import assignments as assignments_api

    root, mine, leaf, sibling = _tree(db_session)
    boss = _user(db_session, "Boss12")
    _grant_subtree(db_session, boss, mine)

    item = _item(db_session, sibling, boss)

    with pytest.raises(HTTPException) as exc:
        assignments_api.update_location(
            body={"item_id": item.id, "location": "Nueva ubicación"},
            request=_FakeRequest(),
            user=_boss_dict(boss),
            db=db_session,
        )
    assert exc.value.status_code == 403


def test_update_location_within_subtree_succeeds(db_session):
    from itcj2.apps.helpdesk.api.inventory import assignments as assignments_api

    root, mine, leaf, sibling = _tree(db_session)
    boss = _user(db_session, "Boss13")
    _grant_subtree(db_session, boss, mine)

    item = _item(db_session, leaf, boss)

    result = assignments_api.update_location(
        body={"item_id": item.id, "location": "Nueva ubicación"},
        request=_FakeRequest(),
        user=_boss_dict(boss),
        db=db_session,
    )
    assert result["success"] is True
    db_session.refresh(item)
    assert item.location_detail == "Nueva ubicación"


# ---------------------------------------------------------------------------
# /me-scope — campo nuevo, no debe quitar `user_dept` existente
# ---------------------------------------------------------------------------

def test_me_scope_includes_visible_department_ids_without_removing_user_dept(db_session):
    from itcj2.apps.helpdesk.api.inventory import assignments as assignments_api

    root, mine, leaf, sibling = _tree(db_session)
    boss = _user(db_session, "Boss14")
    _grant_subtree(db_session, boss, mine)

    result = assignments_api.get_my_scope(user=_boss_dict(boss), db=db_session)

    assert result["success"] is True
    assert "user_dept" in result["data"]  # campo viejo, consumido por el frontend
    assert "visible_department_ids" in result["data"]  # campo nuevo
    visible_ids = set(result["data"]["visible_department_ids"])
    assert visible_ids == {mine.id, leaf.id}


# ---------------------------------------------------------------------------
# pending.py — assign-to-department (limbo → departamento)
# ---------------------------------------------------------------------------

def test_pending_assign_to_department_outside_subtree_denied(db_session):
    from itcj2.apps.helpdesk.api.inventory import pending as pending_api

    root, mine, leaf, sibling = _tree(db_session)
    boss = _user(db_session, "Boss15")
    _grant_subtree(db_session, boss, mine)

    with pytest.raises(HTTPException) as exc:
        pending_api.assign_to_department(
            body={"item_ids": [999999], "department_id": sibling.id},
            user=_boss_dict(boss),
            db=db_session,
        )
    assert exc.value.status_code == 403


def test_pending_assign_to_department_within_subtree_succeeds(db_session):
    from itcj2.apps.helpdesk.api.inventory import pending as pending_api

    root, mine, leaf, sibling = _tree(db_session)
    boss = _user(db_session, "Boss16")
    _grant_subtree(db_session, boss, mine)

    # El item pendiente vive temporalmente en `root` (cualquier depto, el
    # servicio no valida su origen; lo que importa es el destino).
    item = _item(db_session, root, boss, status="PENDING_ASSIGNMENT")

    result = pending_api.assign_to_department(
        body={"item_ids": [item.id], "department_id": mine.id},
        user=_boss_dict(boss),
        db=db_session,
    )
    assert result["success"] is True
    db_session.refresh(item)
    assert item.department_id == mine.id
    assert item.status == "ACTIVE"


# ---------------------------------------------------------------------------
# (c)/(e) inventory_retirement_service.add_items
# ---------------------------------------------------------------------------

def test_add_items_rejects_item_outside_requester_scope(db_session):
    from itcj2.apps.helpdesk.services.inventory_retirement_service import InventoryRetirementService

    root, mine, leaf, sibling = _tree(db_session)
    requester = _user(db_session, "Requester1")
    _grant_subtree(db_session, requester, mine)

    req = InventoryRetirementService.create_request(db_session, "Motivo de prueba largo", requester.id)
    foreign_item = _item(db_session, sibling, requester)

    with pytest.raises(ValueError):
        InventoryRetirementService.add_items(
            db_session, req.id, [foreign_item.id],
            user_id=requester.id,
            requester=_boss_dict(requester),
        )


def test_add_items_accepts_item_within_requester_scope(db_session):
    from itcj2.apps.helpdesk.services.inventory_retirement_service import InventoryRetirementService

    root, mine, leaf, sibling = _tree(db_session)
    requester = _user(db_session, "Requester2")
    _grant_subtree(db_session, requester, mine)

    req = InventoryRetirementService.create_request(db_session, "Motivo de prueba largo", requester.id)
    own_item = _item(db_session, leaf, requester)

    updated = InventoryRetirementService.add_items(
        db_session, req.id, [own_item.id],
        user_id=requester.id,
        requester=_boss_dict(requester),
    )
    assert {ri.item_id for ri in updated.items} == {own_item.id}


# ---------------------------------------------------------------------------
# (d)/(e) campaign_service.validate_campaign
# ---------------------------------------------------------------------------

def test_validate_campaign_rejects_foreign_department_validator(db_session):
    from itcj2.apps.helpdesk.services.campaign_service import CampaignService

    root, mine, leaf, sibling = _tree(db_session)
    cc_user = _user(db_session, "CC1")
    validator = _user(db_session, "Validator1")
    _grant_subtree(db_session, validator, mine)

    campaign = CampaignService.create_campaign(db_session, sibling.id, "Campaña de prueba", cc_user.id)
    item = _item(db_session, sibling, cc_user)
    item.campaign_id = campaign.id
    db_session.commit()

    CampaignService.close_campaign(db_session, campaign.id, cc_user.id)

    with pytest.raises(ValueError):
        CampaignService.validate_campaign(
            db_session, campaign.id, action="approve", performed_by_id=validator.id,
            validator=_boss_dict(validator),
        )


def test_validate_campaign_accepts_own_department_validator(db_session):
    from itcj2.apps.helpdesk.services.campaign_service import CampaignService

    root, mine, leaf, sibling = _tree(db_session)
    cc_user = _user(db_session, "CC2")
    validator = _user(db_session, "Validator2")
    _grant_subtree(db_session, validator, mine)

    campaign = CampaignService.create_campaign(db_session, leaf.id, "Campaña de prueba 2", cc_user.id)
    item = _item(db_session, leaf, cc_user)
    item.campaign_id = campaign.id
    db_session.commit()

    CampaignService.close_campaign(db_session, campaign.id, cc_user.id)

    result = CampaignService.validate_campaign(
        db_session, campaign.id, action="approve", performed_by_id=validator.id,
        validator=_boss_dict(validator),
    )
    assert result.status == "VALIDATED"
