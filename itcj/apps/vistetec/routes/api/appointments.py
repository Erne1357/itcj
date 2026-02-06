"""API para gestión de citas."""

from datetime import datetime

from flask import jsonify, request, g

from itcj.core.utils.decorators import api_app_required
from itcj.apps.vistetec.services import appointment_service
from itcj.apps.vistetec.routes.api import appointments_api_bp as bp


# === Endpoints para estudiantes ===

@bp.route('/my-appointments', methods=['GET'])
@api_app_required('vistetec', 'vistetec.appointments.api.view_own')
def list_my_appointments():
    """Lista mis citas como estudiante."""
    status = request.args.get('status')
    include_past = request.args.get('include_past', 'false').lower() == 'true'

    appointments = appointment_service.get_student_appointments(
        student_id=g.current_user["sub"],
        status=status,
        include_past=include_past
    )

    return jsonify([a.to_dict(include_relations=True) for a in appointments])


@bp.route('', methods=['POST'])
@api_app_required('vistetec', 'vistetec.appointments.api.create')
def create_appointment():
    """Crea una nueva cita."""
    data = request.get_json()

    if not data:
        return jsonify({'error': 'Datos requeridos'}), 400

    required = ['garment_id', 'slot_id']
    for field in required:
        if field not in data:
            return jsonify({'error': f'Campo requerido: {field}'}), 400

    try:
        appointment = appointment_service.create_appointment(
            student_id=g.current_user["sub"],
            garment_id=data['garment_id'],
            slot_id=data['slot_id']
        )

        return jsonify({
            'message': 'Cita agendada exitosamente',
            'appointment': appointment.to_dict(include_relations=True)
        }), 201

    except ValueError as e:
        return jsonify({'error': str(e)}), 400


@bp.route('/<int:appointment_id>/cancel', methods=['POST'])
@api_app_required('vistetec', 'vistetec.appointments.api.cancel')
def cancel_my_appointment(appointment_id):
    """Cancela mi cita como estudiante."""
    try:
        appointment = appointment_service.cancel_appointment(
            appointment_id=appointment_id,
            user_id=g.current_user["sub"],
            is_volunteer=False
        )

        return jsonify({
            'message': 'Cita cancelada',
            'appointment': appointment.to_dict()
        })

    except ValueError as e:
        return jsonify({'error': str(e)}), 400


# === Endpoints para voluntarios ===

@bp.route('/volunteer/list', methods=['GET'])
@api_app_required('vistetec', 'vistetec.appointments.api.view_all')
def list_volunteer_appointments():
    """Lista citas de los slots del voluntario."""
    date_str = request.args.get('date')
    status = request.args.get('status')

    date_filter = datetime.fromisoformat(date_str).date() if date_str else None

    appointments = appointment_service.get_volunteer_appointments(
        volunteer_id=g.current_user["sub"],
        date_filter=date_filter,
        status=status
    )

    return jsonify([a.to_dict(include_relations=True) for a in appointments])


@bp.route('/volunteer/today', methods=['GET'])
@api_app_required('vistetec', 'vistetec.appointments.api.view_all')
def list_today_appointments():
    """Lista citas de hoy para el voluntario."""
    appointments = appointment_service.get_today_appointments_for_volunteer(g.current_user["sub"])
    return jsonify([a.to_dict(include_relations=True) for a in appointments])


@bp.route('/<int:appointment_id>/attendance', methods=['POST'])
@api_app_required('vistetec', 'vistetec.appointments.api.attend')
def mark_attendance(appointment_id):
    """Marca asistencia de una cita."""
    data = request.get_json()

    if not data or 'attended' not in data:
        return jsonify({'error': 'Se requiere el campo "attended"'}), 400

    try:
        appointment = appointment_service.mark_attendance(
            appointment_id=appointment_id,
            volunteer_id=g.current_user["sub"],
            attended=data['attended']
        )

        return jsonify({
            'message': 'Asistencia registrada',
            'appointment': appointment.to_dict(include_relations=True)
        })

    except ValueError as e:
        return jsonify({'error': str(e)}), 400


@bp.route('/<int:appointment_id>/complete', methods=['POST'])
@api_app_required('vistetec', 'vistetec.appointments.api.attend')
def complete_appointment(appointment_id):
    """Completa una cita con el resultado."""
    data = request.get_json()

    if not data or 'outcome' not in data:
        return jsonify({'error': 'Se requiere el campo "outcome"'}), 400

    try:
        appointment = appointment_service.complete_appointment(
            appointment_id=appointment_id,
            volunteer_id=g.current_user["sub"],
            outcome=data['outcome'],
            notes=data.get('notes')
        )

        return jsonify({
            'message': 'Cita completada',
            'appointment': appointment.to_dict(include_relations=True)
        })

    except ValueError as e:
        return jsonify({'error': str(e)}), 400


@bp.route('/volunteer/<int:appointment_id>/cancel', methods=['POST'])
@api_app_required('vistetec', 'vistetec.appointments.api.attend')
def volunteer_cancel_appointment(appointment_id):
    """Cancela una cita como voluntario."""
    try:
        appointment = appointment_service.cancel_appointment(
            appointment_id=appointment_id,
            user_id=g.current_user["sub"],
            is_volunteer=True
        )

        return jsonify({
            'message': 'Cita cancelada',
            'appointment': appointment.to_dict()
        })

    except ValueError as e:
        return jsonify({'error': str(e)}), 400


@bp.route('/stats', methods=['GET'])
@api_app_required('vistetec', 'vistetec.appointments.api.view_own')
def get_stats():
    """Obtiene estadísticas de citas."""
    # Si es voluntario, filtrar por sus slots
    from itcj.core.models.user import User
    user = g.user

    volunteer_id = None
    if any(r.name == 'volunteer' for r in user.roles):
        volunteer_id = user.id

    stats = appointment_service.get_appointment_stats(volunteer_id=volunteer_id)
    return jsonify(stats)
