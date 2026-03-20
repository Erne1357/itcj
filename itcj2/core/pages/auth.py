"""
Páginas de autenticación del Core (equivalente a itcj/core/routes/pages/auth.py).

Rutas:
  GET /itcj/login  → Página de inicio de sesión
"""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from sqlalchemy.orm import Session

from itcj2.dependencies import get_current_user_optional, get_db
from itcj2.templates import render

router = APIRouter(prefix="", tags=["core-pages"])


@router.get("/login", name="core.pages.auth.login", response_model=None)
async def login_page(
    request: Request,
    user: dict | None = Depends(get_current_user_optional),
    db: Session = Depends(get_db),
) -> RedirectResponse | HTMLResponse:
    """Página de inicio de sesión.

    Si el usuario ya tiene sesión activa lo redirige a su home según su rol,
    igual que el comportamiento de Flask.
    """
    if user:
        from itcj2.core.services.authz_service import user_roles_in_app
        from itcj2.core.utils.role_home import role_home

        destination = role_home(user_roles_in_app(db, int(user["sub"]), "itcj"))
        return RedirectResponse(destination, status_code=302)

    return render(request, "core/auth/login.html")
