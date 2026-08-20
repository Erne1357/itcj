"""
Email API v2 — estado y desconexión de cuentas Microsoft Graph por app.

Movido desde el pages router (F1a core-config-revamp, contrato C3): los AJAX
de /itcj/config/email/auth/{status,logout} viven aquí con envelope estándar.
Los redirects OAuth (login/callback) SIGUEN siendo páginas.
"""
import logging

from fastapi import APIRouter, HTTPException, Query

from itcj2.dependencies import DbSession, require_perms

router = APIRouter(tags=["core-email"])
logger = logging.getLogger(__name__)

# F1a-D1: espejo de tasks.py — permiso existente core.config.admin
# (admin global del JWT bypasea, consistente con el resto de APIs core).
_ADMIN_PERM = require_perms("itcj", ["core.config.admin"])


def _resolve_app_key(db, app: str) -> str:
    """Resuelve ?app= contra core_apps. Allowlist real, no un string libre.

    `app` termina como componente de ruta en instance/apps/{app}/email/. En julio
    2026 un escaneo automatizado abuso esta misma cadena por el callback OAuth (que
    entonces no tenia auth) y creo ~80 directorios con nombres de payload. Aunque
    estos endpoints si exigen admin, se valida igual: nada llega al filesystem sin
    existir antes en la BD.
    """
    from itcj2.core.models.app import App

    if not app:
        raise HTTPException(400, detail="Falta el parámetro 'app'")
    row = db.query(App.key).filter(App.key == app).first()
    if not row:
        logger.warning("email API: app_key inexistente %r", app)
        raise HTTPException(404, detail="Aplicación no encontrada")
    return row[0]


@router.get("/status")
def email_status(
    app: str = Query("", description="App key a consultar"),
    user: dict = _ADMIN_PERM,
    db: DbSession = None,
):
    """Estado de conexión de correo de una app (contrato C3)."""
    from itcj2.core.utils import msgraph_mail

    app = _resolve_app_key(db, app)

    token = msgraph_mail.acquire_token_silent(app)
    acct = msgraph_mail.read_account_info(app)
    return {"success": True, "data": {"connected": bool(token), "account": acct}}


@router.post("/logout")
def email_logout(
    app: str = Query("", description="App key a desconectar"),
    user: dict = _ADMIN_PERM,
    db: DbSession = None,
):
    """Desconecta la cuenta de correo de una app (contrato C3)."""
    from itcj2.core.utils import msgraph_mail

    app = _resolve_app_key(db, app)

    msgraph_mail.clear_account_and_cache(app)
    logger.info("Cuenta de correo de '%s' desconectada por usuario %s", app, user["sub"])
    return {"success": True, "message": f"Correo desconectado de {app}"}
