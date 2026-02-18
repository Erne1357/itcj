"""Servicio de gestión de prendas (CRUD)."""
from datetime import datetime
from itcj.core.extensions import db
from itcj.apps.vistetec.models.garment import Garment
from itcj.apps.vistetec.services import image_service


def _generate_code():
    """Genera un código secuencial: PRD-YYYY-NNNN."""
    year = datetime.now().year
    prefix = f'PRD-{year}-'

    last = (
        Garment.query
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


def create_garment(data, image_file=None, registered_by_id=None):
    """
    Crea una nueva prenda en el catálogo.

    Args:
        data: dict con campos de la prenda.
        image_file: FileStorage opcional.
        registered_by_id: ID del usuario que registra.

    Returns:
        Garment: La prenda creada.
    """
    garment = Garment(
        code=_generate_code(),
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

    db.session.add(garment)
    db.session.commit()

    return garment


def update_garment(garment_id, data, image_file=None):
    """
    Actualiza una prenda existente.

    Args:
        garment_id: ID de la prenda.
        data: dict con campos a actualizar.
        image_file: FileStorage opcional (reemplaza la imagen).

    Returns:
        Garment or None: La prenda actualizada.
    """
    garment = Garment.query.get(garment_id)
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
        # Eliminar imagen anterior
        image_service.delete_garment_image(garment.image_path)
        garment.image_path = image_service.save_garment_image(image_file, garment.code)

    db.session.commit()
    return garment


def delete_garment(garment_id):
    """
    Elimina una prenda del sistema (solo admin).
    Borra la imagen asociada del filesystem.

    Returns:
        bool: True si se eliminó, False si no existe.
    """
    garment = Garment.query.get(garment_id)
    if not garment:
        return False

    image_service.delete_garment_image(garment.image_path)
    db.session.delete(garment)
    db.session.commit()
    return True


def withdraw_garment(garment_id):
    """
    Retira una prenda del catálogo sin entregarla a nadie.
    Elimina la imagen.

    Returns:
        Garment or None: La prenda retirada.
    """
    garment = Garment.query.get(garment_id)
    if not garment:
        return None
    if garment.status not in ('available', 'reserved'):
        return None

    image_service.delete_garment_image(garment.image_path)
    garment.image_path = None
    garment.status = 'withdrawn'
    db.session.commit()
    return garment


def deliver_garment(garment_id, delivered_to_id, delivered_by_id):
    """
    Marca una prenda como entregada a un estudiante.
    Elimina la imagen del filesystem.

    Returns:
        Garment or None: La prenda entregada.
    """
    garment = Garment.query.get(garment_id)
    if not garment:
        return None

    image_service.delete_garment_image(garment.image_path)
    garment.image_path = None
    garment.status = 'delivered'
    garment.delivered_to_id = delivered_to_id
    garment.delivered_by_id = delivered_by_id
    garment.delivered_at = datetime.utcnow()
    db.session.commit()
    return garment


def list_all_garments(page=1, per_page=20, status=None, category=None, search=None):
    """
    Lista todas las prendas (para voluntarios/admin), incluyendo todos los estados.
    """
    query = Garment.query

    if status:
        query = query.filter(Garment.status == status)
    if category:
        query = query.filter(Garment.category == category)
    if search:
        term = f'%{search}%'
        from sqlalchemy import or_
        query = query.filter(
            or_(
                Garment.name.ilike(term),
                Garment.code.ilike(term),
                Garment.brand.ilike(term),
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
