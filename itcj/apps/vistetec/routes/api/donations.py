"""API para gestión de donaciones."""

from flask import jsonify, request, g
from sqlalchemy import or_

from itcj.core.utils.decorators import api_app_required
from itcj.apps.vistetec.services import donation_service
from itcj.apps.vistetec.routes.api import donations_api_bp as bp
from itcj.core.models.user import User


@bp.route('/search-donors', methods=['GET'])
@api_app_required('vistetec', perms=['vistetec.donations.api.register'])
def search_donors():
    """Busca estudiantes/usuarios para asignar como donantes."""
    query = request.args.get('q', '').strip()

    if len(query) < 2:
        return jsonify([])

    # Buscar por número de control o nombre
    users = User.query.filter(
        User.is_active == True,
        or_(
            User.control_number.ilike(f'%{query}%'),
            User.first_name.ilike(f'%{query}%'),
            User.last_name.ilike(f'%{query}%'),
        )
    ).limit(10).all()

    return jsonify([
        {
            'id': u.id,
            'name': u.full_name,
            'control_number': u.control_number,
        }
        for u in users
    ])


@bp.route('', methods=['GET'])
@api_app_required('vistetec', perms=['vistetec.donations.api.view_all'])
def list_donations():
    """Lista todas las donaciones."""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    donation_type = request.args.get('type')

    result = donation_service.get_donations(
        donation_type=donation_type,
        page=page,
        per_page=per_page
    )

    return jsonify(result)


@bp.route('/my-donations', methods=['GET'])
@api_app_required('vistetec', perms=['vistetec.donations.api.view_own'])
def list_my_donations():
    """Lista mis donaciones como donante."""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)

    result = donation_service.get_my_donations(
        user_id=g.current_user["sub"],
        page=page,
        per_page=per_page
    )

    return jsonify(result)


@bp.route('/stats', methods=['GET'])
@api_app_required('vistetec', perms=['vistetec.donations.api.stats'])
def get_stats():
    """Obtiene estadísticas de donaciones."""
    # Si es estudiante, solo sus stats
    my_stats = request.args.get('mine', 'false').lower() == 'true'

    donor_id = g.current_user["sub"] if my_stats else None
    stats = donation_service.get_donation_stats(donor_id=donor_id)

    return jsonify(stats)


@bp.route('/top-donors', methods=['GET'])
@api_app_required('vistetec', perms=['vistetec.donations.api.stats'])
def get_top_donors():
    """Obtiene los top donadores."""
    limit = request.args.get('limit', 10, type=int)
    donors = donation_service.get_top_donors(limit=limit)
    return jsonify(donors)


@bp.route('/recent', methods=['GET'])
@api_app_required('vistetec', perms=['vistetec.donations.api.view_all'])
def get_recent():
    """Obtiene las donaciones más recientes."""
    limit = request.args.get('limit', 10, type=int)
    donations = donation_service.get_recent_donations(limit=limit)
    return jsonify([d.to_dict(include_relations=True) for d in donations])


@bp.route('/garment', methods=['POST'])
@api_app_required('vistetec', perms=['vistetec.donations.api.register'])
def register_garment_donation():
    """Registra una donación de prenda."""
    data = request.get_json()

    if not data:
        return jsonify({'error': 'Datos requeridos'}), 400

    # Puede ser una prenda existente o crear una nueva
    garment_id = data.get('garment_id')
    garment_data = data.get('garment')

    if not garment_id and not garment_data:
        return jsonify({'error': 'Se requiere garment_id o datos de prenda'}), 400

    try:
        if garment_id:
            # Prenda existente
            donation = donation_service.register_garment_donation(
                registered_by_id=g.current_user["sub"],
                garment_id=garment_id,
                donor_id=data.get('donor_id'),
                donor_name=data.get('donor_name'),
                notes=data.get('notes')
            )
        else:
            # Nueva prenda
            required = ['name', 'category', 'condition']
            for field in required:
                if field not in garment_data:
                    return jsonify({'error': f'Campo requerido en prenda: {field}'}), 400

            donation = donation_service.register_new_garment_donation(
                registered_by_id=g.current_user["sub"],
                garment_data=garment_data,
                donor_id=data.get('donor_id'),
                donor_name=data.get('donor_name'),
                notes=data.get('notes')
            )

        return jsonify({
            'message': 'Donación registrada exitosamente',
            'donation': donation.to_dict(include_relations=True)
        }), 201

    except ValueError as e:
        return jsonify({'error': str(e)}), 400


@bp.route('/pantry', methods=['POST'])
@api_app_required('vistetec', perms=['vistetec.donations.api.register'])
def register_pantry_donation():
    """Registra una donación de despensa."""
    data = request.get_json()

    if not data:
        return jsonify({'error': 'Datos requeridos'}), 400

    if 'pantry_item_id' not in data:
        return jsonify({'error': 'Campo requerido: pantry_item_id'}), 400

    try:
        donation = donation_service.register_pantry_donation(
            registered_by_id=g.current_user["sub"],
            pantry_item_id=data['pantry_item_id'],
            quantity=data.get('quantity', 1),
            donor_id=data.get('donor_id'),
            donor_name=data.get('donor_name'),
            campaign_id=data.get('campaign_id'),
            notes=data.get('notes')
        )

        return jsonify({
            'message': 'Donación registrada exitosamente',
            'donation': donation.to_dict(include_relations=True)
        }), 201

    except ValueError as e:
        return jsonify({'error': str(e)}), 400


@bp.route('/<int:donation_id>', methods=['GET'])
@api_app_required('vistetec', perms=['vistetec.donations.api.view_all'])
def get_donation(donation_id):
    """Obtiene una donación por ID."""
    donation = donation_service.get_donation_by_id(donation_id)

    if not donation:
        return jsonify({'error': 'Donación no encontrada'}), 404

    return jsonify(donation.to_dict(include_relations=True))
