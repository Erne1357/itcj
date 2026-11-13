"""Error común de los servicios de prórrogas; las APIs lo vuelven JSON."""
from __future__ import annotations


class ServiceError(ValueError):
    def __init__(self, code: str, message: str, status: int = 400, **detail):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.detail = detail
