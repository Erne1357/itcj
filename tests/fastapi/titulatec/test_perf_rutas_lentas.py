"""Rutas lentas de TitulaTec (perf 2026-10-07, rama `perf/rutas-lentas`).

Lo medido en prod (Loki, desde el deploy del 2026-10-06 14:53) y en dev con los
mismos usuarios:

* Citas del encargado (`GET /admin/appointments`, p95 134 ms): los días de
  revisión se leían 3 veces (día por omisión, carril y tablero) y las ventanas
  del día del tablero 2 más; el carril y el tablero contaban la ocupación por
  separado. Ahora `_shell_ctx` lee UNA vez días, ventanas y ocupación
  (`_carril`) y los presta.
* Espacios (la vista y su `POST /espacios/{id}`, ~140 ms): una consulta de
  ocupación POR VENTANA y las ventanas del día pedidas dos veces. Ahora una
  lectura de ventanas y un `window_occupancy_map`.
* «Mis documentos» del alumno: dos consultas por espacio (tipo y documento) y la
  carrera leída tres veces. Ahora tipos y documentos en lote y el perfil una vez.
* Tablero del alumno: la carrera se leía dos veces (el identity map es de
  referencias DÉBILES: la primera ya no estaba).
* «Mi cita»: el proceso acreditable se buscaba 3 veces y las cancelaciones 2.

Cada prueba fija «no crece» o «una sola lectura» sobre filas SEMBRADAS, nunca un
total absoluto (la BD de dev es compartida), y la de equivalencia compara el
resultado con y sin lo prestado.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import event

from tests.fastapi.titulatec.conftest import INITIAL_DOC_TYPES, POSGRADO_DOC_TYPES


class _Sentencias(list):
    def tocan(self, fragmento: str) -> list[str]:
        return [s for s in self if fragmento in s]


def _medir(db_session, fn) -> _Sentencias:
    sentencias = _Sentencias()

    def _ver(_conn, _cursor, statement, *_a):
        sentencias.append(" ".join(statement.split()))

    conn = db_session.connection()
    event.listen(conn, "before_cursor_execute", _ver)
    try:
        fn()
    finally:
        event.remove(conn, "before_cursor_execute", _ver)
    return sentencias


# ---------------------------------------------------------------------------
# Citas del encargado: días, ventanas y ocupación UNA vez
# ---------------------------------------------------------------------------
@pytest.fixture()
def agenda(db_session, seed_phase_defs, make_program, make_cohort, make_review_day,
           make_officer, make_review_window):
    """Convocatoria nueva (la activa) con `n_dias` días abiertos y `n_ventanas`
    del encargado por día, más una de otra persona y un día CERRADO."""
    seed_phase_defs()

    def construir(n_dias, n_ventanas, base):
        prog = make_program(f"Ing. Perf Rutas {n_dias}x{n_ventanas} {base:%m%d}")
        cohort = make_cohort()
        off, _ = make_officer([prog])
        otro, _ = make_officer([prog], first_name="OTRA")
        dias = []
        for i in range(n_dias):
            fila = make_review_day(cohort, day=base + timedelta(days=i))
            for j in range(n_ventanas):
                make_review_window(fila, off, start=f"{8 + j:02d}:00",
                                   end=f"{8 + j:02d}:45", slot=15, cap=2)
            make_review_window(fila, otro, start="16:00", end="17:00", slot=30)
            dias.append(fila)
        cerrado = make_review_day(cohort, day=base + timedelta(days=n_dias))
        cerrado.is_closed = True
        db_session.flush()
        return {"prog": prog, "cohort": cohort, "off": off, "dias": dias,
                "cerrado": cerrado}

    return construir


@pytest.mark.usefixtures("authz_congelada")
def test_la_agenda_lee_dias_y_ventanas_una_sola_vez(db_session, agenda):
    from itcj2.apps.titulatec.pages.appointments import _shell_ctx

    s = agenda(3, 2, date(2031, 3, 3))
    dia = s["dias"][1].date

    def vista():
        return _shell_ctx(db_session, user_id=s["off"].id, v="agenda",
                          date_raw=dia.isoformat())

    vista()                                    # calienta alcance y catálogos
    db_session.expire_all()
    sql = _medir(db_session, vista)

    assert len(sql.tocan("FROM titulatec_cohort_review_days")) == 1, sql
    assert len(sql.tocan("FROM titulatec_review_windows")) == 1, sql


@pytest.mark.usefixtures("authz_congelada")
def test_el_tablero_y_el_carril_dicen_lo_mismo_con_y_sin_lo_prestado(db_session, agenda):
    from itcj2.apps.titulatec.pages.appointments import _board_ctx, _carril, _dias_ctx

    s = agenda(3, 3, date(2031, 4, 7))
    cid, uid, allowed = s["cohort"].id, s["off"].id, {s["prog"].id}
    hoy = date(2031, 1, 1)
    for dia in [f.date for f in s["dias"]] + [s["cerrado"].date]:
        carril = _carril(db_session, cid)
        assert (_board_ctx(db_session, dia, allowed, user_id=uid, cohort_id=cid,
                           carril=carril)
                == _board_ctx(db_session, dia, allowed, user_id=uid, cohort_id=cid)), dia
        assert (_dias_ctx(db_session, cid, abierto=dia, today=hoy, carril=carril)
                == _dias_ctx(db_session, cid, abierto=dia, today=hoy)), dia


@pytest.mark.usefixtures("authz_congelada")
def test_espacios_no_crece_con_las_ventanas_del_dia(db_session, agenda):
    from itcj2.apps.titulatec.pages.appointments import _shell_ctx

    def medir(s):
        dia = s["dias"][0].date

        def vista():
            return _shell_ctx(db_session, user_id=s["off"].id, v="espacios",
                              date_raw=dia.isoformat())

        ctx = vista()
        db_session.expire_all()
        return _medir(db_session, vista), ctx

    chico, ctx_chico = medir(agenda(1, 2, date(2031, 5, 5)))
    grande, ctx_grande = medir(agenda(1, 5, date(2031, 6, 2)))

    assert len(ctx_chico["espacios"]["mios"]) == 2 and len(ctx_grande["espacios"]["mios"]) == 5
    assert len(ctx_grande["espacios"]["ajenos"]) == 1
    assert len(chico) == len(grande), (len(chico), len(grande))
    # La ocupación de la vista Espacios: UNA consulta (más la del carril).
    assert len(grande.tocan("scheduled_at")) == len(chico.tocan("scheduled_at"))


def test_espacios_cuenta_igual_que_por_ventana(db_session, agenda, make_student,
                                              make_process, make_appointment):
    """Mismo `ocupados/capacidad` que `window_occupancy` ventana por ventana."""
    from itcj2.apps.titulatec.pages.appointments import _espacios_ctx
    from itcj2.apps.titulatec.services.slot_service import SlotService

    s = agenda(1, 3, date(2031, 7, 7))
    fila = s["dias"][0]
    ventanas = SlotService.windows_for_day(db_session, fila.id, solo_abiertas=False)
    for v in ventanas[:2]:
        proc = make_process(make_student(), cohort=s["cohort"], program=s["prog"],
                            current_phase=2)
        a = make_appointment(proc, when=datetime.combine(fila.date, v.start_time))
        a.window_id = v.id
    db_session.flush()

    ctx = _espacios_ctx(db_session, fila.date, user_id=s["off"].id,
                        cohort_id=s["cohort"].id)
    por_id = {m["id"]: (m["ocupados"], m["capacidad"]) for m in ctx["mios"]}
    for v in ventanas:
        if v.owner_user_id == s["off"].id:
            assert por_id[v.id] == SlotService.window_occupancy(db_session, v)
    assert [m["id"] for m in ctx["mios"]] == [
        v.id for v in ventanas if v.owner_user_id == s["off"].id]


# ---------------------------------------------------------------------------
# Páginas del alumno
# ---------------------------------------------------------------------------
STUDENT_PERMS = (
    "titulatec.dashboard.student",
    "titulatec.document.api.read.own",
    "titulatec.document.api.upload.own",
    "titulatec.document.api.delete.own",
    "titulatec.appointment.page.my",
)


@pytest.fixture()
def alumno(db_session, seed_phase_defs, seed_document_types, make_cohort, make_student,
           make_process):
    def _build(program=None, current_phase=1):
        seed_phase_defs()
        seed_document_types(types=INITIAL_DOC_TYPES + POSGRADO_DOC_TYPES)
        student = make_student(perm_codes=STUDENT_PERMS)
        proc = make_process(student, cohort=make_cohort(), program=program,
                            current_phase=current_phase)
        db_session.commit()
        return student, proc
    return _build


@pytest.mark.usefixtures("authz_congelada")
def test_mis_documentos_no_crece_con_los_espacios(db_session, alumno, client_as,
                                                 make_program):
    def medir(student):
        c = client_as(student)
        assert c.get("/titulatec/student/documents").status_code == 200   # calienta
        db_session.expire_all()
        holder = {}
        sql = _medir(db_session, lambda: holder.setdefault(
            "r", c.get("/titulatec/student/documents")))
        assert holder["r"].status_code == 200
        return sql, holder["r"].text

    lic, html_lic = medir(alumno(program=make_program("Ing. Perf Documentos Lic"))[0])
    pos, html_pos = medir(alumno(program=make_program("Maestria Perf Documentos",
                                                       level="maestria"))[0])

    assert html_lic.count('id="slot-') == 3 and html_pos.count('id="slot-') == 7
    # Tipos y documentos: los MISMOS SELECT con 3 que con 7 espacios -- uno del
    # lote de la página y uno del resumen del aviso de pie --, nunca uno por
    # espacio. (El total difiere en 1 a propósito: con extras de posgrado sin
    # subir, R-G lee una vez el número de fase de `initial_docs`.)
    for tabla in ("FROM titulatec_document_types", "FROM titulatec_documents "):
        assert len(lic.tocan(tabla)) == len(pos.tocan(tabla)) == 2, tabla
    for sql in (lic, pos):
        assert len(sql.tocan("FROM core_programs")) == 1, sql


@pytest.mark.usefixtures("authz_congelada")
def test_el_tablero_del_alumno_lee_su_carrera_una_vez(db_session, alumno, client_as,
                                                     make_program):
    student, _ = alumno(program=make_program("Ing. Perf Tablero"))
    c = client_as(student)
    assert c.get("/titulatec/student/dashboard").status_code == 200
    db_session.expire_all()
    sql = _medir(db_session, lambda: c.get("/titulatec/student/dashboard"))
    assert len(sql.tocan("FROM core_programs")) == 1, sql


@pytest.mark.usefixtures("authz_congelada")
def test_mi_cita_busca_el_proceso_y_las_cancelaciones_una_vez(
        db_session, alumno, client_as, make_survey_review, make_appointment):
    student, proc = alumno(current_phase=2)
    make_survey_review(proc, status="approved")
    make_appointment(proc, status="scheduled")
    db_session.commit()
    c = client_as(student)
    assert c.get("/titulatec/student/cita", follow_redirects=False).status_code == 200
    db_session.expire_all()
    holder = {}
    sql = _medir(db_session, lambda: holder.setdefault(
        "r", c.get("/titulatec/student/cita", follow_redirects=False)))
    assert holder["r"].status_code == 200

    # `creditable_process` filtra por el alumno y el estado: una sola vez.
    acreditable = [s for s in sql.tocan("FROM titulatec_processes")
                   if "titulatec_processes.student_id" in s]
    assert len(acreditable) == 1, acreditable
    # El conteo de cancelaciones (cifra y bloqueo de D9): una sola vez.
    assert len(sql.tocan("cancelled_by_id IS NOT NULL")) == 1, sql
