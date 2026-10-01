"""Servicio del no adeudo de biblioteca: Biblioteca registra, Caja cobra.

Spec `docs/superpowers/specs/2026-10-01-titulatec-biblioteca-caja-design.md`
§4.2 (máquina de estados), D3/D4/D5/D9/D16-D19, §4.7/§4.8 (bandejas) y §5
(invariantes). Este service es el ÚNICO escritor de
`titulatec_library_clearances` y del cumplimiento del requisito de cotejo
`library_clearance` (§5, invariante 1): nadie fuera de aquí muta esa fila.

Máquina de estados (modelo `LibraryClearance`):

    (alta del proceso | backfill) ──────────────────────────────> pending
    pending ──Registrar (Biblioteca), total > 0 ────────────────> awaiting_payment
    pending ──Registrar (Biblioteca), total = 0 ────────────────> cleared/no_charge  (+constancia BIB)
    awaiting_payment ──Corregir (Biblioteca) ───────────────────> awaiting_payment (nuevo monto)
                                                                  | cleared/no_charge si total = 0
    awaiting_payment ──Registrar pago (Caja) ───────────────────> cleared/payment    (+constancia BIB)
    pending|awaiting_payment ──Constancia previa (Biblioteca, SE o importación)
                                                                ─> cleared/prior     (sin constancia nueva)
    cleared/payment ──Revertir pago (Caja, motivo) ─────────────> awaiting_payment   (anula la constancia)
    cleared/no_charge|legacy ──Revertir (Biblioteca, motivo) ───> pending            (anula la constancia si hay)
    cleared/prior ──Deshacer constancia previa (motivo) ────────> pending

Montos (D16/D18/D19): Registrar = adeudo (0 = «sin adeudo») + nota opcional.
La donación voluntaria de libro se CONGELA desde `Cohort.book_donation_amount`
(NULL → `ValueError`, D19) y `total = adeudo + donación`: un cambio posterior
de la convocatoria no mueve lo ya registrado, y Corregir vuelve a congelar con
la donación VIGENTE. «Sin adeudo» es adeudo 0, no total 0: con donación el
egresado igual pasa a Caja; total 0 libera sin pasar por Caja (D18). Al volver
a `pending` (Revertir sin cargo/legado, Deshacer previa) la fila regresa a la
forma de recién abierta —sin montos ni datos de Biblioteca, Caja o constancia
previa; lo anterior queda en el payload del evento— salvo `ready_at`, que
queda como historia hasta la siguiente entrada a Caja. Una constancia previa
registrada desde `awaiting_payment` conserva los montos como historia.

Ruling R10 (revisión de la Tarea 4): `ready_at` es la entrada VIGENTE a Caja —
ancla del recordatorio de pago y FIFO de «Por cobrar»—: se vuelve a fijar CADA
vez que la fila ENTRA a `awaiting_payment` desde otro estado (Registrar desde
`pending`, Revertir pago desde `cleared/payment`), nunca al corregir dentro de
`awaiting_payment`. Y una corrección que no cambia nada (mismo adeudo, misma
donación congelada, misma nota) es no-op: sin evento, sin aviso, sin correo y
sin firma nueva de Biblioteca.

Requisito `library_clearance`: quedar `cleared` → `RequirementService.fulfill`
(source='system', external_ref='library_clearance:{id}'); salir de `cleared`
→ `unfulfill`. Si la convocatoria NO tiene el requisito automático ACTIVO
(`auto_source='library_clearance'`), no hay cumplimiento que escribir y la
transición sigue igual: es una convocatoria sin candado de biblioteca (§4.4).

Constancias (§4.5): quedar `cleared` por `payment`/`no_charge` emite
`CertificateService.issue(kind='library_clearance',
source_ref='library_clearance:{id}')`; revertir anula (`void`). `prior` y
`legacy` no emiten. «A lo más una vigente por origen» (§5, invariante 5) se
cumple por construcción: solo se emite al ENTRAR a cleared/payment|no_charge y
toda salida de esos dos estados anula; volver a liberar saca un folio nuevo.

Reglas fijas (patrón `SurveyReviewService`):

* `@staticmethod`, `db: Session` primero; imports de modelos y de otros
  services LOCALES, dentro de cada método (ciclos).
* `ValueError` = regla de negocio, con el mensaje YA listo para el usuario;
  `LookupError` = el id no existe (la ruta lo traduce a 404).
* Proceso admitido: `active` u `on_hold` (convocatoria en pausa: Biblioteca y
  Caja sí operan); `cancelled`/`completed` → `ValueError`.
* Ya pasó su cotejo (Rulings R20/R21 de la revisión final): con la fase 2
  `approved` y el no adeudo SIN liberar, `release_status`/`summary_for_process`
  dicen `NOT_APPLICABLE` (el candado no lo cuenta y el egresado no ve «en
  Biblioteca»), Registrar, el lote y la constancia previa responden
  `ValueError` y «Por revisar» no lo muestra. Caja sí puede cobrar un monto
  que Biblioteca ya mandó (`register_payment` no cambia).
* Toda transición: `SELECT … FOR UPDATE` de la fila CON `populate_existing()`
  —tras esperar el lock se relee lo que la otra transacción ya commiteó,
  aunque esta sesión guarde la foto vieja en su mapa de identidad—; TODA la
  validación antes de mutar; `ProcessEvent` en la fase 2; aviso in-app en la
  misma transacción; UN commit (ninguno con `register_prior(commit=False)`).
* Dos personas sobre la misma fila (Review Focus #1): la segunda ve el estado
  nuevo y recibe un `ValueError` claro. Para que el segundo de Biblioteca no
  CORRIJA sin querer lo que otro acaba de registrar, ni Caja cobre un monto
  distinto del que confirmó, las rutas pasan lo que el usuario vio:
  `register(expected_status=, expected_total=)` y
  `register_payment(expected_total=)` (opcionales; `None` = sin esa guarda).
  `expected_total` se valida con `_check_total_shape` (finito y >= 0), NUNCA
  con el tope `AMOUNT_MAX` (Ruling R9, spec §4.8): ese tope topa lo que SE
  TECLEA (`debt_amount`), y un adeudo al tope más la donación lo supera sin
  dejar de ser un total legítimo.
* Correos (spec §4.11, §5 invariante 9): cada transición encola su correo
  de `StudentMail` junto a su aviso in-app, antes de su único commit (la
  fila nace en la MISMA transacción; si el commit falla, se va con él):
  pasa a Caja o se corrige el monto → `library_ready`; queda liberado (sin
  cargo, pago o constancia previa) → `library_cleared`; se revierte o
  deshace → `library_reverted`. El recordatorio del pago pendiente lo encola
  el barrido diario (`MailReminders`). `test_mail_writers.py` fija evento →
  correo por AST.
* `updated_at` no tiene `onupdate` (ver el modelo): se fija a mano.
"""
from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import case, func, or_
from sqlalchemy.orm import Session

from itcj2.core.utils.timezone import db_now

# Vigencia de una constancia previa (D9): `issued_on >= hoy - 365 días`.
PRIOR_VALIDITY_DAYS = 365

# Tope de cualquier monto tecleado (adeudo, donación): $100,000.00.
AMOUNT_MAX = Decimal("100000.00")

# Motivo de Revertir/Deshacer (obligatorio) y notas (opcionales): 1..1000.
REASON_MAX = 1000

# `LibraryClearance.receipt_number` es String(40).
RECEIPT_MAX = 40

# `CotejoRequirement.auto_source` del requisito que acredita este service.
AUTO_SOURCE_LIBRARY = "library_clearance"

# La cita de cotejo es la fase 2 del catálogo: todo evento de esta solicitud
# se cuelga de ella (mismo valor que `RequirementService.PHASE_COTEJO`).
PHASE_COTEJO = 2

# Procesos sobre los que Biblioteca y Caja pueden operar (spec §4.2).
ADMITTED_PROCESS_STATUSES = ("active", "on_hold")

# Pseudo-estado de la liberación (Ruling R21, I3 de la revisión final): el
# proceso YA pasó su cotejo -su fase 2 está `approved`- sin un no adeudo
# liberado. El backfill de `tt20261001a` salta a propósito esos procesos (D17:
# una fase 2 ya liberada no se toca), así que pueden no tener fila, o tener
# una que nunca llegó a `cleared`. Como `missing`, NO se guarda: lo infieren
# `release_status[_map]` y `summary_for_process`. `ClearanceGate` lo trata
# igual que `not_required` (no bloquea) y las vistas del egresado no lo pintan.
NOT_APPLICABLE = "not_applicable"

# Ruling R20 (I2): a quien ya pasó su cotejo no se le abre trámite de no
# adeudo (Registrar, lote «Sin adeudo», constancia previa).
_MSG_COTEJO_YA_LIBERADO = ("Este egresado ya pasó su cotejo; no necesita trámite de "
                           "no adeudo.")

# Quién registra una constancia previa: va al payload del evento.
PRIOR_BY = ("library", "school_services", "import")

# Los 8 `ProcessEvent` que escribe este service (fase 2, <= 40 caracteres).
# Fijado contra los `_log(...)` reales por `test_library_clearance_service.py`.
LIBRARY_EVENT_TYPES = (
    "library_debt_registered",
    "library_no_charge",
    "library_amount_corrected",
    "library_payment_registered",
    "library_prior_registered",
    "library_payment_reverted",
    "library_clearance_reverted",
    "library_prior_undone",
)

# Tipo de constancia que emite este service (`CERT_KINDS` de certificate_service).
CERT_KIND = "library_clearance"

# Nombre de cada estado en las pestañas (mensajes de concurrencia).
_STATUS_LABELS = {
    "pending": "Por revisar",
    "awaiting_payment": "En caja",
    "cleared": "Liberado",
}

_CENT = Decimal("0.01")

# Pesos: «800», «800.5», «1,200.50» (comas de miles bien agrupadas). Solo
# dígitos ASCII: `\d` aceptaría dígitos de otros alfabetos.
_AMOUNT_RE = re.compile(r"(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.([0-9]+))?")

_MSG_AMOUNT_FORMAT = "Monto no válido: escríbelo en pesos, por ejemplo 1,200.50."


# ---------------------------------------------------------------------------
# Dinero
# ---------------------------------------------------------------------------
def parse_amount(raw: str | None) -> Decimal:
    """Monto tecleado en un formulario → `Decimal` a centavos.

    Acepta «800», «800.5», «1,200.50», «$1,200» y «$ 1,200.50» (espacios
    alrededor). `ValueError` legible —sin escribir nada— si viene vacío, es
    negativo, trae más de 2 decimales, notación científica o cualquier otra
    cosa que no sean pesos, o pasa de `AMOUNT_MAX` (Review Focus #3). Nunca
    `float`.
    """
    texto = ("" if raw is None else str(raw)).strip()
    if not texto:
        raise ValueError("Escribe el monto.")
    negativo = False
    if texto.startswith("-"):
        negativo, texto = True, texto[1:].lstrip()
    if texto.startswith("$"):
        texto = texto[1:].lstrip()
    if texto.startswith("-"):
        negativo, texto = True, texto[1:].lstrip()
    if negativo:
        raise ValueError("El monto no puede ser negativo.")
    coincide = _AMOUNT_RE.fullmatch(texto)
    if coincide is None:
        raise ValueError(_MSG_AMOUNT_FORMAT)
    if coincide.group(1) is not None and len(coincide.group(1)) > 2:
        raise ValueError("El monto admite a lo más 2 decimales.")
    return _check_amount(Decimal(texto.replace(",", "")))


def format_amount(value) -> str:
    """«$1,200.00» (cadena vacía para `None`)."""
    if value is None:
        return ""
    return f"${Decimal(value):,.2f}"


def _check_amount(value) -> Decimal:
    """Monto ya numérico (`Decimal` o `int`, nunca `float`/`bool`/texto) →
    `Decimal` a centavos, o `ValueError` legible."""
    if isinstance(value, bool) or not isinstance(value, (Decimal, int)):
        raise ValueError(_MSG_AMOUNT_FORMAT)
    monto = Decimal(value)
    if not monto.is_finite():
        raise ValueError(_MSG_AMOUNT_FORMAT)
    if monto < 0:
        raise ValueError("El monto no puede ser negativo.")
    if monto > AMOUNT_MAX:
        raise ValueError(f"El monto no puede pasar de {format_amount(AMOUNT_MAX)}.")
    if monto != monto.quantize(_CENT):
        raise ValueError("El monto admite a lo más 2 decimales.")
    if monto == 0:
        monto = Decimal(0)          # sin «-0.00»
    return monto.quantize(_CENT)


def _txt(value) -> str | None:
    """Monto para el payload JSON de un evento («1200.00»): JSON no serializa
    `Decimal`."""
    return None if value is None else f"{Decimal(value):.2f}"


def _ref(clearance_id: int) -> str:
    """Origen de la constancia y `external_ref` del cumplimiento."""
    return f"library_clearance:{clearance_id}"


class LibraryClearanceService:
    """Único dueño de `titulatec_library_clearances` y del requisito
    `library_clearance`."""

    # ----------------------------------------------------------------- bitácora
    @staticmethod
    def _log(db: Session, process_id: int, actor_id: int | None,
             event_type: str, payload: dict | None = None) -> None:
        """Escribe un `ProcessEvent` en la fase 2. No commitea (gemelo de
        `SurveyReviewService._log`)."""
        from itcj2.apps.titulatec.models import ProcessEvent
        db.add(ProcessEvent(
            process_id=process_id, actor_id=actor_id, event_type=event_type,
            phase_number=PHASE_COTEJO, payload=payload,
        ))

    # ------------------------------------------------------------------ lectura
    @staticmethod
    def get_for_process(db: Session, process_id: int):
        """La fila de ese proceso, o `None` si todavía no tiene."""
        from itcj2.apps.titulatec.models import LibraryClearance
        return db.query(LibraryClearance).filter_by(process_id=process_id).first()

    @staticmethod
    def open_for_process(db: Session, process, *, just_created: bool = False):
        """La fila `pending` del proceso, creándola si falta. Idempotente, sin
        commit (transacción del llamador).

        `just_created=True` es SOLO para `ImportService.import_rows`, con un
        proceso que acaba de insertar en esta misma transacción: no puede tener
        fila, así que va directo al INSERT sin SELECT previo (un SELECT por
        alumno es costo puro en un lote de 400; `test_import_scale.py`). Hace
        `flush()` para que el llamador tenga ya el `id` —con `autoflush=False`
        (el `SessionLocal` real) otra búsqueda en la misma transacción no vería
        la fila pendiente e intentaría crear una segunda—; ese INSERT ocurriría
        de todos modos en el siguiente flush del importador.

        La variante idempotente inserta con `ON CONFLICT DO NOTHING`: dos
        llamadores a la vez sobre el mismo proceso nunca chocan con el UNIQUE.
        """
        from itcj2.apps.titulatec.models import LibraryClearance

        if just_created:
            row = LibraryClearance(process_id=process.id, status="pending")
            db.add(row)
            db.flush()
            return row

        row = LibraryClearanceService.get_for_process(db, process.id)
        if row is None:
            LibraryClearanceService._insert_if_missing(db, process.id)
            row = LibraryClearanceService.get_for_process(db, process.id)
        return row

    @staticmethod
    def release_status(db: Session, process_id: int) -> str:
        """Estado de liberación del no adeudo para el candado de agendar
        (`ClearanceGate`): `'cleared'` si la fila está liberada; si no, y la
        fase 2 del proceso YA está `approved`, `NOT_APPLICABLE` (Ruling R21:
        ya pasó su cotejo); si no, su `status` real (`pending` |
        `awaiting_payment`) o `'missing'` sin fila. Fuente ÚNICA de esa
        lectura: nadie más compara `LibraryClearance.status`. Es
        `release_status_map` con un solo id: imposible que diverjan."""
        return LibraryClearanceService.release_status_map(
            db, [process_id]).get(process_id, "missing")

    @staticmethod
    def prior_outcome(db: Session, process_id: int) -> str:
        """Clasifica, SOLO LECTURA, qué le tocaría a una constancia previa de
        biblioteca sobre este proceso (D9, spec §4.12): `"apply"` (sin fila
        todavía, o `pending`/`awaiting_payment`: `register_prior` la
        liberaría) o `"already"` (`cleared`: nada que aplicar).

        Distinta a propósito de `release_status` -esa es SOLO para
        `ClearanceGate` y la guarda de agendar (§4.4)-: esta es la ÚNICA
        lectura de `LibraryClearance.status` permitida para la clasificación
        de constancias previas fuera de este service. `PriorClearanceService`
        llama aquí en vez de comparar `.status` por su cuenta (§5, invariante
        2). Gemela de `SurveyReviewService.prior_outcome` (sin el bote
        `"conflict"`: biblioteca no tiene un estado "en revisión por alguien
        más" que requiera que lo decida un humano)."""
        row = LibraryClearanceService.get_for_process(db, process_id)
        if row is None or row.status in ("pending", "awaiting_payment"):
            return "apply"
        return "already"

    @staticmethod
    def payment_due(db: Session, process_id: int) -> dict | None:
        """Lo que el egresado debe pagar en Caja AHORA, SOLO LECTURA:
        `{"debt", "donation", "total", "note", "ready_at"}` —los montos
        CONGELADOS de su fila (`Decimal`), la nota de Biblioteca y su entrada
        vigente a Caja— si su no adeudo está `awaiting_payment`; `None` en
        cualquier otro estado o sin fila.

        Para los correos del pago (spec §4.11): `library_ready`,
        `library_reminder` y la reversión de un pago se re-validan con esto al
        enviar y pintan los montos VIGENTES. Lee la FILA y no el candado a
        propósito: lo que Biblioteca mandó a Caja se debe aunque la
        convocatoria no exija el no adeudo para agendar. No contesta «¿le
        faltan liberaciones?» —eso es SOLO de `ClearanceGate` (invariante 2)—:
        como `prior_outcome`, deja la comparación de `status` en el dueño."""
        row = LibraryClearanceService.get_for_process(db, process_id)
        if row is None or row.status != "awaiting_payment":
            return None
        return {"debt": row.debt_amount, "donation": row.donation_amount,
                "total": row.total_amount, "note": row.library_note,
                "ready_at": row.ready_at}

    @staticmethod
    def awaiting_payment_clause():
        """`payment_due` en SQL, sobre `LibraryClearance` (la consulta que lo
        use debe tenerla en su FROM): el no adeudo está en Caja. Para los
        candidatos del recordatorio de pago (`MailReminders`), que así no
        compara `LibraryClearance.status` por su cuenta."""
        from itcj2.apps.titulatec.models import LibraryClearance
        return LibraryClearance.status == "awaiting_payment"

    @staticmethod
    def release_status_map(db: Session, process_ids: list[int]) -> dict[int, str]:
        """`release_status` de varios procesos EN UNA consulta (filas de la
        cola): el proceso con su fila de no adeudo y su fase 2, los dos por
        `OUTER JOIN`. Un id sin proceso sale `'missing'` (falla cerrado,
        igual que sin fila)."""
        from sqlalchemy import and_

        from itcj2.apps.titulatec.models import (
            LibraryClearance, ProcessPhase, TitulationProcess,
        )

        if not process_ids:
            return {}
        filas = (db.query(TitulationProcess.id, LibraryClearance.status,
                          ProcessPhase.status)
                 .outerjoin(LibraryClearance,
                            LibraryClearance.process_id == TitulationProcess.id)
                 .outerjoin(ProcessPhase,
                            and_(ProcessPhase.process_id == TitulationProcess.id,
                                 ProcessPhase.phase_number == PHASE_COTEJO))
                 .filter(TitulationProcess.id.in_(process_ids))
                 .all())
        out = {pid: "missing" for pid in process_ids}
        for pid, estado, fase2 in filas:
            out[pid] = LibraryClearanceService._release_of(estado, fase2)
        return out

    @staticmethod
    def _release_of(estado: str | None, fase2: str | None) -> str:
        """Una fila (`estado`, `None` sin fila) y el estado de su fase 2 ->
        el valor de `release_status`. Liberada gana siempre; si no, la fase
        2 aprobada la vuelve `NOT_APPLICABLE` (Ruling R21)."""
        if estado == "cleared":
            return "cleared"
        if fase2 == "approved":
            return NOT_APPLICABLE
        return estado or "missing"

    @staticmethod
    def summary_for_process(db: Session, process_id: int) -> dict:
        """Foto plana del no adeudo para el panel de atender, el expediente y
        el egresado. SOLO lectura: nunca commitea ni abre la fila.

        Llaves: `status` (`'missing'` = pseudo-estado sin fila;
        `NOT_APPLICABLE` = ya pasó su cotejo sin un no adeudo liberado, Ruling
        R21 -mismo criterio que `release_status`-), `via`, `debt`,
        `donation`, `total` (`Decimal` | None), `note` (la de Biblioteca),
        `ready_at`, `paid_at`, `receipt`, `certificate_number` (la constancia
        VIGENTE, nunca una anulada), `prior_issued_on`, `prior_note`,
        `can_revert`, `clearance_id`. Formatear es de quien pinta
        (`format_amount`). Con `NOT_APPLICABLE` las vistas del egresado no
        pintan nada y las de SE dicen «No aplica (cotejo ya liberado)» sin
        ofrecer «Constancia previa…».
        """
        from itcj2.apps.titulatec.models import Certificate

        row = LibraryClearanceService.get_for_process(db, process_id)
        no_aplica = ((row is None or row.status != "cleared")
                     and LibraryClearanceService._phase2_approved(db, process_id))
        if row is None:
            return {"status": NOT_APPLICABLE if no_aplica else "missing",
                    "via": None, "debt": None, "donation": None,
                    "total": None, "note": None, "ready_at": None, "paid_at": None,
                    "receipt": None, "certificate_number": None,
                    "prior_issued_on": None, "prior_note": None,
                    "can_revert": False, "clearance_id": None}

        vigente = (db.query(Certificate.number)
                   .filter(Certificate.source_ref == _ref(row.id),
                           Certificate.voided_at.is_(None))
                   .order_by(Certificate.id.desc())
                   .first())
        return {
            "status": NOT_APPLICABLE if no_aplica else row.status,
            "via": row.cleared_via,
            "debt": row.debt_amount,
            "donation": row.donation_amount,
            "total": row.total_amount,
            "note": row.library_note,
            "ready_at": row.ready_at,
            "paid_at": row.paid_at,
            "receipt": row.receipt_number,
            "certificate_number": vigente[0] if vigente else None,
            "prior_issued_on": row.prior_issued_on,
            "prior_note": row.prior_note,
            "can_revert": LibraryClearanceService.can_revert(db, row),
            "clearance_id": row.id,
        }

    @staticmethod
    def can_revert(db: Session, clearance) -> bool:
        """¿Se puede revertir (o deshacer) esta liberación ahora mismo?

        Gemelo de `SurveyReviewService.can_revoke` (§4.2, §5 invariante 7): la
        fila está `cleared`, su proceso sigue admitido (`active`/`on_hold`) y
        la fase 2 todavía no está `approved`. Qué transición aplica la decide
        `cleared_via` (pago → `revert_payment`; sin cargo/legado →
        `revert_clearance`; previa → `undo_prior`).
        """
        from itcj2.apps.titulatec.models import TitulationProcess

        if clearance is None or clearance.status != "cleared":
            return False
        process = db.get(TitulationProcess, clearance.process_id)
        if process is None or process.status not in ADMITTED_PROCESS_STATUSES:
            return False
        return not LibraryClearanceService._phase2_approved(db, process.id)

    # ------------------------------------------------------------- transiciones
    @staticmethod
    def register(db: Session, clearance_id: int, actor_id: int, *,
                 debt_amount: Decimal, note: str | None = None,
                 expected_status: str | None = None,
                 expected_total: Decimal | None = None):
        """Registrar (Biblioteca) desde `pending`, o Corregir desde
        `awaiting_payment`: adeudo (0 = «sin adeudo») + nota opcional.

        Congela la donación VIGENTE de la convocatoria. Total > 0 →
        `awaiting_payment` (`library_debt_registered` o, al corregir,
        `library_amount_corrected`); total 0 → `cleared/no_charge` con
        constancia BIB y requisito cumplido (`library_no_charge`). Corregir sin
        cambiar nada es no-op (Ruling R10): la fila queda como estaba.

        `expected_status` / `expected_total`: lo que el usuario tenía en
        pantalla. Si la fila ya no está así (otra persona la movió mientras
        tanto), `ValueError` en vez de pisar su trabajo.

        Ruling R20 (I2): un proceso con la fase 2 ya `approved` (ya pasó su
        cotejo) no abre trámite: `ValueError`, sin escribir nada.
        """
        clearance = LibraryClearanceService._locked(db, clearance_id)
        plan = LibraryClearanceService._prepare_registration(
            db, clearance, debt_amount=debt_amount, note=note,
            expected_status=expected_status, expected_total=expected_total)
        requirement = (
            LibraryClearanceService._library_requirement(db, plan["process"].cohort_id)
            if plan["total"] == 0 else None)

        LibraryClearanceService._apply_registration(db, clearance, plan, actor_id, requirement)
        db.commit()
        return clearance

    @staticmethod
    def register_no_debt_bulk(db: Session, clearance_ids, actor_id: int) -> dict:
        """Lote «Sin adeudo» (D10): Registrar con adeudo 0 cada id marcado en
        «Por revisar», en UNA transacción con UN commit.

        Valida TODAS las filas antes de mutar ninguna. Las que no pasan (ya no
        están `pending`, convocatoria sin donación, proceso revocado o
        terminado, fase 2 ya aprobada -Ruling R20-, id inexistente) se omiten
        con su motivo, en el orden recibido; los ids repetidos cuentan una
        vez. Devuelve `{"done": int, "skipped": [(clearance_id, motivo),
        ...]}`.
        """
        from itcj2.apps.titulatec.models import LibraryClearance, TitulationProcess

        ids = list(dict.fromkeys(int(cid) for cid in clearance_ids))
        if not ids:
            return {"done": 0, "skipped": []}

        filas = (db.query(LibraryClearance)
                 .filter(LibraryClearance.id.in_(ids))
                 .order_by(LibraryClearance.id)     # orden fijo de locks: sin deadlocks
                 .populate_existing()
                 .with_for_update()
                 .all())
        por_id = {fila.id: fila for fila in filas}
        # Los procesos en UNA consulta: el `db.get` de `_admitted_process` los
        # toma luego del mapa de identidad en vez de pedir uno por fila. Y las
        # fases 2 aprobadas en OTRA (Ruling R20), no una por fila.
        aprobadas: set[int] = set()
        if filas:
            pids = {fila.process_id for fila in filas}
            (db.query(TitulationProcess)
             .filter(TitulationProcess.id.in_(pids))
             .all())
            aprobadas = LibraryClearanceService._phase2_approved_ids(db, pids)

        planes, omitidos = [], []
        for cid in ids:
            clearance = por_id.get(cid)
            if clearance is None:
                omitidos.append((cid, f"No existe el registro de no adeudo {cid}."))
                continue
            try:
                plan = LibraryClearanceService._prepare_registration(
                    db, clearance, debt_amount=Decimal("0"), note=None,
                    expected_status="pending",
                    phase2_approved=clearance.process_id in aprobadas)
            except ValueError as exc:
                omitidos.append((cid, str(exc)))
                continue
            planes.append((clearance, plan))

        requisitos: dict[int, object] = {}
        for _, plan in planes:
            cohort_id = plan["process"].cohort_id
            if plan["total"] == 0 and cohort_id not in requisitos:
                requisitos[cohort_id] = LibraryClearanceService._library_requirement(
                    db, cohort_id)

        for clearance, plan in planes:
            LibraryClearanceService._apply_registration(
                db, clearance, plan, actor_id,
                requisitos.get(plan["process"].cohort_id))
        db.commit()
        return {"done": len(planes), "skipped": omitidos}

    @staticmethod
    def register_payment(db: Session, clearance_id: int, actor_id: int, *,
                         receipt_number: str | None = None,
                         expected_total: Decimal | None = None):
        """Registrar pago (Caja): `awaiting_payment` → `cleared/payment`.

        Cobra el monto CONGELADO de la fila (adeudo + donación); número de
        recibo opcional (<= 40). Cumple el requisito, emite la constancia BIB y
        escribe `library_payment_registered`. `expected_total` = el total que
        Caja confirmó («Registrar pago de $X»): si Biblioteca lo corrigió
        entretanto, `ValueError` para volver a confirmar.
        """
        clearance = LibraryClearanceService._locked(db, clearance_id)
        process = LibraryClearanceService._admitted_process(db, clearance)
        if clearance.status == "pending":
            raise ValueError("Biblioteca todavía no registra el monto de este egresado; "
                             "aún no hay nada que cobrar.")
        if clearance.status == "cleared":
            if clearance.cleared_via == "payment":
                raise ValueError("Este pago ya está registrado.")
            raise ValueError("Este no adeudo ya está liberado; no hay nada que cobrar.")
        if clearance.status != "awaiting_payment":
            raise ValueError(f"Este caso no está por cobrar (estado: {clearance.status}).")
        LibraryClearanceService._check_expected(clearance, expected_total=expected_total)
        recibo = LibraryClearanceService._clean_receipt(receipt_number)
        requirement = LibraryClearanceService._library_requirement(db, process.cohort_id)

        ahora = db_now()
        clearance.status = "cleared"
        clearance.cleared_via = "payment"
        clearance.paid_by_id = actor_id
        clearance.paid_at = ahora
        clearance.receipt_number = recibo
        clearance.updated_at = ahora

        LibraryClearanceService._fulfill(db, process, clearance, requirement, actor_id)
        from itcj2.apps.titulatec.services.certificate_service import CertificateService
        cert = CertificateService.issue(db, kind=CERT_KIND, process=process,
                                        source_ref=_ref(clearance.id), actor_id=actor_id)
        datos = {"clearance_id": clearance.id, "total": _txt(clearance.total_amount),
                 "receipt": recibo, "certificate": cert.number}
        LibraryClearanceService._log(db, process.id, actor_id,
                                     "library_payment_registered", datos)

        from itcj2.apps.titulatec.services.notify import notify_student
        notify_student(db, process.student_id, type="LIBRARY_CLEARED",
                       title="Tu no adeudo de biblioteca quedó liberado",
                       body=f"Caja registró tu pago de {format_amount(clearance.total_amount)}.",
                       process_id=process.id, phase_number=PHASE_COTEJO)
        from itcj2.apps.titulatec.services.student_mail import StudentMail
        StudentMail.library_cleared(db, process, via="payment")

        db.commit()
        return clearance

    @staticmethod
    def register_prior(db: Session, clearance_id: int, actor_id: int | None, *,
                       issued_on: date, note: str | None = None, by: str,
                       commit: bool = True):
        """Constancia previa (D9): `pending|awaiting_payment` → `cleared/prior`.

        El egresado ya pagó y trae su papel: `issued_on` obligatoria, no
        futura y vigente (`>= hoy - PRIOR_VALIDITY_DAYS`: exactamente 365 días
        vale, 366 no). NO emite constancia BIB. `by` ∈ `PRIOR_BY` va al
        payload. `commit=False` (con `actor_id=None`) lo usa
        `PriorClearanceService.apply_pending` dentro de
        `ImportService.import_rows`: hace `flush()` y deja el commit al
        llamador. Ruling R20 (I2): con la fase 2 ya `approved` -ya pasó su
        cotejo- `ValueError`; ni la importación ni el alta llegan aquí con un
        proceso así (los dos solo aplican sobre procesos abiertos).
        """
        clearance = LibraryClearanceService._locked(db, clearance_id)
        process = LibraryClearanceService._admitted_process(db, clearance)
        if clearance.status not in ("pending", "awaiting_payment"):
            raise ValueError("Este no adeudo ya está liberado.")
        LibraryClearanceService._assert_needs_clearance(db, process)
        if by not in PRIOR_BY:
            raise ValueError(f"Origen de constancia previa desconocido: {by!r}.")
        fecha = LibraryClearanceService._check_prior_date(issued_on)
        nota = LibraryClearanceService._clean_note(note)
        requirement = LibraryClearanceService._library_requirement(db, process.cohort_id)

        desde = clearance.status
        clearance.status = "cleared"
        clearance.cleared_via = "prior"
        clearance.prior_issued_on = fecha
        clearance.prior_note = nota
        clearance.prior_by_id = actor_id
        clearance.updated_at = db_now()

        LibraryClearanceService._fulfill(db, process, clearance, requirement, actor_id)
        datos = {"clearance_id": clearance.id, "issued_on": fecha.isoformat(),
                 "note": nota, "by": by, "from_status": desde}
        LibraryClearanceService._log(db, process.id, actor_id,
                                     "library_prior_registered", datos)

        from itcj2.apps.titulatec.services.notify import notify_student
        notify_student(db, process.student_id, type="LIBRARY_CLEARED",
                       title="Tu no adeudo de biblioteca quedó liberado",
                       body="Se registró tu constancia de no adeudo previa; llévala "
                            "a tu cita de cotejo.",
                       process_id=process.id, phase_number=PHASE_COTEJO)
        # «Lleva tu constancia física a tu cotejo». También desde la importación
        # (`commit=False`): queda en la transacción del lote del llamador.
        from itcj2.apps.titulatec.services.student_mail import StudentMail
        StudentMail.library_cleared(db, process, via="prior")

        if commit:
            db.commit()
        else:
            db.flush()
        return clearance

    @staticmethod
    def revert_payment(db: Session, clearance_id: int, actor_id: int, reason: str):
        """Revertir pago (Caja, motivo): `cleared/payment` → `awaiting_payment`.

        Solo con la fase 2 sin aprobar (`can_revert`). El monto congelado se
        queda (sigue debiéndolo); se borran pago y recibo —salen del corte del
        día—, se descumple el requisito y se anula la constancia. Es una
        entrada NUEVA a Caja: `ready_at` se vuelve a fijar (Ruling R10).
        """
        clearance = LibraryClearanceService._locked(db, clearance_id)
        process = LibraryClearanceService._admitted_process(db, clearance)
        if clearance.status != "cleared" or clearance.cleared_via != "payment":
            raise ValueError("Solo se puede revertir un pago registrado.")
        LibraryClearanceService._assert_phase2_open(db, process)
        motivo = LibraryClearanceService._clean_reason(reason)
        requirement = LibraryClearanceService._library_requirement(db, process.cohort_id)

        previo = {"receipt": clearance.receipt_number,
                  "paid_at": clearance.paid_at.isoformat() if clearance.paid_at else None,
                  "total": _txt(clearance.total_amount)}
        ahora = db_now()
        clearance.status = "awaiting_payment"
        clearance.cleared_via = None
        clearance.paid_by_id = None
        clearance.paid_at = None
        clearance.receipt_number = None
        clearance.ready_at = ahora          # vuelve a entrar a Caja (Ruling R10)
        clearance.updated_at = ahora

        LibraryClearanceService._unfulfill(db, process, requirement, actor_id)
        from itcj2.apps.titulatec.services.certificate_service import CertificateService
        cert = CertificateService.void(db, source_ref=_ref(clearance.id),
                                       actor_id=actor_id, reason=motivo)
        datos = {"clearance_id": clearance.id, "reason": motivo, **previo,
                 "certificate": cert.number if cert is not None else None}
        LibraryClearanceService._log(db, process.id, actor_id,
                                     "library_payment_reverted", datos)

        LibraryClearanceService._notify_reverted(db, process, motivo)
        from itcj2.apps.titulatec.services.student_mail import StudentMail
        StudentMail.library_reverted(db, process, reason=motivo,
                                     to_status="awaiting_payment")

        db.commit()
        return clearance

    @staticmethod
    def revert_clearance(db: Session, clearance_id: int, actor_id: int, reason: str):
        """Revertir (Biblioteca, motivo): `cleared/no_charge|legacy` → `pending`.

        Solo con la fase 2 sin aprobar. Descumple el requisito (también el que
        un encargado marcó a mano en el legado) y anula la constancia si la
        hubo (el legado nunca tuvo). Un pago lo revierte Caja
        (`revert_payment`); una previa se deshace (`undo_prior`).
        """
        clearance = LibraryClearanceService._locked(db, clearance_id)
        process = LibraryClearanceService._admitted_process(db, clearance)
        if clearance.status != "cleared":
            raise ValueError("Este no adeudo no está liberado; no hay nada que revertir.")
        if clearance.cleared_via == "payment":
            raise ValueError("Este no adeudo se liberó con un pago; el pago lo revierte Caja.")
        if clearance.cleared_via == "prior":
            raise ValueError("Este no adeudo se liberó con una constancia previa; "
                             "usa «Deshacer constancia previa».")
        if clearance.cleared_via not in ("no_charge", "legacy"):
            raise ValueError("Esta liberación no se puede revertir desde Biblioteca.")
        LibraryClearanceService._assert_phase2_open(db, process)
        motivo = LibraryClearanceService._clean_reason(reason)
        requirement = LibraryClearanceService._library_requirement(db, process.cohort_id)

        previo = LibraryClearanceService._snapshot(clearance)
        LibraryClearanceService._reset_to_pending(clearance)

        LibraryClearanceService._unfulfill(db, process, requirement, actor_id)
        from itcj2.apps.titulatec.services.certificate_service import CertificateService
        cert = CertificateService.void(db, source_ref=_ref(clearance.id),
                                       actor_id=actor_id, reason=motivo)
        datos = {"clearance_id": clearance.id, "reason": motivo, **previo,
                 "certificate": cert.number if cert is not None else None}
        LibraryClearanceService._log(db, process.id, actor_id,
                                     "library_clearance_reverted", datos)

        LibraryClearanceService._notify_reverted(db, process, motivo)
        from itcj2.apps.titulatec.services.student_mail import StudentMail
        StudentMail.library_reverted(db, process, reason=motivo, to_status="pending")

        db.commit()
        return clearance

    @staticmethod
    def undo_prior(db: Session, clearance_id: int, actor_id: int, reason: str):
        """Deshacer constancia previa (Biblioteca o SE, motivo):
        `cleared/prior` → `pending`. Solo con la fase 2 sin aprobar;
        descumple el requisito (la previa no emitió constancia que anular)."""
        clearance = LibraryClearanceService._locked(db, clearance_id)
        process = LibraryClearanceService._admitted_process(db, clearance)
        if clearance.status != "cleared" or clearance.cleared_via != "prior":
            raise ValueError("Solo se puede deshacer una constancia previa registrada.")
        LibraryClearanceService._assert_phase2_open(db, process)
        motivo = LibraryClearanceService._clean_reason(reason)
        requirement = LibraryClearanceService._library_requirement(db, process.cohort_id)

        previo = LibraryClearanceService._snapshot(clearance)
        LibraryClearanceService._reset_to_pending(clearance)

        LibraryClearanceService._unfulfill(db, process, requirement, actor_id)
        datos = {"clearance_id": clearance.id, "reason": motivo, **previo}
        LibraryClearanceService._log(db, process.id, actor_id,
                                     "library_prior_undone", datos)

        LibraryClearanceService._notify_reverted(db, process, motivo)
        from itcj2.apps.titulatec.services.student_mail import StudentMail
        StudentMail.library_reverted(db, process, reason=motivo, to_status="pending")

        db.commit()
        return clearance

    @staticmethod
    def for_process_locked(db: Session, process_id: int):
        """La fila del proceso, bloqueada (`FOR UPDATE`), para las rutas de SE
        que van por `{process_id}` (respaldo D9, §4.9). Si el proceso no tiene
        fila (alta durante el blue/green), la abre `pending` antes de
        bloquearla. `LookupError` si el proceso no existe. Sin commit."""
        from itcj2.apps.titulatec.models import TitulationProcess

        if db.get(TitulationProcess, process_id) is None:
            raise LookupError(f"No existe el proceso {process_id}.")
        row = LibraryClearanceService._locked_by_process(db, process_id)
        if row is None:
            LibraryClearanceService._insert_if_missing(db, process_id)
            row = LibraryClearanceService._locked_by_process(db, process_id)
        return row

    # ------------------------------------------------------------------ listas
    @staticmethod
    def counts_by_status(db: Session, q: str | None = None, *,
                         admitted_only: bool = False) -> dict[str, int]:
        """Conteo por pestaña: las 3 llaves de `LIBRARY_STATUSES` siempre
        presentes. Mismo criterio que `list_for_inbox` (búsqueda `q` por nombre
        o número de control; «Por revisar» SIEMPRE sin procesos revocados ni
        terminados, ni los que ya pasaron su cotejo -Ruling R20-), para que el
        contador no anuncie lo que la tabla no muestra.

        `admitted_only` (Ruling R9, spec §4.8): además filtra `awaiting_payment`
        a procesos admitidos -- lo pide Caja («Por cobrar», lista Y contador),
        gemelo de `list_for_inbox(admitted_only=)`. Por omisión en `False`: la
        bandeja de Biblioteca («En caja») sigue contando TODO `awaiting_payment`
        -incluido un proceso ya revocado, que se pinta «Revocada» sin
        acciones- porque su lista (`list_for_inbox` sin el flag) también los
        sigue mostrando; cambiar el default aquí sin tocar la lista
        desalinearía el contador de lo que la tabla pinta."""
        from itcj2.apps.titulatec.models import LibraryClearance, TitulationProcess
        from itcj2.apps.titulatec.models.library_clearance import LIBRARY_STATUSES
        from itcj2.core.models.user import User

        query = (db.query(LibraryClearance.status, func.count(LibraryClearance.id))
                 .join(TitulationProcess, TitulationProcess.id == LibraryClearance.process_id)
                 .filter(LibraryClearanceService._pending_actionable(admitted_only)))
        texto = (q or "").strip()
        if texto:
            patron = f"%{texto}%"
            query = (query.join(User, User.id == TitulationProcess.student_id)
                     .filter(or_(User.full_name.ilike(patron),
                                 User.control_number.ilike(patron))))
        out = {estado: 0 for estado in LIBRARY_STATUSES}
        for estado, total in query.group_by(LibraryClearance.status).all():
            if estado in out:
                out[estado] = total
        return out

    @staticmethod
    def list_for_inbox(db: Session, *, status: str, q: str | None = None,
                       page: int = 1, per_page: int = 50,
                       admitted_only: bool = False) -> tuple[list[dict], bool]:
        """Página de una pestaña de las bandejas de Biblioteca y Caja.

        * `pending` («Por revisar»): FIFO por la aceptación de la inscripción
          (`TitulationProcess.created_at`); SIEMPRE fuera los procesos
          revocados o terminados y los que ya pasaron su cotejo (fase 2
          aprobada, Ruling R20): toda acción respondería 400 (patrón
          `_no_revocada_en_revision` de GTV, `_reviewable_clause`) --
          `admitted_only` no aplica aquí.
        * `awaiting_payment` («En caja» / «Por cobrar»): FIFO por `ready_at`.
          Biblioteca («En caja») y Caja («Por cobrar») comparten este mismo
          `status`, pero quieren cosas distintas: Biblioteca SIGUE mostrando
          un proceso ya revocado (se pinta «Revocada», sin acciones --
          `test_una_inscripcion_revocada_no_ofrece_acciones_y_se_etiqueta`,
          Tarea 7) para que quede claro por qué desapareció de «Por revisar»;
          Caja no tiene ningún uso para un caso que no puede cobrar, así que
          `admitted_only=True` (Ruling R9, spec §4.8: «Por cobrar» lista Y
          contador solo procesos admitidos, mismo predicado que «Por
          revisar») lo saca por completo. Por eso NO es el comportamiento por
          omisión: el llamador de Caja (`pages/cashier_admin.py`) lo pide
          explícito; Biblioteca no cambia.
        * `cleared` («Liberados»): lo liberado más reciente primero
          (`updated_at`); SIN este filtro -- conserva el historial de lo ya
          liberado aunque el proceso se haya revocado después.

        `can_revert` y el número de constancia vigente se calculan EN LOTE (una
        consulta cada uno por página), nunca por fila. Devuelve
        `(filas, has_more)`; cada fila es el dict de `_rows`.
        """
        from itcj2.apps.titulatec.models import LibraryClearance, TitulationProcess
        from itcj2.apps.titulatec.models.library_clearance import LIBRARY_STATUSES

        if status not in LIBRARY_STATUSES:
            raise ValueError(f"Pestaña desconocida: {status!r}.")
        page = max(1, int(page))
        per_page = max(1, int(per_page))

        query = (LibraryClearanceService._inbox_query(db, q)
                 .filter(LibraryClearance.status == status))
        if status == "pending":
            query = query.filter(LibraryClearanceService._reviewable_clause())
        elif status == "awaiting_payment" and admitted_only:
            query = query.filter(TitulationProcess.status.in_(ADMITTED_PROCESS_STATUSES))
        if status == "pending":
            query = query.order_by(TitulationProcess.created_at.asc(),
                                   TitulationProcess.id.asc())
        elif status == "awaiting_payment":
            query = query.order_by(LibraryClearance.ready_at.asc(),
                                   LibraryClearance.id.asc())
        else:
            query = query.order_by(LibraryClearance.updated_at.desc(),
                                   LibraryClearance.id.desc())

        filas = query.offset((page - 1) * per_page).limit(per_page + 1).all()
        has_more = len(filas) > per_page
        return LibraryClearanceService._rows(db, filas[:per_page]), has_more

    @staticmethod
    def cohorts_missing_donation(db: Session) -> list[dict]:
        """Convocatorias SIN donación capturada que tienen casos «Por revisar»
        (aviso de la bandeja de Biblioteca, D19): `[{"cohort_id", "name",
        "pending"}]`, por nombre. Solo cuentan los que «Por revisar» muestra
        (`_reviewable_clause`: admitidos y sin la fase 2 aprobada)."""
        from itcj2.apps.titulatec.models import Cohort, LibraryClearance, TitulationProcess

        filas = (db.query(Cohort.id, Cohort.name, func.count(LibraryClearance.id))
                 .join(TitulationProcess, TitulationProcess.cohort_id == Cohort.id)
                 .join(LibraryClearance, LibraryClearance.process_id == TitulationProcess.id)
                 .filter(Cohort.book_donation_amount.is_(None),
                         LibraryClearance.status == "pending",
                         LibraryClearanceService._reviewable_clause())
                 .group_by(Cohort.id, Cohort.name)
                 .order_by(Cohort.name.asc(), Cohort.id.asc())
                 .all())
        return [{"cohort_id": cid, "name": nombre, "pending": total}
                for cid, nombre, total in filas]

    @staticmethod
    def search(db: Session, q: str | None, limit: int = 20) -> list[dict]:
        """Buscador de Caja (§4.8): nombre o número de control, en CUALQUIER
        estado («En Biblioteca», «Por cobrar», «Pagado»). El número de control
        exacto sale primero; luego por nombre. `q` vacío → `[]`."""
        from itcj2.apps.titulatec.models import LibraryClearance
        from itcj2.core.models.user import User

        texto = (q or "").strip()
        if not texto:
            return []
        limit = max(1, min(int(limit), 100))
        filas = (LibraryClearanceService._inbox_query(db, texto)
                 .order_by(case((func.upper(User.control_number) == texto.upper(), 0),
                                else_=1),
                           User.full_name.asc(),
                           LibraryClearance.id.asc())
                 .limit(limit)
                 .all())
        return LibraryClearanceService._rows(db, filas)

    @staticmethod
    def paid_on(db: Session, day: date) -> tuple[list[dict], Decimal]:
        """Pagos registrados en Caja ese día (pestaña «Pagados»): filas
        `cleared/payment` con `paid_at` dentro del día, recientes primero, y
        el «Total del día» como `Decimal` (corte simple). Un pago revertido ya
        no tiene `paid_at`: sale del corte."""
        from itcj2.apps.titulatec.models import LibraryClearance

        if isinstance(day, datetime):
            day = day.date()
        inicio = datetime.combine(day, time.min)
        fin = inicio + timedelta(days=1)
        filas = (LibraryClearanceService._inbox_query(db)
                 .filter(LibraryClearance.status == "cleared",
                         LibraryClearance.cleared_via == "payment",
                         LibraryClearance.paid_at >= inicio,
                         LibraryClearance.paid_at < fin)
                 .order_by(LibraryClearance.paid_at.desc(), LibraryClearance.id.desc())
                 .all())
        rows = LibraryClearanceService._rows(db, filas)
        total = sum((fila["total"] or Decimal("0") for fila in rows), Decimal("0"))
        return rows, Decimal(total).quantize(_CENT)

    # --------------------------------------------------------- piezas internas
    @staticmethod
    def _locked(db: Session, clearance_id: int):
        """La fila, bloqueada con `FOR UPDATE` y RELEÍDA (`populate_existing`):
        si otra persona la cambió mientras esperábamos el lock, se ve su
        cambio y no la foto vieja del mapa de identidad. `LookupError` si no
        existe (la ruta lo traduce a 404)."""
        from itcj2.apps.titulatec.models import LibraryClearance

        row = (db.query(LibraryClearance).filter_by(id=clearance_id)
               .populate_existing().with_for_update().first())
        if row is None:
            raise LookupError(f"No existe el registro de no adeudo {clearance_id}.")
        return row

    @staticmethod
    def _locked_by_process(db: Session, process_id: int):
        from itcj2.apps.titulatec.models import LibraryClearance
        return (db.query(LibraryClearance).filter_by(process_id=process_id)
                .populate_existing().with_for_update().first())

    @staticmethod
    def _insert_if_missing(db: Session, process_id: int) -> None:
        """`INSERT … ON CONFLICT (process_id) DO NOTHING`: abre la fila `pending`
        sin chocar con el UNIQUE si otro la abrió al mismo tiempo."""
        from sqlalchemy.dialects.postgresql import insert as pg_insert
        from itcj2.apps.titulatec.models import LibraryClearance

        tabla = LibraryClearance.__table__
        db.execute(pg_insert(tabla)
                   .values(process_id=process_id, status="pending")
                   .on_conflict_do_nothing(index_elements=["process_id"]))

    @staticmethod
    def _admitted_process(db: Session, clearance):
        """El proceso de la fila, exigiendo `active`/`on_hold` (§4.2)."""
        from itcj2.apps.titulatec.models import TitulationProcess

        process = db.get(TitulationProcess, clearance.process_id)
        estado = process.status if process is not None else None
        if estado in ADMITTED_PROCESS_STATUSES:
            return process
        if estado == "cancelled":
            raise ValueError("La inscripción de este egresado fue revocada; "
                             "ya no admite cambios.")
        if estado == "completed":
            raise ValueError("El proceso de este egresado ya terminó; ya no admite cambios.")
        raise ValueError(f"El proceso ya no admite cambios (estado: {estado or 'desconocido'}).")

    @staticmethod
    def _prepare_registration(db: Session, clearance, *, debt_amount, note,
                              expected_status=None, expected_total=None,
                              phase2_approved: bool | None = None) -> dict:
        """TODA la validación de Registrar/Corregir, sin mutar nada: proceso
        admitido, estado, lo que el usuario vio, que todavía no pasó su
        cotejo (Ruling R20), monto, nota y donación capturada. Devuelve el
        plan que aplica `_apply_registration`. `phase2_approved` lo trae ya
        resuelto el lote (una consulta para todas las filas); `None` = se
        pregunta aquí."""
        process = LibraryClearanceService._admitted_process(db, clearance)
        if clearance.status not in ("pending", "awaiting_payment"):
            raise ValueError("Este no adeudo ya está liberado; para cambiarlo, primero "
                             "revierte la liberación.")
        LibraryClearanceService._check_expected(
            clearance, expected_status=expected_status, expected_total=expected_total)
        if phase2_approved is None:
            phase2_approved = LibraryClearanceService._phase2_approved(db, process.id)
        if phase2_approved:
            raise ValueError(_MSG_COTEJO_YA_LIBERADO)
        debt = _check_amount(debt_amount)
        nota = LibraryClearanceService._clean_note(note)
        cohort = process.cohort
        if cohort is None or cohort.book_donation_amount is None:
            nombre = cohort.name if cohort is not None else "de este egresado"
            raise ValueError(
                f"La convocatoria {nombre} no tiene capturada la donación voluntaria "
                "de libro; pide a Servicios Escolares que la capture.")
        donation = Decimal(cohort.book_donation_amount).quantize(_CENT)
        return {"process": process, "debt": debt, "donation": donation,
                "total": debt + donation, "note": nota,
                "correcting": clearance.status == "awaiting_payment"}

    @staticmethod
    def _apply_registration(db: Session, clearance, plan: dict, actor_id: int,
                            requirement) -> None:
        """Aplica un plan ya validado. Sin commit."""
        if plan["total"] == 0:
            LibraryClearanceService._clear_no_charge(db, clearance, plan, actor_id, requirement)
        else:
            LibraryClearanceService._mark_ready(db, clearance, plan, actor_id)

    @staticmethod
    def _stamp_registration(clearance, plan: dict, actor_id: int, ahora) -> None:
        """Montos congelados y firma de Biblioteca (Registrar y Corregir)."""
        clearance.debt_amount = plan["debt"]
        clearance.donation_amount = plan["donation"]
        clearance.total_amount = plan["total"]
        clearance.library_note = plan["note"]
        clearance.library_by_id = actor_id
        clearance.library_at = ahora
        clearance.updated_at = ahora

    @staticmethod
    def _mark_ready(db: Session, clearance, plan: dict, actor_id: int) -> None:
        """→ `awaiting_payment` (pasa a Caja, o corrige el monto). Sin commit.

        Ruling R10: (a) entrar a Caja desde `pending` vuelve a fijar
        `ready_at` (corregir dentro de `awaiting_payment`, no); (b) una
        corrección que no cambia nada —mismo adeudo, misma donación congelada
        (la vigente de la convocatoria), misma nota— es no-op: ni evento, ni
        aviso, ni correo, ni firma nueva."""
        if plan["correcting"] and LibraryClearanceService._same_registration(
                clearance, plan):
            return
        previo = LibraryClearanceService._amounts(clearance) if plan["correcting"] else None
        ahora = db_now()
        clearance.status = "awaiting_payment"
        clearance.cleared_via = None
        LibraryClearanceService._stamp_registration(clearance, plan, actor_id, ahora)
        if not plan["correcting"]:
            clearance.ready_at = ahora          # entra a Caja (Ruling R10)

        datos = {"clearance_id": clearance.id, **LibraryClearanceService._amounts(clearance),
                 "note": plan["note"]}
        if previo is not None:
            datos["previous"] = previo
        LibraryClearanceService._log(
            db, plan["process"].id, actor_id,
            "library_amount_corrected" if plan["correcting"] else "library_debt_registered",
            datos)

        process = plan["process"]
        desglose = " + ".join(
            parte for parte in (
                f"adeudo {format_amount(plan['debt'])}" if plan["debt"] > 0 else "",
                (f"donación voluntaria de libro {format_amount(plan['donation'])}"
                 if plan["donation"] > 0 else ""),
            ) if parte)
        prefijo = "Biblioteca corrigió tu monto. " if plan["correcting"] else ""
        from itcj2.apps.titulatec.services.notify import notify_student
        notify_student(db, process.student_id, type="LIBRARY_READY",
                       title="Ya puedes pasar a Caja",
                       body=(f"{prefijo}Total a pagar: {format_amount(plan['total'])} "
                             f"({desglose}). Acude a Caja (Recursos Financieros) con tu "
                             "número de control; no necesitas cita."),
                       process_id=process.id, phase_number=PHASE_COTEJO)
        from itcj2.apps.titulatec.services.student_mail import StudentMail
        StudentMail.library_ready(db, process, debt=plan["debt"],
                                  donation=plan["donation"], total=plan["total"],
                                  note=plan["note"], updated=plan["correcting"])

    @staticmethod
    def _same_registration(clearance, plan: dict) -> bool:
        """¿La corrección deja la fila igual? Mismo adeudo, misma donación
        congelada y misma nota (el total se deriva de los dos montos)."""
        return (clearance.debt_amount == plan["debt"]
                and clearance.donation_amount == plan["donation"]
                and clearance.library_note == plan["note"])

    @staticmethod
    def _clear_no_charge(db: Session, clearance, plan: dict, actor_id: int,
                         requirement) -> None:
        """→ `cleared/no_charge` (total 0, D18): cumple el requisito y emite la
        constancia BIB. Sin commit."""
        ahora = db_now()
        clearance.status = "cleared"
        clearance.cleared_via = "no_charge"
        LibraryClearanceService._stamp_registration(clearance, plan, actor_id, ahora)

        process = plan["process"]
        LibraryClearanceService._fulfill(db, process, clearance, requirement, actor_id)
        from itcj2.apps.titulatec.services.certificate_service import CertificateService
        cert = CertificateService.issue(db, kind=CERT_KIND, process=process,
                                        source_ref=_ref(clearance.id), actor_id=actor_id)
        datos = {"clearance_id": clearance.id, **LibraryClearanceService._amounts(clearance),
                 "note": plan["note"], "corrected": plan["correcting"],
                 "certificate": cert.number}
        LibraryClearanceService._log(db, process.id, actor_id, "library_no_charge", datos)

        from itcj2.apps.titulatec.services.notify import notify_student
        notify_student(db, process.student_id, type="LIBRARY_CLEARED",
                       title="Tu no adeudo de biblioteca quedó liberado",
                       body="Biblioteca registró que no tienes nada que pagar.",
                       process_id=process.id, phase_number=PHASE_COTEJO)
        from itcj2.apps.titulatec.services.student_mail import StudentMail
        StudentMail.library_cleared(db, process, via="no_charge")

    @staticmethod
    def _reset_to_pending(clearance) -> None:
        """Vuelve la fila a la forma de recién abierta. Conserva `ready_at`
        como historia: la siguiente entrada a Caja lo vuelve a fijar (R10)."""
        clearance.status = "pending"
        clearance.cleared_via = None
        clearance.debt_amount = None
        clearance.donation_amount = None
        clearance.total_amount = None
        clearance.library_note = None
        clearance.library_by_id = None
        clearance.library_at = None
        clearance.paid_by_id = None
        clearance.paid_at = None
        clearance.receipt_number = None
        clearance.prior_issued_on = None
        clearance.prior_note = None
        clearance.prior_by_id = None
        clearance.updated_at = db_now()

    @staticmethod
    def _amounts(clearance) -> dict:
        return {"debt": _txt(clearance.debt_amount),
                "donation": _txt(clearance.donation_amount),
                "total": _txt(clearance.total_amount)}

    @staticmethod
    def _snapshot(clearance) -> dict:
        """Lo que se pierde al volver a `pending`, para el payload del evento."""
        return {
            "via": clearance.cleared_via,
            **LibraryClearanceService._amounts(clearance),
            "note": clearance.library_note,
            "issued_on": (clearance.prior_issued_on.isoformat()
                          if clearance.prior_issued_on else None),
            "prior_note": clearance.prior_note,
        }

    @staticmethod
    def _check_expected(clearance, *, expected_status=None, expected_total=None) -> None:
        """¿Sigue la fila como la vio el usuario? (Review Focus #1).

        `expected_total` NO pasa por `_check_amount` (Ruling R9, spec §4.8):
        ese tope (`AMOUNT_MAX`) topa lo que SE TECLEA (`debt_amount`), pero
        `expected_total` es la SUMA ya hecha de adeudo + donación que la
        bandeja le mostró al usuario -un adeudo al tope más la donación
        fácilmente la supera- así que aquí solo se exige forma mínima
        (`_check_total_shape`: finito y >= 0), nunca el tope.
        """
        if expected_status is not None and clearance.status != expected_status:
            actual = _STATUS_LABELS.get(clearance.status, clearance.status)
            raise ValueError(f"Otra persona ya movió este caso: ahora está «{actual}». "
                             "Revisa esa pestaña y vuelve a intentarlo.")
        if expected_total is not None:
            esperado = LibraryClearanceService._check_total_shape(expected_total)
            actual = clearance.total_amount
            if actual is None or Decimal(actual) != esperado:
                detalle = f": ahora es {format_amount(actual)}" if actual is not None else ""
                raise ValueError(f"El monto cambió mientras lo revisabas{detalle}. "
                                 "Revisa el caso y vuelve a confirmar.")

    @staticmethod
    def _check_total_shape(value) -> Decimal:
        """Forma mínima de un `expected_total` (Ruling R9): finito y >= 0,
        SIN el tope `AMOUNT_MAX` -- ver `_check_expected`. Nunca `float`."""
        if isinstance(value, bool) or not isinstance(value, (Decimal, int)):
            raise ValueError(_MSG_AMOUNT_FORMAT)
        total = Decimal(value)
        if not total.is_finite():
            raise ValueError(_MSG_AMOUNT_FORMAT)
        if total < 0:
            raise ValueError("El monto no puede ser negativo.")
        return total

    @staticmethod
    def _library_requirement(db: Session, cohort_id: int):
        """El requisito automático ACTIVO de no adeudo de la convocatoria, o
        `None` (convocatoria sin candado de biblioteca: no hay cumplimiento que
        escribir). Siembra los `DEFAULTS` si la convocatoria no tiene lista,
        sin commit (`RequirementService.auto_requirement`)."""
        from itcj2.apps.titulatec.services.requirement_service import RequirementService
        return RequirementService.auto_requirement(db, cohort_id, AUTO_SOURCE_LIBRARY)

    @staticmethod
    def _fulfill(db: Session, process, clearance, requirement, actor_id) -> None:
        if requirement is None:
            return
        from itcj2.apps.titulatec.services.requirement_service import RequirementService
        RequirementService.fulfill(
            db, process.id, requirement.id, source="system", checked_by_id=actor_id,
            external_ref=_ref(clearance.id), commit=False,
        )

    @staticmethod
    def _unfulfill(db: Session, process, requirement, actor_id) -> None:
        if requirement is None:
            return
        from itcj2.apps.titulatec.services.requirement_service import RequirementService
        RequirementService.unfulfill(db, process.id, requirement.id,
                                     actor_id=actor_id, commit=False)

    @staticmethod
    def _phase2_approved(db: Session, process_id: int) -> bool:
        from itcj2.apps.titulatec.models import ProcessPhase

        fase2 = (db.query(ProcessPhase.status)
                 .filter_by(process_id=process_id, phase_number=PHASE_COTEJO)
                 .first())
        return fase2 is not None and fase2[0] == "approved"

    @staticmethod
    def _phase2_approved_ids(db: Session, process_ids) -> set[int]:
        """`_phase2_approved` de varios procesos en UNA consulta (el lote)."""
        from itcj2.apps.titulatec.models import ProcessPhase

        ids = list(process_ids)
        if not ids:
            return set()
        return {pid for (pid,) in
                db.query(ProcessPhase.process_id)
                .filter(ProcessPhase.process_id.in_(ids),
                        ProcessPhase.phase_number == PHASE_COTEJO,
                        ProcessPhase.status == "approved")}

    @staticmethod
    def _assert_phase2_open(db: Session, process) -> None:
        if LibraryClearanceService._phase2_approved(db, process.id):
            raise ValueError("La fase 2 de este egresado ya fue liberada; "
                             "ya no se puede revertir.")

    @staticmethod
    def _assert_needs_clearance(db: Session, process) -> None:
        """Ruling R20 (I2): quien ya pasó su cotejo (fase 2 `approved`) no
        abre trámite de no adeudo -su estado es `NOT_APPLICABLE`-. Lo usa la
        constancia previa; Registrar y el lote hacen la MISMA pregunta, con el
        mismo mensaje, dentro de `_prepare_registration` (el lote con la
        respuesta ya resuelta para todas sus filas)."""
        if LibraryClearanceService._phase2_approved(db, process.id):
            raise ValueError(_MSG_COTEJO_YA_LIBERADO)

    @staticmethod
    def _notify_reverted(db: Session, process, motivo: str) -> None:
        from itcj2.apps.titulatec.services.notify import notify_student
        notify_student(db, process.student_id, type="LIBRARY_REVERTED",
                       title="Se revirtió tu no adeudo de biblioteca",
                       body=motivo, process_id=process.id, phase_number=PHASE_COTEJO)

    @staticmethod
    def _check_prior_date(issued_on) -> date:
        if issued_on is None:
            raise ValueError("Escribe la fecha de la constancia previa.")
        if isinstance(issued_on, datetime):
            issued_on = issued_on.date()
        if not isinstance(issued_on, date):
            raise ValueError("La fecha de la constancia previa no es válida.")
        hoy = db_now().date()
        if issued_on > hoy:
            raise ValueError("La fecha de la constancia previa no puede ser futura.")
        if issued_on < hoy - timedelta(days=PRIOR_VALIDITY_DAYS):
            raise ValueError("La constancia venció: tiene más de un año.")
        return issued_on

    @staticmethod
    def _clean_reason(reason: str | None) -> str:
        """Motivo listo para guardar: recortado, 1..`REASON_MAX` caracteres."""
        limpio = (reason or "").strip()
        if not limpio:
            raise ValueError("Escribe el motivo antes de continuar.")
        if len(limpio) > REASON_MAX:
            raise ValueError(f"El motivo no puede superar los {REASON_MAX} caracteres.")
        return limpio

    @staticmethod
    def _clean_note(note: str | None) -> str | None:
        """Nota opcional: recortada; en blanco → `None`; <= `REASON_MAX`."""
        limpio = (note or "").strip()
        if len(limpio) > REASON_MAX:
            raise ValueError(f"La nota no puede superar los {REASON_MAX} caracteres.")
        return limpio or None

    @staticmethod
    def _clean_receipt(receipt_number: str | None) -> str | None:
        limpio = (receipt_number or "").strip()
        if len(limpio) > RECEIPT_MAX:
            raise ValueError(f"El número de recibo no puede pasar de {RECEIPT_MAX} "
                             "caracteres.")
        return limpio or None

    @staticmethod
    def _phase2_open_clause():
        """SQL: la fase 2 del proceso NO está `approved` (sin fila cuenta como
        no aprobada), correlacionada a `TitulationProcess` (la consulta que
        la use debe tenerlo en su FROM). Gemela SQL de `_phase2_approved`."""
        from sqlalchemy import exists

        from itcj2.apps.titulatec.models import ProcessPhase, TitulationProcess
        return ~(exists()
                 .where(ProcessPhase.process_id == TitulationProcess.id,
                        ProcessPhase.phase_number == PHASE_COTEJO,
                        ProcessPhase.status == "approved")
                 .correlate(TitulationProcess))

    @staticmethod
    def _reviewable_clause():
        """«Por revisar» de Biblioteca: proceso admitido (`active`/`on_hold`)
        Y que todavía no pasó su cotejo (Ruling R20) -- exactamente a quien
        `register`/el lote sí aceptarían. Lista, contador y aviso de donación
        comparten este predicado, para que ninguno anuncie lo que la tabla no
        muestra."""
        from sqlalchemy import and_

        from itcj2.apps.titulatec.models import TitulationProcess
        return and_(TitulationProcess.status.in_(ADMITTED_PROCESS_STATUSES),
                    LibraryClearanceService._phase2_open_clause())

    @staticmethod
    def _pending_actionable(admitted_only: bool = False):
        """«Por revisar» SIEMPRE solo con lo que Biblioteca puede registrar
        (`_reviewable_clause`: admitido y sin la fase 2 aprobada);
        `admitted_only` suma `awaiting_payment` con la regla de admitidos
        (Ruling R9, lo pide el contador de Caja, `counts_by_status(
        admitted_only=True)`; Caja SÍ cobra aunque la fase 2 ya esté
        aprobada) -- el resto de las pestañas conserva el historial de los
        revocados o terminados. El llamador ya hizo JOIN a
        `TitulationProcess`."""
        from sqlalchemy import and_

        from itcj2.apps.titulatec.models import LibraryClearance, TitulationProcess
        por_revisar = or_(LibraryClearance.status != "pending",
                          LibraryClearanceService._reviewable_clause())
        if not admitted_only:
            return por_revisar
        return and_(por_revisar,
                    or_(LibraryClearance.status != "awaiting_payment",
                        TitulationProcess.status.in_(ADMITTED_PROCESS_STATUSES)))

    @staticmethod
    def _inbox_query(db: Session, q: str | None = None):
        """Fila + proceso + egresado + carrera + convocatoria, con la búsqueda
        `q` (ILIKE sobre nombre completo o número de control) ya aplicada."""
        from itcj2.apps.titulatec.models import Cohort, LibraryClearance, TitulationProcess
        from itcj2.core.models.program import Program
        from itcj2.core.models.user import User

        query = (db.query(LibraryClearance, TitulationProcess, User, Program, Cohort)
                 .join(TitulationProcess, TitulationProcess.id == LibraryClearance.process_id)
                 .join(User, User.id == TitulationProcess.student_id)
                 .outerjoin(Program, Program.id == TitulationProcess.program_id)
                 .join(Cohort, Cohort.id == TitulationProcess.cohort_id))
        texto = (q or "").strip()
        if texto:
            patron = f"%{texto}%"
            query = query.filter(or_(User.full_name.ilike(patron),
                                     User.control_number.ilike(patron)))
        return query

    @staticmethod
    def _rows(db: Session, filas) -> list[dict]:
        """Dicts de las bandejas. `can_revert` y la constancia vigente en DOS
        consultas por página, nunca una por fila. Valores crudos (`Decimal`,
        `datetime`, `date`): formatear es de la plantilla (`format_amount`)."""
        from itcj2.apps.titulatec.models import Certificate, ProcessPhase

        if not filas:
            return []
        pids = [process.id for _, process, *_ in filas]
        fase2 = dict(
            db.query(ProcessPhase.process_id, ProcessPhase.status)
            .filter(ProcessPhase.process_id.in_(pids),
                    ProcessPhase.phase_number == PHASE_COTEJO)
            .all())
        refs = [_ref(clearance.id) for clearance, *_ in filas]
        vigentes = dict(
            db.query(Certificate.source_ref, Certificate.number)
            .filter(Certificate.source_ref.in_(refs), Certificate.voided_at.is_(None))
            .all())

        out = []
        for clearance, process, student, program, cohort in filas:
            out.append({
                "id": clearance.id,
                "process_id": process.id,
                "student": student.full_name,
                "control": student.control_number or "",
                "program": program.name if program else "",
                "cohort": cohort.name,
                "cohort_id": cohort.id,
                "current_phase": process.current_phase,
                "status": clearance.status,
                "via": clearance.cleared_via,
                "debt": clearance.debt_amount,
                "donation": clearance.donation_amount,
                "total": clearance.total_amount,
                "note": clearance.library_note,
                "library_at": clearance.library_at,
                "ready_at": clearance.ready_at,
                "paid_at": clearance.paid_at,
                "receipt": clearance.receipt_number,
                "prior_issued_on": clearance.prior_issued_on,
                "prior_note": clearance.prior_note,
                "updated_at": clearance.updated_at,
                "enrolled_at": process.created_at,
                "certificate_number": vigentes.get(_ref(clearance.id)),
                "can_revert": (clearance.status == "cleared"
                               and process.status in ADMITTED_PROCESS_STATUSES
                               and fase2.get(process.id) != "approved"),
                "revoked": process.status == "cancelled",
                "admitted": process.status in ADMITTED_PROCESS_STATUSES,
                "donation_missing": cohort.book_donation_amount is None,
            })
        return out
