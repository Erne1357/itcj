from pydantic import BaseModel
from typing import Optional


# --- Items ---
class CreateItemRequest(BaseModel):
    category_id: int
    department_id: int
    brand: Optional[str] = None
    model: Optional[str] = None
    supplier_serial: Optional[str] = None
    itcj_serial: Optional[str] = None
    id_tecnm: Optional[str] = None
    specifications: Optional[dict] = None
    location_detail: Optional[str] = None
    acquisition_date: Optional[str] = None
    warranty_expiration: Optional[str] = None
    maintenance_frequency_days: Optional[int] = None
    notes: Optional[str] = None
    assigned_to_user_id: Optional[int] = None


class UpdateItemRequest(BaseModel):
    brand: Optional[str] = None
    model: Optional[str] = None
    supplier_serial: Optional[str] = None
    itcj_serial: Optional[str] = None
    id_tecnm: Optional[str] = None
    specifications: Optional[dict] = None
    location_detail: Optional[str] = None
    warranty_expiration: Optional[str] = None
    maintenance_frequency_days: Optional[int] = None
    notes: Optional[str] = None


class ChangeStatusRequest(BaseModel):
    status: str
    notes: Optional[str] = None


class DeactivateRequest(BaseModel):
    reason: str


# --- Assignments ---
class AssignItemRequest(BaseModel):
    item_id: int
    user_id: int
    location: Optional[str] = None
    notes: Optional[str] = None


class UnassignItemRequest(BaseModel):
    item_id: int
    notes: Optional[str] = None


class TransferRequest(BaseModel):
    item_id: int
    new_department_id: int
    notes: str


class BulkAssignRequest(BaseModel):
    item_ids: list[int]
    user_id: int
    notes: Optional[str] = None


class UpdateLocationRequest(BaseModel):
    item_id: int
    location: str
    notes: Optional[str] = None


# --- Categories ---
class CreateInvCategoryRequest(BaseModel):
    code: str
    name: str
    description: Optional[str] = None
    icon: str = "fas fa-box"
    requires_specs: bool = True
    spec_template: Optional[dict] = None
    display_order: int = 0
    inventory_prefix: str
    is_active: bool = True


class UpdateInvCategoryRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    icon: Optional[str] = None
    requires_specs: Optional[bool] = None
    spec_template: Optional[dict] = None
    display_order: Optional[int] = None
    is_active: Optional[bool] = None


# --- Groups ---
class CreateGroupRequest(BaseModel):
    name: str
    department_id: int
    description: Optional[str] = None
    group_type: Optional[str] = None
    location: Optional[str] = None


class UpdateGroupRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    group_type: Optional[str] = None
    location: Optional[str] = None
    is_active: Optional[bool] = None


class UpdateCapacitiesRequest(BaseModel):
    capacities: list[dict]


class AssignItemToGroupRequest(BaseModel):
    item_id: int


class BulkAssignToGroupRequest(BaseModel):
    item_ids: list[int]


# --- Pending ---
class AssignPendingRequest(BaseModel):
    item_ids: list[int]
    department_id: int
    location_detail: Optional[str] = None
    notes: Optional[str] = None


# --- Selection ---
class ValidateForTicketRequest(BaseModel):
    item_ids: list[int]


# --- Bulk ---
class BulkCreateRequest(BaseModel):
    category_id: int
    brand: Optional[str] = None
    model: Optional[str] = None
    specifications: Optional[dict] = None
    acquisition_date: Optional[str] = None
    warranty_expiration: Optional[str] = None
    maintenance_frequency_days: Optional[int] = None
    notes: Optional[str] = None
    department_id: Optional[int] = None
    # Listas de identificadores: texto separado por el separador elegido
    supplier_serial_list: Optional[str] = None
    itcj_serial_list: Optional[str] = None
    id_tecnm_list: Optional[str] = None
    serial_separator: Optional[str] = "newline"  # comma | semicolon | space | newline | auto
    # items: overrides por equipo (posicional). Si no se provee, se usa quantity.
    quantity: Optional[int] = None
    items: Optional[list[dict]] = None


class ValidateBulkSerialsRequest(BaseModel):
    supplier_serial_list: Optional[str] = None
    itcj_serial_list: Optional[str] = None
    id_tecnm_list: Optional[str] = None
    serial_separator: Optional[str] = "newline"
