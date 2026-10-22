"""Calendario de dias inhabiles de TitulaTec (fase 5).

Con la tabla vacia todo conteo de dias habiles da lo de siempre (lun-vie).
`holidays` es la UNICA lectura que usan los consumidores (una consulta por
peticion); `add_range` / `remove_range` son las escrituras, auditadas.
"""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy.orm import Session

from itcj2.apps.titulatec.models.non_working_day import NonWorkingDay
from itcj2.apps.titulatec.services.audit_service import AuditService


class NonWorkingDayService:
    """Altas y bajas por rango del calendario de dias inhabiles."""

    MAX_RANGE_DAYS = 120
    MAX_DESCRIPTION = 150

    @staticmethod
    def holidays(db: Session) -> frozenset[date]:
        """Todas las fechas inhabiles registradas (UNA consulta)."""
        return frozenset(d for (d,) in db.query(NonWorkingDay.day).all())

    @staticmethod
    def list_year(db: Session, year: int) -> list[dict]:
        """Dias inhabiles del año, por fecha: `[{id, day, description}]`."""
        rows = (db.query(NonWorkingDay)
                .filter(NonWorkingDay.day >= date(year, 1, 1),
                        NonWorkingDay.day <= date(year, 12, 31))
                .order_by(NonWorkingDay.day, NonWorkingDay.id)
                .all())
        return [{"id": r.id, "day": r.day, "description": r.description} for r in rows]

    @staticmethod
    def _check_range(start: date, end: date) -> None:
        if start is None or end is None:
            raise ValueError("Indica la fecha de inicio y la de fin.")
        if start > end:
            raise ValueError("La fecha de inicio no puede ser posterior a la de fin.")
        if (end - start).days + 1 > NonWorkingDayService.MAX_RANGE_DAYS:
            raise ValueError(
                f"El rango no puede pasar de {NonWorkingDayService.MAX_RANGE_DAYS} días.")

    @staticmethod
    def add_range(db: Session, actor_id: int, *, start: date, end: date,
                  description: str) -> dict:
        """Registra como inhabiles los dias de `start` a `end` (inclusive).

        Sabados y domingos y dias ya registrados se saltan. Devuelve
        `{"added", "weekend", "existing"}`. `ValueError` con texto para el
        usuario ANTES de escribir nada. Una fila de bitacora, commit.
        """
        NonWorkingDayService._check_range(start, end)
        texto = (description or "").strip()
        if not texto:
            raise ValueError("Escribe una descripción.")
        if len(texto) > NonWorkingDayService.MAX_DESCRIPTION:
            raise ValueError(
                f"La descripción no puede pasar de {NonWorkingDayService.MAX_DESCRIPTION} "
                "caracteres.")

        existentes = {d for (d,) in db.query(NonWorkingDay.day)
                      .filter(NonWorkingDay.day >= start, NonWorkingDay.day <= end).all()}
        agregados = fin_de_semana = repetidos = 0
        dia = start
        while dia <= end:
            if dia.weekday() >= 5:
                fin_de_semana += 1
            elif dia in existentes:
                repetidos += 1
            else:
                db.add(NonWorkingDay(day=dia, description=texto, created_by_id=actor_id))
                agregados += 1
            dia += timedelta(days=1)
        db.flush()
        AuditService.record(
            db, "non_working_day.added", actor_id=actor_id,
            payload={"start": start.isoformat(), "end": end.isoformat(),
                     "added": agregados, "description": texto})
        db.commit()
        return {"added": agregados, "weekend": fin_de_semana, "existing": repetidos}

    @staticmethod
    def remove_range(db: Session, actor_id: int, *, start: date, end: date) -> int:
        """Quita los dias inhabiles de `start` a `end` (inclusive); devuelve
        cuantos quito. Una fila de bitacora, commit."""
        NonWorkingDayService._check_range(start, end)
        filas = (db.query(NonWorkingDay)
                 .filter(NonWorkingDay.day >= start, NonWorkingDay.day <= end).all())
        for fila in filas:
            db.delete(fila)
        db.flush()
        AuditService.record(
            db, "non_working_day.removed", actor_id=actor_id,
            payload={"start": start.isoformat(), "end": end.isoformat(),
                     "removed": len(filas)})
        db.commit()
        return len(filas)
