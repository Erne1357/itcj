"""
Servicio para manejar archivos de campos personalizados
"""
import os
from werkzeug.utils import secure_filename
from flask import current_app
from PIL import Image
import logging

logger = logging.getLogger(__name__)


class CustomFieldsFileService:
    """Maneja la subida y guardado de archivos para campos personalizados"""

    @staticmethod
    def save_custom_field_file(ticket_id: int, field_key: str, file, field_config: dict) -> str:
        """
        Guarda un archivo de campo personalizado

        Args:
            ticket_id: ID del ticket
            field_key: Clave del campo (ej: 'photo')
            file: Objeto FileStorage
            field_config: Configuración del campo desde la plantilla

        Returns:
            Ruta relativa al archivo guardado (ej: '/instance/apps/helpdesk/custom_fields/TK-42_photo.jpg')

        Raises:
            ValueError: Si el archivo es inválido
        """
        # Obtener directorio de subida
        upload_path = current_app.config.get('HELPDESK_CUSTOM_FIELDS_PATH',
                                            'instance/apps/helpdesk/custom_fields')

        # Crear directorio si no existe
        os.makedirs(upload_path, exist_ok=True)

        # Generar nombre seguro del archivo
        original_filename = secure_filename(file.filename)
        if '.' not in original_filename:
            raise ValueError('Archivo sin extensión')

        ext = original_filename.rsplit('.', 1)[1].lower()
        filename = f"TK-{ticket_id}_{field_key}.{ext}"
        filepath = os.path.join(upload_path, filename)

        # Verificar si es una imagen
        validation = field_config.get('validation', {})
        allowed_extensions = validation.get('allowedExtensions', [])

        is_image = ext in ['jpg', 'jpeg', 'png', 'gif', 'webp']

        if is_image:
            # Procesar como imagen (comprimir, redimensionar)
            CustomFieldsFileService._save_image(file, filepath)
        else:
            # Guardar como archivo regular
            file.save(filepath)

        # Retornar ruta relativa
        relative_path = f"/instance/apps/helpdesk/custom_fields/{filename}"
        logger.info(f"Archivo de campo personalizado guardado: {relative_path}")

        return relative_path

    @staticmethod
    def _save_image(file, filepath: str):
        """
        Guarda y optimiza una imagen

        Args:
            file: Objeto FileStorage con la imagen
            filepath: Ruta completa donde guardar el archivo
        """
        try:
            img = Image.open(file)

            # Convertir a RGB si es necesario
            if img.mode in ('RGBA', 'LA', 'P'):
                background = Image.new('RGB', img.size, (255, 255, 255))
                if img.mode == 'P':
                    img = img.convert('RGBA')
                if img.mode in ('RGBA', 'LA'):
                    background.paste(img, mask=img.split()[-1])
                img = background

            # Redimensionar si es muy grande
            max_dimensions = (1920, 1080)
            if img.width > max_dimensions[0] or img.height > max_dimensions[1]:
                img.thumbnail(max_dimensions, Image.Resampling.LANCZOS)

            # Guardar con compresión
            img.save(filepath, format='JPEG', quality=85, optimize=True)

            logger.info(f"Imagen optimizada y guardada: {filepath}")

        except Exception as e:
            logger.error(f"Error procesando imagen: {e}")
            # Fallback: guardar sin procesar
            file.seek(0)
            file.save(filepath)
            logger.warning(f"Imagen guardada sin procesar: {filepath}")
