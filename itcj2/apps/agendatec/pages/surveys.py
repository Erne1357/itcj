"""
Páginas de encuestas para AgendaTec (admin).
Equivalente a itcj/apps/agendatec/routes/pages/admin_surveys.py.

Rutas:
  GET /agendatec/surveys/  → Panel de encuestas con estado de cuenta Microsoft
"""
import logging

from fastapi import APIRouter, Depends, Request

from itcj2.apps.agendatec.pages.nav import render_agendatec
from itcj2.dependencies import require_page_app

logger = logging.getLogger("itcj2.apps.agendatec.pages.surveys")

router = APIRouter(prefix="/surveys", tags=["agendatec-pages-surveys"])

_APP_KEY = "agendatec"


@router.get("", include_in_schema=False)
@router.get("/", name="agendatec.pages.surveys.admin_surveys")
async def admin_surveys(
    request: Request,
    user: dict = Depends(require_page_app("agendatec", perms=["agendatec.surveys.page.list"])),
):
    """Panel de encuestas — muestra el estado de la cuenta Microsoft conectada."""
    from itcj2.core.utils.msgraph_mail import read_account_info

    ms_account = read_account_info(_APP_KEY) or {}

    return render_agendatec(request, "agendatec/admin/surveys.html", {
        "ms_account": ms_account,
    })
