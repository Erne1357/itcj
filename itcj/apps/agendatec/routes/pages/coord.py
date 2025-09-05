# routes/templates/coord.py
from flask import Blueprint, render_template, redirect,url_for,g
from .....core.utils.decorators import login_required, role_required_page, coord_pw_changed_required

coord_pages_bp = Blueprint("coord_pages", __name__)

@coord_pages_bp.get("/")
@login_required
@role_required_page(["coordinator","admin"])
def coord_index():
    return redirect(url_for("agendatec_pages.coord_pages.coord_home_page"))

@coord_pages_bp.get("/home")
@login_required
@role_required_page(["coordinator","admin"])
def coord_home_page():
    return render_template("coord/home.html", title="Coordinador - Dashboard")

@coord_pages_bp.get("/appointments")
@coord_pw_changed_required
@login_required
@role_required_page(["coordinator","admin"])
def coord_appointments_page():
    return render_template("coord/appointments.html", title="Coordinador - Citas del día")

@coord_pages_bp.get("/drops")
@coord_pw_changed_required
@login_required
@role_required_page(["coordinator","admin"])
def coord_drops_page():
    return render_template("coord/drops.html", title="Coordinador - Drops")

@coord_pages_bp.get("/slots")
@coord_pw_changed_required
@login_required
@role_required_page(["coordinator","admin"])
def coord_slots_page():
    return render_template("coord/slots.html", title="Coordinador - Horario ")
