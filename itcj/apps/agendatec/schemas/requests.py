# schemas/requests.py
"""
Schemas de validación para solicitudes de AgendaTec.

Este módulo define los schemas Pydantic para validar datos de entrada
en los endpoints de solicitudes.
"""
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class RequestType(str, Enum):
    """Tipos de solicitud disponibles."""
    DROP = "DROP"
    APPOINTMENT = "APPOINTMENT"


class CreateDropRequestSchema(BaseModel):
    """
    Schema para crear una solicitud de baja.
    
    Attributes:
        type: Tipo de solicitud (debe ser DROP).
        program_id: ID del programa académico.
        description: Descripción o motivo de la baja.
    """
    type: RequestType = Field(..., description="Tipo de solicitud")
    program_id: int = Field(..., gt=0, description="ID del programa académico")
    description: Optional[str] = Field(None, max_length=1000, description="Motivo de la baja")

    @field_validator("type")
    @classmethod
    def validate_type_is_drop(cls, v: RequestType) -> RequestType:
        """Valida que el tipo sea DROP."""
        if v != RequestType.DROP:
            raise ValueError("El tipo debe ser DROP para esta solicitud")
        return v


class CreateAppointmentRequestSchema(BaseModel):
    """
    Schema para crear una solicitud de cita.
    
    Attributes:
        type: Tipo de solicitud (debe ser APPOINTMENT).
        program_id: ID del programa académico.
        slot_id: ID del slot de tiempo.
        description: Descripción o motivo de la cita.
    """
    type: RequestType = Field(..., description="Tipo de solicitud")
    program_id: int = Field(..., gt=0, description="ID del programa académico")
    slot_id: int = Field(..., gt=0, description="ID del slot de tiempo")
    description: Optional[str] = Field(None, max_length=1000, description="Motivo de la cita")

    @field_validator("type")
    @classmethod
    def validate_type_is_appointment(cls, v: RequestType) -> RequestType:
        """Valida que el tipo sea APPOINTMENT."""
        if v != RequestType.APPOINTMENT:
            raise ValueError("El tipo debe ser APPOINTMENT para esta solicitud")
        return v


class CreateRequestSchema(BaseModel):
    """
    Schema genérico para crear cualquier tipo de solicitud.
    
    Valida los campos comunes y los específicos según el tipo.
    
    Attributes:
        type: Tipo de solicitud (DROP o APPOINTMENT).
        program_id: ID del programa académico.
        slot_id: ID del slot de tiempo (requerido para APPOINTMENT).
        description: Descripción o motivo de la solicitud.
    """
    type: RequestType = Field(..., description="Tipo de solicitud")
    program_id: int = Field(..., gt=0, description="ID del programa académico")
    slot_id: Optional[int] = Field(None, gt=0, description="ID del slot de tiempo")
    description: Optional[str] = Field(None, max_length=1000, description="Motivo")

    @field_validator("slot_id")
    @classmethod
    def validate_slot_required_for_appointment(cls, v, info):
        """Valida que slot_id esté presente para APPOINTMENT."""
        # Note: Esta validación se hace a nivel de modelo
        # Para validación cruzada con 'type', usar model_validator
        return v

    def model_post_init(self, __context) -> None:
        """Validación post-inicialización."""
        if self.type == RequestType.APPOINTMENT and not self.slot_id:
            raise ValueError("slot_id es requerido para solicitudes de tipo APPOINTMENT")


class UpdateRequestStatusSchema(BaseModel):
    """
    Schema para actualizar el estado de una solicitud.
    
    Attributes:
        status: Nuevo estado de la solicitud.
        comment: Comentario del coordinador.
    """
    status: str = Field(..., description="Nuevo estado")
    comment: Optional[str] = Field(None, max_length=500, description="Comentario del coordinador")

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        """Valida que el estado sea válido."""
        valid_statuses = {
            "PENDING",
            "RESOLVED_SUCCESS",
            "RESOLVED_NOT_COMPLETED", 
            "NO_SHOW",
            "ATTENDED_OTHER_SLOT",
            "CANCELED",
        }
        v_upper = v.upper().strip()
        if v_upper not in valid_statuses:
            raise ValueError(f"Estado inválido. Valores permitidos: {', '.join(valid_statuses)}")
        return v_upper


class AdminRequestFilterSchema(BaseModel):
    """
    Schema para filtros de búsqueda de solicitudes (admin).
    
    Attributes:
        status: Filtrar por estado.
        type: Filtrar por tipo de solicitud.
        program_id: Filtrar por programa.
        period_id: Filtrar por período académico.
        coordinator_id: Filtrar por coordinador asignado.
        search: Búsqueda por texto en nombre/email de estudiante.
        page: Número de página (paginación).
        per_page: Elementos por página.
        from_date: Fecha de inicio del rango.
        to_date: Fecha de fin del rango.
    """
    status: Optional[str] = Field(None, description="Filtrar por estado")
    type: Optional[RequestType] = Field(None, description="Filtrar por tipo")
    program_id: Optional[int] = Field(None, gt=0, description="Filtrar por programa")
    period_id: Optional[int] = Field(None, gt=0, description="Filtrar por período")
    coordinator_id: Optional[int] = Field(None, gt=0, description="Filtrar por coordinador")
    search: Optional[str] = Field(None, max_length=100, description="Búsqueda de texto")
    page: int = Field(1, ge=1, description="Número de página")
    per_page: int = Field(25, ge=1, le=100, description="Elementos por página")
    from_date: Optional[str] = Field(None, description="Fecha de inicio (YYYY-MM-DD)")
    to_date: Optional[str] = Field(None, description="Fecha de fin (YYYY-MM-DD)")
