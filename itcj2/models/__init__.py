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
    PeriodEnabledDay, Request, SurveyDispatch, TimeSlot,
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
