from itcj2.apps.maint.models.area import MaintArea
from itcj2.apps.maint.models.category import MaintCategory
from itcj2.apps.maint.models.ticket import MaintTicket
from itcj2.apps.maint.models.ticket_technician import MaintTicketTechnician
from itcj2.apps.maint.models.technician_area import MaintTechnicianArea
from itcj2.apps.maint.models.status_log import MaintStatusLog
from itcj2.apps.maint.models.action_log import MaintTicketActionLog
from itcj2.apps.maint.models.comment import MaintComment
from itcj2.apps.maint.models.attachment import MaintAttachment
from itcj2.apps.maint.models.priority import MaintPriority
from itcj2.apps.maint.models.config_change_log import MaintConfigChangeLog
from itcj2.apps.maint.models.simple_catalog import MaintMaintenanceType, MaintServiceOrigin

__all__ = [
    "MaintArea",
    "MaintCategory",
    "MaintTicket",
    "MaintTicketTechnician",
    "MaintTechnicianArea",
    "MaintStatusLog",
    "MaintTicketActionLog",
    "MaintComment",
    "MaintAttachment",
    "MaintPriority",
    "MaintConfigChangeLog",
    "MaintMaintenanceType",
    "MaintServiceOrigin",
]
