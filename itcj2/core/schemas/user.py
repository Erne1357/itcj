from pydantic import BaseModel, Field


class PositionInfo(BaseModel):
    title: str
    department: str | None = None


class UserProfileBasic(BaseModel):
    id: int
    username: str | None = None
    full_name: str
    email: str | None = None
    role: str = "Usuario"
    roles: dict[str, list[str]] = {}
    positions: list[PositionInfo] = []


class UserProfileResponse(BaseModel):
    status: str = "ok"
    data: UserProfileBasic


class FullProfileResponse(BaseModel):
    status: str = "ok"
    data: dict


class PasswordStateResponse(BaseModel):
    must_change: bool


class ChangePasswordRequest(BaseModel):
    new_password: str = Field(..., min_length=8)


class UpdateProfileRequest(BaseModel):
    email: str | None = None
