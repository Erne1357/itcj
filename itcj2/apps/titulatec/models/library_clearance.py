"""No adeudo de biblioteca por proceso (Biblioteca -> Caja).

Spec `2026-10-01-titulatec-biblioteca-caja-design.md` §4.1.1/§4.2. Una fila
por proceso (`process_id` es UNIQUE): nace cuando el proceso entra a la
bandeja de Biblioteca y es la MISMA fila que Biblioteca registra, Caja cobra
o Servicios Escolares exonera despues -- nunca se crea una segunda (unico
escritor: `LibraryClearanceService`, tarea aparte, spec §5 invariante 1).

Maquina de estados (detalle y guardas en `LibraryClearanceService`):

    (nace)            ────────────────────────────>  pending
    pending           ──Biblioteca registra adeudo──> awaiting_payment  (hay monto a cobrar)
    pending           ──Biblioteca registra 0──────>  cleared   (cleared_via='no_charge')
    awaiting_payment  ──Caja cobra─────────────────>  cleared   (cleared_via='payment')
    pending/awaiting  ──SE aplica constancia previa─>  cleared   (cleared_via='prior')

`cleared_via='legacy'` es EXCLUSIVO del backfill de la migracion
`tt20261001a`: procesos que ya cumplian el requisito `library_clearance`
antes de que este feature existiera (no hay Biblioteca/Caja/SE detras).

Montos (`debt_amount`/`donation_amount`/`total_amount`): NULL hasta que
Biblioteca registra el adeudo. `donation_amount` queda CONGELADA en ese
momento con el `Cohort.book_donation_amount` vigente -- un cambio posterior
de la convocatoria no mueve lo ya registrado; "Corregir" vuelve a congelar
con la vigente de ese momento (Review Focus #2, tarea aparte).
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
LIBRARY_STATUSES = ("pending", "awaiting_payment", "cleared")

# Dominio de `cleared_via`. NULL salvo cuando `status='cleared'`.
# 'payment' = Caja cobro el monto congelado. 'no_charge' = Biblioteca
# registro un adeudo de 0. 'prior' = Servicios Escolares aplico una
# constancia previa (§4.12). 'legacy' = ya cumplia el requisito antes de
# este feature (backfill de `tt20261001a`).
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
    ready_at = Column(DateTime, nullable=True)   # 1a vez que paso a caja: ancla de recordatorios

    # --- Caja ---
    paid_by_id = Column(BigInteger, ForeignKey("core_users.id"), nullable=True)
    paid_at = Column(DateTime, nullable=True)
    receipt_number = Column(String(40), nullable=True)

    # --- Constancia previa (§4.12) ---
    prior_issued_on = Column(Date, nullable=True)
    prior_note = Column(Text, nullable=True)
    prior_by_id = Column(BigInteger, ForeignKey("core_users.id"), nullable=True)

    created_at = Column(DateTime, nullable=False, server_default=text("NOW()"))
    updated_at = Column(DateTime, nullable=False, server_default=text("NOW()"))

    def __repr__(self) -> str:
        return f"<LibraryClearance p{self.process_id} {self.status}>"
