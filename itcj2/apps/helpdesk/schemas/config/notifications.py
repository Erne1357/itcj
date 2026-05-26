"""
Schemas Pydantic para la API de plantillas de notificación del Helpdesk.
Solo permite editar contenido de plantilla existente (edit + toggle).
No permite crear ni borrar plantillas — son responsabilidad del seed.
"""
from pydantic import BaseModel, Field
from typing import Optional, Any


class UpdateNotificationTemplateRequest(BaseModel):
    """
    Edición de plantilla: SOLO campos de contenido y canal.
    Campos inmutables excluidos: code (identificador estable), name (descriptivo del seed).
    """
    description: Optional[str] = None
    channel: Optional[str] = Field(default=None, pattern="^(inapp|email|both)$")
    subject_template: Optional[str] = Field(default=None, max_length=255)
    body_template: Optional[str] = Field(default=None, min_length=1)


class ToggleNotificationTemplateRequest(BaseModel):
    is_active: bool


class PreviewNotificationRequest(BaseModel):
    """
    Renderiza la plantilla con datos de un ticket real o con datos de muestra.
    Si no se provee ni ticket_id ni sample_data, se usan datos dummy razonables.
    """
    ticket_id: Optional[int] = None
    sample_data: Optional[dict[str, Any]] = None
