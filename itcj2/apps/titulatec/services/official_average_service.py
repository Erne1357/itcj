"""Promedio oficial por número de control (spec 2026-10-13-titulatec-promedios-
design.md §4.1).

La tabla `titulatec_official_averages` es la FUENTE; `final_average` del proceso
es su copia aplicada. Dos caminos, como `PriorClearanceService`:

* `upsert` + `apply_to_processes` -- lo usa la CLI al cargar el archivo: guarda
  el valor y lo copia a los procesos que ya existen.
* `apply_pending` -- lo llama `ImportService.import_rows` al CREAR un proceso,
  para que el promedio guardado antes de que el alumno se inscribiera llegue
  solo (aprobación, Accesos, liga, CSV: todo alta pasa por `import_rows`).

Nada aquí hace commit: la transacción es del llamador.
"""
from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal, Optional

from sqlalchemy.orm import Session

from itcj2.apps.titulatec.services.audit_service import AuditService
from itcj2.apps.titulatec.services.import_service import normalize_control

# Mínimo aprobatorio TecNM: un «9.5» es casi seguro un «95» mal escrito.
MIN_AVERAGE = Decimal("70")
MAX_AVERAGE = Decimal("100")

_CENTS = Decimal("0.01")
# Solo dígitos ASCII con UN separador decimal (punto o coma). Un separador de
# miles («1,000.5», «1.000,5») no calza a propósito: es ambiguo y se rechaza.
_NUMBER_RE = re.compile(r"[0-9]+(?:[.,][0-9]+)?")

# Acción de bitácora: `average.final_set`. Va como LITERAL en `record(...)` (el
# contrato de audit_actions lo barre por AST) y NO como `process.*`, prefijo que
# reserva la escucha del espejo de `ProcessEvent`.


def _q(value) -> Decimal:
    return Decimal(value).quantize(_CENTS, rounding=ROUND_HALF_UP)


def _fmt(value) -> Optional[str]:
    """Decimal -> texto para la bitácora (JSON no guarda Decimal)."""
    return None if value is None else str(_q(value))


class OfficialAverageService:

    @staticmethod
    def parse_average(raw) -> Optional[Decimal]:
        """`85`, `85.5`, `85,5` (con espacios alrededor) -> `Decimal` a 2
        decimales (`ROUND_HALF_UP`); cualquier otra cosa -> `None`."""
        if raw is None:
            return None
        text = str(raw).strip()
        if not _NUMBER_RE.fullmatch(text):
            return None
        return _q(text.replace(",", "."))

    @staticmethod
    def in_range(value: Decimal) -> bool:
        return MIN_AVERAGE <= value <= MAX_AVERAGE

    @staticmethod
    def upsert(db: Session, control, average: Decimal, *,
               actor_id) -> Literal["created", "updated", "same"]:
        """Guarda el promedio del control. Sin commit."""
        from itcj2.apps.titulatec.models import OfficialAverage

        control = normalize_control(control)
        average = _q(average)
        row = db.get(OfficialAverage, control)
        if row is None:
            db.add(OfficialAverage(control_number=control, average=average,
                                   loaded_by_id=actor_id))
            db.flush()
            return "created"
        if _q(row.average) == average:
            return "same"
        row.average = average
        row.loaded_by_id = actor_id
        db.flush()
        return "updated"

    @staticmethod
    def _audit(db: Session, process, before, after, *, actor_id=None) -> None:
        AuditService.record(
            db, "average.final_set", entity_type="process", entity_id=process.id,
            process_id=process.id,
            before={"final_average": _fmt(before)}, after={"final_average": _fmt(after)},
            actor_id=actor_id)

    @staticmethod
    def apply_to_processes(db: Session, control, average: Decimal, *,
                           actor_id=None) -> int:
        """Escribe `final_average` en los procesos no cancelados del alumno con
        ese control. Devuelve cuántos CAMBIARON (mismo valor no cuenta ni audita)."""
        from itcj2.apps.titulatec.models import TitulationProcess
        from itcj2.core.models.user import User

        control = normalize_control(control)
        average = _q(average)
        procesos = (db.query(TitulationProcess)
                    .join(User, User.id == TitulationProcess.student_id)
                    .filter(User.control_number == control,
                            TitulationProcess.status != "cancelled")
                    .order_by(TitulationProcess.id).all())
        cambiados = 0
        for proc in procesos:
            antes = proc.final_average
            if antes is not None and _q(antes) == average:
                continue
            proc.final_average = average
            OfficialAverageService._audit(db, proc, antes, average, actor_id=actor_id)
            cambiados += 1
        if cambiados:
            db.flush()
        return cambiados

    @staticmethod
    def apply_pending(db: Session, process, control) -> bool:
        """Copia el promedio guardado a un proceso RECIÉN creado. Solo si el
        proceso no tiene `final_average` (nunca pisa uno ya puesto) y hay fila
        para el control. Sin commit."""
        from itcj2.apps.titulatec.models import OfficialAverage

        if process.final_average is not None:
            return False
        control = normalize_control(control)
        if not control:
            return False
        row = db.get(OfficialAverage, control)
        if row is None:
            return False
        process.final_average = _q(row.average)
        OfficialAverageService._audit(db, process, None, row.average)
        return True
