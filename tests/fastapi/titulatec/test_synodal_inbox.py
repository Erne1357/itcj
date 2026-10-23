"""Bandeja «Sinodales» del departamento académico (fase 4, spec §9): `SynodalInboxService`.

Solo lectura. Lo que se fija aquí:

- «Por asignar» = procesos `active` en la fase `synodal_assignment` SIN
  sinodales vigentes, en orden FIFO por `ProcessPhase.started_at` de la fase 4
  (desempate por `process_id`), con posición y semáforo de días hábiles
  (ámbar >= 3, rojo >= 5);
- «Asignados» = procesos con sinodales vigentes y la fase 5 sin aprobar (sin
  revocados);
- alcance por DEPARTAMENTO (R-D): el jefe o coordinador ve las carreras
  mapeadas a su departamento; quien tiene `process.api.read.all` ve todos los
  departamentos mapeados; una carrera sin departamento no sale (nadie puede
  operarla); un `department_id` ajeno no abre nada;
- contadores por pestaña sobre el conjunto filtrado (búsqueda, carrera y
  departamento), no sobre la página; `contains` usa el MISMO universo;
- número fijo de consultas por página.

Cada prueba siembra su propio departamento y sus carreras: las listas son
exactas aunque la base de dev traiga datos reales. Las de `read.all` filtran
por el departamento sembrado (sin filtro, solo comprueban inclusión).
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from tests.fastapi.titulatec.conftest import _n
from tests.fastapi.titulatec.test_documents_inbox import _Contador

T0 = datetime(2026, 10, 1, 9, 0)
READ_ALL = "titulatec.process.api.read.all"
_RUN = os.getpid()
ROLE_ALL = f"tt_test_sinodales_all_{_RUN}"


# ---------------------------------------------------------------------------
# Andamiaje
# ---------------------------------------------------------------------------
@pytest.fixture()
def mundo(db_session, seed_phase_defs, make_program, make_department,
          make_program_department, make_academic_head, make_teacher, make_user,
          make_cohort, make_student, make_process, make_synodals):
    """Dos departamentos académicos con sus carreras mapeadas, el jefe de cada
    uno, 4 docentes del primero y una fábrica de procesos."""
    seed_phase_defs()
    n = _n()
    d1 = make_department(name=f"Depto bandeja sinodales {n}")
    d2 = make_department(name=f"Otro depto bandeja sinodales {n}")
    p1 = make_program(f"Ingenieria Bandeja Sinodales {n}")
    p2 = make_program(f"Ingenieria Bandeja Sinodales Hermana {n}")
    p3 = make_program(f"Licenciatura Bandeja Sinodales {n}")
    suelta = make_program(f"Carrera Sin Departamento {n}")
    make_program_department(p1, d1)
    make_program_department(p2, d1)
    make_program_department(p3, d2)
    jefe1 = make_academic_head(d1, kind="head")
    jefe2 = make_academic_head(d2, kind="head")
    docentes = [make_teacher(d1, user=make_user(first_name=f"DOCENTE{i}",
                                                last_name=f"BANDEJA{n}"))
                for i in range(4)]
    cohorte = make_cohort()

    def nuevo(*, program=p1, phase=4, status="active", started=T0, first="ANA",
              last="PEREZ", middle="LOPEZ", control=None, synodals=False):
        from itcj2.apps.titulatec.models import ProcessPhase

        alumno = make_student(first_name=first, last_name=last, control_number=control)
        alumno.middle_name = middle
        proc = make_process(alumno, cohort=cohorte, program=program, current_phase=phase,
                            status=status)
        fase4 = (db_session.query(ProcessPhase)
                 .filter_by(process_id=proc.id, phase_number=4).one())
        fase4.started_at = started
        if phase > 4:
            fase4.completed_at = started + timedelta(days=1)
        db_session.flush()
        if synodals:
            make_synodals(proc, dict(zip(("president", "secretary", "vocal", "alternate"),
                                         docentes)), assigned_by=jefe1)
        return proc

    def lista(user=jefe1, tab="pending", **kw):
        from itcj2.apps.titulatec.services.synodal_inbox_service import SynodalInboxService
        return SynodalInboxService.list(db_session, user.id, tab=tab, **kw)

    return SimpleNamespace(db=db_session, d1=d1, d2=d2, p1=p1, p2=p2, p3=p3, suelta=suelta,
                           jefe1=jefe1, jefe2=jefe2, docentes=docentes, nuevo=nuevo,
                           lista=lista)


@pytest.fixture()
def lector_global(make_user, make_role, grant_user_role):
    """Usuario con `process.api.read.all` (admin / jefatura de la DEP, R-D)."""
    def _make():
        user = make_user(first_name="DIVISION", last_name="ESTUDIOS")
        grant_user_role(user, make_role(ROLE_ALL, (READ_ALL,)))
        return user
    return _make


def _ids(ctx):
    return [r["process_id"] for r in ctx["rows"]]


def _fase(db, proc, n, status):
    from itcj2.apps.titulatec.models import ProcessPhase
    ph = db.query(ProcessPhase).filter_by(process_id=proc.id, phase_number=n).one()
    ph.status = status
    db.flush()


# ---------------------------------------------------------------------------
# 1. «Por asignar»: FIFO, campos, semáforo
# ---------------------------------------------------------------------------
def test_por_asignar_es_fifo_por_el_inicio_de_la_fase_4(mundo):
    b = mundo.nuevo(started=T0 + timedelta(days=2))
    a = mundo.nuevo(started=T0)
    c = mundo.nuevo(started=T0 + timedelta(days=5), program=mundo.p2)
    mundo.nuevo(phase=3)                                  # todavía en el Formato B
    mundo.nuevo(status="on_hold")                         # pausado

    ctx = mundo.lista()

    assert _ids(ctx) == [a.id, b.id, c.id]
    assert [r["position"] for r in ctx["rows"]] == [1, 2, 3]


def test_empate_del_inicio_se_desempata_por_process_id(mundo):
    a = mundo.nuevo(started=T0)
    b = mundo.nuevo(started=T0)

    assert _ids(mundo.lista()) == sorted([a.id, b.id])


def test_fila_trae_los_campos_del_contrato(mundo):
    p = mundo.nuevo(first="ANA", last="PEREZ", middle="LOPEZ", control=f"99{_n():06d}")

    (r,) = mundo.lista()["rows"]

    assert r["process_id"] == p.id and r["folio"] == p.folio
    assert r["student_name"] == "PEREZ LOPEZ, ANA"
    assert r["control_number"] == p.student.control_number
    assert r["program_name"] == mundo.p1.name
    assert r["department_name"] == mundo.d1.name
    assert r["position"] == 1
    assert isinstance(r["waited_days"], int) and r["wait_level"] in ("ok", "warn", "late")


@pytest.mark.parametrize("dias_habiles,nivel", [(2, "ok"), (3, "warn"), (5, "late")])
def test_semaforo_en_dias_habiles(mundo, monkeypatch, dias_habiles, nivel):
    from itcj2.apps.titulatec.services import synodal_inbox_service as mod

    hoy = datetime(2026, 10, 21, 12, 0)                  # miércoles
    monkeypatch.setattr(mod, "db_now", lambda: hoy)
    inicio = {2: datetime(2026, 10, 19, 10), 3: datetime(2026, 10, 16, 10),
              5: datetime(2026, 10, 14, 10)}[dias_habiles]   # fin de semana de por medio
    mundo.nuevo(started=inicio)

    (r,) = mundo.lista()["rows"]

    assert r["waited_days"] == dias_habiles and r["wait_level"] == nivel


def test_sin_inicio_registrado_va_al_final_y_sin_semaforo(mundo):
    sin = mundo.nuevo(started=None)
    con = mundo.nuevo(started=T0)

    ctx = mundo.lista()

    assert _ids(ctx) == [con.id, sin.id]
    assert ctx["rows"][1]["waited_days"] is None and ctx["rows"][1]["wait_level"] is None


# ---------------------------------------------------------------------------
# 2. «Asignados» y contadores
# ---------------------------------------------------------------------------
def test_asignados_son_los_que_tienen_sinodales_y_la_fase_5_sin_aprobar(mundo):
    pendiente = mundo.nuevo()
    asignado = mundo.nuevo(phase=5, synodals=True)
    terminado = mundo.nuevo(phase=6, synodals=True)       # fase 5 aprobada
    revocado = mundo.nuevo(phase=5, synodals=True, status="cancelled")

    ctx = mundo.lista(tab="assigned")

    assert _ids(ctx) == [asignado.id]
    assert ctx["rows"][0]["position"] is None and ctx["rows"][0]["waited_days"] is None
    assert ctx["counts"] == {"pending": 1, "assigned": 1, "anexo": 0}
    assert terminado.id not in _ids(mundo.lista()) and revocado.id not in _ids(mundo.lista())
    assert _ids(mundo.lista()) == [pendiente.id]


def test_un_proceso_en_la_fase_4_con_sinodales_vigentes_no_sale_por_asignar(mundo):
    """Dato incoherente (la asignación aprueba la fase 4 en la misma transacción):
    nunca aparece en las dos pestañas."""
    raro = mundo.nuevo(synodals=True)

    assert raro.id not in _ids(mundo.lista())
    assert raro.id in _ids(mundo.lista(tab="assigned"))


def test_contadores_respetan_filtros_y_no_la_pagina(mundo):
    for i in range(3):
        mundo.nuevo(started=T0 + timedelta(hours=i))
    mundo.nuevo(program=mundo.p2)
    mundo.nuevo(phase=5, synodals=True)

    ctx = mundo.lista(per_page=2)

    assert len(ctx["rows"]) == 2 and ctx["page"].total == 4
    assert ctx["counts"] == {"pending": 4, "assigned": 1, "anexo": 0}
    assert len(mundo.lista(per_page=2, page="2")["rows"]) == 2
    assert mundo.lista(program_id=mundo.p2.id)["counts"] == {"pending": 1, "assigned": 0, "anexo": 0}


def test_pestana_desconocida_cae_en_por_asignar(mundo):
    p = mundo.nuevo()

    ctx = mundo.lista(tab="zzz")

    assert ctx["tab"] == "pending" and _ids(ctx) == [p.id]


# ---------------------------------------------------------------------------
# 3. Búsqueda y filtros
# ---------------------------------------------------------------------------
def test_busqueda_por_control_y_por_nombre(mundo):
    control = f"99{_n():06d}"
    x = mundo.nuevo(first="ZULEMA", last="QUIROGA", middle="BRAVO", control=control)
    mundo.nuevo(first="OTRA", last="PERSONA", middle="DISTINTA")

    assert _ids(mundo.lista(q=control)) == [x.id]
    assert _ids(mundo.lista(q="quiroga bravo zulema")) == [x.id]
    assert mundo.lista(q="NOEXISTE-XYZ")["counts"]["pending"] == 0


def test_filtro_de_carrera(mundo):
    a = mundo.nuevo(program=mundo.p1)
    b = mundo.nuevo(program=mundo.p2)

    assert _ids(mundo.lista(program_id=mundo.p2.id)) == [b.id]
    assert _ids(mundo.lista(program_id=mundo.p1.id)) == [a.id]


def test_programs_del_filtro_son_los_de_sus_departamentos(mundo):
    from itcj2.apps.titulatec.services.synodal_inbox_service import SynodalInboxService

    ids = {p["id"] for p in SynodalInboxService.programs(mundo.db, mundo.jefe1.id)}

    assert ids == {mundo.p1.id, mundo.p2.id}
    assert {p["id"] for p in SynodalInboxService.programs(mundo.db, mundo.jefe2.id)} == {
        mundo.p3.id}


# ---------------------------------------------------------------------------
# 4. Alcance por departamento (R-D)
# ---------------------------------------------------------------------------
def test_cada_jefe_ve_solo_las_carreras_de_su_departamento(mundo):
    propio = mundo.nuevo(program=mundo.p1)
    ajeno = mundo.nuevo(program=mundo.p3)

    assert _ids(mundo.lista(user=mundo.jefe1)) == [propio.id]
    assert _ids(mundo.lista(user=mundo.jefe2)) == [ajeno.id]


def test_un_departamento_ajeno_en_el_filtro_no_abre_nada(mundo):
    mundo.nuevo(program=mundo.p3)

    ctx = mundo.lista(user=mundo.jefe1, department_id=mundo.d2.id)

    assert ctx["rows"] == [] and ctx["counts"] == {"pending": 0, "assigned": 0, "anexo": 0}


def test_read_all_ve_todos_los_departamentos_mapeados(mundo, lector_global):
    a = mundo.nuevo(program=mundo.p1)
    b = mundo.nuevo(program=mundo.p3)
    division = lector_global()

    assert _ids(mundo.lista(user=division, department_id=mundo.d1.id)) == [a.id]
    assert _ids(mundo.lista(user=division, department_id=mundo.d2.id)) == [b.id]
    todos = set(_ids(mundo.lista(user=division, per_page=1000)))
    assert {a.id, b.id} <= todos


def test_carrera_sin_departamento_no_sale_ni_con_read_all(mundo, lector_global):
    suelto = mundo.nuevo(program=mundo.suelta)
    division = lector_global()

    assert suelto.id not in _ids(mundo.lista(user=division, per_page=1000))
    assert suelto.id not in _ids(mundo.lista(user=mundo.jefe1))


def test_sin_departamento_a_cargo_no_ve_nada(mundo, make_user):
    mundo.nuevo()
    nadie = make_user(first_name="SIN", last_name="DEPARTAMENTO")

    ctx = mundo.lista(user=nadie)

    assert ctx["rows"] == [] and ctx["counts"] == {"pending": 0, "assigned": 0, "anexo": 0}


def test_departments_lista_los_que_opera(mundo, lector_global):
    from itcj2.apps.titulatec.services.synodal_inbox_service import SynodalInboxService

    assert [d["id"] for d in SynodalInboxService.departments(mundo.db, mundo.jefe1.id)] == [
        mundo.d1.id]
    ids = {d["id"] for d in SynodalInboxService.departments(mundo.db, lector_global().id)}
    assert {mundo.d1.id, mundo.d2.id} <= ids


# ---------------------------------------------------------------------------
# 5. `contains` y presupuesto de consultas
# ---------------------------------------------------------------------------
def test_contains_aplica_pestana_busqueda_carrera_y_alcance(mundo):
    from itcj2.apps.titulatec.services.synodal_inbox_service import SynodalInboxService

    control = f"99{_n():06d}"
    p = mundo.nuevo(program=mundo.p2, control=control)
    asignado = mundo.nuevo(phase=5, synodals=True)
    ajeno = mundo.nuevo(program=mundo.p3)

    def c(pid, user=mundo.jefe1, **kw):
        kw.setdefault("tab", "pending")
        return SynodalInboxService.contains(mundo.db, user.id, pid, **kw)

    assert c(p.id)
    assert not c(p.id, tab="assigned")
    assert c(asignado.id, tab="assigned")
    assert c(p.id, q=control) and not c(p.id, q="NOEXISTE-XYZ")
    assert c(p.id, program_id=mundo.p2.id) and not c(p.id, program_id=mundo.p1.id)
    assert not c(ajeno.id)
    assert c(ajeno.id, user=mundo.jefe2)
    assert not c(p.id, tab="zzz")


def test_la_lista_cuesta_lo_mismo_con_2_que_con_6_filas(mundo):
    for i in range(2):
        mundo.nuevo(started=T0 + timedelta(hours=i))
    mundo.lista()                       # calienta el alcance (permisos en caché)
    with _Contador(mundo.db.get_bind()) as c2:
        assert len(mundo.lista()["rows"]) == 2
    for i in range(4):
        mundo.nuevo(started=T0 + timedelta(days=1, hours=i))
    with _Contador(mundo.db.get_bind()) as c6:
        assert len(mundo.lista()["rows"]) == 6
    assert len(c2) == len(c6), "\n".join(c6.sentencias)
