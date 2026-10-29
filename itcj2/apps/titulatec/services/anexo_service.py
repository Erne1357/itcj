"""Anexo III (fase 6): folio, firmas requeridas, PDF al vuelo y dictamen -- spec fase 6 §5-§10.

El PDF se regenera cada vez que se pide (como el oficio de sinodales); lo unico
que se guarda es el folio y la fecha de liberacion en `titulatec_anexos`, para
que reimprimir no cambie el documento. Todo lo que pinta la plantilla
(`oficios/anexo_iii.html`) llega precalculado en `context`: no decide nada.

Descarga en dos pasos (revision final de la fase 6): `prepare_pdf` emite el
folio si hace falta y arma el contexto UNA vez, bajo el bloqueo del proceso;
la ruta hace `commit` (suelta el bloqueo, y el del contador en la primera
emision) y solo despues `render` pinta con WeasyPrint, fuera de la transaccion.

Las firmas requeridas salen SOLO de `ReviewService.counting_roles` (el unico
traductor de `Modality.signature_rule`).

`AnexoService` es la UNICA puerta de la fase 6 (`PhaseService._DOOR_PHASES`):
el escaneo firmado es un `Document` de tipo `DOC_TYPE`; subirlo o borrarlo
sincroniza la fase (`sync_phase`, desde `DocumentService.save`/`delete`) y
solo `approve`/`observe` lo dictaminan, junto con la fase, en UNA transaccion.
Invariante: fase 6 `approved` <=> escaneo `approved`.

Entrega (fase 6 v2, spec 2026-10-29): el oficial lo imprime vinculacion y lo
marca «Listo para recoger» (`mark_ready`); el alumno solo ve la vista previa
con marca de agua (`preview_pdf`, nunca escribe) y sube el escaneo en `ready`,
`observed` o `in_review` (reemplazo sin dictamen, C6 del v1); Titulacion puede
pedir reimpresion (`observe(reprint=True)`). La
etapa (`STAGES`) es una lectura derivada con UNA duena: `stage`/`stage_map`.
"""
from __future__ import annotations

import logging

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from itcj2.apps.titulatec.services.oficio_service import (
    FOOTER_ADDRESS, FOOTER_CONTACT, NO_SYNODALS_MSG,
    OficioService, _date_label,
)
from itcj2.core.utils.timezone import db_now

logger = logging.getLogger(__name__)

PHASE_CODE = "anexo_iii"
# Tipo de documento del escaneo firmado (`titulatec_document_types`, fase 6).
DOC_TYPE = "anexo_iii"
REVIEW_PHASE_CODE = "synodal_review"
SYNODALS_REQUIRED = 4
REASON_MAX = 500

NOT_OPERABLE_MSG = "El Anexo III todavia no se opera en esta app."
NOT_REACHED_MSG = "El proceso todavia no llega al Anexo III."
NO_DEPARTMENT_MSG = "La carrera del proceso no esta ligada a un departamento academico."
NO_MODALITY_MSG = "El proceso no tiene una modalidad con producto definido."
NOT_IN_REVIEW_MSG = ("Este Anexo III no esta por revisar: el alumno aun no sube el "
                     "escaneo firmado o ya fue dictaminado.")
REASON_REQUIRED_MSG = "Escribe el motivo de la observacion."
REASON_TOO_LONG_MSG = "El motivo de la observacion admite hasta 500 caracteres."

DEPARTMENT_HEAD_LABEL = "Jefe(a) del departamento académico"
# Quién firma cuando la regla de firma no se puede leer (proceso sin modalidad
# o regla desconocida): texto neutro en vez de un 500 (revisión final, punto 12).
# Fase 6 v2: la firma y el sello del jefe ya vienen en el original impreso; el
# alumno solo junta las de sus sinodales.
SIGNERS_FALLBACK_TEXT = ("La firma y el sello del jefe del departamento académico ya vienen "
                         "en el original que te entrega vinculación; tú juntas las firmas de "
                         "los sinodales que indique tu modalidad.")
VERSION_CHANGED_MSG = "El alumno subio otro escaneo; revisalo de nuevo."

# Entrega (spec 2026-10-29 §4). Nadie fuera de `stage`/`stage_map` compara
# `ready_at`/`reprint_*` para decidir en que va el Anexo.
STAGES = ("preparing", "reprint", "ready", "in_review", "observed", "approved")
STAGE_LABELS = {
    "preparing": "En preparación",
    "reprint": "Reimpresión",
    "ready": "Por recoger",
    "in_review": "En revisión",
    "observed": "Con observaciones",
    "approved": "Aprobado",
}
# Desde donde vinculacion marca listo (§10) y desde donde el alumno sube (§4;
# `in_review` = reemplazar el escaneo sin dictamen, C6 del v1, Ruling del controlador).
_PREPARABLE_STAGES = ("preparing", "reprint", "ready")
UPLOAD_STAGES = ("ready", "observed", "in_review")
NOTE_MAX = 300
NOTE_REQUIRED_MSG = "Escribe el lugar y el horario para recoger el Anexo III."
NOTE_TOO_LONG_MSG = "La nota de recogida admite hasta 300 caracteres."
NOT_PREPARABLE_MSG = ("Este Anexo III ya no se puede marcar listo: el alumno ya subio "
                      "el escaneo o ya fue aprobado.")
NO_FOLIO_REPRINT_MSG = "Este Anexo III no tiene folio: no hay nada que reimprimir."
STAGE_CHANGED_MSG = "El Anexo III cambio de etapa mientras lo veias; revisalo de nuevo."
# Guarda de subida del escaneo (`DocumentService.save`, las dos rutas del alumno).
ANEXO_NOT_READY_MSG = ("Tu Anexo III todavia no esta listo para recoger: aun no puedes "
                       "subir el escaneo.")


def _stage_of(phase_status, reprint_requested_at, ready_at) -> str:
    """Orden EXACTO de spec §4: gana la primera regla que aplica."""
    if phase_status == "approved":
        return "approved"
    if reprint_requested_at is not None:
        return "reprint"
    if phase_status == "in_review":
        return "in_review"
    if phase_status == "rejected":
        return "observed"
    if ready_at is not None:
        return "ready"
    return "preparing"


class AnexoStageChanged(ValueError):
    """`mark_ready(expected_stage=...)` encontro OTRA etapa bajo el bloqueo: el
    formulario de vinculacion estaba viejo (molde `AnexoVersionChanged`). Nada
    se escribe; la ruta la distingue para re-pintar con aviso."""


class AnexoVersionChanged(ValueError):
    """`approve`/`observe(expected_version=N)` encontro OTRA version del escaneo:
    el alumno lo reemplazo entre que Titulacion lo vio y lo dictamino (Ruling R5
    de la fase 6; molde `DocumentVersionChanged`). Subclase de `ValueError`
    para que cualquier `except ValueError` la siga atrapando; la ruta la
    distingue para contestar 200 + aviso en vez de 400."""


# Estados de la fase 6 desde los que una subida la pone «Por revisar» (C6).
_SYNC_TO_REVIEW = ("in_progress", "rejected", "in_review")

# Leyendas de la tarjeta de la fase 6 del expediente (`AnexoService.empty_label`).
NOT_APPLICABLE_LABEL = "No aplica para esta modalidad."
NOT_IN_APP_LABEL = ("Esta fase todavía no está en la app: el Anexo III se lleva "
                    "en T-soft. Lo que se ve aquí es su estado, no su contenido.")
PENDING_LABEL = "El proceso todavía no llega al Anexo III."

_TEMPLATE_NAME = "titulatec/oficios/anexo_iii.html"


class AnexoService:

    # ------------------------------------------------------------------
    # Corte y alcance
    # ------------------------------------------------------------------
    @staticmethod
    def phase_number(db: Session) -> int | None:
        from itcj2.apps.titulatec.services.phase_service import PhaseService
        return PhaseService.phase_number_for_code(db, PHASE_CODE)

    @staticmethod
    def operable(db: Session) -> bool:
        """¿La fase 6 se opera en esta app? Falla cerrado (corte o sin catalogo)."""
        from itcj2.apps.titulatec.services.phase_service import PhaseService
        return PHASE_CODE in PhaseService.operable_codes(db, [PHASE_CODE])

    @staticmethod
    def reached(db: Session, process) -> bool:
        """Fase 6 en el catalogo, proceso no cancelado, `current_phase >= n6` y
        su `ProcessPhase` no `skipped`."""
        from itcj2.apps.titulatec.models import ProcessPhase

        n = AnexoService.phase_number(db)
        if n is None or process is None or process.status == "cancelled":
            return False
        if (process.current_phase or 0) < n:
            return False
        estado = (db.query(ProcessPhase.status)
                  .filter(ProcessPhase.process_id == process.id,
                          ProcessPhase.phase_number == n).scalar())
        return estado != "skipped"

    @staticmethod
    def empty_label(db: Session, process) -> str | None:
        """Leyenda de la tarjeta de la fase 6 del expediente, o None si ahí va
        el ESTADO (estado + folio + ligas). Molde de `ReviewService.empty_label`:

        - La modalidad salta la fase 6 (`skips_phases`, p. ej. EGEL) o su
          `ProcessPhase` ya está `skipped` -> `NOT_APPLICABLE_LABEL`. Gana
          sobre el corte: es un hecho de la modalidad.
        - La fase 6 no se opera en esta app (corte en ella o antes, o sin la
          fase en el catálogo) -> `NOT_IN_APP_LABEL`.
        - El proceso todavía no llega a la fase 6 -> `PENDING_LABEL`.
        - Si no, None.
        Dos consultas a lo más (número de fase y estado de su `ProcessPhase`).
        """
        from itcj2.apps.titulatec.models import ProcessPhase
        from itcj2.apps.titulatec.services.phase_service import PhaseService

        n = AnexoService.phase_number(db)
        if n is not None and process is not None:
            if n in PhaseService._skips(process):
                return NOT_APPLICABLE_LABEL
            estado = (db.query(ProcessPhase.status)
                      .filter(ProcessPhase.process_id == process.id,
                              ProcessPhase.phase_number == n).scalar())
            if estado == "skipped":
                return NOT_APPLICABLE_LABEL
        if n is None or PhaseService._handoff_phase() <= n:
            return NOT_IN_APP_LABEL
        if process is None or (process.current_phase or 0) < n:
            return PENDING_LABEL
        return None

    # ------------------------------------------------------------------
    # Etapa de la entrega (spec 2026-10-29 §4): UNA lectura, sin N+1
    # ------------------------------------------------------------------
    @staticmethod
    def stage(db: Session, process) -> str | None:
        """Etapa de la fase 6 (`STAGES`), o None si el Anexo no se opera o el
        proceso no la alcanzo (`reached`). Es `stage_map` de un proceso: lee
        la BD (bajo el bloqueo del proceso, lo que dejo quien llego antes)."""
        if process is None:
            return None
        return AnexoService.stage_map(db, [process.id]).get(process.id)

    @staticmethod
    def stage_map(db: Session, process_ids) -> dict[int, str]:
        """`{process_id: etapa}` en 3 consultas fijas (operable, numero de la
        fase y una con la fase 6 y el Anexo unidos). Los procesos que no
        alcanzaron la fase 6 (mismo criterio que `reached`) no salen."""
        from sqlalchemy import and_, func

        from itcj2.apps.titulatec.models import Anexo, ProcessPhase, TitulationProcess

        ids = sorted({int(i) for i in (process_ids or ()) if i is not None})
        if not ids or not AnexoService.operable(db):
            return {}
        n = AnexoService.phase_number(db)
        filas = (db.query(TitulationProcess.id, ProcessPhase.status,
                          Anexo.reprint_requested_at, Anexo.ready_at)
                 .outerjoin(ProcessPhase, and_(ProcessPhase.process_id == TitulationProcess.id,
                                               ProcessPhase.phase_number == n))
                 .outerjoin(Anexo, Anexo.process_id == TitulationProcess.id)
                 .filter(TitulationProcess.id.in_(ids),
                         TitulationProcess.status != "cancelled",
                         func.coalesce(TitulationProcess.current_phase, 0) >= n)
                 .order_by(TitulationProcess.id).all())
        return {pid: _stage_of(estado, reimpresion, listo)
                for pid, estado, reimpresion, listo in filas if estado != "skipped"}

    @staticmethod
    def ready_info(db: Session, process) -> dict | None:
        """Datos de la entrega en tipos planos (la plantilla se pinta tras el
        `db.close()`), o None sin fila o con el Anexo inoperable."""
        from itcj2.apps.titulatec.utils.dates_es import dia_mes_hora

        if process is None:
            return None
        return AnexoService.ready_map(db, [process.id]).get(process.id)

    @staticmethod
    def ready_map(db: Session, process_ids) -> dict[int, dict]:
        """`ready_info` en lote: `{process_id: dict}` en UNA consulta (sin fila
        del Anexo, o Anexo inoperable, no hay entrada)."""
        from itcj2.apps.titulatec.models import Anexo
        from itcj2.apps.titulatec.utils.dates_es import dia_mes_hora

        ids = sorted({int(i) for i in (process_ids or ()) if i is not None})
        if not ids or not AnexoService.operable(db):
            return {}
        return {
            a.process_id: {
                "ready_at": a.ready_at,
                "ready_label": dia_mes_hora(a.ready_at) if a.ready_at else None,
                "pickup_note": a.pickup_note,
                "reprint_reason": a.reprint_reason,
                "reprint_requested_at": a.reprint_requested_at,
                "folio": a.folio,
            }
            for a in db.query(Anexo).filter(Anexo.process_id.in_(ids)).all()
        }

    @staticmethod
    def default_pickup_note(db: Session, process) -> str | None:
        """Precarga de la nota de recogida (E3, spec §5): la propia del Anexo
        si ya tiene (se conserva al pedir reimpresion); si no, la del Anexo
        listo mas reciente (`ready_at`) de una carrera del MISMO departamento
        academico (`department_of_program`, el mapeo del oficio). None sin
        antecedente o sin departamento."""
        from itcj2.apps.titulatec.models import Anexo, ProgramDepartment, TitulationProcess
        from itcj2.apps.titulatec.services.scope_service import department_of_program

        propia = (db.query(Anexo.pickup_note)
                  .filter(Anexo.process_id == process.id).scalar())
        if propia:
            return propia
        depto = (department_of_program(db, process.program_id)
                 if process.program_id else None)
        if depto is None:
            return None
        return (db.query(Anexo.pickup_note)
                .join(TitulationProcess, TitulationProcess.id == Anexo.process_id)
                .join(ProgramDepartment,
                      ProgramDepartment.program_id == TitulationProcess.program_id)
                .filter(ProgramDepartment.department_id == depto,
                        Anexo.ready_at.isnot(None), Anexo.pickup_note.isnot(None))
                .order_by(Anexo.ready_at.desc(), Anexo.id.desc())
                .limit(1).scalar())

    # ------------------------------------------------------------------
    # Firmas
    # ------------------------------------------------------------------
    @staticmethod
    def required_signers(process) -> list[str]:
        """`["department_head", *roles que cuentan]`. `ValueError` si la regla
        de firma es desconocida (falla cerrado)."""
        from itcj2.apps.titulatec.services.review_service import ReviewService
        return ["department_head",
                *ReviewService.counting_roles(ReviewService.rule_for(process))]

    @staticmethod
    def signer_labels(process) -> list[str]:
        """`required_signers` en etiquetas de pantalla (Titulacion). `ValueError`
        si la regla de firma es desconocida."""
        from itcj2.apps.titulatec.services.synodal_service import ROLE_LABELS

        return [DEPARTMENT_HEAD_LABEL if r == "department_head" else ROLE_LABELS.get(r, r)
                for r in AnexoService.required_signers(process)]

    @staticmethod
    def signers_text(process) -> str:
        """Quien firma, en lenguaje llano (alumno y Titulacion)."""
        from itcj2.apps.titulatec.services.synodal_service import ROLE_LABELS

        roles = [r for r in AnexoService.required_signers(process) if r != "department_head"]
        if len(roles) == 1:
            sinodales = f"la firma del {ROLE_LABELS.get(roles[0], roles[0])}"
        else:
            sinodales = f"las firmas de tus {len(roles)} sinodales"
        return ("La firma y el sello del jefe del departamento académico ya vienen en el "
                f"original que te entrega vinculación; tú juntas {sinodales}.")

    # ------------------------------------------------------------------
    # Folio
    # ------------------------------------------------------------------
    @staticmethod
    def get(db: Session, process_id: int):
        from itcj2.apps.titulatec.models import Anexo
        return db.query(Anexo).filter(Anexo.process_id == process_id).first()

    @staticmethod
    def _released_at(db: Session, process):
        """Fin de la fase 5: `completed_at` de su `ProcessPhase`, respaldo el
        evento `phase_approved` de esa fase, ultimo recurso `db_now()`."""
        from itcj2.apps.titulatec.models import ProcessEvent, ProcessPhase
        from itcj2.apps.titulatec.services.phase_service import PhaseService

        n5 = PhaseService.phase_number_for_code(db, REVIEW_PHASE_CODE)
        if n5 is not None:
            cuando = (db.query(ProcessPhase.completed_at)
                      .filter(ProcessPhase.process_id == process.id,
                              ProcessPhase.phase_number == n5).scalar())
            if cuando is not None:
                return cuando
            cuando = (db.query(ProcessEvent.created_at)
                      .filter(ProcessEvent.process_id == process.id,
                              ProcessEvent.event_type == "phase_approved",
                              ProcessEvent.phase_number == n5)
                      .order_by(ProcessEvent.id.desc()).limit(1).scalar())
            if cuando is not None:
                return cuando
        return db_now()

    @staticmethod
    def _next_number(db: Session, semester: str) -> int:
        """Contador atomico por semestre: UNA sentencia, nace en 1."""
        from sqlalchemy.dialects.postgresql import insert as pg_insert
        from itcj2.apps.titulatec.models import AnexoCounter

        tabla = AnexoCounter.__table__
        stmt = (pg_insert(tabla)
                .values(semester=semester, last_value=1)
                .on_conflict_do_update(
                    index_elements=["semester"],
                    set_={"last_value": tabla.c.last_value + 1})
                .returning(tabla.c.last_value))
        return db.execute(stmt).scalar_one()

    @staticmethod
    def ensure_folio(db: Session, process, actor_id: int | None):
        """El `Anexo` del proceso; lo crea (folio + fecha congelada) la primera
        vez. Sin commit. `ValueError` si la fase no se opera, no se alcanzo o los
        datos del documento estan incompletos: ANTES de numerar valida con
        `context` (4 sinodales, departamento, modalidad con producto), asi que
        un folio nunca se quema por datos invalidos sin importar el llamador."""
        return AnexoService._ensure(db, process, actor_id)[0]

    @staticmethod
    def _ensure(db: Session, process, actor_id: int | None):
        """`(anexo, contexto | None)`. Nucleo de `ensure_folio`/`prepare_pdf`.

        Bajo el bloqueo del proceso: relee y, si no hay fila, valida con
        `context` (falla cerrado) y numera. En la primera emision devuelve ese
        mismo contexto con el folio recien emitido (asi `prepare_pdf` no lo
        vuelve a calcular); si la fila ya existia (o gano otro la carrera),
        `None`."""
        from itcj2.apps.titulatec.models import Anexo
        from itcj2.apps.titulatec.services.audit_service import AuditService
        from itcj2.apps.titulatec.services.certificate_service import semester_key
        from itcj2.apps.titulatec.services.phase_service import PhaseService

        if not AnexoService.operable(db):
            raise ValueError(NOT_OPERABLE_MSG)
        PhaseService._lock_process_row(db, process)
        if not AnexoService.reached(db, process):
            raise ValueError(NOT_REACHED_MSG)
        existente = AnexoService.get(db, process.id)
        if existente is not None:
            return existente, None

        ctx = AnexoService.context(db, process)     # falla cerrado antes de numerar
        ahora = db_now()
        semestre = semester_key(ahora)
        liberado = AnexoService._released_at(db, process)
        try:
            with db.begin_nested():
                n = AnexoService._next_number(db, semestre)
                anexo = Anexo(process_id=process.id, folio=f"AIII-{semestre}-{n:04d}",
                              semester=semestre, released_at=liberado,
                              issued_at=ahora, issued_by_id=actor_id)
                db.add(anexo)
                db.flush()
        except IntegrityError:
            # Otro proceso gano la carrera: se relee su fila.
            existente = AnexoService.get(db, process.id)
            if existente is None:
                raise
            return existente, None

        datos = {"folio": anexo.folio, "semester": semestre}
        PhaseService._log(db, process.id, actor_id, "anexo_iii_issued",
                          AnexoService.phase_number(db), dict(datos))
        AuditService.record(
            db, "anexo_iii.issued",
            entity_type="anexo", entity_id=anexo.id,
            process_id=process.id, subject=process.folio,
            payload=dict(datos), actor_id=actor_id)
        # El contexto se armo antes de numerar (sin fila): le faltan el folio y
        # la fecha CONGELADA (la misma que leera cada reimpresion).
        ctx["folio"] = anexo.folio
        ctx["date_label"] = _date_label(anexo.released_at)
        return anexo, ctx

    # ------------------------------------------------------------------
    # Sincronia de la subida (C6)
    # ------------------------------------------------------------------
    @staticmethod
    def sync_phase(db: Session, process) -> str | None:
        """Sincroniza la `ProcessPhase` de la fase 6 con el escaneo firmado.

        Molde de `DocumentService.sync_initial_phase`: es un efecto secundario
        de `DocumentService.save`/`delete` del tipo de la fase 6, no una guarda
        (nunca lanza). Solo actua con el Anexo operable y el proceso `active`
        parado en la fase 6:

        - escaneo presente -> `in_review` si estaba `in_progress`, `rejected`
          o `in_review`, y SIEMPRE `updated_at = db_now()`: es la clave FIFO de
          la bandeja de Titulacion, asi que cada subida (tambien un reemplazo
          sin dictamen) manda el escaneo al final de la cola;
        - escaneo ausente -> `in_progress` si estaba `in_review`;
        - nunca toca `approved`, `skipped` ni `pending` (ni crea la fila).

        Devuelve el estado escrito o None. Sin commit ni flush: lo hace el
        llamador, que ademas tiene la fila del proceso bloqueada y releida (asi
        `current_phase` no es el que se leyo antes de comprimir el PDF). La
        fase se relee (`populate_existing`) por lo mismo: un objeto viejo de la
        sesion escribiria encima del dictamen de otro.
        """
        from itcj2.apps.titulatec.models import Document, ProcessPhase

        if process.status != "active":
            return None
        n = AnexoService.phase_number(db)
        if n is None or process.current_phase != n or not AnexoService.operable(db):
            return None

        presente = (db.query(Document.id)
                    .filter(Document.process_id == process.id,
                            Document.type_code == DOC_TYPE)
                    .first()) is not None
        fase = (db.query(ProcessPhase)
                .filter_by(process_id=process.id, phase_number=n)
                .populate_existing().first())
        if fase is None:
            return None
        if presente:
            if fase.status not in _SYNC_TO_REVIEW:
                return None
            nuevo = "in_review"
        else:
            if fase.status != "in_review":
                return None
            nuevo = "in_progress"
        fase.status = nuevo
        fase.updated_at = db_now()
        return nuevo

    # ------------------------------------------------------------------
    # Entrega: vinculacion lo marca «Listo para recoger» (spec 2026-10-29 §10)
    # ------------------------------------------------------------------
    @staticmethod
    def mark_ready(db: Session, process, actor_id: int, note: str, *,
                   expected_stage: str | None = None) -> dict:
        """Marca el Anexo listo para recoger con la nota de lugar y horario.

        Nota `strip()`, 1..`NOTE_MAX`, validada antes del bloqueo (invalida no
        escribe nada). Bajo el bloqueo del proceso: alcanzado, etapa
        `preparing`/`reprint`/`ready` (`NOT_PREPARABLE_MSG`) y la guarda del
        motor (`assert_can_transition`: activo, fase en curso, corte); emite el
        folio si falta (`ensure_folio` valida antes con `context`).

        - Desde `preparing`/`reprint` (`first=True`): `ready_at`/`ready_by_id`,
          limpia la reimpresion y encola el correo `anexo_ready`. Tras una
          reimpresion la fase 6 vuelve de `rejected` a `in_progress`: sin eso
          la etapa seria `observed` (regla 4 antes que la 5) y no `ready`.
        - En `ready` (`first=False`): solo cambia la nota (sin correo); con la
          MISMA nota (tras `strip()`) no escribe nada (`changed=False`).

        `expected_stage` (opcional): la etapa que vinculacion tenia en pantalla;
        bajo el bloqueo, si cambio, `AnexoStageChanged` sin escribir nada.
        Evento `anexo_iii_ready` y bitacora `anexo_iii.ready` en cada escritura.
        Sin commit (lo hace la ruta); error bajo el bloqueo: rollback y se
        re-lanza. Devuelve `{"anexo", "first", "changed"}` (`changed`: se
        escribio algo; la ruta toca la campana solo con `first or changed`).
        """
        from itcj2.apps.titulatec.models import ProcessPhase
        from itcj2.apps.titulatec.services.audit_service import AuditService
        from itcj2.apps.titulatec.services.phase_service import PhaseService
        from itcj2.apps.titulatec.services.student_mail import StudentMail

        if not AnexoService.operable(db):
            raise ValueError(NOT_OPERABLE_MSG)
        nota = (note or "").strip()
        if not nota:
            raise ValueError(NOTE_REQUIRED_MSG)
        if len(nota) > NOTE_MAX:
            raise ValueError(NOTE_TOO_LONG_MSG)
        try:
            PhaseService._lock_process_row(db, process)
            if not AnexoService.reached(db, process):
                raise ValueError(NOT_REACHED_MSG)
            etapa = AnexoService.stage(db, process)
            if expected_stage is not None and etapa != expected_stage:
                raise AnexoStageChanged(STAGE_CHANGED_MSG)
            if etapa not in _PREPARABLE_STAGES:
                raise ValueError(NOT_PREPARABLE_MSG)
            n = AnexoService.phase_number(db)
            PhaseService.assert_can_transition(db, process, n)
            anexo = AnexoService.ensure_folio(db, process, actor_id)

            first = etapa != "ready"
            if not first and anexo.pickup_note == nota:
                return {"anexo": anexo, "first": False, "changed": False}
            anexo.pickup_note = nota
            if first:
                anexo.ready_at = db_now()
                anexo.ready_by_id = actor_id
                anexo.reprint_reason = None
                anexo.reprint_requested_at = None
                fase = (db.query(ProcessPhase)
                        .filter_by(process_id=process.id, phase_number=n)
                        .populate_existing().first())
                if fase is not None and fase.status == "rejected":
                    fase.status = "in_progress"
            datos = {"folio": anexo.folio, "note": nota, "first": first}
            PhaseService._log(db, process.id, actor_id, "anexo_iii_ready", n, dict(datos))
            AuditService.record(
                db, "anexo_iii.ready",
                entity_type="anexo", entity_id=anexo.id,
                process_id=process.id, subject=process.folio,
                payload=dict(datos), actor_id=actor_id)
            if first:
                StudentMail.anexo_ready(db, process, folio=anexo.folio, note=nota)
            db.flush()
            return {"anexo": anexo, "first": first, "changed": True}
        except Exception:
            db.rollback()
            raise

    # ------------------------------------------------------------------
    # Dictamen de Titulacion (puerta unica, spec §10)
    # ------------------------------------------------------------------
    @staticmethod
    def _state(db: Session, process, n, *, locked: bool):
        """`(escaneo, estado de la fase 6)`. Sin `locked`: lo que ya hay en la
        sesion (pre-chequeo). Con `locked` (bajo el bloqueo del proceso): el
        escaneo `FOR UPDATE` y los dos releidos con `populate_existing`, asi la
        verificacion ve lo que dejo quien llego antes."""
        from itcj2.apps.titulatec.models import Document, ProcessPhase
        from itcj2.apps.titulatec.services.document_service import DocumentService

        if locked:
            doc = DocumentService._locked_document(db, process.id, DOC_TYPE)
        else:
            doc = (db.query(Document)
                   .filter_by(process_id=process.id, type_code=DOC_TYPE).first())
        consulta = db.query(ProcessPhase).filter_by(process_id=process.id, phase_number=n)
        if locked:
            consulta = consulta.populate_existing()
        fase = consulta.first()
        return doc, (fase.status if fase is not None else None)

    @staticmethod
    def _assert_in_review(db: Session, process, n, *, locked: bool):
        """«Por revisar» + guarda del motor, sin escribir. Devuelve el escaneo.

        Se corre DOS veces (molde de `FormatBService._assert_in_review`): sin
        bloqueo sobre lo cargado (lo comun falla sin tomar candado ni deshacer
        nada) y bajo el bloqueo sobre lo releido. Orden: Anexo operable
        (`NOT_OPERABLE_MSG`), fase 6 `in_review` con el escaneo presente y
        `pending` (`NOT_IN_REVIEW_MSG`) y `assert_can_transition` (proceso
        `active`, fase en curso, corte).
        """
        from itcj2.apps.titulatec.services.phase_service import PhaseService

        if not AnexoService.operable(db):
            raise ValueError(NOT_OPERABLE_MSG)
        doc, estado = AnexoService._state(db, process, n, locked=locked)
        if estado != "in_review" or doc is None or doc.review_status != "pending":
            raise ValueError(NOT_IN_REVIEW_MSG)
        PhaseService.assert_can_transition(db, process, n)
        return doc

    @staticmethod
    def approve(db: Session, process, reviewer_id: int, *,
                expected_version: int | None = None) -> dict:
        """Titulacion aprueba el escaneo y, en la MISMA transaccion, la fase 6.

        Escaneo `approved` (sin nota) + `approve_phase` con la puerta abierta:
        el proceso pasa a la siguiente fase aplicable (la 7). Cualquier error
        bajo el bloqueo: `rollback` y se re-lanza. Devuelve lo de
        `approve_phase`. `expected_version` (opcional) es la version del
        escaneo que Titulacion tenia en pantalla: bajo el bloqueo, si cambio,
        `AnexoVersionChanged` sin escribir nada.
        """
        n = AnexoService.phase_number(db)
        AnexoService._assert_in_review(db, process, n, locked=False)
        return AnexoService._dictaminar(db, process, n, reviewer_id, "approved", None,
                                        expected_version=expected_version)

    @staticmethod
    def observe(db: Session, process, reviewer_id: int, *, reason: str,
                expected_version: int | None = None, reprint: bool = False) -> None:
        """Titulacion observa el escaneo: escaneo `rejected` con el motivo y
        `reject_phase` (el alumno lo ve y vuelve a subir, C6). Motivo
        obligatorio (`REASON_REQUIRED_MSG`) y de a lo mas `REASON_MAX`
        caracteres tras `strip()` (`REASON_TOO_LONG_MSG`); se valida antes de
        tomar el bloqueo, asi que un motivo invalido no escribe nada.
        `expected_version`: igual que en `approve`.

        `reprint=True` (E4, «Requiere reimpresion»): en la MISMA transaccion
        el Anexo regresa a vinculacion -- `ready_at`/`ready_by_id` a NULL,
        `reprint_reason` = motivo, `reprint_requested_at` -- con folio,
        semestre y fecha congelada intactos; evento
        `anexo_iii_reprint_requested` y bitacora `anexo_iii.reprint_requested`."""
        n = AnexoService.phase_number(db)
        AnexoService._assert_in_review(db, process, n, locked=False)
        motivo = (reason or "").strip()
        if not motivo:
            raise ValueError(REASON_REQUIRED_MSG)
        if len(motivo) > REASON_MAX:
            raise ValueError(REASON_TOO_LONG_MSG)
        AnexoService._dictaminar(db, process, n, reviewer_id, "rejected", motivo,
                                 expected_version=expected_version, reprint=reprint)

    @staticmethod
    def _dictaminar(db: Session, process, n: int, reviewer_id: int, veredicto: str,
                    motivo: str | None, *, expected_version: int | None = None,
                    reprint: bool = False):
        """Bloqueo -> re-chequeo -> escaneo + bitacora -> puerta -> motor.

        El escaneo se escribe y se hace `flush` ANTES del motor: `_door_guard`
        lo lee de la BD (`_door_state_ok`) y `approve_phase`/`reject_phase`
        releen el proceso con `populate_existing`. La ronda es la `version` del
        documento; el evento del motor lleva `{"anexo_iii": {folio, round}}`
        (un evento por dictamen, sin duplicar). La puerta se cierra pase lo que
        pase; cualquier error bajo el bloqueo hace `rollback`. `reprint`: ver
        `observe` (se escribe antes del motor, que hace el commit).
        """
        from itcj2.apps.titulatec.services.audit_service import AuditService
        from itcj2.apps.titulatec.services.phase_service import PhaseService

        try:
            PhaseService._lock_process_row(db, process)
            doc = AnexoService._assert_in_review(db, process, n, locked=True)
            if expected_version is not None and doc.version != expected_version:
                raise AnexoVersionChanged(VERSION_CHANGED_MSG)
            anexo = AnexoService.get(db, process.id)
            if reprint and anexo is None:
                raise ValueError(NO_FOLIO_REPRINT_MSG)
            doc.review_status = veredicto
            doc.review_note = motivo
            doc.reviewed_by_id = reviewer_id
            ronda = doc.version
            AuditService.record(
                db, "anexo_iii.reviewed",
                entity_type="anexo", entity_id=anexo.id if anexo else None,
                process_id=process.id, subject=process.folio, reason=motivo,
                payload={"status": veredicto, "round": ronda},
                actor_id=reviewer_id)
            if reprint:
                anexo.ready_at = None
                anexo.ready_by_id = None
                anexo.reprint_reason = motivo
                anexo.reprint_requested_at = db_now()
                PhaseService._log(db, process.id, reviewer_id, "anexo_iii_reprint_requested",
                                  n, {"folio": anexo.folio, "reason": motivo})
                AuditService.record(
                    db, "anexo_iii.reprint_requested",
                    entity_type="anexo", entity_id=anexo.id,
                    process_id=process.id, subject=process.folio, reason=motivo,
                    payload={"folio": anexo.folio, "round": ronda},
                    actor_id=reviewer_id)
            db.flush()
            evento = {"anexo_iii": {"folio": anexo.folio if anexo else None, "round": ronda,
                                    # El correo de fase observada lo lee (`mail_compose`).
                                    **({"reprint": True} if reprint else {})}}
            PhaseService.open_door(db, PHASE_CODE, process.id, veredicto)
            if veredicto == "approved":
                return PhaseService.approve_phase(db, process, n, reviewer_id,
                                                  event_payload=evento)
            PhaseService.reject_phase(db, process, n, reviewer_id, motivo,
                                      event_payload=evento)
            return None
        except Exception:
            db.rollback()
            raise
        finally:
            PhaseService.close_door(db)

    # ------------------------------------------------------------------
    # Documento
    # ------------------------------------------------------------------
    @staticmethod
    def context(db: Session, process) -> dict:
        """Todas las piezas del Anexo (spec §7). `ValueError` sin los 4
        sinodales vigentes, sin departamento o sin modalidad/producto."""
        from itcj2.apps.titulatec.models import Modality
        from itcj2.apps.titulatec.services.synodal_service import SynodalService

        sinodales = SynodalService.active_for_process(db, process.id)
        if len(sinodales) != SYNODALS_REQUIRED:
            raise ValueError(NO_SYNODALS_MSG)
        marco = OficioService.department_frame(db, process)
        depto = marco["department"]
        if depto is None:
            raise ValueError(NO_DEPARTMENT_MSG)
        modalidad = db.get(Modality, process.modality_id) if process.modality_id else None
        producto = " ".join(str(getattr(modalidad, "product_label", None) or "").split())
        if modalidad is None or not producto:
            raise ValueError(NO_MODALITY_MSG)

        base = SynodalService._notice_base(db, process)
        anexo = AnexoService.get(db, process.id)
        liberado = anexo.released_at if anexo else AnexoService._released_at(db, process)
        egresado = (base["alumno"] or "").title()
        carrera = base["carrera"] or ""
        control = base["control"] or ""
        proyecto = (base["titulo"] or "").upper()
        return {
            "preview": False,           # `preview_pdf` lo prende (marca de agua)
            "header": marco["header"],
            "folio": anexo.folio if anexo else None,
            "date_label": _date_label(liberado),
            "addressee": marco["addressee"],
            "signer": marco["signer"],
            "student_name": egresado,
            "control_number": control,
            "program_name": carrera,
            "project_title": proyecto,
            "product_label": producto,
            "items": [
                {"letter": "a", "label": "Nombre del egresado", "value": egresado},
                {"letter": "b", "label": "Carrera", "value": carrera},
                {"letter": "c", "label": "No. de control", "value": control},
                {"letter": "d", "label": "Nombre del proyecto", "value": proyecto},
                {"letter": "e", "label": "Producto", "value": producto},
            ],
            "synodals": [{
                "role_label": s["role_label"],
                "name": (s["name"] or "").upper(),
                "academic_degree": (s["academic_degree"] or "").upper(),
                "license": s["professional_license"] or "",
            } for s in sinodales],
            "footer_address": FOOTER_ADDRESS,
            "footer_contact": FOOTER_CONTACT,
        }

    @staticmethod
    def prepare_pdf(db: Session, process, actor_id: int | None) -> dict:
        """Lo que pinta el Anexo: emite el folio si hace falta (`ensure_folio`,
        que valida ANTES de numerar) y arma `context` UNA sola vez. Sin commit.

        Toma el bloqueo del proceso (y, en la primera emision, el del contador
        del semestre): el llamador hace `commit` ENSEGUIDA y solo despues llama
        `render`, asi WeasyPrint nunca corre con esos bloqueos tomados. Devuelve
        un dict plano (se pinta despues de cerrar la sesion). `ValueError` igual
        que `ensure_folio`/`context`."""
        _anexo, ctx = AnexoService._ensure(db, process, actor_id)
        return ctx if ctx is not None else AnexoService.context(db, process)

    @staticmethod
    def render(ctx: dict) -> bytes:
        """PDF del Anexo a partir del contexto de `prepare_pdf`. No toca la BD:
        se llama fuera de la transaccion (despues del `commit` de la ruta)."""
        from weasyprint import HTML

        from itcj2.apps.titulatec.pages.nav import titulatec_templates
        from itcj2.apps.titulatec.utils.certificate_pdf import CORE_STATIC_DIR

        html = titulatec_templates.get_template(_TEMPLATE_NAME).render(**ctx)
        return HTML(string=html, base_url=str(CORE_STATIC_DIR)).write_pdf()

    @staticmethod
    def filename(db: Session, process) -> str:
        from itcj2.core.models.user import User

        alumno = db.get(User, process.student_id)
        control = (alumno.control_number if alumno and alumno.control_number
                   else f"proceso{process.id}")
        return f"{control}_ANEXO_III.pdf"

    # ------------------------------------------------------------------
    # Vista previa del alumno (E2, spec 2026-10-29 §6)
    # ------------------------------------------------------------------
    @staticmethod
    def preview_pdf(db: Session, process) -> dict:
        """Contexto de la vista previa: `context` con `preview=True` (marca de
        agua) y el folio solo si ya existe. NUNCA escribe ni toma bloqueo (sin
        `_ensure`): la fecha es la congelada o la de liberacion calculada al
        vuelo. Falla cerrado como el oficial (`ValueError`)."""
        if not AnexoService.operable(db):
            raise ValueError(NOT_OPERABLE_MSG)
        if not AnexoService.reached(db, process):
            raise ValueError(NOT_REACHED_MSG)
        ctx = AnexoService.context(db, process)
        ctx["preview"] = True
        return ctx

    @staticmethod
    def preview_filename(db: Session, process) -> str:
        return AnexoService.filename(db, process).removesuffix(".pdf") + "_VISTA_PREVIA.pdf"

    # ------------------------------------------------------------------
    # Avisos en la campana (best-effort, sesion propia, tras el commit)
    # ------------------------------------------------------------------
    RELEASE_TYPE = "ANEXO_READY"
    RELEASE_TITLE = "Prepara el Anexo III"
    RELEASE_BODY = "Prepara el Anexo III de {alumno}."
    RELEASE_URL = "/titulatec/admin/sinodales?tab=anexo&selected={process_id}"
    REPRINT_TYPE = "ANEXO_REPRINT"
    REPRINT_TITLE = "Reimprimir Anexo III"
    REPRINT_BODY = "Reimprime el Anexo III de {alumno}."
    REPRINT_URL = "/titulatec/admin/sinodales?tab=anexo&etapa=preparar&selected={process_id}"
    PICKUP_TYPE = "ANEXO_PICKUP"
    PICKUP_TITLE = "Tu Anexo III está listo para recoger"
    PICKUP_URL = "/titulatec/student/anexo"

    @staticmethod
    def _vinculacion_recipients(db: Session, process) -> list[int]:
        """Quien gestiona el Anexo en el departamento de la carrera: ocupantes
        vigentes de `coord_vinculacion_{depto}` y, si el puesto esta vacante,
        de `head_{depto}`. [] sin carrera o sin departamento."""
        from itcj2.apps.titulatec.services.scope_service import department_of_program
        from itcj2.core.models.department import Department
        from itcj2.core.models.position import Position, UserPosition
        from itcj2.core.services.authz_service import _active_position_filter

        if process is None or process.program_id is None:
            return []
        depto_id = department_of_program(db, process.program_id)
        depto = db.get(Department, depto_id) if depto_id is not None else None
        if depto is None:
            return []

        def _ocupantes(codigo: str) -> list[int]:
            filas = (db.query(UserPosition.user_id)
                     .join(Position, Position.id == UserPosition.position_id)
                     .filter(Position.code == codigo, _active_position_filter())
                     .distinct().all())
            return sorted(int(f[0]) for f in filas)

        return (_ocupantes(f"coord_vinculacion_{depto.code}")
                or _ocupantes(f"head_{depto.code}"))

    @staticmethod
    def notify_release(process_id: int) -> None:
        """Avisa en la campana a quien gestiona el Anexo en el departamento
        (`_vinculacion_recipients`). Abre su PROPIA sesion y commitea (se llama
        DESPUES del commit del voto); sin correo. Inerte si el Anexo no se opera
        o la carrera no tiene departamento. Los errores los maneja el llamador
        (best-effort)."""
        AnexoService._notify_vinculacion(process_id, AnexoService.RELEASE_TYPE,
                                         AnexoService.RELEASE_TITLE, AnexoService.RELEASE_URL,
                                         body=AnexoService.RELEASE_BODY)

    @staticmethod
    def notify_reprint(process_id: int) -> None:
        """Como `notify_release`, tras pedirse la reimpresion (E4): «Reimprimir
        Anexo III», a «Por preparar» de Sinodales. Solo si la etapa sigue en
        `reprint` (llegar tarde no avisa de algo ya resuelto)."""
        AnexoService._notify_vinculacion(process_id, AnexoService.REPRINT_TYPE,
                                         AnexoService.REPRINT_TITLE, AnexoService.REPRINT_URL,
                                         body=AnexoService.REPRINT_BODY, stage="reprint")

    @staticmethod
    def _notify_vinculacion(process_id: int, type_: str, title: str, url: str, *,
                            body: str, stage: str | None = None) -> None:
        from itcj2.apps.titulatec.models import TitulationProcess
        # El mismo nombre que pintan las vistas de Titulación (una sola función).
        from itcj2.apps.titulatec.pages._titulacion_shared import nombre as _nombre
        from itcj2.core.models.user import User
        from itcj2.core.services.notification_service import NotificationService
        from itcj2.database import SessionLocal

        db = SessionLocal()
        try:
            if not AnexoService.operable(db):
                return
            proceso = db.get(TitulationProcess, process_id)
            if stage is not None and AnexoService.stage(db, proceso) != stage:
                return
            destinatarios = AnexoService._vinculacion_recipients(db, proceso)
            if not destinatarios:
                return
            alumno = db.get(User, proceso.student_id)
            nombre = _nombre(alumno)
            control = (alumno.control_number if alumno else None) or ""
            alumno_txt = " · ".join(p for p in (nombre, control) if p) or proceso.folio
            destino = url.format(process_id=process_id)
            for uid in destinatarios:
                NotificationService.create(
                    db, user_id=uid, app_name="titulatec", type=type_,
                    title=title, body=body.format(alumno=alumno_txt),
                    data={"url": destino, "process_id": process_id})
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def notify_ready(process_id: int) -> None:
        """Campana al alumno: su Anexo esta listo para recoger (y al corregir
        la nota), con la nota vigente. Sesion propia tras el commit de
        `mark_ready`; inerte si la etapa ya no es `ready`. Best-effort: los
        errores los maneja el llamador."""
        from itcj2.apps.titulatec.models import TitulationProcess
        from itcj2.core.services.notification_service import NotificationService
        from itcj2.database import SessionLocal

        db = SessionLocal()
        try:
            proceso = db.get(TitulationProcess, process_id)
            if AnexoService.stage(db, proceso) != "ready":
                return
            NotificationService.create(
                db, user_id=proceso.student_id, app_name="titulatec",
                type=AnexoService.PICKUP_TYPE, title=AnexoService.PICKUP_TITLE,
                body=AnexoService.get(db, process_id).pickup_note,
                data={"url": AnexoService.PICKUP_URL, "process_id": process_id})
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
