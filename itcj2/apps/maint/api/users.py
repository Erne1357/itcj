"""
Endpoints de usuarios para la app maint.

Búsqueda de usuarios para el selector "Solicitar para" del formulario de
creación de tickets (crear en nombre de un tercero). Mantenimiento atiende a
TODO el instituto, así que el solicitante puede ser de cualquier departamento.
"""
import logging

from fastapi import APIRouter, HTTPException

from itcj2.dependencies import DbSession, require_perms

router = APIRouter(tags=["maint-users"])
logger = logging.getLogger(__name__)


# ==================== BÚSQUEDA DE USUARIOS ====================

@router.get("")
def search_users(
    search: str = None,
    department_id: int = None,
    user: dict = require_perms("maint", ["maint.tickets.api.create.behalf"]),
    db: DbSession = None,
):
    """Busca usuarios activos del instituto para el selector "Solicitar para".

    Solo accesible para quien puede crear en nombre de otro (puesto del jefe
    o secretaría de mantenimiento; admin global).

    - `search`: término (>=2 chars) que busca en nombre, apellido, usuario,
      correo o número de control en TODO el instituto. Es lo normal en este
      flujo porque mantenimiento atiende a cualquier departamento.
    - `department_id`: alternativa para listar usuarios de un depto concreto.

    Devuelve hasta 50 usuarios con su departamento (para contexto visual).
    """
    from sqlalchemy import or_, func
    from itcj2.core.models.user import User
    from itcj2.core.models.position import Position, UserPosition
    from itcj2.core.models.department import Department

    term = (search or "").strip()
    if not term and not department_id:
        raise HTTPException(
            status_code=400,
            detail="Indica un término de búsqueda (search) o un department_id",
        )
    if term and len(term) < 2:
        return {"success": True, "data": [], "total": 0}

    q = (
        db.query(
            User.id, User.first_name, User.last_name, User.email,
            Department.name.label("dept_name"),
        )
        .outerjoin(UserPosition, (UserPosition.user_id == User.id) & (UserPosition.is_active == True))
        .outerjoin(Position, (Position.id == UserPosition.position_id) & (Position.is_active == True))
        .outerjoin(Department, Department.id == Position.department_id)
        .filter(User.is_active == True)
    )

    if term:
        like = f"%{term}%"
        q = q.filter(or_(
            User.first_name.ilike(like),
            User.last_name.ilike(like),
            User.username.ilike(like),
            User.email.ilike(like),
            User.control_number.ilike(like),
            func.concat(User.first_name, " ", User.last_name).ilike(like),
        ))
    elif department_id:
        q = q.filter(Position.department_id == department_id)

    rows = (
        q.order_by(User.last_name.asc(), User.first_name.asc())
        .limit(150)
        .all()
    )

    data = []
    seen: set = set()
    for user_id, first_name, last_name, email, dept_name in rows:
        if user_id in seen:
            continue
        seen.add(user_id)
        full_name = f"{first_name or ''} {last_name or ''}".strip()
        data.append({
            "id": user_id,
            "name": full_name or str(user_id),
            "email": email,
            "department": dept_name,
        })
        if len(data) >= 50:
            break

    return {"success": True, "data": data, "total": len(data)}
