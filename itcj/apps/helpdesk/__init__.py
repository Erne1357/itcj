from flask import Blueprint,redirect, url_for, g, current_app,render_template
from itcj.core.utils.decorators import login_required
from itcj.core.utils.decorators import guard_blueprint
from itcj.apps.helpdesk import models  # Asegura que los modelos se importen
import logging

# Blueprint de helpdesk
helpdesk_api_bp = Blueprint('helpdesk_api', __name__, )
helpdesk_pages_bp = Blueprint('helpdesk_pages', __name__, template_folder='templates', static_folder='/static')

guard_blueprint(helpdesk_api_bp, "helpdesk")
guard_blueprint(helpdesk_pages_bp, "helpdesk")

#Registro de blueprints de API
from itcj.apps.helpdesk.routes.api import tickets_api_bp
from itcj.apps.helpdesk.routes.api import assignments_api_bp
from itcj.apps.helpdesk.routes.api import comments_api_bp
from itcj.apps.helpdesk.routes.api import attachments_api_bp
from itcj.apps.helpdesk.routes.api import categories_api_bp

helpdesk_api_bp.register_blueprint(tickets_api_bp, url_prefix='/tickets')
helpdesk_api_bp.register_blueprint(assignments_api_bp, url_prefix='/assignments')
helpdesk_api_bp.register_blueprint(comments_api_bp, url_prefix='/comments')
helpdesk_api_bp.register_blueprint(attachments_api_bp, url_prefix='/attachments')
helpdesk_api_bp.register_blueprint(categories_api_bp, url_prefix='/categories')

@helpdesk_pages_bp.get("/")
@login_required
def home():
        return render_template("template.html", tittle="Tickets - Home")
        #urrent_app.logger.info(f"Redirigiendo a home de {g.current_user.get('role') if g.current_user else 'anónimo'}")
        #if g.current_user:
            #return redirect(role_home(g.current_user.get("role")))
        #return redirect(url_for("pages_core.pages_auth.login_page"))

@helpdesk_pages_bp.get("/tech")
@login_required
def tech_home():
    return render_template("tecnicos.html", title="Tickets - Tech")

@helpdesk_pages_bp.get("/secretaria")
@login_required
def secretaria_home():
    return render_template("secretaria.html", title="Tickets - Secretaria")

@helpdesk_pages_bp.get("/jefe-departamento")
@login_required
def jefe_departamento_home():
    return render_template("jefe-departamento.html", title="Tickets - Jefe de Departamento")

@helpdesk_pages_bp.get("/mis-tickets")
@login_required
def mis_tickets():
    return render_template("mis-tickets.html", title="Tickets - Mis Tickets")

@helpdesk_pages_bp.get("/crear-ticket")
@login_required
def crear_ticket():
    return render_template("crear-ticket.html", title="Tickets - Crear Ticket")


def role_home(role: str) -> str:
        return { "student": "/agendatec/student/home",
                 "coordinator": "/agendatec/coord/home",
                 "social_service": "/agendatec/social/home",
                  "admin":"/agendatec/admin/home" }.get(role, "/")