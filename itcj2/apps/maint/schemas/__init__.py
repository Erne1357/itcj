from itcj2.apps.maint.schemas.tickets import (
    CreateTicketRequest,
    UpdateTicketRequest,
    ResolveTicketRequest,
    RateTicketRequest,
    CancelTicketRequest,
)
from itcj2.apps.maint.schemas.assignments import (
    AssignTechnicianRequest,
    UnassignTechnicianRequest,
)
from itcj2.apps.maint.schemas.categories import (
    CreateCategoryRequest,
    UpdateCategoryRequest,
    ToggleCategoryRequest,
    UpdateFieldTemplateRequest,
)
from itcj2.apps.maint.schemas.comments import CreateCommentRequest
from itcj2.apps.maint.schemas.technician_areas import (
    AssignTechnicianAreaRequest,
    RemoveTechnicianAreaRequest,
)

__all__ = [
    "CreateTicketRequest",
    "UpdateTicketRequest",
    "ResolveTicketRequest",
    "RateTicketRequest",
    "CancelTicketRequest",
    "AssignTechnicianRequest",
    "UnassignTechnicianRequest",
    "CreateCategoryRequest",
    "UpdateCategoryRequest",
    "ToggleCategoryRequest",
    "UpdateFieldTemplateRequest",
    "CreateCommentRequest",
    "AssignTechnicianAreaRequest",
    "RemoveTechnicianAreaRequest",
]
