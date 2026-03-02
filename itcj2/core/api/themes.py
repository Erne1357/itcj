"""
Themes API v2 — 9 endpoints (temas visuales del sistema).
Fuente: itcj/core/routes/api/themes.py
"""
import logging
from typing import Optional, Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from itcj2.dependencies import DbSession, CurrentUser, require_roles

router = APIRouter(tags=["core-themes"])
logger = logging.getLogger(__name__)


# ── Schemas ───────────────────────────────────────────────────────────────────

class ThemeCreateBody(BaseModel):
    name: str
    model_config = {"extra": "allow"}


class ThemeUpdateBody(BaseModel):
    model_config = {"extra": "allow"}


class ThemeToggleBody(BaseModel):
    active: bool = False


class ThemeEnableBody(BaseModel):
    enabled: bool = True


# ── Endpoint público ──────────────────────────────────────────────────────────

@router.get("/active")
def get_active_theme():
    """Tema actualmente activo (público, sin autenticación)."""
    from itcj2.core.services import themes_service as svc

    theme = svc.get_active_theme()
    if not theme:
        return {"status": "ok", "data": None}
    return {"status": "ok", "data": theme.to_dict(include_full=True)}


# ── Endpoints protegidos (solo admin) ─────────────────────────────────────────

@router.get("/stats")
def get_themes_stats(
    user: dict = require_roles("itcj", ["admin"]),
    db: DbSession = None,
):
    """Estadísticas de temas (total y activos)."""
    from itcj2.core.services import themes_service as svc

    return {
        "status": "ok",
        "data": {"total": svc.get_themes_count(), "active": svc.get_active_themes_count()},
    }


@router.get("")
def list_themes(
    user: dict = require_roles("itcj", ["admin"]),
    db: DbSession = None,
):
    """Lista todas las temáticas."""
    from itcj2.core.services import themes_service as svc

    themes = svc.list_themes()
    return {"status": "ok", "data": [t.to_dict() for t in themes]}


@router.get("/{theme_id}")
def get_theme(
    theme_id: int,
    user: dict = require_roles("itcj", ["admin"]),
    db: DbSession = None,
):
    """Detalle de una temática."""
    from itcj2.core.services import themes_service as svc

    theme = svc.get_theme(theme_id)
    if not theme:
        raise HTTPException(404, detail={"status": "error", "error": "theme_not_found"})
    return {"status": "ok", "data": theme.to_dict(include_full=True)}


@router.post("", status_code=201)
async def create_theme(
    body: ThemeCreateBody,
    user: dict = require_roles("itcj", ["admin"]),
    db: DbSession = None,
):
    """Crea una nueva temática."""
    from itcj2.core.services import themes_service as svc

    payload = body.model_dump()
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(400, detail={"status": "error", "error": "name_required"})

    try:
        user_id = int(user["sub"])
        theme = svc.create_theme(payload, created_by_id=user_id)
        logger.info(f"Tema '{name}' creado por usuario {user_id}")
        return {"status": "ok", "data": theme.to_dict(include_full=True)}
    except ValueError as e:
        raise HTTPException(409, detail={"status": "error", "error": str(e)})


@router.patch("/{theme_id}")
async def update_theme(
    theme_id: int,
    body: ThemeUpdateBody,
    user: dict = require_roles("itcj", ["admin"]),
    db: DbSession = None,
):
    """Actualiza una temática existente."""
    from itcj2.core.services import themes_service as svc

    payload = body.model_dump()
    try:
        theme = svc.update_theme(theme_id, **payload)
        logger.info(f"Tema {theme_id} actualizado por usuario {int(user['sub'])}")
        return {"status": "ok", "data": theme.to_dict(include_full=True)}
    except ValueError as e:
        error_msg = str(e)
        status = 404 if ("no encontrada" in error_msg.lower() or "not found" in error_msg.lower()) else 409
        raise HTTPException(status, detail={"status": "error", "error": error_msg})


@router.post("/{theme_id}/toggle")
def toggle_theme(
    theme_id: int,
    body: ThemeToggleBody,
    user: dict = require_roles("itcj", ["admin"]),
    db: DbSession = None,
):
    """Activa o desactiva manualmente una temática."""
    from itcj2.core.services import themes_service as svc

    try:
        theme = svc.toggle_theme_manual(theme_id, body.active)
        return {"status": "ok", "data": theme.to_dict()}
    except ValueError as e:
        raise HTTPException(404, detail={"status": "error", "error": str(e)})


@router.post("/{theme_id}/enable")
def toggle_theme_enabled(
    theme_id: int,
    body: ThemeEnableBody,
    user: dict = require_roles("itcj", ["admin"]),
    db: DbSession = None,
):
    """Habilita o deshabilita una temática."""
    from itcj2.core.services import themes_service as svc

    try:
        theme = svc.toggle_theme_enabled(theme_id, body.enabled)
        return {"status": "ok", "data": theme.to_dict()}
    except ValueError as e:
        raise HTTPException(404, detail={"status": "error", "error": str(e)})


@router.delete("/{theme_id}", status_code=204)
def delete_theme(
    theme_id: int,
    user: dict = require_roles("itcj", ["admin"]),
    db: DbSession = None,
):
    """Elimina una temática."""
    from itcj2.core.services import themes_service as svc

    try:
        svc.delete_theme(theme_id)
        logger.info(f"Tema {theme_id} eliminado por usuario {int(user['sub'])}")
    except ValueError as e:
        raise HTTPException(404, detail={"status": "error", "error": str(e)})
