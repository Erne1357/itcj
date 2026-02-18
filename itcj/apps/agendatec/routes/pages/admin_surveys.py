# routes/pages/admin_surveys.py
"""
Paginas de encuestas para AgendaTec.

La autenticacion OAuth con Microsoft Graph se gestiona de forma centralizada
desde itcj/core (pestaña Correo en Configuracion). Aqui solo se renderiza
la pagina de encuestas y se consulta el estado de conexion.
"""
from flask import Blueprint, render_template

from itcj.core.utils.decorators import app_required, login_required
from itcj.core.utils.msgraph_mail import read_account_info

admin_surveys_pages_bp = Blueprint("admin_surveys_pages", __name__, template_folder="../../templates")

_APP_KEY = "agendatec"


@admin_surveys_pages_bp.get("/")
@login_required
@app_required(app_key="agendatec", perms=["agendatec.surveys.page.list"])
def admin_surveys():
    acct = read_account_info(_APP_KEY) or {}
    return render_template("agendatec/admin/surveys.html", ms_account=acct)
