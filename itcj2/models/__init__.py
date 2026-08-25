"""Importa **todos** los modelos de la plataforma en un solo lugar.

Esto garantiza que el registro de clases de SQLAlchemy esté completo antes
de que se configure cualquier mapper (p. ej. las relaciones en User que
referencian Ticket, Request, etc. de otras apps).
"""

# Core
from itcj2.core.models import (  # noqa: F401
    Role, User, App, Permission, RolePermission,
    UserAppRole, UserAppPerm, Coordinator, Program,
    ProgramCoordinator, AcademicPeriod, Theme, Department,
    Notification, Position, UserPosition, PositionAppRole,
    PositionAppPerm, ProgramPosition,
    TaskDefinition, PeriodicTask, TaskRun,
)

# Helpdesk
from itcj2.apps.helpdesk.models import (  # noqa: F401
    Ticket, Assignment, Category, Comment, Attachment,
    StatusLog, TicketCollaborator, TicketEditLog,
    InventoryCategory, InventoryItem, InventoryHistory,
    InventoryGroup, InventoryGroupCapacity, TicketInventoryItem,
)

# AgendaTec
from itcj2.apps.agendatec.models import (  # noqa: F401
    AgendaTecPeriodConfig, Appointment, AuditLog, AvailabilityWindow,
    AvailabilityWindowProgram, PeriodEnabledDay, Request, SurveyDispatch,
    TimeSlot, TimeSlotProgram,
)

# VisteTec
from itcj2.apps.vistetec.models import (  # noqa: F401
    VTAppointment, VTDonation, Garment, VTLocation,
    PantryCampaign, PantryItem, SlotVolunteer, VTTimeSlot,
)

# Warehouse
from itcj2.apps.warehouse.models import (  # noqa: F401
    WarehouseCategory, WarehouseSubcategory, WarehouseProduct,
    WarehouseStockEntry, WarehouseMovement, WarehouseTicketMaterial,
)

# Maint
from itcj2.apps.maint.models import (  # noqa: F401
    MaintArea,
    MaintCategory, MaintTicket, MaintTicketTechnician, MaintTechnicianArea,
    MaintStatusLog, MaintTicketActionLog, MaintComment, MaintAttachment,
    MaintPriority, MaintConfigChangeLog,
    MaintMaintenanceType, MaintServiceOrigin,
    MaintNotificationTemplate,
)

# Adhoc
from itcj2.apps.adhoc.models import (  # noqa: F401
    AdhocArea, adhoc_user_areas, AdhocProcess,
    AdhocIndicatorYear, AdhocIndicator, AdhocIndicatorTracking,
    AdhocMailConfig,
    AdhocDocumentCategory, AdhocDocumentClassification,
    AdhocApprovalFlow, AdhocApprovalFlowStep, adhoc_flow_step_assignees, AdhocDocument,
    AdhocIncidentCategory, AdhocIncident,
    AdhocProgramCategory, AdhocProgramEvent, AdhocProgramEventFile,
    AdhocTask, adhoc_task_assignees, AdhocTaskComment, AdhocTaskApproval,
)
