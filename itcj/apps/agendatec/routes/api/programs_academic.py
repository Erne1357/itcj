# routes/api/programs_academic.py
"""
API de programas académicos para AgendaTec.

Este módulo contiene los endpoints para consulta de programas:
- Listar programas
- Obtener coordinadores de un programa
"""
from flask import Blueprint, jsonify, request

from itcj.apps.agendatec.models import db
from itcj.core.models.coordinator import Coordinator
from itcj.core.models.program import Program
from itcj.core.models.program_coordinator import ProgramCoordinator
from itcj.core.models.user import User
from itcj.core.utils.decorators import api_auth_required

api_programs_bp = Blueprint("api_programs", __name__)

def _parse_pagination():
    try:
        limit = int(request.args.get("limit", 100))
        offset = int(request.args.get("offset", 0))
        return max(1, min(limit, 500)), max(0, offset)
    except Exception:
        return 100, 0

@api_programs_bp.get("")
@api_auth_required
def list_programs():
    q = (request.args.get("q") or "").strip()
    limit, offset = _parse_pagination()
    query = db.session.query(Program)
    if q:
        query = query.filter(Program.name.ilike(f"%{q}%"))
    total = query.count()
    items = (query.order_by(Program.name.asc())
                  .limit(limit).offset(offset).all())
    return jsonify({
        "total": total, "limit": limit, "offset": offset,
        "items": [{"id": p.id, "name": p.name} for p in items]
    })

@api_programs_bp.get("/<int:program_id>/coordinator")
@api_auth_required
def program_coordinator(program_id: int):
    rows = (db.session.query(Coordinator, User)
            .join(ProgramCoordinator, ProgramCoordinator.coordinator_id==Coordinator.id)
            .join(User, User.id==Coordinator.user_id)
            .filter(ProgramCoordinator.program_id==program_id)
            .all())
    data = [{
        "coordinator_id": c.id,
        "user_id": u.id,
        "full_name": u.full_name,
        "email": c.contact_email or u.email,
        "office_hours": c.office_hours or "",
        "username": getattr(u, "username", None)
    } for c,u in rows]
    return jsonify({"program_id": program_id, "coordinators": data})
