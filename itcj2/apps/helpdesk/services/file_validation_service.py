"""
Servicio de validación de archivos para Help-Desk.
Valida magic bytes, extensiones, tamaños y comprime imágenes.
"""
import os
import io
from PIL import Image
from itcj2.config import get_settings

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
    'xlsx': [b'PK\x03\x04'],
    'xls': [b'\xd0\xcf\x11\xe0'],
    'docx': [b'PK\x03\x04'],
    'doc': [b'\xd0\xcf\x11\xe0'],
    'csv': None,
}

IMAGE_EXTENSIONS = {'jpg', 'jpeg', 'png', 'gif', 'webp'}


def _get_allowed_extensions():
    s = get_settings()
    return set(s.HELPDESK_ALLOWED_EXTENSIONS.split(','))


def _get_allowed_doc_extensions():
    s = get_settings()
    return set(s.HELPDESK_ALLOWED_DOC_EXTENSIONS.split(','))


def _get_all_allowed_extensions():
    return _get_allowed_extensions() | _get_allowed_doc_extensions()


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
    return get_extension(filename) in _get_allowed_doc_extensions()


def validate_file_magic_bytes(file_storage, extension):
    """
    Valida que los magic bytes del archivo correspondan a la extensión.

    Returns:
        tuple: (is_valid: bool, error_message: str|None)
    """
    expected_signatures = MAGIC_BYTES.get(extension)

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

    Acepta tanto FastAPI UploadFile (tiene .filename y .file) como
    objetos file-like de Werkzeug (tienen .filename y .seek/.read directamente).

    Returns:
        tuple: (is_valid, file_info_or_error)
    """
    settings = get_settings()

    if not file_storage:
        return False, 'No se proporcionó archivo'

    # Normalizar: FastAPI UploadFile tiene .filename en sí mismo pero los métodos
    # seek/read/tell están en .file (SpooledTemporaryFile). Werkzeug FileStorage
    # los tiene directamente sobre sí mismo.
    original_filename = getattr(file_storage, 'filename', None)
    if not original_filename:
        return False, 'No se proporcionó archivo'

    file_handle = getattr(file_storage, 'file', file_storage)

    extension = get_extension(original_filename)

    if not extension:
        return False, 'El archivo no tiene extensión'

    if allowed_extensions is None:
        allowed_extensions = _get_all_allowed_extensions()

    if extension not in allowed_extensions:
        return False, f'Extensión .{extension} no permitida'

    if max_size is None:
        if extension in IMAGE_EXTENSIONS:
            max_size = settings.HELPDESK_MAX_FILE_SIZE
        else:
            max_size = settings.HELPDESK_MAX_DOCUMENT_SIZE

    file_handle.seek(0, os.SEEK_END)
    file_size = file_handle.tell()
    file_handle.seek(0)

    if file_size == 0:
        return False, 'El archivo está vacío'

    if file_size > max_size:
        max_mb = max_size / (1024 * 1024)
        return False, f'El archivo excede el límite de {max_mb:.0f}MB'

    is_valid, error = validate_file_magic_bytes(file_handle, extension)
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

    Returns:
        tuple: (BytesIO buffer con imagen comprimida, tamaño en bytes)
    """
    img = Image.open(image_file)

    if img.mode in ('RGBA', 'P', 'LA'):
        background = Image.new('RGB', img.size, (255, 255, 255))
        if img.mode == 'P':
            img = img.convert('RGBA')
        background.paste(img, mask=img.split()[-1] if 'A' in img.mode else None)
        img = background
    elif img.mode != 'RGB':
        img = img.convert('RGB')

    img.thumbnail(max_size, Image.LANCZOS)

    buffer = io.BytesIO()
    img.save(buffer, format='JPEG', quality=quality, optimize=True)
    buffer.seek(0)

    return buffer, buffer.getbuffer().nbytes


def get_next_comment_image_number(db, ticket_id):
    """
    Obtiene el siguiente número consecutivo de imagen para comentarios del ticket.

    Args:
        db: Sesión de SQLAlchemy
        ticket_id: ID del ticket

    Returns:
        int: Siguiente número consecutivo (1-based)
    """
    from itcj2.apps.helpdesk.models.attachment import Attachment

    count = db.query(Attachment).filter_by(
        ticket_id=ticket_id,
        attachment_type='comment'
    ).filter(
        Attachment.mime_type.like('image/%')
    ).count()

    return count + 1
