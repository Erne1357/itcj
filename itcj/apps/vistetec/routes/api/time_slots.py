"""API para gestión de horarios de disponibilidad (slots generales)."""

from datetime import datetime

from flask import jsonify, request, g

from itcj.core.utils.decorators import api_app_required
from itcj.apps.vistetec.services import time_slot_service
from itcj.apps.vistetec.routes.api import slots_api_bp as bp


# ==================== QUERIES ====================

@bp.route('', methods=['GET'])
@api_app_required('vistetec', perms=['vistetec.slots.api.view_available'])
def list_available_slots():
    """Lista slots disponibles para estudiantes."""
    from_date = request.args.get('from_date')
    to_date = request.args.get('to_date')
    location_id = request.args.get('location_id', type=int)

    from_date = datetime.fromisoformat(from_date).date() if from_date else None
    to_date = datetime.fromisoformat(to_date).date() if to_date else None

    slots = time_slot_service.get_available_slots(
        from_date=from_date,
        to_date=to_date,
        location_id=location_id
    )

    return jsonify([s.to_dict() for s in slots])


@bp.route('/all', methods=['GET'])
@api_app_required('vistetec', perms=['vistetec.slots.api.view_own'])
def list_all_slots():
    """Lista todos los slots activos futuros (para voluntarios)."""
    from_date = request.args.get('from_date')
    to_date = request.args.get('to_date')
    location_id = request.args.get('location_id', type=int)

    from_date = datetime.fromisoformat(from_date).date() if from_date else None
    to_date = datetime.fromisoformat(to_date).date() if to_date else None

    slots = time_slot_service.get_all_slots(
        from_date=from_date,
        to_date=to_date,
        location_id=location_id
    )

    volunteer_id = int(g.current_user["sub"])
    result = []
    for s in slots:
        data = s.to_dict(include_volunteers=True)
        data['is_signed_up'] = time_slot_service.is_volunteer_signed_up(s.id, volunteer_id)
        result.append(data)

    return jsonify(result)


@bp.route('/calendar', methods=['GET'])
@api_app_required('vistetec', perms=['vistetec.slots.api.view_available'])
def get_calendar_slots():
    """Obtiene slots agrupados por fecha para un calendario."""
    from_date = request.args.get('from_date')
    to_date = request.args.get('to_date')

    if not from_date or not to_date:
        return jsonify({'error': 'Se requieren from_date y to_date'}), 400

    from_date = datetime.fromisoformat(from_date).date()
    to_date = datetime.fromisoformat(to_date).date()

    slots = time_slot_service.get_slots_for_date_range(from_date, to_date)

    return jsonify(slots)


@bp.route('/locations', methods=['GET'])
@api_app_required('vistetec', perms=['vistetec.slots.api.view_available'])
def list_locations():
    """Lista ubicaciones disponibles."""
    locations = time_slot_service.get_locations()
    return jsonify([loc.to_dict() for loc in locations])


@bp.route('/my-slots', methods=['GET'])
@api_app_required('vistetec', perms=['vistetec.slots.api.view_own'])
def list_my_signups():
    """Lista los slots donde estoy inscrito como voluntario."""
    include_past = request.args.get('include_past', 'false').lower() == 'true'

    slots = time_slot_service.get_volunteer_signups(
        volunteer_id=int(g.current_user["sub"]),
        include_past=include_past
    )

    return jsonify([s.to_dict(include_volunteers=True) for s in slots])


# ==================== SCHEDULE CREATION ====================

@bp.route('', methods=['POST'])
@api_app_required('vistetec', perms=['vistetec.slots.api.create'])
def create_schedule():
    """Crea horarios dividiendo un bloque en slots por duración."""
    data = request.get_json()

    if not data:
        return jsonify({'error': 'Datos requeridos'}), 400

    required = ['start_date', 'end_date', 'weekdays', 'start_time', 'end_time', 'slot_duration_minutes']
    for field in required:
        if field not in data:
            return jsonify({'error': f'Campo requerido: {field}'}), 400

    try:
        start_date = datetime.fromisoformat(data['start_date']).date()
        end_date = datetime.fromisoformat(data['end_date']).date()
        start_time = datetime.strptime(data['start_time'], '%H:%M').time()
        end_time = datetime.strptime(data['end_time'], '%H:%M').time()

        slots = time_slot_service.create_schedule_slots(
            created_by_id=int(g.current_user["sub"]),
            start_date=start_date,
            end_date=end_date,
            weekdays=data['weekdays'],
            start_time=start_time,
            end_time=end_time,
            slot_duration_minutes=int(data['slot_duration_minutes']),
            max_students_per_slot=int(data.get('max_students_per_slot', 1)),
            location_id=data.get('location_id')
        )

        return jsonify({
            'created': len(slots),
            'slots': [s.to_dict() for s in slots]
        }), 201

    except ValueError as e:
        return jsonify({'error': str(e)}), 400


# ==================== VOLUNTEER SIGNUP ====================

@bp.route('/<int:slot_id>/signup', methods=['POST'])
@api_app_required('vistetec', perms=['vistetec.slots.api.signup'])
def signup_for_slot(slot_id):
    """Voluntario se inscribe a un slot."""
    try:
        sv = time_slot_service.signup_volunteer(
            slot_id=slot_id,
            volunteer_id=int(g.current_user["sub"])
        )
        return jsonify({
            'message': 'Inscrito al horario',
            'signup': sv.to_dict()
        }), 201

    except ValueError as e:
        return jsonify({'error': str(e)}), 400


@bp.route('/<int:slot_id>/unsignup', methods=['POST'])
@api_app_required('vistetec', perms=['vistetec.slots.api.signup'])
def unsignup_from_slot(slot_id):
    """Voluntario cancela su inscripción a un slot."""
    try:
        time_slot_service.unsignup_volunteer(
            slot_id=slot_id,
            volunteer_id=int(g.current_user["sub"])
        )
        return jsonify({'message': 'Inscripción cancelada'})

    except ValueError as e:
        return jsonify({'error': str(e)}), 400


# ==================== SLOT MANAGEMENT ====================

@bp.route('/<int:slot_id>', methods=['PUT'])
@api_app_required('vistetec', perms=['vistetec.slots.api.update'])
def update_slot(slot_id):
    """Actualiza un slot (solo el creador)."""
    data = request.get_json()

    if not data:
        return jsonify({'error': 'Datos requeridos'}), 400

    try:
        if 'date' in data:
            data['date'] = datetime.fromisoformat(data['date']).date()
        if 'start_time' in data:
            data['start_time'] = datetime.strptime(data['start_time'], '%H:%M').time()
        if 'end_time' in data:
            data['end_time'] = datetime.strptime(data['end_time'], '%H:%M').time()

        slot = time_slot_service.update_slot(
            slot_id=slot_id,
            user_id=int(g.current_user["sub"]),
            **data
        )

        return jsonify(slot.to_dict())

    except ValueError as e:
        return jsonify({'error': str(e)}), 400


@bp.route('/<int:slot_id>', methods=['DELETE'])
@api_app_required('vistetec', perms=['vistetec.slots.api.delete'])
def cancel_slot(slot_id):
    """Cancela un slot (solo el creador)."""
    try:
        slot = time_slot_service.cancel_slot(
            slot_id=slot_id,
            user_id=int(g.current_user["sub"])
        )

        return jsonify({'message': 'Slot cancelado', 'slot': slot.to_dict()})

    except ValueError as e:
        return jsonify({'error': str(e)}), 400
