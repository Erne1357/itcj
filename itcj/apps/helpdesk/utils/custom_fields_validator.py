"""
Validador para campos personalizados de categorías de tickets
"""
from typing import Dict, List, Tuple
from werkzeug.datastructures import FileStorage
import logging

logger = logging.getLogger(__name__)


class CustomFieldsValidator:
    """Valida campos personalizados contra la plantilla de campo de la categoría"""

    @staticmethod
    def validate(field_template: Dict, custom_fields: Dict, files: Dict = None) -> Tuple[bool, List[str]]:
        """
        Valida campos personalizados contra la plantilla

        Args:
            field_template: Plantilla field_template JSON de la categoría
            custom_fields: Valores de campos personalizados enviados
            files: Archivos subidos (para campos tipo file)

        Returns:
            (is_valid, errors) tupla con resultado de validación y lista de errores
        """
        errors = []

        if not field_template or not field_template.get('enabled'):
            return True, []

        fields_config = field_template.get('fields', [])

        for field_config in fields_config:
            field_key = field_config['key']
            field_type = field_config['type']
            is_required = field_config.get('required', False)
            visible_when = field_config.get('visible_when')

            # Verificar condiciones de visibilidad
            if visible_when:
                if not CustomFieldsValidator._check_visibility(visible_when, custom_fields):
                    continue  # Campo no visible, saltar validación

            # Obtener valor del campo
            if field_type == 'file':
                field_value = files.get(field_key) if files else None
            else:
                field_value = custom_fields.get(field_key)

            # Validar requerido
            if is_required:
                if field_type == 'file':
                    if not field_value:
                        errors.append(f"El campo '{field_config['label']}' es obligatorio")
                        continue
                elif field_type == 'checkbox':
                    if field_value is not True:
                        errors.append(f"Debe marcar '{field_config['label']}'")
                        continue
                else:
                    if not field_value or (isinstance(field_value, str) and not field_value.strip()):
                        errors.append(f"El campo '{field_config['label']}' es obligatorio")
                        continue

            # Saltar validación adicional si el campo está vacío y no es requerido
            if not field_value:
                continue

            # Validación específica por tipo
            if field_type == 'text':
                errors.extend(CustomFieldsValidator._validate_text(field_value, field_config))
            elif field_type == 'textarea':
                errors.extend(CustomFieldsValidator._validate_textarea(field_value, field_config))
            elif field_type == 'select':
                errors.extend(CustomFieldsValidator._validate_select(field_value, field_config))
            elif field_type == 'radio':
                errors.extend(CustomFieldsValidator._validate_radio(field_value, field_config))
            elif field_type == 'file':
                errors.extend(CustomFieldsValidator._validate_file(field_value, field_config))

        return len(errors) == 0, errors

    @staticmethod
    def _check_visibility(visible_when: Dict, custom_fields: Dict) -> bool:
        """Verifica si un campo debe ser visible según las condiciones"""
        for key, expected_value in visible_when.items():
            actual_value = custom_fields.get(key)
            if actual_value != expected_value:
                return False
        return True

    @staticmethod
    def _validate_text(value: str, config: Dict) -> List[str]:
        """Valida campo de texto"""
        errors = []
        validation = config.get('validation', {})

        if 'minLength' in validation:
            if len(value) < validation['minLength']:
                errors.append(f"{config['label']} debe tener al menos {validation['minLength']} caracteres")

        if 'maxLength' in validation:
            if len(value) > validation['maxLength']:
                errors.append(f"{config['label']} no puede exceder {validation['maxLength']} caracteres")

        return errors

    @staticmethod
    def _validate_textarea(value: str, config: Dict) -> List[str]:
        """Valida campo de texto largo"""
        return CustomFieldsValidator._validate_text(value, config)

    @staticmethod
    def _validate_select(value: str, config: Dict) -> List[str]:
        """Valida campo de selección"""
        errors = []
        options = config.get('options', [])
        valid_values = [opt['value'] for opt in options]

        if value not in valid_values:
            errors.append(f"Valor inválido para {config['label']}")

        return errors

    @staticmethod
    def _validate_radio(value: str, config: Dict) -> List[str]:
        """Valida campo de opción múltiple"""
        return CustomFieldsValidator._validate_select(value, config)

    @staticmethod
    def _validate_file(file: FileStorage, config: Dict) -> List[str]:
        """Valida archivo subido"""
        errors = []
        validation = config.get('validation', {})

        # Verificar tamaño de archivo
        if 'maxSize' in validation:
            file.seek(0, 2)  # Ir al final del archivo
            file_size = file.tell()
            file.seek(0)  # Regresar al inicio

            if file_size > validation['maxSize']:
                max_mb = validation['maxSize'] / (1024 * 1024)
                errors.append(f"{config['label']}: El archivo no debe exceder {max_mb}MB")

        # Verificar extensión
        if 'allowedExtensions' in validation:
            filename = file.filename
            if '.' not in filename:
                errors.append(f"{config['label']}: Archivo sin extensión")
            else:
                ext = filename.rsplit('.', 1)[1].lower()
                if ext not in validation['allowedExtensions']:
                    allowed = ', '.join(validation['allowedExtensions'])
                    errors.append(f"{config['label']}: Solo se permiten archivos {allowed}")

        return errors
