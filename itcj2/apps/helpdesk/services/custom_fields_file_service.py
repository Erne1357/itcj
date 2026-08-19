"""
Servicio para manejar archivos de campos personalizados
"""
import os
from werkzeug.utils import secure_filename
from PIL import Image
import logging

logger = logging.getLogger(__name__)

# Mismo criterio que HELPDESK_ALLOWED_EXTENSIONS + los documentos que la UI de
# campos personalizados permite adjuntar. Sin .html/.svg/.js: custom_fields/ vive
# bajo instance/, que es servible.
_ALLOWED_EXTENSIONS = {
    'jpg', 'jpeg', 'png', 'gif', 'webp',
    'pdf', 'doc', 'docx', 'xls', 'xlsx', 'csv', 'txt',
}


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

        # Allowlist de extensión: antes se aceptaba cualquiera (este path NO pasa
        # por file_validation_service, a diferencia de los adjuntos normales), así
        # que se podía dejar un .html/.svg en un directorio que se sirve por HTTP.
        if ext not in _ALLOWED_EXTENSIONS:
            raise ValueError(
                f'Extensión no permitida. Solo se aceptan: {", ".join(sorted(_ALLOWED_EXTENSIONS))}'
            )

        # Límite de tamaño: este path tampoco lo aplicaba.
        raw_probe = file.file
        raw_probe.seek(0, 2)
        size = raw_probe.tell()
        raw_probe.seek(0)
        if size > s.HELPDESK_MAX_DOCUMENT_SIZE:
            raise ValueError(
                f'El archivo no debe exceder {s.HELPDESK_MAX_DOCUMENT_SIZE // (1024 * 1024)}MB'
            )

        # field_key viene de la plantilla de campos de la categoría, que un usuario
        # con helpdesk.categories.api.update edita libremente; sin sanear, un key
        # con "../" escribía fuera de custom_fields/. secure_filename lo aplana.
        safe_key = secure_filename(str(field_key)) or 'campo'
        filename = f"TK-{ticket_id}_{safe_key}.{ext}"
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
