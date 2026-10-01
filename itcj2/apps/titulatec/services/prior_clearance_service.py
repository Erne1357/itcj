"""Servicio de constancias previas (D9, spec `2026-10-01-titulatec-biblioteca-
caja-design.md` §4.12): egresados que YA traían, de ANTES de este sistema, su
liberación de encuesta o su no adeudo de biblioteca -otro semestre, en papel,
en el sistema legado-. Servicios Escolares (o el desarrollador, para la
encuesta: "el desarrollador recibirá una base de datos de las encuestas del
semestre anterior", D9) la carga por archivo con la CLI `titulatec
import-prior-clearances` y este servicio decide, por número de control, si se
aplica DE INMEDIATO (ya hay un proceso abierto) o se DIFIERE (upsert de
`PriorClearance`, sin proceso todavía -el alumno aún no se inscribe a este
periodo-).

Dos puntos de entrada:

* `apply_pending(db, process, control_number)` -- la llama `ImportService.
  import_rows` justo DESPUÉS de `LibraryClearanceService.open_for_process`,
  al dar de alta un proceso NUEVO (siempre `active`, fase 2 siempre
  `pending`): aplica las `PriorClearance` vigentes de ese número que sigan
  sin aplicar. Sin commit (la transacción del lote es de `import_rows`).
* `import_rows(db, *, kind, rows, source, dry_run, today)` -- el motor de la
  CLI: por fila, clasifica en una de las 6 llaves de `IMPORT_BUCKETS` y, si
  no es `dry_run`, aplica o difiere.

Quien de verdad MUTA la fila del egresado es cada dueño -`SurveyReviewService
.register_prior` (encuesta) y `LibraryClearanceService.register_prior`
(biblioteca)-: este módulo nunca escribe `SurveyReview.status` ni
`LibraryClearance.status` (§5, invariante 1). TAMPOCO los LEE directo (fix
round 1, Important del revisor: `clearance.status == "cleared"` y
`existente.status == "approved"` se colaron en la primera entrega): la
clasificación "¿aplicaría, ya se aplicó, o es un conflicto?" vive en
`SurveyReviewService.prior_outcome`/`LibraryClearanceService.prior_outcome`
-predicados de SOLO LECTURA de cada dueño, distintos de `release_status`
(reservado a `ClearanceGate`)-, y este módulo SIEMPRE llama a esos dos en vez
de comparar `.status` por su cuenta, tanto en `dry_run` como en la corrida
real. `test_el_servicio_nunca_lee_status_directo`
(`test_prior_clearance_service.py`) lo barre por AST. Vigencia (D9): `issued_on`
obligatoria, no futura y `>= hoy - PRIOR_VALIDITY_DAYS` (365 días; exactamente
365 vale, 366 no) -- el MISMO límite que `LibraryClearanceService.
PRIOR_VALIDITY_DAYS`, reusado de allá para no declarar el número dos veces.
Esa validación de aquí es solo de CLASIFICACIÓN (decide en qué bote cae la
fila); la mutación real la vuelve a validar el service dueño -defensa en
profundidad, igual que el resto de la app-, así que una `PriorClearance`
diferida que se vuelve vieja ENTRE que se importó y que el alumno por fin se
inscribe (`apply_pending`) simplemente no se aplica -se registra en el log y
se salta, sin tumbar el alta del proceso-.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from itcj2.core.utils.timezone import db_now

logger = logging.getLogger(__name__)

# Dominio de `kind` (igual que `models/prior_clearance.py::PRIOR_KINDS`).
PRIOR_KINDS = ("survey", "library")

# Llaves del resultado de `import_rows`, en el orden en que la CLI las imprime.
IMPORT_BUCKETS = ("applied", "deferred", "already", "conflicts", "expired", "invalid")

# La cita de cotejo es la fase 2 del catálogo (mismo valor que `PHASE_COTEJO`
# en `survey_review_service.py`/`library_clearance_service.py`).
_PHASE_COTEJO = 2

# Ruling R13: formatos de fecha que acepta una fila (y `--fecha` de la CLI).
# `AAAA-MM-DD` (ISO, el de siempre) y `DD/MM/AAAA` (el que escribe a mano
# Servicios Escolares), cada uno con hora opcional -la exportación de Google
# Forms es-MX trae «15/03/2026 10:22:33»-. Se prueban EN ORDEN y se usa el
# primero que calce completo (`strptime` exige que no sobre ni falte nada).
_FECHA_FORMATOS = (
    "%Y-%m-%d",
    "%Y-%m-%d %H:%M:%S",
    "%d/%m/%Y",
    "%d/%m/%Y %H:%M:%S",
)


def _parse_fecha_texto(texto: str) -> Optional[date]:
    """`texto` contra cada formato de `_FECHA_FORMATOS`, en orden; `None` si
    ninguno calza completo."""
    for formato in _FECHA_FORMATOS:
        try:
            return datetime.strptime(texto, formato).date()
        except ValueError:
            continue
    return None


def _parse_date(value, *, today: date) -> tuple[Optional[date], Optional[str], Optional[str]]:
    """Texto (cualquiera de `_FECHA_FORMATOS`, R13)/`date`/`datetime` ->
    `(fecha, None, None)` si es vigente, o `(None, bote, motivo)` si no se
    puede aplicar. `bote` ∈ `"invalid"` (ausente, no parseable o futura) |
    `"expired"` (> 365 días, D9: exactamente 365 vale, 366 no); `motivo` ya
    es el texto legible que imprime la CLI."""
    from itcj2.apps.titulatec.services.library_clearance_service import PRIOR_VALIDITY_DAYS

    if value is None or (isinstance(value, str) and not value.strip()):
        return None, "invalid", "fecha de emisión ausente"
    if isinstance(value, datetime):
        value = value.date()
    if not isinstance(value, date):
        texto = str(value).strip()
        value = _parse_fecha_texto(texto)
        if value is None:
            return None, "invalid", (
                f"fecha no reconocida: {texto!r} (usa AAAA-MM-DD o DD/MM/AAAA, "
                "con hora opcional)")
    if value > today:
        return None, "invalid", "la fecha de emisión no puede ser futura"
    if value < today - timedelta(days=PRIOR_VALIDITY_DAYS):
        return None, "expired", "la constancia venció (más de 365 días)"
    return value, None, None


def _open_process_for_control(db: Session, control: str):
    """El proceso ABIERTO (activo o en pausa, fase 2 sin aprobar) de ese
    número de control, o `None`. "Abierto" en el sentido de §4.12: el único
    que puede recibir una aplicación inmediata. Cualquier otro caso -sin
    proceso, con uno ya revocado/terminado, o con la fase 2 ya aprobada- se
    trata como "sin proceso" y la constancia se difiere; si el alumno vuelve
    a inscribirse después, `apply_pending` la aplicará sola."""
    from itcj2.apps.titulatec.models import ProcessPhase, TitulationProcess
    from itcj2.apps.titulatec.services.library_clearance_service import (
        ADMITTED_PROCESS_STATUSES,
    )
    from itcj2.core.models.user import User

    user = db.query(User).filter_by(control_number=control).first()
    if user is None:
        return None
    procesos = (db.query(TitulationProcess)
               .filter(TitulationProcess.student_id == user.id,
                       TitulationProcess.status.in_(ADMITTED_PROCESS_STATUSES))
               .order_by(TitulationProcess.id.desc())
               .all())
    for proceso in procesos:
        fase2 = (db.query(ProcessPhase.status)
                .filter_by(process_id=proceso.id, phase_number=_PHASE_COTEJO)
                .first())
        if fase2 is None or fase2[0] != "approved":
            return proceso
    return None


class PriorClearanceService:
    """Decide, por número de control, si una constancia previa se aplica ya
    o se difiere. Las transiciones reales viven en `SurveyReviewService` y
    `LibraryClearanceService`."""

    # ------------------------------------------------------------------
    # Aplicación diferida (la llama `ImportService.import_rows`)
    # ------------------------------------------------------------------
    @staticmethod
    def apply_pending(db: Session, process, control_number: str) -> list[str]:
        """Aplica al `process` (recién creado) las `PriorClearance` vigentes
        de `control_number` que sigan sin aplicar (`applied_process_id IS
        NULL`). Sin commit: la llama `ImportService.import_rows` justo
        después de `LibraryClearanceService.open_for_process(...,
        just_created=True)`, dentro de la transacción del lote completo.

        Devuelve los `kind` que sí aplicó (`["survey"]`, `["library"]`, los
        dos, o `[]`). Una previa que ya no es válida al momento de aplicarse
        -p. ej. venció entre que se importó y que el alumno por fin se
        inscribió- se salta (se registra en el log) en vez de tumbar el alta
        completa del proceso.
        """
        from itcj2.apps.titulatec.models import PriorClearance

        control = (control_number or "").strip().upper()
        if not control:
            return []

        pendientes = (db.query(PriorClearance)
                     .filter(PriorClearance.control_number == control,
                             PriorClearance.applied_process_id.is_(None))
                     .order_by(PriorClearance.kind)
                     .with_for_update()
                     .all())
        aplicadas: list[str] = []
        for previa in pendientes:
            try:
                if previa.kind == "survey":
                    PriorClearanceService._apply_survey(db, process, previa)
                elif previa.kind == "library":
                    PriorClearanceService._apply_library(db, process, previa)
                else:
                    continue
            except ValueError:
                logger.warning(
                    "No se pudo aplicar la constancia previa %s (%s, control %s) "
                    "al proceso %s: ya no es válida.",
                    previa.id, previa.kind, control, process.id)
                continue
            previa.applied_process_id = process.id
            previa.applied_at = db_now()
            aplicadas.append(previa.kind)
        if aplicadas:
            # `flush()`, no `commit()` (sin commit: la transacción es del
            # llamador) -- pero SÍ hace falta: `Session.refresh()`/una
            # consulta posterior en la MISMA transacción no ven un atributo
            # modificado que nunca se mandó a Postgres (gotcha ya documentado
            # en `LibraryClearanceService.open_for_process`).
            db.flush()
        return aplicadas

    @staticmethod
    def _apply_survey(db: Session, process, previa) -> None:
        from itcj2.apps.titulatec.services.survey_review_service import SurveyReviewService

        if SurveyReviewService.prior_outcome(db, process.id) != "apply":
            return
        SurveyReviewService.register_prior(
            db, process, issued_on=previa.issued_on, note=previa.note, actor_id=None)

    @staticmethod
    def _apply_library(db: Session, process, previa) -> None:
        from itcj2.apps.titulatec.services.library_clearance_service import (
            LibraryClearanceService,
        )

        if LibraryClearanceService.prior_outcome(db, process.id) != "apply":
            return
        clearance = LibraryClearanceService.open_for_process(db, process)
        LibraryClearanceService.register_prior(
            db, clearance.id, None, issued_on=previa.issued_on, note=previa.note,
            by="import", commit=False)

    # ------------------------------------------------------------------
    # Importación por CLI
    # ------------------------------------------------------------------
    @staticmethod
    def import_rows(db: Session, *, kind: str, rows: list[dict], source: str,
                    dry_run: bool = False, today: Optional[date] = None) -> dict:
        """Importa, por número de control, constancias previas de un
        semestre anterior (D9, spec §4.12). `kind` ∈ `PRIOR_KINDS`. `rows` =
        lista de dicts `{"control_number": str, "issued_on": str|date|None,
        "note": str|None (opcional)}` -la CLI arma esta lista desde el CSV
        (columna de control autodetectada o `--columna-control`; fecha por
        columna o `--fecha` fija)-; llamar directo desde una prueba también
        vale.

        Por fila:

        1. `control_number` normalizado a MAYÚSCULA y validado con
           `CONTROL_NUMBER_RE` -> bote `invalid` si no calza.
        2. `issued_on` validada (D9: obligatoria, no futura, vigente) ->
           `invalid`/`expired` si no pasa.
        3. proceso ABIERTO para ese control (activo/en pausa, fase 2 sin
           aprobar):
           - sin proceso abierto -> se DIFIERE: upsert de `PriorClearance`
             (único por `kind`+`control_number`; una fila repetida actualiza
             `issued_on`/`note`/`source` en vez de duplicar) -> `deferred`.
             Si esa misma constancia YA se había aplicado antes (a un
             proceso anterior) no hay nada que diferir de nuevo -> `already`.
             `apply_pending` la aplicará sola cuando el alumno se inscriba.
           - con proceso, encuesta: sin `SurveyReview` ->
             `SurveyReviewService.register_prior` -> `applied`; con una YA
             `approved` -> `already`; `in_review`/`rejected` -> `conflicts`
             (lo decide GTV, no esta CLI).
           - con proceso, biblioteca: `pending`/`awaiting_payment` ->
             `LibraryClearanceService.register_prior` -> `applied`;
             `cleared` -> `already`.

        `dry_run=True` NO toca la sesión -ni siquiera un INSERT idempotente
        que luego se deshaga-: la clasificación completa corre igual
        (incluida la vigencia y la búsqueda del proceso), pero ninguna rama
        mutadora se ejecuta. `dry_run=False` hace UN commit al final.

        Devuelve un dict con las 6 llaves de `IMPORT_BUCKETS`; cada una es
        una lista de `{"control_number": str, "reason": str}`, en el orden
        del CSV.
        """
        from itcj2.apps.titulatec.services.import_service import CONTROL_NUMBER_RE
        from itcj2.apps.titulatec.services.library_clearance_service import (
            LibraryClearanceService,
        )
        from itcj2.apps.titulatec.services.survey_review_service import SurveyReviewService

        if kind not in PRIOR_KINDS:
            raise ValueError(f"Tipo de constancia previa desconocido: {kind!r}.")
        hoy = today or db_now().date()

        out: dict[str, list[dict]] = {bote: [] for bote in IMPORT_BUCKETS}

        def _add(bote: str, control: str, motivo: str) -> None:
            out[bote].append({"control_number": control, "reason": motivo})

        for row in rows:
            crudo = row.get("control_number") or ""
            control = crudo.strip().upper()
            if not control or not CONTROL_NUMBER_RE.fullmatch(control):
                _add("invalid", crudo.strip() or "(vacío)", "número de control inválido")
                continue

            fecha, bote_fecha, motivo_fecha = _parse_date(row.get("issued_on"), today=hoy)
            if bote_fecha is not None:
                _add(bote_fecha, control, motivo_fecha)
                continue

            nota = (row.get("note") or "").strip() or None
            proceso = _open_process_for_control(db, control)

            if proceso is None:
                bote = PriorClearanceService._defer(
                    db, kind=kind, control=control, issued_on=fecha, note=nota,
                    source=source, dry_run=dry_run)
                if bote == "already":
                    _add("already", control, "ya se había aplicado antes")
                else:
                    _add("deferred", control,
                        "sin proceso abierto; se aplicará cuando se inscriba")
                continue

            if kind == "survey":
                # Clasificación vía el ÚNICO predicado de lectura del dueño
                # (§5, invariante 2): ni aquí ni en ningún otro .py de la app
                # se compara `SurveyReview.status` fuera de
                # `SurveyReviewService`/`ClearanceGate`.
                outcome = SurveyReviewService.prior_outcome(db, proceso.id)
                if outcome == "apply":
                    if not dry_run:
                        SurveyReviewService.register_prior(
                            db, proceso, issued_on=fecha, note=nota, actor_id=None)
                    _add("applied", control, f"encuesta liberada en el proceso {proceso.folio}")
                elif outcome == "already":
                    _add("already", control, "la encuesta ya estaba liberada")
                else:
                    _add("conflicts", control,
                        "ya envió la encuesta de este semestre; lo decide GTV")
            else:
                # Mismo predicado, lado biblioteca: NUNCA se lee
                # `LibraryClearance.status` aquí, ni en dry-run ni en la
                # corrida real.
                outcome = LibraryClearanceService.prior_outcome(db, proceso.id)
                if outcome == "already":
                    _add("already", control, "el no adeudo ya estaba liberado")
                else:
                    if not dry_run:
                        clearance = LibraryClearanceService.open_for_process(db, proceso)
                        LibraryClearanceService.register_prior(
                            db, clearance.id, None, issued_on=fecha, note=nota,
                            by="import", commit=False)
                    _add("applied", control,
                        f"no adeudo liberado en el proceso {proceso.folio}")

        if not dry_run:
            db.commit()
        return out

    @staticmethod
    def _defer(db: Session, *, kind: str, control: str, issued_on: date,
              note: Optional[str], source: str, dry_run: bool) -> str:
        """Registra (o actualiza) la `PriorClearance` diferida de `control`,
        o confirma que ya se había aplicado antes. UNIQUE (kind,
        control_number): una segunda carga del MISMO número actualiza
        fecha/nota/origen en vez de duplicar. Devuelve `"deferred"` (quedó
        en espera, nueva o actualizada) o `"already"` (una carga anterior YA
        se aplicó a un proceso -- no hay nada que diferir de nuevo). Sin
        escritura alguna si `dry_run`."""
        from itcj2.apps.titulatec.models import PriorClearance

        query = db.query(PriorClearance).filter_by(kind=kind, control_number=control)
        fila = query.first() if dry_run else query.with_for_update().first()
        if fila is not None and fila.applied_process_id is not None:
            return "already"
        if dry_run:
            return "deferred"
        if fila is None:
            db.add(PriorClearance(kind=kind, control_number=control, issued_on=issued_on,
                                  note=note, source=source))
        else:
            fila.issued_on = issued_on
            fila.note = note
            fila.source = source
        db.flush()
        return "deferred"
