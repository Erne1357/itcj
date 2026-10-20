"""Buscador de la Agenda: también encuentra a los alumnos SIN cita (D8, spec
2026-09-29-titulatec-cotejo-espacios-design.md §4).

Reusa la fábrica de cubos de `test_appt_queue_buckets.py` (mismo universo:
pendientes, bloqueados, rechazados -con y sin cita viva- y sin encuesta
liberada, todos en la MISMA carrera y ya probados uno por uno ahí): el
buscador filtra EN PYTHON sobre esas mismas listas, así que aquí solo hace
falta ejercitar el filtro de texto, el de `program_id` y el de `estado`.
"""
from __future__ import annotations

from datetime import date
from urllib.parse import quote

import lxml.html
import pytest

from tests.fastapi.titulatec.test_appt_queue_buckets import cola  # noqa: F401 (fixture reusada)

URL = "/titulatec/admin/appointments"
# Mismo día que fabrica `cola` (`test_appt_queue_buckets.py`): un solo día de
# cotejo, así que `_default_day` no puede interferir si se nos olvida `date=`.
_D = date(2029, 5, 7)


def _buscar(client_as, actor, q, **extra):
    params = {"date": _D.isoformat(), "q": q, **extra}
    qs = "&".join(f"{k}={quote(str(v))}" for k, v in params.items())
    return client_as(actor).get(f"{URL}?{qs}")


def _fila(html, process_id):
    hallazgos = lxml.html.fromstring(html).xpath(
        '//*[@id="appt-sincita-%d"]' % process_id)
    return hallazgos[0] if hallazgos else None


def _control(db_session, proc):
    from itcj2.core.models.user import User
    return db_session.get(User, proc.student_id).control_number


# ===========================================================================
# Las cuatro fuentes (D8, §4): pendientes, bloqueados, rechazados SIN cita
# viva y sin encuesta liberada -- las mismas que ya prueba
# `test_appt_queue_buckets.py`, una por una.
# ===========================================================================
def test_un_pendiente_sale_como_sin_cita_y_es_abrible(cola, client_as, db_session):
    resp = _buscar(client_as, cola["off"], _control(db_session, cola["pendiente"]))

    assert resp.status_code == 200, resp.text[:300]
    fila = _fila(resp.text, cola["pendiente"].id)
    assert fila is not None, "el pendiente no aparece en «Sin cita»"
    assert fila.tag == "a", "un pendiente SÍ está en `visibles`: tiene que abrir"
    assert fila.get("hx-get") == (
        f"{URL}?v=atender&date={_D.isoformat()}&selected={cola['pendiente'].id}")


def test_un_bloqueado_tambien_sale_abrible(cola, client_as, db_session):
    resp = _buscar(client_as, cola["off"], _control(db_session, cola["bloqueado"]))

    fila = _fila(resp.text, cola["bloqueado"].id)
    assert fila is not None
    assert fila.tag == "a"


def test_rechazado_sin_cita_viva_sale_pero_con_cita_viva_no(cola, client_as, db_session):
    """`rech_sin_cita` (fase 02 rechazada, JAMÁS tuvo cita) SÍ está "sin cita".
    `rechazado` (fase 02 rechazada, pero con una `attended` VIGENTE esperando
    dictamen) NO -- ese no le falta cita, le falta que el encargado dictamine."""
    sin_cita = _buscar(client_as, cola["off"],
                       _control(db_session, cola["rech_sin_cita"]))
    con_cita = _buscar(client_as, cola["off"],
                       _control(db_session, cola["rechazado"]))

    assert _fila(sin_cita.text, cola["rech_sin_cita"].id) is not None
    assert _fila(con_cita.text, cola["rechazado"].id) is None


def test_encuesta_sin_liberar_sale_sin_enlace(cola, client_as, db_session):
    """D1: no está en `visibles` -- no hay ficha que darle todavía. Fila con
    la píldora de su estado real, sin `hx-get`."""
    resp = _buscar(client_as, cola["off"], _control(db_session, cola["sin_encuesta"]))

    fila = _fila(resp.text, cola["sin_encuesta"].id)
    assert fila is not None
    assert fila.tag == "div", "sin liberar: sin `visibles`, sin ficha que abrir"
    assert not fila.get("hx-get")
    assert "Encuesta pendiente" in fila.text_content()


# ===========================================================================
# Filtros de la vista (`estado`, `program_id`) y `casefold`
# ===========================================================================
def test_con_estado_no_hay_filas_sin_cita(cola, client_as, db_session):
    """Un estado de CITA no puede casar con quien no tiene ninguna."""
    resp = _buscar(client_as, cola["off"], _control(db_session, cola["pendiente"]),
                   estado="scheduled")

    assert resp.status_code == 200
    filas = lxml.html.fromstring(resp.text).xpath(
        '//*[starts-with(@id, "appt-sincita-")]')
    assert not filas


def test_casefold_no_importan_mayusculas(cola, client_as):
    resp = _buscar(client_as, cola["off"], "pendiente")

    assert _fila(resp.text, cola["pendiente"].id) is not None


def test_el_folio_tambien_sirve_de_busqueda(cola, client_as):
    resp = _buscar(client_as, cola["off"], cola["pendiente"].folio.lower())

    assert _fila(resp.text, cola["pendiente"].id) is not None


@pytest.fixture()
def dos_carreras(seed_phase_defs, seed_document_types, make_program, make_cohort,
                 make_review_day, make_officer, make_student, make_process,
                 make_document, make_survey_review):
    """Un encargado con DOS carreras (para que `program_id` filtre de verdad y
    no repita lo que ya prueba el alcance por carrera): un pendiente en cada
    una, mismo apellido para que la búsqueda case con los dos a la vez."""
    seed_phase_defs()
    seed_document_types()
    prog_a = make_program("Ingeniería del Buscador A")
    prog_b = make_program("Ingeniería del Buscador B")
    cohort = make_cohort()
    make_review_day(cohort, day=_D)
    officer, pos = make_officer([prog_a, prog_b])

    def _pendiente(control, program):
        st = make_student(last_name="DELBUSCADOR", control_number=control)
        proc = make_process(st, cohort=cohort, program=program, current_phase=2)
        for code in ("birth_certificate", "high_school_cert", "curp"):
            make_document(proc, type_code=code, review_status="approved")
        make_survey_review(proc, status="approved")
        return proc

    p_a = _pendiente("99200001", prog_a)
    p_b = _pendiente("99200002", prog_b)
    return {"prog_a": prog_a, "prog_b": prog_b, "off": officer,
            "p_a": p_a, "p_b": p_b}


def test_de_otra_carrera_no_sale_con_el_filtro_de_programa(dos_carreras, client_as):
    esc = dos_carreras

    sin_filtro = _buscar(client_as, esc["off"], "DELBUSCADOR")
    assert _fila(sin_filtro.text, esc["p_a"].id) is not None
    assert _fila(sin_filtro.text, esc["p_b"].id) is not None, (
        "control positivo: sin filtro, las DOS carreras del encargado salen")

    con_filtro = _buscar(client_as, esc["off"], "DELBUSCADOR",
                         program_id=esc["prog_a"].id)
    assert _fila(con_filtro.text, esc["p_a"].id) is not None
    assert _fila(con_filtro.text, esc["p_b"].id) is None, (
        "`program_id` no filtró: la otra carrera del MISMO encargado no debía salir")
