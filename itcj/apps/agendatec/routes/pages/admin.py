# backend/routes/pages/admin.py
from flask import Blueprint, render_template
from .....core.utils.decorators import role_required_page, login_required

admin_pages_bp = Blueprint("admin_pages", __name__)

@admin_pages_bp.get("/home")
@login_required
@role_required_page(["admin"])
def admin_home():
    return render_template("admin/home.html", page_title="Admin · Dashboard")

@admin_pages_bp.get("/users")
@login_required
@role_required_page(["admin"])
def admin_users():
    return render_template("admin/users.html", page_title="Admin · Usuarios")

@admin_pages_bp.get("/requests")
@login_required
@role_required_page(["admin"])
def admin_requests():
    return render_template("admin/requests.html", page_title="Admin · Solicitudes")

@admin_pages_bp.get("/reports")
@login_required
@role_required_page(["admin"])
def admin_reports():
    return render_template("admin/reports.html", page_title="Admin · Reportes")
