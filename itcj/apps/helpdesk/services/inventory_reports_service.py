"""
Servicio para reportes de inventario con multi-filtros y exportación
"""
from itcj.core.extensions import db
from itcj.apps.helpdesk.models import (
    InventoryItem, InventoryCategory, InventoryHistory
)
from sqlalchemy import func, desc, and_, or_
from datetime import datetime, timedelta, date
import csv
import io
import logging

logger = logging.getLogger(__name__)


class InventoryReportsService:
    """Reportes avanzados de inventario"""

    # ==================== REPORTE DE EQUIPOS ====================

    @staticmethod
    def get_equipment_report(filters: dict) -> dict:
        """
        Reporte de equipos con multi-filtros.

        Args:
            filters: {
                department_ids: list[int],
                category_ids: list[int],
                statuses: list[str],
                brand: str,
                search: str,
                include_inactive: bool,
                page: int,
                per_page: int
            }

        Returns:
            { items: [...], total: int, page: int, per_page: int, total_pages: int }
        """
        query = InventoryItem.query

        # Activos por defecto
        if not filters.get('include_inactive'):
            query = query.filter(InventoryItem.is_active == True)

        # Multi-filtro departamentos
        dept_ids = filters.get('department_ids', [])
        if dept_ids:
            query = query.filter(InventoryItem.department_id.in_(dept_ids))

        # Multi-filtro categorías
        cat_ids = filters.get('category_ids', [])
        if cat_ids:
            query = query.filter(InventoryItem.category_id.in_(cat_ids))

        # Multi-filtro estados
        statuses = filters.get('statuses', [])
        if statuses:
            query = query.filter(InventoryItem.status.in_([s.upper() for s in statuses]))

        # Filtro marca
        brand = filters.get('brand', '').strip()
        if brand:
            query = query.filter(InventoryItem.brand.ilike(f'%{brand}%'))

        # Búsqueda general
        search = filters.get('search', '').strip()
        if search:
            search_filter = or_(
                InventoryItem.inventory_number.ilike(f'%{search}%'),
                InventoryItem.brand.ilike(f'%{search}%'),
                InventoryItem.model.ilike(f'%{search}%'),
                InventoryItem.serial_number.ilike(f'%{search}%'),
                InventoryItem.location_detail.ilike(f'%{search}%'),
            )
            query = query.filter(search_filter)

        # Orden
        query = query.order_by(InventoryItem.inventory_number)

        # Paginación
        page = max(1, filters.get('page', 1))
        per_page = min(500, max(1, filters.get('per_page', 50)))
        total = query.count()
        total_pages = (total + per_page - 1) // per_page

        items = query.offset((page - 1) * per_page).limit(per_page).all()

        return {
            'items': [item.to_dict(include_relations=True) for item in items],
            'total': total,
            'page': page,
            'per_page': per_page,
            'total_pages': total_pages,
        }

    # ==================== REPORTE DE MOVIMIENTOS ====================

    @staticmethod
    def get_movements_report(filters: dict) -> dict:
        """
        Reporte de movimientos/historial con multi-filtros.

        Args:
            filters: {
                date_from: str (ISO),
                date_to: str (ISO),
                event_types: list[str],
                department_ids: list[int],
                performed_by_id: int,
                search: str,
                page: int,
                per_page: int
            }

        Returns:
            { events: [...], total: int, page: int, per_page: int, total_pages: int }
        """
        query = db.session.query(InventoryHistory).join(
            InventoryItem, InventoryHistory.item_id == InventoryItem.id
        )

        # Rango de fechas
        date_from = filters.get('date_from')
        if date_from:
            try:
                dt_from = datetime.fromisoformat(date_from)
                query = query.filter(InventoryHistory.timestamp >= dt_from)
            except ValueError:
                pass

        date_to = filters.get('date_to')
        if date_to:
            try:
                dt_to = datetime.fromisoformat(date_to)
                # Incluir todo el día
                if dt_to.hour == 0 and dt_to.minute == 0:
                    dt_to = dt_to + timedelta(days=1)
                query = query.filter(InventoryHistory.timestamp < dt_to)
            except ValueError:
                pass

        # Tipos de evento
        event_types = filters.get('event_types', [])
        if event_types:
            query = query.filter(
                InventoryHistory.event_type.in_([e.upper() for e in event_types])
            )

        # Departamentos del equipo
        dept_ids = filters.get('department_ids', [])
        if dept_ids:
            query = query.filter(InventoryItem.department_id.in_(dept_ids))

        # Usuario que realizó la acción
        performed_by_id = filters.get('performed_by_id')
        if performed_by_id:
            query = query.filter(
                InventoryHistory.performed_by_id == performed_by_id
            )

        # Búsqueda en notas o número de inventario
        search = filters.get('search', '').strip()
        if search:
            search_filter = or_(
                InventoryHistory.notes.ilike(f'%{search}%'),
                InventoryItem.inventory_number.ilike(f'%{search}%'),
                InventoryItem.serial_number.ilike(f'%{search}%'),
            )
            query = query.filter(search_filter)

        # Orden: más reciente primero
        query = query.order_by(desc(InventoryHistory.timestamp))

        # Paginación
        page = max(1, filters.get('page', 1))
        per_page = min(500, max(1, filters.get('per_page', 50)))
        total = query.count()
        total_pages = (total + per_page - 1) // per_page

        events = query.offset((page - 1) * per_page).limit(per_page).all()

        return {
            'events': [e.to_dict(include_relations=True) for e in events],
            'total': total,
            'page': page,
            'per_page': per_page,
            'total_pages': total_pages,
        }

    # ==================== EXPORTACIÓN CSV ====================

    @staticmethod
    def export_equipment_csv(filters: dict) -> str:
        """Genera CSV de reporte de equipos (sin paginación)."""
        # Sin paginación para export
        filters_copy = {**filters, 'page': 1, 'per_page': 10000}
        result = InventoryReportsService.get_equipment_report(filters_copy)

        output = io.StringIO()
        writer = csv.writer(output)

        # Header
        writer.writerow([
            'No. Inventario', 'Categoría', 'Marca', 'Modelo',
            'No. Serie', 'Departamento', 'Asignado a', 'Ubicación',
            'Estado', 'Fecha Adquisición', 'Vencimiento Garantía',
            'Último Mantenimiento', 'Próx. Mantenimiento', 'Notas'
        ])

        for item in result['items']:
            dept = item.get('department') or {}
            user = item.get('assigned_to_user') or {}
            cat = item.get('category') or {}
            writer.writerow([
                item.get('inventory_number', ''),
                cat.get('name', ''),
                item.get('brand', ''),
                item.get('model', ''),
                item.get('serial_number', ''),
                dept.get('name', ''),
                user.get('full_name', 'Sin asignar'),
                item.get('location_detail', ''),
                item.get('status', ''),
                item.get('acquisition_date', ''),
                item.get('warranty_expiration', ''),
                item.get('last_maintenance_date', ''),
                item.get('next_maintenance_date', ''),
                item.get('notes', ''),
            ])

        return output.getvalue()

    @staticmethod
    def export_movements_csv(filters: dict) -> str:
        """Genera CSV de reporte de movimientos (sin paginación)."""
        filters_copy = {**filters, 'page': 1, 'per_page': 10000}
        result = InventoryReportsService.get_movements_report(filters_copy)

        output = io.StringIO()
        writer = csv.writer(output)

        writer.writerow([
            'Fecha', 'Tipo de Evento', 'No. Inventario', 'Equipo',
            'Realizado por', 'Notas', 'Valor Anterior', 'Valor Nuevo'
        ])

        event_labels = InventoryReportsService.get_event_type_labels()

        for event in result['events']:
            performed_by = event.get('performed_by') or {}
            # Obtener info del equipo desde el evento
            item_id = event.get('item_id', '')

            writer.writerow([
                event.get('timestamp', ''),
                event_labels.get(event.get('event_type', ''), event.get('event_type', '')),
                event.get('item_id', ''),
                '',  # Se llena en frontend con relación
                performed_by.get('full_name', ''),
                event.get('notes', ''),
                str(event.get('old_value', '')),
                str(event.get('new_value', '')),
            ])

        return output.getvalue()

    @staticmethod
    def export_warranty_csv() -> str:
        """Genera CSV de reporte de garantías."""
        from itcj.apps.helpdesk.services.inventory_stats_service import InventoryStatsService
        report = InventoryStatsService.get_warranty_report()

        output = io.StringIO()
        writer = csv.writer(output)

        writer.writerow([
            'Estado', 'No. Inventario', 'Marca', 'Modelo',
            'Departamento', 'Vencimiento Garantía', 'Días Restantes'
        ])

        today = date.today()

        # Items por vencer en 30 días
        for item in report['expiring_30_days']['items']:
            days_left = ''
            if item.get('warranty_expiration'):
                try:
                    exp = date.fromisoformat(item['warranty_expiration'])
                    days_left = (exp - today).days
                except (ValueError, TypeError):
                    pass
            writer.writerow([
                'Vence en 30 días', item.get('inventory_number', ''),
                item.get('brand', ''), item.get('model', ''),
                '', item.get('warranty_expiration', ''), days_left
            ])

        # Items por vencer en 60 días
        for item in report['expiring_60_days']['items']:
            days_left = ''
            if item.get('warranty_expiration'):
                try:
                    exp = date.fromisoformat(item['warranty_expiration'])
                    days_left = (exp - today).days
                except (ValueError, TypeError):
                    pass
            writer.writerow([
                'Vence en 60 días', item.get('inventory_number', ''),
                item.get('brand', ''), item.get('model', ''),
                '', item.get('warranty_expiration', ''), days_left
            ])

        return output.getvalue()

    @staticmethod
    def export_maintenance_csv() -> str:
        """Genera CSV de reporte de mantenimiento."""
        from itcj.apps.helpdesk.services.inventory_stats_service import InventoryStatsService
        report = InventoryStatsService.get_maintenance_report()

        output = io.StringIO()
        writer = csv.writer(output)

        writer.writerow([
            'Estado', 'No. Inventario', 'Marca', 'Modelo',
            'Departamento', 'Próx. Mantenimiento', 'Último Mantenimiento'
        ])

        for item in report['overdue']['items']:
            writer.writerow([
                'Vencido', item.get('inventory_number', ''),
                item.get('brand', ''), item.get('model', ''),
                '', item.get('next_maintenance_date', ''),
                item.get('last_maintenance_date', '')
            ])

        for item in report['upcoming_30_days']['items']:
            writer.writerow([
                'Próximos 30 días', item.get('inventory_number', ''),
                item.get('brand', ''), item.get('model', ''),
                '', item.get('next_maintenance_date', ''),
                item.get('last_maintenance_date', '')
            ])

        return output.getvalue()

    @staticmethod
    def export_lifecycle_csv() -> str:
        """Genera CSV de reporte de ciclo de vida."""
        from itcj.apps.helpdesk.services.inventory_stats_service import InventoryStatsService
        report = InventoryStatsService.get_lifecycle_report()

        output = io.StringIO()
        writer = csv.writer(output)

        writer.writerow([
            'Antigüedad', 'No. Inventario', 'Marca', 'Modelo',
            'Departamento', 'Fecha Adquisición', 'Años'
        ])

        today = date.today()
        for item in report['older_than_5_years']['items']:
            years = ''
            if item.get('acquisition_date'):
                try:
                    acq = date.fromisoformat(item['acquisition_date'])
                    years = round((today - acq).days / 365.25, 1)
                except (ValueError, TypeError):
                    pass
            writer.writerow([
                'Más de 5 años', item.get('inventory_number', ''),
                item.get('brand', ''), item.get('model', ''),
                '', item.get('acquisition_date', ''), years
            ])

        return output.getvalue()

    # ==================== HELPERS ====================

    @staticmethod
    def get_event_type_labels() -> dict:
        """Mapeo de event_type a etiqueta legible."""
        return {
            'REGISTERED': 'Registrado',
            'ASSIGNED_TO_DEPT': 'Asignado a Depto.',
            'ASSIGNED_TO_USER': 'Asignado a Usuario',
            'UNASSIGNED': 'Desasignado',
            'REASSIGNED': 'Reasignado',
            'LOCATION_CHANGED': 'Cambio de Ubicación',
            'STATUS_CHANGED': 'Cambio de Estado',
            'MAINTENANCE_SCHEDULED': 'Mantenimiento Programado',
            'MAINTENANCE_COMPLETED': 'Mantenimiento Completado',
            'SPECS_UPDATED': 'Specs Actualizadas',
            'TRANSFERRED': 'Transferido',
            'DEACTIVATED': 'Dado de Baja',
            'REACTIVATED': 'Reactivado',
        }

    @staticmethod
    def get_status_labels() -> dict:
        """Mapeo de status a etiqueta legible."""
        return {
            'PENDING_ASSIGNMENT': 'Pendiente',
            'ACTIVE': 'Activo',
            'MAINTENANCE': 'En Mantenimiento',
            'DAMAGED': 'Dañado',
            'RETIRED': 'Retirado',
            'LOST': 'Extraviado',
        }
