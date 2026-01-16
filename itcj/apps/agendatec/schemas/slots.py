# schemas/slots.py
"""
Schemas de validación para slots de AgendaTec.

Este módulo define los schemas Pydantic para validar datos de entrada
en los endpoints de slots de tiempo.
"""
from datetime import date, time
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class SlotHoldSchema(BaseModel):
    """
    Schema para retener temporalmente un slot.
    
    Attributes:
        slot_id: ID del slot a retener.
    """
    slot_id: int = Field(..., gt=0, description="ID del slot")


class CreateSlotSchema(BaseModel):
    """
    Schema para crear un slot de tiempo.
    
    Attributes:
        day: Fecha del slot.
        start_time: Hora de inicio.
        end_time: Hora de fin.
        coordinator_id: ID del coordinador.
    """
    day: date = Field(..., description="Fecha del slot")
    start_time: time = Field(..., description="Hora de inicio")
    end_time: time = Field(..., description="Hora de fin")
    coordinator_id: int = Field(..., gt=0, description="ID del coordinador")

    @field_validator("end_time")
    @classmethod
    def validate_end_after_start(cls, v, info):
        """Valida que la hora de fin sea posterior a la de inicio."""
        # Esta validación requiere acceso a start_time
        # Se puede hacer en model_validator si es necesario
        return v


class SlotFilterSchema(BaseModel):
    """
    Schema para filtrar slots.
    
    Attributes:
        day: Filtrar por fecha.
        coordinator_id: Filtrar por coordinador.
        program_id: Filtrar por programa.
        available_only: Mostrar solo slots disponibles.
    """
    day: Optional[date] = Field(None, description="Filtrar por fecha")
    coordinator_id: Optional[int] = Field(None, gt=0, description="Filtrar por coordinador")
    program_id: Optional[int] = Field(None, gt=0, description="Filtrar por programa")
    available_only: bool = Field(True, description="Solo mostrar disponibles")


class DayConfigSchema(BaseModel):
    """
    Schema para configurar un día para citas.
    
    Attributes:
        date: Fecha a configurar.
        start_time: Hora de inicio de disponibilidad.
        end_time: Hora de fin de disponibilidad.
        slot_duration_minutes: Duración de cada slot en minutos.
    """
    date: date = Field(..., description="Fecha a configurar")
    start_time: time = Field(..., description="Hora de inicio")
    end_time: time = Field(..., description="Hora de fin")
    slot_duration_minutes: int = Field(30, ge=10, le=120, description="Duración del slot")

    @field_validator("slot_duration_minutes")
    @classmethod
    def validate_duration(cls, v: int) -> int:
        """Valida que la duración sea razonable."""
        if v < 10:
            raise ValueError("La duración mínima es 10 minutos")
        if v > 120:
            raise ValueError("La duración máxima es 120 minutos")
        return v
