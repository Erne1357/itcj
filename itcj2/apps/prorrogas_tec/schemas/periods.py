from pydantic import BaseModel
from datetime import datetime
from typing import Optional


# 🔹 Base
class ProrrogasPeriodConfigBase(BaseModel):
    student_admission_start: Optional[datetime] = None
    student_admission_deadline: Optional[datetime] = None
    payment_1: Optional[datetime] = None
    payment_2: Optional[datetime] = None
    payment_3: Optional[datetime] = None


# 🔹 Crear
class ProrrogasPeriodConfigCreate(ProrrogasPeriodConfigBase):
    period_id: int


# 🔹 Update
class ProrrogasPeriodConfigUpdate(BaseModel):
    student_admission_start: Optional[datetime] = None
    student_admission_deadline: Optional[datetime] = None
    payment_1: Optional[datetime] = None
    payment_2: Optional[datetime] = None
    payment_3: Optional[datetime] = None


# 🔹 Response
class ProrrogasPeriodConfigOut(ProrrogasPeriodConfigBase):
    id: int
    period_id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True