"""
API CRUD de transiciones entre estados de ticket del Helpdesk.
Permite gestionar la matriz de transiciones válidas desde la UI de configuración.
Espejo de itcj2/apps/helpdesk/api/config/priorities.py.
"""
import logging

from fastapi import APIRouter, HTTPException, Request
from itcj2.dependencies import DbSession, require_perms
from itcj2.apps.helpdesk.schemas.config.transitions import (
    CreateTransitionRequest,
    UpdateTransitionRequest,
    BulkSetTransitionsRequest,
)

router = APIRouter(tags=["helpdesk-config-transitions"])
logger = logging.getLogger(__name__)


@router.get("")
def list_transitions(
    from_status_id: int = None,
    to_status_id: int = None,
    include_inactive: str = "false",
    user: dict = require_perms("helpdesk", ["helpdesk.config.statuses.api.read"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.models.status_transition import StatusTransition

    query = db.query(StatusTransition)
    if include_inactive.lower() != "true":
        query = query.filter_by(is_active=True)
    if from_status_id is not None:
        query = query.filter_by(from_status_id=from_status_id)
    if to_status_id is not None:
        query = query.filter_by(to_status_id=to_status_id)

    transitions = query.all()
    return {
        "transitions": [t.to_dict(include_status_codes=True) for t in transitions],
        "total": len(transitions),
    }


@router.get("/matrix")
def get_matrix(
    user: dict = require_perms("helpdesk", ["helpdesk.config.statuses.api.read"]),
    db: DbSession = None,
):
    """
    Devuelve estructura optimizada para la UI de matriz de transiciones.
    Incluye todos los estados activos y todas las transiciones (activas e inactivas).
    """
    from itcj2.apps.helpdesk.models.ticket_status import TicketStatus
    from itcj2.apps.helpdesk.models.status_transition import StatusTransition

    statuses = db.query(TicketStatus).filter_by(is_active=True).order_by(TicketStatus.display_order).all()
    transitions = db.query(StatusTransition).all()

    return {
        "statuses": [s.to_dict() for s in statuses],
        "transitions": [
            {
                "id": t.id,
                "from_status_id": t.from_status_id,
                "to_status_id": t.to_status_id,
                "is_active": t.is_active,
                "required_perm": t.required_perm,
                "required_fields": t.required_fields,
            }
            for t in transitions
        ],
    }


@router.post("", status_code=201)
def create_transition(
    body: CreateTransitionRequest,
    request: Request,
    user: dict = require_perms("helpdesk", ["helpdesk.config.statuses.api.update"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.models.ticket_status import TicketStatus
    from itcj2.apps.helpdesk.models.status_transition import StatusTransition
    from itcj2.apps.helpdesk.services.config_audit_service import log_config_change
    from itcj2.apps.helpdesk.utils.catalog_cache import invalidate_transitions

    user_id = int(user["sub"])

    # Verificar que ambos estados existen
    from_status = db.get(TicketStatus, body.from_status_id)
    if not from_status:
        raise HTTPException(404, detail={
            "error": "from_status_not_found",
            "message": f"Estado origen con id {body.from_status_id} no encontrado",
        })
    to_status = db.get(TicketStatus, body.to_status_id)
    if not to_status:
        raise HTTPException(404, detail={
            "error": "to_status_not_found",
            "message": f"Estado destino con id {body.to_status_id} no encontrado",
        })

    # Verificar unicidad
    existing = db.query(StatusTransition).filter_by(
        from_status_id=body.from_status_id,
        to_status_id=body.to_status_id,
    ).first()
    if existing:
        raise HTTPException(409, detail={
            "error": "transition_exists",
            "message": (
                f"Ya existe una transición de '{from_status.code}' a '{to_status.code}'. "
                "Use PATCH para actualizarla."
            ),
        })

    transition = StatusTransition(
        from_status_id=body.from_status_id,
        to_status_id=body.to_status_id,
        required_perm=body.required_perm,
        required_fields=body.required_fields,
        is_active=True,
    )
    db.add(transition)
    db.flush()

    log_config_change(
        db=db,
        user_id=user_id,
        entity_type="status_transition",
        entity_id=transition.id,
        action="create",
        before=None,
        after=transition.to_dict(include_status_codes=True),
        ip_address=request.client.host if request.client else None,
    )

    db.commit()
    db.refresh(transition)
    invalidate_transitions()

    logger.info(
        f"Transición {from_status.code} → {to_status.code} creada por usuario {user_id}"
    )
    return {
        "message": "Transición creada exitosamente",
        "transition": transition.to_dict(include_status_codes=True),
    }


@router.patch("/{transition_id}")
def update_transition(
    transition_id: int,
    body: UpdateTransitionRequest,
    request: Request,
    user: dict = require_perms("helpdesk", ["helpdesk.config.statuses.api.update"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.models.status_transition import StatusTransition
    from itcj2.apps.helpdesk.services.config_audit_service import log_config_change
    from itcj2.apps.helpdesk.utils.catalog_cache import invalidate_transitions

    user_id = int(user["sub"])
    transition = db.get(StatusTransition, transition_id)
    if not transition:
        raise HTTPException(404, detail={"error": "not_found", "message": "Transición no encontrada"})

    before = transition.to_dict(include_status_codes=True)

    for field, value in body.model_dump(exclude_none=True).items():
        setattr(transition, field, value)

    log_config_change(
        db=db,
        user_id=user_id,
        entity_type="status_transition",
        entity_id=transition.id,
        action="update",
        before=before,
        after=transition.to_dict(include_status_codes=True),
        ip_address=request.client.host if request.client else None,
    )

    db.commit()
    db.refresh(transition)
    invalidate_transitions()

    logger.info(f"Transición {transition_id} actualizada por usuario {user_id}")
    return {
        "message": "Transición actualizada exitosamente",
        "transition": transition.to_dict(include_status_codes=True),
    }


@router.delete("/{transition_id}")
def delete_transition(
    transition_id: int,
    request: Request,
    user: dict = require_perms("helpdesk", ["helpdesk.config.statuses.api.update"]),
    db: DbSession = None,
):
    """Soft-delete: marca la transición como inactiva."""
    from itcj2.apps.helpdesk.models.status_transition import StatusTransition
    from itcj2.apps.helpdesk.services.config_audit_service import log_config_change
    from itcj2.apps.helpdesk.utils.catalog_cache import invalidate_transitions

    user_id = int(user["sub"])
    transition = db.get(StatusTransition, transition_id)
    if not transition:
        raise HTTPException(404, detail={"error": "not_found", "message": "Transición no encontrada"})

    before = transition.to_dict(include_status_codes=True)
    transition.is_active = False

    log_config_change(
        db=db,
        user_id=user_id,
        entity_type="status_transition",
        entity_id=transition.id,
        action="delete",
        before=before,
        after=transition.to_dict(include_status_codes=True),
        ip_address=request.client.host if request.client else None,
    )

    db.commit()
    invalidate_transitions()

    logger.info(f"Transición {transition_id} desactivada (soft-delete) por usuario {user_id}")
    return {"message": "Transición eliminada exitosamente"}


@router.put("/bulk")
def bulk_set_transitions(
    body: BulkSetTransitionsRequest,
    request: Request,
    user: dict = require_perms("helpdesk", ["helpdesk.config.statuses.api.update"]),
    db: DbSession = None,
):
    """
    Upsert masivo de la matriz de transiciones.
    - Crea pares que no existen.
    - Actualiza pares existentes con los valores del payload.
    - Desactiva pares que están activos en BD pero no aparecen en el payload.
    Registra UN solo log con snapshot antes/después.
    """
    from itcj2.apps.helpdesk.models.status_transition import StatusTransition
    from itcj2.apps.helpdesk.services.config_audit_service import log_config_change
    from itcj2.apps.helpdesk.utils.catalog_cache import invalidate_transitions

    user_id = int(user["sub"])

    # Validar estructura mínima del payload
    for i, item in enumerate(body.transitions):
        if "from_status_id" not in item or "to_status_id" not in item:
            raise HTTPException(400, detail={
                "error": "invalid_transition_item",
                "message": f"El item en posición {i} debe tener from_status_id y to_status_id",
            })

    # Snapshot before — todos los registros activos actuales
    current_all = db.query(StatusTransition).all()
    before_snapshot = [t.to_dict(include_status_codes=True) for t in current_all]

    # Construir mapa de pares del payload
    payload_pairs: dict[tuple[int, int], dict] = {}
    for item in body.transitions:
        key = (int(item["from_status_id"]), int(item["to_status_id"]))
        payload_pairs[key] = item

    # Índice de registros existentes en BD (activos e inactivos)
    existing_map: dict[tuple[int, int], StatusTransition] = {
        (t.from_status_id, t.to_status_id): t for t in current_all
    }

    # Upsert: crear o actualizar
    for (from_id, to_id), item in payload_pairs.items():
        t = existing_map.get((from_id, to_id))
        if t is None:
            t = StatusTransition(
                from_status_id=from_id,
                to_status_id=to_id,
            )
            db.add(t)
        t.required_perm = item.get("required_perm")
        t.required_fields = item.get("required_fields")
        t.is_active = bool(item.get("is_active", True))

    # Desactivar pares activos no presentes en el payload
    for (from_id, to_id), t in existing_map.items():
        if t.is_active and (from_id, to_id) not in payload_pairs:
            t.is_active = False

    db.flush()

    # Snapshot after
    db.expire_all()
    after_all = db.query(StatusTransition).all()
    after_snapshot = [t.to_dict(include_status_codes=True) for t in after_all]

    log_config_change(
        db=db,
        user_id=user_id,
        entity_type="status_transition_matrix",
        entity_id=None,
        action="bulk_update",
        before={"transitions": before_snapshot},
        after={"transitions": after_snapshot},
        ip_address=request.client.host if request.client else None,
    )

    db.commit()
    invalidate_transitions()

    logger.info(
        f"Matriz de transiciones actualizada en bulk por usuario {user_id} "
        f"({len(payload_pairs)} pares en payload)"
    )
    return {
        "message": "Matriz de transiciones actualizada exitosamente",
        "total": len(after_snapshot),
    }
