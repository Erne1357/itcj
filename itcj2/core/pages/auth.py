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

# Tope defensivo: un `next` más largo que esto no es una ruta de la plataforma,
# es alguien probando el parser.
_MAX_NEXT_LENGTH = 512


def safe_next(raw: str | None) -> str | None:
    """Valida `?next=` como ruta RELATIVA del mismo origen. `None` si no lo es.

    Esta página es el login de las SIETE apps del instituto. Honrar un `next`
    sin validar la convierte en un open redirect: la víctima ve el dominio
    institucional y el login de verdad, y tras autenticarse aterriza donde diga
    el atacante. Las reglas, en orden:

    - Debe empezar con exactamente UNA `/` — una ruta, no una URL.
    - `//host` es *protocol-relative*: el navegador sale del sitio. Se rechaza.
    - `/\\host` lo tratan como `//host` varios navegadores. Se rechaza.
    - Cualquier `:` ANTES de la primera `/` es un esquema (`https:`,
      `javascript:`). Se rechaza.
    - Caracteres de control (CR/LF sobre todo) parten el header `Location` en
      dos e inyectan cabeceras. Se rechazan.

    El query string y el fragmento se conservan: el destino de la encuesta los
    puede necesitar y no amplían la superficie (siguen dentro del origen).
    """
    if raw is None:
        return None
    value = raw.strip()
    if not value or len(value) > _MAX_NEXT_LENGTH:
        return None
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        return None
    if ":" in value.split("/", 1)[0]:
        return None
    if not value.startswith("/"):
        return None
    if value.startswith("//") or value.startswith("/\\"):
        return None
    return value


@router.get("/login", name="core.pages.auth.login", response_model=None)
async def login_page(
    request: Request,
    next: str | None = None,  # noqa: A002 — el nombre del query param es parte del contrato
    user: dict | None = Depends(get_current_user_optional),
    db: Session = Depends(get_db),
) -> RedirectResponse | HTMLResponse:
    """Página de inicio de sesión.

    Si el usuario ya tiene sesión activa lo redirige a `next` cuando es una ruta
    válida del sitio y, si no, a su home según su rol (comportamiento previo).
    """
    destino = safe_next(next)

    if user:
        from itcj2.core.services.authz_service import user_roles_in_app
        from itcj2.core.utils.role_home import role_home

        destination = destino or role_home(
            user_roles_in_app(db, int(user["sub"]), "itcj")
        )
        return RedirectResponse(destination, status_code=302)

    return render(request, "core/auth/login.html", {"next_url": destino or ""})
