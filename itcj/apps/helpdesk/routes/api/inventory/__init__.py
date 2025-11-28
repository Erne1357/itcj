from flask import Blueprint

# Crear blueprints de API
from itcj.apps.helpdesk.routes.api import inventory_api_bp

# Importar rutas para registrarlas
from itcj.apps.helpdesk.routes.api.inventory.inventory_categories import bp as inventory_categories
from itcj.apps.helpdesk.routes.api.inventory.inventory_history import bp as inventory_history
from itcj.apps.helpdesk.routes.api.inventory.inventory_stats import bp as inventory_stats
from itcj.apps.helpdesk.routes.api.inventory.inventory_items import bp as inventory_items
from itcj.apps.helpdesk.routes.api.inventory.inventory_assignments import bp as inventory_assignments
from itcj.apps.helpdesk.routes.api.inventory.inventory_dashboard import bp as inventory_dashboard
from itcj.apps.helpdesk.routes.api.inventory.inventory_groups import inventory_groups_api_bp
from itcj.apps.helpdesk.routes.api.inventory.inventory_bulk import inventory_bulk_api_bp
from itcj.apps.helpdesk.routes.api.inventory.inventory_pending import inventory_pending_api_bp
from itcj.apps.helpdesk.routes.api.inventory.inventory_selection import bp as inventory_selection

import itcj.apps.helpdesk.routes.api.inventory.inventory_assignments
import itcj.apps.helpdesk.routes.api.inventory.inventory_categories
import itcj.apps.helpdesk.routes.api.inventory.inventory_dashboard
import itcj.apps.helpdesk.routes.api.inventory.inventory_history
import itcj.apps.helpdesk.routes.api.inventory.inventory_items
import itcj.apps.helpdesk.routes.api.inventory.inventory_stats
import itcj.apps.helpdesk.routes.api.inventory.inventory_groups
import itcj.apps.helpdesk.routes.api.inventory.inventory_bulk
import itcj.apps.helpdesk.routes.api.inventory.inventory_pending
import itcj.apps.helpdesk.routes.api.inventory.inventory_selection

inventory_api_bp.register_blueprint(inventory_categories, url_prefix='/categories')
inventory_api_bp.register_blueprint(inventory_history, url_prefix='/history')
inventory_api_bp.register_blueprint(inventory_stats, url_prefix='/stats')
inventory_api_bp.register_blueprint(inventory_items, url_prefix='/items')
inventory_api_bp.register_blueprint(inventory_assignments, url_prefix='/assignments')
inventory_api_bp.register_blueprint(inventory_dashboard, url_prefix='/dashboard')
inventory_api_bp.register_blueprint(inventory_groups_api_bp, url_prefix='/groups')
inventory_api_bp.register_blueprint(inventory_bulk_api_bp, url_prefix='/bulk')
inventory_api_bp.register_blueprint(inventory_pending_api_bp, url_prefix='/pending')
inventory_api_bp.register_blueprint(inventory_selection, url_prefix='/selection')