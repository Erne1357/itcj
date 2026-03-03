from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse


def register_routers(app: FastAPI):
    """Registro centralizado de todos los routers (equivalente a register_blueprints)."""

    # Core API v2
    from itcj2.core.router import core_router
    app.include_router(core_router)

    # Helpdesk API v2
    from itcj2.apps.helpdesk.router import helpdesk_router
    app.include_router(helpdesk_router)

    # AgendaTec API v2
    from itcj2.apps.agendatec.router import agendatec_router
    app.include_router(agendatec_router)

    # VisteTec API v2
    from itcj2.apps.vistetec.router import vistetec_router
    app.include_router(vistetec_router)

    # ── Fase 4: Page routers ─────────────────────────────────────────────────
    # Core pages (prefix /itcj): login, dashboard, perfil, config, móvil
    from itcj2.core.pages.router import core_pages_router
    app.include_router(core_pages_router)

    # Help-Desk pages (prefix /help-desk): landing, user, secretary, technician,
    # department, inventory, admin
    from itcj2.apps.helpdesk.pages.router import helpdesk_pages_router
    app.include_router(helpdesk_pages_router)

    # AgendaTec pages (prefix /agendatec): landing, student, coord, admin, social, surveys
    from itcj2.apps.agendatec.pages.router import agendatec_pages_router
    app.include_router(agendatec_pages_router)

    # VisteTec pages (prefix /vistetec): landing, student, volunteer, admin
    from itcj2.apps.vistetec.pages.router import vistetec_pages_router
    app.include_router(vistetec_pages_router)

    # Redirect raíz: autenticado → dashboard o móvil, no autenticado → login
    @app.get("/", include_in_schema=False)
    async def root_redirect(request: Request):
        user = getattr(request.state, "current_user", None)
        if user:
            # Alumnos tienen cn (número de control de 8 dígitos)
            if user.get("cn"):
                return RedirectResponse("/itcj/m/", status_code=302)
            return RedirectResponse("/itcj/dashboard", status_code=302)
        return RedirectResponse("/itcj/auth/login", status_code=302)
