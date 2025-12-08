from flask import request, jsonify, g
from itcj.core.utils.decorators import api_app_required
from itcj.apps.helpdesk.models import Category
from itcj.core.extensions import db
from datetime import datetime
from . import categories_api_bp
import logging

logger = logging.getLogger(__name__)


# ==================== LISTAR CATEGORÍAS ====================
@categories_api_bp.get('')
@api_app_required('helpdesk', perms=['helpdesk.categories.api.read'])
def list_categories():
    """
    Lista todas las categorías.
    
    Query params:
        - area: Filtrar por área ('DESARROLLO' o 'SOPORTE')
        - active: Filtrar por activas (true/false)
        - include_inactive: Incluir inactivas (true/false, default: false)
    
    Returns:
        200: Lista de categorías ordenadas por display_order
    """
    area = request.args.get('area')
    active_filter = request.args.get('active')
    include_inactive = request.args.get('include_inactive', 'false').lower() == 'true'
    
    try:
        query = Category.query
        
        # Filtrar por área
        if area:
            if area not in ['DESARROLLO', 'SOPORTE']:
                return jsonify({
                    'error': 'invalid_area',
                    'message': 'El área debe ser DESARROLLO o SOPORTE'
                }), 400
            query = query.filter_by(area=area)
        
        # Filtrar por activas/inactivas
        if active_filter is not None:
            is_active = active_filter.lower() == 'true'
            query = query.filter_by(is_active=is_active)
        elif not include_inactive:
            # Por defecto solo mostrar activas
            query = query.filter_by(is_active=True)
        
        # Ordenar por display_order
        categories = query.order_by(Category.area, Category.display_order).all()
        
        # Agrupar por área
        grouped = {
            'DESARROLLO': [],
            'SOPORTE': []
        }
        
        for cat in categories:
            grouped[cat.area].append(cat.to_dict())
        
        return jsonify({
            'categories': [cat.to_dict() for cat in categories],
            'grouped': grouped,
            'total': len(categories)
        }), 200
        
    except Exception as e:
        logger.error(f"Error al listar categorías: {e}")
        return jsonify({
            'error': 'list_failed',
            'message': str(e)
        }), 500


# ==================== OBTENER CATEGORÍA POR ID ====================
@categories_api_bp.get('/<int:category_id>')
@api_app_required('helpdesk', perms=['helpdesk.categories.api.read'])
def get_category(category_id):
    """
    Obtiene una categoría específica por ID.
    
    Returns:
        200: Categoría encontrada
        404: Categoría no encontrada
    """
    try:
        category = Category.query.get(category_id)
        
        if not category:
            return jsonify({
                'error': 'not_found',
                'message': 'Categoría no encontrada'
            }), 404
        
        # Contar tickets de esta categoría
        from itcj.apps.helpdesk.models import Ticket
        tickets_count = Ticket.query.filter_by(category_id=category_id).count()
        
        data = category.to_dict()
        data['tickets_count'] = tickets_count
        
        return jsonify({
            'category': data
        }), 200
        
    except Exception as e:
        logger.error(f"Error al obtener categoría {category_id}: {e}")
        return jsonify({
            'error': 'fetch_failed',
            'message': str(e)
        }), 500


# ==================== CREAR CATEGORÍA ====================
@categories_api_bp.post('')
@api_app_required('helpdesk', perms=['helpdesk.categories.api.update'])
def create_category():
    """
    Crea una nueva categoría.
    
    Body:
        {
            "area": "DESARROLLO" | "SOPORTE",
            "code": str,  # Código único (ej: 'dev_sii', 'sop_hardware')
            "name": str,  # Nombre visible (ej: 'SII', 'Hardware')
            "description": str (opcional),
            "display_order": int (opcional, default: se calcula automáticamente)
        }
    
    Returns:
        201: Categoría creada exitosamente
        400: Datos inválidos
        409: El código ya existe
    """
    data = request.get_json()
    user_id = int(g.current_user['sub'])
    
    # Validar campos requeridos
    required_fields = ['area', 'code', 'name']
    missing_fields = [field for field in required_fields if field not in data]
    
    if missing_fields:
        return jsonify({
            'error': 'missing_fields',
            'message': f'Faltan campos requeridos: {", ".join(missing_fields)}'
        }), 400
    
    # Validar área
    if data['area'] not in ['DESARROLLO', 'SOPORTE']:
        return jsonify({
            'error': 'invalid_area',
            'message': 'El área debe ser DESARROLLO o SOPORTE'
        }), 400
    
    # Validar código único
    existing = Category.query.filter_by(code=data['code']).first()
    if existing:
        return jsonify({
            'error': 'code_exists',
            'message': f'Ya existe una categoría con el código "{data["code"]}"'
        }), 409
    
    # Validar longitudes
    if len(data['code'].strip()) < 3:
        return jsonify({
            'error': 'invalid_code',
            'message': 'El código debe tener al menos 3 caracteres'
        }), 400
    
    if len(data['name'].strip()) < 2:
        return jsonify({
            'error': 'invalid_name',
            'message': 'El nombre debe tener al menos 2 caracteres'
        }), 400
    
    try:
        # Si no se proporciona display_order, calcular el siguiente
        if 'display_order' not in data or data['display_order'] is None:
            max_order = db.session.query(db.func.max(Category.display_order)).filter_by(
                area=data['area']
            ).scalar()
            display_order = (max_order or 0) + 1
        else:
            display_order = data['display_order']
        
        # Crear categoría
        category = Category(
            area=data['area'],
            code=data['code'].strip().lower(),
            name=data['name'].strip(),
            description=data.get('description', '').strip() if data.get('description') else None,
            display_order=display_order,
            is_active=True
        )
        
        db.session.add(category)
        db.session.commit()
        
        logger.info(f"Categoría '{category.name}' creada por usuario {user_id}")
        
        return jsonify({
            'message': 'Categoría creada exitosamente',
            'category': category.to_dict()
        }), 201
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error al crear categoría: {e}")
        return jsonify({
            'error': 'creation_failed',
            'message': str(e)
        }), 500


# ==================== ACTUALIZAR CATEGORÍA ====================
@categories_api_bp.patch('/<int:category_id>')
@api_app_required('helpdesk', perms=['helpdesk.categories.api.update'])
def update_category(category_id):
    """
    Actualiza una categoría existente.
    
    Body:
        {
            "name": str (opcional),
            "description": str (opcional),
            "display_order": int (opcional)
        }
    
    Nota: No se puede cambiar el área ni el código (son inmutables).
    
    Returns:
        200: Categoría actualizada
        400: Datos inválidos
        404: Categoría no encontrada
    """
    data = request.get_json()
    user_id = int(g.current_user['sub'])
    
    try:
        category = Category.query.get(category_id)
        
        if not category:
            return jsonify({
                'error': 'not_found',
                'message': 'Categoría no encontrada'
            }), 404
        
        # Actualizar campos permitidos
        if 'name' in data:
            name = data['name'].strip()
            if len(name) < 2:
                return jsonify({
                    'error': 'invalid_name',
                    'message': 'El nombre debe tener al menos 2 caracteres'
                }), 400
            category.name = name
        
        if 'description' in data:
            category.description = data['description'].strip() if data['description'] else None
        
        if 'display_order' in data:
            if not isinstance(data['display_order'], int) or data['display_order'] < 0:
                return jsonify({
                    'error': 'invalid_display_order',
                    'message': 'El display_order debe ser un número entero positivo'
                }), 400
            category.display_order = data['display_order']
        
        db.session.commit()
        
        logger.info(f"Categoría {category_id} actualizada por usuario {user_id}")
        
        return jsonify({
            'message': 'Categoría actualizada exitosamente',
            'category': category.to_dict()
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error al actualizar categoría {category_id}: {e}")
        return jsonify({
            'error': 'update_failed',
            'message': str(e)
        }), 500


# ==================== ACTIVAR/DESACTIVAR CATEGORÍA ====================
@categories_api_bp.post('/<int:category_id>/toggle')
@api_app_required('helpdesk', perms=['helpdesk.categories.api.update'])
def toggle_category(category_id):
    """
    Activa o desactiva una categoría.
    
    Body:
        {
            "is_active": bool
        }
    
    Returns:
        200: Estado actualizado
        400: Datos inválidos o hay tickets activos
        404: Categoría no encontrada
    """
    data = request.get_json()
    user_id = int(g.current_user['sub'])
    
    if 'is_active' not in data:
        return jsonify({
            'error': 'missing_field',
            'message': 'Se requiere el campo is_active'
        }), 400
    
    try:
        category = Category.query.get(category_id)
        
        if not category:
            return jsonify({
                'error': 'not_found',
                'message': 'Categoría no encontrada'
            }), 404
        
        new_status = data['is_active']
        
        # Si se quiere desactivar, verificar que no tenga tickets activos
        if not new_status and category.is_active:
            from itcj.apps.helpdesk.models import Ticket
            active_tickets = Ticket.query.filter(
                Ticket.category_id == category_id,
                Ticket.status.notin_(['CLOSED', 'CANCELED'])
            ).count()
            
            if active_tickets > 0:
                return jsonify({
                    'error': 'has_active_tickets',
                    'message': f'No se puede desactivar. Hay {active_tickets} ticket(s) activo(s) con esta categoría',
                    'active_tickets_count': active_tickets
                }), 400
        
        category.is_active = new_status
        db.session.commit()
        
        action = 'activada' if new_status else 'desactivada'
        logger.info(f"Categoría {category_id} {action} por usuario {user_id}")
        
        return jsonify({
            'message': f'Categoría {action} exitosamente',
            'category': category.to_dict()
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error al cambiar estado de categoría {category_id}: {e}")
        return jsonify({
            'error': 'toggle_failed',
            'message': str(e)
        }), 500


# ==================== REORDENAR CATEGORÍAS ====================
@categories_api_bp.post('/reorder')
@api_app_required('helpdesk', perms=['helpdesk.categories.api.update'])
def reorder_categories():
    """
    Reordena categorías (drag & drop).
    
    Body:
        {
            "area": "DESARROLLO" | "SOPORTE",
            "order": [
                {"id": 1, "display_order": 1},
                {"id": 3, "display_order": 2},
                {"id": 2, "display_order": 3}
            ]
        }
    
    Returns:
        200: Orden actualizado
        400: Datos inválidos
    """
    data = request.get_json()
    user_id = int(g.current_user['sub'])
    
    # Validar campos requeridos
    if 'area' not in data or 'order' not in data:
        return jsonify({
            'error': 'missing_fields',
            'message': 'Se requieren los campos: area, order'
        }), 400
    
    # Validar área
    if data['area'] not in ['DESARROLLO', 'SOPORTE']:
        return jsonify({
            'error': 'invalid_area',
            'message': 'El área debe ser DESARROLLO o SOPORTE'
        }), 400
    
    # Validar que order sea una lista
    if not isinstance(data['order'], list):
        return jsonify({
            'error': 'invalid_order',
            'message': 'El campo order debe ser un array'
        }), 400
    
    try:
        # Actualizar el display_order de cada categoría
        for item in data['order']:
            if 'id' not in item or 'display_order' not in item:
                return jsonify({
                    'error': 'invalid_order_item',
                    'message': 'Cada item debe tener id y display_order'
                }), 400
            
            category = Category.query.get(item['id'])
            
            if not category:
                return jsonify({
                    'error': 'category_not_found',
                    'message': f'Categoría con id {item["id"]} no encontrada'
                }), 404
            
            # Verificar que la categoría pertenezca al área especificada
            if category.area != data['area']:
                return jsonify({
                    'error': 'area_mismatch',
                    'message': f'La categoría {category.name} no pertenece al área {data["area"]}'
                }), 400
            
            category.display_order = item['display_order']
        
        db.session.commit()
        
        logger.info(f"Categorías del área {data['area']} reordenadas por usuario {user_id}")
        
        # Obtener categorías actualizadas
        categories = Category.query.filter_by(
            area=data['area']
        ).order_by(Category.display_order).all()
        
        return jsonify({
            'message': 'Orden actualizado exitosamente',
            'categories': [cat.to_dict() for cat in categories]
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error al reordenar categorías: {e}")
        return jsonify({
            'error': 'reorder_failed',
            'message': str(e)
        }), 500


# ==================== ELIMINAR CATEGORÍA ====================
@categories_api_bp.delete('/<int:category_id>')
@api_app_required('helpdesk', perms=['helpdesk.categories.api.update'])
def delete_category(category_id):
    """
    Elimina una categoría (soft delete, marca como inactiva).
    
    Solo se puede eliminar si no tiene tickets asociados.
    
    Returns:
        200: Categoría eliminada
        400: Tiene tickets asociados
        404: Categoría no encontrada
    """
    user_id = int(g.current_user['sub'])
    
    try:
        category = Category.query.get(category_id)
        
        if not category:
            return jsonify({
                'error': 'not_found',
                'message': 'Categoría no encontrada'
            }), 404
        
        # Verificar que no tenga tickets (ni siquiera cerrados)
        from itcj.apps.helpdesk.models import Ticket
        tickets_count = Ticket.query.filter_by(category_id=category_id).count()
        
        if tickets_count > 0:
            return jsonify({
                'error': 'has_tickets',
                'message': f'No se puede eliminar. Hay {tickets_count} ticket(s) asociado(s) a esta categoría',
                'tickets_count': tickets_count
            }), 400
        
        # Soft delete: marcar como inactiva
        category.is_active = False
        db.session.commit()
        
        logger.info(f"Categoría {category_id} eliminada (soft delete) por usuario {user_id}")
        
        return jsonify({
            'message': 'Categoría eliminada exitosamente'
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error al eliminar categoría {category_id}: {e}")
        return jsonify({
            'error': 'delete_failed',
            'message': str(e)
        }), 500


# ==================== ESTADÍSTICAS DE CATEGORÍAS ====================
@categories_api_bp.get('/stats')
@api_app_required('helpdesk', perms=['helpdesk.categories.api.read'])
def get_categories_stats():
    """
    Obtiene estadísticas de uso de categorías.
    
    Returns:
        200: Estadísticas por categoría
    """
    from itcj.apps.helpdesk.models import Ticket
    from sqlalchemy import func
    
    try:
        # Obtener conteo de tickets por categoría
        stats = db.session.query(
            Category.id,
            Category.name,
            Category.area,
            Category.is_active,
            func.count(Ticket.id).label('tickets_count'),
            func.count(
                db.case((Ticket.status.notin_(['CLOSED', 'CANCELED']), Ticket.id))
            ).label('active_tickets_count')
        ).outerjoin(
            Ticket, Ticket.category_id == Category.id
        ).group_by(
            Category.id, Category.name, Category.area, Category.is_active
        ).order_by(
            Category.area, Category.display_order
        ).all()
        
        # Formatear resultados
        categories_stats = []
        for stat in stats:
            categories_stats.append({
                'id': stat.id,
                'name': stat.name,
                'area': stat.area,
                'is_active': stat.is_active,
                'tickets_count': stat.tickets_count,
                'active_tickets_count': stat.active_tickets_count
            })
        
        # Agrupar por área
        grouped = {
            'DESARROLLO': [s for s in categories_stats if s['area'] == 'DESARROLLO'],
            'SOPORTE': [s for s in categories_stats if s['area'] == 'SOPORTE']
        }
        
        return jsonify({
            'categories': categories_stats,
            'grouped': grouped
        }), 200
        
    except Exception as e:
        logger.error(f"Error al obtener estadísticas de categorías: {e}")
        return jsonify({
            'error': 'stats_failed',
            'message': str(e)
        }), 500