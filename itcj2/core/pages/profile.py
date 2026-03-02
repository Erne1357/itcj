"""
Página de perfil del usuario (equivalente a itcj/core/routes/pages/profile.py).

Rutas:
  GET /itcj/profile  → Perfil del usuario autenticado
"""
from fastapi import APIRouter, Depends, HTTPException, Request

from itcj2.dependencies import require_page_login
from itcj2.templates import render

router = APIRouter(tags=["core-pages"])


@router.get("/profile", name="core.pages.profile")
async def profile(
    request: Request,
    user: dict = Depends(require_page_login),
):
    """Página de perfil del usuario autenticado."""
    from itcj2.core.services.profile_service import get_user_profile_data

    user_id = int(user["sub"])
    profile_data = get_user_profile_data(user_id)

    if not profile_data:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    return render(request, "core/profile/profile.html", {"profile": profile_data})
