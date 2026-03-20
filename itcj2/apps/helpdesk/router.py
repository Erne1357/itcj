"""Helpdesk app — router assembly (v2)."""
from fastapi import APIRouter

from itcj2.apps.helpdesk.api.tickets import router as tickets_router
from itcj2.apps.helpdesk.api.assignments import router as assignments_router
from itcj2.apps.helpdesk.api.comments import router as comments_router
from itcj2.apps.helpdesk.api.ticket_collaborators import router as collaborators_router
from itcj2.apps.helpdesk.api.ticket_comments import router as ticket_comments_router
from itcj2.apps.helpdesk.api.ticket_equipment import router as ticket_equipment_router
from itcj2.apps.helpdesk.api.categories import router as categories_router
from itcj2.apps.helpdesk.api.attachments import router as attachments_router
from itcj2.apps.helpdesk.api.documents import router as documents_router
from itcj2.apps.helpdesk.api.stats import router as stats_router
from itcj2.apps.helpdesk.api.inventory import inventory_router

helpdesk_router = APIRouter(prefix="/api/help-desk/v2", tags=["helpdesk"])

helpdesk_router.include_router(tickets_router, prefix="/tickets")
helpdesk_router.include_router(assignments_router, prefix="/assignments")
helpdesk_router.include_router(comments_router, prefix="/comments")
helpdesk_router.include_router(collaborators_router, prefix="/tickets")
helpdesk_router.include_router(ticket_comments_router, prefix="/tickets")
helpdesk_router.include_router(ticket_equipment_router, prefix="/tickets")
helpdesk_router.include_router(categories_router, prefix="/categories")
helpdesk_router.include_router(attachments_router, prefix="/attachments")
helpdesk_router.include_router(documents_router, prefix="/documents")
helpdesk_router.include_router(stats_router, prefix="/stats")
helpdesk_router.include_router(inventory_router, prefix="/inventory")
