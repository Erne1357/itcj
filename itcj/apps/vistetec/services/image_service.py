"""Servicio de manejo de imágenes de prendas."""
import os
import uuid
from datetime import datetime
from flask import current_app
from werkzeug.utils import secure_filename


ALLOWED_EXTENSIONS = {'jpg', 'jpeg', 'png', 'webp'}


def _allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def save_garment_image(file):
    """
    Guarda la imagen de una prenda en el filesystem.

    Args:
        file: FileStorage object del request.

    Returns:
        str: Ruta relativa de la imagen guardada (para almacenar en BD).

    Raises:
        ValueError: Si el archivo no es válido.
    """
    if not file or not file.filename:
        raise ValueError('No se proporcionó un archivo.')

    if not _allowed_file(file.filename):
        raise ValueError(
            f'Tipo de archivo no permitido. Usa: {", ".join(ALLOWED_EXTENSIONS)}'
        )

    # Verificar tamaño
    max_size = current_app.config.get('VISTETEC_MAX_IMAGE_SIZE', 3 * 1024 * 1024)
    file.seek(0, os.SEEK_END)
    size = file.tell()
    file.seek(0)

    if size > max_size:
        max_mb = max_size / (1024 * 1024)
        raise ValueError(f'El archivo excede el tamaño máximo de {max_mb:.0f} MB.')

    # Generar ruta: YYYY/MM/garment_<uuid>.<ext>
    now = datetime.now()
    ext = file.filename.rsplit('.', 1)[1].lower()
    filename = f'garment_{uuid.uuid4().hex[:8]}.{ext}'
    relative_dir = os.path.join(str(now.year), f'{now.month:02d}')
    relative_path = os.path.join(relative_dir, filename)

    upload_path = current_app.config['VISTETEC_UPLOAD_PATH']
    full_dir = os.path.join(upload_path, relative_dir)
    os.makedirs(full_dir, exist_ok=True)

    full_path = os.path.join(upload_path, relative_path)
    file.save(full_path)

    return relative_path


def delete_garment_image(relative_path):
    """
    Elimina la imagen de una prenda del filesystem.

    Args:
        relative_path: Ruta relativa almacenada en la BD.
    """
    if not relative_path:
        return

    upload_path = current_app.config['VISTETEC_UPLOAD_PATH']
    full_path = os.path.join(upload_path, relative_path)

    if os.path.exists(full_path):
        os.remove(full_path)


def get_image_url(relative_path):
    """
    Retorna la URL para servir una imagen de prenda.

    Args:
        relative_path: Ruta relativa almacenada en la BD.

    Returns:
        str or None: URL de la imagen.
    """
    if not relative_path:
        return None
    return f'/api/vistetec/v1/garments/image/{relative_path}'
