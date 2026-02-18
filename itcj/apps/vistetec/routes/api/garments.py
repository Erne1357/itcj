"""API de gestión de prendas (voluntarios/admin)."""
import os
from flask import request, jsonify, g, send_from_directory, current_app, abort
from itcj.core.utils.decorators import api_app_required
from itcj.apps.vistetec.routes.api import garments_api_bp
from itcj.apps.vistetec.services import garment_service


@garments_api_bp.get('')
@api_app_required('vistetec', perms=['vistetec.garments.api.create'])
def list_garments():
    """GET /api/vistetec/v1/garments - Lista todas las prendas (todos los estados)."""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    per_page = min(per_page, 100)

    result = garment_service.list_all_garments(
        page=page,
        per_page=per_page,
        status=request.args.get('status'),
        category=request.args.get('category'),
        search=request.args.get('search'),
    )
    return jsonify(result), 200


@garments_api_bp.post('')
@api_app_required('vistetec', perms=['vistetec.garments.api.create'])
def create_garment():
    """POST /api/vistetec/v1/garments - Registra una nueva prenda."""
    # Soporta FormData (con imagen) o JSON
    if request.content_type and 'multipart/form-data' in request.content_type:
        data = {
            'name': request.form.get('name'),
            'description': request.form.get('description'),
            'category': request.form.get('category'),
            'gender': request.form.get('gender'),
            'size': request.form.get('size'),
            'brand': request.form.get('brand'),
            'color': request.form.get('color'),
            'material': request.form.get('material'),
            'condition': request.form.get('condition'),
            'donated_by_id': request.form.get('donated_by_id', type=int),
        }
        image_file = request.files.get('image')
    else:
        data = request.get_json() or {}
        image_file = None

    # Validación básica
    if not data.get('name'):
        return jsonify({'error': 'El nombre es obligatorio'}), 400
    if not data.get('category'):
        return jsonify({'error': 'La categoría es obligatoria'}), 400
    if not data.get('condition'):
        return jsonify({'error': 'La condición es obligatoria'}), 400

    try:
        user_id = int(g.current_user['sub'])
        garment = garment_service.create_garment(
            data=data,
            image_file=image_file,
            registered_by_id=user_id,
        )
        return jsonify(garment.to_dict()), 201
    except ValueError as e:
        return jsonify({'error': str(e)}), 400


@garments_api_bp.put('/<int:garment_id>')
@api_app_required('vistetec', perms=['vistetec.garments.api.update'])
def update_garment(garment_id):
    """PUT /api/vistetec/v1/garments/<id> - Actualiza una prenda."""
    if request.content_type and 'multipart/form-data' in request.content_type:
        data = {}
        for field in ['name', 'description', 'category', 'gender', 'size',
                       'brand', 'color', 'material', 'condition']:
            val = request.form.get(field)
            if val is not None:
                data[field] = val
        image_file = request.files.get('image')
    else:
        data = request.get_json() or {}
        image_file = None

    try:
        garment = garment_service.update_garment(garment_id, data, image_file)
        if not garment:
            return jsonify({'error': 'Prenda no encontrada'}), 404
        return jsonify(garment.to_dict()), 200
    except ValueError as e:
        return jsonify({'error': str(e)}), 400


@garments_api_bp.delete('/<int:garment_id>')
@api_app_required('vistetec', perms=['vistetec.garments.api.delete'])
def delete_garment(garment_id):
    """DELETE /api/vistetec/v1/garments/<id> - Elimina una prenda (admin)."""
    if garment_service.delete_garment(garment_id):
        return jsonify({'message': 'Prenda eliminada'}), 200
    return jsonify({'error': 'Prenda no encontrada'}), 404


@garments_api_bp.post('/<int:garment_id>/withdraw')
@api_app_required('vistetec', perms=['vistetec.garments.api.withdraw'])
def withdraw_garment(garment_id):
    """POST /api/vistetec/v1/garments/<id>/withdraw - Retira una prenda."""
    garment = garment_service.withdraw_garment(garment_id)
    if not garment:
        return jsonify({'error': 'Prenda no encontrada o no se puede retirar'}), 404
    return jsonify(garment.to_dict()), 200


@garments_api_bp.get('/image/<path:image_path>')
@api_app_required('vistetec')
def serve_image(image_path):
    """GET /api/vistetec/v1/garments/image/<path> - Sirve imagen de prenda."""
    upload_path = current_app.config['VISTETEC_UPLOAD_PATH']
    directory = os.path.join(upload_path, os.path.dirname(image_path))
    filename = os.path.basename(image_path)

    if not os.path.exists(os.path.join(directory, filename)):
        abort(404)

    return send_from_directory(directory, filename)
