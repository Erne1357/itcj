"""
Departments API v2 — 10 endpoints.
Fuente: itcj/core/routes/api/departments.py
"""
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from itcj2.dependencies import DbSession, require_perms

router = APIRouter(tags=["core-departments"])
logger = logging.getLogger(__name__)


# ── Schemas ───────────────────────────────────────────────────────────────────

class DepartmentCreateBody(BaseModel):
    code: str
    name: str
    description: Optional[str] = None
    parent_id: Optional[int] = None
    icon_class: Optional[str] = None


class DepartmentUpdateBody(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None
    parent_id: Optional[int] = None
    icon_class: Optional[str] = None


# ── Consultas jerárquicas ─────────────────────────────────────────────────────

@router.get("/direction")
def get_direction(
    user: dict = require_perms("itcj", ["core.departments.api.read.hierarchy"]),
    db: DbSession = None,
):
    """Obtiene la dirección (departamento raíz sin padre)."""
    from itcj.core.services import departments_service as svc

    direction = svc.get_direction()
    return {
        "status": "ok",
        "data": direction.to_dict(include_children=True) if direction else None,
    }


@router.get("/union-delegation")
def get_union_delegation(
    user: dict = require_perms("itcj", ["core.departments.api.read.hierarchy"]),
    db: DbSession = None,
):
    """Obtiene la delegación sindical."""
    from itcj.core.services import departments_service as svc

    union_delegation = svc.get_union_delegation()
    return {
        "status": "ok",
        "data": union_delegation.to_dict(include_children=True) if union_delegation else None,
    }


@router.get("/subdirections")
def list_subdirections(
    user: dict = require_perms("itcj", ["core.departments.api.read.hierarchy"]),
    db: DbSession = None,
):
    """Lista solo las subdirecciones (departamentos de segundo nivel)."""
    from itcj.core.services import departments_service as svc

    subdirs = svc.list_subdirections()
    return {"status": "ok", "data": [d.to_dict(include_children=True) for d in subdirs]}


@router.get("/parent-options")
def list_parent_options(
    user: dict = require_perms("itcj", ["core.departments.api.read"]),
    db: DbSession = None,
):
    """Lista departamentos disponibles como padres (dirección y subdirecciones)."""
    from itcj.core.services import departments_service as svc

    options = svc.list_parent_options()
    return {"status": "ok", "data": [d.to_dict() for d in options]}


@router.get("/by-parent")
def list_by_parent(
    parent_id: Optional[int] = None,
    user: dict = require_perms("itcj", ["core.departments.api.read"]),
    db: DbSession = None,
):
    """Lista departamentos filtrados por parent_id."""
    from itcj.core.services import departments_service as svc

    depts = svc.list_departments_by_parent(parent_id)
    return {"status": "ok", "data": [d.to_dict() for d in depts]}


# ── CRUD ──────────────────────────────────────────────────────────────────────

@router.get("")
def list_departments(
    user: dict = require_perms("itcj", ["core.departments.api.read"]),
    db: DbSession = None,
):
    """Lista todos los departamentos."""
    from itcj.core.services import departments_service as svc

    depts = svc.list_departments()
    return {"status": "ok", "data": [d.to_dict() for d in depts]}


@router.get("/{dept_id}")
def get_department(
    dept_id: int,
    user: dict = require_perms("itcj", ["core.departments.api.read"]),
    db: DbSession = None,
):
    """Obtiene detalle completo de un departamento con posiciones y usuario actual."""
    from itcj.core.services import departments_service as dept_svc
    from itcj.core.services import positions_service as pos_svc

    dept = dept_svc.get_department(dept_id)
    if not dept:
        raise HTTPException(404, detail={"status": "error", "error": "not_found"})

    positions = dept_svc.get_department_positions(dept_id)
    positions_data = [
        {
            "id": p.id,
            "code": p.code,
            "title": p.title,
            "description": p.description,
            "email": p.email,
            "department_id": p.department_id,
            "is_active": p.is_active,
            "allows_multiple": p.allows_multiple,
            "current_user": pos_svc.get_position_current_user(p.id),
        }
        for p in positions
    ]

    return {
        "status": "ok",
        "data": {
            **dept.to_dict(include_children=True),
            "positions": positions_data,
        },
    }


@router.post("", status_code=201)
def create_department(
    body: DepartmentCreateBody,
    user: dict = require_perms("itcj", ["core.departments.api.create"]),
    db: DbSession = None,
):
    """Crea un nuevo departamento."""
    from itcj.core.services import departments_service as svc

    code = body.code.strip()
    name = body.name.strip()
    if not code or not name:
        raise HTTPException(400, detail={"status": "error", "error": "code_and_name_required"})

    try:
        dept = svc.create_department(
            code,
            name,
            body.description.strip() if body.description else None,
            body.parent_id,
            body.icon_class.strip() if body.icon_class else None,
        )
        logger.info(f"Departamento '{name}' creado por usuario {int(user['sub'])}")
        return {"status": "ok", "data": dept.to_dict()}
    except ValueError as e:
        raise HTTPException(409, detail={"status": "error", "error": str(e)})


@router.patch("/{dept_id}")
def update_department(
    dept_id: int,
    body: DepartmentUpdateBody,
    user: dict = require_perms("itcj", ["core.departments.api.update"]),
    db: DbSession = None,
):
    """Actualiza un departamento."""
    from itcj.core.services import departments_service as svc

    updates = body.model_dump(exclude_none=True)
    try:
        dept = svc.update_department(dept_id, **updates)
        logger.info(f"Departamento {dept_id} actualizado por usuario {int(user['sub'])}")
        return {"status": "ok", "data": dept.to_dict()}
    except ValueError as e:
        raise HTTPException(404, detail={"status": "error", "error": str(e)})


# ── Usuarios del departamento ─────────────────────────────────────────────────

@router.get("/{dept_id}/users")
def get_department_users(
    dept_id: int,
    user: dict = require_perms("itcj", ["core.departments.api.read"]),
    db: DbSession = None,
):
    """Obtiene usuarios asignados a un departamento con estadísticas."""
    from itcj.core.services import departments_service as dept_svc
    from itcj.core.models.position import Position, UserPosition
    from itcj.core.models.user import User
    from itcj.core.extensions import db as flask_db

    dept = dept_svc.get_department(dept_id)
    if not dept:
        raise HTTPException(404, detail={"status": "error", "error": "Department not found"})

    users_data = (
        flask_db.session.query(User, Position, UserPosition)
        .join(UserPosition, User.id == UserPosition.user_id)
        .join(Position, UserPosition.position_id == Position.id)
        .filter(
            Position.department_id == dept_id,
            Position.is_active == True,
            UserPosition.is_active == True,
            User.is_active == True,
        )
        .distinct(User.id)
        .all()
    )

    users_list = []
    seen_users: set[int] = set()

    for u, position, assignment in users_data:
        if u.id in seen_users:
            continue
        seen_users.add(u.id)

        ticket_count = 0
        try:
            from itcj.apps.helpdesk.models.ticket import Ticket
            ticket_count = Ticket.query.filter_by(
                requester_id=u.id, requester_department_id=dept_id
            ).count()
        except (ImportError, AttributeError):
            pass

        users_list.append({
            "id": u.id,
            "name": u.full_name,
            "full_name": u.full_name,
            "email": u.email,
            "username": u.username,
            "control_number": u.control_number,
            "is_active": u.is_active,
            "role": u.role.name if u.role else None,
            "position": {"id": position.id, "code": position.code, "title": position.title},
            "assignment": {
                "start_date": assignment.start_date.isoformat() if assignment.start_date else None,
                "notes": assignment.notes,
            },
            "ticket_count": ticket_count,
        })

    return {
        "status": "ok",
        "data": {"department": dept.to_dict(), "users": users_list, "total": len(users_list)},
    }
