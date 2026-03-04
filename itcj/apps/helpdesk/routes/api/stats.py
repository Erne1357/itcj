"""
Rutas para estadísticas y métricas del sistema de tickets.
"""
from flask import Blueprint, jsonify, g, request
from sqlalchemy import func, case, distinct
from itcj.core.utils.decorators import api_app_required
from itcj.apps.helpdesk.models.ticket import Ticket
from itcj.apps.helpdesk.models.assignment import Assignment
from itcj.apps.helpdesk.models.collaborator import TicketCollaborator
from itcj.core.services.authz_service import user_roles_in_app
from . import stats_api_bp as stats_bp
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


@stats_bp.get('/department/<int:department_id>')
@api_app_required('helpdesk', perms=['helpdesk.tickets.api.read.own'])
def get_department_stats(department_id):
    """
    Obtiene estadísticas agregadas de tickets de un departamento.
    Solo retorna conteos, no los tickets completos.
    """
    user_id = int(g.current_user['sub'])
    user_roles = user_roles_in_app(user_id, 'helpdesk')

    from itcj.core.services.authz_service import _get_users_with_position
    secretary_comp_center = _get_users_with_position(['secretary_comp_center'])

    can_view = False
    if 'admin' in user_roles or user_id in secretary_comp_center:
        can_view = True
    elif 'department_head' in user_roles:
        from itcj.core.models.position import UserPosition
        user_position = UserPosition.query.filter_by(user_id=user_id, is_active=True).first()
        if user_position and user_position.position:
            can_view = user_position.position.department_id == department_id

    if not can_view:
        return jsonify({'error': 'forbidden', 'message': 'Sin permiso para este departamento'}), 403

    try:
        query = Ticket.query.filter_by(requester_department_id=department_id)
        active_count   = query.filter(Ticket.status.in_(['PENDING', 'ASSIGNED', 'IN_PROGRESS'])).count()
        resolved_count = query.filter(Ticket.status.in_(['RESOLVED_SUCCESS', 'RESOLVED_FAILED', 'CLOSED'])).count()

        resolved_tickets = query.filter(Ticket.resolved_at.isnot(None), Ticket.created_at.isnot(None)).all()
        avg_hours = 0
        if resolved_tickets:
            total_h = sum((t.resolved_at - t.created_at).total_seconds() / 3600 for t in resolved_tickets)
            avg_hours = round(total_h / len(resolved_tickets), 1)

        rated_tickets = query.filter(Ticket.rating_attention.isnot(None)).all()
        satisfaction_percent = 0
        if rated_tickets:
            avg_r = sum(t.rating_attention for t in rated_tickets) / len(rated_tickets)
            satisfaction_percent = round((avg_r / 5) * 100, 1)

        return jsonify({'success': True, 'data': {
            'department_id': department_id,
            'total_tickets': query.count(),
            'active_tickets': active_count,
            'resolved_tickets': resolved_count,
            'avg_resolution_hours': avg_hours,
            'satisfaction_percent': satisfaction_percent,
            'rated_tickets_count': len(rated_tickets),
        }}), 200
    except Exception as e:
        logger.error(f"Error stats departamento {department_id}: {e}")
        return jsonify({'error': 'server_error', 'message': 'Error al obtener estadísticas'}), 500


@stats_bp.get('/technician')
@api_app_required('helpdesk', perms=['helpdesk.tickets.api.resolve'])
def get_technician_stats():
    """Obtiene estadísticas del técnico actual."""
    user_id = int(g.current_user['sub'])
    try:
        assigned_count    = Ticket.query.filter_by(assigned_to_user_id=user_id, status='ASSIGNED').count()
        in_progress_count = Ticket.query.filter_by(assigned_to_user_id=user_id, status='IN_PROGRESS').count()
        resolved_count    = Ticket.query.filter_by(assigned_to_user_id=user_id).filter(
            Ticket.status.in_(['RESOLVED_SUCCESS', 'RESOLVED_FAILED', 'CLOSED'])).count()

        resolved_tickets = Ticket.query.filter_by(assigned_to_user_id=user_id).filter(
            Ticket.resolved_at.isnot(None), Ticket.created_at.isnot(None)).all()
        avg_hours = 0
        if resolved_tickets:
            avg_hours = round(sum((t.resolved_at - t.created_at).total_seconds() / 3600
                                  for t in resolved_tickets) / len(resolved_tickets), 1)

        rated_tickets = Ticket.query.filter_by(assigned_to_user_id=user_id).filter(
            Ticket.rating_attention.isnot(None)).all()
        satisfaction_percent = 0
        if rated_tickets:
            avg_r = sum(t.rating_attention for t in rated_tickets) / len(rated_tickets)
            satisfaction_percent = round((avg_r / 5) * 100, 1)

        today_start = datetime.combine(datetime.today(), datetime.min.time())
        resolved_today = Ticket.query.filter_by(assigned_to_user_id=user_id).filter(
            Ticket.resolved_at >= today_start,
            Ticket.status.in_(['RESOLVED_SUCCESS', 'RESOLVED_FAILED', 'CLOSED'])).count()

        return jsonify({'success': True, 'data': {
            'assigned_count': assigned_count,
            'in_progress_count': in_progress_count,
            'resolved_count': resolved_count,
            'resolved_today_count': resolved_today,
            'avg_resolution_hours': avg_hours,
            'satisfaction_percent': satisfaction_percent,
        }}), 200
    except Exception as e:
        logger.error(f"Error stats técnico {user_id}: {e}")
        return jsonify({'error': 'server_error', 'message': 'Error al obtener estadísticas'}), 500


# ---------------------------------------------------------------------------
# NUEVO: /stats/global
# ---------------------------------------------------------------------------

@stats_bp.get('/global')
@api_app_required('helpdesk', perms=['helpdesk.stats.api.read'])
def get_global_stats():
    """KPIs globales del sistema con filtros de fecha."""
    period_id, preset, start_raw, end_raw, area = _parse_filters()

    try:
        q = _base_query(period_id, preset, start_raw, end_raw, area)
        tickets = q.all()

        exclude_outliers_param = request.args.get('exclude_outliers', '0') == '1'
        exclusion_info = None
        if exclude_outliers_param and tickets:
            tickets, exclusion_info = _exclude_outlier_tickets(tickets)

        total = len(tickets)

        # Conteos por status
        by_status = {}
        for s in ('PENDING', 'ASSIGNED', 'IN_PROGRESS', 'RESOLVED_SUCCESS',
                  'RESOLVED_FAILED', 'CLOSED', 'CANCELED'):
            by_status[s] = sum(1 for t in tickets if t.status == s)

        # Por área
        by_area = {'DESARROLLO': 0, 'SOPORTE': 0}
        for t in tickets:
            if t.area in by_area:
                by_area[t.area] += 1

        # Por prioridad
        by_priority = {'BAJA': 0, 'MEDIA': 0, 'ALTA': 0, 'URGENTE': 0}
        for t in tickets:
            if t.priority in by_priority:
                by_priority[t.priority] += 1

        # Tasas
        resolved_ok = by_status['RESOLVED_SUCCESS'] + by_status['CLOSED']
        resolved_fail = by_status['RESOLVED_FAILED']
        resolved_total = resolved_ok + resolved_fail
        resolution_rate = round(resolved_ok / resolved_total * 100, 1) if resolved_total else 0

        # SLA
        resolved_tickets = [t for t in tickets if t.resolved_at]
        sla_ok = sum(1 for t in resolved_tickets if _within_sla(t))
        sla_rate = round(sla_ok / len(resolved_tickets) * 100, 1) if resolved_tickets else 0

        # Tiempos
        res_hours = [_resolution_hours(t) for t in resolved_tickets if _resolution_hours(t) is not None]
        avg_resolution_hours = _safe_avg(res_hours)

        invested = [t.time_invested_minutes / 60 for t in tickets
                    if t.time_invested_minutes and t.time_invested_minutes > 0]
        avg_time_invested_hours = _safe_avg(invested)

        # Tiempo a asignar (created_at → primera asignación)
        assign_hours = []
        for t in tickets:
            first_asgn = Assignment.query.filter_by(ticket_id=t.id).order_by(Assignment.assigned_at).first()
            if first_asgn and first_asgn.assigned_at and t.created_at:
                h = (first_asgn.assigned_at - t.created_at).total_seconds() / 3600
                if h >= 0:
                    assign_hours.append(h)
        avg_time_to_assign_hours = _safe_avg(assign_hours)

        # Ratings
        rated = [t for t in tickets if t.rating_attention is not None]
        avg_rating_attention = _safe_avg([t.rating_attention for t in rated])
        avg_rating_speed     = _safe_avg([t.rating_speed for t in rated if t.rating_speed is not None])
        efficiency_rated = [t for t in tickets if t.rating_efficiency is not None]
        efficiency_rate  = round(sum(1 for t in efficiency_rated if t.rating_efficiency) /
                                 len(efficiency_rated) * 100, 1) if efficiency_rated else 0

        # Tendencia mensual (últimos 12 meses)
        now = datetime.utcnow()
        monthly_trend = []
        for i in range(11, -1, -1):
            month_start = (now.replace(day=1) - timedelta(days=i * 30)).replace(day=1, hour=0, minute=0, second=0)
            month_end   = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(seconds=1)
            count = sum(1 for t in tickets if t.created_at and month_start <= t.created_at <= month_end)
            monthly_trend.append({
                'month': month_start.strftime('%b %Y'),
                'count': count,
                'year': month_start.year,
                'month_num': month_start.month,
            })

        return jsonify({'success': True, 'data': {
            'total': total,
            'by_status': by_status,
            'by_area': by_area,
            'by_priority': by_priority,
            'resolution_rate': resolution_rate,
            'sla_compliance_rate': sla_rate,
            'avg_rating_attention': avg_rating_attention,
            'avg_rating_speed': avg_rating_speed,
            'efficiency_rate': efficiency_rate,
            'avg_resolution_hours': avg_resolution_hours,
            'avg_time_to_assign_hours': avg_time_to_assign_hours,
            'avg_time_invested_hours': avg_time_invested_hours,
            'rated_count': len(rated),
            'monthly_trend': monthly_trend,
            'periods': _get_periods_list(),
            'exclusion_info': exclusion_info,
        }}), 200
    except Exception as e:
        logger.error(f"Error stats globales: {e}", exc_info=True)
        return jsonify({'error': 'server_error', 'message': 'Error al obtener estadísticas globales'}), 500


# ---------------------------------------------------------------------------
# NUEVO: /stats/by-department
# ---------------------------------------------------------------------------

@stats_bp.get('/by-department')
@api_app_required('helpdesk', perms=['helpdesk.stats.api.read'])
def get_stats_by_department():
    """Métricas agrupadas por departamento solicitante."""
    period_id, preset, start_raw, end_raw, area = _parse_filters()

    try:
        q = _base_query(period_id, preset, start_raw, end_raw, area)
        tickets = q.all()

        exclude_outliers_param = request.args.get('exclude_outliers', '0') == '1'
        exclusion_info = None
        if exclude_outliers_param and tickets:
            tickets, exclusion_info = _exclude_outlier_tickets(tickets)

        # Agrupar por departamento
        dept_map = {}
        for t in tickets:
            dept_id = t.requester_department_id
            if dept_id not in dept_map:
                dept_map[dept_id] = []
            dept_map[dept_id].append(t)

        results = []
        for dept_id, dept_tickets in dept_map.items():
            # Nombre del departamento
            dept_name = 'Sin departamento'
            if dept_id:
                try:
                    from itcj.core.models.department import Department
                    dept = Department.query.get(dept_id)
                    if dept:
                        dept_name = dept.name
                except Exception:
                    pass

            total = len(dept_tickets)
            active   = sum(1 for t in dept_tickets if t.status in ('PENDING', 'ASSIGNED', 'IN_PROGRESS'))
            resolved = sum(1 for t in dept_tickets if t.status in ('RESOLVED_SUCCESS', 'RESOLVED_FAILED', 'CLOSED'))
            canceled = sum(1 for t in dept_tickets if t.status == 'CANCELED')

            res_tickets = [t for t in dept_tickets if t.resolved_at]
            res_hours   = [_resolution_hours(t) for t in res_tickets if _resolution_hours(t) is not None]
            avg_res_h   = _safe_avg(res_hours)

            rated  = [t for t in dept_tickets if t.rating_attention is not None]
            avg_rt = _safe_avg([t.rating_attention for t in rated])

            sla_ok   = sum(1 for t in res_tickets if _within_sla(t))
            sla_rate = round(sla_ok / len(res_tickets) * 100, 1) if res_tickets else 0

            # Categoría más frecuente
            cat_count = {}
            for t in dept_tickets:
                cat_count[t.category_id] = cat_count.get(t.category_id, 0) + 1
            top_cat_id = max(cat_count, key=cat_count.get) if cat_count else None
            top_cat_name = None
            if top_cat_id:
                try:
                    from itcj.apps.helpdesk.models.category import Category
                    cat = Category.query.get(top_cat_id)
                    if cat:
                        top_cat_name = cat.name
                except Exception:
                    pass

            results.append({
                'department_id': dept_id,
                'department_name': dept_name,
                'total': total,
                'active': active,
                'resolved': resolved,
                'canceled': canceled,
                'avg_resolution_hours': avg_res_h,
                'avg_rating': avg_rt,
                'sla_rate': sla_rate,
                'rated_count': len(rated),
                'top_category': top_cat_name,
            })

        results.sort(key=lambda x: x['total'], reverse=True)
        return jsonify({'success': True, 'data': results, 'exclusion_info': exclusion_info}), 200
    except Exception as e:
        logger.error(f"Error stats por departamento: {e}", exc_info=True)
        return jsonify({'error': 'server_error', 'message': 'Error al obtener estadísticas por departamento'}), 500


# ---------------------------------------------------------------------------
# NUEVO: /stats/by-technician
# ---------------------------------------------------------------------------

@stats_bp.get('/by-technician')
@api_app_required('helpdesk', perms=['helpdesk.stats.api.read'])
def get_stats_by_technician():
    """
    Métricas por técnico.
    Admin/Secretaría: todos los técnicos.
    Técnico: solo sus propios datos.
    """
    user_id = int(g.current_user['sub'])
    user_roles = user_roles_in_app(user_id, 'helpdesk')
    period_id, preset, start_raw, end_raw, area = _parse_filters()

    from itcj.core.services.authz_service import _get_users_with_position
    secretary_ids = _get_users_with_position(['secretary_comp_center'])
    is_admin_or_sec = 'admin' in user_roles or user_id in secretary_ids

    try:
        q = _base_query(period_id, preset, start_raw, end_raw, area)
        tickets = q.all()

        exclude_outliers_param = request.args.get('exclude_outliers', '0') == '1'
        exclusion_info = None
        if exclude_outliers_param and tickets:
            tickets, exclusion_info = _exclude_outlier_tickets(tickets)

        # Recopilar IDs de técnicos relevantes
        if is_admin_or_sec:
            tech_ids = set(t.assigned_to_user_id for t in tickets if t.assigned_to_user_id)
        else:
            tech_ids = {user_id}

        results = []
        for tid in tech_ids:
            # Tickets donde es asignado principal
            lead_tickets = [t for t in tickets if t.assigned_to_user_id == tid]
            # Tickets donde es colaborador
            collab_ids = set(
                tc.ticket_id for tc in
                TicketCollaborator.query.filter_by(user_id=tid).all()
            )
            collab_tickets = [t for t in tickets if t.id in collab_ids and t.assigned_to_user_id != tid]

            resolved   = [t for t in lead_tickets if t.status in ('RESOLVED_SUCCESS', 'RESOLVED_FAILED', 'CLOSED')]
            in_prog    = [t for t in lead_tickets if t.status == 'IN_PROGRESS']
            assigned_l = [t for t in lead_tickets if t.status == 'ASSIGNED']

            res_hours = [_resolution_hours(t) for t in resolved if _resolution_hours(t) is not None]
            avg_res_h = _safe_avg(res_hours)

            invested  = [t.time_invested_minutes / 60 for t in resolved
                         if t.time_invested_minutes and t.time_invested_minutes > 0]
            avg_inv_h = _safe_avg(invested)

            rated     = [t for t in lead_tickets if t.rating_attention is not None]
            avg_att   = _safe_avg([t.rating_attention for t in rated])
            avg_spd   = _safe_avg([t.rating_speed for t in rated if t.rating_speed is not None])
            eff_rated = [t for t in lead_tickets if t.rating_efficiency is not None]
            eff_rate  = round(sum(1 for t in eff_rated if t.rating_efficiency) /
                              len(eff_rated) * 100, 1) if eff_rated else 0

            sla_ok    = sum(1 for t in resolved if _within_sla(t))
            sla_rate  = round(sla_ok / len(resolved) * 100, 1) if resolved else 0

            # Nombre del técnico
            tech_name = f'Usuario #{tid}'
            try:
                from itcj.core.models.user import User
                u = User.query.get(tid)
                if u:
                    tech_name = u.full_name
            except Exception:
                pass

            results.append({
                'user_id': tid,
                'name': tech_name,
                'resolved': len(resolved),
                'in_progress': len(in_prog),
                'assigned': len(assigned_l),
                'tickets_as_lead': len(lead_tickets),
                'tickets_as_collaborator': len(collab_tickets),
                'avg_resolution_hours': avg_res_h,
                'avg_time_invested_hours': avg_inv_h,
                'avg_rating_attention': avg_att,
                'avg_rating_speed': avg_spd,
                'efficiency_rate': eff_rate,
                'sla_rate': sla_rate,
                'rated_count': len(rated),
            })

        results.sort(key=lambda x: x['resolved'], reverse=True)
        return jsonify({'success': True, 'data': results, 'is_admin': is_admin_or_sec,
                        'exclusion_info': exclusion_info}), 200
    except Exception as e:
        logger.error(f"Error stats por técnico: {e}", exc_info=True)
        return jsonify({'error': 'server_error', 'message': 'Error al obtener estadísticas por técnico'}), 500


# ---------------------------------------------------------------------------
# NUEVO: /stats/time-breakdown
# ---------------------------------------------------------------------------

@stats_bp.get('/time-breakdown')
@api_app_required('helpdesk', perms=['helpdesk.stats.api.read'])
def get_time_breakdown():
    """Desglose de tiempos: asignación, resolución, trabajo."""
    period_id, preset, start_raw, end_raw, area = _parse_filters()

    try:
        q = _base_query(period_id, preset, start_raw, end_raw, area)
        tickets = q.all()

        exclude_outliers_param = request.args.get('exclude_outliers', '0') == '1'
        exclusion_info = None
        if exclude_outliers_param and tickets:
            tickets, exclusion_info = _exclude_outlier_tickets(tickets)

        resolved_tickets = [t for t in tickets if t.resolved_at]

        # Tiempo a asignar
        assign_h = []
        for t in tickets:
            fa = Assignment.query.filter_by(ticket_id=t.id).order_by(Assignment.assigned_at).first()
            if fa and fa.assigned_at and t.created_at:
                h = (fa.assigned_at - t.created_at).total_seconds() / 3600
                if 0 <= h <= 720:  # máx 30 días
                    assign_h.append(round(h, 2))

        # Tiempo resolución (calendar)
        res_h = [round(_resolution_hours(t), 2) for t in resolved_tickets
                 if _resolution_hours(t) is not None and _resolution_hours(t) <= 720]

        # Tiempo invertido (técnico)
        inv_h = [round(t.time_invested_minutes / 60, 2) for t in tickets
                 if t.time_invested_minutes and t.time_invested_minutes > 0]

        # Por prioridad
        by_priority = []
        for prio in ('URGENTE', 'ALTA', 'MEDIA', 'BAJA'):
            p_tickets = [t for t in resolved_tickets if t.priority == prio]
            p_hours   = [_resolution_hours(t) for t in p_tickets if _resolution_hours(t) is not None]
            p_sla     = sum(1 for t in p_tickets if _within_sla(t))
            by_priority.append({
                'priority': prio,
                'count': len(p_tickets),
                'avg_resolution_hours': _safe_avg(p_hours),
                'sla_rate': round(p_sla / len(p_tickets) * 100, 1) if p_tickets else 0,
            })

        # Por área
        by_area = []
        for ar in ('DESARROLLO', 'SOPORTE'):
            a_tickets = [t for t in resolved_tickets if t.area == ar]
            a_hours   = [_resolution_hours(t) for t in a_tickets if _resolution_hours(t) is not None]
            a_inv     = [t.time_invested_minutes / 60 for t in a_tickets
                         if t.time_invested_minutes and t.time_invested_minutes > 0]
            by_area.append({
                'area': ar,
                'count': len(a_tickets),
                'avg_resolution_hours': _safe_avg(a_hours),
                'avg_time_invested_hours': _safe_avg(a_inv),
            })

        # Histograma de tiempo de resolución (buckets)
        buckets = [(0, 4, '<4h'), (4, 24, '4-24h'), (24, 72, '1-3d'), (72, 168, '3-7d'), (168, 9999, '>7d')]
        resolution_histogram = [
            {'range': label, 'count': sum(1 for h in res_h if lo <= h < hi)}
            for lo, hi, label in buckets
        ]

        return jsonify({'success': True, 'data': {
            'avg_time_to_assign_hours': _safe_avg(assign_h),
            'avg_resolution_hours': _safe_avg(res_h),
            'avg_time_invested_hours': _safe_avg(inv_h),
            'by_priority': by_priority,
            'by_area': by_area,
            'resolution_histogram': resolution_histogram,
            'assign_hours_raw': assign_h[:200],
            'resolution_hours_raw': res_h[:200],
            'exclusion_info': exclusion_info,
        }}), 200
    except Exception as e:
        logger.error(f"Error time-breakdown: {e}", exc_info=True)
        return jsonify({'error': 'server_error', 'message': 'Error al calcular tiempos'}), 500


# ---------------------------------------------------------------------------
# NUEVO: /stats/ratings-detail
# ---------------------------------------------------------------------------

@stats_bp.get('/ratings-detail')
@api_app_required('helpdesk', perms=['helpdesk.stats.api.read'])
def get_ratings_detail():
    """Distribución detallada de calificaciones."""
    period_id, preset, start_raw, end_raw, area = _parse_filters()

    try:
        q = _base_query(period_id, preset, start_raw, end_raw, area)
        tickets = q.all()

        exclude_outliers_param = request.args.get('exclude_outliers', '0') == '1'
        exclusion_info = None
        if exclude_outliers_param and tickets:
            tickets, exclusion_info = _exclude_outlier_tickets(tickets)

        rated = [t for t in tickets if t.rating_attention is not None]
        unrated_count = len(tickets) - len(rated)

        dist_attention = [sum(1 for t in rated if t.rating_attention == s) for s in range(1, 6)]
        dist_speed     = [sum(1 for t in rated if t.rating_speed == s) for s in range(1, 6)]
        eff_rated      = [t for t in tickets if t.rating_efficiency is not None]

        # Por técnico
        tech_map = {}
        for t in rated:
            tid = t.assigned_to_user_id
            if tid not in tech_map:
                tech_map[tid] = []
            tech_map[tid].append(t)

        by_technician = []
        for tid, t_list in tech_map.items():
            name = f'Usuario #{tid}'
            try:
                from itcj.core.models.user import User
                u = User.query.get(tid)
                if u:
                    name = u.full_name
            except Exception:
                pass
            by_technician.append({
                'name': name,
                'avg_attention': _safe_avg([t.rating_attention for t in t_list]),
                'avg_speed':     _safe_avg([t.rating_speed for t in t_list if t.rating_speed is not None]),
                'count': len(t_list),
            })
        by_technician.sort(key=lambda x: x['avg_attention'], reverse=True)

        # Por departamento
        dept_map = {}
        for t in rated:
            did = t.requester_department_id
            if did not in dept_map:
                dept_map[did] = []
            dept_map[did].append(t)

        by_department = []
        for did, d_list in dept_map.items():
            name = 'Sin dpto.'
            if did:
                try:
                    from itcj.core.models.department import Department
                    d = Department.query.get(did)
                    if d:
                        name = d.name
                except Exception:
                    pass
            by_department.append({
                'name': name,
                'avg_attention': _safe_avg([t.rating_attention for t in d_list]),
                'avg_speed':     _safe_avg([t.rating_speed for t in d_list if t.rating_speed is not None]),
                'count': len(d_list),
            })
        by_department.sort(key=lambda x: x['avg_attention'], reverse=True)

        # Comentarios recientes
        recent_comments = []
        for t in sorted(rated, key=lambda x: x.rated_at or datetime.min, reverse=True)[:15]:
            if t.rating_comment:
                recent_comments.append({
                    'ticket_number': t.ticket_number,
                    'rating': t.rating_attention,
                    'comment': t.rating_comment,
                    'date': t.rated_at.isoformat() if t.rated_at else None,
                })

        return jsonify({'success': True, 'data': {
            'avg_attention': _safe_avg([t.rating_attention for t in rated]),
            'avg_speed':     _safe_avg([t.rating_speed for t in rated if t.rating_speed is not None]),
            'efficiency_rate': round(sum(1 for t in eff_rated if t.rating_efficiency) /
                                     len(eff_rated) * 100, 1) if eff_rated else 0,
            'rated_count': len(rated),
            'unrated_count': unrated_count,
            'dist_attention': dist_attention,
            'dist_speed': dist_speed,
            'by_technician': by_technician,
            'by_department': by_department,
            'recent_comments': recent_comments,
            'exclusion_info': exclusion_info,
        }}), 200
    except Exception as e:
        logger.error(f"Error ratings-detail: {e}", exc_info=True)
        return jsonify({'error': 'server_error', 'message': 'Error al obtener calificaciones'}), 500


# ---------------------------------------------------------------------------
# NUEVO: /stats/analysis/outliers
# ---------------------------------------------------------------------------

@stats_bp.get('/analysis/outliers')
@api_app_required('helpdesk', perms=['helpdesk.stats.api.read'])
def get_outliers():
    """Detección de outliers por IQR en tiempo de resolución, calificación y tiempo invertido."""
    period_id, preset, start_raw, end_raw, area = _parse_filters()

    try:
        q = _base_query(period_id, preset, start_raw, end_raw, area)
        tickets = q.all()

        resolved = [t for t in tickets if t.resolved_at]

        def _ticket_summary(t):
            return {
                'id': t.id,
                'ticket_number': t.ticket_number,
                'title': t.title,
                'status': t.status,
                'priority': t.priority,
                'area': t.area,
                'resolution_hours': round(_resolution_hours(t), 2) if _resolution_hours(t) else None,
                'time_invested_hours': round(t.time_invested_minutes / 60, 2) if t.time_invested_minutes else None,
                'rating_attention': t.rating_attention,
                'created_at': t.created_at.isoformat() if t.created_at else None,
                'resolved_at': t.resolved_at.isoformat() if t.resolved_at else None,
            }

        # Outliers en tiempo de resolución (alto = lento)
        res_values = [(t, _resolution_hours(t)) for t in resolved if _resolution_hours(t) is not None]
        res_bounds  = _iqr_bounds([v for _, v in res_values])
        res_outliers = []
        if res_bounds:
            res_outliers = [_ticket_summary(t) for t, h in res_values
                            if h > res_bounds['upper_fence']]

        # Outliers en calificación (bajo = mala calificación)
        rated = [t for t in tickets if t.rating_attention is not None]
        rat_values = [t.rating_attention for t in rated]
        rat_bounds  = _iqr_bounds(rat_values)
        rat_outliers = []
        if rat_bounds:
            rat_outliers = [_ticket_summary(t) for t in rated
                            if t.rating_attention < rat_bounds['lower_fence']]

        # Outliers en tiempo invertido (alto)
        inv_tickets = [t for t in tickets if t.time_invested_minutes and t.time_invested_minutes > 0]
        inv_values  = [t.time_invested_minutes / 60 for t in inv_tickets]
        inv_bounds  = _iqr_bounds(inv_values)
        inv_outliers = []
        if inv_bounds:
            inv_outliers = [_ticket_summary(t) for t, h in zip(inv_tickets, inv_values)
                            if h > inv_bounds['upper_fence']]

        return jsonify({'success': True, 'data': {
            'resolution': {
                'bounds': res_bounds,
                'outlier_count': len(res_outliers),
                'tickets': res_outliers[:50],
            },
            'rating': {
                'bounds': rat_bounds,
                'outlier_count': len(rat_outliers),
                'tickets': rat_outliers[:50],
            },
            'time_invested': {
                'bounds': inv_bounds,
                'outlier_count': len(inv_outliers),
                'tickets': inv_outliers[:50],
            },
        }}), 200
    except Exception as e:
        logger.error(f"Error outliers: {e}", exc_info=True)
        return jsonify({'error': 'server_error', 'message': 'Error al calcular outliers'}), 500


# ---------------------------------------------------------------------------
# NUEVO: /stats/analysis/kmeans
# ---------------------------------------------------------------------------

@stats_bp.get('/analysis/kmeans')
@api_app_required('helpdesk', perms=['helpdesk.stats.api.read'])
def get_kmeans():
    """K-means sobre tickets resueltos agrupando por (tiempo resolución, calificación)."""
    period_id, preset, start_raw, end_raw, area = _parse_filters()
    k = request.args.get('k', 3, type=int)
    k = max(2, min(k, 6))  # entre 2 y 6
    exclude_outliers = request.args.get('exclude_outliers', '0') == '1'

    try:
        q = _base_query(period_id, preset, start_raw, end_raw, area)
        tickets = q.filter(Ticket.resolved_at.isnot(None),
                           Ticket.rating_attention.isnot(None)).all()

        exclusion_info = None
        if exclude_outliers and tickets:
            tickets, exclusion_info = _exclude_outlier_tickets(tickets)

        if len(tickets) < k:
            return jsonify({'success': True, 'data': {
                'k': k, 'clusters': [],
                'exclusion_info': exclusion_info,
                'message': f'Datos insuficientes. Se necesitan al menos {k} tickets calificados y resueltos.'
            }}), 200

        points = []
        valid_tickets = []
        for t in tickets:
            h = _resolution_hours(t)
            if h is not None and 0 < h <= 720:
                points.append((h, float(t.rating_attention)))
                valid_tickets.append(t)

        if len(valid_tickets) < k:
            return jsonify({'success': True, 'data': {
                'k': k, 'clusters': [],
                'message': f'Datos válidos insuficientes ({len(valid_tickets)} tickets).'
            }}), 200

        assignments = _kmeans_2d(points, k=k)

        # Agrupar resultados
        max_x = max(p[0] for p in points) or 1.0
        max_y = max(p[1] for p in points) or 1.0

        clusters = []
        for j in range(k):
            cluster_pts = [(points[i], valid_tickets[i]) for i, a in enumerate(assignments) if a == j]
            if not cluster_pts:
                continue
            c_hours   = [p[0] for p, _ in cluster_pts]
            c_ratings = [p[1] for p, _ in cluster_pts]
            centroid_h = _safe_avg(c_hours)
            centroid_r = _safe_avg(c_ratings)

            clusters.append({
                'id': j,
                'label': _cluster_label(centroid_h, centroid_r),
                'size': len(cluster_pts),
                'centroid_hours': centroid_h,
                'centroid_rating': centroid_r,
                'tickets': [{
                    'id': t.id,
                    'ticket_number': t.ticket_number,
                    'title': t.title[:60],
                    'priority': t.priority,
                    'area': t.area,
                    'resolution_hours': round(p[0], 2),
                    'rating': p[1],
                    'x': round(p[0] / max_x, 4),   # normalizado para scatter
                    'y': round(p[1] / max_y, 4),
                } for p, t in cluster_pts[:100]],
            })

        # Ordenar clusters por tiempo de resolución ascendente
        clusters.sort(key=lambda c: c['centroid_hours'])

        return jsonify({'success': True, 'data': {
            'k': k,
            'total_tickets': len(valid_tickets),
            'clusters': clusters,
            'exclusion_info': exclusion_info,
            'axes': {
                'x_label': 'Tiempo de resolución (horas)',
                'y_label': 'Calificación de atención (1-5)',
                'x_max': max_x,
                'y_max': max_y,
            }
        }}), 200
    except Exception as e:
        logger.error(f"Error k-means: {e}", exc_info=True)
        return jsonify({'error': 'server_error', 'message': 'Error al ejecutar clustering'}), 500


# ---------------------------------------------------------------------------
# NUEVO: /stats/analysis/distribution
# ---------------------------------------------------------------------------

@stats_bp.get('/analysis/distribution')
@api_app_required('helpdesk', perms=['helpdesk.stats.api.read'])
def get_distribution():
    """Histogramas y distribuciones de tickets."""
    period_id, preset, start_raw, end_raw, area = _parse_filters()
    exclude_outliers = request.args.get('exclude_outliers', '0') == '1'

    try:
        q = _base_query(period_id, preset, start_raw, end_raw, area)
        tickets = q.all()

        exclusion_info = None
        if exclude_outliers and tickets:
            tickets, exclusion_info = _exclude_outlier_tickets(tickets)

        resolved = [t for t in tickets if t.resolved_at]

        # Histograma tiempo de resolución
        buckets_res = [(0, 2, '<2h'), (2, 8, '2-8h'), (8, 24, '8-24h'),
                       (24, 72, '1-3d'), (72, 168, '3-7d'), (168, 9999, '>7d')]
        res_h_list = [_resolution_hours(t) for t in resolved if _resolution_hours(t) is not None]
        resolution_histogram = [
            {'range': label, 'count': sum(1 for h in res_h_list if lo <= h < hi), 'min_h': lo, 'max_h': hi}
            for lo, hi, label in buckets_res
        ]

        # Histograma tiempo invertido
        buckets_inv = [(0, 0.5, '<30min'), (0.5, 2, '30min-2h'), (2, 8, '2-8h'),
                       (8, 24, '8-24h'), (24, 9999, '>24h')]
        inv_h_list = [t.time_invested_minutes / 60 for t in tickets
                      if t.time_invested_minutes and t.time_invested_minutes > 0]
        time_invested_histogram = [
            {'range': label, 'count': sum(1 for h in inv_h_list if lo <= h < hi)}
            for lo, hi, label in buckets_inv
        ]

        # Por día de semana (creación)
        DAYS = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']
        by_weekday = [
            {'day': DAYS[i], 'day_idx': i,
             'count': sum(1 for t in tickets if t.created_at and t.created_at.weekday() == i)}
            for i in range(7)
        ]

        # Por hora del día
        by_hour = [
            {'hour': h, 'label': f'{h:02d}:00',
             'count': sum(1 for t in tickets if t.created_at and t.created_at.hour == h)}
            for h in range(24)
        ]

        # Por categoría
        cat_count = {}
        for t in tickets:
            cat_count[t.category_id] = cat_count.get(t.category_id, 0) + 1

        by_category = []
        for cat_id, count in sorted(cat_count.items(), key=lambda x: x[1], reverse=True)[:10]:
            name = f'Cat #{cat_id}'
            if cat_id:
                try:
                    from itcj.apps.helpdesk.models.category import Category
                    cat = Category.query.get(cat_id)
                    if cat:
                        name = cat.name
                except Exception:
                    pass
            by_category.append({'category': name, 'count': count})

        return jsonify({'success': True, 'data': {
            'resolution_histogram': resolution_histogram,
            'time_invested_histogram': time_invested_histogram,
            'by_weekday': by_weekday,
            'by_hour': by_hour,
            'by_category': by_category,
            'exclusion_info': exclusion_info,
        }}), 200
    except Exception as e:
        logger.error(f"Error distribution: {e}", exc_info=True)
        return jsonify({'error': 'server_error', 'message': 'Error al calcular distribuciones'}), 500


# ---------------------------------------------------------------------------
# NUEVO: /stats/analysis/trends
# ---------------------------------------------------------------------------

@stats_bp.get('/analysis/trends')
@api_app_required('helpdesk', perms=['helpdesk.stats.api.read'])
def get_trends():
    """Tendencias temporales: mensual, comparativo anual, SLA trend, heatmap."""
    period_id, preset, start_raw, end_raw, area = _parse_filters()
    exclude_outliers = request.args.get('exclude_outliers', '0') == '1'

    try:
        q = _base_query(period_id, preset, start_raw, end_raw, area)
        tickets = q.all()

        exclusion_info = None
        if exclude_outliers and tickets:
            tickets, exclusion_info = _exclude_outlier_tickets(tickets)

        now = datetime.utcnow()

        # Tendencia mensual (24 meses)
        monthly = []
        for i in range(23, -1, -1):
            # Calcular inicio del mes
            month_date = (now.replace(day=1) - timedelta(days=i * 30)).replace(day=1)
            m_start = month_date.replace(hour=0, minute=0, second=0, microsecond=0)
            if month_date.month == 12:
                m_end = month_date.replace(year=month_date.year + 1, month=1, day=1) - timedelta(seconds=1)
            else:
                m_end = month_date.replace(month=month_date.month + 1, day=1) - timedelta(seconds=1)

            m_tickets = [t for t in tickets if t.created_at and m_start <= t.created_at <= m_end]
            m_resolved = [t for t in m_tickets if t.resolved_at and m_start <= t.created_at <= m_end]
            m_res_h    = [_resolution_hours(t) for t in m_resolved if _resolution_hours(t) is not None]
            m_rated    = [t for t in m_tickets if t.rating_attention is not None]

            monthly.append({
                'month': m_start.strftime('%b %Y'),
                'year': m_start.year,
                'month_num': m_start.month,
                'created': len(m_tickets),
                'resolved': len(m_resolved),
                'avg_resolution_hours': _safe_avg(m_res_h),
                'avg_rating': _safe_avg([t.rating_attention for t in m_rated]),
                'sla_rate': round(sum(1 for t in m_resolved if _within_sla(t)) /
                                  len(m_resolved) * 100, 1) if m_resolved else 0,
            })

        # Comparativo año actual vs anterior
        this_year = now.year
        prev_year = this_year - 1
        yoy = []
        for m in range(1, 13):
            this_y_count = sum(1 for t in tickets if t.created_at and
                               t.created_at.year == this_year and t.created_at.month == m)
            prev_y_count = sum(1 for t in tickets if t.created_at and
                               t.created_at.year == prev_year and t.created_at.month == m)
            yoy.append({
                'month': m,
                'month_label': datetime(2000, m, 1).strftime('%b'),
                'this_year': this_y_count,
                'prev_year': prev_y_count,
            })

        # Heatmap semana × hora (últimos 90 días, todos los tickets)
        ninety_days_ago = now - timedelta(days=90)
        recent = [t for t in tickets if t.created_at and t.created_at >= ninety_days_ago]
        heatmap = []
        DAYS = ['Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb', 'Dom']
        for dow in range(7):
            for h in range(24):
                count = sum(1 for t in recent
                            if t.created_at and t.created_at.weekday() == dow and t.created_at.hour == h)
                heatmap.append({'dow': dow, 'hour': h, 'day': DAYS[dow], 'count': count})

        return jsonify({'success': True, 'data': {
            'monthly': monthly,
            'yoy': yoy,
            'heatmap': heatmap,
            'exclusion_info': exclusion_info,
        }}), 200
    except Exception as e:
        logger.error(f"Error trends: {e}", exc_info=True)
        return jsonify({'error': 'server_error', 'message': 'Error al calcular tendencias'}), 500
