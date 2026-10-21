"""Fase 4 (sinodales), tarea 1: modelos, índices parciales y fixtures."""
import pytest
from sqlalchemy.exc import IntegrityError

from itcj2.apps.titulatec.models import (
    DepartmentSettings, Modality, ProgramDepartment, SynodalAssignment, TeacherProfile,
)


@pytest.fixture()
def escenario(db_session, make_student, make_process, make_program, make_department,
              make_teacher, make_academic_head):
    dept = make_department()
    prog = make_program("Carrera sinodales prueba")
    alumno = make_student()
    proc = make_process(alumno, program=prog)
    jefe = make_academic_head(dept)
    docentes = [make_teacher(dept) for _ in range(5)]
    return proc, jefe, docentes


def _asignar(db, proc, user, role, jefe, activo=True):
    row = SynodalAssignment(process_id=proc.id, user_id=user.id, role=role,
                            assigned_by_id=jefe.id, is_active=activo)
    db.add(row)
    db.flush()
    return row


def test_defaults_de_asignacion(db_session, escenario):
    proc, jefe, docs = escenario
    row = SynodalAssignment(process_id=proc.id, user_id=docs[0].id, role="alternate",
                            assigned_by_id=jefe.id)
    db_session.add(row)
    db_session.flush()
    db_session.refresh(row)
    assert row.is_active is True
    assert row.replaced_at is None and row.replaced_by_id is None
    assert row.replacement_reason is None


def test_dos_activos_misma_posicion_falla(db_session, escenario):
    proc, jefe, docs = escenario
    _asignar(db_session, proc, docs[0], "president", jefe)
    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            _asignar(db_session, proc, docs[1], "president", jefe)


def test_inactivo_mas_activo_misma_posicion_ok(db_session, escenario):
    proc, jefe, docs = escenario
    _asignar(db_session, proc, docs[0], "president", jefe, activo=False)
    _asignar(db_session, proc, docs[1], "president", jefe)


def test_mismo_usuario_activo_en_dos_roles_falla(db_session, escenario):
    proc, jefe, docs = escenario
    _asignar(db_session, proc, docs[0], "president", jefe)
    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            _asignar(db_session, proc, docs[0], "vocal", jefe)


def test_mismo_usuario_sustituido_y_activo_ok(db_session, escenario):
    proc, jefe, docs = escenario
    _asignar(db_session, proc, docs[0], "president", jefe, activo=False)
    _asignar(db_session, proc, docs[0], "vocal", jefe)


def test_fixtures_de_docente_y_depto(db_session, make_department, make_program,
                                     make_program_department, make_teacher,
                                     make_academic_head, make_process, make_student,
                                     make_synodals):
    from itcj2.core.models.position import UserPosition

    dept = make_department()
    prog = make_program("Carrera fixtures sinodales")
    pd = make_program_department(prog, dept, official_name="Oficial")
    assert isinstance(pd, ProgramDepartment) and pd.official_name == "Oficial"

    docente = make_teacher(dept)
    perfil = db_session.get(TeacherProfile, docente.id)
    assert perfil.professional_license == "10837613"
    assert db_session.query(UserPosition).filter_by(user_id=docente.id, is_active=True).count() == 1

    jefe = make_academic_head(dept)
    coord = make_academic_head(dept, kind="coord")
    assert jefe.id != coord.id

    proc = make_process(make_student(), program=prog)
    t = {r: make_teacher(dept) for r in ("president", "secretary", "vocal", "alternate")}
    rows = make_synodals(proc, t, jefe)
    assert {r.role for r in rows} == set(t) and all(r.is_active for r in rows)


def test_option_label_y_settings(db_session, make_department):
    m = db_session.query(Modality).first()
    if m is not None:
        assert hasattr(m, "option_label")
    dept = make_department()
    s = DepartmentSettings(department_id=dept.id, oficio_header="DEPTO",
                           addressee_position_code="head_x")
    db_session.add(s)
    db_session.flush()
    assert s.attn_position_code is None
