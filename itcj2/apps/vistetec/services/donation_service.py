"""Servicio para gestión de donaciones."""
from datetime import datetime
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from itcj2.apps.vistetec.models.donation import Donation
from itcj2.apps.vistetec.models.garment import Garment
from itcj2.models.base import paginate


def _generate_code(db: Session) -> str:
    """Genera código único para donación: DON-YYYY-NNNN."""
    year = datetime.now().year
    prefix = f"DON-{year}-"

    last = db.query(Donation).filter(
        Donation.code.like(f"{prefix}%")
    ).order_by(Donation.id.desc()).first()

    if last:
        last_num = int(last.code.split('-')[-1])
        new_num = last_num + 1
    else:
        new_num = 1

    return f"{prefix}{new_num:04d}"


def get_donations(
    db: Session,
    donation_type: Optional[str] = None,
    donor_id: Optional[int] = None,
    page: int = 1,
    per_page: int = 20,
) -> dict:
    """Lista donaciones con paginación."""
    query = db.query(Donation)

    if donation_type:
        query = query.filter(Donation.donation_type == donation_type)
    if donor_id:
        query = query.filter(Donation.donor_id == donor_id)

    query = query.order_by(Donation.created_at.desc())
    pagination = paginate(query, page=page, per_page=per_page)

    return {
        'items': [d.to_dict(include_relations=True) for d in pagination.items],
        'total': pagination.total,
        'pages': pagination.pages,
        'page': page,
        'has_next': pagination.has_next,
        'has_prev': pagination.has_prev,
    }


def get_my_donations(db: Session, user_id: int, page: int = 1, per_page: int = 20) -> dict:
    """Lista donaciones de un usuario específico."""
    return get_donations(db, donor_id=user_id, page=page, per_page=per_page)


def get_donation_by_id(db: Session, donation_id: int) -> Optional[Donation]:
    """Obtiene una donación por ID."""
    return db.get(Donation, donation_id)


def get_donation_by_code(db: Session, code: str) -> Optional[Donation]:
    """Obtiene una donación por código."""
    return db.query(Donation).filter_by(code=code).first()


def register_garment_donation(
    db: Session,
    registered_by_id: int,
    garment_id: int,
    donor_id: Optional[int] = None,
    donor_name: Optional[str] = None,
    notes: Optional[str] = None,
) -> Donation:
    """Registra una donación de prenda existente."""
    garment = db.get(Garment, garment_id)
    if not garment:
        raise ValueError("Prenda no encontrada")

    existing = db.query(Donation).filter_by(garment_id=garment_id).first()
    if existing:
        raise ValueError("Esta prenda ya tiene una donación registrada")

    donation = Donation(
        code=_generate_code(db),
        donor_id=donor_id,
        donor_name=donor_name if not donor_id else None,
        donation_type='garment',
        garment_id=garment_id,
        registered_by_id=registered_by_id,
        notes=notes,
    )

    garment.donated_by_id = donor_id

    db.add(donation)
    db.commit()

    return donation


def register_new_garment_donation(
    db: Session,
    registered_by_id: int,
    garment_data: dict,
    donor_id: Optional[int] = None,
    donor_name: Optional[str] = None,
    notes: Optional[str] = None,
) -> Donation:
    """Registra una donación creando una nueva prenda."""
    from itcj2.apps.vistetec.services import garment_service

    data = {
        'name': garment_data.get('name'),
        'category': garment_data.get('category'),
        'condition': garment_data.get('condition'),
        'description': garment_data.get('description'),
        'size': garment_data.get('size'),
        'color': garment_data.get('color'),
        'brand': garment_data.get('brand'),
        'gender': garment_data.get('gender'),
        'material': garment_data.get('material'),
        'donated_by_id': donor_id,
    }
    garment = garment_service.create_garment(
        db=db,
        data=data,
        registered_by_id=registered_by_id,
    )

    donation = Donation(
        code=_generate_code(db),
        donor_id=donor_id,
        donor_name=donor_name if not donor_id else None,
        donation_type='garment',
        garment_id=garment.id,
        registered_by_id=registered_by_id,
        notes=notes,
    )

    db.add(donation)
    db.commit()

    return donation


def register_pantry_donation(
    db: Session,
    registered_by_id: int,
    pantry_item_id: int,
    quantity: int = 1,
    donor_id: Optional[int] = None,
    donor_name: Optional[str] = None,
    campaign_id: Optional[int] = None,
    notes: Optional[str] = None,
) -> Donation:
    """Registra una donación de despensa."""
    from itcj2.apps.vistetec.models.pantry_campaign import PantryCampaign
    from itcj2.apps.vistetec.models.pantry_item import PantryItem

    item = db.get(PantryItem, pantry_item_id)
    if not item:
        raise ValueError("Producto de despensa no encontrado")

    campaign = None
    if campaign_id:
        campaign = db.get(PantryCampaign, campaign_id)
        if not campaign:
            raise ValueError("Campaña no encontrada")

    donation = Donation(
        code=_generate_code(db),
        donor_id=donor_id,
        donor_name=donor_name if not donor_id else None,
        donation_type='pantry',
        pantry_item_id=pantry_item_id,
        quantity=quantity,
        campaign_id=campaign_id,
        registered_by_id=registered_by_id,
        notes=notes,
    )

    item.current_stock += quantity

    if campaign:
        campaign.collected_quantity += quantity

    db.add(donation)
    db.commit()

    return donation


def get_donation_stats(db: Session, donor_id: Optional[int] = None) -> dict:
    """Obtiene estadísticas de donaciones."""
    base_query = db.query(Donation)

    if donor_id:
        base_query = base_query.filter(Donation.donor_id == donor_id)

    total = base_query.count()
    garments = base_query.filter(Donation.donation_type == 'garment').count()
    pantry = base_query.filter(Donation.donation_type == 'pantry').count()

    pantry_items_q = db.query(func.sum(Donation.quantity)).filter(
        Donation.donation_type == 'pantry'
    )
    if donor_id:
        pantry_items_q = pantry_items_q.filter(Donation.donor_id == donor_id)
    pantry_items = pantry_items_q.scalar() or 0

    return {
        'total_donations': total,
        'garments_donated': garments,
        'pantry_donations': pantry,
        'pantry_items_total': pantry_items,
    }


def get_top_donors(db: Session, limit: int = 10) -> list:
    """Obtiene los top donadores."""
    from itcj2.core.models.user import User

    results = db.query(
        Donation.donor_id,
        func.count(Donation.id).label('total')
    ).filter(
        Donation.donor_id.isnot(None)
    ).group_by(
        Donation.donor_id
    ).order_by(
        func.count(Donation.id).desc()
    ).limit(limit).all()

    donors = []
    for donor_id, total in results:
        user = db.get(User, donor_id)
        if user:
            donors.append({
                'id': donor_id,
                'name': user.full_name,
                'total_donations': total,
            })

    return donors


def get_recent_donations(db: Session, limit: int = 10) -> list[Donation]:
    """Obtiene las donaciones más recientes."""
    return db.query(Donation).order_by(
        Donation.created_at.desc()
    ).limit(limit).all()
