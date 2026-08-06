"""Helpers get-or-create para catálogos de helpdesk que la BD de test (CI, vacía
por `create_all`) no trae precargados — `database/DML/` es gitignored a
propósito (trae PII real) y nunca llega al checkout de CI.

Cada helper opera DENTRO de la sesión/transacción del test (`db_session`, que
hace rollback al terminar) — nunca hace un commit fuera de esa transacción. Si
la fila ya existe (como en la BD de dev, cargada por `database/DML/`), la
reutiliza en vez de duplicarla.
"""
from itcj2.apps.helpdesk.models.category import Category
from itcj2.apps.helpdesk.models.inventory_category import InventoryCategory
from itcj2.apps.helpdesk.models.priority import Priority
from itcj2.core.models.department import Department
from itcj2.core.models.role import Role


def ensure_helpdesk_category(db, code="test_default_cat", area="DESARROLLO"):
    """Categoría activa de `helpdesk_category`.

    `create_ticket` exige una categoría real: valida `category.area == area`
    y lee `category.field_template`. `Area` (DESARROLLO/SOPORTE) no necesita
    su propio helper — `catalog_cache.get_area_codes` ya degrada a ese mismo
    par de codes cuando `helpdesk_area` está vacía (fallback defensivo
    existente), así que basta con usar uno de esos dos codes aquí.
    """
    cat = db.query(Category).filter_by(code=code).first()
    if cat:
        return cat
    cat = Category(area=area, code=code, name=code, is_active=True)
    db.add(cat)
    db.commit()
    db.refresh(cat)
    return cat


def ensure_helpdesk_priority(db, code="MEDIA"):
    """Prioridad activa de `helpdesk_priority` + invalida el cache in-process
    de `catalog_cache`.

    A diferencia de `get_area_codes`, `catalog_cache.get_priority_codes` de
    helpdesk NO tiene fallback defensivo: si el cache ya se pobló vacío en
    este proceso de pytest (porque algún test anterior corrió contra una BD
    sin prioridades), se queda pegado en `set()` para el resto de la sesión.
    Invalidar aquí fuerza una relectura con el `db` de ESTE test — que sí ve
    la fila recién insertada, porque `_ensure_loaded` usa el `db` que se le
    pasa (a diferencia del cache de maint, que abre su propia sesión).
    """
    pr = db.query(Priority).filter_by(code=code).first()
    if not pr:
        pr = Priority(code=code, label=code.capitalize(), sla_hours=72, is_active=True)
        db.add(pr)
        db.commit()
        db.refresh(pr)
    from itcj2.apps.helpdesk.utils.catalog_cache import invalidate_priorities
    invalidate_priorities()
    return pr


def ensure_inventory_category(db, code="test_default_inv_cat"):
    """Categoría activa de `helpdesk_inventory_categories`. Sin cache propio
    (se lee siempre directo de BD), así que no requiere invalidación."""
    cat = db.query(InventoryCategory).filter_by(code=code).first()
    if cat:
        return cat
    cat = InventoryCategory(code=code, name=code, inventory_prefix="TST", is_active=True)
    db.add(cat)
    db.commit()
    db.refresh(cat)
    return cat


def ensure_comp_center(db):
    """Departamento del Centro de Cómputo.

    El "limbo" de inventario no es `department_id = NULL` (columna NOT NULL):
    es `status='PENDING_ASSIGNMENT'` en este departamento. `bulk_send_to_limbo`
    e `InventoryPendingService.get_pending_items` lo asumen existente por code
    y truenan (o devuelven vacío) sin él.
    """
    dept = db.query(Department).filter_by(code="comp_center").first()
    if dept:
        return dept
    dept = Department(code="comp_center", name="Centro de Cómputo", is_active=True)
    db.add(dept)
    db.commit()
    db.refresh(dept)
    return dept


def ensure_role(db, name):
    """Rol de `core_roles` (p. ej. `department_head`, `tech_desarrollo`).

    En dev ya existe (cargado por `database/DML/`); en una BD vacía (CI) no.
    Es fila de referencia pura — sin PII, sin datos de negocio inventados,
    mismo tipo de fila que `student` en `_seed_minimal_reference_data` — así
    que el get-or-create es seguro incluso cuando la sesión del test es la
    misma que usa el endpoint bajo prueba (vía `app.dependency_overrides`).
    """
    role = db.query(Role).filter_by(name=name).first()
    if role:
        return role
    role = Role(name=name)
    db.add(role)
    db.commit()
    db.refresh(role)
    return role
