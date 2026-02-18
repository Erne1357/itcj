"""Servicio del catálogo público de prendas."""
from itcj.core.extensions import db
from itcj.apps.vistetec.models.garment import Garment
from sqlalchemy import or_


def list_garments(page=1, per_page=12, category=None, gender=None,
                  size=None, color=None, condition=None, search=None):
    """
    Lista prendas disponibles con filtros y paginación.
    Solo muestra prendas con status 'available'.
    """
    query = Garment.query.filter(Garment.status == 'available')

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
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    return {
        'items': [g.to_dict() for g in pagination.items],
        'total': pagination.total,
        'page': pagination.page,
        'per_page': pagination.per_page,
        'pages': pagination.pages,
        'has_next': pagination.has_next,
        'has_prev': pagination.has_prev,
    }


def get_garment_detail(garment_id):
    """Retorna el detalle de una prenda por su ID."""
    garment = Garment.query.get(garment_id)
    if not garment:
        return None
    return garment.to_dict(include_relations=True)


def get_available_categories():
    """Retorna las categorías que tienen prendas disponibles."""
    rows = (
        db.session.query(Garment.category, db.func.count(Garment.id))
        .filter(Garment.status == 'available')
        .group_by(Garment.category)
        .order_by(Garment.category)
        .all()
    )
    return [{'name': cat, 'count': count} for cat, count in rows]


def get_available_sizes():
    """Retorna las tallas que tienen prendas disponibles."""
    rows = (
        db.session.query(Garment.size, db.func.count(Garment.id))
        .filter(Garment.status == 'available', Garment.size.isnot(None))
        .group_by(Garment.size)
        .order_by(Garment.size)
        .all()
    )
    return [{'name': sz, 'count': count} for sz, count in rows]


def get_catalog_stats():
    """Estadísticas generales del catálogo."""
    total_available = Garment.query.filter(Garment.status == 'available').count()
    total_delivered = Garment.query.filter(Garment.status == 'delivered').count()
    total_registered = Garment.query.count()

    return {
        'available': total_available,
        'delivered': total_delivered,
        'total_registered': total_registered,
    }
