"""Bandeja «Promedios» (spec 2026-11-26-titulatec-promedios-pendientes-design.md §5).

Expedientes (procesos no cancelados de un alumno con número de control) SIN
promedio oficial. Dos vistas, que resuelve `view_for`:

* `cc` -- Centro de Cómputo y `admin` (`titulatec.average.api.request`): todo
  expediente, sin alcance por carrera, en dos pestañas: `pending` («Por
  capturar») y `requested` («Con Escolares»: CC marcó «No lo tengo»).
* `se` -- Servicios Escolares: SOLO `requested`, acotado por
  `scope_service.officer_programs` (set vacío = nada, fail-closed).

El estado sale de dos columnas de `titulatec_processes` (`average_requested_at`,
`average_requested_by_id`); con promedio el expediente sale de la bandeja y las
columnas se quedan como historia. Guardar = `OfficialAverageService.upsert` +
`apply_to_processes` (bitácora `average.final_set`), con sus mismas reglas y
textos. La UI nunca pisa un promedio existente: eso sigue siendo de la CLI.

Bandeja == escritura: `_scope` es el ÚNICO predicado de «está en tu bandeja»; lo
usan la lista, los contadores, la captura y el archivo. Los mutadores bloquean la
fila del proceso (`FOR NO KEY UPDATE`, como `PhaseService._lock_process_row`) y
hacen su propio commit. Devuelven valores planos o dataclasses, nunca objetos ORM.
"""
from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from itcj2.apps.titulatec.services.audit_service import AuditService
from itcj2.apps.titulatec.services.import_service import (
    CONTROL_NUMBER_RE,
    normalize_control,
)
from itcj2.apps.titulatec.services.official_average_service import (
    _MSG_CONTROL,
    _MSG_DUP,
    _MSG_PROMEDIO,
    _MSG_RANGE,
    OfficialAverageService,
    _procesos_de,
)
from itcj2.apps.titulatec.utils.paging import PAGE_SIZE, Page, paginate_query

logger = logging.getLogger(__name__)

REQUEST_PERM = "titulatec.average.api.request"   # tenerlo = vista `cc`
TABS = ("pending", "requested")
_RELEASE_PHASE_CODE = "review_appointment"        # liberado = como `HandoffService`

# Llaves FIJAS del resultado de `load_rows` (el orden es el del reporte).
LOAD_BUCKETS = ("applied", "not_in_tray", "out_of_range", "invalid", "duplicate")
LOAD_LABELS = {
    "applied": "Aplicados a su proceso",
    "not_in_tray": "No está en tu bandeja",
    "out_of_range": "Fuera de rango (70-100)",
    "invalid": "Formato inválido",
    "duplicate": "Duplicados",
}

_MSG_HAS_AVERAGE = "Ya tiene promedio."
# La tabla oficial ya guarda OTRO valor para el control (p. ej. lo cargó la CLI
# mientras el proceso estaba cancelado y luego se reactivó): la UI nunca la pisa.
_MSG_OFFICIAL = ("Ya hay un promedio oficial guardado para este control ({}); "
                 "si hay que cambiarlo, se corrige con la CLI.")
_MSG_NOT_IN_TRAY = "No está en tu bandeja."
# Primera frase de `_MSG_PROMEDIO`: lo demás habla del separador de un archivo.
_MSG_FORMATO = "Formato inválido: se espera un número (ej. 85.5)."


@dataclass(frozen=True)
class AverageRow:
    process_id: int
    folio: str
    control: str
    name: str
    program: str | None
    cohort: str
    phase_number: int
    phase_name: str | None
    released: bool                 # fase de cotejo aprobada: ya está en Liberados
    requested_at: datetime | None  # cuándo CC lo pasó a Escolares
    requested_by_name: str | None


def _scope(query, *, view, allowed_program_ids):
    """Filtro de «está en la bandeja de este actor», SIN mirar el promedio (para
    que capturar uno ya puesto diga «Ya tiene promedio» y no 404). La consulta
    une `User` por `student_id`. `None` = alcance vacío (fail-closed)."""
    from itcj2.apps.titulatec.models import TitulationProcess as TP
    from itcj2.core.models.user import User

    query = query.filter(TP.status != "cancelled",
                         User.control_number.isnot(None), User.control_number != "")
    if view == "se":
        query = query.filter(TP.average_requested_at.isnot(None))
    if allowed_program_ids != "ALL":
        allowed = set(allowed_program_ids or ())
        if not allowed:
            return None
        query = query.filter(TP.program_id.in_(allowed))
    return query


def _pending(query, *, view, allowed_program_ids, q):
    """`_scope` + sin promedio + búsqueda (`process_search`)."""
    from itcj2.apps.titulatec.models import TitulationProcess as TP
    from itcj2.apps.titulatec.services.process_service import process_search

    query = _scope(query, view=view, allowed_program_ids=allowed_program_ids)
    if query is None:
        return None
    query = query.filter(TP.final_average.is_(None))
    pred = process_search(q)
    return query if pred is None else query.filter(pred)


def _lock_in_tray(db: Session, process_id, *, view, allowed_program_ids):
    """`(proceso bloqueado, control normalizado)` si está en la bandeja del actor
    (con o sin promedio); si no, `LookupError` (la ruta responde 404)."""
    from itcj2.apps.titulatec.models import TitulationProcess as TP
    from itcj2.core.models.user import User

    query = _scope(db.query(TP, User.control_number)
                   .join(User, User.id == TP.student_id).filter(TP.id == process_id),
                   view=view, allowed_program_ids=allowed_program_ids)
    row = None if query is None else (
        query.populate_existing().with_for_update(key_share=True, of=TP).one_or_none())
    if row is None:
        raise LookupError(process_id)
    return row[0], normalize_control(row[1])


def _lock_control(db: Session, control: str) -> list:
    """Bloquea los procesos no cancelados del control: los MISMOS que escribirá
    `apply_to_processes` (lookup único `_procesos_de`)."""
    from itcj2.apps.titulatec.models import TitulationProcess as TP

    ids = sorted(p.id for _c, p in _procesos_de(db, {control}))
    if not ids:
        return []
    return (db.query(TP).filter(TP.id.in_(ids)).order_by(TP.id)
            .populate_existing().with_for_update(key_share=True).all())


def _official_other(db: Session, control: str, valor: Decimal):
    """El promedio de `titulatec_official_averages` si es DISTINTO de `valor`
    (mismo valor = nada que pisar); si no, `None`."""
    from itcj2.apps.titulatec.models import OfficialAverage

    fila = db.get(OfficialAverage, control)
    if fila is None or Decimal(fila.average).quantize(Decimal("0.01")) == valor:
        return None
    return f"{Decimal(fila.average):.2f}"


def _still_in_tray(db: Session, control: str, *, view, allowed_program_ids) -> bool:
    """Re-chequeo tras el bloqueo: el expediente sigue sin promedio y en la
    bandeja del actor (CC pudo regresarlo, o se canceló, entre la consulta y el
    bloqueo)."""
    from itcj2.apps.titulatec.models import TitulationProcess as TP
    from itcj2.core.models.user import User

    query = _pending(db.query(TP.id).select_from(TP).join(User, User.id == TP.student_id)
                     .filter(User.control_number.in_({control, "L" + control})),
                     view=view, allowed_program_ids=allowed_program_ids, q=None)
    return query is not None and query.first() is not None


class AverageQueueService:

    @staticmethod
    def view_for(db: Session, user_id: int):
        """`("cc", "ALL")` con `titulatec.average.api.request` (la misma fuente
        que el gate, `cached_perms`); si no, `("se", officer_programs)`."""
        from itcj2.apps.titulatec.services.scope_service import officer_programs
        from itcj2.core.services.authz_cache import cached_perms

        if REQUEST_PERM in cached_perms(db, user_id, "titulatec"):
            return ("cc", "ALL")
        return ("se", officer_programs(db, user_id))

    @staticmethod
    def tray(db: Session, *, view, tab, allowed_program_ids, q=None, page=1,
             per_page=PAGE_SIZE) -> Page:
        """Página de `AverageRow`. SE solo tiene `requested`. Orden: ya liberados
        primero, luego FIFO (fecha de paso en `requested`, `created_at` del
        proceso en `pending`), desempate por `id`."""
        from sqlalchemy import and_, case
        from sqlalchemy.orm import aliased

        from itcj2.apps.titulatec.models import (
            Cohort,
            PhaseDefinition,
            ProcessPhase,
        )
        from itcj2.apps.titulatec.models import (
            TitulationProcess as TP,
        )
        from itcj2.apps.titulatec.services.phase_service import PhaseService
        from itcj2.core.models.program import Program
        from itcj2.core.models.user import User

        tab = "requested" if view == "se" or tab == "requested" else "pending"
        release = PhaseService.phase_number_for_code(db, _RELEASE_PHASE_CODE)
        Fase = aliased(ProcessPhase)
        Quien = aliased(User)
        released = Fase.id.isnot(None)
        query = (
            db.query(TP.id, TP.folio, User.control_number, User.full_name, Program.name,
                     Cohort.name, TP.current_phase, PhaseDefinition.name, released,
                     TP.average_requested_at, Quien.full_name)
            .select_from(TP)
            .join(User, User.id == TP.student_id)
            .join(Cohort, Cohort.id == TP.cohort_id)
            .outerjoin(Program, Program.id == TP.program_id)
            .outerjoin(PhaseDefinition, PhaseDefinition.number == TP.current_phase)
            # Catálogo sin la fase de cotejo (-1): nadie sale como liberado.
            .outerjoin(Fase, and_(Fase.process_id == TP.id,
                                  Fase.phase_number == (-1 if release is None else release),
                                  Fase.status == "approved"))
            .outerjoin(Quien, Quien.id == TP.average_requested_by_id)
        )
        query = _pending(query, view=view, allowed_program_ids=allowed_program_ids, q=q)
        if query is None:
            return Page(items=[], total=0, page=1, per_page=per_page)
        en_tab = TP.average_requested_at.isnot(None) if tab == "requested" else (
            TP.average_requested_at.is_(None))
        fifo = TP.average_requested_at if tab == "requested" else TP.created_at
        pagina = paginate_query(
            query.filter(en_tab).order_by(case((released, 0), else_=1), fifo, TP.id),
            page, per_page)
        # `full_name` de un `Quien` ausente (LEFT JOIN) sale «» de `concat`, no NULL.
        return Page(items=[AverageRow(*r[:10], (r[10] or "").strip() or None)
                           for r in pagina.items], total=pagina.total,
                    page=pagina.page, per_page=pagina.per_page)

    @staticmethod
    def tab_counts(db: Session, *, view, allowed_program_ids, q=None) -> dict[str, int]:
        """`{tab: n}` con las llaves de `TABS`, UNA consulta y el mismo filtro que
        `tray` (SE: `pending` siempre 0)."""
        from sqlalchemy import func

        from itcj2.apps.titulatec.models import TitulationProcess as TP
        from itcj2.core.models.user import User

        col = TP.average_requested_at
        query = _pending(
            db.query(func.count().filter(col.is_(None)), func.count().filter(col.isnot(None)))
            .select_from(TP).join(User, User.id == TP.student_id),
            view=view, allowed_program_ids=allowed_program_ids, q=q)
        pending, requested = (0, 0) if query is None else query.one()
        return {"pending": pending, "requested": requested}

    @staticmethod
    def request_school_services(db: Session, process_id, *, actor_id) -> None:
        """«No lo tengo»: pasa el expediente a Servicios Escolares. Idempotente
        (ya pasado = no cambia quién ni cuándo). Commit propio."""
        from itcj2.core.utils.timezone import db_now

        proc, _control = _lock_in_tray(db, process_id, view="cc", allowed_program_ids="ALL")
        if proc.final_average is not None:
            raise ValueError(_MSG_HAS_AVERAGE)
        if proc.average_requested_at is None:
            proc.average_requested_at = db_now()
            proc.average_requested_by_id = actor_id
            AuditService.record(db, "average.requested", entity_type="process",
                                entity_id=proc.id, process_id=proc.id, actor_id=actor_id)
        db.commit()

    @staticmethod
    def withdraw_request(db: Session, process_id, *, actor_id) -> None:
        """«Regresar a Por capturar»: deshace el pase. Idempotente. Commit propio."""
        proc, _control = _lock_in_tray(db, process_id, view="cc", allowed_program_ids="ALL")
        if proc.final_average is not None:
            raise ValueError(_MSG_HAS_AVERAGE)
        if proc.average_requested_at is not None:
            proc.average_requested_at = None
            proc.average_requested_by_id = None
            AuditService.record(db, "average.request_withdrawn", entity_type="process",
                                entity_id=proc.id, process_id=proc.id, actor_id=actor_id)
        db.commit()

    @staticmethod
    def capture(db: Session, process_id, raw, *, actor_id, view,
                allowed_program_ids) -> Decimal:
        """Guarda el promedio de UN expediente de la bandeja del actor. Fuera de
        ella: `LookupError`; ya con promedio, o valor ilegible / fuera de 70-100:
        `ValueError` con el texto para la ventanilla. Commit propio."""
        proc, control = _lock_in_tray(db, process_id, view=view,
                                      allowed_program_ids=allowed_program_ids)
        hermanos = _lock_control(db, control)
        if any(p.final_average is not None for p in [proc, *hermanos]):
            raise ValueError(_MSG_HAS_AVERAGE)
        valor = OfficialAverageService.parse_average(raw)
        if valor is None:
            raise ValueError(_MSG_FORMATO)
        if not OfficialAverageService.in_range(valor):
            raise ValueError(_MSG_RANGE)
        otro = _official_other(db, control, valor)
        if otro is not None:
            raise ValueError(_MSG_OFFICIAL.format(otro))
        OfficialAverageService.upsert(db, control, valor, actor_id=actor_id)
        OfficialAverageService.apply_to_processes(db, control, valor, actor_id=actor_id)
        if proc.final_average is None:
            # El control guardado no calzó con `_procesos_de` (p. ej. minúsculas):
            # sin esto la ventanilla vería «guardado» y la fila seguiría ahí.
            proc.final_average = valor
            OfficialAverageService._audit(db, proc, None, valor, actor_id=actor_id)
        db.commit()
        return valor

    @staticmethod
    def load_rows(db: Session, rows: list[tuple[str, str]], *, actor_id, view,
                  allowed_program_ids, dry_run: bool = False) -> dict[str, list[tuple[str, str]]]:
        """Carga por archivo `(control, promedio)` SOLO sobre la bandeja del actor.
        `{bucket: [(control, motivo)]}` con las llaves de `LOAD_BUCKETS`. Mismas
        reglas que `OfficialAverageService.load_rows` (repetido -> `duplicate`,
        control o número mal formado -> `invalid`, fuera de 70-100 ->
        `out_of_range`); lo que no está en la bandeja o ya tiene promedio ->
        `not_in_tray` (nunca pisa). Un SAVEPOINT por fila y un commit al final
        (`dry_run`: deshace cada savepoint y no commitea)."""
        from itcj2.apps.titulatec.models import TitulationProcess as TP
        from itcj2.core.models.user import User

        out: dict[str, list[tuple[str, str]]] = {b: [] for b in LOAD_BUCKETS}
        limpias = [(normalize_control(c), p) for c, p in rows]
        limpias = [(c, p) for c, p in limpias if c or str(p or "").strip()]
        veces = Counter(c for c, _ in limpias)
        validos = {c for c, _ in limpias if CONTROL_NUMBER_RE.fullmatch(c)}

        # Una consulta para todo el archivo; la tabla puede guardar la «L».
        en_bandeja: set[str] = set()
        if validos:
            query = _pending(
                db.query(User.control_number).select_from(TP)
                .join(User, User.id == TP.student_id)
                .filter(User.control_number.in_(validos | {"L" + c for c in validos})),
                view=view, allowed_program_ids=allowed_program_ids, q=None)
            if query is not None:
                en_bandeja = {normalize_control(c) for (c,) in query.all()}
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
            if control not in en_bandeja:
                out["not_in_tray"].append((control, _MSG_NOT_IN_TRAY))
                continue

            savepoint = db.begin_nested()
            try:
                procesos = _lock_control(db, control)
                if any(p.final_average is not None for p in procesos):
                    # Lo capturó alguien entre la consulta y el bloqueo.
                    savepoint.rollback()
                    out["not_in_tray"].append((control, _MSG_HAS_AVERAGE))
                    continue
                if not _still_in_tray(db, control, view=view,
                                      allowed_program_ids=allowed_program_ids):
                    # Regresado o cancelado entre la consulta y el bloqueo.
                    savepoint.rollback()
                    out["not_in_tray"].append((control, _MSG_NOT_IN_TRAY))
                    continue
                otro = _official_other(db, control, valor)
                if otro is not None:
                    savepoint.rollback()
                    out["not_in_tray"].append((control, _MSG_OFFICIAL.format(otro)))
                    continue
                OfficialAverageService.upsert(db, control, valor, actor_id=actor_id)
                OfficialAverageService.apply_to_processes(db, control, valor, actor_id=actor_id)
                if dry_run:
                    savepoint.rollback()
                else:
                    savepoint.commit()
            except Exception as exc:
                savepoint.rollback()
                # Solo el tipo: el texto de una excepción podría arrastrar datos.
                logger.error("Bandeja de promedios: falló una fila (%s).", type(exc).__name__)
                out["invalid"].append((control, f"Error inesperado ({type(exc).__name__})."))
                continue
            out["applied"].append((control, f"{valor} en {len(procesos)} proceso(s)"))
        if not dry_run:
            db.commit()
        return out
