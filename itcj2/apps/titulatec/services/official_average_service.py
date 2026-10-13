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

import logging
import re
from collections import Counter
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Literal, Optional

from sqlalchemy.orm import Session

from itcj2.apps.titulatec.services.audit_service import AuditService
from itcj2.apps.titulatec.services.import_service import normalize_control

logger = logging.getLogger(__name__)

# Mínimo aprobatorio TecNM: un «9.5» es casi seguro un «95» mal escrito.
MIN_AVERAGE = Decimal("70")
MAX_AVERAGE = Decimal("100")

_CENTS = Decimal("0.01")
# Solo dígitos ASCII con UN separador decimal (punto o coma). Un separador de
# miles («1,000.5», «1.000,5») no calza a propósito: es ambiguo y se rechaza.
_NUMBER_RE = re.compile(r"[0-9]+(?:[.,][0-9]+)?")

# Llaves FIJAS del resultado de `load_rows` (el orden es el del reporte).
LOAD_BUCKETS = ("applied", "stored", "updated", "same", "no_request", "out_of_range",
                "invalid", "duplicate")

_MSG_DUP = "El control aparece más de una vez en el archivo; no se cargó ninguna."
_MSG_CONTROL = "Número de control inválido."
_MSG_PROMEDIO = ("Formato inválido: se espera un número (ej. 85.5). ¿Coma decimal en un "
                 "archivo separado por comas? Guárdalo con «;» o usa punto.")
_MSG_RANGE = "Fuera de rango: debe estar entre 70 y 100."

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
        try:
            return _q(text.replace(",", "."))
        except InvalidOperation:
            # Cifras de más (30 dígitos): `quantize` desborda la precisión. Una
            # celda absurda no debe tumbar el archivo entero.
            return None

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

    @staticmethod
    def load_rows(db: Session, rows: list[tuple[str, str]], *, actor_id,
                  dry_run: bool) -> dict[str, list[tuple[str, str]]]:
        """Carga en lote `(control, promedio)`. Devuelve `{bucket: [(control, motivo)]}`
        con las llaves de `LOAD_BUCKETS`. Por control:

        - repetido en el archivo -> `duplicate` (ninguna aparición se carga);
        - control mal formado o promedio que no es número -> `invalid`;
        - número fuera de 70-100 -> `out_of_range`;
        - con proceso no cancelado -> se guarda y se copia al proceso:
          `applied` (nuevo, o la tabla ya lo tenía pero el proceso no),
          `updated` (cambió el valor guardado; «antes -> después») o `same`;
        - sin proceso pero con alguna solicitud (la rechazada también: se puede
          reabrir) -> se guarda: `stored`/`updated`/`same`;
        - ni proceso ni solicitud -> `no_request`, no se guarda nada (un
          promedio sin alumno conocido es dato huérfano).

        Cada fila va en su SAVEPOINT: si truena, se deshace solo esa y cae en
        `invalid` con el nombre de la excepción (nunca su texto). `dry_run`
        corre el mismo camino y deshace cada savepoint, así el reporte es
        exactamente el de la corrida real. Sin commit: es del llamador.
        """
        from itcj2.apps.titulatec.models import EnrollmentRequest, OfficialAverage
        from itcj2.apps.titulatec.models import TitulationProcess
        from itcj2.apps.titulatec.services.import_service import CONTROL_NUMBER_RE
        from itcj2.core.models.user import User

        out: dict[str, list[tuple[str, str]]] = {b: [] for b in LOAD_BUCKETS}
        limpias = [(normalize_control(c), p) for c, p in rows]
        limpias = [(c, p) for c, p in limpias if c or str(p or "").strip()]
        veces = Counter(c for c, _ in limpias)
        validos = {c for c, _ in limpias if CONTROL_NUMBER_RE.fullmatch(c)}

        # Una consulta por tabla en vez de dos por fila (~545 filas). Las
        # tablas pueden guardar el control con la «L» de licenciatura.
        buscar = validos | {"L" + c for c in validos}
        con_proceso: Counter = Counter()
        con_solicitud: dict[str, list[str]] = {}
        if buscar:
            for ctrl, n in (db.query(User.control_number, TitulationProcess.id)
                            .join(TitulationProcess, TitulationProcess.student_id == User.id)
                            .filter(User.control_number.in_(buscar),
                                    TitulationProcess.status != "cancelled").all()):
                con_proceso[normalize_control(ctrl)] += 1
            for ctrl, status in (db.query(EnrollmentRequest.control_number,
                                          EnrollmentRequest.status)
                                 .filter(EnrollmentRequest.control_number.in_(buscar)).all()):
                con_solicitud.setdefault(normalize_control(ctrl), []).append(status)
        vistos: set[str] = set()

        for control, raw in limpias:
            if veces[control] > 1:
                if control not in vistos:
                    out["duplicate"].append((control, _MSG_DUP))
                vistos.add(control)
                continue
            if control not in validos:
                out["invalid"].append((control, _MSG_CONTROL))
                continue
            valor = OfficialAverageService.parse_average(raw)
            if valor is None:
                out["invalid"].append((control, _MSG_PROMEDIO))
                continue
            if not OfficialAverageService.in_range(valor):
                out["out_of_range"].append((control, f"{valor}: {_MSG_RANGE}"))
                continue

            n_procesos = con_proceso.get(control, 0)
            solicitudes = con_solicitud.get(control, [])
            if not n_procesos and not solicitudes:
                out["no_request"].append((control, "Sin solicitud ni proceso; no se guardó."))
                continue

            savepoint = db.begin_nested()
            try:
                previo = db.get(OfficialAverage, control)
                antes = None if previo is None else _q(previo.average)
                estado = OfficialAverageService.upsert(db, control, valor, actor_id=actor_id)
                cambiados = (OfficialAverageService.apply_to_processes(
                    db, control, valor, actor_id=actor_id) if n_procesos else 0)
                if dry_run:
                    savepoint.rollback()
                else:
                    savepoint.commit()
            except Exception as exc:
                savepoint.rollback()
                # Solo el tipo: el texto de una excepción podría arrastrar datos.
                logger.error("Carga de promedios: falló una fila (%s).", type(exc).__name__)
                out["invalid"].append((control, f"Error inesperado ({type(exc).__name__})."))
                continue

            if estado == "updated":
                out["updated"].append((control, f"{antes} → {valor}"))
            elif n_procesos and (estado == "created" or cambiados):
                out["applied"].append(
                    (control, f"{valor} en {n_procesos} proceso(s)"))
            elif estado == "same":
                out["same"].append((control, f"{valor}"))
            else:
                motivo = f"{valor}"
                if all(st == "rejected" for st in solicitudes):
                    motivo += " (solicitud rechazada)"
                out["stored"].append((control, motivo))
        return out
