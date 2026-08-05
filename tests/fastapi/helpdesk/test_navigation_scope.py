"""La navegación tiene que ofrecer lo que el usuario realmente alcanza.

Dos incoherencias: el grupo "Inventario" se gateaba con `helpdesk.inventory.page.list`,
que el rol `department_head` NO tiene (tiene `.page.list.own_dept`), así que el
dropdown entero desaparecía —incluidos sub-items cuyos permisos sí posee— pese a
que `/help-desk/inventory/items` solo exige acceso al app y ya está acotada al
subárbol. Y "Ver Inventario" exigía `helpdesk.inventory.api.read`, un código que no
existe en el catálogo de permisos: el item no se le mostraba a nadie.
"""
import itcj2.models  # noqa: F401
from itcj2.apps.helpdesk.utils.navigation import get_helpdesk_navigation

DEPT_HEAD_PERMS = {
    "helpdesk.tickets.page.my_tickets",
    "helpdesk.inventory.page.list.own_dept",
    "helpdesk.inventory.page.my_equipment",
    "helpdesk.inventory.api.read.own_dept",
    "helpdesk.inventory_groups.page.list",
    "helpdesk.dashboard.department",
}

ADMIN_PERMS = DEPT_HEAD_PERMS | {
    "helpdesk.inventory.page.list",
    "helpdesk.inventory.page.create",
}


def _group(nav, label):
    return next((i for i in nav if i["label"] == label), None)


def _sub_labels(group):
    return {s["label"] for s in group.get("dropdown", [])}


def test_department_head_reaches_inventory_menu():
    nav = get_helpdesk_navigation(DEPT_HEAD_PERMS, {"department_head"})
    inventory = _group(nav, "Inventario")

    assert inventory is not None, "el jefe de departamento se queda sin menú de inventario"
    assert "Ver Inventario" in _sub_labels(inventory)


def test_admin_still_reaches_inventory_menu():
    nav = get_helpdesk_navigation(ADMIN_PERMS, {"admin"})
    inventory = _group(nav, "Inventario")

    assert inventory is not None
    assert "Ver Inventario" in _sub_labels(inventory)


def test_user_without_inventory_permissions_gets_no_menu():
    nav = get_helpdesk_navigation({"helpdesk.tickets.page.my_tickets"}, {"staff"})

    assert _group(nav, "Inventario") is None


def test_any_of_permission_lists_are_honored():
    """Un item puede declarar varios permisos: basta con tener uno.

    Es lo que permite gatear el grupo "Inventario" con
    `{page.list, page.list.own_dept}` sin duplicar la entrada por rol.
    """
    solo_own_dept = {"helpdesk.inventory.page.list.own_dept"}
    solo_full = {"helpdesk.inventory.page.list"}

    assert _group(get_helpdesk_navigation(solo_own_dept, set()), "Inventario") is not None
    assert _group(get_helpdesk_navigation(solo_full, set()), "Inventario") is not None
