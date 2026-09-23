"""Equipos de técnicos de Help-Desk (``desarrollo`` / ``soporte``).

El equipo de un usuario NO viene del JWT: sale de sus ROLES en la app
(``tech_desarrollo`` / ``tech_soporte``), y es el valor con el que se compara
``helpdesk_ticket.assigned_to_team`` (la cola sin asignar de ese equipo).

El mapeo estaba copiado en tres sitios (la pestaña "Equipo" del dashboard del
técnico, el guard fino de ``POST /tickets/{id}/split`` y —desde la fase 2 de
"Partir ticket"— las páginas de detalle, que se lo pasan al cliente). Aquí vive
una sola vez: si mañana aparece un tercer equipo, se toca este archivo.
"""
from __future__ import annotations

from typing import Iterable

# rol en helpdesk -> valor de `helpdesk_ticket.assigned_to_team`.
# El ORDEN importa: quien tenga los dos roles cuenta como "desarrollo" (mismo
# criterio que tenía el mapeo original en pages/technician.py).
TECH_TEAM_BY_ROLE: tuple[tuple[str, str], ...] = (
    ("tech_desarrollo", "desarrollo"),
    ("tech_soporte", "soporte"),
)


def tech_team(user_roles: Iterable[str] | None) -> str | None:
    """Equipo del usuario a partir de sus roles en helpdesk, o ``None``.

    ``None`` = no es técnico de ninguno de los dos equipos (un jefe de
    departamento, un solicitante…): no tiene cola de equipo que mirar.
    """
    roles = set(user_roles or ())
    for role, team in TECH_TEAM_BY_ROLE:
        if role in roles:
            return team
    return None


def tech_team_for_user(db, user_id: int) -> str | None:
    """``tech_team()`` resolviendo antes los roles del usuario en helpdesk."""
    from itcj2.core.services.authz_service import user_roles_in_app

    return tech_team(user_roles_in_app(db, user_id, "helpdesk"))
