from pydantic import BaseModel
from typing import Union


class GenerateDocumentsRequest(BaseModel):
    ticket_ids: Union[list[int], str]
    doc_type: str
    format: str
    output_mode: str = "zip"
