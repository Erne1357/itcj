# routes/templates/student.py
from flask import Blueprint, render_template, g, current_app, request, url_for, redirect
from itcj.core.utils.decorators import login_required, role_required_page, app_required
from itcj.apps.agendatec.services.student.home import has_request
from itcj.apps.agendatec.utils.period_utils import is_student_window_open, get_student_window, fmt_spanish

student_pages_bp = Blueprint("student_pages", __name__)

@student_pages_bp.before_request
def gate_student_period():
    """Redirige a /student/close cuando la ventana esté cerrada, excepto la propia página de cierre y assets."""
    # Permitir la página de cierre y assets estáticos
    if request.endpoint == "agendatec_pages.student_pages.student_close" and is_student_window_open():
        return redirect(url_for("agendatec_pages.student_pages.student_home"))
    if request.endpoint in ("agendatec_pages.student_pages.student_close", "agendatec_pages.student_pages.student_requests"):
        return
    if not is_student_window_open():
        return redirect(url_for("agendatec_pages.student_pages.student_close"))
    

@student_pages_bp.get("/home")
@login_required
@app_required("agendatec", roles=["student"])
def student_home():
    g.current_user["has_appointment"] = has_request(g.current_user["sub"])
    return render_template("agendatec/student/home.html", title="Alumno - Inicio")

@student_pages_bp.get("/requests")
@login_required
@app_required("agendatec",roles=["student"])
def student_requests():
    return render_template("agendatec/student/requests.html", title="Alumno - Mis solicitudes")

@student_pages_bp.get("/request")
@login_required
@app_required("agendatec",roles=["student"])
def student_new_request():
    return render_template("agendatec/student/new_request.html", title="Alumno - Nueva solicitud")

@student_pages_bp.get("/close")
@login_required
@app_required("agendatec",roles=["student"])
def student_close():
    start, end = get_student_window()
    return render_template("agendatec/student/close.html",
                           win_from=fmt_spanish(start),
                           win_to=fmt_spanish(end))