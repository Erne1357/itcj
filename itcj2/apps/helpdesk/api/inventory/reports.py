"""
API de reportes de inventario con multi-filtros y exportación CSV.
Equivalente FastAPI de itcj/apps/helpdesk/routes/api/inventory/inventory_reports.py

Rutas (prefix: /api/help-desk/v2/inventory/reports):
  POST /equipment          → Reporte de equipos con filtros
  POST /movements          → Reporte de movimientos/historial
  POST /export/csv         → Exportar a CSV (equipment|movements|warranty|maintenance|lifecycle)
  GET  /labels             → Etiquetas legibles de event_types y statuses
"""
import logging
from datetime import datetime

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from itcj2.dependencies import DbSession, require_perms

router = APIRouter(tags=["helpdesk-inventory-reports"])
logger = logging.getLogger(__name__)

# Anclas de subárbol relevantes para reportes/exportación (procedencia): el
# jefe con `.read.stats.subtree` y/o `.export.subtree` ve su subárbol; el resto
# de acceso completo (admin/técnicos/CC/.read.all) sigue viendo todo.
_REPORTS_SUBTREE_PERMS = {
    "helpdesk.inventory.api.read.stats.subtree",
    "helpdesk.inventory.api.export.subtree",
}


def _scope_department_ids(db, user, filters: dict) -> dict:
    """Intersecta ``filters['department_ids']`` con el scope visible del usuario.

    - ``visible is None`` (acceso completo): NO se toca — permite pedir toda la
      institución o cualquier subconjunto, igual que antes para admin/CC/técnicos.
    - ``visible`` es un set: si no pidieron nada, se usa el scope COMPLETO (nunca
      "toda la institución" por default); si pidieron algo, se intersecta (fuera
      de scope ⇒ vacío, nunca fuga de datos ajenos). Un resultado vacío se
      representa como ``[-1]`` (sentinel fail-closed, ningún id real lo iguala).
    """
    from itcj2.apps.helpdesk.utils.inventory_access import visible_department_ids

    visible = visible_department_ids(db, user, extra_subtree_perms=_REPORTS_SUBTREE_PERMS)
    if visible is None:
        return dict(filters)

    requested = set(filters.get("department_ids") or [])
    scoped = (requested & visible) if requested else set(visible)
    return {**filters, "department_ids": list(scoped) if scoped else [-1]}


@router.post("/equipment")
def equipment_report(
    body: dict,
    user: dict = require_perms("helpdesk", ["helpdesk.inventory.api.read.stats"]),
    db: DbSession = None,
):
    """
    Reporte de equipos con multi-filtros.

    Body: { department_ids, category_ids, statuses, brand, search, page, per_page }
    """
    try:
        from itcj2.apps.helpdesk.services.inventory_reports_service import InventoryReportsService
        scoped_body = _scope_department_ids(db, user, body)
        result = InventoryReportsService.get_equipment_report(db, scoped_body)
        return {"success": True, **result}
    except Exception as e:
        logger.error(f"Error en reporte de equipos: {e}")
        raise HTTPException(500, detail={"success": False, "error": str(e)})


@router.post("/movements")
def movements_report(
    body: dict,
    user: dict = require_perms("helpdesk", ["helpdesk.inventory.api.read.stats"]),
    db: DbSession = None,
):
    """
    Reporte de movimientos/historial con multi-filtros.

    Body: { date_from, date_to, event_types, department_ids, performed_by_id, search, page, per_page }
    """
    try:
        from itcj2.apps.helpdesk.services.inventory_reports_service import InventoryReportsService
        scoped_body = _scope_department_ids(db, user, body)
        result = InventoryReportsService.get_movements_report(db, scoped_body)
        return {"success": True, **result}
    except Exception as e:
        logger.error(f"Error en reporte de movimientos: {e}")
        raise HTTPException(500, detail={"success": False, "error": str(e)})


@router.post("/export/csv")
def export_csv(
    body: dict,
    user: dict = require_perms("helpdesk", ["helpdesk.inventory.api.read.stats"]),
    db: DbSession = None,
):
    """
    Exportar reporte a CSV.

    Body: { report_type: "equipment"|"movements"|"warranty"|"maintenance"|"lifecycle", filters: {...} }
    """
    try:
        from itcj2.apps.helpdesk.services.inventory_reports_service import InventoryReportsService

        report_type = body.get("report_type", "equipment")
        filters = _scope_department_ids(db, user, body.get("filters", {}))
        dept_ids = filters.get("department_ids")

        csv_content = ""
        filename = f"reporte_inventario_{report_type}"

        if report_type == "equipment":
            csv_content = InventoryReportsService.export_equipment_csv(db, filters)
            filename = "reporte_equipos"
        elif report_type == "movements":
            csv_content = InventoryReportsService.export_movements_csv(db, filters)
            filename = "reporte_movimientos"
        elif report_type == "warranty":
            csv_content = InventoryReportsService.export_warranty_csv(db, dept_ids)
            filename = "reporte_garantias"
        elif report_type == "maintenance":
            csv_content = InventoryReportsService.export_maintenance_csv(db, dept_ids)
            filename = "reporte_mantenimiento"
        elif report_type == "lifecycle":
            csv_content = InventoryReportsService.export_lifecycle_csv(db, dept_ids)
            filename = "reporte_ciclo_vida"
        else:
            raise HTTPException(400, detail={"success": False, "error": "Tipo de reporte inválido"})

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{filename}_{timestamp}.csv"

        # BOM para que Excel abra bien los acentos
        bom = "\ufeff"
        return Response(
            content=(bom + csv_content).encode("utf-8"),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error exportando CSV: {e}")
        raise HTTPException(500, detail={"success": False, "error": str(e)})


@router.get("/labels")
def get_labels(
    user: dict = require_perms("helpdesk", ["helpdesk.inventory.api.read.stats"]),
    db: DbSession = None,
):
    """Obtiene etiquetas legibles para event_types y statuses."""
    from itcj2.apps.helpdesk.services.inventory_reports_service import InventoryReportsService
    return {
        "success": True,
        "event_types": InventoryReportsService.get_event_type_labels(),
        "statuses": InventoryReportsService.get_status_labels(),
    }
