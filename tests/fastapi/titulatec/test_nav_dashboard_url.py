"""A dónde aterriza cada rol en `/titulatec/` (`pages/nav.py::resolve_dashboard_url`).

Desde 2026-09-15 el alumno de titulación es `graduate`. `student` se queda como
respaldo: una fila vieja de `core_user_app_roles` que el backfill
(`survey_2026_09/14_graduate_role_backfill.sql`) todavía no movió no puede caer
en `/itcj/dashboard`, que a su vez la rebota al shell móvil sin ruta de vuelta.
"""
from __future__ import annotations

from itcj2.apps.titulatec.pages.nav import resolve_dashboard_url

STUDENT_DASHBOARD = "/titulatec/student/dashboard"


def test_graduate_aterriza_en_el_dashboard_del_alumno():
    assert resolve_dashboard_url({"graduate"}) == STUDENT_DASHBOARD


def test_student_sigue_de_respaldo_para_filas_viejas():
    assert resolve_dashboard_url({"student"}) == STUDENT_DASHBOARD


def test_un_oficial_que_tambien_es_graduate_aterriza_en_la_bandeja():
    """Los roles de oficial van primero: un encargado que se titula sigue trabajando."""
    assert (resolve_dashboard_url({"graduate", "titulatec_school_services"})
            == "/titulatec/admin/")


def test_sin_rol_de_la_app_vuelve_al_core():
    assert resolve_dashboard_url(set()) == "/itcj/dashboard"


def test_el_landing_manda_a_un_graduate_a_su_dashboard(
    client_as, make_user, make_role, grant_user_role,
):
    """Integración: el gate (`require_page_app` sin perms) pasa con la asignación y
    el landing resuelve contra los roles de la BD, no contra el JWT."""
    user = make_user(control_number="99150020", username="99150020")
    grant_user_role(user, make_role("graduate"))

    resp = client_as(user).get("/titulatec/", follow_redirects=False)

    assert resp.status_code == 302, resp.text[:300]
    assert resp.headers["location"] == STUDENT_DASHBOARD
