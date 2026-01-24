# routes/api/admin/users.py
"""
Endpoints para gestión de usuarios (coordinadores y estudiantes).

Incluye:
- search_users_for_coordinator: Buscar usuarios para asignar como coordinadores
- create_coordinator: Crear nuevo coordinador
- update_coordinator: Actualizar coordinador existente
- list_students: Listar estudiantes
- list_coordinators: Listar coordinadores
"""
from __future__ import annotations

from typing import Optional

from flask import Blueprint, current_app, g, jsonify, request
from sqlalchemy import or_
from sqlalchemy.orm import joinedload

from itcj.apps.agendatec.config import DEFAULT_STAFF_PASSWORD
from itcj.apps.agendatec.models import db
from itcj.apps.agendatec.models.audit_log import AuditLog
from itcj.core.models.app import App
from itcj.core.models.coordinator import Coordinator
from itcj.core.models.program import Program
from itcj.core.models.program_coordinator import ProgramCoordinator
from itcj.core.models.role import Role
from itcj.core.models.user import User
from itcj.core.models.user_app_role import UserAppRole
from itcj.core.utils.decorators import api_app_required, api_auth_required
from itcj.core.utils.security import hash_nip

admin_users_bp = Blueprint("admin_users", __name__)


@admin_users_bp.get("/users/search")
@api_auth_required
@api_app_required(app_key="agendatec", perms=["agendatec.users.api.read"])
def search_users_for_coordinator():
    """
    Busca usuarios existentes (staff) para asignar como coordinadores.
    Excluye usuarios que ya son coordinadores.

    Query params:
        q: Texto de búsqueda (nombre, email, username)
        limit: Máximo de resultados (default 20)

    Returns:
        JSON con lista de usuarios
    """
    q = (request.args.get("q") or "").strip().lower()
    limit = min(int(request.args.get("limit", 20)), 50)

    if len(q) < 2:
        return jsonify({"items": []})

    existing_coord_users = db.session.query(Coordinator.user_id).subquery()

    base = (
        db.session.query(User)
        .filter(
            User.is_active == True,
            User.control_number == None,
            ~User.id.in_(existing_coord_users)
        )
    )

    search_pattern = f"%{q}%"
    base = base.filter(
        or_(
            User.full_name.ilike(search_pattern),
            User.email.ilike(search_pattern),
            User.username.ilike(search_pattern)
        )
    )

    users = base.order_by(User.full_name.asc()).limit(limit).all()

    items = []
    for u in users:
        items.append({
            "id": u.id,
            "full_name": u.full_name,
            "email": u.email,
            "username": u.username
        })

    return jsonify({"items": items})


@admin_users_bp.post("/users/coordinators")
@api_auth_required
@api_app_required(app_key="agendatec", perms=["agendatec.users.api.create"])
def create_coordinator():
    """
    Crea un coordinador de dos formas:
    1. Con usuario existente: enviar user_id
    2. Creando nuevo usuario: enviar name, email, username (opcional)

    Body JSON:
        user_id: ID de usuario existente (opcional)
        name: Nombre completo (requerido si no hay user_id)
        email: Email (opcional)
        username: Username (opcional)
        program_ids: Lista de IDs de programas a asignar

    Returns:
        JSON con id, user_id y mensaje
    """
    from itcj.core.services import authz_service

    data = request.get_json(silent=True) or {}
    user_id: Optional[int] = data.get("user_id")
    name: str = data.get("name", "").strip()
    email: str = data.get("email", "").strip()
    username: str = data.get("username", "").strip()
    program_ids: list[int] = data.get("program_ids", [])

    created_new_user = False

    if user_id:
        # MODO 1: Usuario existente
        u = db.session.query(User).filter_by(id=user_id, is_active=True).first()
        if not u:
            return jsonify({"error": "user_not_found", "message": "Usuario no encontrado"}), 404

        existing_coord = db.session.query(Coordinator).filter_by(user_id=user_id).first()
        if existing_coord:
            return jsonify({
                "error": "already_coordinator",
                "message": "Este usuario ya es coordinador",
                "coordinator_id": existing_coord.id
            }), 409

    else:
        # MODO 2: Crear nuevo usuario
        if not name:
            return jsonify({"error": "missing_name", "message": "El nombre es requerido"}), 400

        name_parts = name.strip().split()
        if len(name_parts) < 2:
            return jsonify({"error": "invalid_name_format", "message": "El nombre debe tener al menos nombre y apellido"}), 400

        if len(name_parts) >= 3:
            first_name = ' '.join(name_parts[:-2]).upper()
            last_name = name_parts[-2].upper()
            middle_name = name_parts[-1].upper()
        else:
            first_name = name_parts[0].upper()
            last_name = name_parts[-1].upper()
            middle_name = None

        if username:
            existing_user = db.session.query(User).filter_by(username=username).first()
            if existing_user:
                return jsonify({"error": "username_exists", "message": "El nombre de usuario ya existe"}), 409

        u = User(
            first_name=first_name,
            last_name=last_name,
            middle_name=middle_name,
            email=email or None,
            username=username or None,
            control_number=None,
            role_id=None,
            password_hash=hash_nip(DEFAULT_STAFF_PASSWORD),
            must_change_password=True
        )
        db.session.add(u)
        db.session.flush()
        created_new_user = True

    # Crear registro Coordinator
    c = Coordinator(
        user_id=u.id,
        contact_email=email or u.email or None,
        must_change_pw=True
    )
    db.session.add(c)
    db.session.flush()

    # Asignar programas
    if program_ids:
        valid_programs = db.session.query(Program.id).filter(Program.id.in_(program_ids)).all()
        valid_ids = [pid for (pid,) in valid_programs]
        for pid in valid_ids:
            db.session.add(ProgramCoordinator(program_id=pid, coordinator_id=c.id))

    # Asignar roles usando authz_service
    try:
        authz_service.grant_role(u.id, "agendatec", "coordinator")
    except Exception as e:
        current_app.logger.warning(f"No se pudo asignar rol coordinator en agendatec: {e}")

    if created_new_user:
        try:
            authz_service.grant_role(u.id, "itcj", "staff")
        except Exception as e:
            current_app.logger.warning(f"No se pudo asignar rol staff en itcj: {e}")

    # Audit log
    actor_id = g.current_user.get("sub") if getattr(g, "current_user", None) else None
    db.session.add(
        AuditLog(
            actor_id=actor_id,
            entity="coordinator",
            entity_id=c.id,
            action="create",
            payload_json={
                "created_new_user": created_new_user,
                "user_id": u.id,
                "program_ids": program_ids
            },
        )
    )
    db.session.commit()

    return jsonify({
        "id": c.id,
        "user_id": u.id,
        "created_new_user": created_new_user,
        "message": "Coordinador creado exitosamente"
    })


@admin_users_bp.patch("/users/coordinators/<int:coord_id>")
@api_auth_required
@api_app_required(app_key="agendatec", perms=["agendatec.users.api.update"])
def update_coordinator(coord_id: int):
    """
    Actualiza un coordinador existente.

    Body JSON:
        name: Nuevo nombre (opcional)
        email: Nuevo email (opcional)
        program_ids: Nueva lista de programas (opcional)

    Returns:
        JSON con ok: True
    """
    data = request.get_json(silent=True) or {}
    name: Optional[str] = data.get("name")
    email: Optional[str] = data.get("email")
    program_ids: Optional[list[int]] = data.get("program_ids")

    c = db.session.query(Coordinator).options(joinedload(Coordinator.user)).filter(Coordinator.id == coord_id).first()
    if not c:
        return jsonify({"error": "not_found"}), 404

    before = {"name": c.user.full_name, "email": c.contact_email}

    if name is not None and name.strip():
        name_parts = name.strip().split()
        if len(name_parts) >= 2:
            if len(name_parts) >= 3:
                c.user.first_name = ' '.join(name_parts[:-2]).upper()
                c.user.last_name = name_parts[-2].upper()
                c.user.middle_name = name_parts[-1].upper()
            else:
                c.user.first_name = name_parts[0].upper()
                c.user.last_name = name_parts[-1].upper()
                c.user.middle_name = None

    if email is not None:
        c.contact_email = email.strip() or None

    if program_ids is not None:
        db.session.query(ProgramCoordinator).filter(ProgramCoordinator.coordinator_id == c.id).delete()
        if program_ids:
            valid_programs = db.session.query(Program.id).filter(Program.id.in_(program_ids)).all()
            valid_ids = [pid for (pid,) in valid_programs]
            for pid in valid_ids:
                db.session.add(ProgramCoordinator(program_id=pid, coordinator_id=c.id))

    after = {"name": c.user.full_name, "email": c.contact_email, "program_ids": program_ids}
    actor_id = g.current_user.get("sub") if getattr(g, "current_user", None) else None
    db.session.add(
        AuditLog(
            actor_user_id=actor_id,
            entity="coordinator",
            entity_id=c.id,
            action="update",
            from_json=before,
            to_json=after,
        )
    )
    db.session.commit()
    return jsonify({"ok": True})


@admin_users_bp.get("/users/students")
@api_auth_required
@api_app_required(app_key="agendatec", perms=["agendatec.users.api.read"])
def list_students():
    """
    Lista estudiantes para usar en combos y formularios de admin.

    Query params:
        q: Texto para buscar por nombre o control_number

    Returns:
        JSON con items y students (ambas claves para compatibilidad)
    """
    q = (request.args.get("q") or "").strip().lower()

    base = (
        db.session.query(User)
        .join(UserAppRole, UserAppRole.user_id == User.id)
        .join(App, App.id == UserAppRole.app_id)
        .join(Role, Role.id == UserAppRole.role_id)
        .filter(App.key == "agendatec")
        .filter(Role.name == "student")
    )

    if q:
        base = base.filter(
            or_(
                User.full_name.ilike(f"%{q}%"),
                User.control_number.ilike(f"%{q}%"),
                User.username.ilike(f"%{q}%")
            )
        )

    students = base.order_by(User.full_name.asc()).all()

    items = []
    for s in students:
        items.append({
            "id": s.id,
            "full_name": s.full_name,
            "name": s.full_name,
            "control_number": s.control_number,
            "username": s.username,
            "email": s.email
        })

    return jsonify({"items": items, "students": items})


@admin_users_bp.get("/users/coordinators")
@api_auth_required
@api_app_required(app_key="agendatec", perms=["agendatec.users.api.read"])
def list_coordinators():
    """
    Lista coordinadores con sus programas.

    Query params:
        q: Texto para filtrar
        program_id: Filtrar por programa específico

    Returns:
        JSON con items
    """
    q = (request.args.get("q") or "").strip().lower()
    program_id = request.args.get("program_id", type=int)

    base = (
        db.session.query(Coordinator)
        .options(joinedload(Coordinator.user))
    )
    if q:
        base = base.join(User).filter(
            (User.full_name.ilike(f"%{q}%")) | (User.email.ilike(f"%{q}%"))
        )
    rows = base.all()

    # Programas por coordinador
    prog_map = {}
    if rows:
        coord_ids = [c.id for c in rows]
        links = (
            db.session.query(ProgramCoordinator.coordinator_id, Program.id, Program.name)
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

    return jsonify({"items": items})
