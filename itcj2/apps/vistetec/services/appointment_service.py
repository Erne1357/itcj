"""Servicio para gestión de citas."""
from datetime import date, datetime
from typing import Optional

from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from itcj2.apps.vistetec.models.appointment import Appointment
from itcj2.apps.vistetec.models.garment import Garment
from itcj2.apps.vistetec.models.slot_volunteer import SlotVolunteer
from itcj2.apps.vistetec.models.time_slot import TimeSlot


def _generate_code(db: Session) -> str:
    """Genera código único para cita: CIT-YYYY-NNNN."""
    year = datetime.now().year
    prefix = f"CIT-{year}-"

    last = db.query(Appointment).filter(
        Appointment.code.like(f"{prefix}%")
    ).order_by(Appointment.id.desc()).first()

    if last:
        last_num = int(last.code.split('-')[-1])
        new_num = last_num + 1
    else:
        new_num = 1

    return f"{prefix}{new_num:04d}"


def _verify_volunteer_for_slot(db: Session, slot_id: int, volunteer_id: int) -> bool:
    """Verifica que un voluntario está inscrito en un slot."""
    return db.query(SlotVolunteer).filter_by(
        slot_id=slot_id, volunteer_id=volunteer_id
    ).first() is not None


def get_student_appointments(
    db: Session,
    student_id: int,
    status: Optional[str] = None,
    include_past: bool = False,
) -> list[Appointment]:
    """Obtiene las citas de un estudiante."""
    query = db.query(Appointment).filter(Appointment.student_id == student_id)

    if status:
        query = query.filter(Appointment.status == status)

    if not include_past:
        today = date.today()
        query = query.join(TimeSlot).filter(TimeSlot.date >= today)

    return query.order_by(Appointment.created_at.desc()).all()


def get_volunteer_appointments(
    db: Session,
    volunteer_id: int,
    date_filter: Optional[date] = None,
    status: Optional[str] = None,
) -> list[Appointment]:
    """Obtiene las citas para los slots donde un voluntario está inscrito."""
    query = db.query(Appointment).join(TimeSlot).join(
        SlotVolunteer, SlotVolunteer.slot_id == TimeSlot.id
    ).filter(
        SlotVolunteer.volunteer_id == volunteer_id
    )

    if date_filter:
        query = query.filter(TimeSlot.date == date_filter)

    if status:
        query = query.filter(Appointment.status == status)

    return query.order_by(TimeSlot.date, TimeSlot.start_time).all()


def get_appointment_by_id(db: Session, appointment_id: int) -> Optional[Appointment]:
    """Obtiene una cita por ID."""
    return db.get(Appointment, appointment_id)


def get_appointment_by_code(db: Session, code: str) -> Optional[Appointment]:
    """Obtiene una cita por código."""
    return db.query(Appointment).filter_by(code=code).first()


def create_appointment(
    db: Session,
    student_id: int,
    garment_id: int,
    slot_id: int,
    will_bring_donation: bool = False,
) -> Appointment:
    """Crea una nueva cita."""
    slot = db.get(TimeSlot, slot_id)
    if not slot:
        raise ValueError("Horario no encontrado")

    if not slot.is_active:
        raise ValueError("Este horario ya no está disponible")

    if slot.is_full:
        raise ValueError("Este horario ya está lleno")

    now = datetime.now()
    slot_datetime = datetime.combine(slot.date, slot.start_time)
    if slot_datetime <= now:
        raise ValueError("No puedes agendar citas en horarios pasados")

    garment = db.get(Garment, garment_id)
    if not garment:
        raise ValueError("Prenda no encontrada")

    if garment.status != 'available':
        raise ValueError("Esta prenda ya no está disponible")

    existing = db.query(Appointment).filter(
        Appointment.student_id == student_id,
        Appointment.garment_id == garment_id,
        Appointment.status.in_(['scheduled', 'attended'])
    ).first()

    if existing:
        raise ValueError("Ya tienes una cita activa para esta prenda")

    active_count = db.query(Appointment).filter(
        Appointment.student_id == student_id,
        Appointment.status == 'scheduled'
    ).count()

    if active_count >= 3:
        raise ValueError("Solo puedes tener máximo 3 citas activas")

    appointment = Appointment(
        code=_generate_code(db),
        student_id=student_id,
        garment_id=garment_id,
        slot_id=slot_id,
        location_id=slot.location_id,
        status='scheduled',
        will_bring_donation=will_bring_donation,
    )

    slot.current_appointments += 1
    garment.status = 'reserved'

    db.add(appointment)
    db.commit()

    return appointment


def cancel_appointment(
    db: Session,
    appointment_id: int,
    user_id: int,
    is_volunteer: bool = False,
) -> Appointment:
    """Cancela una cita (estudiante o voluntario)."""
    appointment = db.get(Appointment, appointment_id)
    if not appointment:
        raise ValueError("Cita no encontrada")

    if not is_volunteer and appointment.student_id != user_id:
        raise ValueError(f"No tienes permiso para cancelar esta cita")

    if is_volunteer:
        if not _verify_volunteer_for_slot(db, appointment.slot_id, user_id):
            raise ValueError("No tienes permiso para cancelar esta cita")

    if appointment.status not in ['scheduled']:
        raise ValueError("Esta cita no se puede cancelar")

    appointment.status = 'cancelled'
    appointment.slot.current_appointments = max(0, appointment.slot.current_appointments - 1)
    appointment.garment.status = 'available'

    db.commit()

    return appointment


def mark_attendance(
    db: Session,
    appointment_id: int,
    volunteer_id: int,
    attended: bool,
) -> Appointment:
    """Marca asistencia de una cita."""
    appointment = db.get(Appointment, appointment_id)
    if not appointment:
        raise ValueError("Cita no encontrada")

    if not _verify_volunteer_for_slot(db, appointment.slot_id, volunteer_id):
        raise ValueError("No tienes permiso para modificar esta cita")

    if appointment.status != 'scheduled':
        raise ValueError("Esta cita no está en estado programado")

    appointment.status = 'attended' if attended else 'no_show'
    appointment.attended_by_id = volunteer_id
    appointment.attended_at = datetime.now()

    if not attended:
        appointment.garment.status = 'available'

    db.commit()

    return appointment


def complete_appointment(
    db: Session,
    appointment_id: int,
    volunteer_id: int,
    outcome: str,
    notes: Optional[str] = None,
) -> Appointment:
    """Completa una cita con el resultado."""
    valid_outcomes = ['taken', 'not_fit', 'declined']
    if outcome not in valid_outcomes:
        raise ValueError(f"Resultado inválido. Usa: {', '.join(valid_outcomes)}")

    appointment = db.get(Appointment, appointment_id)
    if not appointment:
        raise ValueError("Cita no encontrada")

    if not _verify_volunteer_for_slot(db, appointment.slot_id, volunteer_id):
        raise ValueError("No tienes permiso para modificar esta cita")

    if appointment.status != 'attended':
        raise ValueError("Primero debes marcar la asistencia")

    appointment.status = 'completed'
    appointment.outcome = outcome
    appointment.notes = notes

    if outcome == 'taken':
        appointment.garment.status = 'delivered'
        appointment.garment.delivered_to_id = appointment.student_id
        appointment.garment.delivered_at = datetime.now()
        appointment.garment.delivered_by_id = volunteer_id
    else:
        appointment.garment.status = 'available'

    db.commit()

    return appointment


def get_today_appointments_for_volunteer(db: Session, volunteer_id: int) -> list[Appointment]:
    """Obtiene las citas de hoy para un voluntario."""
    today = date.today()
    return db.query(Appointment).join(TimeSlot).join(
        SlotVolunteer, SlotVolunteer.slot_id == TimeSlot.id
    ).filter(
        SlotVolunteer.volunteer_id == volunteer_id,
        TimeSlot.date == today,
        Appointment.status.in_(['scheduled', 'attended'])
    ).order_by(TimeSlot.start_time).all()


def get_appointment_stats(db: Session, volunteer_id: Optional[int] = None) -> dict:
    """Obtiene estadísticas de citas."""
    base_query = db.query(Appointment)

    if volunteer_id:
        base_query = base_query.join(TimeSlot).join(
            SlotVolunteer, SlotVolunteer.slot_id == TimeSlot.id
        ).filter(
            SlotVolunteer.volunteer_id == volunteer_id
        )

    today = date.today()

    if volunteer_id:
        today_count = base_query.filter(TimeSlot.date == today).count()
    else:
        today_count = base_query.join(TimeSlot).filter(TimeSlot.date == today).count()

    scheduled = base_query.filter(Appointment.status == 'scheduled').count()
    completed = base_query.filter(Appointment.status == 'completed').count()
    no_shows = base_query.filter(Appointment.status == 'no_show').count()

    return {
        'today': today_count,
        'scheduled': scheduled,
        'completed': completed,
        'no_shows': no_shows,
        'total': scheduled + completed + no_shows,
    }
