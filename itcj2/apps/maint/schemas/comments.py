from pydantic import BaseModel, Field


class CreateCommentRequest(BaseModel):
    content: str = Field(min_length=3)
    is_internal: bool = False
    # is_internal=True → solo visible para staff (dispatcher, tech_maint, admin)
