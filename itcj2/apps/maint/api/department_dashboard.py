"""
Dashboard Departamental — Mantenimiento.

Endpoints:
  GET /api/maint/v2/dashboard/me/departments  → deptos del usuario logueado
  GET /api/maint/v2/dashboard/summary         → KPIs básicos (dispatcher/secretary)
  GET /api/maint/v2/dashboard/full            → KPIs completos (admin/department_head)

Permisos YA creados en BD:
  maint.dashboard.api.summary
  maint.dashboard.api.full

Nota: `is_admin_global` se determina por rol `admin` EN LA APP MAINT
(no por JWT global). Un user con `admin` global JWT pero solo `department_head`
en maint se trata como dh para alcance — ve solo sus deptos.
"""
import logging

from fastapi import APIRouter, HTTPException, Query

from itcj2.dependencies import DbSession, require_perms

router = APIRouter(tags=["maint-dashboard-department"])
logger = logging.getLogger(__name__)


def _maint_roles(db, user_id: int) -> set:
    """Roles efectivos del user en la app maint (UserAppRole + PositionAppRole)."""
    from itcj2.core.services.authz_service import user_roles_in_app
    try:
        return set(user_roles_in_app(db, user_id, "maint"))
    except Exception:
        return set()


def _is_maint_admin(db, user_id: int) -> bool:
    """True solo si el user tiene rol `admin` en la app maint
    (vía UserAppRole o PositionAppRole). Reservado para Vista completa
    con sección `by_technician`."""
    return "admin" in _maint_roles(db, user_id)


def _has_full_scope(db, user_id: int) -> bool:
    """True si el user puede ver tickets de cualquier depto (sin filtrar):
    rol `admin` o `dispatcher` en maint. Cubre:
      - admin: cualquier user con rol admin (incluye head_equipment_maint via 08).
      - dispatcher: rol operativo central, incluye secretary_equipment_maint via 08.
    Para `department_head` / `secretary` puros → False (filtra por sus deptos)."""
    roles = _maint_roles(db, user_id)
    return bool(roles & {"admin", "dispatcher"})


@router.get("/me/departments")
def my_departments(
    user: dict = require_perms("maint", [
        "maint.dashboard.api.full",
        "maint.dashboard.api.summary",
    ]),
    db: DbSession = None,
):
    """
    Lista los departamentos del usuario logueado según sus puestos activos.
    Si el usuario es admin global, retorna lista vacía (= acceso a todos).
    """
    from itcj2.apps.maint.services.department_dashboard_service import get_user_departments

    user_id = int(user["sub"])
    has_full_scope = _has_full_scope(db, user_id)

    try:
        departments = get_user_departments(db, user_id)
        # Si tiene scope total (admin o dispatcher) lo marcamos como "admin global"
        # para la UI (oculta selector / muestra "Todos los departamentos").
        # Si además tiene puestos, los devolvemos para poder filtrar.
        return {
            "success": True,
            "data": departments,
            "is_admin_global": has_full_scope,
        }
    except Exception as e:
        logger.error("Error obteniendo departamentos para user %s: %s", user_id, e)
        raise HTTPException(status_code=500, detail="Error al obtener departamentos")


@router.get("/summary")
def dashboard_summary(
    dept: int | None = Query(None, description="ID de departamento; vacío = todos los del user"),
    user: dict = require_perms("maint", [
        "maint.dashboard.api.summary",
        "maint.dashboard.api.full",
    ]),
    db: DbSession = None,
):
    """
    Dashboard de resumen para dispatcher y secretary.
    Usuarios con permiso full también pueden acceder aquí.

    KPIs: open_total, unassigned, in_progress, overdue, resolved_this_week.
    Listas: unassigned_tickets (máx 10), recent_open (máx 5).
    """
    from itcj2.apps.maint.services.department_dashboard_service import (
        get_user_departments,
        get_summary,
    )

    user_id = int(user["sub"])
    has_full_scope = _has_full_scope(db, user_id)
    departments = get_user_departments(db, user_id)
    # Scope total (admin o dispatcher en maint) → sin filtro de dept salvo override.
    # Otros roles (dh, sec puros) → filtran por sus deptos.

    try:
        data = get_summary(
            db=db,
            user_id=user_id,
            is_admin_global=has_full_scope,
            dept_filter=dept,
        )
        return {
            "success": True,
            "data": data,
            "departments": departments,
            "is_admin_global": has_full_scope,
        }
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        logger.error(
            "Error calculando dashboard summary para user %s dept %s: %s",
            user_id, dept, e,
        )
        raise HTTPException(status_code=500, detail="Error al calcular el dashboard")


@router.get("/full")
def dashboard_full(
    dept: int | None = Query(None, description="ID de departamento; vacío = todos los del user"),
    user: dict = require_perms("maint", ["maint.dashboard.api.full"]),
    db: DbSession = None,
):
    """
    Dashboard completo para admin y department_head.

    KPIs: open_total, unassigned, in_progress, overdue, resolved_this_week,
          avg_resolution_hours, rated_count, rated_pct.
    Secciones: by_status, by_category, by_technician, sla_breakdown,
               recent_open (máx 10), overdue_tickets (máx 10).
    """
    from itcj2.apps.maint.services.department_dashboard_service import (
        get_user_departments,
        get_full,
    )

    user_id = int(user["sub"])
    is_maint_admin = _is_maint_admin(db, user_id)
    has_full_scope = _has_full_scope(db, user_id)
    departments = get_user_departments(db, user_id)

    try:
        data = get_full(
            db=db,
            user_id=user_id,
            is_admin_global=has_full_scope,
            dept_filter=dept,
        )
        # Solo admin en maint ve "Por técnico" (info gerencial reservada).
        # dh con scope dept o admin con puesto → NO ve by_technician aunque sea full.
        if not is_maint_admin and "by_technician" in data:
            data = {k: v for k, v in data.items() if k != "by_technician"}
        return {
            "success": True,
            "data": data,
            "departments": departments,
            "is_admin_global": has_full_scope,
            "is_maint_admin": is_maint_admin,
        }
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        logger.error(
            "Error calculando dashboard full para user %s dept %s: %s",
            user_id, dept, e,
        )
        raise HTTPException(status_code=500, detail="Error al calcular el dashboard")
