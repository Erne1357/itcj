"""Servicio para gestión de citas."""

from datetime import date, datetime
from typing import Optional

from sqlalchemy import and_, func

from itcj.core.extensions import db
from itcj.apps.vistetec.models.appointment import Appointment
from itcj.apps.vistetec.models.time_slot import TimeSlot
from itcj.apps.vistetec.models.garment import Garment


def _generate_code() -> str:
    """Genera código único para cita: CIT-YYYY-NNNN."""
    year = datetime.now().year
    prefix = f"CIT-{year}-"

    last = Appointment.query.filter(
        Appointment.code.like(f"{prefix}%")
    ).order_by(Appointment.id.desc()).first()

    if last:
        last_num = int(last.code.split('-')[-1])
        new_num = last_num + 1
    else:
        new_num = 1

    return f"{prefix}{new_num:04d}"


def get_student_appointments(
    student_id: int,
    status: Optional[str] = None,
    include_past: bool = False
) -> list[Appointment]:
    """Obtiene las citas de un estudiante."""
    query = Appointment.query.filter(Appointment.student_id == student_id)

    if status:
        query = query.filter(Appointment.status == status)

    if not include_past:
        today = date.today()
        query = query.join(TimeSlot).filter(TimeSlot.date >= today)

    return query.order_by(Appointment.created_at.desc()).all()


def get_volunteer_appointments(
    volunteer_id: int,
    date_filter: Optional[date] = None,
    status: Optional[str] = None
) -> list[Appointment]:
    """Obtiene las citas para los slots de un voluntario."""
    query = Appointment.query.join(TimeSlot).filter(
        TimeSlot.volunteer_id == volunteer_id
    )

    if date_filter:
        query = query.filter(TimeSlot.date == date_filter)

    if status:
        query = query.filter(Appointment.status == status)

    return query.order_by(TimeSlot.date, TimeSlot.start_time).all()


def get_appointment_by_id(appointment_id: int) -> Optional[Appointment]:
    """Obtiene una cita por ID."""
    return Appointment.query.get(appointment_id)


def get_appointment_by_code(code: str) -> Optional[Appointment]:
    """Obtiene una cita por código."""
    return Appointment.query.filter_by(code=code).first()


def create_appointment(
    student_id: int,
    garment_id: int,
    slot_id: int
) -> Appointment:
    """Crea una nueva cita."""
    # Verificar que el slot existe y tiene disponibilidad
    slot = TimeSlot.query.get(slot_id)
    if not slot:
        raise ValueError("Horario no encontrado")

    if not slot.is_active:
        raise ValueError("Este horario ya no está disponible")

    if slot.is_full:
        raise ValueError("Este horario ya está lleno")

    # Verificar que el slot no ha pasado
    now = datetime.now()
    slot_datetime = datetime.combine(slot.date, slot.start_time)
    if slot_datetime <= now:
        raise ValueError("No puedes agendar citas en horarios pasados")

    # Verificar que la prenda existe y está disponible
    garment = Garment.query.get(garment_id)
    if not garment:
        raise ValueError("Prenda no encontrada")

    if garment.status != 'available':
        raise ValueError("Esta prenda ya no está disponible")

    # Verificar que el estudiante no tenga cita activa para esta prenda
    existing = Appointment.query.filter(
        Appointment.student_id == student_id,
        Appointment.garment_id == garment_id,
        Appointment.status.in_(['scheduled', 'attended'])
    ).first()

    if existing:
        raise ValueError("Ya tienes una cita activa para esta prenda")

    # Verificar que el estudiante no tenga demasiadas citas activas
    active_count = Appointment.query.filter(
        Appointment.student_id == student_id,
        Appointment.status == 'scheduled'
    ).count()

    if active_count >= 3:
        raise ValueError("Solo puedes tener máximo 3 citas activas")

    # Crear la cita
    appointment = Appointment(
        code=_generate_code(),
        student_id=student_id,
        garment_id=garment_id,
        slot_id=slot_id,
        location_id=slot.location_id,
        status='scheduled'
    )

    # Actualizar contador del slot
    slot.current_appointments += 1

    # Reservar la prenda
    garment.status = 'reserved'

    db.session.add(appointment)
    db.session.commit()

    return appointment


def cancel_appointment(
    appointment_id: int,
    user_id: int,
    is_volunteer: bool = False
) -> Appointment:
    """Cancela una cita (estudiante o voluntario)."""
    appointment = Appointment.query.get(appointment_id)
    if not appointment:
        raise ValueError("Cita no encontrada")

    # Verificar permisos
    if not is_volunteer and appointment.student_id != user_id:
        raise ValueError("No tienes permiso para cancelar esta cita")

    if is_volunteer:
        # Verificar que el voluntario es dueño del slot
        if appointment.slot.volunteer_id != user_id:
            raise ValueError("No tienes permiso para cancelar esta cita")

    if appointment.status not in ['scheduled']:
        raise ValueError("Esta cita no se puede cancelar")

    # Actualizar estado
    appointment.status = 'cancelled'

    # Liberar cupo del slot
    appointment.slot.current_appointments = max(0, appointment.slot.current_appointments - 1)

    # Liberar prenda
    appointment.garment.status = 'available'

    db.session.commit()

    return appointment


def mark_attendance(
    appointment_id: int,
    volunteer_id: int,
    attended: bool
) -> Appointment:
    """Marca asistencia de una cita."""
    appointment = Appointment.query.get(appointment_id)
    if not appointment:
        raise ValueError("Cita no encontrada")

    # Verificar que el voluntario es dueño del slot
    if appointment.slot.volunteer_id != volunteer_id:
        raise ValueError("No tienes permiso para modificar esta cita")

    if appointment.status != 'scheduled':
        raise ValueError("Esta cita no está en estado programado")

    appointment.status = 'attended' if attended else 'no_show'
    appointment.attended_by_id = volunteer_id
    appointment.attended_at = datetime.now()

    if not attended:
        # Si no asistió, liberar prenda
        appointment.garment.status = 'available'

    db.session.commit()

    return appointment


def complete_appointment(
    appointment_id: int,
    volunteer_id: int,
    outcome: str,
    notes: Optional[str] = None
) -> Appointment:
    """Completa una cita con el resultado."""
    valid_outcomes = ['taken', 'not_fit', 'declined']
    if outcome not in valid_outcomes:
        raise ValueError(f"Resultado inválido. Usa: {', '.join(valid_outcomes)}")

    appointment = Appointment.query.get(appointment_id)
    if not appointment:
        raise ValueError("Cita no encontrada")

    if appointment.slot.volunteer_id != volunteer_id:
        raise ValueError("No tienes permiso para modificar esta cita")

    if appointment.status != 'attended':
        raise ValueError("Primero debes marcar la asistencia")

    appointment.status = 'completed'
    appointment.outcome = outcome
    appointment.notes = notes

    if outcome == 'taken':
        # Estudiante se lleva la prenda
        appointment.garment.status = 'delivered'
        appointment.garment.delivered_to_id = appointment.student_id
        appointment.garment.delivered_at = datetime.now()
        appointment.garment.delivered_by_id = volunteer_id
    else:
        # No se llevó la prenda, liberarla
        appointment.garment.status = 'available'

    db.session.commit()

    return appointment


def get_today_appointments_for_volunteer(volunteer_id: int) -> list[Appointment]:
    """Obtiene las citas de hoy para un voluntario."""
    today = date.today()
    return Appointment.query.join(TimeSlot).filter(
        TimeSlot.volunteer_id == volunteer_id,
        TimeSlot.date == today,
        Appointment.status.in_(['scheduled', 'attended'])
    ).order_by(TimeSlot.start_time).all()


def get_appointment_stats(volunteer_id: Optional[int] = None) -> dict:
    """Obtiene estadísticas de citas."""
    base_query = Appointment.query

    if volunteer_id:
        base_query = base_query.join(TimeSlot).filter(
            TimeSlot.volunteer_id == volunteer_id
        )

    today = date.today()

    # Citas de hoy
    today_query = base_query.join(TimeSlot) if not volunteer_id else base_query
    today_count = today_query.filter(TimeSlot.date == today).count()

    # Por estado
    scheduled = base_query.filter(Appointment.status == 'scheduled').count()
    completed = base_query.filter(Appointment.status == 'completed').count()
    no_shows = base_query.filter(Appointment.status == 'no_show').count()

    return {
        'today': today_count,
        'scheduled': scheduled,
        'completed': completed,
        'no_shows': no_shows,
        'total': scheduled + completed + no_shows
    }
