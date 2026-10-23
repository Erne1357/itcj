"""Alcance por departamento academico (fase 4, spec §7 y R-D).

`academic_departments` / `academic_programs` / `department_of_program` /
`manageable_departments` y la union en `officer_programs`, que hace que
`assert_process_in_scope` funcione igual para el jefe de departamento.
"""
from datetime import timedelta

import pytest
from fastapi import HTTPException

from itcj2.apps.titulatec.services import scope_service
from itcj2.core.utils.timezone import db_now


@pytest.fixture()
def mundo(db_session, make_department, make_program, make_program_department):
    """Dos departamentos mapeados con una carrera cada uno, y un tercero sin mapeo."""
    dep_a = make_department(name="Depto Sistemas Z")
    dep_b = make_department(name="Depto Electrica A")
    dep_libre = make_department(name="Depto sin mapeo")
    prog_a = make_program("Carrera Academica A")
    prog_b = make_program("Carrera Academica B")
    prog_libre = make_program("Carrera Academica sin depto")
    make_program_department(prog_a, dep_a)
    make_program_department(prog_b, dep_b)
    return dep_a, dep_b, dep_libre, prog_a, prog_b, prog_libre


def test_head_y_coord_ven_sus_carreras(db_session, make_academic_head, mundo):
    dep_a, dep_b, _, prog_a, prog_b, _ = mundo
    jefe = make_academic_head(dep_a, kind="head")
    coord = make_academic_head(dep_b, kind="coord")

    assert scope_service.academic_departments(db_session, jefe.id) == {dep_a.id}
    assert scope_service.academic_programs(db_session, jefe.id) == {prog_a.id}
    assert scope_service.academic_departments(db_session, coord.id) == {dep_b.id}
    assert scope_service.academic_programs(db_session, coord.id) == {prog_b.id}
    assert scope_service.officer_programs(db_session, jefe.id) == {prog_a.id}


def test_puesto_inactivo_no_cuenta(db_session, make_academic_head, mundo):
    from itcj2.core.models.position import UserPosition

    dep_a, *_ = mundo
    jefe = make_academic_head(dep_a)
    for up in db_session.query(UserPosition).filter_by(user_id=jefe.id).all():
        up.is_active = False
    db_session.flush()

    assert scope_service.academic_departments(db_session, jefe.id) == set()
    assert scope_service.academic_programs(db_session, jefe.id) == set()


def test_puesto_vencido_no_cuenta(db_session, make_academic_head, mundo):
    from itcj2.core.models.position import UserPosition

    dep_a, *_ = mundo
    jefe = make_academic_head(dep_a)
    for up in db_session.query(UserPosition).filter_by(user_id=jefe.id).all():
        up.end_date = (db_now() - timedelta(days=3)).date()
    db_session.flush()

    assert scope_service.academic_departments(db_session, jefe.id) == set()


def test_depto_sin_mapeo_no_cuenta(db_session, make_academic_head, mundo):
    _, _, dep_libre, *_ = mundo
    jefe = make_academic_head(dep_libre)

    assert scope_service.academic_departments(db_session, jefe.id) == set()
    assert scope_service.academic_programs(db_session, jefe.id) == set()
    assert scope_service.officer_programs(db_session, jefe.id) == set()


def test_union_no_rompe_a_los_encargados(db_session, make_officer, make_head, mundo):
    _, _, _, prog_a, _, prog_libre = mundo
    encargado, _pos = make_officer([prog_libre])
    assert scope_service.officer_programs(db_session, encargado.id) == {prog_libre.id}

    jefa = make_head()
    assert scope_service.officer_programs(db_session, jefa.id) == "ALL"


def test_union_suma_lo_academico_a_lo_de_encargado(db_session, make_academic_head,
                                                    make_officer, mundo):
    """Un usuario con carreras por puesto de SE y ademas jefe de depto ve la union."""
    from itcj2.core.models.position import ProgramPosition, UserPosition

    dep_a, _, _, prog_a, _, prog_libre = mundo
    encargado, pos = make_officer([prog_libre])
    jefe = make_academic_head(dep_a)
    # El mismo usuario ocupa los dos puestos
    pos_academico = (db_session.query(UserPosition).filter_by(user_id=jefe.id).first())
    pos_academico.user_id = encargado.id
    db_session.flush()

    assert scope_service.officer_programs(db_session, encargado.id) == {
        prog_a.id, prog_libre.id}
    assert db_session.query(ProgramPosition).filter_by(position_id=pos.id).count() == 1


def test_remapear_una_carrera_mueve_el_alcance(db_session, make_academic_head,
                                                make_program_department, mundo):
    dep_a, dep_b, _, prog_a, _, _ = mundo
    jefe_a = make_academic_head(dep_a)
    jefe_b = make_academic_head(dep_b)
    assert prog_a.id in scope_service.academic_programs(db_session, jefe_a.id)

    make_program_department(prog_a, dep_b)  # RF4: la carrera cambia de departamento

    assert prog_a.id not in scope_service.academic_programs(db_session, jefe_a.id)
    assert prog_a.id in scope_service.academic_programs(db_session, jefe_b.id)
    assert scope_service.department_of_program(db_session, prog_a.id) == dep_b.id


def test_department_of_program(db_session, mundo):
    dep_a, _, _, prog_a, _, prog_libre = mundo
    assert scope_service.department_of_program(db_session, prog_a.id) == dep_a.id
    assert scope_service.department_of_program(db_session, prog_libre.id) is None


def test_manageable_departments_academico_y_all(db_session, make_academic_head,
                                                 make_head, mundo):
    dep_a, dep_b, dep_libre, *_ = mundo
    jefe = make_academic_head(dep_a)
    propios = scope_service.manageable_departments(db_session, jefe.id)
    assert propios == [{"id": dep_a.id, "code": dep_a.code, "name": dep_a.name}]

    # R-D: con process.api.read.all, todos los departamentos mapeados, por nombre.
    jefa = make_head()
    todos = scope_service.manageable_departments(db_session, jefa.id)
    ids = [d["id"] for d in todos]
    assert dep_a.id in ids and dep_b.id in ids and dep_libre.id not in ids
    assert ids.index(dep_b.id) < ids.index(dep_a.id)  # "Electrica A" < "Sistemas Z"
    nombres = [d["name"] for d in todos]
    assert nombres == sorted(nombres)


def test_assert_process_in_scope_para_el_jefe(db_session, make_academic_head,
                                               make_student, make_process, mundo):
    dep_a, _, _, prog_a, prog_b, _ = mundo
    jefe = make_academic_head(dep_a)
    propio = make_process(make_student(), program=prog_a)
    ajeno = make_process(make_student(), program=prog_b)

    assert scope_service.assert_process_in_scope(db_session, jefe.id, propio.id).id == propio.id
    with pytest.raises(HTTPException) as exc:
        scope_service.assert_process_in_scope(db_session, jefe.id, ajeno.id)
    assert exc.value.status_code == 404
