from flask import Blueprint,redirect, url_for, g, current_app
from itcj.core.utils.decorators import login_required
import logging

# Blueprint de AgendaTec
api_core_bp = Blueprint('api_core', __name__ )
pages_core_bp = Blueprint('pages_core', __name__, template_folder='templates', static_folder='static')

from .routes.api.auth import api_auth_bp
from .routes.api.user import api_user_bp
from .routes.api.authz import api_authz_bp
from .routes.api.positions import api_positions_bp
from .routes.api.departments import api_departments_bp
api_core_bp.register_blueprint(api_departments_bp, url_prefix="/departments")
api_core_bp.register_blueprint(api_positions_bp, url_prefix="/positions")
api_core_bp.register_blueprint(api_auth_bp, url_prefix="/auth")
api_core_bp.register_blueprint(api_user_bp, url_prefix="/user")
api_core_bp.register_blueprint(api_authz_bp, url_prefix="/authz")

from .routes.pages.auth import pages_auth_bp
from .routes.pages.dashboard import pages_dashboard_bp
from .routes.pages.config import pages_config_bp
pages_core_bp.register_blueprint(pages_auth_bp)
pages_core_bp.register_blueprint(pages_dashboard_bp)
pages_core_bp.register_blueprint(pages_config_bp)