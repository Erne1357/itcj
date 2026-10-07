"""Servicio del no adeudo de biblioteca: Biblioteca registra, Caja cobra.

Spec `docs/superpowers/specs/2026-10-01-titulatec-biblioteca-caja-design.md`
§4.2 (máquina de estados), D3/D4/D5/D9/D16-D19, §4.7/§4.8 (bandejas) y §5
(invariantes). Este service es el ÚNICO escritor de
`titulatec_library_clearances` y del cumplimiento del requisito de cotejo
`library_clearance` (§5, invariante 1): nadie fuera de aquí muta esa fila.

Máquina de estados (modelo `LibraryClearance`):

    (alta del proceso | backfill) ──────────────────────────────> pending
    pending ──Registrar (Biblioteca), total > 0 ────────────────> awaiting_payment
    pending ──Registrar (Biblioteca), total = 0 ────────────────> cleared/no_charge  (+folio BIB)
    awaiting_payment ──Corregir (Biblioteca) ───────────────────> awaiting_payment (nuevo monto)
                                                                  | cleared/no_charge si total = 0
    awaiting_payment ──Registrar pago (Caja) ───────────────────> cleared/payment    (+folio BIB)
    pending|awaiting_payment ──Constancia previa (Biblioteca, SE o importación)
                                                                ─> cleared/prior     (+folio BIB, semestre anterior)
    (migración tt20261001a | promoción D17) ────────────────────> cleared/legacy    (dato, no una transición: su folio
                                                                  BIB, semestre anterior, lo emite el backfill
                                                                  `FolioBackfillService`, no este service)
    cleared/payment ──Revertir pago (Caja, motivo) ─────────────> awaiting_payment   (anula el folio)
    cleared/no_charge|legacy ──Revertir (Biblioteca, motivo) ───> pending            (anula el folio si hay)
    cleared/prior ──Deshacer constancia previa (motivo) ────────> pending            (anula el folio)
    pending|awaiting_payment ──Observar (Biblioteca, motivo) ───> observed/blocking  (`ready_at` = NULL)
    pending|awaiting_payment ──Observar con adeudo (motivo, adeudo; total > 0)
                                                                ─> observed/with_debt (montos congelados
                                                                   como al Registrar; entra a Caja)
    observed ──Observar otra vez (actualiza el motivo; el adeudo, si no hay pago)
                                                                ─> observed
    observed/with_debt (sin pago) ──Registrar pago (Caja) ──────> observed/with_debt + pago RETENIDO
                                                                  (sin folio, sin requisito, sin cita)
    observed/with_debt + pago ──Revertir pago (Caja, motivo) ───> observed/with_debt (sin pago)
    observed/blocking ──Activar (Biblioteca) ───────────────────> pending   (montos intactos)
    observed/with_debt sin pago ──Activar (Biblioteca) ─────────> awaiting_payment (`ready_at` = ahora)
    observed/with_debt + pago ──Activar (Biblioteca) ───────────> cleared/payment  (+folio BIB)

«Con observaciones» (spec `2026-10-05-titulatec-biblioteca-observaciones-
design.md` §2/§3.2, gemelo de «Observar» de GTV): Biblioteca DETIENE al
egresado con un motivo. Desde `cleared` no se observa (primero se revierte).
Hay DOS tipos (`observation_kind`, spec `2026-10-07-titulatec-liberados-
biblioteca-helpdesk-design.md` §2, D3/D4):

* `blocking` («observación normal», la de siempre, D4): mientras dura
  ninguna otra transición aplica -ni Registrar, ni el pago de Caja, ni las
  reversas, ni la constancia previa- con el mensaje `_MSG_OBSERVADO`; solo
  Activar, que lo regresa SIEMPRE a `pending` con los montos que tuviera
  (precargan el formulario de Registrar). Observarlo desde Caja limpia
  `ready_at` (sale de «Por cobrar» y de los recordatorios de pago) y conserva
  los montos.
* `with_debt` («con adeudo», D3: «tiene un libro y debe entregarlo, y además
  debe X»): Biblioteca captura el adeudo y se congela con la MISMA lógica que
  Registrar (`_frozen_donation`: donación vigente de la convocatoria, total =
  adeudo + donación; total 0 → `ValueError`, «usa la observación normal»).
  Entra a Caja (`ready_at` = ahora si no estaba ya ahí) y Caja SÍ cobra, pero
  el pago queda RETENIDO: la fila sigue `observed/with_debt` con
  `paid_at`/`paid_by_id`/`receipt_number`, SIN folio, SIN requisito y con el
  candado de la cita cerrado (`ClearanceGate` ve `observed` igual que
  siempre). El cobro escribe el MISMO evento `library_payment_registered`
  (con `certificate: None`, `held: True` y su `paid_at`) para que el corte
  del día lo cuente el día que se cobra; su reversa, el mismo
  `library_payment_reverted`. Lo libera «Activar»: sin pago → `awaiting_payment`
  (Caja cobra por el camino normal); con pago → `cleared/payment` con folio,
  requisito, avisos y correo de «liberada» y su PROPIO evento
  `library_cleared_after_observation` (repetir `library_payment_registered`
  contaría el cobro dos veces en el corte). No recibe recordatorios de pago
  (`payment_due` es solo de `awaiting_payment`): el correo de la observación
  ya le dice que pague y entregue en la misma visita.

Cambiar de tipo (Ruling de la Tarea E, 2026-10-07): re-observar puede pasar
de `blocking` a `with_debt` (congela montos) y de `with_debt` SIN pago a
`blocking` (sale de Caja, conserva los montos como historia). Con un pago
retenido NO se cambia a `blocking` ni se cambia el adeudo -solo el motivo-:
una normal no deja revertir el pago y el dinero quedaría atrapado. Para eso,
Caja revierte primero. Registrar, la constancia previa y las reversas de
liberación siguen bloqueadas para los dos tipos. Una fila `observed` sin
`observation_kind` (dato anterior a `tt20261007a`) se lee como `blocking`
(falla cerrado). El requisito `library_clearance` no cambia al observar ni al
activar hacia `pending`/`awaiting_payment` (no estaba cumplido).

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

Constancias (§4.5) y folios (spec `2026-10-05-titulatec-folios-design.md`
§3.3): quedar `cleared` por `payment`/`no_charge` emite
`CertificateService.issue(kind='library_clearance',
source_ref='library_clearance:{id}')` en el semestre de la emisión; quedar
`cleared/prior` (`register_prior`, también con `commit=False`) emite el MISMO
`source_ref` en el semestre ANTERIOR al del registro
(`previous_semester_key`; para una previa diferida, el de su importación:
kwarg `registered_at`, D5). Revertir (`revert_payment`/`revert_clearance`) y
`undo_prior` anulan (`void`). `legacy` no emite aquí: sus folios los da el
backfill (`FolioBackfillService`: `titulatec emitir-folios-previos` y el paso 5
de `activar-biblioteca-caja`), que también cubre las previas registradas antes
de que este service emitiera. «A lo más una vigente por origen» (§5,
invariante 5) se cumple por construcción: solo se emite al ENTRAR a
cleared/payment|no_charge|prior y toda salida de esos estados anula; volver a
liberar saca un folio nuevo.

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
  Ese choque es `ClearanceConflict` (subclase de `ValueError`, Ruling R24):
  las rutas responden 200 con la bandeja re-pintada y un aviso, no un 400.
  `expected_total` se valida con `_check_total_shape` (finito y >= 0), NUNCA
  con el tope `AMOUNT_MAX` (Ruling R9, spec §4.8): ese tope topa lo que SE
  TECLEA (`debt_amount`), y un adeudo al tope más la donación lo supera sin
  dejar de ser un total legítimo.
* Correos (spec §4.11, §5 invariante 9): cada transición encola su correo
  de `StudentMail` junto a su aviso in-app, antes de su único commit (la
  fila nace en la MISMA transacción; si el commit falla, se va con él):
  pasa a Caja o se corrige el monto → `library_ready`; queda liberado (sin
  cargo, pago, constancia previa o al activar con pago retenido) →
  `library_cleared`; se revierte o deshace → `library_reverted`; observar →
  `library_observed`; activar → `library_reenabled` (o `library_cleared`).
  Dos ramas SIN su correo del catálogo (las fijan pruebas de comportamiento,
  `RAMAS_SIN_CORREO` de `test_mail_writers.py`): el cobro RETENIDO encola
  `library_payment_held` en vez de `library_cleared`, y revertir un pago
  retenido no encola nada (nunca se liberó; basta el aviso in-app). El
  recordatorio del pago pendiente lo encola el barrido diario
  (`MailReminders`). `test_mail_writers.py` fija evento → correo por AST.
* `updated_at` no tiene `onupdate` (ver el modelo): se fija a mano.
"""
from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation

from sqlalchemy import case, func, or_
from sqlalchemy.orm import Session

from itcj2.apps.titulatec.utils.paging import PAGE_SIZE, Page, paginate_query
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
_MSG_COTEJO_YA_LIBERADO = ("Este egresado ya pasó su cotejo; no necesita tramitar su "
                           "Constancia de no adeudo.")

# Quién registra una constancia previa: va al payload del evento.
PRIOR_BY = ("library", "school_services", "import")

# Los 10 `ProcessEvent` que escribe este service (fase 2, <= 40 caracteres).
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
    "library_observed",
    "library_reenabled",
    # Activar una observación con adeudo cuyo pago ya estaba retenido (spec
    # 2026-10-07 §2): libera SIN repetir `library_payment_registered` (el
    # corte del día ya contó ese cobro el día que se hizo).
    "library_cleared_after_observation",
)

# Tipos de observación (`LibraryClearance.observation_kind`, `OBSERVATION_KINDS`
# del modelo; spec 2026-10-07 §2). `blocking` detiene todo (D4); `with_debt`
# deja cobrar en Caja, pero el pago no libera hasta «Activar» (D3).
OBS_BLOCKING = "blocking"
OBS_WITH_DEBT = "with_debt"

_MSG_SIN_MONTO = ("Sin monto: con adeudo 0 y sin donación no hay nada que cobrar; usa la "
                  "observación normal.")
_MSG_PAGO_RETENIDO = ("Caja ya registró el pago de este adeudo: solo puedes cambiar el motivo. "
                      "Para cambiar el adeudo o el tipo de observación, pide a Caja que "
                      "revierta el pago primero.")

# Tipo de constancia que emite este service (`CERT_KINDS` de certificate_service).
CERT_KIND = "library_clearance"

# Nombre de cada estado en las pestañas (mensajes de concurrencia).
_STATUS_LABELS = {
    "pending": "Por revisar",
    "awaiting_payment": "En caja",
    "observed": "Con observaciones",
    "cleared": "Liberado",
}

# Cualquier transición sobre una fila `observed` que no sea Observar o
# Rehabilitar (spec 2026-10-05 §3.2).
_MSG_OBSERVADO = ("Está con observaciones de Biblioteca; actívalo primero.")

_CENT = Decimal("0.01")

# Pesos: «800», «800.5», «1,200.50» (comas de miles bien agrupadas). Solo
# dígitos ASCII: `\d` aceptaría dígitos de otros alfabetos.
_AMOUNT_RE = re.compile(r"(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.([0-9]+))?")

_MSG_AMOUNT_FORMAT = "Monto no válido: escríbelo en pesos, por ejemplo 1,200.50."


class ClearanceConflict(ValueError):
    """Choque optimista (Ruling R24, M1 de la revisión final): la fila ya no
    está como el usuario la vio -falló `expected_status` o `expected_total`,
    otra persona la movió mientras tenía la pantalla abierta-.

    Sigue siendo un `ValueError` (todo llamador viejo la trata como una
    regla de negocio más, y el lote la omite con su motivo), pero las rutas
    de Biblioteca (registrar/corregir) y Caja (pagar) la distinguen: responden
    200 con la bandeja RE-PINTADA y el mensaje en `X-Tt-Notice` (warning), en
    vez del 400 de las demás reglas -- htmx no hace swap en un 4xx, así que la
    fila seguía mostrando el estado viejo y reintentar volvía a fallar.
    Nada se escribe: se levanta antes de mutar."""


class ClearanceObserved(ValueError):
    """La fila está «Con observaciones» (spec 2026-10-05 §3.2): cualquier
    transición que no sea Observar o Rehabilitar la rechaza con
    `_MSG_OBSERVADO`. Sigue siendo un `ValueError` (los llamadores viejos y el
    lote la tratan como una regla más); Caja la distingue para RE-PINTAR un
    «Por cobrar» viejo en vez de un 400 sin swap (Review Focus 1), sin
    comparar el estado fuera de los dueños (invariante 2)."""


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
        `awaiting_payment` | `observed`) o `'missing'` sin fila. Fuente ÚNICA de esa
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
        2). Gemela de `SurveyReviewService.prior_outcome`. `"conflict"` =
        Biblioteca lo tiene `observed` («Con observaciones», spec 2026-10-05):
        `register_prior` lo rechazaría; lo decide Biblioteca (rehabilitar
        primero), no la importación."""
        row = LibraryClearanceService.get_for_process(db, process_id)
        if row is None or row.status in ("pending", "awaiting_payment"):
            return "apply"
        if row.status == "observed":
            return "conflict"
        return "already"

    @staticmethod
    def observation(db: Session, process_id: int) -> dict | None:
        """La observación VIGENTE de Biblioteca, SOLO LECTURA: `{"reason",
        "observed_at", "kind", "debt", "donation", "total", "paid_at",
        "receipt"}` si la fila está `observed` («Con observaciones»); `None`
        en cualquier otro estado o sin fila. `kind` es el tipo efectivo
        (`OBS_BLOCKING` | `OBS_WITH_DEBT`, NULL viejo = `blocking`); los
        montos y el pago (retenido) son los de la fila, crudos (`Decimal`,
        `datetime`). Para los correos de observar/activar/pago retenido
        (`mail_compose`), que así no comparan `LibraryClearance.status` por
        su cuenta (invariante 2)."""
        row = LibraryClearanceService.get_for_process(db, process_id)
        kind = LibraryClearanceService._observation_kind(row)
        if kind is None:
            return None
        return {"reason": row.observation_reason, "observed_at": row.observed_at,
                "kind": kind, "debt": row.debt_amount, "donation": row.donation_amount,
                "total": row.total_amount, "paid_at": row.paid_at,
                "receipt": row.receipt_number}

    @staticmethod
    def payment_held(clearance) -> bool:
        """¿Esta fila tiene un pago RETENIDO? (spec 2026-10-07 §2): observada
        CON ADEUDO y Caja ya cobró. SOLO LECTURA, sin consulta: las rutas de
        Caja lo usan para avisar «el pago no libera hasta que Biblioteca
        active» sin comparar el estado por su cuenta (invariante 2)."""
        return (LibraryClearanceService._observation_kind(clearance) == OBS_WITH_DEBT
                and clearance.paid_at is not None)

    @staticmethod
    def payment_due(db: Session, process_id: int) -> dict | None:
        """Lo que el egresado debe pagar en Caja AHORA, SOLO LECTURA:
        `{"debt", "donation", "total", "note", "ready_at"}` —los montos
        CONGELADOS de su fila (`Decimal`), la nota de Biblioteca y su entrada
        vigente a Caja— si su no adeudo está `awaiting_payment` Y su fase 2
        TODAVÍA no se aprobó; `None` en cualquier otro estado, sin fila, o con
        la fase 2 ya `approved` (Ruling R30 #4, re-revisión de la ola final,
        ronda 2: una fase 2 aprobada es `NOT_APPLICABLE` -Ruling R21- aunque
        la fila SIGA `awaiting_payment` -p. ej. durante la transición D17-;
        TitulaTec deja de PERSEGUIR el pago por correo, por el MISMO camino
        que «ya no tiene nada que pagar»).

        Para los correos del pago (spec §4.11): `library_ready`,
        `library_reminder` y la reversión de un pago se re-validan con esto al
        enviar y pintan los montos VIGENTES; con la fase 2 aprobada salen
        `Obsolete` sin que `mail_compose.py` tenga que preguntar nada aparte
        (invariante 2: ningún consumidor fuera del dueño y del gate llama
        `release_status`/`release_status_map`/`is_released`
        -`test_clearance_gate.py::test_solo_el_gate_pregunta_a_los_duenos_
        por_la_liberacion`-). Lee la FILA y no el candado a propósito: lo que
        Biblioteca mandó a Caja se debe aunque la convocatoria no exija el no
        adeudo para agendar -Caja SIGUE pudiendo cobrarlo si el egresado se
        presenta, `register_payment` no llama aquí-. No contesta «¿le faltan
        liberaciones?» —eso es SOLO de `ClearanceGate` (invariante 2)—: como
        `prior_outcome`, deja la comparación de `status`/fase 2 en el dueño."""
        row = LibraryClearanceService.get_for_process(db, process_id)
        if (row is None or row.status != "awaiting_payment"
                or LibraryClearanceService._phase2_approved(db, process_id)):
            return None
        return {"debt": row.debt_amount, "donation": row.donation_amount,
                "total": row.total_amount, "note": row.library_note,
                "ready_at": row.ready_at}

    @staticmethod
    def awaiting_payment_clause():
        """`payment_due` en SQL, sobre `LibraryClearance` Y `TitulationProcess`
        (la consulta que lo use debe tener LAS DOS en su FROM: `_phase2_
        open_clause` correlaciona contra `TitulationProcess`): el no adeudo
        está en Caja Y su fase 2 TODAVÍA no se aprobó -mismo criterio que
        `payment_due`, Ruling R30 #4 ronda 2: una fase 2 ya aprobada es
        `NOT_APPLICABLE` (Ruling R21) aunque la fila siga `awaiting_payment`-.
        Para los candidatos del recordatorio de pago (`MailReminders`), que
        así no compara `LibraryClearance.status` ni `ProcessPhase.status` por
        su cuenta -ni, mucho menos, llama `release_status*` (invariante 2)."""
        from sqlalchemy import and_

        from itcj2.apps.titulatec.models import LibraryClearance
        return and_(LibraryClearance.status == "awaiting_payment",
                    LibraryClearanceService._phase2_open_clause())

    @staticmethod
    def reviewable(db: Session, process_id: int) -> bool:
        """¿Biblioteca todavía revisa el no adeudo de este proceso? SOLO
        LECTURA: el proceso existe, está admitido (`active`/`on_hold`) y su
        fase 2 (la cita de cotejo) NO está `approved` -Ruling R20: a quien
        ya pasó su cotejo no se le abre trámite de no adeudo-. Es la gemela
        en Python de `_reviewable_clause` («Por revisar»): exactamente a
        quien `register`, el lote y la constancia previa aceptarían. No mira
        la fila de no adeudo (pregunta por el proceso; sin fila también
        responde). Un id sin proceso es `False` (falla cerrado).

        Para el correo de la reversión a Biblioteca (m40,
        `mail_compose._compose_library_reverted`): «El Centro de Información
        volverá a revisar tu caso» solo es cierto mientras esto sea `True`.
        Con la fase 2 ya aprobada el correo sale `Obsolete` sin que
        `mail_compose.py` compare estados (invariante 2): la misma forma que
        `payment_due` le da a la reversión a Caja."""
        from itcj2.apps.titulatec.models import TitulationProcess

        process = db.get(TitulationProcess, process_id)
        return (process is not None
                and process.status in ADMITTED_PROCESS_STATUSES
                and not LibraryClearanceService._phase2_approved(db, process_id))

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
        `ready_at`, `paid_at`, `receipt`, `prior_issued_on`, `prior_note`,
        `observation` (el motivo VIGENTE de «Con observaciones», NULL fuera
        de `observed`), `observed_at`, `observation_kind` (spec 2026-10-07
        §2: `blocking` | `with_debt` dentro de `observed`, `None` fuera; con
        `with_debt`, `total` es el adeudo congelado y `paid_at`/`receipt` el
        pago RETENIDO si Caja ya cobró), `can_revert`, `clearance_id`. Formatear es de quien pinta
        (`format_amount`). Con `NOT_APPLICABLE` las vistas del egresado no
        pintan nada y las de SE dicen «No aplica (cotejo ya liberado)» sin
        ofrecer «Constancia previa…».

        NO consulta constancias: ni el estado de impresión (Ruling R14) ni el
        folio vigente (`certificate_number` se quitó por el Ruling R17: sin
        lector desde la Task 4; Caja lee el de `_rows`), revisión final de
        `2026-10-02-titulatec-constancias-y-pendientes-design.md` §3.4. Este
        resumen también lo usan el tablero del egresado y «Mi cita», que no
        pintan la constancia. Las dos vistas de SE la cuelgan ellas como
        `certificate`, con UNA llamada a `CertificateService.print_status_map`
        para encuesta y no adeudo juntos (refs de `certificate_ref`).
        """
        row = LibraryClearanceService.get_for_process(db, process_id)
        no_aplica = ((row is None or row.status != "cleared")
                     and LibraryClearanceService._phase2_approved(db, process_id))
        if row is None:
            return {"status": NOT_APPLICABLE if no_aplica else "missing",
                    "via": None, "debt": None, "donation": None,
                    "total": None, "note": None, "ready_at": None, "paid_at": None,
                    "receipt": None,
                    "prior_issued_on": None, "prior_note": None,
                    "observation": None, "observed_at": None, "observation_kind": None,
                    "can_revert": False, "clearance_id": None}

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
            "prior_issued_on": row.prior_issued_on,
            "prior_note": row.prior_note,
            "observation": row.observation_reason,
            "observed_at": row.observed_at,
            "observation_kind": LibraryClearanceService._observation_kind(row),
            "can_revert": LibraryClearanceService.can_revert(db, row),
            "clearance_id": row.id,
        }

    @staticmethod
    def certificate_ref(clearance_id: int | None) -> str | None:
        """El `source_ref` de las constancias BIB de la fila
        `clearance_id` -el MISMO con que se emiten y anulan (`_ref`)-, o
        `None` sin fila. Con él las dos vistas de SE piden la marca de
        impresión en su UNA llamada a `CertificateService.print_status_map`
        (Ruling R14); un ref que no existe no se pide."""
        return _ref(clearance_id) if clearance_id is not None else None

    @staticmethod
    def can_revert(db: Session, clearance) -> bool:
        """¿Se puede revertir (o deshacer) esta liberación ahora mismo?

        Gemelo de `SurveyReviewService.can_revoke` (§4.2, §5 invariante 7): la
        fila está `cleared`, su proceso sigue admitido (`active`/`on_hold`) y
        la fase 2 todavía no está `approved`. Qué transición aplica la decide
        `cleared_via` (pago → `revert_payment`; sin cargo/legado →
        `revert_clearance`; previa → `undo_prior`).

        Delega el predicado a `_revertible_ids` (mismo criterio exacto que
        usan `_rows` y `day_cut` en lote, para que un renglón nunca diga algo
        distinto de lo que diría este método uno por uno); el `status !=
        'cleared'` se revisa ANTES, sin consulta, para el caso común.
        """
        if clearance is None or clearance.status != "cleared":
            return False
        return clearance.id in LibraryClearanceService._revertible_ids(db, [clearance.id])

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
        tanto), `ClearanceConflict` -se revisa ANTES que «ya está liberado»
        (Ruling R30 #3): re-pinta en vez de pisar su trabajo, aunque la fila
        ya se haya movido a `cleared`.

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
                omitidos.append((cid, f"No existe el registro de la Constancia de no adeudo {cid}."))
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
                         expected_total: Decimal | None = None,
                         expected_status: str | None = None):
        """Registrar pago (Caja): `awaiting_payment` → `cleared/payment`; o,
        sobre una observación CON ADEUDO sin pago, el pago RETENIDO (spec
        2026-10-07 §2): la fila sigue `observed/with_debt` con su pago.

        Cobra el monto CONGELADO de la fila (adeudo + donación); número de
        recibo opcional (<= 40). Por el camino normal cumple el requisito,
        emite la constancia BIB y escribe `library_payment_registered`.
        Retenido: el MISMO evento (`certificate: None`, `held: True`,
        `paid_at`: el corte del día lo cuenta hoy), SIN folio, SIN requisito,
        SIN avisos de «liberada»; aviso `LIBRARY_PAYMENT_HELD` y correo
        `library_payment_held` («tu Constancia se libera cuando Biblioteca
        registre la entrega»). La observación NORMAL sigue sin cobrarse
        (`ClearanceObserved`, D4).

        `expected_total` = el total que Caja confirmó («Registrar pago de
        $X») y `expected_status` el estado de la fila que vio
        (`awaiting_payment` u `observed`): si Biblioteca lo corrigió u
        observó entretanto -o alguien más ya cobró o liberó la fila por otra
        vía-, `ClearanceConflict` (Ruling R30 #3, M1 completo) para re-pintar
        con el monto/estado vigente en vez de un 400 plano; SOLO cuando lo
        visto SÍ coincide (p. ej. un doble clic de «Registrar pago» sobre una
        fila ya cobrada) sigue el `ValueError` normal de abajo.
        """
        clearance = LibraryClearanceService._locked(db, clearance_id)
        process = LibraryClearanceService._admitted_process(db, clearance)
        # Antes que `_check_expected`: los montos de una observada NORMAL
        # siguen en la fila, y aunque coincidan no hay nada que cobrar (spec
        # 2026-10-05 §3.2, Review Focus 1; D4 de 2026-10-07).
        LibraryClearanceService._assert_not_blocking(clearance)
        LibraryClearanceService._check_expected(clearance, expected_status=expected_status,
                                                expected_total=expected_total)
        if LibraryClearanceService._observation_kind(clearance) == OBS_WITH_DEBT:
            # Pago RETENIDO (spec 2026-10-07 §2, D3). En línea y no en un
            # ayudante: el barrido de escritores (`test_mail_writers.py`) pide
            # que la función que escribe `library_payment_registered` sea la
            # que encola `library_cleared`; esta rama sin ese correo la fija
            # una prueba de comportamiento (`RAMAS_SIN_CORREO`).
            if clearance.paid_at is not None:
                raise ValueError("Este pago ya está registrado; la Constancia de no adeudo se "
                                 "libera cuando Biblioteca active el trámite.")
            if not clearance.total_amount:
                raise ValueError("Este caso no tiene monto por cobrar.")
            recibo = LibraryClearanceService._clean_receipt(receipt_number)
            ahora = db_now()
            clearance.paid_by_id = actor_id
            clearance.paid_at = ahora
            clearance.receipt_number = recibo
            clearance.updated_at = ahora
            total = format_amount(clearance.total_amount)
            LibraryClearanceService._log(
                db, process.id, actor_id, "library_payment_registered",
                {"clearance_id": clearance.id, "total": _txt(clearance.total_amount),
                 "receipt": recibo, "certificate": None, "held": True,
                 "paid_at": ahora.isoformat()})

            from itcj2.apps.titulatec.services.notify import notify_student
            notify_student(db, process.student_id, type="LIBRARY_PAYMENT_HELD",
                           title="Caja registró tu pago; falta que Biblioteca active tu trámite",
                           body=(f"Caja registró tu pago de {total}. Tu Constancia de no adeudo "
                                 "de biblioteca se libera cuando Biblioteca registre la entrega: "
                                 f"{clearance.observation_reason}"),
                           process_id=process.id, phase_number=PHASE_COTEJO)
            from itcj2.apps.titulatec.services.student_mail import StudentMail
            StudentMail.library_payment_held(db, process, total=clearance.total_amount,
                                             receipt=recibo)
            db.commit()
            return clearance
        if clearance.status == "pending":
            raise ValueError("Biblioteca todavía no registra el monto de este egresado; "
                             "aún no hay nada que cobrar.")
        if clearance.status == "cleared":
            if clearance.cleared_via == "payment":
                raise ValueError("Este pago ya está registrado.")
            raise ValueError("Esta Constancia de no adeudo ya está liberada; no hay nada que cobrar.")
        if clearance.status != "awaiting_payment":
            raise ValueError(f"Este caso no está por cobrar (estado: {clearance.status}).")
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
                       title="Tu Constancia de no adeudo de biblioteca quedó liberada",
                       body=f"Caja registró tu pago de {format_amount(clearance.total_amount)}.",
                       process_id=process.id, phase_number=PHASE_COTEJO)
        from itcj2.apps.titulatec.services.student_mail import StudentMail
        StudentMail.library_cleared(db, process, via="payment")

        db.commit()
        return clearance

    @staticmethod
    def register_prior(db: Session, clearance_id: int, actor_id: int | None, *,
                       issued_on: date, note: str | None = None, by: str,
                       commit: bool = True, registered_at: datetime | None = None):
        """Constancia previa (D9): `pending|awaiting_payment` → `cleared/prior`.

        El egresado ya pagó y trae su papel: `issued_on` obligatoria, no
        futura y vigente (`>= hoy - PRIOR_VALIDITY_DAYS`: exactamente 365 días
        vale, 366 no). EMITE el folio BIB (`source_ref=_ref(id)`) con
        `semester=previous_semester_key(registered_at or ahora)`: la previa es
        del semestre ANTERIOR al del registro (spec folios 2026-10-05 §3.3);
        `actor_id=None` lo deja sin emisor. `by` ∈ `PRIOR_BY` va al
        payload.

        `registered_at` (spec folios D5, «previa diferida»): la fecha de
        registro que decide el semestre del folio. `None` = «ahora» de este
        método (el registro directo). `PriorClearanceService._apply_library`
        pasa `PriorClearance.created_at` -la IMPORTACIÓN-: una previa
        importada sin proceso y aplicada al inscribirse el egresado, a veces
        semestres después, sigue en el semestre anterior al de su importación.
        SOLO elige el semestre: `updated_at` y el resto siguen siendo «ahora».

        `commit=False` (con `actor_id=None`) lo usa
        `PriorClearanceService.apply_pending` dentro de
        `ImportService.import_rows`: hace `flush()` y deja el commit al
        llamador. Ruling R20 (I2): con la fase 2 ya `approved` -ya pasó su
        cotejo- `ValueError`; ni la importación ni el alta llegan aquí con un
        proceso así (los dos solo aplican sobre procesos abiertos).
        """
        clearance = LibraryClearanceService._locked(db, clearance_id)
        process = LibraryClearanceService._admitted_process(db, clearance)
        LibraryClearanceService._assert_not_observed(clearance)
        if clearance.status not in ("pending", "awaiting_payment"):
            raise ValueError("Esta Constancia de no adeudo ya está liberada.")
        LibraryClearanceService._assert_needs_clearance(db, process)
        if by not in PRIOR_BY:
            raise ValueError(f"Origen de constancia previa desconocido: {by!r}.")
        fecha = LibraryClearanceService._check_prior_date(issued_on)
        nota = LibraryClearanceService._clean_note(note)
        requirement = LibraryClearanceService._library_requirement(db, process.cohort_id)

        ahora = db_now()
        desde = clearance.status
        clearance.status = "cleared"
        clearance.cleared_via = "prior"
        clearance.prior_issued_on = fecha
        clearance.prior_note = nota
        clearance.prior_by_id = actor_id
        clearance.updated_at = ahora

        # Folio de la previa: semestre ANTERIOR al del registro, en la misma
        # transacción (también con `commit=False`, el camino de la importación).
        from itcj2.apps.titulatec.services.certificate_service import (
            CertificateService, previous_semester_key,
        )
        CertificateService.issue(db, kind=CERT_KIND, process=process,
                                 source_ref=_ref(clearance.id), actor_id=actor_id,
                                 semester=previous_semester_key(registered_at or ahora))

        LibraryClearanceService._fulfill(db, process, clearance, requirement, actor_id)
        datos = {"clearance_id": clearance.id, "issued_on": fecha.isoformat(),
                 "note": nota, "by": by, "from_status": desde}
        LibraryClearanceService._log(db, process.id, actor_id,
                                     "library_prior_registered", datos)

        from itcj2.apps.titulatec.services.notify import notify_student
        notify_student(db, process.student_id, type="LIBRARY_CLEARED",
                       title="Tu Constancia de no adeudo de biblioteca quedó liberada",
                       body="Se registró tu constancia de no adeudo previa. Para tu "
                            "cita de cotejo no necesitas llevar nada de biblioteca: tu "
                            "liberación ya quedó registrada para Servicios Escolares.",
                       process_id=process.id, phase_number=PHASE_COTEJO)
        # D9 (spec folios 2026-10-05): el correo de la previa tampoco pide llevar
        # el papel. También desde la importación (`commit=False`): queda en la
        # transacción del lote del llamador.
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
        queda (sigue debiéndolo); se borran pago y recibo de la fila VIGENTE
        (ya no cuenta como «cobrado hoy» para el Registrar/pagar de ahora en
        adelante), se descumple el requisito y se anula la constancia. El
        corte (`day_cut`) del día del cobro original NO cambia (E3,
        invariante 3): este evento entra al corte de HOY como su propio
        renglón negativo. Es una entrada NUEVA a Caja: `ready_at` se vuelve a
        fijar (Ruling R10).

        Pago RETENIDO (observación con adeudo, spec 2026-10-07 §2): la fila
        sigue `observed/with_debt`, sin pago. El MISMO evento
        `library_payment_reverted` (con su total, para el corte de hoy) y
        `certificate: None`; sin anular folio ni descumplir requisito (nunca
        se liberó), sin tocar `ready_at` (nunca salió de Caja) y sin correo
        -el «se revirtió tu Constancia» sería falso-: solo el aviso in-app
        `LIBRARY_PAYMENT_REVERTED`. En línea, como el cobro retenido de
        `register_payment` (barrido de escritores; `RAMAS_SIN_CORREO`). La
        observación NORMAL sigue sin admitirlo (`ClearanceObserved`).
        """
        clearance = LibraryClearanceService._locked(db, clearance_id)
        process = LibraryClearanceService._admitted_process(db, clearance)
        LibraryClearanceService._assert_not_blocking(clearance)
        if LibraryClearanceService._observation_kind(clearance) == OBS_WITH_DEBT:
            if clearance.paid_at is None:
                raise ValueError("Solo se puede revertir un pago registrado.")
            LibraryClearanceService._assert_phase2_open(db, process)
            motivo = LibraryClearanceService._clean_reason(reason)
            previo = {"receipt": clearance.receipt_number,
                      "paid_at": clearance.paid_at.isoformat(),
                      "total": _txt(clearance.total_amount)}
            clearance.paid_by_id = None
            clearance.paid_at = None
            clearance.receipt_number = None
            clearance.updated_at = db_now()
            LibraryClearanceService._log(
                db, process.id, actor_id, "library_payment_reverted",
                {"clearance_id": clearance.id, "reason": motivo, **previo,
                 "certificate": None, "held": True})

            from itcj2.apps.titulatec.services.notify import notify_student
            notify_student(db, process.student_id, type="LIBRARY_PAYMENT_REVERTED",
                           title="Caja revirtió tu pago de la Constancia de no adeudo",
                           body=motivo, process_id=process.id, phase_number=PHASE_COTEJO)
            db.commit()
            return clearance
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
        LibraryClearanceService._assert_not_observed(clearance)
        if clearance.status != "cleared":
            raise ValueError("Esta Constancia de no adeudo no está liberada; no hay nada que revertir.")
        if clearance.cleared_via == "payment":
            raise ValueError("Esta Constancia de no adeudo se liberó con un pago; el pago lo revierte Caja.")
        if clearance.cleared_via == "prior":
            raise ValueError("Esta Constancia de no adeudo se liberó con una constancia previa; "
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
        descumple el requisito y ANULA el folio de la previa (spec folios
        2026-10-05 §3.3, como `revert_clearance`); el número nunca se libera:
        volver a registrar la previa emite uno NUEVO. Una previa sin folio
        (anterior a este código y aún sin backfill) no tiene nada que anular
        y el payload lleva `certificate: None`."""
        clearance = LibraryClearanceService._locked(db, clearance_id)
        process = LibraryClearanceService._admitted_process(db, clearance)
        LibraryClearanceService._assert_not_observed(clearance)
        if clearance.status != "cleared" or clearance.cleared_via != "prior":
            raise ValueError("Solo se puede deshacer una constancia previa registrada.")
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
                                     "library_prior_undone", datos)

        LibraryClearanceService._notify_reverted(db, process, motivo)
        from itcj2.apps.titulatec.services.student_mail import StudentMail
        StudentMail.library_reverted(db, process, reason=motivo, to_status="pending")

        db.commit()
        return clearance

    @staticmethod
    def observe(db: Session, clearance_id: int, *, reason: str, actor_id: int,
                kind: str = OBS_BLOCKING, debt_amount: Decimal | None = None):
        """Observar (Biblioteca, motivo): `pending|awaiting_payment` →
        `observed`; desde `observed` ACTUALIZA la observación vigente (como
        `SurveyReviewService.reject`). Spec 2026-10-05 §3.2, D1, y spec
        2026-10-07 §2 (D3/D4) para el `kind`.

        `kind` (`OBS_BLOCKING` por omisión: la observación de siempre):

        * `OBS_BLOCKING`: detiene todo. Si estaba en Caja (`awaiting_payment`
          o una `with_debt` sin pago) limpia `ready_at` -sale de «Por cobrar»
          y de los recordatorios de pago- y conserva los montos. Con un pago
          RETENIDO, `ValueError` (`_MSG_PAGO_RETENIDO`): la normal no deja
          revertir ese pago.
        * `OBS_WITH_DEBT`: `debt_amount` obligatorio, montos congelados con la
          MISMA lógica que Registrar (`_check_amount` + `_frozen_donation`;
          total = adeudo + donación vigente; total 0 → `ValueError`, «usa la
          observación normal»). Entra a Caja: `ready_at` = ahora si no estaba
          ya ahí (desde `awaiting_payment` o una `with_debt` conserva su
          lugar en la fila). Firma de Biblioteca (`library_by_id`/`_at`) como
          al registrar; la nota de Registrar no se toca. Con un pago RETENIDO
          solo cambia el motivo: `debt_amount` `None` o el mismo adeudo; otro
          → `ValueError`.

        Guardas, todas antes de mutar: proceso admitido (`active`/`on_hold`),
        no `cleared` (primero se revierte), fase 2 sin aprobar (Ruling R20:
        quien ya pasó su cotejo no tiene trámite), `kind` del dominio y motivo
        1..`REASON_MAX` tras recortar. El requisito no cambia (no estaba
        cumplido). Evento `library_observed {reason, from_status, kind,
        from_kind?, debt/donation/total?}`, aviso `LIBRARY_OBSERVED` y correo
        `library_observed` (con el tipo); UN commit."""
        clearance = LibraryClearanceService._locked(db, clearance_id)
        process = LibraryClearanceService._admitted_process(db, clearance)
        if clearance.status == "cleared":
            raise ValueError("Esta Constancia de no adeudo ya está liberada; primero revierte la "
                             "liberación y después regístrale observaciones.")
        if clearance.status not in ("pending", "awaiting_payment", "observed"):
            raise ValueError(f"Este caso no se puede observar (estado: {clearance.status}).")
        if kind not in (OBS_BLOCKING, OBS_WITH_DEBT):
            raise ValueError(f"Tipo de observación desconocido: {kind!r}.")
        LibraryClearanceService._assert_needs_clearance(db, process)
        motivo = LibraryClearanceService._clean_reason(reason)

        desde = clearance.status
        de_tipo = LibraryClearanceService._observation_kind(clearance)
        retenido = LibraryClearanceService.payment_held(clearance)
        # ¿Ya estaba en Caja? (su `ready_at` es la entrada vigente, Ruling R10)
        en_caja = desde == "awaiting_payment" or de_tipo == OBS_WITH_DEBT
        montos = None
        if kind == OBS_BLOCKING:
            if retenido:
                raise ValueError(_MSG_PAGO_RETENIDO)
        elif retenido:
            if (debt_amount is not None
                    and _check_amount(debt_amount) != clearance.debt_amount):
                raise ValueError(_MSG_PAGO_RETENIDO)
        else:
            if debt_amount is None:
                raise ValueError("Escribe el monto del adeudo.")
            debt = _check_amount(debt_amount)
            donation = LibraryClearanceService._frozen_donation(process)
            if debt + donation == 0:
                raise ValueError(_MSG_SIN_MONTO)
            montos = (debt, donation, debt + donation)

        ahora = db_now()
        clearance.status = "observed"
        clearance.observation_kind = kind
        if kind == OBS_BLOCKING and en_caja:
            clearance.ready_at = None       # sale de «Por cobrar» y de los recordatorios
        if montos is not None:
            clearance.debt_amount, clearance.donation_amount, clearance.total_amount = montos
            clearance.library_by_id = actor_id
            clearance.library_at = ahora
            if not en_caja:
                clearance.ready_at = ahora  # entra a Caja (Ruling R10)
        clearance.observation_reason = motivo
        clearance.observed_by_id = actor_id
        clearance.observed_at = ahora
        clearance.updated_at = ahora

        datos = {"clearance_id": clearance.id, "reason": motivo, "from_status": desde,
                 "kind": kind}
        if de_tipo is not None:
            datos["from_kind"] = de_tipo
        if kind == OBS_WITH_DEBT:
            datos.update(LibraryClearanceService._amounts(clearance))
        LibraryClearanceService._log(db, process.id, actor_id, "library_observed", datos)

        if kind == OBS_WITH_DEBT:
            titulo = "Biblioteca registró una observación con adeudo en tu Constancia de no adeudo"
            if clearance.paid_at is not None:
                cuerpo = (f"{motivo}. Tu pago de {format_amount(clearance.total_amount)} ya "
                          "está registrado en Caja; tu Constancia de no adeudo se libera "
                          "cuando Biblioteca registre la entrega.")
            else:
                cuerpo = (f"{motivo}. Adeudo: {format_amount(clearance.total_amount)}. Puedes "
                          "pagar en Caja y entregar en Biblioteca en la misma visita; tu "
                          "Constancia de no adeudo se libera cuando Biblioteca registre la "
                          "entrega.")
        else:
            titulo = "Biblioteca registró observaciones en tu Constancia de no adeudo"
            cuerpo = motivo
        from itcj2.apps.titulatec.services.notify import notify_student
        notify_student(db, process.student_id, type="LIBRARY_OBSERVED", title=titulo,
                       body=cuerpo, process_id=process.id, phase_number=PHASE_COTEJO)
        from itcj2.apps.titulatec.services.student_mail import StudentMail
        StudentMail.library_observed(db, process, reason=motivo, kind=kind)

        db.commit()
        return clearance

    @staticmethod
    def reenable(db: Session, clearance_id: int, *, actor_id: int):
        """Activar (Biblioteca; antes «Rehabilitar»). Tres ramas según la
        observación vigente (spec 2026-10-07 §2):

        * `blocking` → `pending` («Por revisar»), SIEMPRE (D2), con los
          montos que tuviera -precargan el formulario de Registrar-.
        * `with_debt` SIN pago → `awaiting_payment`: Biblioteca ya recibió lo
          que debía entregar y Caja cobra por el camino normal (`ready_at` =
          ahora: entrada nueva a Caja, Ruling R10; montos congelados intactos).
        * `with_debt` CON pago retenido → `cleared/payment`
          (`_release_held_payment`: folio, requisito, avisos y correo de
          «liberada», evento `library_cleared_after_observation`).

        Mismas guardas de proceso y fase 2 que `observe`. Limpia la
        observación vigente y su tipo; en las dos primeras ramas el motivo
        queda en el payload de `library_reenabled {previous_reason, kind,
        to_status}`, aviso `LIBRARY_REENABLED` y correo `library_reenabled`
        (con `to_status`: hacia Caja dice cuánto pagar). UN commit."""
        clearance = LibraryClearanceService._locked(db, clearance_id)
        process = LibraryClearanceService._admitted_process(db, clearance)
        if clearance.status != "observed":
            raise ValueError("Este caso no tiene observaciones de Biblioteca; no hay nada "
                             "que activar.")
        LibraryClearanceService._assert_needs_clearance(db, process)

        tipo = LibraryClearanceService._observation_kind(clearance)
        if LibraryClearanceService.payment_held(clearance):
            requirement = LibraryClearanceService._library_requirement(db, process.cohort_id)
            LibraryClearanceService._release_held_payment(db, clearance, process,
                                                          requirement, actor_id)
            db.commit()
            return clearance

        previo = clearance.observation_reason
        ahora = db_now()
        hacia = "awaiting_payment" if tipo == OBS_WITH_DEBT else "pending"
        clearance.status = hacia
        if hacia == "awaiting_payment":
            clearance.ready_at = ahora      # entrada nueva a Caja (Ruling R10)
        LibraryClearanceService._clear_observation(clearance)
        clearance.updated_at = ahora

        LibraryClearanceService._log(db, process.id, actor_id, "library_reenabled",
                                     {"clearance_id": clearance.id,
                                      "previous_reason": previo, "kind": tipo,
                                      "to_status": hacia})

        if hacia == "awaiting_payment":
            cuerpo = (f"Ya puedes pasar a Caja (Recursos Financieros) a pagar "
                      f"{format_amount(clearance.total_amount)} con tu número de control; no "
                      "necesitas cita. Con ese pago se libera tu Constancia de no adeudo de "
                      "biblioteca.")
        else:
            cuerpo = ("Ya puedes continuar con tu Constancia de no adeudo de "
                      "biblioteca: el Centro de Información volverá a revisar "
                      "tu caso.")
        from itcj2.apps.titulatec.services.notify import notify_student
        notify_student(db, process.student_id, type="LIBRARY_REENABLED",
                       title="Biblioteca activó tu trámite", body=cuerpo,
                       process_id=process.id, phase_number=PHASE_COTEJO)
        from itcj2.apps.titulatec.services.student_mail import StudentMail
        StudentMail.library_reenabled(db, process, to_status=hacia)

        db.commit()
        return clearance

    @staticmethod
    def _release_held_payment(db: Session, clearance, process, requirement,
                              actor_id: int) -> None:
        """«Activar» una observación con adeudo cuyo pago ya está RETENIDO
        (spec 2026-10-07 §2): → `cleared/payment`. Lo mismo que hoy hace
        `register_payment` al liberar -requisito (`_fulfill`), folio BIB
        (`CertificateService.issue`), aviso `LIBRARY_CLEARED` y correo
        `library_cleared(via="payment")`- con su PROPIO evento
        `library_cleared_after_observation` (`library_payment_registered` ya
        lo escribió el cobro; repetirlo lo contaría dos veces en el corte del
        día). El pago (`paid_*`, `receipt_number`) se queda: es el de Caja.
        Sin commit (lo hace `reenable`)."""
        previo = clearance.observation_reason
        ahora = db_now()
        clearance.status = "cleared"
        clearance.cleared_via = "payment"
        LibraryClearanceService._clear_observation(clearance)
        clearance.updated_at = ahora

        LibraryClearanceService._fulfill(db, process, clearance, requirement, actor_id)
        from itcj2.apps.titulatec.services.certificate_service import CertificateService
        cert = CertificateService.issue(db, kind=CERT_KIND, process=process,
                                        source_ref=_ref(clearance.id), actor_id=actor_id)
        LibraryClearanceService._log(
            db, process.id, actor_id, "library_cleared_after_observation",
            {"clearance_id": clearance.id, "previous_reason": previo,
             "total": _txt(clearance.total_amount), "receipt": clearance.receipt_number,
             "paid_at": clearance.paid_at.isoformat() if clearance.paid_at else None,
             "certificate": cert.number})

        from itcj2.apps.titulatec.services.notify import notify_student
        notify_student(db, process.student_id, type="LIBRARY_CLEARED",
                       title="Tu Constancia de no adeudo de biblioteca quedó liberada",
                       body=(f"Biblioteca registró la entrega y tu pago de "
                             f"{format_amount(clearance.total_amount)} ya estaba registrado "
                             "en Caja."),
                       process_id=process.id, phase_number=PHASE_COTEJO)
        from itcj2.apps.titulatec.services.student_mail import StudentMail
        StudentMail.library_cleared(db, process, via="payment")

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
        """Conteo por pestaña: las 4 llaves de `LIBRARY_STATUSES` siempre
        presentes (`observed` = «Con observaciones», spec 2026-10-05 §3.5). Mismo criterio que `list_for_inbox` (búsqueda `q` por nombre
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
            query = (query.join(User, User.id == TitulationProcess.student_id)
                     .filter(LibraryClearanceService._search_clause(texto)))
        out = {estado: 0 for estado in LIBRARY_STATUSES}
        for estado, total in query.group_by(LibraryClearance.status).all():
            if estado in out:
                out[estado] = total
        return out

    @staticmethod
    def list_for_inbox(db: Session, *, status: str, q: str | None = None,
                       page: int = 1, per_page: int = PAGE_SIZE,
                       admitted_only: bool = False) -> Page:
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
        * `observed` («Con observaciones», spec 2026-10-05 §3.2): lo observado
          más reciente primero (`observed_at DESC, id DESC`); SOLO procesos
          admitidos (lista y contador): `reenable` lo exige, así que un
          proceso revocado/terminado no se queda aquí sin acciones. «Por revisar» NUNCA lo
          incluye: es otro `status`.
        * `cleared` («Liberados»): lo liberado más reciente primero
          (`updated_at`); SIN este filtro -- conserva el historial de lo ya
          liberado aunque el proceso se haya revocado después.

        `can_revert` y el número de constancia vigente se calculan EN LOTE (una
        consulta cada uno por página), nunca por fila. Devuelve
        un `Page` cuyos `items` son los dicts de `_rows`.
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
        elif status == "observed":
            # Solo procesos admitidos: uno revocado/terminado estando observado
            # no se queda en la pestaña de trabajo sin acciones posibles.
            query = query.filter(TitulationProcess.status.in_(ADMITTED_PROCESS_STATUSES))
        if status == "pending":
            query = query.order_by(TitulationProcess.created_at.asc(),
                                   TitulationProcess.id.asc())
        elif status == "awaiting_payment":
            query = query.order_by(LibraryClearance.ready_at.asc(),
                                   LibraryClearance.id.asc())
        elif status == "observed":
            query = query.order_by(LibraryClearance.observed_at.desc(),
                                   LibraryClearance.id.desc())
        else:
            query = query.order_by(LibraryClearance.updated_at.desc(),
                                   LibraryClearance.id.desc())

        pagina = paginate_query(query, page, per_page)
        return Page(items=LibraryClearanceService._rows(db, pagina.items),
                    total=pagina.total, page=pagina.page, per_page=pagina.per_page)

    @staticmethod
    def list_for_cashier(db: Session, *, q: str | None = None, page: int = 1,
                         per_page: int = PAGE_SIZE) -> Page:
        """«Por cobrar» de Caja (spec 2026-10-01 §4.8 + spec 2026-10-07 §2):
        lo que Caja puede cobrar AHORA, `_cashier_due_clause` -`awaiting_
        payment` y las observaciones CON ADEUDO sin pago, de procesos
        admitidos (Ruling R9)-. FIFO por `ready_at` (la entrada vigente a
        Caja; una con adeudo la fija al observar). La observación NORMAL no
        aparece (D4). `q` acota por nombre/control (las pruebas aíslan con
        él; la bandeja no lo usa: su buscador va por `search`). Filas de
        `_rows`, con `observation_kind`/`observation_reason` para la
        píldora."""
        from itcj2.apps.titulatec.models import LibraryClearance

        page = max(1, int(page))
        per_page = max(1, int(per_page))
        query = (LibraryClearanceService._inbox_query(db, q)
                 .filter(LibraryClearanceService._cashier_due_clause())
                 .order_by(LibraryClearance.ready_at.asc().nullslast(),
                           LibraryClearance.id.asc()))
        pagina = paginate_query(query, page, per_page)
        return Page(items=LibraryClearanceService._rows(db, pagina.items),
                    total=pagina.total, page=pagina.page, per_page=pagina.per_page)

    @staticmethod
    def cashier_due_count(db: Session, q: str | None = None) -> int:
        """Contador de «Por cobrar» de Caja: el MISMO predicado que
        `list_for_cashier` (nunca anuncia lo que la tabla no muestra)."""
        from itcj2.apps.titulatec.models import LibraryClearance, TitulationProcess
        from itcj2.core.models.user import User

        query = (db.query(func.count(LibraryClearance.id))
                 .join(TitulationProcess, TitulationProcess.id == LibraryClearance.process_id)
                 .filter(LibraryClearanceService._cashier_due_clause()))
        texto = (q or "").strip()
        if texto:
            query = (query.join(User, User.id == TitulationProcess.student_id)
                     .filter(LibraryClearanceService._search_clause(texto)))
        return int(query.scalar() or 0)

    @staticmethod
    def _cashier_due_clause():
        """SQL de «Caja puede cobrarlo ahora», sobre `LibraryClearance` Y
        `TitulationProcess` (las dos en el FROM): proceso admitido (Ruling R9)
        y la fila `awaiting_payment`, u `observed/with_debt` SIN pago (spec
        2026-10-07 §2: el pago queda retenido). La `observed/blocking` -y la
        NULL vieja, que se lee igual- no entra (D4)."""
        from sqlalchemy import and_

        from itcj2.apps.titulatec.models import LibraryClearance, TitulationProcess
        return and_(
            TitulationProcess.status.in_(ADMITTED_PROCESS_STATUSES),
            or_(LibraryClearance.status == "awaiting_payment",
                and_(LibraryClearance.status == "observed",
                     LibraryClearance.observation_kind == OBS_WITH_DEBT,
                     LibraryClearance.paid_at.is_(None))))

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
    def day_cut(db: Session, day: date) -> dict:
        """Corte del día de Caja (E3, spec `2026-10-02-titulatec-constancias-
        y-pendientes-design.md` §3.6): FIJO una vez cerrado el día -- depende
        SOLO de `ProcessEvent` con `created_at` en ese día (invariante 3: los
        eventos no se editan ni se borran), así que una reversa de OTRO día
        nunca mueve el corte de HOY. Reemplaza a `paid_on` (que leía la fila
        VIGENTE por `paid_at`: una reversa posterior la bajaba en silencio,
        incluso en el corte de un día YA cerrado).

        Fuente: la bitácora (`titulatec_process_events`), del más reciente al
        más viejo. `library_payment_registered` es un COBRO (+
        `payload.total`); `library_payment_reverted` es una REVERSA (−
        `payload.total`, con `payload.reason` y `payload.paid_at` del cobro
        que revirtió). Devuelve `{"rows", "charged", "reverted", "net"}`:
        `charged`/`reverted` son sumas NO negativas; `net = charged -
        reverted` sí puede ser negativo (un día con solo reversas de cobros de
        OTRO día). Todo `Decimal` a centavos.

        Cada renglón: `id` (el del evento: la plantilla lo usa como id
        estable del renglón, `caja-mov-{id}`), `kind`
        (`"charge"`|`"reversal"`), `at`, `clearance_id`, `student`,
        `control`, `program`, `amount` CON SIGNO (positivo cobro,
        negativo reversa), `receipt`, `actor` (quién lo hizo, `None` sin
        actor), `reason`/`original_paid_at` (SOLO reversas; `None` en
        cobros), `certificate` (el folio que ESE evento trae en su payload --
        el histórico, no necesariamente el vigente), `held` (cobro RETENIDO
        de una observación con adeudo, spec 2026-10-07 §2) y
        `can_revert_here`.

        Tolerante a payloads viejos de dev incompletos (nunca truena): un
        `total` ausente, que no parsea o no finito (`NaN`/`sNaN`/`Infinity`
        -- `_event_amount`) cuenta como `Decimal("0.00")` -- entra así a
        `charged`/`reverted` (no distorsiona el corte) y, como un
        cobro/reversa REAL nunca tiene total 0 (`register_payment` solo corre
        sobre un total > 0), un `amount` en cero es por construcción ese
        dato viejo: la plantilla lo pinta «—» (un `Decimal` en 0 es «falsy»).

        `can_revert_here` (SOLO en cobros; las reversas nunca ofrecen
        «Revertir…»): el folio de ESE cobro sigue siendo la constancia
        VIGENTE de su fila **y** la fila es revertible AHORA (`_revertible_
        ids`, el mismo predicado batched que usa `_rows`: liberada, proceso
        admitido, fase 2 sin aprobar). En LOTE -- hasta dos consultas de
        folios vigentes (`CertificateService.print_status_map`, que hace como
        máximo 2 por llamada) y una de `_revertible_ids`, nunca una por
        renglón. Dos cobros de la MISMA fila (revertido y vuelto a cobrar)
        solo pueden coincidir con el folio vigente en el MÁS RECIENTE -- cada
        cobro saca un folio nuevo (§5 invariante 5 de la spec de ayer).

        Cobro RETENIDO (observación con adeudo, spec 2026-10-07 §2): su
        evento es el MISMO `library_payment_registered`, así que cuenta el
        día que se cobró; trae `certificate: None`, `held: True` y su
        `paid_at`. Activarlo después escribe `library_cleared_after_
        observation`, que este corte NO lee (sin doble cobro). Sin folio que
        comparar, su `can_revert_here` es: el `paid_at` del payload sigue
        siendo el pago VIGENTE de la fila y ese pago se puede revertir ahora
        (retenido, o ya liberado por «Activar»; proceso admitido, fase 2 sin
        aprobar) -- una consulta más por corte (`_payment_revertible_paid_at`),
        solo si hay cobros retenidos."""
        from itcj2.apps.titulatec.models import ProcessEvent, TitulationProcess
        from itcj2.apps.titulatec.services.certificate_service import CertificateService
        from itcj2.core.models.program import Program
        from itcj2.core.models.user import User
        from sqlalchemy.orm import aliased

        if isinstance(day, datetime):
            day = day.date()
        inicio = datetime.combine(day, time.min)
        fin = inicio + timedelta(days=1)

        Actor = aliased(User)
        filas = (
            db.query(ProcessEvent, TitulationProcess, User, Program, Actor)
            .join(TitulationProcess, TitulationProcess.id == ProcessEvent.process_id)
            .join(User, User.id == TitulationProcess.student_id)
            .outerjoin(Program, Program.id == TitulationProcess.program_id)
            .outerjoin(Actor, Actor.id == ProcessEvent.actor_id)
            .filter(ProcessEvent.event_type.in_(
                ("library_payment_registered", "library_payment_reverted")),
                    ProcessEvent.created_at >= inicio,
                    ProcessEvent.created_at < fin)
            .order_by(ProcessEvent.created_at.desc(), ProcessEvent.id.desc())
            .all()
        )
        if not filas:
            cero = Decimal("0.00")
            return {"rows": [], "charged": cero, "reverted": cero, "net": cero}

        charge_ids = sorted({
            (event.payload or {}).get("clearance_id")
            for event, *_ in filas
            if event.event_type == "library_payment_registered"
            and (event.payload or {}).get("clearance_id") is not None
        })
        folio_vigente: dict[int, str | None] = {}
        revertibles: set[int] = set()
        if charge_ids:
            impresion = CertificateService.print_status_map(
                db, [_ref(cid) for cid in charge_ids])
            folio_vigente = {cid: (impresion.get(_ref(cid)) or {}).get("number")
                             for cid in charge_ids}
            revertibles = LibraryClearanceService._revertible_ids(db, charge_ids)
        retenidos_ids = sorted({
            (event.payload or {}).get("clearance_id")
            for event, *_ in filas
            if event.event_type == "library_payment_registered"
            and (event.payload or {}).get("held")
            and (event.payload or {}).get("clearance_id") is not None
        })
        pago_vigente = (LibraryClearanceService._payment_revertible_paid_at(db, retenidos_ids)
                        if retenidos_ids else {})

        rows = []
        charged = Decimal("0.00")
        reverted = Decimal("0.00")
        for event, _process, student, program, actor in filas:
            payload = event.payload or {}
            es_cobro = event.event_type == "library_payment_registered"
            monto = LibraryClearanceService._event_amount(payload.get("total"))
            clearance_id = payload.get("clearance_id")
            certificate = payload.get("certificate")
            rows.append({
                "id": event.id,
                "kind": "charge" if es_cobro else "reversal",
                "at": event.created_at,
                "clearance_id": clearance_id,
                "student": student.full_name,
                "control": student.control_number or "",
                "program": program.name if program else "",
                "amount": monto if es_cobro else -monto,
                "receipt": payload.get("receipt"),
                "actor": actor.full_name if actor else None,
                "reason": None if es_cobro else payload.get("reason"),
                "original_paid_at": (None if es_cobro else
                                     LibraryClearanceService._parse_event_iso(
                                         payload.get("paid_at"))),
                "certificate": certificate,
                # Cobro RETENIDO de una observación con adeudo (spec 2026-10-07).
                "held": bool(es_cobro and payload.get("held")),
                "can_revert_here": bool(
                    es_cobro and clearance_id is not None
                    and ((clearance_id in revertibles
                          and certificate is not None
                          and folio_vigente.get(clearance_id) == certificate)
                         or (payload.get("held")
                             and pago_vigente.get(clearance_id) is not None
                             and payload.get("paid_at")
                             == pago_vigente[clearance_id].isoformat()))),
            })
            if es_cobro:
                charged += monto
            else:
                reverted += monto

        return {"rows": rows, "charged": charged.quantize(_CENT),
               "reverted": reverted.quantize(_CENT),
               "net": (charged - reverted).quantize(_CENT)}

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
            raise LookupError(f"No existe el registro de la Constancia de no adeudo {clearance_id}.")
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
        pregunta aquí.

        Ruling R30 #3 (re-revisión de la ola final, M1 completo): `_check_
        expected` corre ANTES que «ya está liberado» -si el llamador mandó
        `expected_status`/`expected_total` y ya no coinciden (otra persona
        movió la fila mientras tanto), es SIEMPRE `ClearanceConflict` -re-
        pinta-, nunca el 400 plano de abajo, sin importar a QUÉ estado se
        movió. Sin expectativa (`None`) este chequeo es no-op y el orden no
        cambia nada."""
        process = LibraryClearanceService._admitted_process(db, clearance)
        LibraryClearanceService._check_expected(
            clearance, expected_status=expected_status, expected_total=expected_total)
        LibraryClearanceService._assert_not_observed(clearance)
        if clearance.status not in ("pending", "awaiting_payment"):
            raise ValueError("Esta Constancia de no adeudo ya está liberada; para cambiarla, primero "
                             "revierte la liberación.")
        if phase2_approved is None:
            phase2_approved = LibraryClearanceService._phase2_approved(db, process.id)
        if phase2_approved:
            raise ValueError(_MSG_COTEJO_YA_LIBERADO)
        debt = _check_amount(debt_amount)
        nota = LibraryClearanceService._clean_note(note)
        donation = LibraryClearanceService._frozen_donation(process)
        return {"process": process, "debt": debt, "donation": donation,
                "total": debt + donation, "note": nota,
                "correcting": clearance.status == "awaiting_payment"}

    @staticmethod
    def _frozen_donation(process) -> Decimal:
        """La donación voluntaria de libro VIGENTE de la convocatoria del
        proceso, a centavos, para CONGELARLA en la fila (D16/D19): la usan
        Registrar/Corregir y la observación con adeudo (spec 2026-10-07 §2,
        «misma lógica que Registrar»). Sin capturar -> `ValueError` (D19)."""
        cohort = process.cohort
        if cohort is None or cohort.book_donation_amount is None:
            nombre = cohort.name if cohort is not None else "de este egresado"
            raise ValueError(
                f"La convocatoria {nombre} no tiene capturada la donación voluntaria "
                "de libro; pide a Servicios Escolares que la capture.")
        return Decimal(cohort.book_donation_amount).quantize(_CENT)

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
                       title="Tu Constancia de no adeudo de biblioteca quedó liberada",
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
        """¿Sigue la fila como la vio el usuario? (Review Focus #1). Si no,
        `ClearanceConflict` (Ruling R24): las rutas re-pintan con el estado
        vigente en vez de responder 400.

        `expected_total` NO pasa por `_check_amount` (Ruling R9, spec §4.8):
        ese tope (`AMOUNT_MAX`) topa lo que SE TECLEA (`debt_amount`), pero
        `expected_total` es la SUMA ya hecha de adeudo + donación que la
        bandeja le mostró al usuario -un adeudo al tope más la donación
        fácilmente la supera- así que aquí solo se exige forma mínima
        (`_check_total_shape`: finito y >= 0), nunca el tope. Un total mal
        formado NO es un choque: es un `ValueError` cualquiera (400).
        """
        if expected_status is not None and clearance.status != expected_status:
            actual = _STATUS_LABELS.get(clearance.status, clearance.status)
            raise ClearanceConflict(
                f"Otra persona ya movió este caso: ahora está «{actual}». "
                "Revisa esa pestaña y vuelve a intentarlo.")
        if expected_total is not None:
            esperado = LibraryClearanceService._check_total_shape(expected_total)
            actual = clearance.total_amount
            if actual is None or Decimal(actual) != esperado:
                detalle = f": ahora es {format_amount(actual)}" if actual is not None else ""
                raise ClearanceConflict(f"El monto cambió mientras lo revisabas{detalle}. "
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
    def _event_amount(raw) -> Decimal:
        """`payload.total` (texto) de un evento de Caja -> `Decimal` a
        centavos, para `day_cut`. Ausente, que no parsea, no finito (`NaN`,
        `sNaN`, `Infinity`/`-Infinity`) o negativo -> `Decimal("0.00")` --
        dato viejo de dev; nunca truena. `is_finite()` se revisa DENTRO del
        `try` y ANTES de cualquier comparación: `Decimal(...)` parsea
        `"NaN"` sin error (`sNaN`/`Infinity` sí truenan ahí, pero un `NaN`
        plano no), y comparar un `Decimal('NaN')` con `>= 0` o `< 0` lanza
        `InvalidOperation` -- revisar `is_finite()` primero evita las dos
        rutas de crash. Un cobro/reversa REAL nunca tiene total 0
        (`register_payment` solo corre con total > 0), así que 0 identifica
        por construcción un payload incompleto."""
        if raw in (None, ""):
            return Decimal("0.00")
        try:
            monto = Decimal(str(raw))
            if not monto.is_finite() or monto < 0:
                return Decimal("0.00")
            return monto.quantize(_CENT)
        except (InvalidOperation, ValueError, TypeError):
            return Decimal("0.00")

    @staticmethod
    def _parse_event_iso(raw) -> datetime | None:
        """`payload.paid_at` (ISO) de una reversa -> `datetime`, o `None` si
        falta o no parsea (dato viejo de dev; `day_cut` nunca truena)."""
        if not raw:
            return None
        try:
            return datetime.fromisoformat(raw)
        except (TypeError, ValueError):
            return None

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
    def _revertible_ids(db: Session, clearance_ids) -> set[int]:
        """`can_revert` de VARIAS filas en UNA sola consulta (nunca una por
        renglón): liberada (`cleared`), su proceso sigue admitido
        (`active`/`on_hold`) y la fase 2 todavía no está `approved` -- el
        MISMO predicado que `can_revert`, que delega aquí con un solo id.
        `_rows` y `day_cut` son los únicos que necesitan «revertible» de
        MUCHAS filas a la vez; un id que no aparece en el resultado no es
        revertible (incluido uno que no existe -- falla cerrado)."""
        from sqlalchemy import and_

        from itcj2.apps.titulatec.models import (
            LibraryClearance, ProcessPhase, TitulationProcess,
        )

        ids = list(clearance_ids)
        if not ids:
            return set()
        filas = (
            db.query(LibraryClearance.id, LibraryClearance.status,
                     TitulationProcess.status, ProcessPhase.status)
            .join(TitulationProcess, TitulationProcess.id == LibraryClearance.process_id)
            .outerjoin(ProcessPhase,
                       and_(ProcessPhase.process_id == TitulationProcess.id,
                            ProcessPhase.phase_number == PHASE_COTEJO))
            .filter(LibraryClearance.id.in_(ids))
            .all()
        )
        return {
            cid for cid, estado_clearance, estado_proceso, estado_fase2 in filas
            if estado_clearance == "cleared"
            and estado_proceso in ADMITTED_PROCESS_STATUSES
            and estado_fase2 != "approved"
        }

    @staticmethod
    def _payment_revertible_paid_at(db: Session, clearance_ids) -> dict[int, datetime]:
        """`{id: paid_at}` de las filas cuyo pago VIGENTE Caja puede revertir
        ahora -RETENIDO (`observed/with_debt` con pago) o ya liberado por pago
        (`cleared/payment`, p. ej. tras «Activar»)-, con el proceso admitido y
        la fase 2 sin aprobar: el mismo predicado de proceso y fase 2 que
        `_revertible_ids`, en UNA consulta. Para el pago retenido (spec
        2026-10-07 §2), que no tiene folio que comparar: `_rows`
        (`can_revert_held`) y `day_cut` (su `paid_at` contra el del cobro)."""
        from sqlalchemy import and_

        from itcj2.apps.titulatec.models import (
            LibraryClearance, ProcessPhase, TitulationProcess,
        )

        ids = list(clearance_ids)
        if not ids:
            return {}
        filas = (
            db.query(LibraryClearance.id, LibraryClearance.status,
                     LibraryClearance.cleared_via, LibraryClearance.observation_kind,
                     LibraryClearance.paid_at, TitulationProcess.status, ProcessPhase.status)
            .join(TitulationProcess, TitulationProcess.id == LibraryClearance.process_id)
            .outerjoin(ProcessPhase,
                       and_(ProcessPhase.process_id == TitulationProcess.id,
                            ProcessPhase.phase_number == PHASE_COTEJO))
            .filter(LibraryClearance.id.in_(ids))
            .all()
        )
        return {
            cid: pagado
            for cid, estado, via, tipo, pagado, estado_proceso, estado_fase2 in filas
            if pagado is not None
            and ((estado == "observed" and tipo == OBS_WITH_DEBT)
                 or (estado == "cleared" and via == "payment"))
            and estado_proceso in ADMITTED_PROCESS_STATUSES
            and estado_fase2 != "approved"
        }

    @staticmethod
    def _assert_phase2_open(db: Session, process) -> None:
        if LibraryClearanceService._phase2_approved(db, process.id):
            raise ValueError("La fase 2 de este egresado ya fue liberada; "
                             "ya no se puede revertir.")

    @staticmethod
    def _assert_not_observed(clearance) -> None:
        """Con «Con observaciones» solo Observar y Activar aplican (spec
        2026-10-05 §3.2): todo lo demás responde `_MSG_OBSERVADO`. Para los
        DOS tipos: Registrar/Corregir, el lote, la constancia previa y las
        reversas de liberación. El pago de Caja y su reversa usan
        `_assert_not_blocking` (con adeudo, Caja sí cobra, spec 2026-10-07)."""
        if clearance.status == "observed":
            raise ClearanceObserved(_MSG_OBSERVADO)

    @staticmethod
    def _assert_not_blocking(clearance) -> None:
        """La observación NORMAL (`blocking`, D4) sigue bloqueando el pago de
        Caja y su reversa con `_MSG_OBSERVADO`; la CON ADEUDO no (la decide
        quien llama: cobro y reversa RETENIDOS)."""
        if LibraryClearanceService._observation_kind(clearance) == OBS_BLOCKING:
            raise ClearanceObserved(_MSG_OBSERVADO)

    @staticmethod
    def _observation_kind(clearance) -> str | None:
        """Tipo EFECTIVO de la observación vigente: `None` sin fila o fuera de
        `observed`; dentro, `observation_kind` y, si viene NULL (dato
        anterior a `tt20261007a` o una fábrica de pruebas), `OBS_BLOCKING`
        (falla cerrado: lo trata como la observación que detiene todo)."""
        if clearance is None or clearance.status != "observed":
            return None
        return clearance.observation_kind or OBS_BLOCKING

    @staticmethod
    def _clear_observation(clearance) -> None:
        """Sale de «Con observaciones»: limpia la observación vigente y su
        tipo (el historial queda en los eventos). No toca `status`."""
        clearance.observation_reason = None
        clearance.observed_by_id = None
        clearance.observed_at = None
        clearance.observation_kind = None

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
                       title="Se revirtió tu Constancia de no adeudo de biblioteca",
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
        muestra. Su gemela en Python, para UN proceso, es `reviewable` (el
        correo de la reversión a Biblioteca); las dos parten los mismos
        casos: las dos recorren la misma tabla de `TestRevisable`
        (`test_admitido_y_sin_la_fase_2_aprobada` para `reviewable`,
        `test_la_clausula_sql_parte_los_mismos_casos` para esta, con y sin
        fila de no adeudo; `test_library_clearance_service.py`)."""
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
        por_revisar = and_(
            or_(LibraryClearance.status != "pending",
                LibraryClearanceService._reviewable_clause()),
            # «Con observaciones»: solo admitidos (igual que su lista).
            or_(LibraryClearance.status != "observed",
                TitulationProcess.status.in_(ADMITTED_PROCESS_STATUSES)))
        if not admitted_only:
            return por_revisar
        return and_(por_revisar,
                    or_(LibraryClearance.status != "awaiting_payment",
                        TitulationProcess.status.in_(ADMITTED_PROCESS_STATUSES)))

    @staticmethod
    def _search_clause(texto: str):
        """`ILIKE` de nombre completo o número de control (m09): un solo
        lugar para `counts_by_status` y `_inbox_query` -- antes cada uno traía
        su propia copia literal del `or_(...)`, con riesgo de que el contador
        de una pestaña y su lista divergieran al tocar solo una. `texto` ya
        viene recortado y no vacío -- lo valida el llamador."""
        from itcj2.core.models.user import User
        from itcj2.apps.titulatec.utils.paging import like_pattern
        patron = like_pattern(texto)
        return or_(User.full_name.ilike(patron, escape="\\"),
                   User.control_number.ilike(patron, escape="\\"))

    @staticmethod
    def _inbox_query(db: Session, q: str | None = None):
        """Fila + proceso + egresado + carrera + convocatoria, con la búsqueda
        `q` (ILIKE sobre nombre completo o número de control, `_search_clause`)
        ya aplicada."""
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
            query = query.filter(LibraryClearanceService._search_clause(texto))
        return query

    @staticmethod
    def _rows(db: Session, filas) -> list[dict]:
        """Dicts de las bandejas. `can_revert` en UNA consulta (`_revertible_
        ids`, el mismo predicado batched que usa `day_cut`) y el estado de
        impresión de la constancia vía `CertificateService.print_status_map`
        -hasta 2 consultas MÁS, nunca una por fila- (Tarea 3 de
        `2026-10-02-titulatec-constancias-y-pendientes-design.md` §3.3,
        invariante 2), más UNA de nombres de quien observó solo si la página
        trae filas `observed` (`observed_by`). `certificate` es el dict completo que esa llamada
        regresa (o `None`); la plantilla lo pinta con la macro
        `certificate_cell`. `certificate_number` se CONSERVA -la constancia
        VIGENTE, nunca una anulada- porque Caja lo lee directo bajo su píldora
        (`cashier_body.html`; el resumen de `summary_for_process` ya no lo
        trae, Ruling R17). Valores crudos (`Decimal`, `datetime`, `date`):
        formatear es de la plantilla (`format_amount`)."""
        from itcj2.apps.titulatec.services.certificate_service import CertificateService

        if not filas:
            return []
        revertibles = LibraryClearanceService._revertible_ids(
            db, [clearance.id for clearance, *_ in filas])
        refs = [_ref(clearance.id) for clearance, *_ in filas]
        estado_impresion = CertificateService.print_status_map(db, refs)
        # Quién observó (pestaña «Con observaciones»): UNA consulta por página.
        observadores = {clearance.observed_by_id for clearance, *_ in filas
                        if clearance.observed_by_id is not None}
        nombres: dict[int, str] = {}
        if observadores:
            from itcj2.core.models.user import User
            nombres = dict(db.query(User.id, User.full_name)
                           .filter(User.id.in_(observadores)).all())
        # Pagos RETENIDOS revertibles (spec 2026-10-07 §2): UNA consulta, solo
        # si la página trae alguno.
        retenidos = [clearance.id for clearance, *_ in filas
                     if LibraryClearanceService.payment_held(clearance)]
        pago_revertible = (LibraryClearanceService._payment_revertible_paid_at(db, retenidos)
                           if retenidos else {})

        out = []
        for clearance, process, student, program, cohort in filas:
            certificate = estado_impresion.get(_ref(clearance.id))
            retenido = LibraryClearanceService.payment_held(clearance)
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
                "observation_reason": clearance.observation_reason,
                "observed_at": clearance.observed_at,
                "observed_by": nombres.get(clearance.observed_by_id),
                # Spec 2026-10-07 §2: tipo efectivo (`None` fuera de
                # `observed`), pago RETENIDO y si Caja puede revertirlo.
                "observation_kind": LibraryClearanceService._observation_kind(clearance),
                "held": retenido,
                "can_revert_held": retenido and clearance.id in pago_revertible,
                "updated_at": clearance.updated_at,
                "enrolled_at": process.created_at,
                "certificate": certificate,
                "certificate_number": certificate["number"] if certificate else None,
                "can_revert": clearance.id in revertibles,
                "revoked": process.status == "cancelled",
                "admitted": process.status in ADMITTED_PROCESS_STATUSES,
                "donation_missing": cohort.book_donation_amount is None,
            })
        return out
