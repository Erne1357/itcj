import logging

from fastapi import HTTPException
from sqlalchemy.orm import Session

from itcj2.apps.maint.models.category import MaintCategory
from itcj2.apps.maint.utils.timezone_utils import now_local

logger = logging.getLogger(__name__)


def list_categories(db: Session, only_active: bool = True) -> list[MaintCategory]:
    query = db.query(MaintCategory)
    if only_active:
        query = query.filter(MaintCategory.is_active == True)
    return query.order_by(MaintCategory.display_order.asc(), MaintCategory.name.asc()).all()


def get_category_by_id(db: Session, category_id: int) -> MaintCategory:
    category = db.get(MaintCategory, category_id)
    if not category:
        raise HTTPException(status_code=404, detail='Categoría no encontrada')
    return category


def create_category(
    db: Session,
    code: str,
    name: str,
    description: str = None,
    icon: str = 'bi-tools',
    field_template: list = None,
    display_order: int = 0,
) -> MaintCategory:
    existing = db.query(MaintCategory).filter_by(code=code.upper()).first()
    if existing:
        raise HTTPException(status_code=400, detail=f'Ya existe una categoría con el código {code}')

    category = MaintCategory(
        code=code.upper().strip(),
        name=name.strip(),
        description=description.strip() if description else None,
        icon=icon or 'bi-tools',
        field_template=field_template,
        display_order=display_order or 0,
    )
    db.add(category)

    try:
        db.commit()
        logger.info(f"Categoría maint {category.code} creada")
        return category
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail='Error al crear categoría')


def update_category(
    db: Session,
    category_id: int,
    name: str = None,
    description: str = None,
    icon: str = None,
    display_order: int = None,
) -> MaintCategory:
    category = db.get(MaintCategory, category_id)
    if not category:
        raise HTTPException(status_code=404, detail='Categoría no encontrada')

    if name is not None:
        category.name = name.strip()
    if description is not None:
        category.description = description.strip() if description.strip() else None
    if icon is not None:
        category.icon = icon.strip()
    if display_order is not None:
        category.display_order = display_order

    category.updated_at = now_local()

    try:
        db.commit()
        return category
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail='Error al actualizar categoría')


def toggle_category(db: Session, category_id: int, is_active: bool) -> MaintCategory:
    category = db.get(MaintCategory, category_id)
    if not category:
        raise HTTPException(status_code=404, detail='Categoría no encontrada')

    category.is_active = is_active
    category.updated_at = now_local()

    try:
        db.commit()
        logger.info(f"Categoría {category.code} {'activada' if is_active else 'desactivada'}")
        return category
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail='Error al actualizar categoría')


def update_field_template(
    db: Session,
    category_id: int,
    fields: list[dict],
) -> MaintCategory:
    """
    Reemplaza el field_template de la categoría.
    fields=[] elimina el template (sin campos dinámicos).
    """
    category = db.get(MaintCategory, category_id)
    if not category:
        raise HTTPException(status_code=404, detail='Categoría no encontrada')

    category.field_template = fields if fields else None
    category.updated_at = now_local()

    try:
        db.commit()
        logger.info(f"field_template de {category.code} actualizado ({len(fields)} campos)")
        return category
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail='Error al actualizar field_template')
