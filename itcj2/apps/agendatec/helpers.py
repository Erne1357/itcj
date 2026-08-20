"""
Helpers compartidos para la app agendatec en FastAPI.

Equivale a los helpers de Flask en:
- itcj/apps/agendatec/routes/api/coord/helpers.py
- itcj/apps/agendatec/routes/api/admin/helpers.py
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Optional, Set
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy.orm import Session

from itcj2.core.models.coordinator import Coordinator
from itcj2.core.models.program_coordinator import ProgramCoordinator
from itcj2.core.models.user import User
from itcj2.exceptions import PageForbidden


# ============================================================
# TEMP_TEST_GATE — DESACTIVADO (2026-08-20)
#
# Restringía AgendaTec a los estudiantes de la lista blanca de abajo
# (período exclusivo de pruebas). Con el gate activo, cualquier alumno
# fuera de la tupla recibía 403 / PageForbidden y NO podía solicitar
# cita: inviable con el periodo abierto a todos.
#
# Se apaga desde aquí en vez de comentar las ~44 llamadas repartidas en
# 12 archivos (api/{availability,notifications,periods,programs,requests,
# slots,social}.py, pages/{landing,student}.py, sockets/{slots,requests}.py):
# los dos helpers salen en corto y el resto del código sigue igual. En los
# sockets, `allowed` queda siempre en True y sus bloques se vuelven no-op.
#
# PARA VOLVER A USARLO: poner TEMP_TEST_GATE_ENABLED = True y ajustar la
# tupla de números de control. Nada más — las llamadas siguen puestas.
#
# Efecto lateral bueno de tenerlo apagado: cada llamada hacía
# user_roles_in_app() + db.get(User), o sea 2 golpes a BD por endpoint y
# por connect de socket. Apagado, ni se tocan.
#
# Grep: TEMP_TEST_GATE  → este bloque + sus llamadas.
# ============================================================
TEMP_TEST_GATE_ENABLED = False
TEMP_TEST_GATE_CONTROL_NUMBER = ("22111360", "94110667", "21111182")


def TEMP_TEST_GATE_check_student(user: dict, db: Session, *, is_page: bool = False) -> None:
    """Bloquea estudiantes excepto los de la lista blanca. Coord/admin/social pasan.

    No-op mientras TEMP_TEST_GATE_ENABLED sea False.
    """
    if not TEMP_TEST_GATE_ENABLED:
        return
    if (user or {}).get("role") == "admin":
        return
    try:
        uid = int(user["sub"])
    except Exception:
        uid = None
    if not uid:
        return  # sin auth — flujo normal decide
    from itcj2.core.services.authz_service import user_roles_in_app
    roles = set(user_roles_in_app(db, uid, "agendatec"))
    if "student" not in roles:
        return  # no es estudiante — pasa
    u = db.get(User, uid)
    if u and u.control_number in TEMP_TEST_GATE_CONTROL_NUMBER:
        return
    if is_page:
        raise PageForbidden(has_app_access=False)
    raise HTTPException(status_code=403, detail="test_gate_blocked")


def TEMP_TEST_GATE_check_student_sync(user: dict) -> bool:
    """Versión sync para Socket.IO connect. True = permitir, False = bloquear.

    Siempre True mientras TEMP_TEST_GATE_ENABLED sea False.
    """
    if not TEMP_TEST_GATE_ENABLED:
        return True
    if (user or {}).get("role") == "admin":
        return True
    try:
        uid = int(user["sub"])
    except Exception:
        return True  # sin uid claro — deja pasar
    from itcj2.database import SessionLocal
    with SessionLocal() as db:
        from itcj2.core.services.authz_service import user_roles_in_app
        roles = set(user_roles_in_app(db, uid, "agendatec"))
        if "student" not in roles:
            return True
        u = db.get(User, uid)
        return bool(u and u.control_number in TEMP_TEST_GATE_CONTROL_NUMBER)
# ============================================================


# ---------------------------------------------------------------------------
# Coordinador
# ---------------------------------------------------------------------------

def get_coordinator_for_user(user_id: int, db: Session) -> Optional[Coordinator]:
    """Retorna el Coordinator del usuario dado, o None."""
    return db.query(Coordinator).filter_by(user_id=user_id).first()


def get_coordinator_id_for_user(user_id: int, db: Session) -> Optional[int]:
    """Retorna el coordinator_id del usuario, o None."""
    coord = get_coordinator_for_user(user_id, db)
    return coord.id if coord else None


def get_coord_program_ids(coord_id: int, db: Session) -> Set[int]:
    """Retorna el conjunto de program_ids asignados a un coordinador."""
    rows = (
        db.query(ProgramCoordinator.program_id)
        .filter(ProgramCoordinator.coordinator_id == coord_id)
        .all()
    )
    return {r[0] for r in rows}


def require_coordinator(user_id: int, db: Session) -> int:
    """
    Obtiene el coordinator_id del usuario o lanza 404.
    Útil como helper en endpoints de coordinador.
    """
    coord_id = get_coordinator_id_for_user(user_id, db)
    if not coord_id:
        raise HTTPException(status_code=404, detail="coordinator_not_found")
    return coord_id


# ---------------------------------------------------------------------------
# Ventanas de disponibilidad
# ---------------------------------------------------------------------------

def split_or_delete_windows(
    coord_id: int,
    d: date,
    time_ge: time,
    time_lt: time,
    db: Session,
) -> dict:
    """
    Para cada AvailabilityWindow que solape [time_ge, time_lt):
    - Elimina la ventana original.
    - Recrea hasta dos ventanas 'no solapadas':
        [start_time, time_ge) y [time_lt, end_time)
    conservando slot_minutes.

    Returns:
        Dict con windows_deleted y windows_created.
    """
    from itcj2.apps.agendatec.models.availability_window import AvailabilityWindow

    overlapping = (
        db.query(AvailabilityWindow)
        .filter(
            AvailabilityWindow.coordinator_id == coord_id,
            AvailabilityWindow.day == d,
            ~(
                (AvailabilityWindow.end_time <= time_ge)
                | (AvailabilityWindow.start_time >= time_lt)
            ),
        )
        .all()
    )

    recreated = 0
    deleted = 0

    for w in overlapping:
        left_start = w.start_time
        left_end = min(w.end_time, time_ge)
        right_start = max(w.start_time, time_lt)
        right_end = w.end_time

        db.delete(w)
        deleted += 1

        if left_start < left_end:
            db.add(
                AvailabilityWindow(
                    coordinator_id=coord_id,
                    day=d,
                    start_time=left_start,
                    end_time=left_end,
                    slot_minutes=w.slot_minutes,
                )
            )
            recreated += 1

        if right_start < right_end:
            db.add(
                AvailabilityWindow(
                    coordinator_id=coord_id,
                    day=d,
                    start_time=right_start,
                    end_time=right_end,
                    slot_minutes=w.slot_minutes,
                )
            )
            recreated += 1

    return {"windows_deleted": deleted, "windows_created": recreated}


# ---------------------------------------------------------------------------
# Fechas y rangos
# ---------------------------------------------------------------------------

def get_app_tz() -> ZoneInfo:
    return ZoneInfo("America/Ciudad_Juarez")


def now_app() -> datetime:
    """Ahora, aware, en la zona de la app.

    Usar SIEMPRE esto en vez de `datetime.now()`. El proceso corre en UTC dentro
    del contenedor, así que comparar un naive contra horas de slot locales
    desplaza los guards 6 o 7 horas según el horario de verano.
    """
    return datetime.now(get_app_tz())


def app_dt(d: date, t: time) -> datetime:
    """Combina fecha y hora locales en un datetime aware de la zona de la app.

    Complemento de `now_app()`: comparar `now_app()` contra un
    `datetime.combine()` naive lanza TypeError.
    """
    return datetime.combine(d, t).replace(tzinfo=get_app_tz())


def parse_date_str(s: str) -> Optional[date]:
    """Parsea string YYYY-MM-DD a date, o None si inválido."""
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except (ValueError, AttributeError):
        return None


def parse_datetime_str(s: str) -> Optional[datetime]:
    """Parsea ISO datetime string, agrega timezone si falta."""
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=get_app_tz())
        return dt
    except (ValueError, AttributeError):
        return None


def parse_time_str(s: str) -> Optional[time]:
    """Parsea HH:MM a time, o None si inválido."""
    try:
        h, m = map(int, s.split(":"))
        return datetime.strptime(f"{h:02d}:{m:02d}", "%H:%M").time()
    except Exception:
        return None


def parse_range_from_params(
    from_str: Optional[str],
    to_str: Optional[str],
) -> tuple[datetime, datetime]:
    """
    FastAPI version of range_from_query().
    Toma strings 'from' y 'to', retorna (start, end) como datetimes.
    Default: últimos 7 días.
    """
    def _parse(s, default):
        if s:
            try:
                return datetime.fromisoformat(s)
            except ValueError:
                pass
        return default

    now = datetime.now()
    end = _parse(to_str, now)
    start = _parse(from_str, end - timedelta(days=7))

    # Normalizar para incluir el día completo si solo vino la fecha
    if from_str and len(from_str) == 10:
        start = datetime.combine(start.date(), datetime.min.time())
    if to_str and len(to_str) == 10:
        end = datetime.combine(end.date(), datetime.max.time())

    return start, end


def paginate_query(query, limit: int, offset: int) -> tuple:
    """Aplica paginación a una query SQLAlchemy. Retorna (items, total)."""
    total = query.order_by(None).count()
    items = query.limit(limit).offset(offset).all()
    return items, total


def get_dialect_name(db: Session) -> str:
    """Obtiene el nombre del dialecto de la base de datos."""
    try:
        bind = db.get_bind()
        return (bind and bind.dialect and bind.dialect.name) or ""
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Validación de ventana de admisión (equivale a @api_closed)
# ---------------------------------------------------------------------------

def require_admission_open() -> None:
    """
    Verifica que la ventana de admisión del período activo esté abierta.
    Equivale al decorador @api_closed de Flask.
    Lanza HTTPException(503) si está cerrada.
    """
    from itcj2.core.services import period_service
    from itcj2.database import SessionLocal

    db = SessionLocal()
    try:
        period = period_service.get_active_period(db)
        if not period:
            raise HTTPException(status_code=503, detail="no_active_period")
        config = period_service.get_agendatec_config(db, period.id)
        if not config or not config.is_student_window_open():
            raise HTTPException(status_code=503, detail="admission_closed")
    finally:
        db.close()
