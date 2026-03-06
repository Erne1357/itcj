"""
Servicio para reportes de inventario con multi-filtros y exportación CSV.
Equivalente a itcj/apps/helpdesk/services/inventory_reports_service.py
adaptado a SQLAlchemy 2.0 (sesión explícita).
"""
import csv
import io
import logging
from datetime import date, datetime, timedelta

from sqlalchemy import desc, or_
from sqlalchemy.orm import Session

from itcj2.apps.helpdesk.models.inventory_history import InventoryHistory
from itcj2.apps.helpdesk.models.inventory_item import InventoryItem

logger = logging.getLogger(__name__)


class InventoryReportsService:
    """Reportes avanzados de inventario."""

    # ── Reporte de equipos ────────────────────────────────────────────────────

    @staticmethod
    def get_equipment_report(db: Session, filters: dict) -> dict:
        """
        Reporte de equipos con multi-filtros.

        filters: {
            department_ids: list[int],
            category_ids:   list[int],
            statuses:       list[str],
            brand:          str,
            search:         str,
            include_inactive: bool,
            page:           int,
            per_page:       int,
        }
        """
        query = db.query(InventoryItem)

        if not filters.get("include_inactive"):
            query = query.filter(InventoryItem.is_active == True)

        dept_ids = filters.get("department_ids") or []
        if dept_ids:
            query = query.filter(InventoryItem.department_id.in_(dept_ids))

        cat_ids = filters.get("category_ids") or []
        if cat_ids:
            query = query.filter(InventoryItem.category_id.in_(cat_ids))

        statuses = filters.get("statuses") or []
        if statuses:
            query = query.filter(InventoryItem.status.in_([s.upper() for s in statuses]))

        brand = (filters.get("brand") or "").strip()
        if brand:
            query = query.filter(InventoryItem.brand.ilike(f"%{brand}%"))

        search = (filters.get("search") or "").strip()
        if search:
            query = query.filter(
                or_(
                    InventoryItem.inventory_number.ilike(f"%{search}%"),
                    InventoryItem.brand.ilike(f"%{search}%"),
                    InventoryItem.model.ilike(f"%{search}%"),
                    InventoryItem.supplier_serial.ilike(f"%{search}%"),
                    InventoryItem.itcj_serial.ilike(f"%{search}%"),
                    InventoryItem.id_tecnm.ilike(f"%{search}%"),
                    InventoryItem.location_detail.ilike(f"%{search}%"),
                )
            )

        query = query.order_by(InventoryItem.inventory_number)

        page = max(1, filters.get("page", 1))
        per_page = min(500, max(1, filters.get("per_page", 50)))
        total = query.count()
        total_pages = (total + per_page - 1) // per_page

        items = query.offset((page - 1) * per_page).limit(per_page).all()

        return {
            "items": [item.to_dict(include_relations=True) for item in items],
            "total": total,
            "page": page,
            "per_page": per_page,
            "total_pages": total_pages,
        }

    # ── Reporte de movimientos ────────────────────────────────────────────────

    @staticmethod
    def get_movements_report(db: Session, filters: dict) -> dict:
        """
        Reporte de movimientos/historial con multi-filtros.

        filters: {
            date_from:       str (ISO),
            date_to:         str (ISO),
            event_types:     list[str],
            department_ids:  list[int],
            performed_by_id: int,
            search:          str,
            page:            int,
            per_page:        int,
        }
        """
        query = db.query(InventoryHistory).join(
            InventoryItem, InventoryHistory.item_id == InventoryItem.id
        )

        date_from = filters.get("date_from")
        if date_from:
            try:
                query = query.filter(InventoryHistory.timestamp >= datetime.fromisoformat(date_from))
            except ValueError:
                pass

        date_to = filters.get("date_to")
        if date_to:
            try:
                dt_to = datetime.fromisoformat(date_to)
                if dt_to.hour == 0 and dt_to.minute == 0:
                    dt_to = dt_to + timedelta(days=1)
                query = query.filter(InventoryHistory.timestamp < dt_to)
            except ValueError:
                pass

        event_types = filters.get("event_types") or []
        if event_types:
            query = query.filter(
                InventoryHistory.event_type.in_([e.upper() for e in event_types])
            )

        dept_ids = filters.get("department_ids") or []
        if dept_ids:
            query = query.filter(InventoryItem.department_id.in_(dept_ids))

        performed_by_id = filters.get("performed_by_id")
        if performed_by_id:
            query = query.filter(InventoryHistory.performed_by_id == performed_by_id)

        search = (filters.get("search") or "").strip()
        if search:
            query = query.filter(
                or_(
                    InventoryHistory.notes.ilike(f"%{search}%"),
                    InventoryItem.inventory_number.ilike(f"%{search}%"),
                    InventoryItem.supplier_serial.ilike(f"%{search}%"),
                )
            )

        query = query.order_by(desc(InventoryHistory.timestamp))

        page = max(1, filters.get("page", 1))
        per_page = min(500, max(1, filters.get("per_page", 50)))
        total = query.count()
        total_pages = (total + per_page - 1) // per_page

        events = query.offset((page - 1) * per_page).limit(per_page).all()

        return {
            "events": [e.to_dict(include_relations=True) for e in events],
            "total": total,
            "page": page,
            "per_page": per_page,
            "total_pages": total_pages,
        }

    # ── Exportación CSV ───────────────────────────────────────────────────────

    @staticmethod
    def export_equipment_csv(db: Session, filters: dict) -> str:
        """Genera CSV de reporte de equipos (sin paginación)."""
        result = InventoryReportsService.get_equipment_report(
            db, {**filters, "page": 1, "per_page": 10000}
        )
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "No. Inventario", "Categoría", "Marca", "Modelo",
            "No. Serie", "Departamento", "Asignado a", "Ubicación",
            "Estado", "Fecha Adquisición", "Vencimiento Garantía",
            "Último Mantenimiento", "Próx. Mantenimiento", "Notas",
        ])
        for item in result["items"]:
            dept = item.get("department") or {}
            user = item.get("assigned_to_user") or {}
            cat = item.get("category") or {}
            writer.writerow([
                item.get("inventory_number", ""),
                cat.get("name", ""),
                item.get("brand", ""),
                item.get("model", ""),
                item.get("supplier_serial", ""),
                dept.get("name", ""),
                user.get("full_name", "Sin asignar"),
                item.get("location_detail", ""),
                item.get("status", ""),
                item.get("acquisition_date", ""),
                item.get("warranty_expiration", ""),
                item.get("last_maintenance_date", ""),
                item.get("next_maintenance_date", ""),
                item.get("notes", ""),
            ])
        return output.getvalue()

    @staticmethod
    def export_movements_csv(db: Session, filters: dict) -> str:
        """Genera CSV de reporte de movimientos (sin paginación)."""
        result = InventoryReportsService.get_movements_report(
            db, {**filters, "page": 1, "per_page": 10000}
        )
        event_labels = InventoryReportsService.get_event_type_labels()
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "Fecha", "Tipo de Evento", "No. Inventario",
            "Realizado por", "Notas", "Valor Anterior", "Valor Nuevo",
        ])
        for event in result["events"]:
            performed_by = event.get("performed_by") or {}
            writer.writerow([
                event.get("timestamp", ""),
                event_labels.get(event.get("event_type", ""), event.get("event_type", "")),
                event.get("item_id", ""),
                performed_by.get("full_name", ""),
                event.get("notes", ""),
                str(event.get("old_value", "")),
                str(event.get("new_value", "")),
            ])
        return output.getvalue()

    @staticmethod
    def export_warranty_csv(db: Session) -> str:
        """Genera CSV de reporte de garantías."""
        from itcj2.apps.helpdesk.services.inventory_stats_service import InventoryStatsService
        report = InventoryStatsService.get_warranty_report(db)
        today = date.today()
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "Estado", "No. Inventario", "Marca", "Modelo",
            "Departamento", "Vencimiento Garantía", "Días Restantes",
        ])
        for label, key in [("Vence en 30 días", "expiring_30_days"), ("Vence en 60 días", "expiring_60_days")]:
            for item in report.get(key, {}).get("items", []):
                days_left = ""
                if item.get("warranty_expiration"):
                    try:
                        days_left = (date.fromisoformat(item["warranty_expiration"]) - today).days
                    except (ValueError, TypeError):
                        pass
                writer.writerow([
                    label, item.get("inventory_number", ""),
                    item.get("brand", ""), item.get("model", ""),
                    "", item.get("warranty_expiration", ""), days_left,
                ])
        return output.getvalue()

    @staticmethod
    def export_maintenance_csv(db: Session) -> str:
        """Genera CSV de reporte de mantenimiento."""
        from itcj2.apps.helpdesk.services.inventory_stats_service import InventoryStatsService
        report = InventoryStatsService.get_maintenance_report(db)
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "Estado", "No. Inventario", "Marca", "Modelo",
            "Departamento", "Próx. Mantenimiento", "Último Mantenimiento",
        ])
        for label, key in [("Vencido", "overdue"), ("Próximos 30 días", "upcoming_30_days")]:
            for item in report.get(key, {}).get("items", []):
                writer.writerow([
                    label, item.get("inventory_number", ""),
                    item.get("brand", ""), item.get("model", ""),
                    "", item.get("next_maintenance_date", ""),
                    item.get("last_maintenance_date", ""),
                ])
        return output.getvalue()

    @staticmethod
    def export_lifecycle_csv(db: Session) -> str:
        """Genera CSV de reporte de ciclo de vida."""
        from itcj2.apps.helpdesk.services.inventory_stats_service import InventoryStatsService
        report = InventoryStatsService.get_lifecycle_report(db)
        today = date.today()
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "Antigüedad", "No. Inventario", "Marca", "Modelo",
            "Departamento", "Fecha Adquisición", "Años",
        ])
        for item in report.get("older_than_5_years", {}).get("items", []):
            years = ""
            if item.get("acquisition_date"):
                try:
                    years = round((today - date.fromisoformat(item["acquisition_date"])).days / 365.25, 1)
                except (ValueError, TypeError):
                    pass
            writer.writerow([
                "Más de 5 años", item.get("inventory_number", ""),
                item.get("brand", ""), item.get("model", ""),
                "", item.get("acquisition_date", ""), years,
            ])
        return output.getvalue()

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def get_event_type_labels() -> dict:
        return {
            "REGISTERED": "Registrado",
            "ASSIGNED_TO_DEPT": "Asignado a Depto.",
            "ASSIGNED_TO_USER": "Asignado a Usuario",
            "UNASSIGNED": "Desasignado",
            "REASSIGNED": "Reasignado",
            "LOCATION_CHANGED": "Cambio de Ubicación",
            "STATUS_CHANGED": "Cambio de Estado",
            "MAINTENANCE_SCHEDULED": "Mantenimiento Programado",
            "MAINTENANCE_COMPLETED": "Mantenimiento Completado",
            "SPECS_UPDATED": "Specs Actualizadas",
            "TRANSFERRED": "Transferido",
            "DEACTIVATED": "Dado de Baja",
            "REACTIVATED": "Reactivado",
            "VERIFIED": "Verificación Física",
        }

    @staticmethod
    def get_status_labels() -> dict:
        return {
            "PENDING_ASSIGNMENT": "Pendiente",
            "ACTIVE": "Activo",
            "MAINTENANCE": "En Mantenimiento",
            "DAMAGED": "Dañado",
            "RETIRED": "Retirado",
            "LOST": "Extraviado",
        }
