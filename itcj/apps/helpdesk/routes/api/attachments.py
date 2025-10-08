from flask import request, jsonify, g, send_file
from werkzeug.utils import secure_filename
from itcj.core.utils.decorators import api_app_required
from itcj.apps.helpdesk.services import ticket_service
from itcj.apps.helpdesk.models import Attachment
from itcj.core.extensions import db
from datetime import datetime, timedelta
from . import attachments_api_bp
import os
import uuid
import logging
from PIL import Image
import io

logger = logging.getLogger(__name__)

# Configuración
UPLOAD_FOLDER = os.getenv('HELPDESK_UPLOAD_PATH', 'uploads/helpdesk')
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'pdf'}
ALLOWED_MIME_TYPES = {
    'image/png', 'image/jpeg', 'image/gif', 'image/webp',
    'application/pdf'
}


def allowed_file(filename):
    """Verifica si la extensión del archivo es permitida"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def compress_image(image_file, max_size=(1920, 1080), quality=85):
    """
    Comprime una imagen si es muy grande.
    
    Args:
        image_file: Archivo de imagen
        max_size: Tamaño máximo (ancho, alto)
        quality: Calidad de compresión (1-100)
    
    Returns:
        BytesIO con la imagen comprimida
    """
    try:
        img = Image.open(image_file)
        
        # Convertir a RGB si es necesario
        if img.mode in ('RGBA', 'LA', 'P'):
            background = Image.new('RGB', img.size, (255, 255, 255))
            if img.mode == 'P':
                img = img.convert('RGBA')
            if img.mode in ('RGBA', 'LA'):
                background.paste(img, mask=img.split()[-1])
            img = background
        
        # Redimensionar si es muy grande
        if img.width > max_size[0] or img.height > max_size[1]:
            img.thumbnail(max_size, Image.Resampling.LANCZOS)
        
        # Guardar en buffer
        output = io.BytesIO()
        img.save(output, format='JPEG', quality=quality, optimize=True)
        output.seek(0)
        
        return output
    except Exception as e:
        logger.error(f"Error al comprimir imagen: {e}")
        raise


# ==================== SUBIR ARCHIVO ====================
@attachments_api_bp.post('/ticket/<int:ticket_id>')
@api_app_required('helpdesk', perms=['helpdesk.own.read'])
def upload_attachment(ticket_id):
    """
    Sube un archivo adjunto a un ticket.
    
    Form data:
        file: Archivo a subir (imagen o PDF, máx 5MB)
    
    Returns:
        201: Archivo subido exitosamente
        400: Archivo inválido
        403: Sin permiso
        404: Ticket no encontrado
        413: Archivo muy grande
    """
    user_id = int(g.current_user['sub'])
    
    # Verificar que haya archivo
    if 'file' not in request.files:
        return jsonify({
            'error': 'no_file',
            'message': 'No se proporcionó ningún archivo'
        }), 400
    
    file = request.files['file']
    
    # Verificar que tenga nombre
    if file.filename == '':
        return jsonify({
            'error': 'empty_filename',
            'message': 'El archivo no tiene nombre'
        }), 400
    
    # Verificar extensión
    if not allowed_file(file.filename):
        return jsonify({
            'error': 'invalid_extension',
            'message': f'Solo se permiten archivos: {", ".join(ALLOWED_EXTENSIONS)}'
        }), 400
    
    try:
        # Verificar que pueda acceder al ticket
        ticket = ticket_service.get_ticket_by_id(ticket_id, user_id, check_permissions=True)
        
        # Verificar tamaño
        file.seek(0, os.SEEK_END)
        file_size = file.tell()
        file.seek(0)
        
        if file_size > MAX_FILE_SIZE:
            return jsonify({
                'error': 'file_too_large',
                'message': f'El archivo no debe exceder {MAX_FILE_SIZE // (1024*1024)}MB'
            }), 413
        
        # Generar nombre único
        original_filename = secure_filename(file.filename)
        file_ext = original_filename.rsplit('.', 1)[1].lower()
        unique_filename = f"{ticket_id}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}.{file_ext}"
        
        # Crear directorio si no existe
        ticket_folder = os.path.join(UPLOAD_FOLDER, str(ticket_id))
        os.makedirs(ticket_folder, exist_ok=True)
        
        filepath = os.path.join(ticket_folder, unique_filename)
        
        # Si es imagen, comprimir
        mime_type = file.content_type
        if mime_type and mime_type.startswith('image/'):
            try:
                compressed_image = compress_image(file)
                with open(filepath, 'wb') as f:
                    f.write(compressed_image.read())
                file_size = os.path.getsize(filepath)
                logger.info(f"Imagen comprimida guardada: {filepath}")
            except Exception as e:
                logger.warning(f"No se pudo comprimir imagen, guardando original: {e}")
                file.seek(0)
                file.save(filepath)
        else:
            # Guardar PDF directamente
            file.save(filepath)
        
        # Crear registro en DB
        attachment = Attachment(
            ticket_id=ticket_id,
            uploaded_by_id=user_id,
            filename=unique_filename,
            original_filename=original_filename,
            filepath=filepath,
            mime_type=mime_type,
            file_size=file_size
        )
        
        db.session.add(attachment)
        db.session.commit()
        
        logger.info(f"Archivo {original_filename} subido al ticket {ticket_id} por usuario {user_id}")
        
        return jsonify({
            'message': 'Archivo subido exitosamente',
            'attachment': attachment.to_dict()
        }), 201
        
    except Exception as e:
        logger.error(f"Error al subir archivo al ticket {ticket_id}: {e}")
        if os.path.exists(filepath):
            os.remove(filepath)
        raise


# ==================== LISTAR ARCHIVOS ====================
@attachments_api_bp.get('/ticket/<int:ticket_id>')
@api_app_required('helpdesk', perms=['helpdesk.own.read'])
def list_attachments(ticket_id):
    """
    Lista los archivos adjuntos de un ticket.
    
    Returns:
        200: Lista de archivos
        403: Sin permiso
        404: Ticket no encontrado
    """
    user_id = int(g.current_user['sub'])
    
    try:
        # Verificar que pueda acceder al ticket
        ticket = ticket_service.get_ticket_by_id(ticket_id, user_id, check_permissions=True)
        
        attachments = Attachment.query.filter_by(ticket_id=ticket_id).order_by(Attachment.uploaded_at.desc()).all()
        
        return jsonify({
            'ticket_id': ticket_id,
            'count': len(attachments),
            'attachments': [att.to_dict() for att in attachments]
        }), 200
        
    except Exception as e:
        logger.error(f"Error al listar archivos del ticket {ticket_id}: {e}")
        raise


# ==================== DESCARGAR ARCHIVO ====================
@attachments_api_bp.get('/<int:attachment_id>/download')
@api_app_required('helpdesk', perms=['helpdesk.own.read'])
def download_attachment(attachment_id):
    """
    Descarga un archivo adjunto.
    
    Returns:
        200: Archivo descargado
        403: Sin permiso
        404: Archivo no encontrado
    """
    user_id = int(g.current_user['sub'])
    
    try:
        attachment = Attachment.query.get(attachment_id)
        if not attachment:
            return jsonify({
                'error': 'not_found',
                'message': 'Archivo no encontrado'
            }), 404
        
        # Verificar que pueda acceder al ticket del archivo
        ticket = ticket_service.get_ticket_by_id(attachment.ticket_id, user_id, check_permissions=True)
        
        # Verificar que el archivo existe en el filesystem
        if not os.path.exists(attachment.filepath):
            logger.error(f"Archivo físico no encontrado: {attachment.filepath}")
            return jsonify({
                'error': 'file_not_found',
                'message': 'El archivo no existe en el servidor'
            }), 404
        
        return send_file(
            attachment.filepath,
            mimetype=attachment.mime_type,
            as_attachment=True,
            download_name=attachment.original_filename
        )
        
    except Exception as e:
        logger.error(f"Error al descargar archivo {attachment_id}: {e}")
        raise


# ==================== ELIMINAR ARCHIVO ====================
@attachments_api_bp.delete('/<int:attachment_id>')
@api_app_required('helpdesk', perms=['helpdesk.own.read'])
def delete_attachment(attachment_id):
    """
    Elimina un archivo adjunto (solo el uploader o admin).
    
    Returns:
        200: Archivo eliminado
        403: Sin permiso
        404: Archivo no encontrado
    """
    user_id = int(g.current_user['sub'])
    from itcj.core.services.authz_service import user_roles_in_app
    user_roles = user_roles_in_app(user_id, 'helpdesk')
    is_admin = 'admin' in user_roles
    
    try:
        attachment = Attachment.query.get(attachment_id)
        if not attachment:
            return jsonify({
                'error': 'not_found',
                'message': 'Archivo no encontrado'
            }), 404
        
        # Verificar permiso: admin o el que subió el archivo
        if not is_admin and attachment.uploaded_by_id != user_id:
            return jsonify({
                'error': 'forbidden',
                'message': 'Solo el uploader o admin pueden eliminar el archivo'
            }), 403
        
        # Eliminar archivo físico
        if os.path.exists(attachment.filepath):
            os.remove(attachment.filepath)
            logger.info(f"Archivo físico eliminado: {attachment.filepath}")
        
        # Eliminar registro de DB
        db.session.delete(attachment)
        db.session.commit()
        
        logger.info(f"Attachment {attachment_id} eliminado por usuario {user_id}")
        
        return jsonify({
            'message': 'Archivo eliminado exitosamente'
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error al eliminar archivo {attachment_id}: {e}")
        return jsonify({
            'error': 'delete_failed',
            'message': str(e)
        }), 500