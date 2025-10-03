# routes/templates/coord.py
from flask import Blueprint, render_template, redirect,url_for,g
from itcj.core.utils.decorators import login_required, role_required_page, pw_changed_required,app_required

coord_pages_bp = Blueprint("coord_pages", __name__)

@coord_pages_bp.get("/")
@login_required
@app_required(app_key="agendatec", perms=["agendatec.coord_dashboard.view"])
def coord_index():
    return redirect(url_for("agendatec_pages.coord_pages.coord_home_page"))

@coord_pages_bp.get("/home")
@login_required
@app_required(app_key="agendatec", perms=["agendatec.coord_dashboard.view"])
def coord_home_page():
    return render_template("coord/home.html", title="Coordinador - Dashboard")

@coord_pages_bp.get("/appointments")
@pw_changed_required
@login_required
@app_required(app_key="agendatec", perms=["agendatec.appointments.view"])
def coord_appointments_page():
    return render_template("coord/appointments.html", title="Coordinador - Citas del día")

@coord_pages_bp.get("/drops")
@pw_changed_required
@login_required
@app_required(app_key="agendatec", perms=["agendatec.drops.view"])
def coord_drops_page():
    return render_template("coord/drops.html", title="Coordinador - Drops")

@coord_pages_bp.get("/slots")
@pw_changed_required
@login_required
@app_required(app_key="agendatec", perms=["agendatec.slots.view"])
def coord_slots_page():
    return render_template("coord/slots.html", title="Coordinador - Horario ")
