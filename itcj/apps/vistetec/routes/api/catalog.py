"""API del catálogo público de prendas."""
from flask import request, jsonify, send_from_directory, current_app
from itcj.core.utils.decorators import api_app_required
from itcj.apps.vistetec.routes.api import catalog_api_bp
from itcj.apps.vistetec.services import catalog_service


@catalog_api_bp.get('')
@api_app_required('vistetec', perms=['vistetec.catalog.api.list'])
def list_catalog():
    """GET /api/vistetec/v1/catalog - Lista prendas disponibles con filtros."""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 12, type=int)
    per_page = min(per_page, 50)  # Limitar máximo

    result = catalog_service.list_garments(
        page=page,
        per_page=per_page,
        category=request.args.get('category'),
        gender=request.args.get('gender'),
        size=request.args.get('size'),
        color=request.args.get('color'),
        condition=request.args.get('condition'),
        search=request.args.get('search'),
    )
    return jsonify(result), 200


@catalog_api_bp.get('/<int:garment_id>')
@api_app_required('vistetec', perms=['vistetec.catalog.api.detail'])
def garment_detail(garment_id):
    """GET /api/vistetec/v1/catalog/<id> - Detalle de una prenda."""
    detail = catalog_service.get_garment_detail(garment_id)
    if not detail:
        return jsonify({'error': 'Prenda no encontrada'}), 404
    return jsonify(detail), 200


@catalog_api_bp.get('/categories')
@api_app_required('vistetec', perms=['vistetec.catalog.api.categories'])
def categories():
    """GET /api/vistetec/v1/catalog/categories - Categorías con prendas disponibles."""
    return jsonify(catalog_service.get_available_categories()), 200


@catalog_api_bp.get('/sizes')
@api_app_required('vistetec', perms=['vistetec.catalog.api.categories'])
def sizes():
    """GET /api/vistetec/v1/catalog/sizes - Tallas con prendas disponibles."""
    return jsonify(catalog_service.get_available_sizes()), 200


@catalog_api_bp.get('/stats')
@api_app_required('vistetec')
def stats():
    """GET /api/vistetec/v1/catalog/stats - Estadísticas generales."""
    return jsonify(catalog_service.get_catalog_stats()), 200
