"""Tests de `HandoffService` (bandeja "Liberados" del Departamento de Titulacion).

Tarea 4 del deslinde a T-soft (spec `2026-09-21-titulatec-dpto-titulacion`,
design doc S5). El criterio de "liberado" es UNICAMENTE
`ProcessPhase(phase_number=2, status='approved')` -- la fase de Cita de
cotejo (`review_appointment`). Deliberadamente no se toca `ReviewAppointment`:
los reintentos de cita (no_show/superseded/reagendados) no deben duplicar ni
decidir nada aqui.

`HandoffService` es de SOLO LECTURA (sin commit, sin add) y no resuelve
permisos: `allowed_program_ids` llega ya calculado por el llamador, con el
mismo contrato que `scope_service.officer_programs` ("ALL" o un iterable de
program_id; conjunto vacio -> fail-closed).
"""
import itertools
from datetime import datetime

import pytest

import itcj2.models  # noqa: F401
from itcj2.apps.titulatec.services.handoff_service import HandoffService, ReleasedRow

_control_numbers = itertools.count(1)


def _cn() -> str:
    """Numero de control unico y determinista para este archivo de tests."""
    return f"29{next(_control_numbers):06d}"


@pytest.fixture(autouse=True)
def _catalogo(seed_phase_defs):
    """El numero de la fase de liberacion sale del catalogo
    (`PhaseService.phase_number_for_code`); sin sembrarlo NINGUN proceso
    saldria "liberado" -- el service falla cerrado, no revienta."""
    seed_phase_defs()


def _released(db, **kw):
    """`list_released` devuelve un `Page`; los tests de filtros/alcance/orden
    leen (filas, total) y los de paginado usan el `Page` directo."""
    pagina = HandoffService.list_released(db, **kw)
    return pagina.items, pagina.total


def _release(db_session, process, when):
    """Marca la fase 2 (`review_appointment`) del proceso como aprobada."""
    from itcj2.apps.titulatec.models import ProcessPhase
    ph = (
        db_session.query(ProcessPhase)
        .filter_by(process_id=process.id, phase_number=2)
        .one()
    )
    ph.status = "approved"
    ph.completed_at = when
    db_session.flush()
    return ph


# =========================================================================
# Criterio de liberacion
# =========================================================================

def test_solo_aparecen_los_de_fase2_aprobada(db_session, make_program, make_cohort,
                                             make_user, make_process):
    program = make_program("Ingenieria en Sistemas (T4-A)")
    cohort = make_cohort()
    liberado = make_user(first_name="MARIA", last_name="LOPEZ", control_number=_cn())
    pendiente = make_user(first_name="JUAN", last_name="PEREZ", control_number=_cn())
    proc_liberado = make_process(liberado, cohort=cohort, program=program, current_phase=1)
    make_process(pendiente, cohort=cohort, program=program, current_phase=1)
    _release(db_session, proc_liberado, datetime(2026, 1, 10, 9, 0))

    # Acotado a `program`: la BD de dev ya trae un proceso real liberado
    # (contexto de la Tarea 4) y "ALL" sin acotar lo contaria de mas.
    rows, total = _released(
        db_session, allowed_program_ids={program.id})

    assert total == 1
    assert [r.process_id for r in rows] == [proc_liberado.id]


def test_fase2_en_progreso_no_aparece(db_session, make_program, make_cohort,
                                      make_user, make_process):
    program = make_program("Ingenieria en Sistemas (T4-B)")
    cohort = make_cohort()
    student = make_user(first_name="ANA", last_name="TORRES", control_number=_cn())
    # current_phase=2 -> la fabrica deja la fase 2 en 'in_progress' (aun sin
    # aprobar): estado DISTINTO de 'pending', y tambien debe quedar fuera.
    make_process(student, cohort=cohort, program=program, current_phase=2)

    rows, total = _released(
        db_session, allowed_program_ids={program.id})

    assert rows == []
    assert total == 0


def test_dos_intentos_de_cita_no_duplican_la_fila(db_session, make_program, make_cohort,
                                                   make_user, make_process, make_appointment):
    program = make_program("Ingenieria en Sistemas (T4-C)")
    cohort = make_cohort()
    student = make_user(first_name="LUIS", last_name="RAMIREZ", control_number=_cn())
    proc = make_process(student, cohort=cohort, program=program, current_phase=1)
    _release(db_session, proc, datetime(2026, 1, 12, 11, 0))
    # Historial: un intento superado (no_show) + el vigente (attended).
    # HandoffService NUNCA consulta ReviewAppointment, asi que da igual
    # cuantos intentos haya: el criterio es la fila de ProcessPhase.
    make_appointment(proc, status="no_show", is_current=False, attempt_no=1)
    make_appointment(proc, status="attended", is_current=True, attempt_no=2)

    rows, total = _released(
        db_session, allowed_program_ids={program.id})

    assert total == 1
    assert [r.process_id for r in rows] == [proc.id]


def test_proceso_sin_carrera_nunca_aparece(db_session, make_cohort, make_user, make_process):
    """`program_id IS NULL` es la cola de reparacion de `scope_service`, no un
    egresado liberado -- ni siquiera con alcance "ALL". `program_name` en
    `ReleasedRow` es `str` (no opcional) precisamente porque esta fila nunca
    sale sin programa."""
    cohort = make_cohort()
    alumno = make_user(first_name="SIN", last_name="CARRERA", control_number=_cn())
    proc = make_process(alumno, cohort=cohort, program=None, current_phase=1)
    _release(db_session, proc, datetime(2026, 1, 20, 8, 0))

    # Sin `program.id` que acotar (el proceso no tiene carrera): se acota por
    # `cohort_id`, propio y fresco, para no depender de lo que ya haya en dev.
    rows, total = _released(
        db_session, allowed_program_ids="ALL", cohort_id=cohort.id)

    assert rows == []
    assert total == 0


# =========================================================================
# Alcance por carrera (`allowed_program_ids`)
# =========================================================================

def test_alcance_vacio_devuelve_cero(db_session, make_program, make_cohort,
                                     make_user, make_process):
    program = make_program("Ingenieria en Sistemas (T4-D)")
    cohort = make_cohort()
    student = make_user(first_name="PEDRO", last_name="GOMEZ", control_number=_cn())
    proc = make_process(student, cohort=cohort, program=program, current_phase=1)
    _release(db_session, proc, datetime(2026, 1, 13, 8, 0))

    rows, total = _released(db_session, allowed_program_ids=set())

    assert rows == []
    assert total == 0


def test_all_devuelve_de_todas_las_carreras_y_el_set_acota(
        db_session, make_program, make_cohort, make_user, make_process):
    cohort = make_cohort()
    prog_a = make_program("Ingenieria en Sistemas (T4-E1)")
    prog_b = make_program("Ingenieria Industrial (T4-E2)")
    alumno_a = make_user(first_name="SOFIA", last_name="MARTINEZ", control_number=_cn())
    alumno_b = make_user(first_name="DIEGO", last_name="HERNANDEZ", control_number=_cn())
    proc_a = make_process(alumno_a, cohort=cohort, program=prog_a, current_phase=1)
    proc_b = make_process(alumno_b, cohort=cohort, program=prog_b, current_phase=1)
    _release(db_session, proc_a, datetime(2026, 1, 14, 8, 0))
    _release(db_session, proc_b, datetime(2026, 1, 14, 9, 0))

    # `cohort_id` acota a esta convocatoria: aisla del resto de la BD de dev
    # (que ya trae un proceso real liberado) sin tocar lo que "ALL" prueba.
    rows, total = _released(
        db_session, allowed_program_ids="ALL", cohort_id=cohort.id)
    assert total == 2
    assert {r.process_id for r in rows} == {proc_a.id, proc_b.id}

    rows_a, total_a = _released(
        db_session, allowed_program_ids={prog_a.id}, cohort_id=cohort.id)
    assert total_a == 1
    assert rows_a[0].process_id == proc_a.id


# =========================================================================
# Filtros
# =========================================================================

def test_filtro_por_convocatoria(db_session, make_program, make_cohort, make_user, make_process):
    program = make_program("Ingenieria en Sistemas (T4-F)")
    cohort_1 = make_cohort()
    cohort_2 = make_cohort()
    alumno_1 = make_user(first_name="CARLA", last_name="VEGA", control_number=_cn())
    alumno_2 = make_user(first_name="OMAR", last_name="SOTO", control_number=_cn())
    proc_1 = make_process(alumno_1, cohort=cohort_1, program=program, current_phase=1)
    proc_2 = make_process(alumno_2, cohort=cohort_2, program=program, current_phase=1)
    _release(db_session, proc_1, datetime(2026, 1, 15, 8, 0))
    _release(db_session, proc_2, datetime(2026, 1, 15, 8, 0))

    rows, total = _released(
        db_session, allowed_program_ids="ALL", cohort_id=cohort_1.id)

    assert total == 1
    assert rows[0].process_id == proc_1.id


def test_filtro_por_programa(db_session, make_program, make_cohort, make_user, make_process):
    cohort = make_cohort()
    prog_a = make_program("Ingenieria en Sistemas (T4-K1)")
    prog_b = make_program("Ingenieria Industrial (T4-K2)")
    alumno_a = make_user(first_name="K", last_name="A", control_number=_cn())
    alumno_b = make_user(first_name="K", last_name="B", control_number=_cn())
    proc_a = make_process(alumno_a, cohort=cohort, program=prog_a, current_phase=1)
    proc_b = make_process(alumno_b, cohort=cohort, program=prog_b, current_phase=1)
    _release(db_session, proc_a, datetime(2026, 1, 21, 8, 0))
    _release(db_session, proc_b, datetime(2026, 1, 21, 8, 0))

    rows, total = _released(
        db_session, allowed_program_ids="ALL", program_id=prog_a.id)

    assert total == 1
    assert rows[0].process_id == proc_a.id


def test_filtro_por_modalidad(db_session, make_program, make_cohort, make_user, make_process,
                              make_modality):
    program = make_program("Ingenieria en Sistemas (T4-L)")
    cohort = make_cohort()
    mod_a = make_modality(name="Tesis (T4-L)")
    mod_b = make_modality(name="EGEL (T4-L)")
    alumno_a = make_user(first_name="M", last_name="A", control_number=_cn())
    alumno_b = make_user(first_name="M", last_name="B", control_number=_cn())
    proc_a = make_process(alumno_a, cohort=cohort, program=program, modality=mod_a,
                          current_phase=1)
    proc_b = make_process(alumno_b, cohort=cohort, program=program, modality=mod_b,
                          current_phase=1)
    _release(db_session, proc_a, datetime(2026, 1, 22, 8, 0))
    _release(db_session, proc_b, datetime(2026, 1, 22, 8, 0))

    rows, total = _released(
        db_session, allowed_program_ids="ALL", modality_id=mod_a.id)

    assert total == 1
    assert rows[0].process_id == proc_a.id
    assert rows[0].modality_name == mod_a.name


def test_modalidad_ausente_da_modality_name_none(db_session, make_program, make_cohort,
                                                  make_user, make_process):
    program = make_program("Ingenieria en Sistemas (T4-M)")
    cohort = make_cohort()
    alumno = make_user(first_name="SIN", last_name="MODALIDAD", control_number=_cn())
    proc = make_process(alumno, cohort=cohort, program=program, modality=None, current_phase=1)
    _release(db_session, proc, datetime(2026, 1, 23, 8, 0))

    rows, _total = _released(
        db_session, allowed_program_ids={program.id})

    assert rows[0].modality_name is None


def test_q_busca_por_numero_de_control(db_session, make_program, make_cohort,
                                       make_user, make_process):
    program = make_program("Ingenieria en Sistemas (T4-G)")
    cohort = make_cohort()
    control = _cn()
    alumno = make_user(first_name="RAQUEL", last_name="FLORES", control_number=control)
    otro = make_user(first_name="IVAN", last_name="CASTRO", control_number=_cn())
    proc = make_process(alumno, cohort=cohort, program=program, current_phase=1)
    proc_otro = make_process(otro, cohort=cohort, program=program, current_phase=1)
    _release(db_session, proc, datetime(2026, 1, 16, 8, 0))
    _release(db_session, proc_otro, datetime(2026, 1, 16, 8, 0))

    rows, total = _released(
        db_session, allowed_program_ids={program.id}, q=control)

    assert total == 1
    assert rows[0].process_id == proc.id


def test_q_busca_por_nombre_insensible_a_mayusculas(db_session, make_program, make_cohort,
                                                     make_user, make_process):
    program = make_program("Ingenieria en Sistemas (T4-H)")
    cohort = make_cohort()
    alumno = make_user(first_name="GABRIELA", last_name="NUNEZ", control_number=_cn())
    otro = make_user(first_name="HECTOR", last_name="RIOS", control_number=_cn())
    proc = make_process(alumno, cohort=cohort, program=program, current_phase=1)
    proc_otro = make_process(otro, cohort=cohort, program=program, current_phase=1)
    _release(db_session, proc, datetime(2026, 1, 17, 8, 0))
    _release(db_session, proc_otro, datetime(2026, 1, 17, 8, 0))

    rows, total = _released(
        db_session, allowed_program_ids={program.id}, q="gabriela")

    assert total == 1
    assert rows[0].process_id == proc.id
    assert rows[0].full_name == "GABRIELA NUNEZ"


def test_q_escapa_el_comodin_porcentaje(db_session, make_program, make_cohort,
                                        make_user, make_process):
    """Un '%' en `q` debe buscarse LITERAL, no como comodin SQL.

    `control_number` es siempre digitos (con letra opcional al inicio, ver
    CLAUDE.md de la app 10): ningun numero de control real contiene un '%'.
    Sin escapar, el patron `ILIKE '%<control>%%'` colapsa el `%%` final en un
    comodin de "lo que sea" y el patron se comporta como "empieza con
    <control>", que SI matchea el propio alumno -- trae de mas. Escapado, el
    patron exige un '%' LITERAL despues del control, que ningun numero de
    control real trae, y el resultado correcto es CERO filas.
    """
    program = make_program("Ingenieria en Sistemas (T4-ESCAPE)")
    cohort = make_cohort()
    control = _cn()
    alumno = make_user(first_name="PORCENTAJE", last_name="PRUEBA", control_number=control)
    proc = make_process(alumno, cohort=cohort, program=program, current_phase=1)
    _release(db_session, proc, datetime(2026, 1, 19, 8, 0))

    rows, total = _released(
        db_session, allowed_program_ids={program.id}, q=f"{control}%")

    assert total == 0
    assert rows == []


# =========================================================================
# Forma de la fila / orden / paginacion
# =========================================================================

def test_released_at_es_el_completed_at_de_la_fase(db_session, make_program, make_cohort,
                                                    make_user, make_process):
    program = make_program("Ingenieria en Sistemas (T4-I)")
    cohort = make_cohort()
    alumno = make_user(first_name="NOE", last_name="AGUILAR", control_number=_cn())
    proc = make_process(alumno, cohort=cohort, program=program, current_phase=1)
    momento = datetime(2026, 2, 1, 13, 45)
    _release(db_session, proc, momento)

    rows, _total = _released(
        db_session, allowed_program_ids={program.id})

    assert rows[0].released_at == momento


def test_orden_por_released_at_desc_desempate_por_process_id_desc(
        db_session, make_program, make_cohort, make_user, make_process):
    program = make_program("Ingenieria en Sistemas (T4-J)")
    cohort = make_cohort()
    a1 = make_user(first_name="A1", last_name="X", control_number=_cn())
    a2 = make_user(first_name="A2", last_name="X", control_number=_cn())
    a3 = make_user(first_name="A3", last_name="X", control_number=_cn())
    p_viejo = make_process(a1, cohort=cohort, program=program, current_phase=1)
    p_nuevo = make_process(a2, cohort=cohort, program=program, current_phase=1)
    p_empate = make_process(a3, cohort=cohort, program=program, current_phase=1)
    _release(db_session, p_viejo, datetime(2026, 1, 1, 8, 0))
    _release(db_session, p_nuevo, datetime(2026, 1, 3, 8, 0))
    _release(db_session, p_empate, datetime(2026, 1, 3, 8, 0))  # mismo instante que p_nuevo

    rows, _total = _released(
        db_session, allowed_program_ids={program.id})

    empatados_desc = sorted([p_nuevo.id, p_empate.id], reverse=True)
    assert [r.process_id for r in rows] == [*empatados_desc, p_viejo.id]


def test_paginacion(db_session, make_program, make_cohort, make_user, make_process):
    program = make_program("Ingenieria en Sistemas (T4-N)")
    cohort = make_cohort()
    for i in range(3):
        alumno = make_user(first_name=f"P{i}", last_name="PAG", control_number=_cn())
        proc = make_process(alumno, cohort=cohort, program=program, current_phase=1)
        _release(db_session, proc, datetime(2026, 1, 24, 8, i))

    p1 = HandoffService.list_released(
        db_session, allowed_program_ids={program.id}, page=1, per_page=2)
    p2 = HandoffService.list_released(
        db_session, allowed_program_ids={program.id}, page=2, per_page=2)
    rows_p1, rows_p2 = p1.items, p2.items

    assert (p1.total, p2.total) == (3, 3)
    assert (p1.has_next, p2.has_next) == (True, False)
    assert len(rows_p1) == 2
    assert len(rows_p2) == 1
    assert {r.process_id for r in rows_p1} & {r.process_id for r in rows_p2} == set()
    # Sigue el orden released_at desc: la pagina 2 continua a la 1.
    assert [r.released_at for r in rows_p1 + rows_p2] == sorted(
        (r.released_at for r in rows_p1 + rows_p2), reverse=True)


def test_liberados_muestra_rango_de_total(db_session, make_program, make_cohort,
                                          make_user, make_process):
    program = make_program("Ingenieria en Sistemas (T4-RG)")
    cohort = make_cohort()
    for i in range(3):
        alumno = make_user(first_name=f"R{i}", last_name="RANGO", control_number=_cn())
        proc = make_process(alumno, cohort=cohort, program=program, current_phase=1)
        _release(db_session, proc, datetime(2026, 1, 24, 9, i))

    p2 = HandoffService.list_released(
        db_session, allowed_program_ids={program.id}, page=2, per_page=2)
    p9 = HandoffService.list_released(
        db_session, allowed_program_ids={program.id}, page=9, per_page=2)
    vacio = HandoffService.list_released(db_session, allowed_program_ids=set())

    assert (p2.start, p2.end, p2.total) == (3, 3, 3)
    assert (p9.page, p9.start, p9.end) == (2, 3, 3)
    assert (vacio.total, vacio.items, vacio.start, vacio.end) == (0, [], 0, 0)


# =========================================================================
# export_rows: mismas filas, sin paginar
# =========================================================================

def test_export_rows_no_pagina(db_session, make_program, make_cohort, make_user, make_process):
    program = make_program("Ingenieria en Sistemas (T4-O)")
    cohort = make_cohort()
    for i in range(3):
        alumno = make_user(first_name=f"E{i}", last_name="EXPORT", control_number=_cn())
        proc = make_process(alumno, cohort=cohort, program=program, current_phase=1)
        _release(db_session, proc, datetime(2026, 1, 25, 8, i))

    rows = HandoffService.export_rows(db_session, allowed_program_ids={program.id})

    assert len(rows) == 3
    assert all(isinstance(r, ReleasedRow) for r in rows)


def test_export_rows_respeta_alcance_vacio(db_session, make_program, make_cohort,
                                           make_user, make_process):
    program = make_program("Ingenieria en Sistemas (T4-P)")
    cohort = make_cohort()
    alumno = make_user(first_name="Q", last_name="EXPORT", control_number=_cn())
    proc = make_process(alumno, cohort=cohort, program=program, current_phase=1)
    _release(db_session, proc, datetime(2026, 1, 26, 8, 0))

    assert HandoffService.export_rows(db_session, allowed_program_ids=set()) == []


# =========================================================================
# Correo PERSONAL (spec 2026-10-07 §7, D9)
# =========================================================================
# Misma resolución que `StudentMail.contact_email`: perfil
# (`core_student_profile.contact_email`) → `contact_email` de la
# `EnrollmentRequest` MÁS RECIENTE que convirtió ESTE proceso → y, como último
# respaldo de la bandeja, el institucional (`core_users.email`, casi siempre
# vacío en egresados). Vacío o solo espacios cuenta como ausente.

def _perfil(db, user, correo):
    from itcj2.core.models.student_profile import StudentProfile
    db.add(StudentProfile(user_id=user.id, contact_email=correo))
    db.flush()


def _solicitud(db, proc, user, correo, cohort):
    from itcj2.apps.titulatec.models import EnrollmentRequest
    req = EnrollmentRequest(
        cohort_id=cohort.id, control_number=user.control_number,
        first_name="ALUMNO", last_name="FICTICIO", phone="6560000000",
        contact_email=correo, has_efirma=False, kind="known",
        status="converted", converted_process_id=proc.id)
    db.add(req)
    db.flush()
    return req


@pytest.fixture()
def liberado_con_correo(db_session, make_program, make_cohort, make_user, make_process):
    """Un liberado con correo institucional; el test le pone perfil/solicitud."""
    def _make(sufijo, institucional="inst.{n}@example.invalid"):
        program = make_program(f"Ingenieria Correo Personal ({sufijo})")
        cohort = make_cohort()
        cn = _cn()
        alumno = make_user(first_name="CORREO", last_name=sufijo, control_number=cn,
                           email=institucional.format(n=cn) if institucional else None)
        if institucional is None:
            alumno.email = None      # `make_user` siempre pone uno por omisión
            db_session.flush()
        proc = make_process(alumno, cohort=cohort, program=program, current_phase=1)
        _release(db_session, proc, datetime(2026, 2, 1, 9, 0))
        return proc, alumno, program, cohort
    return _make


def _email_de(db, program):
    (fila,), _ = _released(db, allowed_program_ids={program.id})
    (csv,) = HandoffService.export_rows(db, allowed_program_ids={program.id})
    assert fila.email == csv.email, "la bandeja y el CSV no coinciden"
    return fila.email


def test_el_correo_del_perfil_gana(db_session, liberado_con_correo):
    proc, alumno, program, cohort = liberado_con_correo("P1")
    _perfil(db_session, alumno, "perfil@example.invalid")
    _solicitud(db_session, proc, alumno, "solicitud@example.invalid", cohort)

    assert _email_de(db_session, program) == "perfil@example.invalid"


def test_sin_perfil_usa_la_solicitud_mas_reciente_del_proceso(db_session,
                                                             liberado_con_correo):
    proc, alumno, program, cohort = liberado_con_correo("P2")
    _solicitud(db_session, proc, alumno, "vieja@example.invalid", cohort)
    _solicitud(db_session, proc, alumno, "nueva@example.invalid", cohort)

    assert _email_de(db_session, program) == "nueva@example.invalid"


def test_perfil_en_blanco_cuenta_como_ausente(db_session, liberado_con_correo):
    proc, alumno, program, cohort = liberado_con_correo("P3")
    _perfil(db_session, alumno, "   ")
    _solicitud(db_session, proc, alumno, " solicitud@example.invalid ", cohort)

    assert _email_de(db_session, program) == "solicitud@example.invalid"


def test_sin_personal_cae_al_institucional(db_session, liberado_con_correo):
    _proc, alumno, program, _cohort = liberado_con_correo("P4")

    assert _email_de(db_session, program) == alumno.email


def test_sin_ningun_correo_es_none(db_session, liberado_con_correo):
    _proc, alumno, program, _cohort = liberado_con_correo("P5", institucional=None)

    assert _email_de(db_session, program) is None


def test_la_solicitud_de_otro_proceso_no_cuenta(db_session, liberado_con_correo,
                                                make_process, make_cohort):
    """Mismo filtro que `StudentMail.contact_email`: `converted_process_id` ==
    ESTE proceso, no cualquier solicitud del alumno."""
    proc, alumno, program, _cohort = liberado_con_correo("P6")
    otra_conv = make_cohort()
    otro = make_process(alumno, cohort=otra_conv, program=program, current_phase=0)
    _solicitud(db_session, otro, alumno, "otra@example.invalid", otra_conv)

    assert _email_de(db_session, program) == alumno.email


def test_misma_resolucion_que_studentmail(db_session, liberado_con_correo):
    from itcj2.apps.titulatec.services.student_mail import StudentMail
    proc, alumno, program, cohort = liberado_con_correo("P7")
    _solicitud(db_session, proc, alumno, "solicitud@example.invalid", cohort)

    assert _email_de(db_session, program) == StudentMail.contact_email(db_session, proc)


def test_el_correo_no_agrega_consultas_por_fila(db_session, make_program, make_cohort,
                                                make_user, make_process):
    """Sin N+1: la página cuesta lo mismo con 1 fila que con 4 (perfil y
    solicitud viajan en la MISMA consulta)."""
    from sqlalchemy import event

    program = make_program("Ingenieria Correo Personal (N+1)")
    cohort = make_cohort()

    def _alta(i):
        alumno = make_user(first_name="NMAS", last_name=f"UNO{i}", control_number=_cn())
        proc = make_process(alumno, cohort=cohort, program=program, current_phase=1)
        _release(db_session, proc, datetime(2026, 2, 2, 9, i))
        _perfil(db_session, alumno, f"p{i}@example.invalid")
        _solicitud(db_session, proc, alumno, f"s{i}@example.invalid", cohort)

    def _contar(fn):
        n = [0]
        motor = db_session.get_bind()

        def _hook(*_a, **_k):
            n[0] += 1
        event.listen(motor, "before_cursor_execute", _hook)
        try:
            fn()
        finally:
            event.remove(motor, "before_cursor_execute", _hook)
        return n[0]

    _alta(0)
    pagina_1 = _contar(lambda: _released(db_session, allowed_program_ids={program.id}))
    csv_1 = _contar(lambda: HandoffService.export_rows(
        db_session, allowed_program_ids={program.id}))
    for i in range(1, 4):
        _alta(i)
    pagina_4 = _contar(lambda: _released(db_session, allowed_program_ids={program.id}))
    csv_4 = _contar(lambda: HandoffService.export_rows(
        db_session, allowed_program_ids={program.id}))

    assert pagina_4 == pagina_1, f"la página crece con las filas: {pagina_1} -> {pagina_4}"
    assert csv_4 == csv_1, f"el CSV crece con las filas: {csv_1} -> {csv_4}"
