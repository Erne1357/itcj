"""Nombres de quienes firman o reciben las cartas, tomados de los puestos de core.

Se consultan al generar cada documento: cuando cambia el director, basta con
reasignar el puesto en core. Cada documento guarda sus valores, así que una carta
ya generada conserva el nombre con el que se hizo. El cargo va escrito en la plantilla.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from itcj2.core.models.position import Position
from itcj2.core.models.user import User
from itcj2.core.services import positions_service

# Marcador → (código del puesto en core, nombre para avisos).
PUESTOS = {
    "director_nombre": ("director", "Director"),
    "subdirector_nombre": ("head_sub_academic", "Subdirector Académico"),
    "subdirector_admin_nombre": ("subdirector_admin_services", "Subdirector de Servicios Administrativos"),
}


def titulares(db: Session) -> dict[str, str]:
    """``{marcador: "NOMBRE PATERNO MATERNO"}`` del titular activo; ``""`` si el puesto está vacante."""
    out = {}
    for marcador, (code, _) in PUESTOS.items():
        pid = db.query(Position.id).filter(Position.code == code, Position.is_active.is_(True)).scalar()
        cur = positions_service.get_position_current_user(db, pid) if pid else None
        u = db.get(User, cur["user_id"]) if cur else None
        out[marcador] = " ".join(filter(None, [u.first_name, u.last_name, u.middle_name])).upper() if u else ""
    return out


def vacantes(valores: dict[str, str]) -> list[str]:
    return [PUESTOS[m][1] for m, v in valores.items() if not v]
