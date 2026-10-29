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


def test_titulatec_tech_management_aterriza_en_liberaciones():
    """GTV (Tarea 6, 2026-09-15): bandeja propia, no la de Escolares."""
    assert (resolve_dashboard_url({"titulatec_tech_management"})
            == "/titulatec/admin/liberaciones")


def test_un_actor_de_escolares_y_de_gtv_aterriza_por_escolares():
    """Spec §8 ("liberacion-gtv"): "aterriza por el primero que coincida en
    `_ROLE_DASHBOARD`". Los roles de Escolares van ANTES que GTV en la lista,
    así que un actor con ambos sigue viendo primero la bandeja de Escolares
    (y, aparte, TODOS los items que sus permisos alcancen en el menú -- eso
    lo cubre `test_survey_reviews_admin_routes.py`, que sí necesita BD)."""
    # La jefa aterriza en el Tablero desde 2026-10-14 (D9).
    assert (resolve_dashboard_url(
        {"titulatec_school_services_head", "titulatec_tech_management"})
        == "/titulatec/admin/tablero")
    assert (resolve_dashboard_url(
        {"titulatec_school_services", "titulatec_tech_management"})
        == "/titulatec/admin/")


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


LIBERADOS = "/titulatec/admin/liberados"


def test_titulacion_aterriza_en_liberados():
    """D1 (spec 2026-10-07 §1.2): el Departamento de Titulación ya no ve la
    Bandeja; su pantalla de trabajo es Liberados."""
    assert resolve_dashboard_url({"titulatec_titulacion"}) == LIBERADOS


def test_titulaciones_sigue_ganando_a_titulacion():
    """La jefatura de la División (sin cambios) va antes en `_ROLE_DASHBOARD`."""
    assert (resolve_dashboard_url({"titulatec_titulaciones", "titulatec_titulacion"})
            == "/titulatec/admin/")


def test_un_actor_de_escolares_y_de_titulacion_aterriza_por_escolares():
    """Titulación es ahora una bandeja propia (como GTV, Cómputo, Biblioteca o
    Caja) y va DESPUÉS de los roles con Bandeja completa."""
    assert (resolve_dashboard_url({"titulatec_school_services", "titulatec_titulacion"})
            == "/titulatec/admin/")


def test_el_landing_manda_a_titulacion_a_liberados(
    client_as, db_session, make_user, make_role, grant_user_role,
):
    """Con el nombre REAL del rol (el landing resuelve por nombre). Desde la
    fase 3 (spec 2026-10-21 §8.1) el rol con `titulatec.titulacion.page.list`
    aterriza en la pestaña Titulación; SIN él, en Liberados. La base de dev ya
    puede traer ese permiso (`init-titulatec-fase-2`): se quita dentro del
    savepoint. El caso con el permiso vive en `test_titulacion_admin.py`."""
    from itcj2.core.models.permission import Permission
    from itcj2.core.models.role_permission import RolePermission

    rol = make_role("titulatec_titulacion")
    ids = [pid for (pid,) in db_session.query(Permission.id)
           .filter(Permission.code == "titulatec.titulacion.page.list").all()]
    if ids:
        db_session.query(RolePermission).filter(
            RolePermission.role_id == rol.id, RolePermission.perm_id.in_(ids),
        ).delete(synchronize_session=False)
        db_session.flush()
    user = make_user(first_name="JEFA", last_name="TITULACION")
    grant_user_role(user, rol)

    resp = client_as(user).get("/titulatec/", follow_redirects=False)

    assert resp.status_code == 302, resp.text[:300]
    assert resp.headers["location"] == LIBERADOS


ACCESOS = "/titulatec/admin/accesos"


def test_titulatec_computer_center_aterriza_en_accesos():
    """Centro de Cómputo (spec 2026-09-24 §8.2): bandeja propia, con el nombre
    REAL del rol que siembra `01_insert_roles.sql`."""
    assert resolve_dashboard_url({"titulatec_computer_center"}) == ACCESOS


def test_la_jefatura_de_computo_aterriza_por_admin():
    """D2: `head_comp_center` trae además `admin` por su puesto, y `admin` va
    primero en `_ROLE_DASHBOARD`: aterriza en la Bandeja y ve Accesos en el menú."""
    assert (resolve_dashboard_url({"admin", "titulatec_computer_center"})
            == "/titulatec/admin/")


def test_el_landing_manda_a_centro_de_computo_a_accesos(
    client_as, make_user, make_role, grant_user_role,
):
    user = make_user(first_name="CENTRO", last_name="COMPUTO")
    grant_user_role(user, make_role("titulatec_computer_center"))

    resp = client_as(user).get("/titulatec/", follow_redirects=False)

    assert resp.status_code == 302, resp.text[:300]
    assert resp.headers["location"] == ACCESOS


# --- Aterrizaje tolerante de la jefa (spec 2026-10-14-titulatec-cli-paquete §1) ---

TABLERO = "/titulatec/admin/tablero"
REPORTS_PERM = "titulatec.reports.page.view"
BANDEJA = "/titulatec/admin/"


def test_jefa_con_el_permiso_en_perms_aterriza_en_el_tablero():
    assert (resolve_dashboard_url({"titulatec_school_services_head"}, perms={REPORTS_PERM})
            == TABLERO)


def test_jefa_sin_el_permiso_en_perms_aterriza_en_la_bandeja():
    """Entre el deploy y `titulatec init-reportes` la jefa no recibe un 403."""
    assert (resolve_dashboard_url({"titulatec_school_services_head"}, perms=set())
            == BANDEJA)
    assert (resolve_dashboard_url({"titulatec_school_services_head"},
                                  perms={"titulatec.dashboard.school_services"})
            == BANDEJA)


def test_sin_perms_se_conserva_el_comportamiento_por_rol():
    """`perms=None` (otros llamadores): solo roles, como antes."""
    assert resolve_dashboard_url({"titulatec_school_services_head"}) == TABLERO


def test_perms_no_cambia_a_admin_ni_a_los_demas_roles():
    assert resolve_dashboard_url({"admin"}, jwt_role="admin", perms=set()) == BANDEJA
    assert (resolve_dashboard_url({"titulatec_school_services_head"}, jwt_role="admin",
                                  perms={REPORTS_PERM}) == BANDEJA)
    assert resolve_dashboard_url({"titulatec_computer_center"}, perms=set()) == ACCESOS
    assert resolve_dashboard_url({"graduate"}, perms=set()) == STUDENT_DASHBOARD
    assert resolve_dashboard_url({"titulatec_school_services"}, perms=set()) == BANDEJA
    assert resolve_dashboard_url(set(), perms=set()) == "/itcj/dashboard"


def _jefa_real(db_session, make_user, make_role, grant_user_role, *, con_permiso):
    """Usuario con el rol REAL `titulatec_school_services_head` (el landing resuelve
    por nombre de rol). La base de dev puede traer ya el permiso (tras
    `init-reportes`): se pone o se quita dentro del savepoint de la prueba."""
    from itcj2.core.models.permission import Permission
    from itcj2.core.models.role_permission import RolePermission
    from tests.fastapi.titulatec.conftest import HEAD_PERMS

    sin = tuple(p for p in HEAD_PERMS if p != REPORTS_PERM)
    rol = make_role("titulatec_school_services_head",
                    sin + ((REPORTS_PERM,) if con_permiso else ()))
    if not con_permiso:
        perm_ids = [pid for (pid,) in db_session.query(Permission.id)
                    .filter(Permission.code == REPORTS_PERM).all()]
        if perm_ids:
            db_session.query(RolePermission).filter(
                RolePermission.role_id == rol.id,
                RolePermission.perm_id.in_(perm_ids),
            ).delete(synchronize_session=False)
            db_session.flush()
    user = make_user(first_name="JEFA", last_name="FICTICIA")
    grant_user_role(user, rol)
    return user


def test_el_landing_manda_a_la_jefa_con_el_permiso_al_tablero(
    client_as, db_session, make_user, make_role, grant_user_role,
):
    jefa = _jefa_real(db_session, make_user, make_role, grant_user_role, con_permiso=True)

    resp = client_as(jefa).get("/titulatec/", follow_redirects=False)

    assert resp.status_code == 302, resp.text[:300]
    assert resp.headers["location"] == TABLERO


def test_el_landing_manda_a_la_jefa_sin_el_permiso_a_la_bandeja(
    client_as, db_session, make_user, make_role, grant_user_role,
):
    jefa = _jefa_real(db_session, make_user, make_role, grant_user_role, con_permiso=False)

    resp = client_as(jefa).get("/titulatec/", follow_redirects=False)

    assert resp.status_code == 302, resp.text[:300]
    assert resp.headers["location"] == BANDEJA
