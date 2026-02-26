from pydantic import BaseModel, Field
from typing import Optional


class CreateCommentRequest(BaseModel):
    content: str = Field(min_length=3)
    is_internal: bool = False


class UpdateCommentRequest(BaseModel):
    content: str = Field(min_length=3)
