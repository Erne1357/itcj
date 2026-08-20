"""Generación y re-división de slots de AgendaTec.

ÚNICO generador de slots del proyecto. Reemplaza la lógica que estaba duplicada
en `api/coord/day_config.py` y `api/availability.py` — con el scope por carrera
habrían sido tres copias que mantener sincronizadas.

EXCEPCIÓN DELIBERADA a CLAUDE.md §3.4 (el commit va en el service): ningún
método de esta clase hace `db.commit()`. El split necesita que la validación, el
acortado, el borrado y la regeneración vivan en UNA sola transacción junto al
`pg_advisory_xact_lock` del endpoint; commitear a mitad liberaría el lock. El
commit lo hace el endpoint.
"""
import logging
from datetime import date, datetime, time, timedelta
from typing import List, Optional, Tuple

from fastapi import HTTPException
from sqlalchemy import and_, func
from sqlalchemy.orm import Session, joinedload

from itcj2.apps.agendatec.helpers import now_app

logger = logging.getLogger(__name__)


def _minutes(a: time, b: time) -> int:
    """Duración en minutos entre dos horas del mismo día."""
    return (b.hour * 60 + b.minute) - (a.hour * 60 + a.minute)


def _overlaps_any(start: time, end: time, intervals: List[Tuple[time, time]]) -> bool:
    return any(start < o_end and end > o_start for o_start, o_end in intervals)


def _appointment_program_id(db: Session, slot_id: int) -> Optional[int]:
    from itcj2.apps.agendatec.models import Appointment

    ap = db.query(Appointment).filter_by(slot_id=slot_id, status="SCHEDULED").first()
    return ap.program_id if ap else None


class SlotService:
    # =======================================================================
    # Scope
    # =======================================================================
    @staticmethod
    def resolve_programs(db: Session, coord_id: int,
                         requested: Optional[List[int]]) -> List[int]:
        """Resuelve el scope de carreras de un rango.

        `None` o lista vacía significa "todas las del coordinador", que se
        materializan como filas explícitas (no como ausencia de filas) para que
        la query del alumno sea un INNER JOIN sin `OR NOT EXISTS`.
        """
        from itcj2.apps.agendatec.helpers import get_coord_program_ids

        owned = get_coord_program_ids(coord_id, db)
        if not owned:
            # Sin esta guarda generaría slots sin proyección de scope:
            # invisibles para todos y sin ningún error.
            raise HTTPException(status_code=400, detail="coordinator_has_no_programs")

        if not requested:
            return sorted(owned)

        requested_set = set(requested)
        invalid = requested_set - owned
        if invalid:
            raise HTTPException(status_code=400, detail={
                "error": "invalid_programs", "invalid": sorted(invalid),
            })
        return sorted(requested_set)

    @staticmethod
    def reconcile_slot_programs(db: Session, slot) -> None:
        """Devuelve el scope de un slot al de su ventana.

        El grandfathering conserva la carrera de una cita viva aunque el
        coordinador la excluya del rango. Cuando esa cita se cancela el slot
        vuelve a estar libre y, sin reconciliar, reaparecería ofreciendo la
        carrera que el coordinador quiso excluir.

        Se llama desde los cuatro sitios que ponen `is_booked = False`.
        """
        from itcj2.apps.agendatec.models import (
            AvailabilityWindow, AvailabilityWindowProgram, TimeSlotProgram,
        )

        window = (
            db.query(AvailabilityWindow)
            .filter(
                AvailabilityWindow.coordinator_id == slot.coordinator_id,
                AvailabilityWindow.day == slot.day,
                AvailabilityWindow.start_time <= slot.start_time,
                AvailabilityWindow.end_time >= slot.end_time,
            )
            .first()
        )
        if window is None:
            return   # slot huérfano de ventana: dejar su proyección como está

        target = [r.program_id for r in
                  db.query(AvailabilityWindowProgram).filter_by(window_id=window.id).all()]
        if not target:
            return

        db.query(TimeSlotProgram).filter_by(slot_id=slot.id).delete(synchronize_session=False)
        for pid in target:
            db.add(TimeSlotProgram(slot_id=slot.id, program_id=pid))

    # =======================================================================
    # Generación
    # =======================================================================
    @staticmethod
    def generate_range(
        db: Session,
        coord_id: int,
        day: date,
        start: time,
        end: time,
        slot_minutes: int,
        program_ids: List[int],
        skip_intervals: Optional[List[Tuple[time, time]]] = None,
    ) -> list:
        """Genera la grilla [start, end) con paso `slot_minutes` y su scope.

        `skip_intervals`: huecos ya ocupados (citas acortadas por un split, o
        slots preservados por su historial). La grilla los salta en vez de
        crear slots encimados.

        NO hace commit. Devuelve los TimeSlot creados, ya flusheados para que
        tengan id (necesario para insertar su proyección de scope).
        """
        from itcj2.apps.agendatec.models import TimeSlot, TimeSlotProgram

        skip = sorted(skip_intervals or [])
        step = timedelta(minutes=slot_minutes)
        cur = datetime.combine(day, start)
        end_dt = datetime.combine(day, end)

        created = []
        while (cur + step) <= end_dt:
            cur_end = cur + step
            if not _overlaps_any(cur.time(), cur_end.time(), skip):
                slot = TimeSlot(
                    coordinator_id=coord_id, day=day,
                    start_time=cur.time(), end_time=cur_end.time(),
                    is_booked=False,
                )
                db.add(slot)
                created.append(slot)
            cur = cur_end

        db.flush()   # se necesitan los ids para la proyección de scope
        for slot in created:
            for pid in program_ids:
                db.add(TimeSlotProgram(slot_id=slot.id, program_id=pid))

        return created

    # =======================================================================
    # Split
    # =======================================================================
    @staticmethod
    def plan_split(
        db: Session,
        coord_id: int,
        day: date,
        start: time,
        end: time,
        new_minutes: int,
        program_ids: List[int],
    ):
        """Planea la re-división de [start, end) sin mutar nada.

        Base común de `POST /coord/day-config` y de su `/preview`, para que no
        puedan divergir.
        """
        from itcj2.apps.agendatec.config.constants import SPLIT_GRACE_MINUTES
        from itcj2.apps.agendatec.models import Appointment, TimeSlot
        from itcj2.apps.agendatec.schemas.slot_plan import (
            AffectedAppointment, ShortenedSlot, SplitOffender, SplitPlan,
        )

        now_local = now_app()
        if day < now_local.date():
            raise HTTPException(status_code=400, detail="day_in_past")

        # --- Frontera --------------------------------------------------------
        # Se trabaja con datetime completo, no .time(), para no romper a las 23:59.
        cutoff_dt = now_local + timedelta(minutes=SPLIT_GRACE_MINUTES)
        if day == now_local.date() and cutoff_dt.date() == day:
            base = max(start, cutoff_dt.time())
        else:
            base = start

        # Una cita EN CURSO no se acorta: corre la frontera hasta que termine.
        # Acortar algo que ya empezó es peor que no dividir el rango.
        straddling_end = (
            db.query(func.max(TimeSlot.end_time))
            .filter(
                TimeSlot.coordinator_id == coord_id,
                TimeSlot.day == day,
                TimeSlot.start_time < base,
                TimeSlot.end_time > base,
                TimeSlot.is_booked.is_(True),
            )
            .scalar()
        )
        start_efectivo = max(base, straddling_end or base)
        if start_efectivo >= end:
            raise HTTPException(status_code=400, detail="range_fully_in_past")

        # Si tras correr la frontera SIGUE habiendo un reservado a caballo, hay
        # datos corruptos previos. El filtro is_booked es obligatorio: sin él
        # este guard atraparía los slots LIBRES que cruzan el corte —el caso
        # normal de un split a media mañana— y devolvería 409 siempre.
        straddler = (
            db.query(TimeSlot.id)
            .filter(
                TimeSlot.coordinator_id == coord_id,
                TimeSlot.day == day,
                TimeSlot.start_time < start_efectivo,
                TimeSlot.end_time > start_efectivo,
                TimeSlot.is_booked.is_(True),
            )
            .first()
        )
        if straddler:
            raise HTTPException(status_code=409, detail={
                "error": "overlapping_slots_in_range", "slot_id": straddler[0],
            })

        # --- El predicado clave: SOLAPA, no "empieza después" ----------------
        # Filtrar por start_time >= dejaría vivos los slots que cruzan la
        # frontera, y la grilla nueva se crearía encima: doble-booking.
        overlaps = and_(TimeSlot.end_time > start_efectivo, TimeSlot.start_time < end)
        in_range = (
            db.query(TimeSlot)
            .filter(TimeSlot.coordinator_id == coord_id, TimeSlot.day == day, overlaps)
            .order_by(TimeSlot.start_time.asc())
            .all()
        )

        plan = SplitPlan(start_efectivo=start_efectivo, end=end, new_minutes=new_minutes)
        booked = [s for s in in_range if s.is_booked]
        free = [s for s in in_range if not s.is_booked]

        anchor_min = start_efectivo.hour * 60 + start_efectivo.minute
        end_min = end.hour * 60 + end.minute

        # --- Validación C1 / C2 / C3 sobre los reservados --------------------
        for s in booked:
            s_min = s.start_time.hour * 60 + s.start_time.minute
            cur_len = _minutes(s.start_time, s.end_time)
            offset = s_min - anchor_min

            if offset < 0 or offset % new_minutes != 0:
                plan.offenders.append(
                    SplitOffender(s.id, s.start_time, s.end_time, "not_on_grid"))
                continue
            if new_minutes > cur_len:
                plan.offenders.append(
                    SplitOffender(s.id, s.start_time, s.end_time, "would_grow"))
                continue

            # C2 solo aplica si el slot realmente cambia: evaluarla siempre
            # produce 409 falsos al recortar la cola vacía de un rango.
            needs_change = cur_len != new_minutes
            if needs_change and (s_min + new_minutes) > end_min:
                plan.offenders.append(
                    SplitOffender(s.id, s.start_time, s.end_time, "does_not_fit"))
                continue

            if needs_change:
                new_end = (datetime.combine(day, s.start_time)
                           + timedelta(minutes=new_minutes)).time()
                # TODO slot que cambia se acorta, tenga o no cita SCHEDULED.
                plan.to_shorten.append(ShortenedSlot(
                    slot_id=s.id,
                    old_start=s.start_time, old_end=s.end_time,
                    new_start=s.start_time, new_end=new_end,
                ))
                # Solo los SCHEDULED se notifican: DONE y NO_SHOW dejan
                # is_booked=True pero avisarles es ruido.
                ap = (
                    db.query(Appointment)
                    .options(joinedload(Appointment.student), joinedload(Appointment.program))
                    .filter_by(slot_id=s.id, status="SCHEDULED")
                    .first()
                )
                if ap:
                    plan.to_notify.append(AffectedAppointment(
                        slot_id=s.id,
                        appointment_id=ap.id,
                        request_id=ap.request_id,
                        student_id=ap.student_id,
                        student_name=(ap.student.full_name if ap.student else ""),
                        program_name=(ap.program.name if ap.program else ""),
                        old_start=s.start_time, old_end=s.end_time,
                        new_start=s.start_time, new_end=new_end,
                    ))

        if plan.offenders:
            return plan   # bloqueado: no se planea nada más

        # --- Borrado: excluir slots con historial de citas -------------------
        # agendatec_appointments.slot_id es ON DELETE CASCADE, y hay citas
        # CANCELED viviendo sobre slots libres. Borrarlas destruye historial.
        free_ids = [s.id for s in free]
        with_history = set()
        if free_ids:
            with_history = {
                row[0] for row in
                db.query(Appointment.slot_id).filter(Appointment.slot_id.in_(free_ids)).all()
            }
        for s in free:
            if s.id in with_history:
                plan.preserved_with_history.append(s.id)
            else:
                plan.to_delete_ids.append(s.id)

        # --- Huecos ocupados por los supervivientes --------------------------
        # Se guardan EN EL PLAN. apply_split los reusa tal cual: recalcularlos
        # con reglas distintas hacía que /preview reportara más slots creados
        # de los que el POST realmente crea.
        shortened_by_id = {s.slot_id: s for s in plan.to_shorten}
        for s in booked:
            sh = shortened_by_id.get(s.id)
            plan.occupied.append((s.start_time, sh.new_end if sh else s.end_time))
        for sid in plan.preserved_with_history:
            s = next(x for x in free if x.id == sid)
            plan.occupied.append((s.start_time, s.end_time))

        # --- Grilla nueva ----------------------------------------------------
        cur = datetime.combine(day, start_efectivo)
        end_dt = datetime.combine(day, end)
        step = timedelta(minutes=new_minutes)
        while (cur + step) <= end_dt:
            cur_end = cur + step
            if not _overlaps_any(cur.time(), cur_end.time(), plan.occupied):
                plan.to_create.append((cur.time(), cur_end.time()))
            cur = cur_end

        # --- Citas que quedarían fuera del scope nuevo -----------------------
        scope = set(program_ids)
        for s in booked:
            ap = (
                db.query(Appointment)
                .options(joinedload(Appointment.student), joinedload(Appointment.program))
                .filter_by(slot_id=s.id, status="SCHEDULED")
                .first()
            )
            if ap and ap.program_id not in scope:
                plan.out_of_scope.append(AffectedAppointment(
                    slot_id=s.id,
                    appointment_id=ap.id, request_id=ap.request_id,
                    student_id=ap.student_id,
                    student_name=(ap.student.full_name if ap.student else ""),
                    program_name=(ap.program.name if ap.program else ""),
                    old_start=s.start_time, old_end=s.end_time,
                    new_start=s.start_time, new_end=s.end_time,
                ))

        return plan

    @staticmethod
    def apply_split(db: Session, coord_id: int, day: date, plan, program_ids: List[int]):
        """Ejecuta el plan. NO hace commit: el endpoint sostiene el advisory lock."""
        from itcj2.apps.agendatec.models import TimeSlot, TimeSlotProgram
        from itcj2.apps.agendatec.schemas.slot_plan import SplitResult

        if plan.blocked:
            raise ValueError("apply_split llamado con un plan bloqueado")

        result = SplitResult(affected=list(plan.to_notify))

        # 1) Acortar los reservados que cambian.
        #    db.get() por PK: localizarlos por (coordinator_id, day, start_time)
        #    sería ambiguo porque uq_time_slot NO existe en la BD real.
        for sh in plan.to_shorten:
            slot = db.get(TimeSlot, sh.slot_id)
            if slot is None:
                raise HTTPException(status_code=409, detail="slot_vanished_during_split")
            slot.end_time = sh.new_end
            result.slots_shortened += 1

        # SessionLocal usa autoflush=False (itcj2/database.py:38). Sin este flush
        # explícito, cualquier SELECT posterior devolvería el end_time VIEJO y la
        # grilla se generaría sobre datos rancios.
        db.flush()

        # 2) Borrar los libres sin historial.
        #    El AND is_booked=false es la red contra el TOCTOU: si un alumno
        #    reservó entre el plan y el lock, esa fila ya NO se borra — su
        #    ON DELETE CASCADE habría destruido la cita recién creada.
        if plan.to_delete_ids:
            result.slots_deleted = (
                db.query(TimeSlot)
                .filter(TimeSlot.id.in_(plan.to_delete_ids), TimeSlot.is_booked.is_(False))
                .delete(synchronize_session=False)   # el CASCADE limpia time_slot_programs
            )
            if result.slots_deleted != len(plan.to_delete_ids):
                raise HTTPException(status_code=409, detail={
                    "error": "slot_booked_during_split",
                    "expected": len(plan.to_delete_ids),
                    "deleted": result.slots_deleted,
                })

        # 3) Regenerar la grilla saltando lo ocupado. plan.occupied viene del
        #    plan, NO se recalcula.
        created = SlotService.generate_range(
            db, coord_id, day, plan.start_efectivo, plan.end,
            plan.new_minutes, program_ids, skip_intervals=plan.occupied,
        )
        result.slots_created = len(created)

        # 4) Re-proyectar el scope de los reservados acortados, conservando la
        #    carrera de su cita viva (grandfathering).
        for sh in plan.to_shorten:
            db.query(TimeSlotProgram).filter_by(slot_id=sh.slot_id).delete(
                synchronize_session=False)
            keep = set(program_ids)
            ap_program = _appointment_program_id(db, sh.slot_id)
            if ap_program:
                keep.add(ap_program)
            for pid in sorted(keep):
                db.add(TimeSlotProgram(slot_id=sh.slot_id, program_id=pid))

        db.flush()
        return result
