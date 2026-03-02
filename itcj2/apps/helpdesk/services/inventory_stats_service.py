"""
Servicio para estadísticas de inventario
"""
from datetime import datetime, timedelta, date

from sqlalchemy import func, case, and_, or_
from sqlalchemy.orm import Session

from itcj2.apps.helpdesk.models.inventory_item import InventoryItem
from itcj2.apps.helpdesk.models.inventory_category import InventoryCategory
from itcj2.apps.helpdesk.models.ticket import Ticket


class InventoryStatsService:
    """Estadísticas y análisis del inventario"""

    @staticmethod
    def get_overview_stats(db: Session):
        """
        Obtiene estadísticas generales del inventario.
        """
        total = db.query(InventoryItem).filter_by(is_active=True).count()

        by_status = db.query(
            InventoryItem.status,
            func.count(InventoryItem.id)
        ).filter(
            InventoryItem.is_active == True
        ).group_by(InventoryItem.status).all()

        status_counts = {status: count for status, count in by_status}

        assigned_to_users = db.query(InventoryItem).filter(
            InventoryItem.is_active == True,
            InventoryItem.assigned_to_user_id.isnot(None)
        ).count()

        global_items = db.query(InventoryItem).filter(
            InventoryItem.is_active == True,
            InventoryItem.assigned_to_user_id.is_(None)
        ).count()

        under_warranty = db.query(InventoryItem).filter(
            InventoryItem.is_active == True,
            InventoryItem.warranty_expiration >= date.today()
        ).count()

        warranty_expiring_soon = db.query(InventoryItem).filter(
            InventoryItem.is_active == True,
            InventoryItem.warranty_expiration >= date.today(),
            InventoryItem.warranty_expiration <= date.today() + timedelta(days=60)
        ).count()

        needs_maintenance = db.query(InventoryItem).filter(
            InventoryItem.is_active == True,
            InventoryItem.next_maintenance_date.isnot(None),
            InventoryItem.next_maintenance_date <= date.today()
        ).count()

        return {
            'total': total,
            'by_status': status_counts,
            'assigned_to_users': assigned_to_users,
            'global_items': global_items,
            'under_warranty': under_warranty,
            'warranty_expiring_soon': warranty_expiring_soon,
            'needs_maintenance': needs_maintenance,
        }

    @staticmethod
    def get_by_category(db: Session):
        """
        Obtiene estadísticas por categoría.
        """
        results = db.query(
            InventoryCategory.id,
            InventoryCategory.name,
            InventoryCategory.code,
            InventoryCategory.icon,
            func.count(InventoryItem.id).label('count')
        ).outerjoin(
            InventoryItem,
            and_(
                InventoryItem.category_id == InventoryCategory.id,
                InventoryItem.is_active == True
            )
        ).filter(
            InventoryCategory.is_active == True
        ).group_by(
            InventoryCategory.id,
            InventoryCategory.name,
            InventoryCategory.code,
            InventoryCategory.icon
        ).order_by(
            InventoryCategory.display_order
        ).all()

        return [
            {
                'category_id': r.id,
                'category_name': r.name,
                'category_code': r.code,
                'icon': r.icon,
                'count': r.count
            }
            for r in results
        ]

    @staticmethod
    def get_by_department(db: Session):
        """
        Obtiene estadísticas por departamento.
        """
        from itcj2.core.models.department import Department

        results = db.query(
            Department.id,
            Department.name,
            func.count(InventoryItem.id).label('total'),
            func.sum(
                case(
                    (InventoryItem.assigned_to_user_id.isnot(None), 1),
                    else_=0
                )
            ).label('assigned'),
            func.sum(
                case(
                    (InventoryItem.assigned_to_user_id.is_(None), 1),
                    else_=0
                )
            ).label('global_items')
        ).outerjoin(
            InventoryItem,
            and_(
                InventoryItem.department_id == Department.id,
                InventoryItem.is_active == True
            )
        ).group_by(
            Department.id,
            Department.name
        ).order_by(
            func.count(InventoryItem.id).desc()
        ).all()

        return [
            {
                'department_id': r.id,
                'department_name': r.name,
                'total': r.total or 0,
                'assigned': r.assigned or 0,
                'global_items': r.global_items or 0
            }
            for r in results
        ]

    @staticmethod
    def get_problematic_items(db: Session, min_tickets=5, days=180):
        """
        Identifica equipos con muchas fallas.
        """
        since_date = datetime.now() - timedelta(days=days)

        results = db.query(
            InventoryItem,
            func.count(Ticket.id).label('ticket_count')
        ).outerjoin(
            Ticket,
            and_(
                Ticket.inventory_item_id == InventoryItem.id,
                Ticket.created_at >= since_date
            )
        ).filter(
            InventoryItem.is_active == True
        ).group_by(
            InventoryItem.id
        ).having(
            func.count(Ticket.id) >= min_tickets
        ).order_by(
            func.count(Ticket.id).desc()
        ).all()

        problematic = []
        for item, ticket_count in results:
            tickets = db.query(Ticket).filter(
                Ticket.inventory_item_id == item.id,
                Ticket.created_at >= since_date
            ).order_by(Ticket.created_at).all()

            if len(tickets) > 1:
                time_diffs = []
                for i in range(1, len(tickets)):
                    diff = (tickets[i].created_at - tickets[i-1].created_at).days
                    time_diffs.append(diff)
                mtbf_days = sum(time_diffs) / len(time_diffs) if time_diffs else 0
            else:
                mtbf_days = days

            problematic.append({
                'item': item,
                'ticket_count': ticket_count,
                'mtbf_days': round(mtbf_days, 1),
                'recommendation': InventoryStatsService._get_recommendation(
                    ticket_count, mtbf_days, item
                )
            })

        return problematic

    @staticmethod
    def _get_recommendation(ticket_count, mtbf_days, item):
        if ticket_count >= 15:
            return "CRÍTICO: Considerar reemplazo urgente"
        elif ticket_count >= 10:
            return "ALTO: Programar reemplazo en próximo ciclo"
        elif mtbf_days < 20:
            return "MEDIO: Revisar con técnico especializado"
        elif item.warranty_expiration and item.warranty_expiration < date.today():
            return "Fuera de garantía. Evaluar costo-beneficio"
        else:
            return "Monitorear de cerca"

    @staticmethod
    def get_warranty_report(db: Session):
        """
        Reporte de garantías.
        """
        today = date.today()

        under_warranty = db.query(InventoryItem).filter(
            InventoryItem.is_active == True,
            InventoryItem.warranty_expiration >= today
        ).count()

        expiring_30 = db.query(InventoryItem).filter(
            InventoryItem.is_active == True,
            InventoryItem.warranty_expiration >= today,
            InventoryItem.warranty_expiration <= today + timedelta(days=30)
        ).all()

        expiring_60 = db.query(InventoryItem).filter(
            InventoryItem.is_active == True,
            InventoryItem.warranty_expiration >= today + timedelta(days=31),
            InventoryItem.warranty_expiration <= today + timedelta(days=60)
        ).all()

        expired = db.query(InventoryItem).filter(
            InventoryItem.is_active == True,
            InventoryItem.warranty_expiration < today
        ).count()

        no_warranty_info = db.query(InventoryItem).filter(
            InventoryItem.is_active == True,
            InventoryItem.warranty_expiration.is_(None)
        ).count()

        return {
            'under_warranty': under_warranty,
            'expiring_30_days': {
                'count': len(expiring_30),
                'items': [item.to_dict() for item in expiring_30]
            },
            'expiring_60_days': {
                'count': len(expiring_60),
                'items': [item.to_dict() for item in expiring_60]
            },
            'expired': expired,
            'no_warranty_info': no_warranty_info
        }

    @staticmethod
    def get_maintenance_report(db: Session):
        """
        Reporte de mantenimientos.
        """
        today = date.today()

        overdue = db.query(InventoryItem).filter(
            InventoryItem.is_active == True,
            InventoryItem.next_maintenance_date.isnot(None),
            InventoryItem.next_maintenance_date < today
        ).all()

        upcoming_30 = db.query(InventoryItem).filter(
            InventoryItem.is_active == True,
            InventoryItem.next_maintenance_date >= today,
            InventoryItem.next_maintenance_date <= today + timedelta(days=30)
        ).all()

        six_months_ago = today - timedelta(days=180)
        no_recent_maintenance = db.query(InventoryItem).filter(
            InventoryItem.is_active == True,
            or_(
                InventoryItem.last_maintenance_date < six_months_ago,
                and_(
                    InventoryItem.last_maintenance_date.is_(None),
                    InventoryItem.acquisition_date < six_months_ago
                )
            )
        ).count()

        return {
            'overdue': {
                'count': len(overdue),
                'items': [item.to_dict() for item in overdue]
            },
            'upcoming_30_days': {
                'count': len(upcoming_30),
                'items': [item.to_dict() for item in upcoming_30]
            },
            'no_recent_maintenance': no_recent_maintenance
        }

    @staticmethod
    def get_lifecycle_report(db: Session):
        """
        Reporte de ciclo de vida (equipos antiguos).
        """
        today = date.today()

        five_years_ago = today - timedelta(days=365*5)
        older_than_5_years = db.query(InventoryItem).filter(
            InventoryItem.is_active == True,
            InventoryItem.acquisition_date < five_years_ago
        ).all()

        three_years_ago = today - timedelta(days=365*3)
        between_3_and_5_years = db.query(InventoryItem).filter(
            InventoryItem.is_active == True,
            InventoryItem.acquisition_date >= five_years_ago,
            InventoryItem.acquisition_date < three_years_ago
        ).count()

        one_year_ago = today - timedelta(days=365)
        less_than_1_year = db.query(InventoryItem).filter(
            InventoryItem.is_active == True,
            InventoryItem.acquisition_date >= one_year_ago
        ).count()

        return {
            'older_than_5_years': {
                'count': len(older_than_5_years),
                'items': [item.to_dict() for item in older_than_5_years],
                'recommendation': 'Evaluar para reemplazo programado'
            },
            'between_3_and_5_years': between_3_and_5_years,
            'less_than_1_year': less_than_1_year
        }
