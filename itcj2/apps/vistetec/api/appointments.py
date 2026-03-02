"""
Appointments API v2 — 8 endpoints (estudiantes y voluntarios).
Fuente: itcj/apps/vistetec/routes/api/appointments.py
"""
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException
from itcj2.dependencies import DbSession, require_perms
from itcj2.apps.vistetec.schemas.appointments import (
    CreateAppointmentBody,
    AttendanceBody,
    CompleteAppointmentBody,
)

router = APIRouter(tags=["vistetec-appointments"])
logger = logging.getLogger(__name__)


# ── Endpoints para estudiantes ────────────────────────────────────────────────

@router.get("/my-appointments")
def list_my_appointments(
    status: Optional[str] = None,
    include_past: bool = False,
    user: dict = require_perms("vistetec", ["vistetec.appointments.api.view_own"]),
    db: DbSession = None,
):
    """Lista mis citas como estudiante."""
    from itcj2.apps.vistetec.services import appointment_service

    appointments = appointment_service.get_student_appointments(
        student_id=user["sub"],
        status=status,
        include_past=include_past,
    )
    return [a.to_dict(include_relations=True) for a in appointments]


@router.post("", status_code=201)
def create_appointment(
    body: CreateAppointmentBody,
    user: dict = require_perms("vistetec", ["vistetec.appointments.api.create"]),
    db: DbSession = None,
):
    """Crea una nueva cita."""
    from itcj2.apps.vistetec.services import appointment_service

    try:
        appointment = appointment_service.create_appointment(
            student_id=user["sub"],
            garment_id=body.garment_id,
            slot_id=body.slot_id,
            will_bring_donation=body.will_bring_donation,
        )
        logger.info(f"Cita creada por estudiante {user['sub']}, prenda {body.garment_id}")
        return {
            "message": "Cita agendada exitosamente",
            "appointment": appointment.to_dict(include_relations=True),
        }
    except ValueError as e:
        raise HTTPException(400, detail={"error": "validation_error", "message": str(e)})


@router.post("/{appointment_id}/cancel")
def cancel_my_appointment(
    appointment_id: int,
    user: dict = require_perms("vistetec", ["vistetec.appointments.api.cancel"]),
    db: DbSession = None,
):
    """Cancela mi cita como estudiante."""
    from itcj2.apps.vistetec.services import appointment_service

    try:
        appointment = appointment_service.cancel_appointment(
            appointment_id=appointment_id,
            user_id=int(user["sub"]),
            is_volunteer=False,
        )
        return {
            "message": "Cita cancelada",
            "appointment": appointment.to_dict(include_relations=True),
        }
    except ValueError as e:
        raise HTTPException(400, detail={"error": "validation_error", "message": str(e)})


# ── Endpoints para voluntarios ────────────────────────────────────────────────

@router.get("/volunteer/list")
def list_volunteer_appointments(
    date: Optional[str] = None,
    status: Optional[str] = None,
    user: dict = require_perms("vistetec", ["vistetec.appointments.api.view_all"]),
    db: DbSession = None,
):
    """Lista citas de los slots del voluntario."""
    from itcj2.apps.vistetec.services import appointment_service

    date_filter = datetime.fromisoformat(date).date() if date else None

    appointments = appointment_service.get_volunteer_appointments(
        volunteer_id=user["sub"],
        date_filter=date_filter,
        status=status,
    )
    return [a.to_dict(include_relations=True) for a in appointments]


@router.get("/volunteer/today")
def list_today_appointments(
    user: dict = require_perms("vistetec", ["vistetec.appointments.api.view_all"]),
    db: DbSession = None,
):
    """Lista citas de hoy para el voluntario."""
    from itcj2.apps.vistetec.services import appointment_service

    appointments = appointment_service.get_today_appointments_for_volunteer(user["sub"])
    return [a.to_dict(include_relations=True) for a in appointments]


@router.post("/{appointment_id}/attendance")
def mark_attendance(
    appointment_id: int,
    body: AttendanceBody,
    user: dict = require_perms("vistetec", ["vistetec.appointments.api.attend"]),
    db: DbSession = None,
):
    """Marca asistencia de una cita."""
    from itcj2.apps.vistetec.services import appointment_service

    try:
        appointment = appointment_service.mark_attendance(
            appointment_id=appointment_id,
            volunteer_id=user["sub"],
            attended=body.attended,
        )
        return {
            "message": "Asistencia registrada",
            "appointment": appointment.to_dict(include_relations=True),
        }
    except ValueError as e:
        raise HTTPException(400, detail={"error": "validation_error", "message": str(e)})


@router.post("/{appointment_id}/complete")
def complete_appointment(
    appointment_id: int,
    body: CompleteAppointmentBody,
    user: dict = require_perms("vistetec", ["vistetec.appointments.api.attend"]),
    db: DbSession = None,
):
    """Completa una cita con el resultado."""
    from itcj2.apps.vistetec.services import appointment_service

    try:
        appointment = appointment_service.complete_appointment(
            appointment_id=appointment_id,
            volunteer_id=user["sub"],
            outcome=body.outcome,
            notes=body.notes,
        )
        return {
            "message": "Cita completada",
            "appointment": appointment.to_dict(include_relations=True),
        }
    except ValueError as e:
        raise HTTPException(400, detail={"error": "validation_error", "message": str(e)})


@router.post("/volunteer/{appointment_id}/cancel")
def volunteer_cancel_appointment(
    appointment_id: int,
    user: dict = require_perms("vistetec", ["vistetec.appointments.api.attend"]),
    db: DbSession = None,
):
    """Cancela una cita como voluntario."""
    from itcj2.apps.vistetec.services import appointment_service

    try:
        appointment = appointment_service.cancel_appointment(
            appointment_id=appointment_id,
            user_id=user["sub"],
            is_volunteer=True,
        )
        return {
            "message": "Cita cancelada",
            "appointment": appointment.to_dict(),
        }
    except ValueError as e:
        raise HTTPException(400, detail={"error": "validation_error", "message": str(e)})


# ── Stats ─────────────────────────────────────────────────────────────────────

@router.get("/stats")
def get_appointment_stats(
    user: dict = require_perms("vistetec", ["vistetec.appointments.api.view_own"]),
    db: DbSession = None,
):
    """Estadísticas de citas. Voluntarios ven sus propias stats."""
    from itcj2.apps.vistetec.services import appointment_service
    from itcj2.core.services.authz_service import user_roles_in_app

    user_id = int(user["sub"])
    user_roles = user_roles_in_app(user_id, "vistetec")

    volunteer_id = user_id if "volunteer" in user_roles else None

    return appointment_service.get_appointment_stats(volunteer_id=volunteer_id)
