"""Menú del alumno por etapa (UI fase 3, T1).

`student_nav_items` (pages/nav.py) decide los ítems «Ahora» y «Consultar» con los
mismos predicados que abren cada página. Aquí se prueba el menú YA PINTADO (rail
de `base_student.html`): qué grupos salen, qué ítems y cuál lleva `aria-current`.

Todo se siembra con las fábricas del conftest (nunca con datos de la base de dev).
Los casos que operan fases >= 3 fijan el corte en 9; los de inercia lo bajan a 3.
"""
from __future__ import annotations

from datetime import datetime

import lxml.html
import pytest

from itcj2.apps.titulatec.services.phase_service import PhaseService
from tests.fastapi.titulatec.conftest import ROLE_STUDENT, STUDENT_PERMS

DASH = "/titulatec/student/dashboard"
DOCS = "/titulatec/student/documents"

EXTRA_PERMS = (
    "titulatec.format_b.page.fill",
    "titulatec.chat.page.view",
    "titulatec.chat.api.read",
)


@pytest.fixture(autouse=True)
def _sesiones(patched_session_local):
    return None


@pytest.fixture()
def corte(monkeypatch):
    def _fijar(fase):
        monkeypatch.setattr(PhaseService, "_handoff_phase", staticmethod(lambda: fase))
    return _fijar


def _menu(html: str) -> dict:
    """Lee el rail: `{"now": [...], "consult": [...], "current": [...], "all": [...]}`."""
    doc = lxml.html.fromstring(html)
    rail = doc.xpath('//nav[contains(@class, "tt-rail-nav")]')[0]
    grupo = None
    out = {"now": [], "consult": [], "current": [], "all": []}
    for el in rail:
        if el.get("data-tt-nav-group"):
            grupo = el.get("data-tt-nav-group")
            continue
        etiqueta = " ".join(el.text_content().split())
        out["all"].append(etiqueta)
        if el.get("aria-current") == "page":
            out["current"].append(etiqueta)
        if etiqueta in ("Inicio", "Perfil"):
            continue
        out[grupo].append(etiqueta)
    return out


@pytest.fixture()
def alumno(db_session, make_student, make_process, seed_phase_defs, seed_document_types,
           make_role):
    """Alumno con proceso en la fase pedida (por número o por código del catálogo)."""
    def _build(fase, *, status="active"):
        seed_phase_defs()
        seed_document_types()
        make_role(ROLE_STUDENT, STUDENT_PERMS + EXTRA_PERMS)
        student = make_student()
        n = fase if isinstance(fase, int) else PhaseService.phase_number_for_code(db_session, fase)
        proc = make_process(student, current_phase=n, status=status)
        db_session.commit()
        return student, proc
    return _build


def test_fase_1_ahora_es_documentos(client_as, alumno, corte):
    corte(3)
    student, _ = alumno(1)

    resp = client_as(student).get(DASH)

    assert resp.status_code == 200, resp.text[:500]
    assert _menu(resp.text) == {
        "now": ["Documentos"], "consult": [],
        "current": ["Inicio"], "all": ["Inicio", "Documentos", "Perfil"],
    }


def test_fase_2_ahora_es_la_cita(client_as, alumno, corte):
    corte(3)
    student, _ = alumno(2)

    m = _menu(client_as(student).get(DASH).text)

    assert m["now"] == ["Cita de cotejo"]
    assert m["consult"] == []


def test_fase_2_con_reemplazo_abierto_suma_documentos(client_as, alumno, corte, make_document,
                                                       db_session):
    corte(3)
    student, proc = alumno(2)
    make_document(proc, type_code="birth_certificate", review_status="rejected",
                  replacement_requested_at=datetime(2026, 1, 5, 10, 0), note="Ilegible")
    db_session.commit()

    m = _menu(client_as(student).get(DASH).text)

    assert m["now"] == ["Cita de cotejo", "Documentos"]
    assert m["consult"] == []


def test_fase_3_con_corte_9_ofrece_formato_b_y_no_documentos_ni_cita(client_as, alumno, corte):
    corte(9)
    student, _ = alumno("format_b")

    m = _menu(client_as(student).get(DASH).text)

    assert m["now"] == ["Formato B"]
    assert "Documentos" not in m["all"] and "Cita de cotejo" not in m["all"]
    assert m["consult"] == []


def test_fase_3_con_corte_3_solo_inicio_y_perfil(client_as, alumno, corte):
    corte(3)
    student, _ = alumno("format_b")

    m = _menu(client_as(student).get(DASH).text)

    assert m["all"] == ["Inicio", "Perfil"]
    assert m["now"] == [] and m["consult"] == []


def test_fase_6_ahora_anexo_y_consulta_formato_b_y_revision(
    client_as, db_session, make_anexo_case, make_role, corte,
):
    corte(9)
    make_role(ROLE_STUDENT, STUDENT_PERMS + EXTRA_PERMS)
    caso = make_anexo_case()
    db_session.commit()

    m = _menu(client_as(caso.student).get(DASH).text)

    assert m["now"] == ["Anexo III"]
    assert m["consult"] == ["Formato B", "Revisión"]
    assert m["all"] == ["Inicio", "Anexo III", "Formato B", "Revisión", "Perfil"]


def test_fase_6_con_corte_6_no_ofrece_el_anexo(
    client_as, db_session, make_anexo_case, make_role, corte,
):
    """El corte manda: con el corte en 6 la fase 6 ya no se opera aquí (la 5 sí, en consulta)."""
    corte(6)
    make_role(ROLE_STUDENT, STUDENT_PERMS + EXTRA_PERMS)
    caso = make_anexo_case()
    db_session.commit()

    m = _menu(client_as(caso.student).get(DASH).text)

    assert "Anexo III" not in m["all"]
    assert m["now"] == []
    assert m["consult"] == ["Formato B", "Revisión"]


def test_sin_proceso_solo_inicio_y_perfil(client_as, make_student, seed_phase_defs, corte, db_session):
    corte(9)
    seed_phase_defs()
    student = make_student()
    db_session.commit()

    m = _menu(client_as(student).get(DASH).text)

    assert m["all"] == ["Inicio", "Perfil"]


def test_proceso_revocado_solo_inicio_y_perfil(client_as, alumno, corte):
    corte(9)
    student, _ = alumno("format_b", status="cancelled")

    m = _menu(client_as(student).get(DASH).text)

    assert m["all"] == ["Inicio", "Perfil"]


def test_sin_el_permiso_de_la_pantalla_no_hay_liga(client_as, db_session, make_student, make_process,
                                                    seed_phase_defs, corte):
    """La liga no se ofrece si la página daría 403: Formato B exige `format_b.page.fill`."""
    corte(9)
    seed_phase_defs()
    student = make_student()
    make_process(student, current_phase=PhaseService.phase_number_for_code(db_session, "format_b"))
    db_session.commit()

    m = _menu(client_as(student).get(DASH).text)

    assert m["all"] == ["Inicio", "Perfil"]


def test_la_pagina_activa_lleva_aria_current(client_as, alumno, corte):
    corte(3)
    student, _ = alumno(1)

    resp = client_as(student).get(DOCS)

    assert resp.status_code == 200, resp.text[:500]
    m = _menu(resp.text)
    assert m["current"] == ["Documentos"]
    assert m["now"] == ["Documentos"]


def test_si_el_calculo_falla_el_menu_es_el_minimo(client_as, alumno, corte, monkeypatch):
    corte(3)
    student, _ = alumno(1)
    import itcj2.apps.titulatec.pages.nav as nav

    def _roto(db, uid):
        raise RuntimeError("falla simulada")

    monkeypatch.setattr(nav, "_student_nav_compute", _roto)

    resp = client_as(student).get(DASH)

    assert resp.status_code == 200
    assert _menu(resp.text)["all"] == ["Inicio", "Perfil"]


# ---------------------------------------------------------------------------
# Presupuesto de consultas del cálculo del menú (sobre filas sembradas aquí)
# ---------------------------------------------------------------------------
def _sentencias(db_session, fn):
    from sqlalchemy import event

    visto: list[str] = []

    def _ver(conn, cursor, statement, params, context, executemany):
        visto.append(" ".join(statement.split()))

    conexion = db_session.get_bind()
    event.listen(conexion, "before_cursor_execute", _ver)
    try:
        fn()
    finally:
        event.remove(conexion, "before_cursor_execute", _ver)
    return visto


def test_presupuesto_fase_1_y_fase_6(alumno, corte, db_session, make_anexo_case, make_role):
    """Fase 1 (lo que vive en producción): proceso + catálogo + `can_student_act`
    (catálogo de fases) y los permisos con la caché; fase 6 (solo dev, corte 9) paga las guardas
    de lectura de Revisión y Anexo. Techo fijo, no crece con N."""
    from itcj2.apps.titulatec.pages.nav import student_nav_items

    corte(3)
    student, _ = alumno(1)
    student_nav_items(student.id)  # tibia la caché de permisos
    n1 = len(_sentencias(db_session, lambda: student_nav_items(student.id)))
    assert n1 <= 5, n1

    corte(9)
    make_role(ROLE_STUDENT, STUDENT_PERMS + EXTRA_PERMS)
    caso = make_anexo_case()
    db_session.commit()
    student_nav_items(caso.student.id)
    n6 = len(_sentencias(db_session, lambda: student_nav_items(caso.student.id)))
    assert n6 <= 14, n6
    print(f"consultas del menu: fase1={n1} fase6={n6}")
