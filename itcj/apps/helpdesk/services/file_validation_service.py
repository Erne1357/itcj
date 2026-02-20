"""
Servicio de validación de archivos para Help-Desk.
Valida magic bytes, extensiones, tamaños y comprime imágenes.
"""
import os
import io
from PIL import Image
from itcj.config import Config

# Magic bytes para validar que el contenido corresponda a la extensión
MAGIC_BYTES = {
    # Imágenes
    'jpg': [b'\xff\xd8\xff'],
    'jpeg': [b'\xff\xd8\xff'],
    'png': [b'\x89PNG\r\n\x1a\n'],
    'gif': [b'GIF87a', b'GIF89a'],
    'webp': [b'RIFF'],
    # Documentos
    'pdf': [b'%PDF'],
    'xlsx': [b'PK\x03\x04'],       # ZIP-based (Open XML)
    'xls': [b'\xd0\xcf\x11\xe0'],  # OLE2 Compound Document
    'docx': [b'PK\x03\x04'],       # ZIP-based (Open XML)
    'doc': [b'\xd0\xcf\x11\xe0'],  # OLE2 Compound Document
    'csv': None,                     # Texto plano, no tiene magic bytes
}

IMAGE_EXTENSIONS = {'jpg', 'jpeg', 'png', 'gif', 'webp'}
ALL_ALLOWED_EXTENSIONS = Config.HELPDESK_ALLOWED_EXTENSIONS | Config.HELPDESK_ALLOWED_DOC_EXTENSIONS


def get_extension(filename):
    """Obtiene la extensión del archivo en minúsculas."""
    if not filename or '.' not in filename:
        return ''
    return filename.rsplit('.', 1)[1].lower()


def is_image(filename):
    """Verifica si el archivo es una imagen por extensión."""
    return get_extension(filename) in IMAGE_EXTENSIONS


def is_document(filename):
    """Verifica si el archivo es un documento por extensión."""
    return get_extension(filename) in Config.HELPDESK_ALLOWED_DOC_EXTENSIONS


def validate_file_magic_bytes(file_storage, extension):
    """
    Valida que los magic bytes del archivo correspondan a la extensión.

    Args:
        file_storage: Werkzeug FileStorage object
        extension: Extensión esperada (sin punto)

    Returns:
        tuple: (is_valid: bool, error_message: str|None)
    """
    expected_signatures = MAGIC_BYTES.get(extension)

    # CSV no tiene magic bytes, solo validamos que sea texto
    if expected_signatures is None:
        if extension == 'csv':
            try:
                header = file_storage.read(1024)
                file_storage.seek(0)
                header.decode('utf-8')
                return True, None
            except (UnicodeDecodeError, Exception):
                return False, 'El archivo CSV contiene datos binarios no válidos'
        return True, None

    # Leer los primeros bytes
    max_sig_len = max(len(sig) for sig in expected_signatures)
    header = file_storage.read(max_sig_len)
    file_storage.seek(0)

    if not header:
        return False, 'El archivo está vacío'

    for signature in expected_signatures:
        if header[:len(signature)] == signature:
            return True, None

    return False, f'El contenido del archivo no corresponde a un archivo .{extension} válido'


def validate_and_get_file_info(file_storage, allowed_extensions=None, max_size=None):
    """
    Pipeline completo de validación de archivo.

    Args:
        file_storage: Werkzeug FileStorage
        allowed_extensions: Set de extensiones permitidas (default: todas)
        max_size: Tamaño máximo en bytes (default: según tipo)

    Returns:
        tuple: (is_valid, file_info_or_error)
            Si válido: (True, {'extension': str, 'is_image': bool, 'size': int, 'original_filename': str})
            Si inválido: (False, error_message: str)
    """
    if not file_storage or not file_storage.filename:
        return False, 'No se proporcionó archivo'

    original_filename = file_storage.filename
    extension = get_extension(original_filename)

    if not extension:
        return False, 'El archivo no tiene extensión'

    if allowed_extensions is None:
        allowed_extensions = ALL_ALLOWED_EXTENSIONS

    if extension not in allowed_extensions:
        return False, f'Extensión .{extension} no permitida'

    # Determinar max_size según tipo si no se especificó
    if max_size is None:
        if extension in IMAGE_EXTENSIONS:
            max_size = Config.HELPDESK_MAX_FILE_SIZE
        else:
            max_size = Config.HELPDESK_MAX_DOCUMENT_SIZE

    # Validar tamaño
    file_storage.seek(0, os.SEEK_END)
    file_size = file_storage.tell()
    file_storage.seek(0)

    if file_size == 0:
        return False, 'El archivo está vacío'

    if file_size > max_size:
        max_mb = max_size / (1024 * 1024)
        return False, f'El archivo excede el límite de {max_mb:.0f}MB'

    # Validar magic bytes
    is_valid, error = validate_file_magic_bytes(file_storage, extension)
    if not is_valid:
        return False, error

    return True, {
        'extension': extension,
        'is_image': extension in IMAGE_EXTENSIONS,
        'size': file_size,
        'original_filename': original_filename,
    }


def compress_image_for_helpdesk(image_file, max_size=(1920, 1920), quality=80):
    """
    Comprime una imagen para el helpdesk.

    Args:
        image_file: Werkzeug FileStorage o BytesIO con la imagen
        max_size: Tupla (max_width, max_height)
        quality: Calidad JPEG (0-100)

    Returns:
        tuple: (BytesIO buffer con imagen comprimida, tamaño en bytes)
    """
    img = Image.open(image_file)

    # Convertir a RGB si es necesario (RGBA, P, etc.)
    if img.mode in ('RGBA', 'P', 'LA'):
        background = Image.new('RGB', img.size, (255, 255, 255))
        if img.mode == 'P':
            img = img.convert('RGBA')
        background.paste(img, mask=img.split()[-1] if 'A' in img.mode else None)
        img = background
    elif img.mode != 'RGB':
        img = img.convert('RGB')

    # Redimensionar si excede el máximo
    img.thumbnail(max_size, Image.LANCZOS)

    # Comprimir a JPEG
    buffer = io.BytesIO()
    img.save(buffer, format='JPEG', quality=quality, optimize=True)
    buffer.seek(0)

    return buffer, buffer.getbuffer().nbytes


def get_next_comment_image_number(ticket_id):
    """
    Obtiene el siguiente número consecutivo de imagen para comentarios del ticket.
    Busca en los attachments tipo 'comment' que sean imágenes.

    Args:
        ticket_id: ID del ticket

    Returns:
        int: Siguiente número consecutivo (1-based)
    """
    from itcj.apps.helpdesk.models.attachment import Attachment

    count = Attachment.query.filter_by(
        ticket_id=ticket_id,
        attachment_type='comment'
    ).filter(
        Attachment.mime_type.like('image/%')
    ).count()

    return count + 1
