# routes/pages/admin.py
"""
Páginas de administración para AgendaTec.

Incluye: dashboard, usuarios, solicitudes, reportes y períodos.
"""
from flask import Blueprint, render_template

from itcj.core.utils.decorators import app_required, login_required

admin_pages_bp = Blueprint("admin_pages", __name__)

@admin_pages_bp.get("/home")
@login_required
@app_required(app_key="agendatec", perms=["agendatec.admin_dashboard.page.view"])
def admin_home():
    return render_template("agendatec/admin/home.html", page_title="Admin · Dashboard")

@admin_pages_bp.get("/users")
@login_required
@app_required(app_key="agendatec", perms=["agendatec.users.page.list"])
def admin_users():
    return render_template("agendatec/admin/users.html", page_title="Admin · Usuarios")

@admin_pages_bp.get("/requests")
@login_required
@app_required(app_key="agendatec", perms=["agendatec.requests.page.list"])
def admin_requests():
    return render_template("agendatec/admin/requests.html", page_title="Admin · Solicitudes")

@admin_pages_bp.get("/requests/create")
@login_required
@app_required(app_key="agendatec", perms=["agendatec.requests.page.create"])
def admin_create_request():
    return render_template("agendatec/admin/create_request.html", page_title="Admin · Crear Solicitud")

@admin_pages_bp.get("/reports")
@login_required
@app_required(app_key="agendatec", perms=["agendatec.reports.page.view"])
def admin_reports():
    return render_template("agendatec/admin/reports.html", page_title="Admin · Reportes")

@admin_pages_bp.get("/periods")
@login_required
@app_required(app_key="agendatec", perms=["agendatec.periods.page.list"])
def admin_periods():
    return render_template("agendatec/admin/periods.html", page_title="Admin · Períodos Académicos")

@admin_pages_bp.get("/periods/<int:period_id>/days")
@login_required
@app_required(app_key="agendatec", perms=["agendatec.periods.page.edit"])
def admin_period_days(period_id):
    return render_template("agendatec/admin/period_days.html", page_title="Admin · Configurar Días", period_id=period_id)
