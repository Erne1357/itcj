"""No adeudo de biblioteca por proceso (Biblioteca -> Caja).

Spec `2026-10-01-titulatec-biblioteca-caja-design.md` §4.1.1/§4.2. Una fila
por proceso (`process_id` es UNIQUE): nace `pending` al dar de alta el
proceso (`ImportService.import_rows` -> `LibraryClearanceService.
open_for_process`); los procesos que ya existian la reciben del backfill de
la migracion o del re-backfill de `activar-biblioteca-caja` (`pending`, o
`cleared/legacy` si ya cumplian el requisito a mano). Es la MISMA fila que
despues registra Biblioteca, cobra Caja o libera una constancia previa --
nunca se crea una segunda (unico escritor de transiciones:
`LibraryClearanceService`, spec §5 invariante 1; el backfill y la promocion
D17 son DATO, sin eventos).

Maquina de estados (detalle y guardas en `LibraryClearanceService`):

    (nace)            ──────────────────────────────────> pending
    pending           ──Biblioteca registra, total > 0──> awaiting_payment  (hay monto a cobrar)
    pending           ──Biblioteca registra, total = 0──> cleared   (cleared_via='no_charge')
    awaiting_payment  ──Biblioteca corrige──────────────> awaiting_payment | cleared/no_charge
    awaiting_payment  ──Caja cobra──────────────────────> cleared   (cleared_via='payment')
    pending/awaiting  ──constancia previa───────────────> cleared   (cleared_via='prior';
                         (Biblioteca, SE o la importacion   +folio BIB del semestre anterior)
                          `import-prior-clearances`)
    cleared/payment   ──Caja revierte el pago───────────> awaiting_payment
    cleared/no_charge|legacy ──Biblioteca revierte──────> pending
    cleared/prior     ──se deshace la previa────────────> pending
                         (Biblioteca o SE)
    pending|awaiting  ──Biblioteca observa (motivo)─────> observed/blocking  (`ready_at` = NULL,
                                                                    montos intactos)
    pending|awaiting  ──Biblioteca observa CON ADEUDO───> observed/with_debt (montos congelados
                         (motivo + adeudo, total > 0)                 como al Registrar)
    observed          ──Biblioteca actualiza el motivo──> observed
    observed/with_debt (sin pago) ──Caja cobra──────────> observed/with_debt + pago (RETENIDO:
                                                         sin folio, sin requisito, sin cita)
    observed/with_debt + pago ──Caja revierte el pago──> observed/with_debt (sin pago)
    observed/blocking ──Biblioteca activa──────────────> pending   (montos intactos)
    observed/with_debt sin pago ──Biblioteca activa────> awaiting_payment (Caja cobra)
    observed/with_debt + pago ──Biblioteca activa──────> cleared/payment (+folio BIB)

Las tres reversas exigen la fase 2 SIN aprobar (`can_revert`); observar y
rehabilitar tambien (spec `2026-10-05-titulatec-biblioteca-observaciones-
design.md` §3.2). Desde `cleared` no se observa: primero se revierte. Con
`observed` ni se registra, ni se aplica una constancia previa: primero se
activa. La observacion NORMAL (`observation_kind='blocking'`) tampoco deja
cobrar ni revertir (D4); la CON ADEUDO (`with_debt`, spec 2026-10-07 §2, D3)
deja que Caja cobre y revierta su pago, pero ese pago NO libera: lo libera
«Activar».

`cleared_via='legacy'` no tiene arista de entrada: lo escribe el dato, nunca
una transicion -- el backfill de la migracion `tt20261001a` y la promocion
D17 de `activar-biblioteca-caja` (Ruling R20) para procesos que ya cumplian
el requisito `library_clearance` a mano (o cuya fase 2 ya estaba aprobada)
antes de que el candado se encendiera; no hay Biblioteca/Caja/SE detras.

Montos (`debt_amount`/`donation_amount`/`total_amount`): NULL hasta que
Biblioteca registra el adeudo. `donation_amount` queda CONGELADA en ese
momento con el `Cohort.book_donation_amount` vigente -- un cambio posterior
de la convocatoria no mueve lo ya registrado; "Corregir" vuelve a congelar
con la vigente de ese momento (Review Focus #2). Una constancia previa
registrada desde `awaiting_payment` conserva los montos como historia; volver
a `pending` los borra.
"""
from sqlalchemy import (
    BigInteger, CheckConstraint, Column, Date, DateTime, ForeignKey, Integer,
    Numeric, String, Text, UniqueConstraint,
)
from sqlalchemy.sql import text

from itcj2.models.base import Base

# Dominio de `status` (spec §4.1.1/§4.2). Nace en 'pending'.
# 'awaiting_payment' = Biblioteca ya registro un adeudo > 0 y falta que Caja
# cobre. 'cleared' = sin adeudo pendiente (ver `cleared_via` para el motivo).
# 'observed' = Biblioteca DETUVO al egresado con un motivo («Con
# observaciones», spec 2026-10-05 §3.1): ni agenda ni paga hasta que Biblioteca
# lo rehabilite (vuelve a 'pending'). Sin CHECK de dominio en la BD.
LIBRARY_STATUSES = ("pending", "awaiting_payment", "observed", "cleared")

# Dominio de `observation_kind` (spec 2026-10-07 §2, migracion `tt20261007a`).
# NULL fuera de 'observed'. 'blocking' = la observacion de siempre: detiene
# TODO, incluido el pago en Caja (D4); las filas `observed` que ya existian la
# recibieron en la migracion. 'with_debt' = observacion CON ADEUDO (D3):
# Biblioteca congela adeudo + donacion como al Registrar, Caja SI cobra, pero
# el pago queda RETENIDO (sin folio, sin requisito, sin cita) hasta que
# Biblioteca activa. Una fila `observed` con NULL (dato viejo) se lee como
# 'blocking' (falla cerrado). Sin CHECK de dominio en la BD.
OBSERVATION_KINDS = ("blocking", "with_debt")

# Dominio de `cleared_via`. NULL salvo cuando `status='cleared'`.
# 'payment' = Caja cobro el monto congelado. 'no_charge' = Biblioteca
# registro un total de 0 (sin adeudo y donacion $0, D18). 'prior' = una
# constancia previa (§4.12) que registro Biblioteca, Servicios Escolares
# (respaldo D9) o la importacion `import-prior-clearances`. 'legacy' = ya
# cumplia el requisito antes del candado (backfill de `tt20261001a` y
# promocion D17 de `activar-biblioteca-caja`).
CLEARED_VIA = ("payment", "no_charge", "prior", "legacy")


class LibraryClearance(Base):
    __tablename__ = "titulatec_library_clearances"
    __table_args__ = (
        UniqueConstraint("process_id", name="uq_titulatec_library_clearances_process"),
        # Tolerantes a NULL: un CHECK solo falla con FALSE, y la comparacion
        # contra NULL es NULL (patron de `cohort_review_day.py`). Los montos
        # son NULL hasta que Biblioteca los registra.
        CheckConstraint(
            "total_amount IS NULL OR debt_amount IS NULL OR donation_amount IS NULL "
            "OR total_amount = debt_amount + donation_amount",
            name="ck_titulatec_library_clearances_total_eq_sum",
        ),
        CheckConstraint("debt_amount IS NULL OR debt_amount >= 0",
                        name="ck_titulatec_library_clearances_debt_nonneg"),
        CheckConstraint("donation_amount IS NULL OR donation_amount >= 0",
                        name="ck_titulatec_library_clearances_donation_nonneg"),
        CheckConstraint("total_amount IS NULL OR total_amount >= 0",
                        name="ck_titulatec_library_clearances_total_nonneg"),
    )

    id = Column(Integer, primary_key=True)
    process_id = Column(Integer, ForeignKey("titulatec_processes.id"), nullable=False)

    status = Column(String(20), nullable=False,
                    server_default=text("'pending'"), index=True)
    cleared_via = Column(String(20), nullable=True)   # dominio: CLEARED_VIA; NULL salvo 'cleared'

    debt_amount = Column(Numeric(10, 2), nullable=True)
    donation_amount = Column(Numeric(10, 2), nullable=True)   # congelada al registrar
    total_amount = Column(Numeric(10, 2), nullable=True)

    # --- Biblioteca ---
    library_note = Column(Text, nullable=True)
    library_by_id = Column(BigInteger, ForeignKey("core_users.id"), nullable=True)
    library_at = Column(DateTime, nullable=True)
    # ULTIMA entrada a caja (Ruling R10): se vuelve a fijar cada vez que la fila
    # pasa a `awaiting_payment` desde otro estado, no al corregir el monto.
    # Ancla del recordatorio de pago y FIFO de "Por cobrar".
    ready_at = Column(DateTime, nullable=True)

    # --- Caja ---
    paid_by_id = Column(BigInteger, ForeignKey("core_users.id"), nullable=True)
    paid_at = Column(DateTime, nullable=True)
    receipt_number = Column(String(40), nullable=True)

    # --- Observacion de Biblioteca (spec 2026-10-05 §3.1, tt20261005a) ---
    # La VIGENTE mientras `status='observed'`; NULL en cualquier otro estado
    # (rehabilitar la limpia). El historial vive en `ProcessEvent`.
    observation_reason = Column(Text, nullable=True)
    observed_by_id = Column(BigInteger, ForeignKey("core_users.id"), nullable=True)
    observed_at = Column(DateTime, nullable=True)
    # Tipo de la observacion VIGENTE (spec 2026-10-07 §2, tt20261007a):
    # dominio OBSERVATION_KINDS; NULL fuera de 'observed'.
    observation_kind = Column(String(20), nullable=True)

    # --- Constancia previa (§4.12) ---
    prior_issued_on = Column(Date, nullable=True)
    prior_note = Column(Text, nullable=True)
    prior_by_id = Column(BigInteger, ForeignKey("core_users.id"), nullable=True)

    created_at = Column(DateTime, nullable=False, server_default=text("NOW()"))
    updated_at = Column(DateTime, nullable=False, server_default=text("NOW()"))

    def __repr__(self) -> str:
        return f"<LibraryClearance p{self.process_id} {self.status}>"
