"""Botón «?» del alumno: directorio de encargadas de carrera, solo en fases 1 y 2.

El botón vive en `student/base_student.html` y abre `#tt-help-modal`, que va en
el bloque `modals` de la misma base (cita.html lo pisa y debe llamar `super()`).
"""
from __future__ import annotations

from pathlib import Path

import pytest

IMG = Path(__file__).resolve().parents[3] / "itcj2/apps/titulatec/static/images/directorio-encargadas.jpg"


def test_la_imagen_del_directorio_existe():
    assert IMG.read_bytes()[:3] == b"\xff\xd8\xff"


@pytest.mark.parametrize("fase, url", [
    (1, "/titulatec/student/dashboard"),
    (2, "/titulatec/student/dashboard"),
    (1, "/titulatec/student/documents"),
    (2, "/titulatec/student/perfil"),
    (2, "/titulatec/student/cita"),
])
def test_fases_1_y_2_muestran_el_boton_y_el_modal(
    client_as, make_student, make_process, seed_phase_defs, fase, url,
):
    seed_phase_defs()
    student = make_student()
    make_process(student, current_phase=fase)

    resp = client_as(student).get(url)

    assert resp.status_code == 200, resp.text[:300]
    assert 'id="tt-help-btn"' in resp.text
    assert 'id="tt-help-modal"' in resp.text
    assert "images/directorio-encargadas.jpg" in resp.text


@pytest.mark.parametrize("url", ["/titulatec/student/dashboard", "/titulatec/student/perfil"])
def test_fase_3_no_muestra_el_boton(client_as, make_student, make_process, seed_phase_defs, url):
    seed_phase_defs()
    student = make_student()
    make_process(student, current_phase=3)

    resp = client_as(student).get(url)

    assert resp.status_code == 200, resp.text[:300]
    assert 'id="tt-help-btn"' not in resp.text


def test_sin_proceso_no_muestra_el_boton(client_as, make_student, seed_phase_defs):
    seed_phase_defs()
    student = make_student()

    resp = client_as(student).get("/titulatec/student/dashboard")

    assert resp.status_code == 200, resp.text[:300]
    assert 'id="tt-help-btn"' not in resp.text
