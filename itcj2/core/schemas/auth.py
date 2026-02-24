from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    control_number: str = Field(..., description="Número de control (8 dígitos) o username")
    nip: str = Field("", description="Contraseña/NIP del usuario")


class UserInfo(BaseModel):
    id: int
    role: str | None = None
    full_name: str = ""
    control_number: str | None = None
    username: str | None = None


class LoginResponse(BaseModel):
    user: UserInfo


class MeResponse(BaseModel):
    user: UserInfo
