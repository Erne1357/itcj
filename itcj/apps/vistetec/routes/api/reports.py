"""API de reportes y estadísticas."""

from datetime import datetime

from flask import jsonify, request

from itcj.core.utils.decorators import api_app_required
from itcj.apps.vistetec.services import reports_service
from itcj.apps.vistetec.routes.api import reports_api_bp as bp


def _parse_date(date_str):
    """Parsea fecha desde query param (YYYY-MM-DD)."""
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str, '%Y-%m-%d')
    except ValueError:
        return None


@bp.route('/dashboard', methods=['GET'])
@api_app_required('vistetec', perms=['vistetec.reports.api.dashboard'])
def dashboard_summary():
    """Resumen general para el dashboard."""
    summary = reports_service.get_dashboard_summary()
    return jsonify(summary)


@bp.route('/garments', methods=['GET'])
@api_app_required('vistetec', perms=['vistetec.reports.api.view'])
def garment_report():
    """Reporte de prendas."""
    date_from = _parse_date(request.args.get('date_from'))
    date_to = _parse_date(request.args.get('date_to'))

    report = reports_service.get_garment_report(date_from=date_from, date_to=date_to)
    return jsonify(report)


@bp.route('/donations', methods=['GET'])
@api_app_required('vistetec', perms=['vistetec.reports.api.view'])
def donation_report():
    """Reporte de donaciones."""
    date_from = _parse_date(request.args.get('date_from'))
    date_to = _parse_date(request.args.get('date_to'))

    report = reports_service.get_donation_report(date_from=date_from, date_to=date_to)
    return jsonify(report)


@bp.route('/appointments', methods=['GET'])
@api_app_required('vistetec', perms=['vistetec.reports.api.view'])
def appointment_report():
    """Reporte de citas."""
    date_from = _parse_date(request.args.get('date_from'))
    date_to = _parse_date(request.args.get('date_to'))

    report = reports_service.get_appointment_report(date_from=date_from, date_to=date_to)
    return jsonify(report)


@bp.route('/activity', methods=['GET'])
@api_app_required('vistetec', perms=['vistetec.reports.api.dashboard'])
def recent_activity():
    """Actividad reciente."""
    limit = request.args.get('limit', 15, type=int)
    activities = reports_service.get_recent_activity(limit=limit)
    return jsonify(activities)
