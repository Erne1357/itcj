"""Motor de encuestas de TitulaTec.

Cuatro tablas: la DEFINICION versionada (`SurveyForm`), la respuesta completa
(`SurveyResponse`), la respuesta desglosada POR CAMPO (`SurveyAnswer`, la unica
razon por la que "promedio de la pregunta 3 sobre 400 respuestas" es una
consulta y no un script) y el borrador de quien tiene sesion (`SurveyDraft`).
"""
from sqlalchemy import (
    BigInteger, Boolean, Column, Date, DateTime, ForeignKey, Index, Integer,
    JSON, Numeric, String, Text, UniqueConstraint,
)
from sqlalchemy.sql import text

from itcj2.models.base import Base


class SurveyForm(Base):
    """Una VERSION de un cuestionario.

    `code` NO lleva `unique=True` a proposito: la version 2 es una FILA nueva con
    el mismo codigo y `version = N+1`. Con un UNIQUE de columna el insert de la
    v2 fallaria y todo el esquema de versiones seria letra muerta.

    Lo unico prohibido es que dos versiones del mismo codigo esten ABIERTAS a la
    vez, y eso lo garantiza el indice parcial `uq_titulatec_survey_forms_open`.
    Se declara aqui ademas de en la migracion porque el `create_all` del CI
    (base vacia, sin Alembic) es lo unico que construye el esquema alli.
    """
    __tablename__ = "titulatec_survey_forms"
    __table_args__ = (
        UniqueConstraint("code", "version",
                         name="uq_titulatec_survey_forms_code_version"),
        Index("uq_titulatec_survey_forms_open", "code", unique=True,
              postgresql_where=text("status = 'open'")),
    )

    id = Column(Integer, primary_key=True)
    code = Column(String(40), nullable=False, index=True)          # 'egresados'
    title = Column(String(160), nullable=False)
    description = Column(Text, nullable=True)
    schema = Column(JSON, nullable=False)
    version = Column(Integer, nullable=False, server_default=text("1"))
    status = Column(String(20), nullable=False,
                    server_default=text("'draft'"))                # draft|open|closed
    opens_at = Column(Date, nullable=True)
    closes_at = Column(Date, nullable=True)
    is_anonymous = Column(Boolean, nullable=False, server_default=text("FALSE"))

    created_at = Column(DateTime, nullable=False, server_default=text("NOW()"))
    updated_at = Column(DateTime, nullable=False, server_default=text("NOW()"))

    def __repr__(self) -> str:
        return f"<SurveyForm {self.code} v{self.version} {self.status}>"


class SurveyResponse(Base):
    """Una respuesta enviada.

    `form_version` es SNAPSHOT: cuando se abra la v2, las respuestas de la v1
    siguen siendo interpretables y comparables.

    `identity_source` solo tiene dos valores, 'session' y 'anonymous'. NO existe
    'self_declared': nunca se acredita por numero de control auto-declarado (D1).

    `answers` guarda la PROYECCION VALIDADA que devuelve el validador (llaves
    desconocidas ya descartadas), no el cuerpo crudo. La IP nunca se guarda en
    claro: `client_ip_hash` es sha256(ip + SECRET_KEY).
    """
    __tablename__ = "titulatec_survey_responses"

    id = Column(BigInteger, primary_key=True)
    form_id = Column(Integer, ForeignKey("titulatec_survey_forms.id"),
                     nullable=False, index=True)
    form_version = Column(Integer, nullable=False)
    user_id = Column(BigInteger, ForeignKey("core_users.id"),
                     nullable=True, index=True)
    process_id = Column(Integer, ForeignKey("titulatec_processes.id"),
                        nullable=True, index=True)
    cohort_id = Column(Integer, ForeignKey("titulatec_cohorts.id"),
                       nullable=True, index=True)
    identity_source = Column(String(20), nullable=False)           # session|anonymous
    control_number = Column(String(20), nullable=True, index=True)
    answers = Column(JSON, nullable=False)
    client_ip_hash = Column(String(64), nullable=True)
    user_agent_hash = Column(String(64), nullable=True)
    submitted_at = Column(DateTime, nullable=False,
                          server_default=text("NOW()"), index=True)

    def __repr__(self) -> str:
        return f"<SurveyResponse {self.id} f{self.form_id} {self.identity_source}>"


class SurveyAnswer(Base):
    """Una fila por campo respondido — salvo `multiselect`, que escribe N filas
    (una por opcion marcada, con `value_text` = valor y `value_bool = True`).

    `field_type` es snapshot del tipo al momento de responder: si el schema
    cambia, la fila sigue diciendo como leerse.
    """
    __tablename__ = "titulatec_survey_answers"
    __table_args__ = (
        Index("ix_titulatec_survey_answers_key_num", "field_key", "value_num"),
    )

    id = Column(BigInteger, primary_key=True)
    response_id = Column(
        BigInteger, ForeignKey("titulatec_survey_responses.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    field_key = Column(String(64), nullable=False, index=True)
    field_type = Column(String(20), nullable=False)
    value_text = Column(Text, nullable=True)
    value_num = Column(Numeric(12, 4), nullable=True)
    value_bool = Column(Boolean, nullable=True)

    def __repr__(self) -> str:
        return f"<SurveyAnswer r{self.response_id} {self.field_key}>"


class SurveyDraft(Base):
    """Borrador automatico (D3).

    UNA fila por (formulario, usuario), UPDATE en sitio, sin historial. Se borra
    al enviar. Solo para sesiones autenticadas: un anonimo guarda en
    `localStorage` y no genera ni una escritura.
    """
    __tablename__ = "titulatec_survey_drafts"
    __table_args__ = (
        UniqueConstraint("form_id", "user_id",
                         name="uq_titulatec_survey_drafts_form_user"),
    )

    id = Column(BigInteger, primary_key=True)
    form_id = Column(Integer,
                     ForeignKey("titulatec_survey_forms.id", ondelete="CASCADE"),
                     nullable=False)
    user_id = Column(BigInteger,
                     ForeignKey("core_users.id", ondelete="CASCADE"),
                     nullable=False)
    answers = Column(JSON, nullable=False)
    updated_at = Column(DateTime, nullable=False, server_default=text("NOW()"))

    def __repr__(self) -> str:
        return f"<SurveyDraft f{self.form_id} u{self.user_id}>"
