"""Páginas de tickets de Mantenimiento."""
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from itcj2.dependencies import require_page_app
from itcj2.apps.maint.pages.nav import render_maint

router = APIRouter(tags=["maint-pages"])
logger = logging.getLogger(__name__)


@router.get("/tickets", name="maint_pages.tickets.list")
async def ticket_list(
    request: Request,
    user: dict = Depends(require_page_app("maint", perms=["maint.tickets.page.list"])),
) -> HTMLResponse:
    return render_maint(request, "maint/tickets/list.html", {"active_page": "tickets"})


def _maint_perms(user: dict) -> set:
    """Permisos efectivos del usuario en maint, del caché de authz (el MISMO
    que usa la guarda de la página), con una sesión que siempre se cierra.
    Perf 2026-10-07: antes ~10 consultas sin caché por página, y el detalle
    abría su sesión con `next(get_db())`, que se quedaba con la conexión.
    Un fallo da el conjunto vacío: los flags que dependen de él quedan en
    falso (lo seguro)."""
    from itcj2.database import SessionLocal
    from itcj2.core.services.authz_cache import cached_perms

    db = SessionLocal()
    try:
        return set(cached_perms(db, int(user["sub"]), "maint"))
    except Exception:
        logger.warning("No se pudieron leer los permisos maint del usuario %s", user.get("sub"))
        return set()
    finally:
        db.close()


# Rutas `def` (no `async def`): leen permisos con BD síncrona y FastAPI las
# corre en el threadpool, sin bloquear el event loop.
@router.get("/tickets/create", name="maint_pages.tickets.create")
def ticket_create(
    request: Request,
    user: dict = Depends(require_page_app("maint", perms=["maint.tickets.page.create"])),
) -> HTMLResponse:
    from itcj2.apps.maint.utils import catalog_cache

    # Prioridades activas (con is_default) para renderizar las tarjetas desde BD
    priorities = [p for p in catalog_cache.get_priorities() if p.get("is_active")]

    # Flag para mostrar el selector "Solicitar para" en el formulario.
    # Behalf requiere el PERMISO real de maint (jefe/secretaría de mantenimiento):
    # ser admin GLOBAL del sistema NO basta — un jefe de otro departamento con
    # rol admin global no debe crear solicitudes en nombre de terceros en maint.
    can_create_behalf = "maint.tickets.api.create.behalf" in _maint_perms(user)

    return render_maint(request, "maint/tickets/create.html", {
        "active_page": "tickets_create",
        "priorities": priorities,
        "can_create_behalf": can_create_behalf,
    })


@router.get("/tickets/{ticket_id}", name="maint_pages.tickets.detail")
def ticket_detail(
    ticket_id: int,
    request: Request,
    user: dict = Depends(require_page_app("maint", perms=["maint.tickets.page.detail"])),
) -> HTMLResponse:
    # Coordinadores y admin pueden asignar/desasignar técnicos desde el detalle.
    # Dispatcher y secretaría ya NO asignan (D2 del plan).
    if user.get("role") == "admin":
        can_assign = True
    else:
        can_assign = "maint.assignments.api.assign" in _maint_perms(user)

    return render_maint(request, "maint/tickets/detail.html", {
        "ticket_id": ticket_id,
        "active_page": "tickets",
        "can_assign": can_assign,
    })
