"""CRUD de categorías y subcategorías del almacén global."""
import logging
from datetime import datetime
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from itcj2.apps.warehouse.models.category import WarehouseCategory
from itcj2.apps.warehouse.models.subcategory import WarehouseSubcategory

logger = logging.getLogger(__name__)


# ── Categorías ────────────────────────────────────────────────────────────────

def list_categories(
    db: Session,
    department_code: Optional[str],
    include_inactive: bool = False,
    with_subcategories: bool = False,
) -> list[WarehouseCategory]:
    """
    Lista categorías filtradas por departamento.
    Si department_code es None (superadmin), retorna todas.
    """
    query = db.query(WarehouseCategory)

    if department_code is not None:
        # Incluir categorías globales (dept NULL) + las del dept del usuario
        query = query.filter(
            (WarehouseCategory.department_code == department_code)
            | (WarehouseCategory.department_code == None)  # noqa: E711
        )

    if not include_inactive:
        query = query.filter(WarehouseCategory.is_active == True)

    return query.order_by(WarehouseCategory.display_order, WarehouseCategory.name).all()


def get_category(db: Session, category_id: int) -> WarehouseCategory:
    category = db.get(WarehouseCategory, category_id)
    if not category:
        raise HTTPException(404, detail={"error": "not_found", "message": "Categoría no encontrada"})
    return category


def create_category(db: Session, data, department_code: Optional[str]) -> WarehouseCategory:
    """
    Crea una nueva categoría.
    Si department_code es None (superadmin sin override), la categoría es global.
    """
    category = WarehouseCategory(
        name=data.name.strip(),
        description=data.description.strip() if data.description else None,
        icon=data.icon,
        department_code=data.department_code or department_code,
        is_active=True,
        display_order=data.display_order,
    )
    db.add(category)
    db.flush()
    logger.info("Categoría '%s' creada (dept=%s)", category.name, category.department_code)
    return category


def update_category(db: Session, category_id: int, data) -> WarehouseCategory:
    category = get_category(db, category_id)

    if data.name is not None:
        category.name = data.name.strip()
    if data.description is not None:
        category.description = data.description.strip() if data.description else None
    if data.icon is not None:
        category.icon = data.icon
    if data.display_order is not None:
        category.display_order = data.display_order

    category.updated_at = datetime.now()
    db.flush()
    return category


def deactivate_category(db: Session, category_id: int) -> WarehouseCategory:
    category = get_category(db, category_id)

    active_subs = (
        db.query(WarehouseSubcategory)
        .filter_by(category_id=category_id, is_active=True)
        .count()
    )
    if active_subs > 0:
        raise HTTPException(
            400,
            detail={
                "error": "has_active_subcategories",
                "message": f"No se puede desactivar. Tiene {active_subs} subcategoría(s) activa(s)",
            },
        )

    category.is_active = False
    category.updated_at = datetime.now()
    db.flush()
    return category


# ── Subcategorías ─────────────────────────────────────────────────────────────

def list_subcategories(
    db: Session, category_id: int, include_inactive: bool = False
) -> list[WarehouseSubcategory]:
    # Validar que la categoría existe
    get_category(db, category_id)

    query = db.query(WarehouseSubcategory).filter_by(category_id=category_id)
    if not include_inactive:
        query = query.filter_by(is_active=True)
    return query.order_by(WarehouseSubcategory.display_order, WarehouseSubcategory.name).all()


def get_subcategory(db: Session, subcategory_id: int) -> WarehouseSubcategory:
    sub = db.get(WarehouseSubcategory, subcategory_id)
    if not sub:
        raise HTTPException(404, detail={"error": "not_found", "message": "Subcategoría no encontrada"})
    return sub


def create_subcategory(db: Session, category_id: int, data) -> WarehouseSubcategory:
    get_category(db, category_id)  # validar que existe

    # Verificar nombre único dentro de la categoría
    existing = (
        db.query(WarehouseSubcategory)
        .filter_by(category_id=category_id, name=data.name.strip())
        .first()
    )
    if existing:
        raise HTTPException(
            409,
            detail={
                "error": "name_exists",
                "message": f"Ya existe una subcategoría con el nombre '{data.name}' en esta categoría",
            },
        )

    sub = WarehouseSubcategory(
        category_id=category_id,
        name=data.name.strip(),
        description=data.description.strip() if data.description else None,
        is_active=True,
        display_order=data.display_order,
    )
    db.add(sub)
    db.flush()
    return sub


def update_subcategory(db: Session, subcategory_id: int, data) -> WarehouseSubcategory:
    sub = get_subcategory(db, subcategory_id)

    if data.name is not None:
        # Verificar unicidad si el nombre cambia
        if data.name.strip() != sub.name:
            existing = (
                db.query(WarehouseSubcategory)
                .filter_by(category_id=sub.category_id, name=data.name.strip())
                .first()
            )
            if existing:
                raise HTTPException(
                    409,
                    detail={
                        "error": "name_exists",
                        "message": f"Ya existe una subcategoría con el nombre '{data.name}'",
                    },
                )
        sub.name = data.name.strip()

    if data.description is not None:
        sub.description = data.description.strip() if data.description else None
    if data.display_order is not None:
        sub.display_order = data.display_order

    db.flush()
    return sub


def deactivate_subcategory(db: Session, subcategory_id: int) -> WarehouseSubcategory:
    sub = get_subcategory(db, subcategory_id)

    from itcj2.apps.warehouse.models.product import WarehouseProduct

    active_products = (
        db.query(WarehouseProduct)
        .filter_by(subcategory_id=subcategory_id, is_active=True)
        .count()
    )
    if active_products > 0:
        raise HTTPException(
            400,
            detail={
                "error": "has_active_products",
                "message": f"No se puede desactivar. Tiene {active_products} producto(s) activo(s)",
            },
        )

    sub.is_active = False
    db.flush()
    return sub
