"""
Schemas Pydantic para el CRUD de plantillas de notificación (maint config).
"""
from typing import Optional, Any
from pydantic import BaseModel, Field


class UpdateNotificationTemplate(BaseModel):
    """Actualización parcial de una plantilla — code no se puede editar."""
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    channel: Optional[str] = Field(default=None, pattern=r'^(inapp|email|both)$')
    subject_template: Optional[str] = Field(default=None, max_length=255)
    title_template: Optional[str] = Field(default=None, max_length=255)
    body_template: Optional[str] = Field(default=None, min_length=1)
    variables: Optional[Any] = None


class ToggleNotificationTemplate(BaseModel):
    is_active: bool


class PreviewNotificationTemplate(BaseModel):
    ticket_id: Optional[int] = None
