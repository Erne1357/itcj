"""Servicio para gestión de horarios de disponibilidad."""

from datetime import date, datetime, time, timedelta
from typing import Optional

from sqlalchemy import and_

from itcj.core.extensions import db
from itcj.apps.vistetec.models.time_slot import TimeSlot
from itcj.apps.vistetec.models.location import Location


def get_volunteer_slots(
    volunteer_id: int,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    include_past: bool = False
) -> list[TimeSlot]:
    """Obtiene los slots de un voluntario."""
    query = TimeSlot.query.filter(TimeSlot.volunteer_id == volunteer_id)

    if not include_past:
        today = date.today()
        query = query.filter(TimeSlot.date >= today)

    if from_date:
        query = query.filter(TimeSlot.date >= from_date)
    if to_date:
        query = query.filter(TimeSlot.date <= to_date)

    return query.order_by(TimeSlot.date, TimeSlot.start_time).all()


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


def get_slot_by_id(slot_id: int) -> Optional[TimeSlot]:
    """Obtiene un slot por ID."""
    return TimeSlot.query.get(slot_id)


def create_slot(
    volunteer_id: int,
    slot_date: date,
    start_time: time,
    end_time: time,
    max_appointments: int = 1,
    location_id: Optional[int] = None
) -> TimeSlot:
    """Crea un nuevo slot de disponibilidad."""
    if start_time >= end_time:
        raise ValueError("La hora de inicio debe ser menor a la hora de fin")

    if slot_date < date.today():
        raise ValueError("No se pueden crear slots en el pasado")

    # Verificar solapamiento
    existing = TimeSlot.query.filter(
        TimeSlot.volunteer_id == volunteer_id,
        TimeSlot.date == slot_date,
        TimeSlot.is_active == True,
        db.or_(
            and_(TimeSlot.start_time <= start_time, TimeSlot.end_time > start_time),
            and_(TimeSlot.start_time < end_time, TimeSlot.end_time >= end_time),
            and_(TimeSlot.start_time >= start_time, TimeSlot.end_time <= end_time)
        )
    ).first()

    if existing:
        raise ValueError("Ya tienes un horario que se traslapa con este")

    slot = TimeSlot(
        volunteer_id=volunteer_id,
        date=slot_date,
        start_time=start_time,
        end_time=end_time,
        max_appointments=max_appointments,
        location_id=location_id
    )

    db.session.add(slot)
    db.session.commit()

    return slot


def create_recurring_slots(
    volunteer_id: int,
    start_date: date,
    end_date: date,
    weekdays: list[int],  # 0=Lunes, 6=Domingo
    start_time: time,
    end_time: time,
    max_appointments: int = 1,
    location_id: Optional[int] = None
) -> list[TimeSlot]:
    """Crea slots recurrentes para varios días."""
    if start_date > end_date:
        raise ValueError("La fecha de inicio debe ser menor o igual a la fecha de fin")

    created_slots = []
    current = start_date

    while current <= end_date:
        if current.weekday() in weekdays and current >= date.today():
            try:
                slot = create_slot(
                    volunteer_id=volunteer_id,
                    slot_date=current,
                    start_time=start_time,
                    end_time=end_time,
                    max_appointments=max_appointments,
                    location_id=location_id
                )
                created_slots.append(slot)
            except ValueError:
                # Ignorar slots que se traslapen
                pass

        current += timedelta(days=1)

    return created_slots


def update_slot(
    slot_id: int,
    volunteer_id: int,
    **kwargs
) -> TimeSlot:
    """Actualiza un slot existente."""
    slot = TimeSlot.query.filter_by(id=slot_id, volunteer_id=volunteer_id).first()
    if not slot:
        raise ValueError("Slot no encontrado")

    if slot.current_appointments > 0:
        # Solo permitir ciertos cambios si ya tiene citas
        allowed = {'max_appointments', 'is_active', 'location_id'}
        for key in list(kwargs.keys()):
            if key not in allowed:
                raise ValueError(f"No se puede modificar '{key}' porque ya tiene citas agendadas")

    for key, value in kwargs.items():
        if hasattr(slot, key):
            setattr(slot, key, value)

    db.session.commit()
    return slot


def cancel_slot(slot_id: int, volunteer_id: int) -> TimeSlot:
    """Desactiva un slot (no lo elimina para preservar historial)."""
    slot = TimeSlot.query.filter_by(id=slot_id, volunteer_id=volunteer_id).first()
    if not slot:
        raise ValueError("Slot no encontrado")

    if slot.current_appointments > 0:
        raise ValueError("No se puede cancelar un slot con citas agendadas")

    slot.is_active = False
    db.session.commit()

    return slot


def get_locations(active_only: bool = True) -> list[Location]:
    """Obtiene ubicaciones disponibles."""
    query = Location.query
    if active_only:
        query = query.filter(Location.is_active == True)
    return query.order_by(Location.name).all()


def get_slots_for_date_range(
    start_date: date,
    end_date: date,
    volunteer_id: Optional[int] = None
) -> dict:
    """Obtiene slots agrupados por fecha para un calendario."""
    query = TimeSlot.query.filter(
        TimeSlot.date >= start_date,
        TimeSlot.date <= end_date,
        TimeSlot.is_active == True
    )

    if volunteer_id:
        query = query.filter(TimeSlot.volunteer_id == volunteer_id)

    slots = query.order_by(TimeSlot.date, TimeSlot.start_time).all()

    result = {}
    for slot in slots:
        date_str = slot.date.isoformat()
        if date_str not in result:
            result[date_str] = []
        result[date_str].append(slot.to_dict(include_volunteer=True))

    return result
