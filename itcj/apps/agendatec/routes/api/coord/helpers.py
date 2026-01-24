# routes/api/coord/helpers.py
"""
Funciones helper compartidas para endpoints de coordinadores.

Este módulo contiene funciones de utilidad que son usadas por
múltiples endpoints del módulo coord.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional, Set

from flask import g

from itcj.apps.agendatec.config import DEFAULT_STAFF_PASSWORD
from itcj.apps.agendatec.models import db
from itcj.apps.agendatec.models.availability_window import AvailabilityWindow
from itcj.core.models.coordinator import Coordinator
from itcj.core.models.program_coordinator import ProgramCoordinator
from itcj.core.models.user import User

# Usar constante desde config
DEFAULT_NIP = DEFAULT_STAFF_PASSWORD


def get_current_user() -> Optional[User]:
    """
    Obtiene el usuario actualmente autenticado.

    Returns:
        El objeto User si existe, None en caso contrario.
    """
    try:
        uid = int(g.current_user["sub"])
    except Exception:
        return None
    return db.session.query(User).get(uid)


def get_current_coordinator_id() -> Optional[int]:
    """
    Obtiene el ID del coordinador asociado al usuario autenticado.

    Returns:
        El coordinator_id si el usuario es coordinador, None en caso contrario.
    """
    try:
        uid = int(g.current_user["sub"])
    except Exception:
        return None
    u = db.session.query(User).get(uid)
    if not u:
        return None
    c = db.session.query(Coordinator).filter_by(user_id=u.id).first()
    return c.id if c else None


def get_coord_program_ids(coord_id: int) -> Set[int]:
    """
    Obtiene los IDs de programas asignados a un coordinador.

    Args:
        coord_id: ID del coordinador

    Returns:
        Conjunto de program_ids asignados al coordinador.
    """
    rows = (
        db.session.query(ProgramCoordinator.program_id)
        .filter(ProgramCoordinator.coordinator_id == coord_id)
        .all()
    )
    return {r[0] for r in rows}


def split_or_delete_windows(
    coord_id: int,
    d: date,
    time_ge: datetime.time,
    time_lt: datetime.time
) -> dict:
    """
    Para cada AvailabilityWindow que se solape con [time_ge, time_lt):
    - Elimina la ventana original
    - Recrea hasta dos ventanas 'no solapadas':
        [start_time, time_ge)  y  [time_lt, end_time)
      conservando slot_minutes

    Args:
        coord_id: ID del coordinador
        d: Fecha del día
        time_ge: Hora de inicio del rango a eliminar
        time_lt: Hora de fin del rango a eliminar

    Returns:
        Dict con windows_deleted y windows_created
    """
    overlapping = (
        db.session.query(AvailabilityWindow)
        .filter(
            AvailabilityWindow.coordinator_id == coord_id,
            AvailabilityWindow.day == d,
            ~(
                (AvailabilityWindow.end_time <= time_ge) |
                (AvailabilityWindow.start_time >= time_lt)
            )
        ).all()
    )
    recreated = 0
    deleted = 0
    for w in overlapping:
        left_start, left_end = w.start_time, min(w.end_time, time_ge)
        right_start, right_end = max(w.start_time, time_lt), w.end_time

        # Eliminar original
        db.session.delete(w)
        deleted += 1

        # Recrear izquierda
        if left_start < left_end:
            db.session.add(AvailabilityWindow(
                coordinator_id=coord_id,
                day=d,
                start_time=left_start,
                end_time=left_end,
                slot_minutes=w.slot_minutes
            ))
            recreated += 1

        # Recrear derecha
        if right_start < right_end:
            db.session.add(AvailabilityWindow(
                coordinator_id=coord_id,
                day=d,
                start_time=right_start,
                end_time=right_end,
                slot_minutes=w.slot_minutes
            ))
            recreated += 1

    return {"windows_deleted": deleted, "windows_created": recreated}
