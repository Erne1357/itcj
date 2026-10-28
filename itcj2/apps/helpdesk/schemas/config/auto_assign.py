"""Schemas de configuracion de asignacion automatica y correo al asignar."""
from typing import Literal, Optional

from pydantic import BaseModel, Field


class AssignmentRuleCreate(BaseModel):
    area: str
    category_id: Optional[int] = None
    priority: Optional[str] = None
    strategy: Literal["round_robin", "least_loaded"]
    technician_ids: list[int] = Field(min_length=1)


class AssignmentRuleUpdate(BaseModel):
    area: Optional[str] = None
    category_id: Optional[int] = None
    priority: Optional[str] = None
    strategy: Optional[Literal["round_robin", "least_loaded"]] = None
    technician_ids: Optional[list[int]] = Field(default=None, min_length=1)
    is_active: Optional[bool] = None


class AutoAssignSettingsUpdate(BaseModel):
    enabled: bool


class AssignmentEmailUpdate(BaseModel):
    user_ids: list[int]
