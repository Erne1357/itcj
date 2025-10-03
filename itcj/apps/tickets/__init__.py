from flask import Blueprint,redirect, url_for, g, current_app,render_template
from itcj.core.utils.decorators import login_required
from itcj.core.utils.decorators import guard_blueprint
import logging

# Blueprint de AgendaTec
tickets_api_bp = Blueprint('tickets_api', __name__, )
tickets_pages_bp = Blueprint('tickets_pages', __name__, template_folder='templates', static_folder='/static')

guard_blueprint(tickets_api_bp, "tickets")
guard_blueprint(tickets_pages_bp, "tickets")


@tickets_pages_bp.get("/")
@login_required
def home():
        return render_template("template.html", tittle="Tickets - Home")
        #urrent_app.logger.info(f"Redirigiendo a home de {g.current_user.get('role') if g.current_user else 'anónimo'}")
        #if g.current_user:
            #return redirect(role_home(g.current_user.get("role")))
        #return redirect(url_for("pages_core.pages_auth.login_page"))

def role_home(role: str) -> str:
        return { "student": "/agendatec/student/home",
                 "coordinator": "/agendatec/coord/home",
                 "social_service": "/agendatec/social/home",
                  "admin":"/agendatec/admin/home" }.get(role, "/")