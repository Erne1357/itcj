"""
Servicio para manejar archivos de campos personalizados
"""
import os
from werkzeug.utils import secure_filename
from PIL import Image
import logging

logger = logging.getLogger(__name__)


class CustomFieldsFileService:
    """Maneja la subida y guardado de archivos para campos personalizados"""

    @staticmethod
    def save_custom_field_file(ticket_id: int, field_key: str, file, field_config: dict) -> str:
        """
        Guarda un archivo de campo personalizado.

        Returns:
            Ruta relativa al archivo guardado
        """
        from itcj2.config import get_settings
        s = get_settings()
        upload_path = os.path.join(s.INSTANCE_PATH, 'apps', 'helpdesk', 'custom_fields')

        os.makedirs(upload_path, exist_ok=True)

        original_filename = secure_filename(file.filename)
        if '.' not in original_filename:
            raise ValueError('Archivo sin extensión')

        ext = original_filename.rsplit('.', 1)[1].lower()
        filename = f"TK-{ticket_id}_{field_key}.{ext}"
        filepath = os.path.join(upload_path, filename)

        is_image = ext in ['jpg', 'jpeg', 'png', 'gif', 'webp']

        raw = file.file
        if is_image:
            CustomFieldsFileService._save_image(raw, filepath)
        else:
            with open(filepath, 'wb') as f:
                f.write(raw.read())

        relative_path = f"/instance/apps/helpdesk/custom_fields/{filename}"
        logger.info(f"Archivo de campo personalizado guardado: {relative_path}")

        return relative_path

    @staticmethod
    def _save_image(file, filepath: str):
        """
        Guarda y optimiza una imagen.
        """
        try:
            img = Image.open(file)

            if img.mode in ('RGBA', 'LA', 'P'):
                background = Image.new('RGB', img.size, (255, 255, 255))
                if img.mode == 'P':
                    img = img.convert('RGBA')
                if img.mode in ('RGBA', 'LA'):
                    background.paste(img, mask=img.split()[-1])
                img = background

            max_dimensions = (1920, 1080)
            if img.width > max_dimensions[0] or img.height > max_dimensions[1]:
                img.thumbnail(max_dimensions, Image.Resampling.LANCZOS)

            img.save(filepath, format='JPEG', quality=85, optimize=True)

            logger.info(f"Imagen optimizada y guardada: {filepath}")

        except Exception as e:
            logger.error(f"Error procesando imagen: {e}")
            file.seek(0)
            with open(filepath, 'wb') as f:
                f.write(file.read())
            logger.warning(f"Imagen guardada sin procesar: {filepath}")
