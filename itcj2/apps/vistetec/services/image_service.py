"""Servicio de manejo de imágenes de prendas."""
import io
import os
import uuid
from datetime import datetime

from PIL import Image, ExifTags
from werkzeug.utils import secure_filename

ALLOWED_EXTENSIONS = {'jpg', 'jpeg', 'png', 'webp'}


def _allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def _compress_image(file, max_dimension=1920, quality=85):
    """
    Comprime y redimensiona una imagen con Pillow.

    Returns:
        tuple: (io.BytesIO con bytes comprimidos, extension str)
    """
    img = Image.open(file)

    try:
        orientation_key = None
        for key, val in ExifTags.TAGS.items():
            if val == 'Orientation':
                orientation_key = key
                break
        if orientation_key:
            exif = img._getexif()
            if exif and orientation_key in exif:
                orient = exif[orientation_key]
                if orient == 3:
                    img = img.rotate(180, expand=True)
                elif orient == 6:
                    img = img.rotate(270, expand=True)
                elif orient == 8:
                    img = img.rotate(90, expand=True)
    except (AttributeError, KeyError, IndexError):
        pass

    if img.mode in ('RGBA', 'P', 'LA'):
        if img.mode == 'P':
            img = img.convert('RGBA')
        background = Image.new('RGB', img.size, (255, 255, 255))
        background.paste(img, mask=img.split()[-1] if 'A' in img.mode else None)
        img = background
    elif img.mode != 'RGB':
        img = img.convert('RGB')

    width, height = img.size
    if width > max_dimension or height > max_dimension:
        ratio = min(max_dimension / width, max_dimension / height)
        new_size = (round(width * ratio), round(height * ratio))
        img = img.resize(new_size, Image.LANCZOS)

    output = io.BytesIO()
    img.save(output, format='JPEG', quality=quality, optimize=True)
    output.seek(0)

    return output, 'jpg'


def save_garment_image(file, garment_code):
    """
    Guarda la imagen de una prenda en el filesystem.
    Comprime automáticamente con Pillow antes de guardar.

    Returns:
        str: Ruta relativa de la imagen guardada.

    Raises:
        ValueError: Si el archivo no es válido.
    """
    from itcj2.config import get_settings
    s = get_settings()

    if not file or not file.filename:
        raise ValueError('No se proporcionó un archivo.')

    if not garment_code:
        raise ValueError('No se proporcionó el código de la prenda.')

    if not _allowed_file(file.filename):
        raise ValueError(
            f'Tipo de archivo no permitido. Usa: {", ".join(ALLOWED_EXTENSIONS)}'
        )

    max_size = s.VISTETEC_MAX_IMAGE_SIZE
    file.seek(0, os.SEEK_END)
    size = file.tell()
    file.seek(0)

    if size > max_size:
        max_mb = max_size / (1024 * 1024)
        raise ValueError(f'El archivo excede el tamaño máximo de {max_mb:.0f} MB.')

    try:
        compressed, ext = _compress_image(file)
    except Exception as e:
        raise ValueError(f'Error al procesar la imagen: {str(e)}')

    now = datetime.now()
    safe_code = secure_filename(garment_code)
    filename = f'{safe_code}.{ext}'
    relative_dir = os.path.join(str(now.year), f'{now.month:02d}')
    relative_path = os.path.join(relative_dir, filename)

    upload_path = s.VISTETEC_UPLOAD_PATH
    full_dir = os.path.join(upload_path, relative_dir)
    os.makedirs(full_dir, exist_ok=True)

    full_path = os.path.join(upload_path, relative_path)
    with open(full_path, 'wb') as f:
        f.write(compressed.read())

    return relative_path


def delete_garment_image(relative_path):
    """Elimina la imagen de una prenda del filesystem."""
    if not relative_path:
        return

    from itcj2.config import get_settings
    upload_path = get_settings().VISTETEC_UPLOAD_PATH
    full_path = os.path.join(upload_path, relative_path)

    if os.path.exists(full_path):
        os.remove(full_path)


def get_image_url(relative_path):
    """Retorna la URL para servir una imagen de prenda."""
    if not relative_path:
        return None
    return f'/api/vistetec/v2/garments/image/{relative_path}'
