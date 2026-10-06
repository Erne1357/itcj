"""Constancias (GTV y no adeudo de biblioteca): motor compartido de emision.

Spec `2026-10-01-titulatec-biblioteca-caja-design.md` §4.1.3-5/§4.5: UNA
tabla para los dos tipos de constancia (`kind`), numeracion atomica por tipo
y semestre (`CertificateCounter`; por semestre desde
`2026-10-05-titulatec-folios-design.md` §3.2, migracion `tt20261005c`),
emision individual o por lote (`CertificateBatch`). El PDF NUNCA se guarda:
se regenera de los datos ya congelados en la fila -- mismo resultado siempre,
asi que no hay archivo que mantener sincronizado con la base.

Unico escritor: `CertificateService` (tarea aparte). Una constancia nunca se
borra -- se ANULA (`voided_at`/`voided_by_id`/`void_reason`) y el numero no
se reutiliza; "re-liberar" (Review Focus #6) emite una constancia NUEVA con
numero nuevo, nunca reabre la anulada (spec §5 invariante 5).
"""
from sqlalchemy import (
    BigInteger, Column, DateTime, ForeignKey, Index, Integer, String, Text,
)
from sqlalchemy.sql import text

from itcj2.models.base import Base

# Dominio de `kind`, compartido por Certificate/CertificateBatch/CertificateCounter.
# 'survey_release' = libera la encuesta de egresados (GTV). 'library_clearance'
# = no adeudo de biblioteca.
CERTIFICATE_KINDS = ("survey_release", "library_clearance")


class Certificate(Base):
    """Una constancia emitida. `number` es el folio visible
    (`GTV-2026B-0001`: prefijo, anio + semestre `A`/`B`, consecutivo), unico,
    asignado por `CertificateCounter` (atomico, nunca se repite ni se
    reutiliza aunque la constancia se anule despues).

    `source_ref` ata la constancia a la fila que la origino SIN FK real
    (puede ser `SurveyReview` o `LibraryClearance` segun `kind`):
    `survey_review:{id}` | `library_clearance:{id}`. A lo mas UNA constancia
    vigente (no anulada) por `source_ref` (spec §5 invariante 5): la cuidan
    los llamadores de `CertificateService.issue` -solo emiten al ENTRAR al
    estado liberado y toda salida anula- y, desde la revision final (Ruling
    R29), tambien la BASE: el UNIQUE PARCIAL `uq_titulatec_certificates_
    live_source` sobre `source_ref` WHERE `voided_at IS NULL`. Una anulada y
    su reemplazo SI comparten `source_ref` (la anulada queda fuera del
    indice); dos vigentes del mismo origen truenan con `IntegrityError`.
    """
    __tablename__ = "titulatec_certificates"
    __table_args__ = (
        # «Por imprimir»: constancias sueltas (sin lote) y vigentes (sin
        # anular). Declarado aqui Y en la migracion con el MISMO predicado
        # -- el create_all del CI no pasa por Alembic.
        Index("ix_titulatec_certificates_pending_print", "kind", "issued_at",
              postgresql_where=text("batch_id IS NULL AND voided_at IS NULL")),
        # A lo mas UNA vigente por origen (§5 invariante 5, Ruling R29).
        # Mismo nombre y predicado que en `tt20261001a`.
        Index("uq_titulatec_certificates_live_source", "source_ref", unique=True,
              postgresql_where=text("voided_at IS NULL")),
    )

    id = Column(Integer, primary_key=True)
    kind = Column(String(20), nullable=False)             # dominio: CERTIFICATE_KINDS
    number = Column(String(20), nullable=False, unique=True, index=True)  # 'GTV-2026B-0001'

    process_id = Column(Integer, ForeignKey("titulatec_processes.id"),
                        nullable=False, index=True)
    source_ref = Column(String(64), nullable=False)       # 'survey_review:{id}' | 'library_clearance:{id}'

    # --- Datos congelados al emitir (el PDF se regenera de esto, nunca se guarda) ---
    control_number = Column(String(20), nullable=False)
    student_name = Column(String(200), nullable=False)
    program_name = Column(String(200), nullable=False)
    period_label = Column(String(40), nullable=False)

    issued_at = Column(DateTime, nullable=False, server_default=text("NOW()"))
    # NULL = emitida sin usuario (importaciones y CLI de folios de previas),
    # desde `tt20261005c`.
    issued_by_id = Column(BigInteger, ForeignKey("core_users.id"), nullable=True)

    batch_id = Column(Integer, ForeignKey("titulatec_certificate_batches.id"),
                      nullable=True, index=True)

    voided_at = Column(DateTime, nullable=True)
    voided_by_id = Column(BigInteger, ForeignKey("core_users.id"), nullable=True)
    void_reason = Column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<Certificate {self.number} {self.kind}>"


class CertificateBatch(Base):
    """Lote de impresion de constancias (§4.5): agrupa varias `Certificate`
    emitidas juntas para un solo PDF de varias paginas. Tampoco guarda el
    PDF: se regenera concatenando el de cada constancia del lote.
    """
    __tablename__ = "titulatec_certificate_batches"

    id = Column(Integer, primary_key=True)
    kind = Column(String(20), nullable=False)             # dominio: CERTIFICATE_KINDS
    created_at = Column(DateTime, nullable=False, server_default=text("NOW()"))
    created_by_id = Column(BigInteger, ForeignKey("core_users.id"), nullable=False)
    count = Column(Integer, nullable=False)

    def __repr__(self) -> str:
        return f"<CertificateBatch {self.kind} n={self.count}>"


class CertificateCounter(Base):
    """Contador atomico de folio por tipo y semestre (`2026A`/`2026B`,
    `tt20261005c`; antes era por tipo y anio). El servicio
    (`CertificateService._next_number`) NO lo lee antes de escribir: hace UNA
    sola sentencia `INSERT ... ON CONFLICT (kind, semester) DO UPDATE SET
    last_value = last_value + 1 RETURNING last_value` (segura con PgBouncer,
    spec §4.5) -- la primera emision del (kind, semestre) inserta 1, las
    demas incrementan bajo el lock de fila del propio upsert. El folio
    emitido es ese valor ya incrementado y nunca se reutiliza aunque la
    constancia se anule.
    """
    __tablename__ = "titulatec_certificate_counters"

    kind = Column(String(20), primary_key=True)            # dominio: CERTIFICATE_KINDS
    semester = Column(String(5), primary_key=True)         # '2026A'/'2026B' (SEMESTER_RE)
    last_value = Column(Integer, nullable=False, server_default=text("0"))

    def __repr__(self) -> str:
        return f"<CertificateCounter {self.kind}/{self.semester}={self.last_value}>"
