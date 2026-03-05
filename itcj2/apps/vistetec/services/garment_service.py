"""Servicio de gestión de prendas (CRUD)."""
from datetime import datetime

from sqlalchemy import or_
from sqlalchemy.orm import Session

from itcj2.apps.vistetec.models.garment import Garment
from itcj2.apps.vistetec.services import image_service
from itcj2.models.base import paginate


def _generate_code(db: Session) -> str:
    """Genera un código secuencial: PRD-YYYY-NNNN."""
    year = datetime.now().year
    prefix = f'PRD-{year}-'

    last = (
        db.query(Garment)
        .filter(Garment.code.like(f'{prefix}%'))
        .order_by(Garment.code.desc())
        .first()
    )

    if last:
        try:
            seq = int(last.code.split('-')[-1]) + 1
        except (ValueError, IndexError):
            seq = 1
    else:
        seq = 1

    return f'{prefix}{seq:04d}'


def create_garment(db: Session, data, image_file=None, registered_by_id=None):
    """Crea una nueva prenda en el catálogo."""
    garment = Garment(
        code=_generate_code(db),
        name=data['name'],
        description=data.get('description'),
        category=data['category'],
        gender=data.get('gender'),
        size=data.get('size'),
        brand=data.get('brand'),
        color=data.get('color'),
        material=data.get('material'),
        condition=data['condition'],
        status='available',
        donated_by_id=data.get('donated_by_id'),
        received_by_id=registered_by_id,
        registered_by_id=registered_by_id,
    )

    if image_file:
        garment.image_path = image_service.save_garment_image(image_file, garment.code)

    db.add(garment)
    db.commit()

    return garment


def update_garment(db: Session, garment_id, data, image_file=None):
    """Actualiza una prenda existente."""
    garment = db.get(Garment, garment_id)
    if not garment:
        return None

    updatable_fields = [
        'name', 'description', 'category', 'gender', 'size',
        'brand', 'color', 'material', 'condition',
    ]
    for field in updatable_fields:
        if field in data:
            setattr(garment, field, data[field])

    if image_file:
        image_service.delete_garment_image(garment.image_path)
        garment.image_path = image_service.save_garment_image(image_file, garment.code)

    db.commit()
    return garment


def delete_garment(db: Session, garment_id):
    """Elimina una prenda del sistema."""
    garment = db.get(Garment, garment_id)
    if not garment:
        return False

    image_service.delete_garment_image(garment.image_path)
    db.delete(garment)
    db.commit()
    return True


def withdraw_garment(db: Session, garment_id):
    """Retira una prenda del catálogo sin entregarla."""
    garment = db.get(Garment, garment_id)
    if not garment:
        return None
    if garment.status not in ('available', 'reserved'):
        return None

    image_service.delete_garment_image(garment.image_path)
    garment.image_path = None
    garment.status = 'withdrawn'
    db.commit()
    return garment


def deliver_garment(db: Session, garment_id, delivered_to_id, delivered_by_id):
    """Marca una prenda como entregada a un estudiante."""
    garment = db.get(Garment, garment_id)
    if not garment:
        return None

    image_service.delete_garment_image(garment.image_path)
    garment.image_path = None
    garment.status = 'delivered'
    garment.delivered_to_id = delivered_to_id
    garment.delivered_by_id = delivered_by_id
    garment.delivered_at = datetime.now()
    db.commit()
    return garment


def list_all_garments(db: Session, page=1, per_page=20, status=None, category=None, search=None):
    """Lista todas las prendas (para voluntarios/admin)."""
    query = db.query(Garment)

    if status:
        query = query.filter(Garment.status == status)
    if category:
        query = query.filter(Garment.category == category)
    if search:
        term = f'%{search}%'
        query = query.filter(
            or_(
                Garment.name.ilike(term),
                Garment.code.ilike(term),
                Garment.brand.ilike(term),
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
