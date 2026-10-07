"""Autorización de las páginas de helpdesk sin consultas repetidas (perf 2026-10-07).

- La secretaría del Centro de Cómputo (`_get_users_with_position`) se pedía en
  cada `list_tickets`/`can_user_view_ticket`: asignar tickets hace 3 listas y el
  dashboard del técnico 4, todas en la misma sesión. Se recuerda en `db.info`
  hasta el siguiente commit o rollback.
- El menú (`_build_helpdesk_nav`) pedía permisos y roles sin caché en cada
  página; ahora salen de `cached_perms`/`cached_roles` (las mismas funciones
  envueltas, con la invalidación del caché de authz).
- `get_warehouse_perms_via_helpdesk` buscaba `helpdesk` y `warehouse` en
  `core_apps` con consultas propias; ahora usa `get_app_by_key` (memoria por
  sesión de core).
"""
from unittest.mock import MagicMock, patch

from sqlalchemy import event

import itcj2.models  # noqa: F401


def _contar_posiciones():
    from itcj2.core.services import authz_service

    return patch.object(authz_service, "_get_users_with_position",
                        wraps=authz_service._get_users_with_position)


def test_la_secretaria_se_pide_una_vez_por_sesion(db_session):
    from itcj2.apps.helpdesk.services.ticket_service import _secretary_cc_ids

    with _contar_posiciones() as espia:
        a = _secretary_cc_ids(db_session)
        b = _secretary_cc_ids(db_session)
    assert a == b
    assert espia.call_count == 1


def test_un_commit_olvida_la_secretaria(db_session):
    from itcj2.apps.helpdesk.services.ticket_service import _secretary_cc_ids

    with _contar_posiciones() as espia:
        _secretary_cc_ids(db_session)
        db_session.commit()
        _secretary_cc_ids(db_session)
    assert espia.call_count == 2


def test_un_rollback_olvida_la_secretaria(db_session):
    from itcj2.apps.helpdesk.services.ticket_service import _secretary_cc_ids

    with _contar_posiciones() as espia:
        _secretary_cc_ids(db_session)
        db_session.rollback()
        _secretary_cc_ids(db_session)
    assert espia.call_count == 2


def test_tres_listas_en_la_misma_sesion_piden_la_secretaria_una_vez(db_session):
    from itcj2.apps.helpdesk.services.ticket_service import list_tickets

    with _contar_posiciones() as espia:
        for status in ("PENDING", "ASSIGNED", "IN_PROGRESS"):
            list_tickets(db_session, user_id=999_999_001, user_roles=["admin"], status=status)
    assert espia.call_count == 1


def test_una_sesion_falsa_no_memoriza_y_consulta_como_siempre():
    from itcj2.apps.helpdesk.services.ticket_service import _secretary_cc_ids

    db = MagicMock()
    with patch("itcj2.core.services.authz_service._get_users_with_position",
               return_value=[7, 8]) as pedir:
        assert _secretary_cc_ids(db) == {7, 8}
        assert _secretary_cc_ids(db) == {7, 8}
    assert pedir.call_count == 2


def test_el_menu_sale_del_cache_de_authz():
    from itcj2.apps.helpdesk.pages.nav import _build_helpdesk_nav

    sin_cache_perms = MagicMock(side_effect=AssertionError("sin caché"))
    sin_cache_roles = MagicMock(side_effect=AssertionError("sin caché"))
    with patch("itcj2.core.services.authz_service.get_user_permissions_for_app", sin_cache_perms), \
         patch("itcj2.core.services.authz_service.user_roles_in_app", sin_cache_roles), \
         patch("itcj2.core.services.authz_cache.cached_perms",
               return_value={"helpdesk.tickets.page.list"}) as perms, \
         patch("itcj2.core.services.authz_cache.cached_roles", return_value={"admin"}) as roles, \
         patch("itcj2.apps.helpdesk.utils.warehouse_auth.get_warehouse_perms_via_helpdesk",
               return_value=set()), \
         patch("itcj2.database.SessionLocal", return_value=MagicMock()):
        _build_helpdesk_nav(10, "/help-desk/")
    sin_cache_perms.assert_not_called()
    sin_cache_roles.assert_not_called()
    assert perms.called and roles.called


def test_permisos_de_almacen_usan_la_memoria_de_apps(db_session):
    from itcj2.apps.helpdesk.utils.warehouse_auth import get_warehouse_perms_via_helpdesk
    from itcj2.core.services.authz_service import get_app_by_key

    get_app_by_key(db_session, "helpdesk")          # carga la memoria de la sesión
    sentencias = []

    def _registrar(conn, cursor, statement, *_a):
        sentencias.append(statement)

    bind = db_session.get_bind()
    event.listen(bind, "before_cursor_execute", _registrar)
    try:
        get_warehouse_perms_via_helpdesk(db_session, 999_999_001)
    finally:
        event.remove(bind, "before_cursor_execute", _registrar)
    assert not [s for s in sentencias if "FROM core_apps" in s], sentencias


def test_los_detalles_de_ticket_no_corren_en_el_event_loop():
    """Hacen BD síncrona: `def` (threadpool), no `async def`."""
    import inspect

    from itcj2.apps.helpdesk.pages import department, technician, user

    for mod in (user, technician, department):
        assert not inspect.iscoroutinefunction(mod.ticket_detail), mod.__name__


def test_el_dashboard_del_tecnico_no_corre_en_el_event_loop():
    import inspect

    from itcj2.apps.helpdesk.pages import technician

    assert not inspect.iscoroutinefunction(technician.dashboard)


def test_las_pestanas_reusan_la_sesion_que_reciben():
    """La página completa arma las 4 pestañas en UNA sesión: con `db` no se
    abre otra (así la secretaría, memorizada por sesión, se pide una vez)."""
    from itcj2.apps.helpdesk.pages import technician

    db = MagicMock()
    with patch("itcj2.database.SessionLocal",
               side_effect=AssertionError("no debe abrir otra sesión")), \
         patch("itcj2.apps.helpdesk.services.ticket_service.list_tickets",
               return_value={"tickets": [{"id": 1}]}) as listar:
        for tab in ("assigned", "inProgress", "resolved"):
            technician._query_tech_tickets(10, {"tech_soporte"}, tab, db=db)
    assert all(c.args[0] is db for c in listar.call_args_list)
    db.close.assert_not_called()
