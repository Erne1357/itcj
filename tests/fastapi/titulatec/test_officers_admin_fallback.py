"""Respaldo de `_managed_department_id` para el rol `admin` EN TITULATEC.

Por que existe
---------------
El usuario `admin` de bootstrap (id 7676 en dev) no tiene NINGUN puesto del
organigrama, asi que `positions_service.get_user_primary_managed_department`
siempre le devuelve `None`: sin respaldo, la pestana Encargados le queda
inutilizable ("Sin departamento") aunque tenga el rol `admin` con TODOS los
permisos de titulatec (`database/DML/titulatec/15_grant_admin_all_perms.sql`).
`_managed_department_id` (`pages/officers.py`) ahora le asigna Servicios
Escolares (`core_departments.code = 'school_services'`) cuando, y SOLO cuando,
el usuario tiene el rol literal `admin` en la app titulatec
(`authz_service.user_roles_in_app`) -- tener SOLO el permiso
`titulatec.officers.api.manage` NO activa este respaldo.

Se usa el rol REAL `admin` (no uno ficticio con prefijo `tt_test_*`, a
diferencia del resto de este harness) porque el respaldo esta atado al NOMBRE
del rol. En dev ese rol ya existe con permisos de otras apps; `make_role` es
idempotente y solo AGREGA los permisos de titulatec que le faltan dentro del
savepoint del test, nunca quita nada, y el rollback final no deja rastro.

Regla de oro del modulo hermano (`test_officers_authz.py`): ninguna asercion
negativa va sola. El caso (b) reafirma, con un rol explicitamente DISTINTO de
`admin`, que las regresiones existentes
(`test_officers_authz.py::test_sin_departamento_gestionado_no_muta` /
`_no_desactiva`) siguen protegidas: tener los permisos de `officers.*` sin el
rol `admin` y sin puesto de jefatura sigue sin mutar nada.
"""
from __future__ import annotations

_OFFICER_ADMIN_PERMS = (
    "titulatec.officers.page.list",
    "titulatec.officers.api.manage",
)

_URL = "/titulatec/admin/officers"


def test_admin_en_titulatec_sin_puesto_ve_y_da_de_alta_en_servicios_escolares(
    client_as, db_session, make_user, make_role, grant_user_role, make_department,
):
    """(a) rol `admin` en titulatec, sin puesto -> sin aviso de "sin departamento"
    y el alta aterriza en Servicios Escolares."""
    depto = make_department(code="school_services", name="Servicios Escolares (ficticio)")
    admin_role = make_role("admin", _OFFICER_ADMIN_PERMS)
    # El rol que `officers.py::ROLE_ASSIGNED` cuelga del puesto nuevo, con su
    # nombre LITERAL: sin el, `create_officer` -> `assign_role_to_position`
    # revienta con "Role 'titulatec_school_services' does not exist" y el POST
    # contesta 400. En dev lo siembra `database/DML/titulatec/`, asi que este
    # test pasaba ahi y fallaba en CI, que arranca de una base vacia
    # (create_all sin DML). Medido contra `itcj_ci` el 2026-09-18.
    make_role("titulatec_school_services", _OFFICER_ADMIN_PERMS)
    admin_user = make_user(first_name="ADMIN", last_name="BOOTSTRAP")
    grant_user_role(admin_user, admin_role)

    resp_get = client_as(admin_user).get(_URL)
    assert resp_get.status_code == 200, resp_get.text[:300]
    assert "Sin departamento" not in resp_get.text, (
        "el admin sin puesto no deberia ver el aviso de departamento faltante")

    resp_post = client_as(admin_user).post(
        _URL, data={"name": "TT Admin Fallback Officer"})

    assert resp_post.status_code == 200, resp_post.text[:300]
    assert "TT Admin Fallback Officer" in resp_post.text, (
        "el encargado creado deberia aparecer en el parcial re-renderizado")

    from itcj2.core.models.position import Position
    creado = (db_session.query(Position)
              .filter(Position.department_id == depto.id,
                      Position.title == "TT Admin Fallback Officer")
              .first())
    assert creado is not None, (
        "el alta via admin no aterrizo como Position en Servicios Escolares")
    assert creado.code.startswith("se_officer_")


def test_con_los_permisos_pero_sin_rol_admin_y_sin_puesto_sigue_en_400(
    client_as, db_session, make_user, make_role, grant_user_role, make_department,
):
    """(b) mismos permisos `officers.*`, rol DISTINTO de `admin`, sin puesto de
    jefatura -> sigue sin departamento gestionado (400, nada se muta). El
    respaldo no puede activarse por el permiso solo."""
    make_department(code="school_services", name="Servicios Escolares (ficticio)")
    otro_rol = make_role("tt_test_officers_perms_no_admin", _OFFICER_ADMIN_PERMS)
    actor = make_user(first_name="SIN", last_name="ROL_ADMIN")
    grant_user_role(actor, otro_rol)

    resp_post = client_as(actor).post(_URL, data={"name": "No deberia existir"})

    assert resp_post.status_code == 400, resp_post.text[:300]
    assert resp_post.headers.get("X-Tt-Error"), "el error viaja por el canal de la app"

    from itcj2.core.models.position import Position
    creado = (db_session.query(Position)
              .filter(Position.title == "No deberia existir").first())
    assert creado is None, "no debio crearse ningun encargado"


def test_admin_en_titulatec_que_gestiona_otro_depto_da_de_alta_en_servicios_escolares(
    client_as, db_session, make_user, make_role, grant_user_role, make_department,
    make_position, assign_position,
):
    """(c) Revisión final, efecto de D2: la jefatura de Centro de Cómputo tiene el
    rol `admin` en titulatec Y gestiona su propio departamento. Encargados es de
    Servicios Escolares: con el rol `admin` el alta va SIEMPRE ahí, nunca a
    «encargados de SE» creados dentro de Cómputo."""
    from itcj2.core.models.position import Position

    se = make_department(code="school_services", name="Servicios Escolares (ficticio)")
    computo = make_department(name="Centro de Computo (ficticio)")
    jefatura = make_position(code=f"head_{computo.code}", title="Jefatura CC ficticia",
                             department=computo)
    admin_role = make_role("admin", _OFFICER_ADMIN_PERMS)
    make_role("titulatec_school_services", _OFFICER_ADMIN_PERMS)
    jefa = make_user(first_name="JEFA", last_name="DE COMPUTO")
    assign_position(jefa, jefatura)
    grant_user_role(jefa, admin_role)

    resp = client_as(jefa).post(_URL, data={"name": "TT Encargado Desde CC"})

    assert resp.status_code == 200, resp.headers.get("X-Tt-Error") or resp.text[:300]
    creado = (db_session.query(Position)
              .filter(Position.title == "TT Encargado Desde CC").one())
    assert creado.department_id == se.id, (
        "el encargado nació en el departamento que la jefa gestiona, no en SE")
    assert creado.department_id != computo.id
