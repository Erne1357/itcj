"""Servicio del catálogo público de prendas."""
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from itcj2.apps.vistetec.models.garment import Garment
from itcj2.models.base import paginate


def list_garments(
    db: Session,
    page=1,
    per_page=12,
    category=None,
    gender=None,
    size=None,
    color=None,
    condition=None,
    search=None,
):
    """Lista prendas disponibles con filtros y paginación."""
    query = db.query(Garment).filter(Garment.status == 'available')

    if category:
        query = query.filter(Garment.category == category)
    if gender:
        query = query.filter(Garment.gender == gender)
    if size:
        query = query.filter(Garment.size == size)
    if color:
        query = query.filter(Garment.color.ilike(f'%{color}%'))
    if condition:
        query = query.filter(Garment.condition == condition)
    if search:
        term = f'%{search}%'
        query = query.filter(
            or_(
                Garment.name.ilike(term),
                Garment.description.ilike(term),
                Garment.brand.ilike(term),
                Garment.code.ilike(term),
            )
        )

    query = query.order_by(Garment.created_at.desc())
    pagination = paginate(query, page=page, per_page=per_page)

    return {
        'items': [g.to_dict() for g in pagination.items],
        'total': pagination.total,
        'page': pagination.page,
        'per_page': per_page,
        'pages': pagination.pages,
        'has_next': pagination.has_next,
        'has_prev': pagination.has_prev,
    }


def get_garment_detail(db: Session, garment_id):
    """Retorna el detalle de una prenda por su ID."""
    garment = db.get(Garment, garment_id)
    if not garment:
        return None
    return garment.to_dict(include_relations=True)


def get_available_categories(db: Session):
    """Retorna las categorías que tienen prendas disponibles."""
    rows = (
        db.query(Garment.category, func.count(Garment.id))
        .filter(Garment.status == 'available')
        .group_by(Garment.category)
        .order_by(Garment.category)
        .all()
    )
    return [{'name': cat, 'count': count} for cat, count in rows]


def get_available_sizes(db: Session):
    """Retorna las tallas que tienen prendas disponibles."""
    rows = (
        db.query(Garment.size, func.count(Garment.id))
        .filter(Garment.status == 'available', Garment.size.isnot(None))
        .group_by(Garment.size)
        .order_by(Garment.size)
        .all()
    )
    return [{'name': sz, 'count': count} for sz, count in rows]


def get_catalog_stats(db: Session):
    """Estadísticas generales del catálogo."""
    total_available = db.query(Garment).filter(Garment.status == 'available').count()
    total_delivered = db.query(Garment).filter(Garment.status == 'delivered').count()
    total_registered = db.query(Garment).count()

    return {
        'available': total_available,
        'delivered': total_delivered,
        'total_registered': total_registered,
    }
