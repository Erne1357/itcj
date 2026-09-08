"""Contrato de ESQUEMA de las tablas nuevas de la encuesta y la convocatoria.

`Base.metadata` solo dice lo que el codigo CREE que existe. Este archivo golpea
Postgres de verdad con `db_session`: si la migracion no corrio, el primer INSERT
truena con `UndefinedTable`, que es justo el fallo que hay que ver antes de
escribir la migracion.

Los dos indices UNICOS PARCIALES estan declarados en el `__table_args__` de su
modelo ADEMAS de en la migracion con `op.execute`. Sin esa declaracion, el
`create_all` del CI (base vacia, sin Alembic — `.github/workflows/deploy.yml:78-105`)
no los crearia y `test_solo_una_version_abierta_por_codigo` fallaria solo alli.

Patron para las violaciones de restriccion: `with db_session.begin_nested():`.
Un `db_session.rollback()` pelado descarta TAMBIEN las filas que sembraron las
factories (ver el docstring del conftest de este paquete, sobre
`join_transaction_mode="create_savepoint"`); el savepoint anidado solo descarta
el INSERT que fallo y deja la sesion utilizable.

Los codigos y numeros de control son irrepetibles a proposito: cuando el DML
`11_seed_survey_form.sql` siembre 'egresados' v1 ABIERTA en la BD de dev, un
test que usara ese literal fallaria por la razon equivocada.
"""
from __future__ import annotations

import uuid
from datetime import date

import pytest
from sqlalchemy import text as sa_text
from sqlalchemy.exc import IntegrityError

TABLAS_NUEVAS = [
    "core_student_profile",
    "titulatec_survey_forms",
    "titulatec_survey_responses",
    "titulatec_survey_answers",
    "titulatec_survey_drafts",
    "titulatec_requirement_fulfillments",
    "titulatec_enrollment_requests",
]


def _uniq() -> str:
    return uuid.uuid4().hex[:8]


def _form(db, *, code=None, version=1, status="open"):
    """Formulario minimo valido. `code` irrepetible salvo que se pida otro."""
    from itcj2.apps.titulatec.models import SurveyForm

    row = SurveyForm(
        code=code or f"prueba_{_uniq()}",
        version=version,
        status=status,
        title="Encuesta de egresados (prueba)",
        schema={"enabled": True, "fields": []},
    )
    db.add(row)
    db.flush()
    return row


# ---------------------------------------------------------------------------
# Registro (no tocan la BD)
# ---------------------------------------------------------------------------
def test_student_profile_esta_reexportado_en_core_models():
    """Sin el re-export, la tabla no entra a `Base.metadata`, el `create_all` del
    CI no la crea y todo test que la toque muere con `UndefinedTable`."""
    import itcj2.core.models as core_models

    assert hasattr(core_models, "StudentProfile")
    assert "StudentProfile" in core_models.__all__


def test_las_siete_tablas_nuevas_estan_en_base_metadata():
    import itcj2.apps.titulatec.models  # noqa: F401
    import itcj2.core.models  # noqa: F401
    from itcj2.models.base import Base

    faltantes = [t for t in TABLAS_NUEVAS if t not in Base.metadata.tables]
    assert not faltantes, (
        f"tablas fuera de Base.metadata: {faltantes}. Alembic no las ve en "
        "--autogenerate y el create_all del CI no las crea."
    )


# ---------------------------------------------------------------------------
# core_student_profile
# ---------------------------------------------------------------------------
def test_perfil_de_alumno_hace_round_trip(db_session, make_user, make_program):
    from itcj2.core.models import StudentProfile

    user = make_user(control_number=f"99{_uniq()[:6]}")
    prog = make_program("ING. EN SISTEMAS (PRUEBA PERFIL)")
    db_session.add(StudentProfile(
        user_id=user.id,
        english_accredited=True,
        english_accredited_at=date(2026, 5, 1),
        english_source="manual",
        contact_email="egresado.personal@example.invalid",
        phone="6561234567",
        program_id=prog.id,
        program_text="ING. EN SISTEMAS COMPUTACIONALES",
        reticula="ISIC-2010",
        estatus_alumno="EGRESADO",
        campus="CENTRO",
        curp="XXXX000000HCHXXX00",
        has_efirma=True,
    ))
    db_session.flush()

    row = db_session.get(StudentProfile, user.id)
    assert row.contact_email == "egresado.personal@example.invalid"
    # D17: guardar el correo personal NO lo da por verificado.
    assert row.contact_email_verified_at is None
    assert row.created_at is not None
    # D12: `core_users.email` no se toca nunca.
    assert user.email != "egresado.personal@example.invalid"


def test_ingles_acreditado_es_triestado(db_session, make_user):
    """NULL ('no sabemos') no es lo mismo que False ('sabemos que no')."""
    from itcj2.core.models import StudentProfile

    u1, u2 = make_user(), make_user()
    db_session.add_all([
        StudentProfile(user_id=u1.id),
        StudentProfile(user_id=u2.id, english_accredited=False),
    ])
    db_session.flush()

    assert db_session.get(StudentProfile, u1.id).english_accredited is None
    assert db_session.get(StudentProfile, u2.id).english_accredited is False


# ---------------------------------------------------------------------------
# titulatec_survey_forms
# ---------------------------------------------------------------------------
def test_dos_versiones_del_mismo_codigo_conviven(db_session):
    """`SurveyForm.code` NO lleva `unique=True`: la v2 es una FILA nueva."""
    code = f"prueba_{_uniq()}"
    v1 = _form(db_session, code=code, version=1, status="closed")
    v2 = _form(db_session, code=code, version=2, status="open")

    assert v1.id != v2.id
    assert v1.code == v2.code == code


def test_solo_una_version_abierta_por_codigo(db_session):
    """Indice parcial `uq_titulatec_survey_forms_open`: sembrar la v2 obliga a
    cerrar la v1 en la MISMA transaccion (riesgo 12 del spec)."""
    from itcj2.apps.titulatec.models import SurveyForm

    code = f"prueba_{_uniq()}"
    _form(db_session, code=code, version=1, status="open")

    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.add(SurveyForm(
                code=code, version=2, status="open", title="v2",
                schema={"enabled": True, "fields": []},
            ))
            db_session.flush()

    # Cerrando la v1 primero, la v2 entra sin problema.
    db_session.query(SurveyForm).filter_by(code=code, version=1).update(
        {"status": "closed"})
    db_session.add(SurveyForm(code=code, version=2, status="open", title="v2",
                              schema={"enabled": True, "fields": []}))
    db_session.flush()


# ---------------------------------------------------------------------------
# titulatec_survey_responses / _answers / _drafts
# ---------------------------------------------------------------------------
def test_respuesta_congela_la_version_y_se_desglosa_por_campo(
        db_session, make_user, make_cohort, make_process):
    from itcj2.apps.titulatec.models import SurveyAnswer, SurveyResponse

    form = _form(db_session, version=3)
    student = make_user(control_number=f"99{_uniq()[:6]}")
    cohort = make_cohort()
    proc = make_process(student, cohort=cohort)

    resp = SurveyResponse(
        form_id=form.id, form_version=form.version, user_id=student.id,
        process_id=proc.id, cohort_id=cohort.id, identity_source="session",
        control_number=student.control_number,
        answers={"situacion_laboral": "empleado", "relacion_carrera": 5},
        client_ip_hash="a" * 64, user_agent_hash="b" * 64,
    )
    db_session.add(resp)
    db_session.flush()
    db_session.add_all([
        SurveyAnswer(response_id=resp.id, field_key="situacion_laboral",
                     field_type="radio", value_text="empleado"),
        SurveyAnswer(response_id=resp.id, field_key="relacion_carrera",
                     field_type="scale", value_num=5),
    ])
    db_session.flush()

    assert resp.form_version == 3
    assert resp.submitted_at is not None

    filas = (db_session.query(SurveyAnswer)
             .filter_by(response_id=resp.id)
             .order_by(SurveyAnswer.field_key).all())
    assert [f.field_key for f in filas] == ["relacion_carrera", "situacion_laboral"]
    assert float(filas[0].value_num) == 5.0
    assert filas[1].value_text == "empleado"


def test_respuesta_anonima_no_lleva_usuario_ni_proceso(db_session):
    """D1: sin sesion cuenta para la estadistica y nada mas."""
    from itcj2.apps.titulatec.models import SurveyResponse

    form = _form(db_session)
    resp = SurveyResponse(form_id=form.id, form_version=form.version,
                          identity_source="anonymous",
                          answers={"situacion_laboral": "buscando"})
    db_session.add(resp)
    db_session.flush()

    assert resp.user_id is None
    assert resp.process_id is None
    assert resp.control_number is None


def test_borrador_es_unico_por_formulario_y_usuario(db_session, make_user):
    """D3: UPDATE en sitio, sin historial. Una fila por (form, user)."""
    from itcj2.apps.titulatec.models import SurveyDraft

    form = _form(db_session)
    user = make_user()
    db_session.add(SurveyDraft(form_id=form.id, user_id=user.id, answers={"a": 1}))
    db_session.flush()

    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.add(SurveyDraft(form_id=form.id, user_id=user.id,
                                       answers={"a": 2}))
            db_session.flush()


# ---------------------------------------------------------------------------
# titulatec_cotejo_requirements (columnas nuevas) + cumplimientos
# ---------------------------------------------------------------------------
def test_requisito_de_cotejo_gana_code_y_auto_source(db_session, make_cohort):
    from itcj2.apps.titulatec.models import CotejoRequirement

    cohort = make_cohort()
    req = CotejoRequirement(cohort_id=cohort.id, label="Encuesta de egresados",
                            icon="clipboard-check", code="graduate_survey",
                            auto_source="graduate_survey")
    db_session.add(req)
    db_session.flush()

    assert req.code == "graduate_survey"
    assert req.auto_source == "graduate_survey"

    # Ambas son NULL-ables: los requisitos que ya existen no se rompen.
    otro = CotejoRequirement(cohort_id=cohort.id, label="12 fotografias")
    db_session.add(otro)
    db_session.flush()
    assert otro.code is None and otro.auto_source is None


def test_cumplimiento_es_unico_por_proceso_y_requisito(
        db_session, make_user, make_cohort, make_process):
    from itcj2.apps.titulatec.models import CotejoRequirement, RequirementFulfillment

    cohort = make_cohort()
    proc = make_process(make_user(), cohort=cohort)
    req = CotejoRequirement(cohort_id=cohort.id, label="Encuesta de egresados")
    db_session.add(req)
    db_session.flush()

    f = RequirementFulfillment(process_id=proc.id, requirement_id=req.id,
                               source="self_service",
                               external_ref="survey_response:1")
    db_session.add(f)
    db_session.flush()

    assert f.status == "fulfilled"      # server_default
    assert f.fulfilled_at is not None

    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.add(RequirementFulfillment(
                process_id=proc.id, requirement_id=req.id, source="officer"))
            db_session.flush()


def test_borrar_un_requisito_con_cumplimiento_esta_restringido(
        db_session, make_user, make_cohort, make_process):
    """ON DELETE RESTRICT, no CASCADE: con CASCADE, borrar un requisito a media
    convocatoria destruiria el credito de todos los que ya lo cumplieron."""
    from itcj2.apps.titulatec.models import CotejoRequirement, RequirementFulfillment

    cohort = make_cohort()
    proc = make_process(make_user(), cohort=cohort)
    req = CotejoRequirement(cohort_id=cohort.id, label="Encuesta de egresados")
    db_session.add(req)
    db_session.flush()
    db_session.add(RequirementFulfillment(process_id=proc.id, requirement_id=req.id,
                                          source="system"))
    db_session.flush()

    # SQL crudo: el ORM aplicaria sus propias reglas de cascada y taparia la
    # restriccion que se quiere probar, que es la de la BD.
    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.execute(
                sa_text("DELETE FROM titulatec_cotejo_requirements WHERE id = :i"),
                {"i": req.id},
            )


# ---------------------------------------------------------------------------
# titulatec_enrollment_requests
# ---------------------------------------------------------------------------
def test_solicitud_viva_es_unica_por_convocatoria_y_control(db_session, make_cohort):
    """Indice parcial `uq_titulatec_enrollment_req_open`: prohibe duplicados
    VIVOS y deja reintentar despues de un rechazo. Un UniqueConstraint normal
    no distingue las dos cosas."""
    from itcj2.apps.titulatec.models import EnrollmentRequest

    cohort = make_cohort()
    control = f"99{_uniq()[:6]}"

    def _req(status):
        return EnrollmentRequest(
            cohort_id=cohort.id, control_number=control,
            first_name="EGRESADO", last_name="PRUEBA", phone="6560000000",
            contact_email="egresado@example.invalid", has_efirma=False,
            kind="unknown", status=status,
        )

    db_session.add(_req("unverified"))
    db_session.flush()

    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.add(_req("pending_review"))
            db_session.flush()

    # 'rejected' queda FUERA del indice: la persona puede volver a intentarlo,
    # incluso varias veces.
    db_session.add(_req("rejected"))
    db_session.add(_req("rejected"))
    db_session.flush()


def test_solicitud_arranca_sin_verificar_y_sin_envios(db_session, make_cohort):
    from itcj2.apps.titulatec.models import EnrollmentRequest

    cohort = make_cohort()
    req = EnrollmentRequest(
        cohort_id=cohort.id, control_number=f"99{_uniq()[:6]}",
        first_name="EGRESADO", last_name="PRUEBA", phone="6560000000",
        contact_email="egresado@example.invalid", has_efirma=True,
        kind="known",
    )
    db_session.add(req)
    db_session.flush()

    assert req.status == "unverified"       # server_default
    assert req.verify_send_count == 0       # server_default
    assert req.verified_at is None
    assert req.converted_process_id is None
