"""
Servicio de validación de archivos para Help-Desk.
Valida magic bytes, extensiones, tamaños y comprime imágenes.
"""
import logging
import os
import io
import zipfile

from PIL import Image
from itcj2.config import get_settings

logger = logging.getLogger(__name__)

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


# Firmas de formatos que NUNCA deben aceptarse como CSV. La comprobación anterior
# ("¿decodifica como UTF-8?") dejaba pasar cualquier texto, y a la vez rechazaba
# CSVs legítimos exportados por Excel en cp1252 — estricta donde no importaba y
# laxa donde sí.
_BINARY_SIGNATURES = [
    b'PK\x03\x04',        # zip / ooxml / jar
    b'%PDF',              # pdf
    b'MZ',                # ejecutable windows
    b'\x7fELF',           # ejecutable linux
    b'\xd0\xcf\x11\xe0',  # ole2 (doc/xls)
    b'\x89PNG',
    b'\xff\xd8\xff',      # jpeg
    b'GIF8',
    b'\x1f\x8b',          # gzip
    b'#!',                # script con shebang
]

# Entradas que debe traer el contenedor OOXML de cada tipo. Un docx/xlsx es un ZIP,
# así que la firma PK\x03\x04 por sí sola acepta cualquier zip (incluido un jar).
_OOXML_REQUIRED_PREFIX = {
    'docx': 'word/',
    'xlsx': 'xl/',
}


def _validate_ooxml(file_storage, extension):
    """Verifica que el ZIP sea realmente un contenedor OOXML del tipo declarado."""
    try:
        file_storage.seek(0)
        with zipfile.ZipFile(file_storage) as zf:
            names = zf.namelist()
    except (zipfile.BadZipFile, OSError, ValueError) as exc:
        logger.info("validate_ooxml: zip ilegible (.%s): %s", extension, exc)
        return False, f'El contenido del archivo no corresponde a un archivo .{extension} válido'
    finally:
        try:
            file_storage.seek(0)
        except (OSError, ValueError):
            pass

    if '[Content_Types].xml' not in names:
        return False, f'El contenido del archivo no corresponde a un archivo .{extension} válido'

    prefix = _OOXML_REQUIRED_PREFIX[extension]
    if not any(n.startswith(prefix) for n in names):
        return False, f'El contenido del archivo no corresponde a un archivo .{extension} válido'

    return True, None


def _validate_csv_text(file_storage):
    """CSV es texto plano: se rechaza lo que traiga firma binaria conocida, byte
    nulo o demasiados caracteres de control. Se aceptan varias codificaciones —
    Excel exporta en cp1252 y el check anterior (solo UTF-8) tiraba esos archivos.
    """
    file_storage.seek(0)
    header = file_storage.read(8192)
    file_storage.seek(0)

    if not header:
        return False, 'El archivo está vacío'

    for sig in _BINARY_SIGNATURES:
        if header.startswith(sig):
            return False, 'El archivo CSV contiene datos binarios no válidos'

    if b'\x00' in header:
        return False, 'El archivo CSV contiene datos binarios no válidos'

    text = None
    for enc in ('utf-8-sig', 'utf-8', 'cp1252', 'latin-1'):
        try:
            text = header.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        return False, 'El archivo CSV contiene datos binarios no válidos'

    # latin-1 decodifica CUALQUIER byte, así que el filtro real es la proporción de
    # caracteres de control (fuera de tab/CR/LF) en el fragmento leído.
    control = sum(1 for ch in text if ord(ch) < 32 and ch not in '\t\r\n')
    if control > len(text) * 0.02:
        return False, 'El archivo CSV contiene datos binarios no válidos'

    return True, None


def _validate_image_decodes(file_storage, extension):
    """Un archivo con cabecera correcta pero cuerpo corrupto pasaba la validación y
    reventaba después, al comprimir. Pillow confirma que la imagen es real."""
    try:
        file_storage.seek(0)
        img = Image.open(file_storage)
        img.verify()
    except Exception as exc:
        logger.info("validate_image: imagen ilegible (.%s): %s", extension, exc)
        return False, f'El contenido del archivo no corresponde a un archivo .{extension} válido'
    finally:
        try:
            file_storage.seek(0)
        except (OSError, ValueError):
            pass
    return True, None


def validate_file_magic_bytes(file_storage, extension):
    """
    Valida que el CONTENIDO del archivo corresponda a la extensión declarada.

    No basta con la firma inicial: `webp` compartía prefijo con cualquier RIFF
    (avi/wav) y `docx`/`xlsx` aceptaban cualquier ZIP. Cada familia se verifica
    ahora con la comprobación que de verdad la distingue.

    Returns:
        tuple: (is_valid: bool, error_message: str|None)
    """
    if extension == 'csv':
        return _validate_csv_text(file_storage)

    expected_signatures = MAGIC_BYTES.get(extension)
    if expected_signatures is None:
        return True, None

    max_sig_len = max(len(sig) for sig in expected_signatures)
    # webp: "RIFF" son 4 bytes y el marcador real ("WEBP") vive en el offset 8.
    read_len = max(max_sig_len, 12)
    file_storage.seek(0)
    header = file_storage.read(read_len)
    file_storage.seek(0)

    if not header:
        return False, 'El archivo está vacío'

    if not any(header[:len(sig)] == sig for sig in expected_signatures):
        return False, f'El contenido del archivo no corresponde a un archivo .{extension} válido'

    if extension == 'webp' and header[8:12] != b'WEBP':
        return False, 'El contenido del archivo no corresponde a un archivo .webp válido'

    if extension in _OOXML_REQUIRED_PREFIX:
        return _validate_ooxml(file_storage, extension)

    if extension in IMAGE_EXTENSIONS:
        return _validate_image_decodes(file_storage, extension)

    # doc/xls comparten la firma OLE2 y distinguirlos exige parsear el compound
    # file. Se acepta la familia: ninguno de los dos se ejecuta ni se sirve, y
    # separarlos rechazaría archivos legítimos.
    return True, None


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
