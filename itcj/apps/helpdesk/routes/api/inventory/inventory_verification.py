"""
API para verificación física de equipos del inventario.
Permite registrar que un equipo fue inspeccionado presencialmente,
con o sin cambios de datos, y consultar el historial de verificaciones.

Acceso: Admin y Secretaría del Centro de Cómputo.
"""
from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify, g
from sqlalchemy import or_
from sqlalchemy.orm import joinedload
from itcj.core.extensions import db
from itcj.core.utils.decorators import api_app_required
from itcj.apps.helpdesk.models import InventoryItem, InventoryHistory, InventoryGroup
from itcj.apps.helpdesk.models.inventory_verification import InventoryVerification
from itcj.apps.helpdesk.services.inventory_service import InventoryService
from itcj.apps.helpdesk.services.inventory_group_service import InventoryGroupService

bp = Blueprint('inventory_verification', __name__)

# ─── Constantes ──────────────────────────────────────────────────────────────
_RECENT_DAYS = 30    # < 30 días → "recent"
_OUTDATED_DAYS = 90  # 30-90 días → "outdated"  |  > 90 días → "critical"


def _verification_status(last_verified_at):
    """Calcula el estado de verificación según la última fecha."""
    if not last_verified_at:
        return 'never'
    delta = (datetime.utcnow() - last_verified_at).days
    if delta < _RECENT_DAYS:
        return 'recent'
    if delta <= _OUTDATED_DAYS:
        return 'outdated'
    return 'critical'


# ─── GET /items/verification-status ─────────────────────────────────────────

@bp.route('/status', methods=['GET'])
@api_app_required('helpdesk', perms=['helpdesk.inventory.api.verify'])
def get_verification_status():
    """
    Lista equipos activos con su estado de verificación, paginados desde el servidor.

    Query params:
        - department_id: int (opcional)
        - category_id:   int (opcional)
        - status_filter: str — all | recent | outdated | critical | never
        - search:        str — número, marca o modelo
        - page:          int (default 1)
        - per_page:      int (default 50, máx 100)

    Returns:
        200: Página de equipos + stats globales (sin filtro de status)
    """
    department_id = request.args.get('department_id', type=int)
    category_id   = request.args.get('category_id',   type=int)
    status_filter = request.args.get('status_filter', 'all')
    search        = request.args.get('search', '').strip()
    page          = max(1, request.args.get('page',     1,  type=int))
    per_page      = min(100, max(1, request.args.get('per_page', 50, type=int)))

    # ── Filtros base compartidos por ambas queries ─────────────────────────
    base_filters = [InventoryItem.is_active == True]
    if department_id:
        base_filters.append(InventoryItem.department_id == department_id)
    if category_id:
        base_filters.append(InventoryItem.category_id == category_id)
    if search:
        term = f'%{search}%'
        base_filters.append(or_(
            InventoryItem.inventory_number.ilike(term),
            InventoryItem.brand.ilike(term),
            InventoryItem.model.ilike(term),
        ))

    # ── Query 1: Ligera — solo id + last_verified_at para stats + filtrado ─
    # Una sola query SQL, sin cargar relaciones ni columnas pesadas.
    light_rows = (
        db.session.query(InventoryItem.id, InventoryItem.last_verified_at)
        .filter(*base_filters)
        .order_by(
            InventoryItem.last_verified_at.asc().nullsfirst(),
            InventoryItem.inventory_number,
        )
        .all()
    )

    # Calcular stats y filtrar por verification_status en Python (O(n) simple)
    stats = {'total': 0, 'recent': 0, 'outdated': 0, 'critical': 0, 'never': 0}
    filtered = []  # [(item_id, verification_status)]

    for item_id, lva in light_rows:
        vs = _verification_status(lva)
        stats['total'] += 1
        stats[vs] += 1
        if status_filter == 'all' or vs == status_filter:
            filtered.append((item_id, vs))

    # Paginación sobre los IDs ya filtrados
    total_filtered = len(filtered)
    start     = (page - 1) * per_page
    page_rows = filtered[start:start + per_page]
    page_ids  = [r[0] for r in page_rows]
    vs_map    = {r[0]: r[1] for r in page_rows}

    if not page_ids:
        return jsonify({
            'success': True,
            'data': [],
            'pagination': {
                'total': total_filtered,
                'page': page,
                'per_page': per_page,
                'pages': max(1, (total_filtered + per_page - 1) // per_page),
            },
            'stats': stats,
        }), 200

    # ── Query 2: Completa — solo la página actual, con eager loading ───────
    # joinedload evita las N+1 queries al serializar relaciones.
    items = (
        InventoryItem.query
        .filter(InventoryItem.id.in_(page_ids))
        .options(
            joinedload(InventoryItem.category),
            joinedload(InventoryItem.department),
            joinedload(InventoryItem.last_verified_by),
            joinedload(InventoryItem.assigned_to_user),
            joinedload(InventoryItem.registered_by),
            joinedload(InventoryItem.assigned_by),
            joinedload(InventoryItem.group),
        )
        .all()
    )

    # Preservar el orden del filtrado
    item_map = {item.id: item for item in items}
    result = []
    for item_id in page_ids:
        if item_id not in item_map:
            continue
        item_data = item_map[item_id].to_dict(include_relations=True)
        item_data['verification_status'] = vs_map[item_id]
        result.append(item_data)

    return jsonify({
        'success': True,
        'data': result,
        'pagination': {
            'total': total_filtered,
            'page': page,
            'per_page': per_page,
            'pages': max(1, (total_filtered + per_page - 1) // per_page),
        },
        'stats': stats,
    }), 200


# ─── GET /items/<id>/verifications ───────────────────────────────────────────

@bp.route('/items/<int:item_id>/history', methods=['GET'])
@api_app_required('helpdesk', perms=['helpdesk.inventory.api.read.all'])
def get_item_verifications(item_id):
    """
    Historial de verificaciones de un equipo específico.

    Returns:
        200: Lista de verificaciones (más reciente primero)
        404: Equipo no encontrado
    """
    item = InventoryItem.query.get(item_id)
    if not item:
        return jsonify({'success': False, 'error': 'Equipo no encontrado'}), 404

    verifications = (
        InventoryVerification.query
        .filter_by(inventory_item_id=item_id)
        .order_by(InventoryVerification.verified_at.desc())
        .all()
    )

    return jsonify({
        'success': True,
        'data': [v.to_dict(include_relations=True) for v in verifications],
        'total': len(verifications),
    }), 200


# ─── POST /items/<id>/verify ─────────────────────────────────────────────────

@bp.route('/items/<int:item_id>/verify', methods=['POST'])
@api_app_required('helpdesk', perms=['helpdesk.inventory.api.verify'])
def verify_item(item_id):
    """
    Registrar verificación física de un equipo.

    Body (JSON):
        observations:       str  (opcional) — observaciones libres
        location_confirmed: str  (opcional) — ubicación vista al verificar

        # Cambios opcionales al equipo:
        location_detail:    str  (opcional) — nueva ubicación a guardar
        status:             str  (opcional) — nuevo estado (ACTIVE|MAINTENANCE|DAMAGED|LOST|RETIRED)
        brand:              str  (opcional)
        model:              str  (opcional)
        serial_number:      str  (opcional)

    Returns:
        200: Verificación registrada con éxito
        400: Datos inválidos
        404: Equipo no encontrado
    """
    user_id = int(g.current_user['sub'])
    ip      = request.remote_addr
    data    = request.get_json() or {}

    item = InventoryItem.query.get(item_id)
    if not item:
        return jsonify({'success': False, 'error': 'Equipo no encontrado'}), 404

    if not item.is_active:
        return jsonify({'success': False, 'error': 'El equipo está dado de baja'}), 400

    # ── Aplicar cambios opcionales ────────────────────────────────────────
    changes_applied = {}

    # Campos básicos (brand, model, serial_number, location_detail)
    basic_updatable = ['brand', 'model', 'serial_number', 'location_detail']
    update_payload = {}
    for field in basic_updatable:
        if field in data and data[field] is not None:
            old_val = getattr(item, field)
            new_val = str(data[field]).strip() if data[field] else None
            if old_val != new_val:
                update_payload[field] = new_val
                changes_applied[field] = {'old': old_val, 'new': new_val}

    # Especificaciones técnicas
    new_specs = data.get('specifications')
    if new_specs is not None and isinstance(new_specs, dict) and new_specs:
        old_specs = item.specifications or {}
        if old_specs != new_specs:
            update_payload['specifications'] = new_specs
            changes_applied['specifications'] = {'old': old_specs, 'new': new_specs}

    if update_payload:
        update_payload['update_notes'] = 'Cambio registrado durante verificación física'
        try:
            InventoryService.update_item(item_id, update_payload, user_id, ip)
            # update_item hace commit; re-fetch
            item = InventoryItem.query.get(item_id)
        except ValueError as e:
            return jsonify({'success': False, 'error': str(e)}), 400

    # Cambio de estado
    new_status = data.get('status')
    if new_status and new_status != item.status:
        valid_statuses = ['ACTIVE', 'MAINTENANCE', 'DAMAGED', 'LOST', 'RETIRED']
        if new_status not in valid_statuses:
            return jsonify({
                'success': False,
                'error': f'Estado inválido. Opciones: {", ".join(valid_statuses)}'
            }), 400
        try:
            old_status = item.status
            InventoryService.change_status(
                item_id, new_status, user_id,
                notes=f'Estado actualizado durante verificación física',
                ip_address=ip
            )
            item = InventoryItem.query.get(item_id)
            changes_applied['status'] = {'old': old_status, 'new': new_status}
        except ValueError as e:
            return jsonify({'success': False, 'error': str(e)}), 400

    # Cambio de grupo
    if 'group_id' in data:
        new_group_id = data['group_id']  # None = sin grupo, int = nuevo grupo
        old_group_id = item.group_id
        if new_group_id != old_group_id:
            try:
                if new_group_id is None and old_group_id is not None:
                    # Quitar del grupo
                    old_group = InventoryGroup.query.get(old_group_id)
                    InventoryGroupService.unassign_item_from_group(item_id, user_id)
                    changes_applied['group'] = {
                        'old': old_group.name if old_group else str(old_group_id),
                        'new': None,
                    }
                elif new_group_id is not None:
                    # Asignar a nuevo grupo (puede ser cambio de grupo también)
                    old_group = InventoryGroup.query.get(old_group_id) if old_group_id else None
                    if old_group_id is not None:
                        # Quitar del grupo anterior primero
                        InventoryGroupService.unassign_item_from_group(item_id, user_id)
                    InventoryGroupService.assign_item_to_group(item_id, new_group_id, user_id)
                    new_group = InventoryGroup.query.get(new_group_id)
                    changes_applied['group'] = {
                        'old': old_group.name if old_group else None,
                        'new': new_group.name if new_group else str(new_group_id),
                    }
                item = InventoryItem.query.get(item_id)
            except ValueError as e:
                return jsonify({'success': False, 'error': str(e)}), 400

    # ── Crear registro de verificación ────────────────────────────────────
    verification = InventoryVerification(
        inventory_item_id=item_id,
        verified_by_id=user_id,
        verified_at=datetime.utcnow(),
        location_confirmed=data.get('location_confirmed') or item.location_detail,
        status_found=data.get('status') or item.status,
        observations=data.get('observations'),
        changes_applied=changes_applied if changes_applied else None,
    )
    db.session.add(verification)

    # Actualizar campos de última verificación en el equipo
    item.last_verified_at     = verification.verified_at
    item.last_verified_by_id  = user_id

    # Registrar en historial del inventario
    history_entry = InventoryHistory(
        item_id=item_id,
        event_type='VERIFIED',
        old_value=None,
        new_value={
            'location_confirmed': verification.location_confirmed,
            'status_found':       verification.status_found,
            'changes':            changes_applied,
        },
        notes=verification.observations or 'Verificación física registrada',
        performed_by_id=user_id,
        ip_address=ip,
    )
    db.session.add(history_entry)

    db.session.commit()

    return jsonify({
        'success': True,
        'message': 'Verificación registrada correctamente',
        'verification': verification.to_dict(include_relations=True),
        'item': item.to_dict(include_relations=True),
        'verification_status': _verification_status(item.last_verified_at),
    }), 200
