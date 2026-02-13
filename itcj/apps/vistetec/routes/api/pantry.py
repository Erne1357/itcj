"""API para gestión de despensa y campañas."""

from flask import jsonify, request

from itcj.core.utils.decorators import api_app_required
from itcj.apps.vistetec.services import pantry_service
from itcj.apps.vistetec.routes.api import pantry_api_bp as bp


# ==================== ITEMS ====================

@bp.route('/items', methods=['GET'])
@api_app_required('vistetec', perms=['vistetec.pantry.api.view'])
def list_items():
    """Lista items de despensa."""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    category = request.args.get('category')
    search = request.args.get('search')
    is_active = request.args.get('is_active')

    active_filter = None
    if is_active is not None:
        active_filter = is_active.lower() == 'true'

    result = pantry_service.get_items(
        category=category,
        search=search,
        is_active=active_filter,
        page=page,
        per_page=per_page,
    )
    return jsonify(result)


@bp.route('/items', methods=['POST'])
@api_app_required('vistetec', perms=['vistetec.pantry.api.manage'])
def create_item():
    """Crea un item de despensa."""
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Datos requeridos'}), 400

    try:
        item = pantry_service.create_item(data)
        return jsonify({'message': 'Artículo creado', 'item': item.to_dict()}), 201
    except ValueError as e:
        return jsonify({'error': str(e)}), 400


@bp.route('/items/<int:item_id>', methods=['GET'])
@api_app_required('vistetec', perms=['vistetec.pantry.api.view'])
def get_item(item_id):
    """Obtiene un item por ID."""
    item = pantry_service.get_item_by_id(item_id)
    if not item:
        return jsonify({'error': 'Artículo no encontrado'}), 404
    return jsonify(item.to_dict())


@bp.route('/items/<int:item_id>', methods=['PUT'])
@api_app_required('vistetec', perms=['vistetec.pantry.api.manage'])
def update_item(item_id):
    """Actualiza un item de despensa."""
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Datos requeridos'}), 400

    try:
        item = pantry_service.update_item(item_id, data)
        return jsonify({'message': 'Artículo actualizado', 'item': item.to_dict()})
    except ValueError as e:
        return jsonify({'error': str(e)}), 400


@bp.route('/items/<int:item_id>', methods=['DELETE'])
@api_app_required('vistetec', perms=['vistetec.pantry.api.manage'])
def delete_item(item_id):
    """Desactiva un item (soft delete)."""
    try:
        pantry_service.deactivate_item(item_id)
        return jsonify({'message': 'Artículo desactivado'})
    except ValueError as e:
        return jsonify({'error': str(e)}), 400


@bp.route('/categories', methods=['GET'])
@api_app_required('vistetec', perms=['vistetec.pantry.api.view'])
def list_categories():
    """Lista categorías de items."""
    categories = pantry_service.get_categories()
    return jsonify(categories)


# ==================== STOCK ====================

@bp.route('/stock', methods=['GET'])
@api_app_required('vistetec', perms=['vistetec.pantry.api.view'])
def get_stock():
    """Retorna inventario actual."""
    summary = pantry_service.get_stock_summary()
    return jsonify(summary)


@bp.route('/stock/in', methods=['POST'])
@api_app_required('vistetec', perms=['vistetec.pantry.api.manage'])
def stock_in():
    """Registra entrada de stock."""
    data = request.get_json()
    if not data or 'item_id' not in data or 'quantity' not in data:
        return jsonify({'error': 'Se requiere item_id y quantity'}), 400

    try:
        item = pantry_service.stock_in(
            item_id=data['item_id'],
            quantity=data['quantity'],
            notes=data.get('notes'),
        )
        return jsonify({'message': 'Entrada registrada', 'item': item.to_dict()})
    except ValueError as e:
        return jsonify({'error': str(e)}), 400


@bp.route('/stock/out', methods=['POST'])
@api_app_required('vistetec', perms=['vistetec.pantry.api.manage'])
def stock_out():
    """Registra salida de stock."""
    data = request.get_json()
    if not data or 'item_id' not in data or 'quantity' not in data:
        return jsonify({'error': 'Se requiere item_id y quantity'}), 400

    try:
        item = pantry_service.stock_out(
            item_id=data['item_id'],
            quantity=data['quantity'],
            notes=data.get('notes'),
        )
        return jsonify({'message': 'Salida registrada', 'item': item.to_dict()})
    except ValueError as e:
        return jsonify({'error': str(e)}), 400


# ==================== CAMPAÑAS ====================

@bp.route('/campaigns', methods=['GET'])
@api_app_required('vistetec', perms=['vistetec.pantry.api.view'])
def list_campaigns():
    """Lista campañas."""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    is_active = request.args.get('is_active')

    active_filter = None
    if is_active is not None:
        active_filter = is_active.lower() == 'true'

    result = pantry_service.get_campaigns(
        is_active=active_filter,
        page=page,
        per_page=per_page,
    )
    return jsonify(result)


@bp.route('/campaigns/active', methods=['GET'])
@api_app_required('vistetec', perms=['vistetec.pantry.api.view'])
def list_active_campaigns():
    """Lista campañas activas."""
    campaigns = pantry_service.get_active_campaigns()
    return jsonify(campaigns)


@bp.route('/campaigns', methods=['POST'])
@api_app_required('vistetec', perms=['vistetec.pantry.api.manage_campaigns'])
def create_campaign():
    """Crea una campaña."""
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Datos requeridos'}), 400

    try:
        campaign = pantry_service.create_campaign(data)
        return jsonify({'message': 'Campaña creada', 'campaign': campaign.to_dict()}), 201
    except ValueError as e:
        return jsonify({'error': str(e)}), 400


@bp.route('/campaigns/<int:campaign_id>', methods=['GET'])
@api_app_required('vistetec', perms=['vistetec.pantry.api.view'])
def get_campaign(campaign_id):
    """Obtiene una campaña por ID."""
    campaign = pantry_service.get_campaign_by_id(campaign_id)
    if not campaign:
        return jsonify({'error': 'Campaña no encontrada'}), 404
    return jsonify(campaign.to_dict())


@bp.route('/campaigns/<int:campaign_id>', methods=['PUT'])
@api_app_required('vistetec', perms=['vistetec.pantry.api.manage_campaigns'])
def update_campaign(campaign_id):
    """Actualiza una campaña."""
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Datos requeridos'}), 400

    try:
        campaign = pantry_service.update_campaign(campaign_id, data)
        return jsonify({'message': 'Campaña actualizada', 'campaign': campaign.to_dict()})
    except ValueError as e:
        return jsonify({'error': str(e)}), 400


@bp.route('/campaigns/<int:campaign_id>', methods=['DELETE'])
@api_app_required('vistetec', perms=['vistetec.pantry.api.manage_campaigns'])
def delete_campaign(campaign_id):
    """Desactiva una campaña."""
    try:
        pantry_service.deactivate_campaign(campaign_id)
        return jsonify({'message': 'Campaña desactivada'})
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
