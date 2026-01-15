# routes/pages/coord.py
"""
Páginas de coordinadores para AgendaTec.

Incluye: dashboard, citas, bajas y configuración de horarios.
"""
from flask import Blueprint, redirect, render_template, url_for

from itcj.core.utils.decorators import (
    app_required,
    login_required,
    pw_changed_required,
)

coord_pages_bp = Blueprint("coord_pages", __name__)

@coord_pages_bp.get("/")
@login_required
@app_required(app_key="agendatec", perms=["agendatec.coord_dashboard.page.view"])
def coord_index():
    return redirect(url_for("agendatec_pages.coord_pages.coord_home_page"))

@coord_pages_bp.get("/home")
@login_required
@app_required(app_key="agendatec", perms=["agendatec.coord_dashboard.page.view"])
def coord_home_page():
    return render_template("agendatec/coord/home.html", title="Coordinador - Dashboard")

@coord_pages_bp.get("/appointments")
@pw_changed_required
@login_required
@app_required(app_key="agendatec", perms=["agendatec.appointments.page.list"])
def coord_appointments_page():
    return render_template("agendatec/coord/appointments.html", title="Coordinador - Citas del día")

@coord_pages_bp.get("/drops")
@pw_changed_required
@login_required
@app_required(app_key="agendatec", perms=["agendatec.drops.page.list"])
def coord_drops_page():
    return render_template("agendatec/coord/drops.html", title="Coordinador - Drops")

@coord_pages_bp.get("/slots")
@pw_changed_required
@login_required
@app_required(app_key="agendatec", perms=["agendatec.slots.page.list"])
def coord_slots_page():
    return render_template("agendatec/coord/slots.html", title="Coordinador - Horario ")
