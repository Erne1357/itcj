from fastapi import FastAPI


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
