# backend/routes/pages/admin.py
from flask import Blueprint, render_template
from itcj.core.utils.decorators import role_required_page, login_required,app_required

admin_pages_bp = Blueprint("admin_pages", __name__)

@admin_pages_bp.get("/home")
@login_required
@app_required(app_key="agendatec", perms=["agendatec.admin_dashboard.view"])
def admin_home():
    return render_template("agendatec/admin/home.html", page_title="Admin · Dashboard")

@admin_pages_bp.get("/users")
@login_required
@app_required(app_key="agendatec", perms=["agendatec.users.view"])
def admin_users():
    return render_template("agendatec/admin/users.html", page_title="Admin · Usuarios")

@admin_pages_bp.get("/requests")
@login_required
@app_required(app_key="agendatec", perms=["agendatec.requests_all.view"])
def admin_requests():
    return render_template("agendatec/admin/requests.html", page_title="Admin · Solicitudes")

@admin_pages_bp.get("/reports")
@login_required
@app_required(app_key="agendatec", perms=["agendatec.reports.view"])
def admin_reports():
    return render_template("agendatec/admin/reports.html", page_title="Admin · Reportes")
