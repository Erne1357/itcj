from pydantic import BaseModel, Field


class NotificationListParams(BaseModel):
    app: str | None = None
    unread: bool = False
    limit: int = Field(20, ge=1, le=100)
    offset: int = Field(0, ge=0)
    before_id: int | None = None


class UnreadCountsData(BaseModel):
    counts: dict[str, int]
    total: int


class UnreadCountsResponse(BaseModel):
    status: str = "ok"
    data: UnreadCountsData
