"""
Admin Users API v2 — Gestión de coordinadores y estudiantes.
Fuente: itcj/apps/agendatec/routes/api/admin/users.py
"""
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.orm import joinedload

from itcj2.dependencies import DbSession, require_perms
from itcj2.apps.agendatec.schemas.admin import CreateCoordinatorBody, UpdateCoordinatorBody
from itcj2.apps.agendatec.config import DEFAULT_STAFF_PASSWORD
from itcj2.apps.agendatec.models.audit_log import AuditLog
from itcj2.core.models.app import App
from itcj2.core.models.coordinator import Coordinator
from itcj2.core.models.program import Program
from itcj2.core.models.program_coordinator import ProgramCoordinator
from itcj2.core.models.role import Role
from itcj2.core.models.user import User
from itcj2.core.models.user_app_role import UserAppRole
from itcj2.core.utils.security import hash_nip

router = APIRouter(tags=["agendatec-admin-users"])
logger = logging.getLogger(__name__)

ReadPerm = require_perms("agendatec", ["agendatec.users.api.read"])
CreatePerm = require_perms("agendatec", ["agendatec.users.api.create"])
UpdatePerm = require_perms("agendatec", ["agendatec.users.api.update"])


# ==================== GET /users/search ====================

@router.get("/users/search")
def search_users_for_coordinator(
    q: str = Query(""),
    limit: int = Query(20, ge=1, le=50),
    user: dict = ReadPerm,
    db: DbSession = None,
):
    """Busca usuarios existentes (staff) para asignar como coordinadores."""
    term = q.strip().lower()
    if len(term) < 2:
        return {"items": []}

    existing_coord_users = db.query(Coordinator.user_id).subquery()
    pattern = f"%{term}%"

    users = (
        db.query(User)
        .filter(
            User.is_active == True,
            User.control_number == None,
            ~User.id.in_(existing_coord_users),
            or_(
                User.full_name.ilike(pattern),
                User.email.ilike(pattern),
                User.username.ilike(pattern),
            ),
        )
        .order_by(User.full_name.asc())
        .limit(limit)
        .all()
    )

    return {
        "items": [
            {"id": u.id, "full_name": u.full_name, "email": u.email, "username": u.username}
            for u in users
        ]
    }


# ==================== GET /users/students ====================

@router.get("/users/students")
def list_students(
    q: str = Query(""),
    user: dict = ReadPerm,
    db: DbSession = None,
):
    """Lista estudiantes para usar en combos de admin."""
    base = (
        db.query(User)
        .join(UserAppRole, UserAppRole.user_id == User.id)
        .join(App, App.id == UserAppRole.app_id)
        .join(Role, Role.id == UserAppRole.role_id)
        .filter(App.key == "agendatec", Role.name == "student")
    )

    if q.strip():
        base = base.filter(
            or_(
                User.full_name.ilike(f"%{q}%"),
                User.control_number.ilike(f"%{q}%"),
                User.username.ilike(f"%{q}%"),
            )
        )

    students = base.order_by(User.full_name.asc()).all()

    items = [
        {
            "id": s.id,
            "full_name": s.full_name,
            "name": s.full_name,
            "control_number": s.control_number,
            "username": s.username,
            "email": s.email,
        }
        for s in students
    ]
    return {"items": items, "students": items}


# ==================== GET /users/coordinators ====================

@router.get("/users/coordinators")
def list_coordinators(
    q: str = Query(""),
    program_id: Optional[int] = Query(None),
    user: dict = ReadPerm,
    db: DbSession = None,
):
    """Lista coordinadores con sus programas."""
    base = db.query(Coordinator).options(joinedload(Coordinator.user))

    if q.strip():
        base = base.join(User).filter(
            or_(User.full_name.ilike(f"%{q}%"), User.email.ilike(f"%{q}%"))
        )

    rows = base.all()

    prog_map = {}
    if rows:
        coord_ids = [c.id for c in rows]
        links = (
            db.query(ProgramCoordinator.coordinator_id, Program.id, Program.name)
            .join(Program, Program.id == ProgramCoordinator.program_id)
            .filter(ProgramCoordinator.coordinator_id.in_(coord_ids))
            .all()
        )
        for cid, pid, pname in links:
            prog_map.setdefault(cid, []).append({"id": pid, "name": pname})

    items = []
    for c in rows:
        progs = prog_map.get(c.id, [])
        if program_id and all(p["id"] != program_id for p in progs):
            continue
        items.append({
            "id": c.id,
            "user_id": c.user_id,
            "name": c.user.full_name,
            "email": c.contact_email,
            "programs": progs,
        })

    return {"items": items}


# ==================== POST /users/coordinators ====================

@router.post("/users/coordinators")
def create_coordinator(
    body: CreateCoordinatorBody,
    user: dict = CreatePerm,
    db: DbSession = None,
):
    """
    Crea un coordinador. Dos modos:
    1. Con usuario existente: enviar user_id.
    2. Creando nuevo usuario: enviar name, email, username.
    """
    from itcj2.core.services import authz_service

    created_new_user = False

    if body.user_id:
        u = db.query(User).filter_by(id=body.user_id, is_active=True).first()
        if not u:
            raise HTTPException(status_code=404, detail="user_not_found")

        existing = db.query(Coordinator).filter_by(user_id=body.user_id).first()
        if existing:
            raise HTTPException(
                status_code=409,
                detail={"error": "already_coordinator", "coordinator_id": existing.id},
            )
    else:
        name = (body.name or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="missing_name")

        name_parts = name.split()
        if len(name_parts) < 2:
            raise HTTPException(status_code=400, detail="invalid_name_format")

        if len(name_parts) >= 3:
            first_name = " ".join(name_parts[:-2]).upper()
            last_name = name_parts[-2].upper()
            middle_name = name_parts[-1].upper()
        else:
            first_name = name_parts[0].upper()
            last_name = name_parts[-1].upper()
            middle_name = None

        username = (body.username or "").strip() or None
        if username:
            if db.query(User).filter_by(username=username).first():
                raise HTTPException(status_code=409, detail="username_exists")

        u = User(
            first_name=first_name,
            last_name=last_name,
            middle_name=middle_name,
            email=(body.email or "").strip() or None,
            username=username,
            control_number=None,
            role_id=None,
            password_hash=hash_nip(DEFAULT_STAFF_PASSWORD),
            must_change_password=True,
        )
        db.add(u)
        db.flush()
        created_new_user = True

    c = Coordinator(
        user_id=u.id,
        contact_email=(body.email or "").strip() or u.email or None,
        must_change_pw=True,
    )
    db.add(c)
    db.flush()

    if body.program_ids:
        valid_ids = [
            pid for (pid,) in db.query(Program.id).filter(Program.id.in_(body.program_ids)).all()
        ]
        for pid in valid_ids:
            db.add(ProgramCoordinator(program_id=pid, coordinator_id=c.id))

    try:
        authz_service.grant_role(u.id, "agendatec", "coordinator")
    except Exception as e:
        logger.warning(f"No se pudo asignar rol coordinator: {e}")

    if created_new_user:
        try:
            authz_service.grant_role(u.id, "itcj", "staff")
        except Exception as e:
            logger.warning(f"No se pudo asignar rol staff: {e}")

    actor_id = user.get("sub")
    db.add(
        AuditLog(
            actor_id=actor_id,
            entity="coordinator",
            entity_id=c.id,
            action="create",
            payload_json={
                "created_new_user": created_new_user,
                "user_id": u.id,
                "program_ids": body.program_ids,
            },
        )
    )
    db.commit()

    return {
        "id": c.id,
        "user_id": u.id,
        "created_new_user": created_new_user,
        "message": "Coordinador creado exitosamente",
    }


# ==================== PATCH /users/coordinators/<coord_id> ====================

@router.patch("/users/coordinators/{coord_id}")
def update_coordinator(
    coord_id: int,
    body: UpdateCoordinatorBody,
    user: dict = UpdatePerm,
    db: DbSession = None,
):
    """Actualiza un coordinador existente."""
    c = (
        db.query(Coordinator)
        .options(joinedload(Coordinator.user))
        .filter(Coordinator.id == coord_id)
        .first()
    )
    if not c:
        raise HTTPException(status_code=404, detail="not_found")

    before = {"name": c.user.full_name, "email": c.contact_email}

    if body.name is not None and body.name.strip():
        name_parts = body.name.strip().split()
        if len(name_parts) >= 2:
            if len(name_parts) >= 3:
                c.user.first_name = " ".join(name_parts[:-2]).upper()
                c.user.last_name = name_parts[-2].upper()
                c.user.middle_name = name_parts[-1].upper()
            else:
                c.user.first_name = name_parts[0].upper()
                c.user.last_name = name_parts[-1].upper()
                c.user.middle_name = None

    if body.email is not None:
        c.contact_email = body.email.strip() or None

    if body.program_ids is not None:
        db.query(ProgramCoordinator).filter(
            ProgramCoordinator.coordinator_id == c.id
        ).delete()
        if body.program_ids:
            valid_ids = [
                pid
                for (pid,) in db.query(Program.id)
                .filter(Program.id.in_(body.program_ids))
                .all()
            ]
            for pid in valid_ids:
                db.add(ProgramCoordinator(program_id=pid, coordinator_id=c.id))

    after = {"name": c.user.full_name, "email": c.contact_email, "program_ids": body.program_ids}
    actor_id = user.get("sub")
    db.add(
        AuditLog(
            actor_user_id=actor_id,
            entity="coordinator",
            entity_id=c.id,
            action="update",
            from_json=before,
            to_json=after,
        )
    )
    db.commit()
    return {"ok": True}
