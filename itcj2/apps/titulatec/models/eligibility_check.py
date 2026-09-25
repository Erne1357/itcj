"""Consulta de elegibilidad de una solicitud de inscripcion contra el SII.

Una fila por INTENTO de consulta (`attempt`), no una por solicitud: la tarea
de celery (con backoff) y el barrido periodico reintentan SOLO los `error`
con `retryable` -- el SII no respondio (`SiiUnavailable`) -- hasta
`TITULATEC_SII_MAX_ATTEMPTS`, y cada intento deja su propio rastro -- que
reglas se evaluaron, con que resultado y por que.
`EnrollmentRequest.last_check_id` (agregado en esta misma migracion) apunta a
la fila VIGENTE; las anteriores quedan como historial.

`status` nace en 'pending' (server_default) cuando el servicio abre la fila
al empezar a consultar -- por eso `started_at` tambien tiene NOW() de
default y `finished_at`/`duration_ms` quedan NULL hasta que la consulta
termina. La bandeja de Servicios Escolares (spec S8/3.5) pinta "Consultando..."
mientras `status == 'pending'`.

Lo que SI se guarda (`facts`, `results`) es la lista blanca declarada en
`[facts]`/`[[rule]]` de `rules.toml` (spec 3.2); lo que NUNCA se guarda aqui
es el NIP: `[credential]` no entra ni en `facts` ni en `results` (spec 3.2,
5). `error` es el mensaje de `SiiUnavailable`/`SiiQueryError` sin la cadena
de conexion (spec 5).
"""
from sqlalchemy import (
    BigInteger, Boolean, Column, DateTime, ForeignKey, Index, Integer, JSON, String, Text,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import text

from itcj2.models.base import Base


class EligibilityCheck(Base):
    __tablename__ = "titulatec_eligibility_checks"
    __table_args__ = (
        Index("ix_titulatec_eligibility_checks_request_status", "request_id", "status"),
    )

    id = Column(Integer, primary_key=True)
    request_id = Column(BigInteger, ForeignKey("titulatec_enrollment_requests.id"),
                        nullable=False, index=True)
    status = Column(String(20), nullable=False,
                    server_default=text("'pending'"))   # pending|apt|not_apt|error
    rules_version = Column(String(40), nullable=True)
    results = Column(JSON, nullable=True)               # [{rule, ok, message}]
    facts = Column(JSON, nullable=True)                 # columnas no sensibles de [facts]
    # Diferencias nombre/carrera formulario vs SII, si `[identity]` esta
    # declarado en las reglas y no coincide (spec 3.3). NULL = no se comparo
    # o no hubo discrepancia.
    identity_mismatch = Column(JSON, nullable=True)
    error = Column(Text, nullable=True)                 # mensaje de SiiUnavailable/SiiQueryError, sin credenciales
    # Solo en `status == 'error'`: True si el SII no respondio
    # (`SiiUnavailable`: conexion, timeout, backend apagado) y por eso se
    # reintenta (spec 3.4); False si es de configuracion (reglas, consulta
    # invalida, falla inesperada), que esperar no arregla. NULL en los demas
    # estados. Migracion `tt20260925b`.
    retryable = Column(Boolean, nullable=True)
    attempt = Column(Integer, nullable=False, server_default=text("1"))
    started_at = Column(DateTime, nullable=False, server_default=text("NOW()"))
    finished_at = Column(DateTime, nullable=True)
    duration_ms = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=text("NOW()"))

    request = relationship("EnrollmentRequest", foreign_keys=[request_id])

    def __repr__(self) -> str:
        return f"<EligibilityCheck req{self.request_id} intento{self.attempt} {self.status}>"
