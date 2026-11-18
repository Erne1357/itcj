"""Entrada de alta/edición de DVR. `password` NO se recorta (se guarda tal cual)."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class DvrInput(BaseModel):
    # Los secretos no deben aparecer en str(ValidationError).
    model_config = ConfigDict(hide_input_in_errors=True)

    name: str = Field(min_length=1, max_length=100)
    location: str | None = Field(default=None, max_length=150)
    brand: str | None = Field(default=None, max_length=50)
    model: str | None = Field(default=None, max_length=80)
    channels: int | None = Field(default=None, ge=1, le=128)
    camera_type: Literal["bala", "ptz", "mixtas"] | None = None
    cameras_installed: int | None = Field(default=None, ge=0, le=128)
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

    @field_validator("camera_type", mode="before")
    @classmethod
    def _blank_type(cls, v):
        return None if isinstance(v, str) and not v.strip() else v

    @model_validator(mode="after")
    def _installed_within_channels(self):
        if self.channels and self.cameras_installed is not None and self.cameras_installed > self.channels:
            raise ValueError(f"Hay más cámaras que canales: el DVR tiene {self.channels} canales.")
        return self
