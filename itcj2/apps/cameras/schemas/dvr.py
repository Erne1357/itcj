"""Entrada de alta/edición de DVR. `password` NO se recorta (se guarda tal cual)."""
from pydantic import BaseModel, ConfigDict, Field, field_validator


class DvrInput(BaseModel):
    # Los secretos no deben aparecer en str(ValidationError).
    model_config = ConfigDict(hide_input_in_errors=True)

    name: str = Field(min_length=1, max_length=100)
    location: str | None = Field(default=None, max_length=150)
    brand: str | None = Field(default=None, max_length=50)
    model: str | None = Field(default=None, max_length=80)
    channels: int | None = Field(default=None, ge=1, le=128)
    username: str | None = Field(default=None, max_length=50, repr=False)
    notes: str | None = Field(default=None, repr=False)
    remove_username: bool = False
    remove_notes: bool = False
    department_ids: list[int] = []
    password: str | None = Field(default=None, repr=False)
    remove_password: bool = False
    pattern: str | None = Field(default=None, repr=False)
    remove_pattern: bool = False

    @field_validator("name", mode="before")
    @classmethod
    def _strip_name(cls, v):
        return v.strip() if isinstance(v, str) else v
