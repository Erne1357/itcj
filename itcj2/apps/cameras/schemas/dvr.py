"""Entrada de alta/edición de DVR. `password` NO se recorta (se guarda tal cual)."""
from pydantic import BaseModel, Field, field_validator


class DvrInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    location: str | None = Field(default=None, max_length=150)
    brand: str | None = Field(default=None, max_length=50)
    model: str | None = Field(default=None, max_length=80)
    channels: int | None = Field(default=None, ge=1, le=128)
    username: str | None = Field(default=None, max_length=50)
    notes: str | None = None
    department_ids: list[int] = []
    password: str | None = None
    remove_password: bool = False
    pattern: str | None = None
    remove_pattern: bool = False

    @field_validator("name", mode="before")
    @classmethod
    def _strip_name(cls, v):
        return v.strip() if isinstance(v, str) else v
