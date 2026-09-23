"""Solicitud de liberacion de la encuesta de egresados por GTV.

Gestion Tecnologica y Vinculacion (GTV, `core_departments.code = 'tech_management'`)
revisa la encuesta que el egresado ya envio y decide si libera el requisito de
cotejo `graduate_survey` o deja observaciones. Lo que revisa lo atiende
fisicamente en su ventanilla (Residencias, Practicas, Servicio Social): el
egresado no mueve ningun estado desde el sistema.

Una fila por proceso (`process_id` es UNIQUE): nace cuando se envia la
encuesta (`SurveyReviewService.open_for_submission`) y es la MISMA fila la
que GTV libera, observa o revoca despues — nunca se crea una segunda. El
envio de la encuesta ya NO acredita el requisito por si solo; lo hace esta
tabla cuando GTV libera.
"""
from sqlalchemy import (
    BigInteger, Column, DateTime, ForeignKey, Integer, String, Text,
    UniqueConstraint,
)
from sqlalchemy.sql import text

from itcj2.models.base import Base


class SurveyReview(Base):
    """Solicitud de liberacion, una por proceso.

    Maquina de estados (detalle y guardas en `SurveyReviewService`, tarea
    aparte):

        (envio de encuesta)  ──────────────────────>  in_review
        in_review  ──Liberar────────────────────────> approved
        in_review  ──Observar (motivo)───────────────> rejected
        rejected   ──Liberar────────────────────────> approved   (sin accion del egresado)
        rejected   ──Observar (motivo)───────────────> rejected   (actualiza el texto)
        approved   ──Revocar (motivo)────────────────> rejected   (solo si la fase 2 no esta approved)
    """
    __tablename__ = "titulatec_survey_reviews"
    __table_args__ = (
        UniqueConstraint("process_id", name="uq_titulatec_survey_reviews_process"),
    )

    id = Column(Integer, primary_key=True)
    process_id = Column(Integer, ForeignKey("titulatec_processes.id"),
                        nullable=False)
    response_id = Column(BigInteger, ForeignKey("titulatec_survey_responses.id"),
                         nullable=False, index=True)          # la respuesta congelada
    status = Column(String(20), nullable=False,
                    server_default=text("'in_review'"),
                    index=True)                                # in_review|approved|rejected
    rejection_reason = Column(Text, nullable=True)              # observaciones vigentes; se limpia al liberar
    reviewed_by_id = Column(BigInteger, ForeignKey("core_users.id"),
                            nullable=True)                      # autor del ultimo dictamen
    reviewed_at = Column(DateTime, nullable=True)

    submitted_at = Column(DateTime, nullable=False, server_default=text("NOW()"))
    created_at = Column(DateTime, nullable=False, server_default=text("NOW()"))
    updated_at = Column(DateTime, nullable=False, server_default=text("NOW()"))

    def __repr__(self) -> str:
        return f"<SurveyReview p{self.process_id} {self.status}>"
