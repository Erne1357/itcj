"""Servicio para gestión de horarios de disponibilidad (slots generales)."""

from datetime import date, datetime, time, timedelta
from typing import Optional

from sqlalchemy import and_

from itcj.core.extensions import db
from itcj.apps.vistetec.models.time_slot import TimeSlot
from itcj.apps.vistetec.models.slot_volunteer import SlotVolunteer
from itcj.apps.vistetec.models.location import Location


# ==================== SLOT QUERIES ====================

def get_slot_by_id(slot_id: int) -> Optional[TimeSlot]:
    """Obtiene un slot por ID."""
    return TimeSlot.query.get(slot_id)


def get_available_slots(
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    location_id: Optional[int] = None
) -> list[TimeSlot]:
    """Obtiene slots disponibles (con cupo) para estudiantes."""
    today = date.today()
    now = datetime.now().time()

    query = TimeSlot.query.filter(
        TimeSlot.is_active == True,
        TimeSlot.date >= today,
        TimeSlot.current_appointments < TimeSlot.max_appointments
    )

    # Excluir slots de hoy que ya pasaron
    query = query.filter(
        db.or_(
            TimeSlot.date > today,
            and_(TimeSlot.date == today, TimeSlot.start_time > now)
        )
    )

    if from_date:
        query = query.filter(TimeSlot.date >= from_date)
    if to_date:
        query = query.filter(TimeSlot.date <= to_date)
    if location_id:
        query = query.filter(TimeSlot.location_id == location_id)

    return query.order_by(TimeSlot.date, TimeSlot.start_time).all()


def get_all_slots(
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    location_id: Optional[int] = None
) -> list[TimeSlot]:
    """Obtiene todos los slots activos futuros (para voluntarios)."""
    today = date.today()

    query = TimeSlot.query.filter(
        TimeSlot.is_active == True,
        TimeSlot.date >= today
    )

    if from_date:
        query = query.filter(TimeSlot.date >= from_date)
    if to_date:
        query = query.filter(TimeSlot.date <= to_date)
    if location_id:
        query = query.filter(TimeSlot.location_id == location_id)

    return query.order_by(TimeSlot.date, TimeSlot.start_time).all()


def get_slots_for_date_range(
    start_date: date,
    end_date: date,
) -> dict:
    """Obtiene slots agrupados por fecha para un calendario."""
    query = TimeSlot.query.filter(
        TimeSlot.date >= start_date,
        TimeSlot.date <= end_date,
        TimeSlot.is_active == True
    )

    slots = query.order_by(TimeSlot.date, TimeSlot.start_time).all()

    result = {}
    for slot in slots:
        date_str = slot.date.isoformat()
        if date_str not in result:
            result[date_str] = []
        result[date_str].append(slot.to_dict(include_volunteers=True))

    return result


# ==================== SCHEDULE CREATION ====================

def create_schedule_slots(
    created_by_id: int,
    start_date: date,
    end_date: date,
    weekdays: list[int],
    start_time: time,
    end_time: time,
    slot_duration_minutes: int,
    max_students_per_slot: int = 1,
    location_id: Optional[int] = None
) -> list[TimeSlot]:
    """Genera slots dividiendo un bloque horario por duración.

    Ej: 8:00-12:00, duración 30 min → genera 8 slots por día seleccionado.
    """
    if start_date > end_date:
        raise ValueError("La fecha de inicio debe ser menor o igual a la fecha de fin")

    if start_time >= end_time:
        raise ValueError("La hora de inicio debe ser menor a la hora de fin")

    if slot_duration_minutes < 10 or slot_duration_minutes > 120:
        raise ValueError("La duración del slot debe ser entre 10 y 120 minutos")

    if max_students_per_slot < 1 or max_students_per_slot > 10:
        raise ValueError("Los alumnos por slot deben ser entre 1 y 10")

    if not weekdays:
        raise ValueError("Debe seleccionar al menos un día de la semana")

    today = date.today()
    created_slots = []
    current_date = start_date

    while current_date <= end_date:
        if current_date.weekday() in weekdays and current_date >= today:
            # Generar slots para este día dividiendo el bloque
            slot_start = datetime.combine(current_date, start_time)
            block_end = datetime.combine(current_date, end_time)
            duration = timedelta(minutes=slot_duration_minutes)

            while slot_start + duration <= block_end:
                slot_end_dt = slot_start + duration
                s_time = slot_start.time()
                e_time = slot_end_dt.time()

                # Verificar solapamiento por ubicación + fecha + hora
                overlap = TimeSlot.query.filter(
                    TimeSlot.date == current_date,
                    TimeSlot.is_active == True,
                    db.or_(
                        and_(TimeSlot.start_time <= s_time, TimeSlot.end_time > s_time),
                        and_(TimeSlot.start_time < e_time, TimeSlot.end_time >= e_time),
                        and_(TimeSlot.start_time >= s_time, TimeSlot.end_time <= e_time)
                    )
                )
                if location_id:
                    overlap = overlap.filter(TimeSlot.location_id == location_id)

                if not overlap.first():
                    slot = TimeSlot(
                        created_by_id=created_by_id,
                        date=current_date,
                        start_time=s_time,
                        end_time=e_time,
                        max_appointments=max_students_per_slot,
                        location_id=location_id
                    )
                    db.session.add(slot)
                    created_slots.append(slot)

                slot_start = slot_end_dt

        current_date += timedelta(days=1)

    db.session.commit()
    return created_slots


# ==================== SLOT MANAGEMENT ====================

def update_slot(slot_id: int, user_id: int, **kwargs) -> TimeSlot:
    """Actualiza un slot existente (solo el creador)."""
    slot = TimeSlot.query.filter_by(id=slot_id, created_by_id=user_id).first()
    if not slot:
        raise ValueError("Slot no encontrado")

    if slot.current_appointments > 0:
        allowed = {'max_appointments', 'is_active', 'location_id'}
        for key in list(kwargs.keys()):
            if key not in allowed:
                raise ValueError(f"No se puede modificar '{key}' porque ya tiene citas agendadas")

    for key, value in kwargs.items():
        if hasattr(slot, key):
            setattr(slot, key, value)

    db.session.commit()
    return slot


def cancel_slot(slot_id: int, user_id: int) -> TimeSlot:
    """Desactiva un slot (solo el creador)."""
    slot = TimeSlot.query.filter_by(id=slot_id, created_by_id=user_id).first()
    if not slot:
        raise ValueError("Slot no encontrado")

    if slot.current_appointments > 0:
        raise ValueError("No se puede cancelar un slot con citas agendadas")

    slot.is_active = False
    db.session.commit()
    return slot


# ==================== VOLUNTEER SIGNUP ====================

def signup_volunteer(slot_id: int, volunteer_id: int) -> SlotVolunteer:
    """Voluntario se inscribe a un slot."""
    slot = TimeSlot.query.get(slot_id)
    if not slot:
        raise ValueError("Slot no encontrado")

    if not slot.is_active:
        raise ValueError("Este horario ya no está activo")

    # Verificar que no sea un slot pasado
    now = datetime.now()
    slot_datetime = datetime.combine(slot.date, slot.start_time)
    if slot_datetime <= now:
        raise ValueError("No puedes inscribirte a un horario pasado")

    # Verificar duplicado
    existing = SlotVolunteer.query.filter_by(
        slot_id=slot_id, volunteer_id=volunteer_id
    ).first()
    if existing:
        raise ValueError("Ya estás inscrito en este horario")

    sv = SlotVolunteer(slot_id=slot_id, volunteer_id=volunteer_id)
    db.session.add(sv)
    db.session.commit()
    return sv


def unsignup_volunteer(slot_id: int, volunteer_id: int) -> bool:
    """Voluntario cancela su inscripción a un slot."""
    sv = SlotVolunteer.query.filter_by(
        slot_id=slot_id, volunteer_id=volunteer_id
    ).first()
    if not sv:
        raise ValueError("No estás inscrito en este horario")

    db.session.delete(sv)
    db.session.commit()
    return True


def get_volunteer_signups(
    volunteer_id: int,
    include_past: bool = False
) -> list[TimeSlot]:
    """Retorna los slots donde el voluntario está inscrito."""
    query = TimeSlot.query.join(SlotVolunteer).filter(
        SlotVolunteer.volunteer_id == volunteer_id,
        TimeSlot.is_active == True
    )

    if not include_past:
        today = date.today()
        query = query.filter(TimeSlot.date >= today)

    return query.order_by(TimeSlot.date, TimeSlot.start_time).all()


def is_volunteer_signed_up(slot_id: int, volunteer_id: int) -> bool:
    """Verifica si un voluntario está inscrito en un slot."""
    return SlotVolunteer.query.filter_by(
        slot_id=slot_id, volunteer_id=volunteer_id
    ).first() is not None


# ==================== LOCATIONS ====================

def get_locations(active_only: bool = True) -> list[Location]:
    """Obtiene ubicaciones disponibles."""
    query = Location.query
    if active_only:
        query = query.filter(Location.is_active == True)
    return query.order_by(Location.name).all()
