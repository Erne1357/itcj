"""
Helper genérico de CRUD para catálogos simples de configuración (maint).

Contiene la lógica compartida entre maint_types.py y service_origins.py
(y cualquier catálogo futuro de estructura id/code/label/display_order/is_active).

No es un router — es un módulo de utilidades invocado por los routers.
"""
import logging
from typing import Any, Callable

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from itcj2.apps.maint.services.config_audit_service import log_config_change, client_ip
from itcj2.apps.maint.schemas.config.catalogs import (
    CreateCatalogItem,
    UpdateCatalogItem,
    ToggleCatalogItem,
    ReorderCatalog,
)

logger = logging.getLogger(__name__)


def item_to_dict(item) -> dict:
    """Serializa un ítem de catálogo simple a dict."""
    return {
        "id": item.id,
        "code": item.code,
        "label": item.label,
        "display_order": item.display_order,
        "is_active": item.is_active,
    }


def crud_list(db: Session, model_class) -> dict:
    """Retorna todos los ítems ordenados por display_order."""
    items = db.query(model_class).order_by(model_class.display_order).all()
    return {
        "success": True,
        "data": [item_to_dict(i) for i in items],
        "total": len(items),
    }


def crud_create(
    db: Session,
    body: CreateCatalogItem,
    model_class,
    entity_type: str,
    user_id: int,
    request: Request,
    invalidate_fn: Callable,
) -> dict:
    """Crea un nuevo ítem. Valida unicidad de code (400 si duplicado)."""
    existing = db.query(model_class).filter(model_class.code == body.code).first()
    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"Ya existe un registro con code '{body.code}'",
        )

    item = model_class(
        code=body.code,
        label=body.label,
        display_order=body.display_order if body.display_order is not None else 0,
        is_active=True,
    )
    db.add(item)
    db.flush()  # obtener id antes del commit

    after = item_to_dict(item)
    log_config_change(
        db=db,
        user_id=user_id,
        entity_type=entity_type,
        entity_id=item.id,
        action="create",
        before=None,
        after=after,
        ip=client_ip(request),
    )

    try:
        db.commit()
        db.refresh(item)
        invalidate_fn()
        logger.info(f"catalog_crud [{entity_type}]: '{item.code}' creado por usuario {user_id}")
        return {"success": True, "data": item_to_dict(item)}
    except Exception as exc:
        db.rollback()
        logger.error(f"catalog_crud [{entity_type}]: error al crear ({exc!r})")
        raise HTTPException(status_code=500, detail="Error interno al crear el registro")


def crud_update(
    db: Session,
    item_id: int,
    body: UpdateCatalogItem,
    model_class,
    entity_type: str,
    user_id: int,
    request: Request,
    invalidate_fn: Callable,
) -> dict:
    """Actualización parcial (label, display_order). code nunca se modifica."""
    item = db.get(model_class, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Registro no encontrado")

    before = item_to_dict(item)
    updates = body.model_dump(exclude_none=True)
    for key, val in updates.items():
        setattr(item, key, val)

    after = item_to_dict(item)
    log_config_change(
        db=db,
        user_id=user_id,
        entity_type=entity_type,
        entity_id=item_id,
        action="update",
        before=before,
        after=after,
        ip=client_ip(request),
    )

    try:
        db.commit()
        db.refresh(item)
        invalidate_fn()
        logger.info(f"catalog_crud [{entity_type}]: id={item_id} actualizado por usuario {user_id}")
        return {"success": True, "data": item_to_dict(item)}
    except Exception as exc:
        db.rollback()
        logger.error(f"catalog_crud [{entity_type}]: error al actualizar id={item_id} ({exc!r})")
        raise HTTPException(status_code=500, detail="Error interno al actualizar el registro")


def crud_toggle(
    db: Session,
    item_id: int,
    body: ToggleCatalogItem,
    model_class,
    entity_type: str,
    user_id: int,
    request: Request,
    invalidate_fn: Callable,
) -> dict:
    """Activa o desactiva un ítem. No permite desactivar el último activo."""
    item = db.get(model_class, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Registro no encontrado")

    if not body.is_active:
        active_count = db.query(model_class).filter(
            model_class.is_active == True  # noqa: E712
        ).count()
        if active_count <= 1:
            raise HTTPException(
                status_code=400,
                detail="Debe existir al menos un registro activo en el catálogo",
            )

    before = item_to_dict(item)
    item.is_active = body.is_active
    after = item_to_dict(item)

    log_config_change(
        db=db,
        user_id=user_id,
        entity_type=entity_type,
        entity_id=item_id,
        action="toggle",
        before=before,
        after=after,
        ip=client_ip(request),
    )

    try:
        db.commit()
        db.refresh(item)
        invalidate_fn()
        estado = "activado" if body.is_active else "desactivado"
        logger.info(f"catalog_crud [{entity_type}]: id={item_id} {estado} por usuario {user_id}")
        return {"success": True, "data": item_to_dict(item)}
    except Exception as exc:
        db.rollback()
        logger.error(f"catalog_crud [{entity_type}]: error en toggle id={item_id} ({exc!r})")
        raise HTTPException(status_code=500, detail="Error interno al cambiar estado del registro")


def crud_reorder(
    db: Session,
    body: ReorderCatalog,
    model_class,
    entity_type: str,
    user_id: int,
    request: Request,
    invalidate_fn: Callable,
) -> dict:
    """Reordena el catálogo en bloque."""
    if not body.order:
        raise HTTPException(status_code=400, detail="La lista de orden no puede estar vacía")

    before_snapshot: list[dict[str, Any]] = []
    for entry in body.order:
        item = db.get(model_class, entry.id)
        if not item:
            raise HTTPException(
                status_code=404,
                detail=f"Registro con id={entry.id} no encontrado",
            )
        before_snapshot.append({"id": item.id, "code": item.code, "display_order": item.display_order})
        item.display_order = entry.display_order

    after_snapshot = [{"id": e.id, "display_order": e.display_order} for e in body.order]

    log_config_change(
        db=db,
        user_id=user_id,
        entity_type=entity_type,
        entity_id=None,
        action="reorder",
        before={"items": before_snapshot},
        after={"items": after_snapshot},
        ip=client_ip(request),
    )

    try:
        db.commit()
        invalidate_fn()
        logger.info(f"catalog_crud [{entity_type}]: reordenado por usuario {user_id}")
        return {"success": True}
    except Exception as exc:
        db.rollback()
        logger.error(f"catalog_crud [{entity_type}]: error al reordenar ({exc!r})")
        raise HTTPException(status_code=500, detail="Error interno al reordenar el catálogo")
