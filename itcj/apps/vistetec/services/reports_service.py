"""Servicio de reportes y estadísticas para VisteTec."""

from datetime import datetime, timedelta

from sqlalchemy import func, case, extract

from itcj.core.extensions import db
from itcj.apps.vistetec.models.garment import Garment
from itcj.apps.vistetec.models.donation import Donation
from itcj.apps.vistetec.models.appointment import Appointment
from itcj.apps.vistetec.models.pantry_item import PantryItem
from itcj.apps.vistetec.models.pantry_campaign import PantryCampaign


def get_dashboard_summary():
    """Resumen general para el dashboard administrativo."""
    garments = _garment_summary()
    donations = _donation_summary()
    appointments = _appointment_summary()
    pantry = _pantry_summary()

    return {
        'garments': garments,
        'donations': donations,
        'appointments': appointments,
        'pantry': pantry,
    }


def _garment_summary():
    """Estadísticas resumidas de prendas."""
    total = Garment.query.count()
    by_status = dict(
        db.session.query(
            Garment.status, func.count(Garment.id)
        ).group_by(Garment.status).all()
    )

    thirty_days_ago = datetime.utcnow() - timedelta(days=30)
    recent = Garment.query.filter(Garment.created_at >= thirty_days_ago).count()

    return {
        'total': total,
        'available': by_status.get('available', 0),
        'reserved': by_status.get('reserved', 0),
        'delivered': by_status.get('delivered', 0),
        'withdrawn': by_status.get('withdrawn', 0),
        'recent_30d': recent,
    }


def _donation_summary():
    """Estadísticas resumidas de donaciones."""
    total = Donation.query.count()
    garments = Donation.query.filter_by(donation_type='garment').count()
    pantry = Donation.query.filter_by(donation_type='pantry').count()

    thirty_days_ago = datetime.utcnow() - timedelta(days=30)
    recent = Donation.query.filter(Donation.created_at >= thirty_days_ago).count()

    pantry_items_total = db.session.query(
        func.coalesce(func.sum(Donation.quantity), 0)
    ).filter(Donation.donation_type == 'pantry').scalar()

    return {
        'total': total,
        'garments': garments,
        'pantry': pantry,
        'pantry_items_total': int(pantry_items_total),
        'recent_30d': recent,
    }


def _appointment_summary():
    """Estadísticas resumidas de citas."""
    total = Appointment.query.count()
    by_status = dict(
        db.session.query(
            Appointment.status, func.count(Appointment.id)
        ).group_by(Appointment.status).all()
    )

    completed = by_status.get('completed', 0)
    no_show = by_status.get('no_show', 0)
    total_final = completed + no_show
    attendance_rate = round((completed / total_final * 100), 1) if total_final > 0 else 0

    by_outcome = dict(
        db.session.query(
            Appointment.outcome, func.count(Appointment.id)
        ).filter(Appointment.outcome.isnot(None)).group_by(Appointment.outcome).all()
    )

    return {
        'total': total,
        'scheduled': by_status.get('scheduled', 0),
        'completed': completed,
        'no_show': no_show,
        'cancelled': by_status.get('cancelled', 0),
        'attendance_rate': attendance_rate,
        'outcomes': {
            'taken': by_outcome.get('taken', 0),
            'not_fit': by_outcome.get('not_fit', 0),
            'declined': by_outcome.get('declined', 0),
        },
    }


def _pantry_summary():
    """Estadísticas resumidas de despensa."""
    total_items = PantryItem.query.filter_by(is_active=True).count()
    total_stock = db.session.query(
        func.coalesce(func.sum(PantryItem.current_stock), 0)
    ).filter(PantryItem.is_active == True).scalar()
    low_stock = PantryItem.query.filter(
        PantryItem.is_active == True,
        PantryItem.current_stock <= 5,
    ).count()

    active_campaigns = PantryCampaign.query.filter_by(is_active=True).count()

    return {
        'total_items': total_items,
        'total_stock': int(total_stock),
        'low_stock': low_stock,
        'active_campaigns': active_campaigns,
    }


def get_garment_report(date_from=None, date_to=None):
    """Reporte detallado de prendas."""
    query = Garment.query

    if date_from:
        query = query.filter(Garment.created_at >= date_from)
    if date_to:
        query = query.filter(Garment.created_at <= date_to)

    total = query.count()

    by_status = dict(
        db.session.query(
            Garment.status, func.count(Garment.id)
        ).filter(
            *_date_filters(Garment.created_at, date_from, date_to)
        ).group_by(Garment.status).all()
    )

    by_category = [
        {'category': cat, 'count': cnt}
        for cat, cnt in db.session.query(
            Garment.category, func.count(Garment.id)
        ).filter(
            *_date_filters(Garment.created_at, date_from, date_to)
        ).group_by(Garment.category).order_by(func.count(Garment.id).desc()).all()
    ]

    by_condition = [
        {'condition': cond, 'count': cnt}
        for cond, cnt in db.session.query(
            Garment.condition, func.count(Garment.id)
        ).filter(
            *_date_filters(Garment.created_at, date_from, date_to)
        ).group_by(Garment.condition).order_by(func.count(Garment.id).desc()).all()
    ]

    by_gender = [
        {'gender': g or 'sin_especificar', 'count': cnt}
        for g, cnt in db.session.query(
            Garment.gender, func.count(Garment.id)
        ).filter(
            *_date_filters(Garment.created_at, date_from, date_to)
        ).group_by(Garment.gender).order_by(func.count(Garment.id).desc()).all()
    ]

    return {
        'total': total,
        'by_status': by_status,
        'by_category': by_category,
        'by_condition': by_condition,
        'by_gender': by_gender,
    }


def get_donation_report(date_from=None, date_to=None):
    """Reporte detallado de donaciones."""
    filters = _date_filters(Donation.created_at, date_from, date_to)

    total = db.session.query(func.count(Donation.id)).filter(*filters).scalar()

    by_type = dict(
        db.session.query(
            Donation.donation_type, func.count(Donation.id)
        ).filter(*filters).group_by(Donation.donation_type).all()
    )

    # Donaciones por mes (últimos 6 meses)
    six_months_ago = datetime.utcnow() - timedelta(days=180)
    effective_from = date_from if date_from and date_from > six_months_ago else six_months_ago

    monthly = [
        {
            'year': int(year),
            'month': int(month),
            'count': cnt,
        }
        for year, month, cnt in db.session.query(
            extract('year', Donation.created_at),
            extract('month', Donation.created_at),
            func.count(Donation.id),
        ).filter(
            Donation.created_at >= effective_from,
            *(_date_filters(Donation.created_at, None, date_to))
        ).group_by(
            extract('year', Donation.created_at),
            extract('month', Donation.created_at),
        ).order_by(
            extract('year', Donation.created_at),
            extract('month', Donation.created_at),
        ).all()
    ]

    # Top 5 artículos de despensa más donados
    top_pantry = [
        {'item_name': name, 'total_quantity': int(qty)}
        for name, qty in db.session.query(
            PantryItem.name,
            func.sum(Donation.quantity),
        ).join(PantryItem, Donation.pantry_item_id == PantryItem.id).filter(
            Donation.donation_type == 'pantry',
            *filters,
        ).group_by(PantryItem.name).order_by(
            func.sum(Donation.quantity).desc()
        ).limit(5).all()
    ]

    return {
        'total': total,
        'by_type': by_type,
        'monthly': monthly,
        'top_pantry_items': top_pantry,
    }


def get_appointment_report(date_from=None, date_to=None):
    """Reporte detallado de citas."""
    filters = _date_filters(Appointment.created_at, date_from, date_to)

    total = db.session.query(func.count(Appointment.id)).filter(*filters).scalar()

    by_status = dict(
        db.session.query(
            Appointment.status, func.count(Appointment.id)
        ).filter(*filters).group_by(Appointment.status).all()
    )

    by_outcome = dict(
        db.session.query(
            Appointment.outcome, func.count(Appointment.id)
        ).filter(
            Appointment.outcome.isnot(None),
            *filters,
        ).group_by(Appointment.outcome).all()
    )

    completed = by_status.get('completed', 0)
    no_show = by_status.get('no_show', 0)
    total_final = completed + no_show
    attendance_rate = round((completed / total_final * 100), 1) if total_final > 0 else 0

    # Citas por mes
    six_months_ago = datetime.utcnow() - timedelta(days=180)
    effective_from = date_from if date_from and date_from > six_months_ago else six_months_ago

    monthly = [
        {
            'year': int(year),
            'month': int(month),
            'count': cnt,
        }
        for year, month, cnt in db.session.query(
            extract('year', Appointment.created_at),
            extract('month', Appointment.created_at),
            func.count(Appointment.id),
        ).filter(
            Appointment.created_at >= effective_from,
            *(_date_filters(Appointment.created_at, None, date_to))
        ).group_by(
            extract('year', Appointment.created_at),
            extract('month', Appointment.created_at),
        ).order_by(
            extract('year', Appointment.created_at),
            extract('month', Appointment.created_at),
        ).all()
    ]

    return {
        'total': total,
        'by_status': by_status,
        'by_outcome': by_outcome,
        'attendance_rate': attendance_rate,
        'monthly': monthly,
    }


def get_recent_activity(limit=15):
    """Actividad reciente (donaciones, citas, prendas combinadas)."""
    activities = []

    # Últimas donaciones
    donations = Donation.query.order_by(
        Donation.created_at.desc()
    ).limit(limit).all()
    for d in donations:
        activities.append({
            'type': 'donation',
            'icon': 'bi-heart-fill',
            'color': '#dc3545',
            'message': f'Donación {d.code} ({d.donation_type})',
            'date': d.created_at.isoformat() if d.created_at else None,
            'timestamp': d.created_at,
        })

    # Últimas citas completadas
    appointments = Appointment.query.filter(
        Appointment.status.in_(['completed', 'attended'])
    ).order_by(Appointment.updated_at.desc()).limit(limit).all()
    for a in appointments:
        activities.append({
            'type': 'appointment',
            'icon': 'bi-calendar-check-fill',
            'color': '#198754',
            'message': f'Cita {a.code} - {a.status}',
            'date': (a.updated_at or a.created_at).isoformat(),
            'timestamp': a.updated_at or a.created_at,
        })

    # Últimas prendas registradas
    garments = Garment.query.order_by(
        Garment.created_at.desc()
    ).limit(limit).all()
    for g in garments:
        activities.append({
            'type': 'garment',
            'icon': 'bi-bag-plus-fill',
            'color': '#8B1538',
            'message': f'Prenda {g.code} - {g.name}',
            'date': g.created_at.isoformat() if g.created_at else None,
            'timestamp': g.created_at,
        })

    # Ordenar por fecha y tomar los más recientes
    activities.sort(key=lambda x: x['timestamp'] or datetime.min, reverse=True)
    for a in activities:
        del a['timestamp']

    return activities[:limit]


def _date_filters(column, date_from=None, date_to=None):
    """Construye filtros de fecha para queries."""
    filters = []
    if date_from:
        filters.append(column >= date_from)
    if date_to:
        filters.append(column <= date_to)
    return filters
