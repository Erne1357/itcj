"""
API para verificación física de equipos del inventario.
Equivalente FastAPI de itcj/apps/helpdesk/routes/api/inventory/inventory_verification.py

Rutas (prefix: /api/help-desk/v2/inventory/verification):
  GET  /status                          → Lista equipos con estado de verificación (paginado)
  GET  /items/{item_id}/history         → Historial de verificaciones de un equipo
  POST /items/{item_id}/verify          → Registrar verificación física
"""
import logging
from datetime import datetime

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy.orm import joinedload

from itcj2.dependencies import DbSession, require_perms

router = APIRouter(tags=["helpdesk-inventory-verification"])
logger = logging.getLogger(__name__)

# Umbrales de estado de verificación (en días)
_RECENT_DAYS = 30
_OUTDATED_DAYS = 90


def _verification_status(last_verified_at) -> str:
    """Calcula el estado de verificación según la última fecha."""
    if not last_verified_at:
        return "never"
    delta = (datetime.now() - last_verified_at).days
    if delta < _RECENT_DAYS:
        return "recent"
    if delta <= _OUTDATED_DAYS:
        return "outdated"
    return "critical"


# ── GET /status ───────────────────────────────────────────────────────────────

@router.get("/status")
def get_verification_status(
    request: Request,
    department_id: int | None = None,
    category_id: int | None = None,
    status_filter: str = "all",
    search: str = "",
    page: int = 1,
    per_page: int = 50,
    user: dict = require_perms("helpdesk", ["helpdesk.inventory.api.verify"]),
    db: DbSession = None,
):
    """
    Lista equipos activos con su estado de verificación, paginados desde el servidor.

    status_filter: all | recent | outdated | critical | never
    """
    from sqlalchemy import or_
    from itcj2.apps.helpdesk.models.inventory_item import InventoryItem
    from itcj2.apps.helpdesk.utils.inventory_access import visible_department_ids

    page = max(1, page)
    per_page = min(100, max(1, per_page))
    search = search.strip()

    # Query ligera: solo id + last_verified_at para stats + filtrado.
    # visible None = ve todo; si no, el ?department_id= NUNCA sustituye el
    # scope, solo lo intersecta (fuera de scope ⇒ vacío), igual que items.py.
    visible = visible_department_ids(db, user)
    base_filters = [InventoryItem.is_active == True]
    if visible is None:
        if department_id:
            base_filters.append(InventoryItem.department_id == department_id)
    elif department_id:
        wanted = visible & {department_id}
        base_filters.append(InventoryItem.department_id.in_(wanted or {-1}))
    else:
        base_filters.append(InventoryItem.department_id.in_(visible or {-1}))
    if category_id:
        base_filters.append(InventoryItem.category_id == category_id)
    if search:
        term = f"%{search}%"
        base_filters.append(
            or_(
                InventoryItem.inventory_number.ilike(term),
                InventoryItem.brand.ilike(term),
                InventoryItem.model.ilike(term),
            )
        )

    light_rows = (
        db.query(InventoryItem.id, InventoryItem.last_verified_at)
        .filter(*base_filters)
        .order_by(
            InventoryItem.last_verified_at.asc().nullsfirst(),
            InventoryItem.inventory_number,
        )
        .all()
    )

    # Calcular stats y filtrar por verification_status en Python
    stats = {"total": 0, "recent": 0, "outdated": 0, "critical": 0, "never": 0}
    filtered = []

    for item_id, lva in light_rows:
        vs = _verification_status(lva)
        stats["total"] += 1
        stats[vs] += 1
        if status_filter == "all" or vs == status_filter:
            filtered.append((item_id, vs))

    # Paginación sobre los IDs ya filtrados
    total_filtered = len(filtered)
    start = (page - 1) * per_page
    page_rows = filtered[start : start + per_page]
    page_ids = [r[0] for r in page_rows]
    vs_map = {r[0]: r[1] for r in page_rows}

    if not page_ids:
        return {
            "success": True,
            "data": [],
            "pagination": {
                "total": total_filtered,
                "page": page,
                "per_page": per_page,
                "pages": max(1, (total_filtered + per_page - 1) // per_page),
            },
            "stats": stats,
        }

    # Query completa — solo la página, con eager loading
    items = (
        db.query(InventoryItem)
        .filter(InventoryItem.id.in_(page_ids))
        .options(
            joinedload(InventoryItem.category),
            joinedload(InventoryItem.department),
            joinedload(InventoryItem.last_verified_by),
            joinedload(InventoryItem.assigned_to_user),
            joinedload(InventoryItem.registered_by),
            joinedload(InventoryItem.assigned_by),
            joinedload(InventoryItem.group),
        )
        .all()
    )

    item_map = {item.id: item for item in items}
    result = []
    for item_id in page_ids:
        if item_id not in item_map:
            continue
        item_data = item_map[item_id].to_dict(include_relations=True)
        item_data["verification_status"] = vs_map[item_id]
        result.append(item_data)

    return {
        "success": True,
        "data": result,
        "pagination": {
            "total": total_filtered,
            "page": page,
            "per_page": per_page,
            "pages": max(1, (total_filtered + per_page - 1) // per_page),
        },
        "stats": stats,
    }


# ── GET /items/{item_id}/history ──────────────────────────────────────────────

@router.get("/items/{item_id}/history")
def get_item_verifications(
    item_id: int,
    user: dict = require_perms("helpdesk", ["helpdesk.inventory.api.read.all"]),
    db: DbSession = None,
):
    """Historial de verificaciones de un equipo específico."""
    from itcj2.apps.helpdesk.models.inventory_item import InventoryItem
    from itcj2.apps.helpdesk.models.inventory_verification import InventoryVerification

    item = db.query(InventoryItem).filter_by(id=item_id).first()
    if not item:
        raise HTTPException(404, detail={"success": False, "error": "Equipo no encontrado"})

    verifications = (
        db.query(InventoryVerification)
        .filter_by(inventory_item_id=item_id)
        .order_by(InventoryVerification.verified_at.desc())
        .all()
    )

    return {
        "success": True,
        "data": [v.to_dict(include_relations=True) for v in verifications],
        "total": len(verifications),
    }


# ── POST /items/{item_id}/verify ──────────────────────────────────────────────

@router.post("/items/{item_id}/verify")
def verify_item(
    item_id: int,
    body: dict,
    request: Request,
    user: dict = require_perms("helpdesk", ["helpdesk.inventory.api.verify"]),
    db: DbSession = None,
):
    """
    Registrar verificación física de un equipo.

    Body: {
        observations:       str  (opcional)
        location_confirmed: str  (opcional)
        location_detail:    str  (opcional)  → nueva ubicación a guardar
        status:             str  (opcional)  → ACTIVE|MAINTENANCE|DAMAGED|LOST|RETIRED
        brand:              str  (opcional)
        model:              str  (opcional)
        serial_number:      str  (opcional)
        specifications:     dict (opcional)
        group_id:           int  (opcional, None = quitar del grupo)
        assigned_to_user_id: int (opcional, None = liberar/global del depto)
    }
    """
    from itcj2.apps.helpdesk.models.inventory_item import InventoryItem
    from itcj2.apps.helpdesk.models.inventory_history import InventoryHistory
    from itcj2.apps.helpdesk.models.inventory_verification import InventoryVerification
    from itcj2.apps.helpdesk.services.inventory_service import InventoryService
    from itcj2.apps.helpdesk.services.inventory_group_service import InventoryGroupService

    user_id = int(user["sub"])
    ip = request.client.host if request.client else None
    now = datetime.now()

    item = db.query(InventoryItem).filter_by(id=item_id).first()
    if not item:
        raise HTTPException(404, detail={"success": False, "error": "Equipo no encontrado"})
    if not item.is_active:
        raise HTTPException(400, detail={"success": False, "error": "El equipo está dado de baja"})

    changes_applied = {}

    # Campos básicos actualizables
    basic_updatable = ["brand", "model", "supplier_serial", "itcj_serial", "id_tecnm", "location_detail"]
    update_payload = {}
    for field in basic_updatable:
        if field in body and body[field] is not None:
            old_val = getattr(item, field)
            new_val = str(body[field]).strip() if body[field] else None
            if old_val != new_val:
                update_payload[field] = new_val
                changes_applied[field] = {"old": old_val, "new": new_val}

    # Especificaciones técnicas
    new_specs = body.get("specifications")
    if new_specs is not None and isinstance(new_specs, dict) and new_specs:
        old_specs = item.specifications or {}
        if old_specs != new_specs:
            update_payload["specifications"] = new_specs
            changes_applied["specifications"] = {"old": old_specs, "new": new_specs}

    _LOCKED_FIELDS = frozenset({"brand", "model", "supplier_serial", "itcj_serial", "id_tecnm"})

    if update_payload:
        update_payload["update_notes"] = "Cambio registrado durante verificación física"
        try:
            InventoryService.update_item(db, item_id, update_payload, user_id, ip)
            db.refresh(item)
        except ValueError as e:
            raise HTTPException(400, detail={"success": False, "error": str(e)})

    # Si el equipo está bloqueado y se modificaron campos críticos, registrar LOCKED_FIELD_MODIFIED
    if item.is_locked and changes_applied:
        locked_changes = {f: v for f, v in changes_applied.items() if f in _LOCKED_FIELDS}
        for field, change in locked_changes.items():
            db.add(InventoryHistory(
                item_id=item_id,
                event_type="LOCKED_FIELD_MODIFIED",
                old_value={field: change["old"]},
                new_value={field: change["new"]},
                notes=f"Campo bloqueado modificado durante verificación física: {field}.",
                performed_by_id=user_id,
                ip_address=ip,
            ))

    # Asignación a usuario. TRAMPA: NO delegar en InventoryService.assign_to_user /
    # unassign_from_user — ambos hacen su propio commit (partiría esta transacción)
    # y assign_to_user exige status == 'ACTIVE' (el mismo submit puede marcar el
    # equipo DAMAGED). Se escribe en línea, ANTES del cambio de estado, y viaja en
    # el commit único de abajo.
    if "assigned_to_user_id" in body:
        from itcj2.core.models.position import Position, UserPosition
        from itcj2.core.models.user import User

        new_assigned_id = body["assigned_to_user_id"]
        old_assigned_id = item.assigned_to_user_id

        if new_assigned_id != old_assigned_id:
            if new_assigned_id is not None:
                # Debe existir Y pertenecer (puesto activo) al departamento del
                # equipo — no se acepta cualquier id del sistema.
                target_user = (
                    db.query(User)
                    .join(UserPosition, User.id == UserPosition.user_id)
                    .join(Position, UserPosition.position_id == Position.id)
                    .filter(
                        User.id == new_assigned_id,
                        Position.department_id == item.department_id,
                        Position.is_active.is_(True),
                        UserPosition.is_active.is_(True),
                    )
                    .first()
                )
                if not target_user:
                    raise HTTPException(400, detail={
                        "success": False,
                        "error": "El usuario no pertenece al departamento del equipo",
                    })

                old_user = db.get(User, old_assigned_id) if old_assigned_id else None
                item.assigned_to_user_id = new_assigned_id
                item.assigned_by_id = user_id
                item.assigned_at = now

                db.add(InventoryHistory(
                    item_id=item_id,
                    event_type="ASSIGNED_TO_USER" if old_assigned_id is None else "REASSIGNED",
                    old_value={
                        "assigned_to_user_id": old_assigned_id,
                        "assigned_to_user_name": old_user.full_name if old_user else None,
                    },
                    new_value={
                        "assigned_to_user_id": new_assigned_id,
                        "assigned_to_user_name": target_user.full_name,
                    },
                    notes=f"Asignado a {target_user.full_name} durante verificación física",
                    performed_by_id=user_id,
                    ip_address=ip,
                ))
            else:
                # "Sin asignar" sobre un equipo ya global es no-op (no hay nada
                # que liberar); solo actuamos si de verdad tenía dueño.
                old_user = db.get(User, old_assigned_id) if old_assigned_id else None
                item.assigned_to_user_id = None
                item.assigned_by_id = None
                item.assigned_at = None

                db.add(InventoryHistory(
                    item_id=item_id,
                    event_type="UNASSIGNED",
                    old_value={
                        "assigned_to_user_id": old_assigned_id,
                        "assigned_to_user_name": old_user.full_name if old_user else None,
                    },
                    new_value={"assigned_to_user_id": None, "status": "Global del departamento"},
                    notes="Equipo liberado durante verificación física",
                    performed_by_id=user_id,
                    ip_address=ip,
                ))

            changes_applied["assigned_to_user_id"] = {"old": old_assigned_id, "new": new_assigned_id}
            # Flush (no commit): los bloques de abajo (estado/grupo) hacen
            # db.refresh(item) tras commits propios de otros services. Con
            # autoflush=False (SessionLocal de producción) un refresh SIN flush
            # previo pisaría esta asignación en memoria con lo que aún hay en BD.
            # Sigue viajando en el commit único de más abajo, no finaliza nada.
            db.flush()

    # Cambio de estado
    new_status = body.get("status")
    if new_status and new_status != item.status:
        valid_statuses = ["ACTIVE", "MAINTENANCE", "DAMAGED", "LOST", "RETIRED"]
        if new_status not in valid_statuses:
            raise HTTPException(400, detail={
                "success": False,
                "error": f"Estado inválido. Opciones: {', '.join(valid_statuses)}"
            })
        try:
            old_status = item.status
            InventoryService.change_status(
                db, item_id, new_status, user_id,
                notes="Estado actualizado durante verificación física",
                ip_address=ip,
            )
            db.refresh(item)
            changes_applied["status"] = {"old": old_status, "new": new_status}
        except ValueError as e:
            raise HTTPException(400, detail={"success": False, "error": str(e)})

    # Cambio de grupo
    if "group_id" in body:
        new_group_id = body["group_id"]
        old_group_id = item.group_id
        if new_group_id != old_group_id:
            try:
                if new_group_id is None and old_group_id is not None:
                    old_group = db.query(__import__(
                        "itcj2.apps.helpdesk.models.inventory_group",
                        fromlist=["InventoryGroup"]
                    ).InventoryGroup).filter_by(id=old_group_id).first()
                    InventoryGroupService.unassign_item_from_group(db, item_id, user_id)
                    changes_applied["group"] = {
                        "old": old_group.name if old_group else str(old_group_id),
                        "new": None,
                    }
                elif new_group_id is not None:
                    from itcj2.apps.helpdesk.models.inventory_group import InventoryGroup
                    old_group = db.query(InventoryGroup).filter_by(id=old_group_id).first() if old_group_id else None
                    if old_group_id is not None:
                        InventoryGroupService.unassign_item_from_group(db, item_id, user_id)
                    InventoryGroupService.assign_item_to_group(db, item_id, new_group_id, user_id)
                    new_group = db.query(InventoryGroup).filter_by(id=new_group_id).first()
                    changes_applied["group"] = {
                        "old": old_group.name if old_group else None,
                        "new": new_group.name if new_group else str(new_group_id),
                    }
                db.refresh(item)
            except ValueError as e:
                raise HTTPException(400, detail={"success": False, "error": str(e)})

    # Crear registro de verificación (usa el mismo `now` de arriba, así
    # assigned_at/verified_at/last_verified_at quedan consistentes entre sí).
    verification = InventoryVerification(
        inventory_item_id=item_id,
        verified_by_id=user_id,
        verified_at=now,
        location_confirmed=body.get("location_confirmed") or item.location_detail,
        status_found=body.get("status") or item.status,
        observations=body.get("observations"),
        changes_applied=changes_applied if changes_applied else None,
    )
    db.add(verification)

    # Actualizar campos de última verificación en el equipo
    item.last_verified_at = now
    item.last_verified_by_id = user_id

    # Registrar en historial
    history_entry = InventoryHistory(
        item_id=item_id,
        event_type="VERIFIED",
        old_value=None,
        new_value={
            "location_confirmed": verification.location_confirmed,
            "status_found": verification.status_found,
            "changes": changes_applied,
        },
        notes=verification.observations or "Verificación física registrada",
        performed_by_id=user_id,
        ip_address=ip,
    )
    db.add(history_entry)
    db.commit()
    db.refresh(verification)
    db.refresh(item)

    return {
        "success": True,
        "message": "Verificación registrada correctamente",
        "verification": verification.to_dict(include_relations=True),
        "item": item.to_dict(include_relations=True),
        "verification_status": _verification_status(item.last_verified_at),
    }
