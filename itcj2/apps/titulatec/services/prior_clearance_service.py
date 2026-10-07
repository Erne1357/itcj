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
real. El MOTIVO fino de un conflicto de encuesta (¿GTV revocó una previa
aquí, o hay una solicitud real en revisión? m39) es, por la misma regla, otro
predicado de solo lectura del dueño: `SurveyReviewService.
prior_conflict_reason`. `test_el_servicio_nunca_lee_status_directo`
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
        completa del proceso. (m14) `_apply_survey`/`_apply_library` devuelven
        `bool` (mutó o no): solo si mutó se marca `applied_process_id`/
        `applied_at` -si `prior_outcome` ya dice `"already"` (hoy
        inalcanzable: el único llamador, `ImportService.import_rows`, siempre
        trae un proceso recién creado sin review/clearance previos) la previa
        queda SIN marcar, disponible para un proceso futuro del mismo
        control.
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
                    muto = PriorClearanceService._apply_survey(db, process, previa)
                elif previa.kind == "library":
                    muto = PriorClearanceService._apply_library(db, process, previa)
                else:
                    continue
            except ValueError:
                logger.warning(
                    "No se pudo aplicar la constancia previa %s (%s, control %s) "
                    "al proceso %s: ya no es válida.",
                    previa.id, previa.kind, control, process.id)
                continue
            if not muto:
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
    def _apply_survey(db: Session, process, previa) -> bool:
        """`True` si mutó (creó la solicitud aprobada); `False` si
        `prior_outcome` ya no dice `"apply"` -sin fila que crear (m14):
        `apply_pending` solo marca la previa cuando esto da `True`."""
        from itcj2.apps.titulatec.services.survey_review_service import SurveyReviewService

        if SurveyReviewService.prior_outcome(db, process.id) != "apply":
            return False
        # R7 (spec 2026-10-05 import-encuesta-xlsx): la diferida que vino
        # del Excel trae su respuesta y su marca de papel; se transmiten.
        # `registered_at=previa.created_at` (spec folios D5, «previa diferida»):
        # el folio sale del semestre anterior a la IMPORTACIÓN, no al de esta
        # inscripción (que puede ser semestres después).
        SurveyReviewService.register_prior(
            db, process, issued_on=previa.issued_on, note=previa.note, actor_id=None,
            response_id=previa.response_id, paper_pending=previa.paper_pending is True,
            registered_at=previa.created_at)
        if previa.response_id is not None:
            # La respuesta importada queda del egresado y de este proceso.
            from itcj2.apps.titulatec.services.survey_import_service import (
                SurveyImportService,
            )
            SurveyImportService.link_response_to_process(db, previa.response_id, process)
        return True

    @staticmethod
    def _apply_library(db: Session, process, previa) -> bool:
        """Gemela de `_apply_survey`, lado biblioteca (m14)."""
        from itcj2.apps.titulatec.services.library_clearance_service import (
            LibraryClearanceService,
        )

        if LibraryClearanceService.prior_outcome(db, process.id) != "apply":
            return False
        clearance = LibraryClearanceService.open_for_process(db, process)
        # `registered_at=previa.created_at`: igual que `_apply_survey` (D5).
        LibraryClearanceService.register_prior(
            db, clearance.id, None, issued_on=previa.issued_on, note=previa.note,
            by="import", commit=False, registered_at=previa.created_at)
        return True

    # ------------------------------------------------------------------
    # Importación por CLI
    # ------------------------------------------------------------------
    @staticmethod
    def import_rows(db: Session, *, kind: str, rows: list[dict], source: str,
                    dry_run: bool = False, today: Optional[date] = None,
                    commit: bool = True) -> dict:
        """Importa, por número de control, constancias previas de un
        semestre anterior (D9, spec §4.12). `kind` ∈ `PRIOR_KINDS` (importado
        de `models/prior_clearance.py`: fuente única, m15). `rows` = lista de
        dicts `{"control_number": str, "issued_on": str|date|None, "note":
        str|None (opcional)}` -la CLI arma esta lista desde el CSV (columna de
        control autodetectada o `--columna-control`; fecha por columna o
        `--fecha` fija)-; llamar directo desde una prueba también vale.

        Llaves OPCIONALES, solo con `kind='survey'` (spec `2026-10-05-
        titulatec-import-encuesta-xlsx-design.md` R7/D3; las manda
        `SurveyImportService`, nunca el CSV): `"response_id": int|None` (la
        `SurveyResponse` importada) y `"paper_pending": bool` (constancia
        por recoger). Con proceso abierto viajan a `register_prior`; sin él
        se guardan en la `PriorClearance` diferida y `apply_pending` las
        transmite. Una fila SIN estas llaves no toca la liga de una diferida
        pendiente que ya la tenía (un CSV posterior no la borra); al
        reemplazar una ya aplicada (Ruling R28) la previa nueva queda con lo
        que traiga la fila (sin llaves -> sin respuesta ni papel).

        Por fila:

        1. `control_number` normalizado a MAYÚSCULA y validado con
           `CONTROL_NUMBER_RE` -> bote `invalid` si no calza.
        2. `issued_on` validada (D9: obligatoria, no futura, vigente) ->
           `invalid`/`expired` si no pasa.
        3. proceso ABIERTO para ese control (activo/en pausa, fase 2 sin
           aprobar):
           - sin proceso abierto -> se DIFIERE: upsert de `PriorClearance`
             (único por `kind`+`control_number`; una fila repetida actualiza
             `source`, se queda con la `issued_on` MÁS NUEVA y conserva la `note` si la
             nueva viene vacía, en vez de duplicar) -> `deferred`.
             Si la que había YA se aplicó a un proceso anterior: con una fecha
             MÁS NUEVA la reemplaza y vuelve a quedar pendiente -> `deferred`
             (Ruling R28); con la misma fecha o una anterior, ya registrada
             -> `already`. `apply_pending` la aplicará sola cuando el alumno
             se inscriba.
           - con proceso, encuesta: sin `SurveyReview` ->
             `SurveyReviewService.register_prior` -> `applied`; con una YA
             `approved` -> `already`; `in_review`/`rejected`, o una previa
             revocada por GTV en este proceso (Ruling R30 #2) -> `conflicts`
             (lo decide GTV, no esta CLI) -- el MOTIVO distingue las dos
             (m39, `SurveyReviewService.prior_conflict_reason`): «GTV revocó
             su constancia previa; debe contestar la encuesta de egresados»
             vs «ya envió la encuesta de este semestre; lo decide GTV».
           - con proceso, biblioteca: `pending`/`awaiting_payment` ->
             `LibraryClearanceService.register_prior` -> `applied`;
             `cleared` -> `already`.

        `dry_run=True` NO toca la sesión -ni siquiera un INSERT idempotente
        que luego se deshaga-: la clasificación completa corre igual
        (incluida la vigencia y la búsqueda del proceso), pero ninguna rama
        mutadora se ejecuta. `dry_run=False` hace UN commit al final.

        Un MISMO `(kind, control_number)` repetido en `rows` -el mismo
        archivo con una fila duplicada- cuenta `applied` una sola vez; la(s)
        repetición(es) caen en `already` (m13): en la corrida real esto ya
        salía solo (`register_prior` flushea, así que `prior_outcome` ve la
        mutación de la fila anterior), pero en dry-run NADA muta la sesión y
        sin este `set` las dos filas saldrían `applied`, prometiendo más
        altas de las que la corrida real aplicaría.

        `commit=False` (lo usa `SurveyImportService.import_rows`, que escribe
        las respuestas y es dueño de la transacción completa): solo `flush()`
        al final; el llamador hace el único commit.

        Devuelve un dict con las 6 llaves de `IMPORT_BUCKETS`; cada una es
        una lista de `{"control_number": str, "reason": str}`, en el orden
        del CSV.
        """
        from itcj2.apps.titulatec.models.prior_clearance import PRIOR_KINDS
        from itcj2.apps.titulatec.services.import_service import CONTROL_NUMBER_RE
        from itcj2.apps.titulatec.services.library_clearance_service import (
            LibraryClearanceService,
        )
        from itcj2.apps.titulatec.services.survey_review_service import SurveyReviewService

        if kind not in PRIOR_KINDS:
            raise ValueError(f"Tipo de constancia previa desconocido: {kind!r}.")
        hoy = today or db_now().date()

        out: dict[str, list[dict]] = {bote: [] for bote in IMPORT_BUCKETS}
        # (kind, control) ya contados como `applied` EN ESTE MISMO archivo
        # (m13): una repetición cuenta `already` en vez de volver a sumar a
        # `applied`, en dry-run y en la corrida real por igual (en la real es
        # un no-op: `prior_outcome` ya daría `already` por sí solo).
        ya_aplicadas: set[tuple[str, str]] = set()

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
            # R7: llaves opcionales de la importación del Excel (solo encuesta).
            trae_liga = kind == "survey" and (
                "response_id" in row or "paper_pending" in row)
            response_id = row.get("response_id") if kind == "survey" else None
            paper_pending = (row.get("paper_pending") is True) if kind == "survey" else False
            proceso = _open_process_for_control(db, control)

            if proceso is None:
                bote = PriorClearanceService._defer(
                    db, kind=kind, control=control, issued_on=fecha, note=nota,
                    source=source, dry_run=dry_run,
                    link=((response_id, paper_pending) if trae_liga else None))
                if bote == "already":
                    _add("already", control,
                        "ya registrada: se aplicó antes y esta no es más nueva")
                elif bote == "replaced":
                    _add("deferred", control,
                        "más nueva que la que ya se aplicó antes; se aplicará "
                        "cuando se inscriba")
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
                if outcome == "apply" and (kind, control) in ya_aplicadas:
                    outcome = "already"          # m13: duplicado en dry-run
                if outcome == "apply":
                    if not dry_run:
                        SurveyReviewService.register_prior(
                            db, proceso, issued_on=fecha, note=nota, actor_id=None,
                            response_id=response_id, paper_pending=paper_pending)
                    ya_aplicadas.add((kind, control))
                    _add("applied", control, f"encuesta liberada en el proceso {proceso.folio}")
                elif outcome == "already":
                    _add("already", control, "la encuesta ya estaba liberada")
                else:
                    # m39: el MOTIVO del conflicto -nunca el `.status`/evento
                    # por su cuenta- lo da el dueño (§5, invariante 2).
                    motivo = SurveyReviewService.prior_conflict_reason(db, proceso.id)
                    if motivo == "revoked":
                        _add("conflicts", control,
                            "GTV revocó su constancia previa; debe contestar la "
                            "encuesta de egresados")
                    else:
                        _add("conflicts", control,
                            "ya envió la encuesta de este semestre; lo decide GTV")
            else:
                # Mismo predicado, lado biblioteca: NUNCA se lee
                # `LibraryClearance.status` aquí, ni en dry-run ni en la
                # corrida real.
                outcome = LibraryClearanceService.prior_outcome(db, proceso.id)
                if outcome == "apply" and (kind, control) in ya_aplicadas:
                    outcome = "already"          # m13: duplicado en dry-run
                if outcome == "already":
                    _add("already", control, "la Constancia de no adeudo ya estaba liberada")
                elif outcome == "conflict":
                    # «Con observaciones» (spec 2026-10-05): `register_prior`
                    # lo rechazaría; primero lo rehabilita Biblioteca.
                    _add("conflicts", control,
                        "Biblioteca registró observaciones en su Constancia de no adeudo; "
                        "lo decide Biblioteca")
                else:
                    if not dry_run:
                        clearance = LibraryClearanceService.open_for_process(db, proceso)
                        LibraryClearanceService.register_prior(
                            db, clearance.id, None, issued_on=fecha, note=nota,
                            by="import", commit=False)
                    ya_aplicadas.add((kind, control))
                    _add("applied", control,
                        f"Constancia de no adeudo liberada en el proceso {proceso.folio}")

        if not dry_run:
            # Resumen de la corrida; el commit lo decide `commit` / el llamador.
            from itcj2.apps.titulatec.services.audit_service import AuditService
            AuditService.record(
                db, "prior_clearance.import_run",
                entity_type="prior_clearance",
                payload={"kind": kind, "source": source, "rows": len(rows),
                         "counts": {b: len(v) for b, v in out.items()}},
            )
            if commit:
                db.commit()
            else:
                db.flush()
        return out

    @staticmethod
    def attach_imported_response(db: Session, *, control_number: str,
                                 response_id: Optional[int], paper_pending: bool):
        """Respuesta importada del Excel (spec `2026-10-05-titulatec-import-
        encuesta-xlsx-design.md` R7) cuyo control YA estaba liberado por una
        constancia previa SIN respuesta (p. ej. la del CSV de
        `import-prior-clearances`): se le adjunta para que GTV vea «Ver
        respuestas» y, si la fila venía en naranja, la constancia por recoger.

        Busca la solicitud previa en el proceso ABIERTO del control o, si no
        hay, en el proceso al que ya se aplicó su `PriorClearance` de
        encuesta. La mutación de la solicitud la hace su dueño
        (`SurveyReviewService.attach_imported_response`: solo previas sin
        respuesta); aquí solo se liga la `PriorClearance` aplicada a ese
        mismo proceso (si no tenía respuesta). Devuelve el proceso al que
        quedó ligada la respuesta, o `None` si no se adjuntó a nada. Sin
        commit."""
        from itcj2.apps.titulatec.models import PriorClearance, TitulationProcess
        from itcj2.apps.titulatec.services.survey_review_service import SurveyReviewService

        control = (control_number or "").strip().upper()
        if response_id is None or not control:
            return None
        previa = (db.query(PriorClearance)
                 .filter_by(kind="survey", control_number=control)
                 .with_for_update().first())
        proceso = _open_process_for_control(db, control)
        review = SurveyReviewService.get_for_process(db, proceso.id) if proceso else None
        if review is None and previa is not None and previa.applied_process_id is not None:
            proceso = db.get(TitulationProcess, previa.applied_process_id)
            review = (SurveyReviewService.get_for_process(db, proceso.id)
                      if proceso is not None else None)
        if review is None or not SurveyReviewService.attach_imported_response(
                db, review, response_id=response_id, paper_pending=paper_pending):
            return None
        if (previa is not None and previa.applied_process_id == proceso.id
                and previa.response_id is None):
            previa.response_id = response_id
            previa.paper_pending = paper_pending is True
            db.flush()
        return proceso

    @staticmethod
    def _defer(db: Session, *, kind: str, control: str, issued_on: date,
              note: Optional[str], source: str, dry_run: bool,
              link: Optional[tuple[Optional[int], bool]] = None) -> str:
        """Registra (o actualiza) la `PriorClearance` diferida de `control`.
        UNIQUE (kind, control_number): una segunda carga del MISMO número
        actualiza origen (y la fecha si es MÁS NUEVA; la nota si no viene
        vacía) en vez de duplicar. Devuelve:

        * `"deferred"` -- quedó en espera (nueva, o una pendiente actualizada);
        * `"replaced"` -- Ruling R28 (M5 de la revisión final): la que había
          YA se aplicó a un proceso anterior (revocado o terminado) y esta es
          MÁS NUEVA -otro semestre-: reemplaza fecha/nota/origen y limpia
          `applied_*`, así que queda pendiente para un proceso futuro
          (`apply_pending`). La aplicada vieja sigue en su proceso (su
          `SurveyReview`/`LibraryClearance`); solo deja de estar en este
          registro;
        * `"already"` -- la que había ya se aplicó y esta NO es más nueva
          (misma fecha o anterior): ya registrada, no se toca nada.

        `link` = `(response_id, paper_pending)` de la importación del Excel
        (R7), o `None` si la fila no los trae: en una fila NUEVA o
        REEMPLAZADA se escribe tal cual (`None` -> sin respuesta ni papel);
        en una pendiente que se actualiza, `None` deja intacta la liga que
        ya tenía.

        Sin escritura alguna si `dry_run` (la clasificación es la misma)."""
        from itcj2.apps.titulatec.models import PriorClearance

        query = db.query(PriorClearance).filter_by(kind=kind, control_number=control)
        fila = query.first() if dry_run else query.with_for_update().first()
        reemplaza = False
        if fila is not None and fila.applied_process_id is not None:
            if fila.issued_on is not None and issued_on <= fila.issued_on:
                return "already"
            reemplaza = True
        if dry_run:
            return "replaced" if reemplaza else "deferred"
        response_id, paper_pending = link if link is not None else (None, False)
        antes = None
        if reemplaza:
            antes = {"issued_on": fila.issued_on, "note": fila.note,
                     "source": fila.source,
                     "applied_process_id": fila.applied_process_id}
        if fila is None:
            db.add(PriorClearance(kind=kind, control_number=control, issued_on=issued_on,
                                  note=note, source=source, response_id=response_id,
                                  paper_pending=paper_pending))
        elif reemplaza:
            fila.issued_on = issued_on
            fila.note = note
            fila.source = source
        else:
            # Pendiente que se actualiza (ruling Tarea 2 de la importación del
            # Excel): gana la fecha MÁS NUEVA -una carga posterior con fecha
            # vieja no acorta la vigencia- y una nota vacía no borra la que
            # ya había (el Excel no trae nota; la del CSV se conserva).
            if fila.issued_on is None or issued_on > fila.issued_on:
                fila.issued_on = issued_on
            if note:
                fila.note = note
            fila.source = source
        if fila is not None:
            if reemplaza:
                fila.applied_process_id = None
                fila.applied_at = None
            if reemplaza or link is not None:
                fila.response_id = response_id
                fila.paper_pending = paper_pending
        db.flush()
        from itcj2.apps.titulatec.services.audit_service import AuditService
        if reemplaza:
            AuditService.record(
                db, "prior_clearance.replaced",
                entity_type="prior_clearance", entity_id=fila.id,
                subject=control,
                before=AuditService.safe(antes),
                after=AuditService.safe({"issued_on": issued_on, "note": note,
                                         "source": source,
                                         "applied_process_id": None}),
                payload={"kind": kind},
            )
            return "replaced"
        AuditService.record(
            db, "prior_clearance.deferred",
            entity_type="prior_clearance",
            entity_id=fila.id if fila is not None else None,
            subject=control,
            after=AuditService.safe({"issued_on": fila.issued_on if fila else issued_on,
                                     "note": fila.note if fila else note,
                                     "source": source}),
            payload={"kind": kind},
        )
        return "deferred"
