"""Tablero de la jefa de Servicios Escolares (2026-10-14): permiso, menú, aterrizaje y rutas.

Permiso `titulatec.reports.page.view` (jefa de SE y `admin`). Solo se fija lo de
la Tarea 1: autorización de `/titulatec/admin/tablero` y `/body`, el menú y el
aterrizaje por rol. El contenido de las pestañas llega en tareas posteriores.
"""
from __future__ import annotations

import pytest

from itcj2.apps.titulatec.pages.nav import resolve_dashboard_url

URL = "/titulatec/admin/tablero"
BODY = f"{URL}/body"
PERM = "titulatec.reports.page.view"
TABS = ("panorama", "ritmo", "encargados", "carreras", "atorados")


@pytest.fixture()
def jefa(make_head):
    from tests.fastapi.titulatec.conftest import HEAD_PERMS
    return make_head(perm_codes=HEAD_PERMS + (PERM,))


def test_la_jefa_con_el_permiso_ve_la_pagina(client_as, jefa):
    r = client_as(jefa).get(URL)
    assert r.status_code == 200, r.text[:500]
    assert 'id="tt-report-body"' in r.text


def test_la_jefa_con_el_permiso_ve_el_parcial(client_as, jefa):
    r = client_as(jefa).get(BODY)
    assert r.status_code == 200, r.text[:500]
    assert 'id="tt-report-body"' in r.text


@pytest.mark.parametrize("tab", TABS + ("foo", "", "PANORAMA"))
def test_cualquier_tab_responde_200(client_as, jefa, tab):
    assert client_as(jefa).get(BODY, params={"tab": tab}).status_code == 200


def test_la_barra_tiene_las_cinco_pestanas_con_swap_outer_html(client_as, jefa):
    html = client_as(jefa).get(BODY).text
    for tab in TABS:
        assert f"/titulatec/admin/tablero/body?tab={tab}" in html
    assert 'hx-target="#tt-report-body"' in html
    assert 'hx-select="#tt-report-body"' in html
    assert 'hx-swap="morph:outerHTML"' in html


def _rol_con_acceso_a_la_app(db_session, make_user, make_role, grant_user_role, nombre, perms):
    user = make_user(first_name="ROL", last_name="FICTICIO")
    grant_user_role(user, make_role(nombre, perms))
    return user


def test_el_rol_admin_con_el_permiso_ve_pagina_y_parcial(
        client_as, db_session, make_user, make_role, grant_user_role):
    """En produccion `admin` recibe el permiso EXPLICITO del 26 (no del 15)."""
    from tests.fastapi.titulatec.conftest import HEAD_PERMS
    admin = _rol_con_acceso_a_la_app(db_session, make_user, make_role, grant_user_role,
                                     "admin", HEAD_PERMS + (PERM,))
    c = client_as(admin)
    assert c.get(URL).status_code == 200
    assert c.get(BODY).status_code == 200


def test_titulatec_titulaciones_real_sin_el_permiso_403(
        client_as, db_session, make_user, make_role, grant_user_role):
    """El rol REAL `titulatec_titulaciones` (sus permisos de la BD, que no traen
    `reports.page.view`) no entra al tablero."""
    from itcj2.core.models.permission import Permission
    from itcj2.core.models.role import Role
    from itcj2.core.models.role_permission import RolePermission

    rol = db_session.query(Role).filter_by(name="titulatec_titulaciones").first()
    if rol is None:
        pytest.skip("la base no tiene el rol titulatec_titulaciones sembrado")
    codes = [c for (c,) in db_session.query(Permission.code)
             .join(RolePermission, RolePermission.perm_id == Permission.id)
             .filter(RolePermission.role_id == rol.id, Permission.code.like("titulatec.%")).all()]
    assert PERM not in codes
    user = _rol_con_acceso_a_la_app(db_session, make_user, make_role, grant_user_role,
                                    "titulatec_titulaciones", tuple(codes))
    c = client_as(user)
    assert c.get(URL).status_code == 403
    assert c.get(BODY).status_code == 403


def test_el_encargado_recibe_403(client_as, make_officer, make_program):
    officer, _pos = make_officer([make_program("CARRERA TABLERO FICTICIA")])
    assert client_as(officer).get(URL).status_code == 403
    assert client_as(officer).get(BODY).status_code == 403


def test_con_otro_permiso_de_dashboard_pero_sin_el_del_tablero_403(client_as, make_head):
    user = make_head(perm_codes=("titulatec.dashboard.titulaciones",))
    assert client_as(user).get(URL).status_code == 403
    assert client_as(user).get(BODY).status_code == 403


def test_el_menu_trae_tablero_primero_con_el_permiso(jefa, db_session):
    from itcj2.apps.titulatec.pages.nav import admin_nav_items

    con = admin_nav_items(jefa.id, db_session)
    assert con[0] == {"label": "Tablero", "icon": "bi-speedometer2", "url": URL}


def test_el_menu_no_trae_tablero_sin_el_permiso(make_officer, make_program, db_session):
    from itcj2.apps.titulatec.pages.nav import admin_nav_items

    officer, _pos = make_officer([make_program("CARRERA TABLERO FICTICIA")])
    labels = [it["label"] for it in admin_nav_items(officer.id, db_session)]
    assert "Tablero" not in labels
    assert "Bandeja" in labels


def test_la_jefa_aterriza_en_el_tablero():
    assert resolve_dashboard_url({"titulatec_school_services_head"}) == URL


def test_admin_sigue_aterrizando_en_la_bandeja():
    assert (resolve_dashboard_url({"admin", "titulatec_school_services_head"})
            == "/titulatec/admin/")
