from flask import Blueprint,redirect, url_for, g, current_app
from itcj.core.utils.decorators import login_required
from itcj.core.utils.decorators import guard_blueprint
import logging

# Blueprint de AgendaTec
agendatec_api_bp = Blueprint('agendatec_api', __name__, )
agendatec_pages_bp = Blueprint('agendatec_pages', __name__, template_folder='/templates', static_folder='/static')

#guard_blueprint(agendatec_api_bp, "agendatec")
#guard_blueprint(agendatec_pages_bp, "agendatec")
from .routes.api.programs_academic import api_programs_bp
from .routes.api.availability import api_avail_bp
from .routes.api.requests import api_req_bp
from .routes.api.slots import api_slots_bp
from .routes.api.coord import api_coord_bp
from .routes.api.social import api_social_bp
from .routes.api.admin import api_admin_bp
from .routes.api.notifications import api_notifications_bp
agendatec_api_bp.register_blueprint(api_programs_bp, url_prefix="/api/agendatec/v1")
agendatec_api_bp.register_blueprint(api_avail_bp, url_prefix="/api/agendatec/v1")
agendatec_api_bp.register_blueprint(api_req_bp, url_prefix="/api/agendatec/v1")
agendatec_api_bp.register_blueprint(api_slots_bp, url_prefix="/api/agendatec/v1")
agendatec_api_bp.register_blueprint(api_coord_bp, url_prefix="/api/agendatec/v1")
agendatec_api_bp.register_blueprint(api_social_bp,url_prefix="/api/agendatec/v1")
agendatec_api_bp.register_blueprint(api_admin_bp, url_prefix="/api/agendatec/v1/admin")
agendatec_api_bp.register_blueprint(api_notifications_bp,url_prefix="/api/agendatec/v1")

#Register blueprints for pages
from .routes.pages.student import student_pages_bp
from .routes.pages.coord import coord_pages_bp
from .routes.pages.social import social_pages_bp
from .routes.pages.admin import admin_pages_bp
from .routes.pages.admin_surveys import admin_surveys_pages
agendatec_pages_bp.register_blueprint(social_pages_bp, url_prefix="/social")
agendatec_pages_bp.register_blueprint(student_pages_bp, url_prefix="/student")
agendatec_pages_bp.register_blueprint(coord_pages_bp, url_prefix="/coord")
agendatec_pages_bp.register_blueprint(admin_pages_bp, url_prefix="/admin")
agendatec_pages_bp.register_blueprint(admin_surveys_pages)

@agendatec_pages_bp.get("/")
@login_required
def home():
        current_app.logger.info(f"Redirigiendo a home de {g.current_user.get('role') if g.current_user else 'anónimo'}")
        if g.current_user:
            return redirect(role_home(g.current_user.get("role")))
        return redirect(url_for("pages_core.pages_auth.login_page"))

def role_home(role: str) -> str:
        return { "student": "/agendatec/student/home",
                 "coordinator": "/agendatec/coord/home",
                 "social_service": "/agendatec/social/home",
                  "admin":"/agendatec/admin/home" }.get(role, "/")