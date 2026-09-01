from datetime import datetime
from decimal import Decimal
from enum import Enum
from pydantic import BaseModel
from typing import Optional

class PaymentStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    MIDDLE = "MIDDLE"
    NOPAID = "NOPAID"

class PaymentBase(BaseModel):
    num_payments_terms: int
    amount: Decimal
    expiration_date: Optional[datetime] = None
    payday: Optional[datetime] = None
    status: PaymentStatus
    admin_comment: Optional[str] = None

class PaymentCreate(PaymentBase):
    request_id: int
    period_id: Optional[int] = None

class PaymentUpdate(BaseModel):
    num_payments_terms: Optional[int] = None
    amount: Optional[Decimal] = None
    expiration_date: Optional[datetime] = None
    payday: Optional[datetime] = None
    status: Optional[PaymentStatus] = None
    admin_comment: Optional[str] = None

class PaymentResponse(PaymentBase):
    id: int
    request_id: int
    period_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True  # Pydantic v2
