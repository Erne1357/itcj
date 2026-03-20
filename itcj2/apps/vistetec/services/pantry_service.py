"""Servicio para gestión de despensa y campañas."""
from datetime import date
from typing import Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from itcj2.apps.vistetec.models.pantry_campaign import PantryCampaign
from itcj2.apps.vistetec.models.pantry_item import PantryItem
from itcj2.models.base import paginate


# ==================== ITEMS ====================

def get_items(
    db: Session,
    category: Optional[str] = None,
    search: Optional[str] = None,
    is_active: Optional[bool] = None,
    page: int = 1,
    per_page: int = 20,
) -> dict:
    """Lista items de despensa con filtros y paginación."""
    query = db.query(PantryItem)

    if category:
        query = query.filter(PantryItem.category == category)
    if is_active is not None:
        query = query.filter(PantryItem.is_active == is_active)
    if search:
        query = query.filter(
            or_(
                PantryItem.name.ilike(f'%{search}%'),
                PantryItem.category.ilike(f'%{search}%'),
            )
        )

    query = query.order_by(PantryItem.name)
    pagination = paginate(query, page=page, per_page=per_page)

    return {
        'items': [i.to_dict() for i in pagination.items],
        'total': pagination.total,
        'pages': pagination.pages,
        'page': page,
        'has_next': pagination.has_next,
        'has_prev': pagination.has_prev,
    }


def get_item_by_id(db: Session, item_id: int) -> Optional[PantryItem]:
    """Obtiene un item por ID."""
    return db.get(PantryItem, item_id)


def create_item(db: Session, data: dict) -> PantryItem:
    """Crea un nuevo item de despensa."""
    name = (data.get('name') or '').strip()
    if not name:
        raise ValueError("El nombre es requerido")

    existing = db.query(PantryItem).filter(
        PantryItem.name.ilike(name),
        PantryItem.is_active == True,
    ).first()
    if existing:
        raise ValueError("Ya existe un artículo activo con ese nombre")

    item = PantryItem(
        name=name,
        category=data.get('category'),
        unit=data.get('unit'),
        current_stock=data.get('current_stock', 0),
    )

    db.add(item)
    db.commit()
    return item


def update_item(db: Session, item_id: int, data: dict) -> PantryItem:
    """Actualiza un item de despensa."""
    item = db.get(PantryItem, item_id)
    if not item:
        raise ValueError("Artículo no encontrado")

    if 'name' in data:
        name = (data['name'] or '').strip()
        if not name:
            raise ValueError("El nombre es requerido")
        item.name = name
    if 'category' in data:
        item.category = data['category']
    if 'unit' in data:
        item.unit = data['unit']

    db.commit()
    return item


def deactivate_item(db: Session, item_id: int) -> PantryItem:
    """Desactiva un item (soft delete)."""
    item = db.get(PantryItem, item_id)
    if not item:
        raise ValueError("Artículo no encontrado")

    item.is_active = False
    db.commit()
    return item


def get_categories(db: Session) -> list[str]:
    """Retorna las categorías únicas de items activos."""
    rows = db.query(PantryItem.category).filter(
        PantryItem.is_active == True,
        PantryItem.category.isnot(None),
    ).distinct().order_by(PantryItem.category).all()
    return [r[0] for r in rows]


# ==================== STOCK ====================

def stock_in(db: Session, item_id: int, quantity: int, notes: Optional[str] = None) -> PantryItem:
    """Registra entrada de stock."""
    if quantity <= 0:
        raise ValueError("La cantidad debe ser mayor a 0")

    item = db.get(PantryItem, item_id)
    if not item:
        raise ValueError("Artículo no encontrado")

    item.current_stock += quantity
    db.commit()
    return item


def stock_out(db: Session, item_id: int, quantity: int, notes: Optional[str] = None) -> PantryItem:
    """Registra salida de stock."""
    if quantity <= 0:
        raise ValueError("La cantidad debe ser mayor a 0")

    item = db.get(PantryItem, item_id)
    if not item:
        raise ValueError("Artículo no encontrado")

    if item.current_stock < quantity:
        raise ValueError("Stock insuficiente")

    item.current_stock -= quantity
    db.commit()
    return item


def get_stock_summary(db: Session) -> dict:
    """Retorna resumen del inventario."""
    items = db.query(PantryItem).filter_by(is_active=True).order_by(PantryItem.name).all()

    total_items = len(items)
    total_stock = sum(i.current_stock for i in items)
    low_stock = [i for i in items if i.current_stock <= 5]

    return {
        'items': [i.to_dict() for i in items],
        'total_items': total_items,
        'total_stock': total_stock,
        'low_stock_count': len(low_stock),
    }


# ==================== CAMPAÑAS ====================

def get_campaigns(
    db: Session,
    is_active: Optional[bool] = None,
    page: int = 1,
    per_page: int = 20,
) -> dict:
    """Lista campañas con paginación."""
    query = db.query(PantryCampaign)

    if is_active is not None:
        query = query.filter(PantryCampaign.is_active == is_active)

    query = query.order_by(PantryCampaign.created_at.desc())
    pagination = paginate(query, page=page, per_page=per_page)

    return {
        'items': [c.to_dict() for c in pagination.items],
        'total': pagination.total,
        'pages': pagination.pages,
        'page': page,
        'has_next': pagination.has_next,
        'has_prev': pagination.has_prev,
    }


def get_active_campaigns(db: Session) -> list[dict]:
    """Retorna campañas activas."""
    campaigns = db.query(PantryCampaign).filter_by(is_active=True).order_by(
        PantryCampaign.end_date.asc()
    ).all()
    return [c.to_dict() for c in campaigns]


def get_campaign_by_id(db: Session, campaign_id: int) -> Optional[PantryCampaign]:
    """Obtiene una campaña por ID."""
    return db.get(PantryCampaign, campaign_id)


def create_campaign(db: Session, data: dict) -> PantryCampaign:
    """Crea una nueva campaña."""
    name = (data.get('name') or '').strip()
    if not name:
        raise ValueError("El nombre es requerido")

    campaign = PantryCampaign(
        name=name,
        description=data.get('description'),
        requested_item_id=data.get('requested_item_id'),
        goal_quantity=data.get('goal_quantity'),
        start_date=_parse_date(data.get('start_date')),
        end_date=_parse_date(data.get('end_date')),
    )

    db.add(campaign)
    db.commit()
    return campaign


def update_campaign(db: Session, campaign_id: int, data: dict) -> PantryCampaign:
    """Actualiza una campaña."""
    campaign = db.get(PantryCampaign, campaign_id)
    if not campaign:
        raise ValueError("Campaña no encontrada")

    if 'name' in data:
        name = (data['name'] or '').strip()
        if not name:
            raise ValueError("El nombre es requerido")
        campaign.name = name
    if 'description' in data:
        campaign.description = data['description']
    if 'requested_item_id' in data:
        campaign.requested_item_id = data['requested_item_id']
    if 'goal_quantity' in data:
        campaign.goal_quantity = data['goal_quantity']
    if 'start_date' in data:
        campaign.start_date = _parse_date(data['start_date'])
    if 'end_date' in data:
        campaign.end_date = _parse_date(data['end_date'])

    db.commit()
    return campaign


def deactivate_campaign(db: Session, campaign_id: int) -> PantryCampaign:
    """Desactiva una campaña."""
    campaign = db.get(PantryCampaign, campaign_id)
    if not campaign:
        raise ValueError("Campaña no encontrada")

    campaign.is_active = False
    db.commit()
    return campaign


def _parse_date(value) -> Optional[date]:
    """Convierte string ISO a date, o retorna None."""
    if not value:
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(value)
