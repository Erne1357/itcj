"""ACL del namespace Socket.IO /requests.

Los handlers de join hacían `enter_room` sin validar nada, así que cualquier
usuario autenticado podía emitir `join_drops {coord_id: N}` iterando N y
recibir en vivo `drop_created`, `appointment_created` y
`request_status_changed` de todas las carreras — con request_id, student_id,
program_id y status.

Se testean los helpers directamente contra la BD: son donde vive la decisión,
y montar un cliente Socket.IO real en pytest requiere un servidor corriendo.
La verificación de que los handlers los invocan está en el test de integración
del final.
"""
import inspect

import pytest

from itcj2.sockets.requests import (
    _can_read_social_sync,
    _is_that_coordinator_sync,
    register_request_namespace,
)


def _user(uid, role="staff"):
    return {"sub": str(uid), "role": role}


@pytest.fixture()
def acl_session(db_session, monkeypatch):
    """Hace que los helpers usen la sesión del test, sin que la cierren.

    Los helpers abren `SessionLocal()` y hacen `db.close()` en su `finally`.
    Monkeypatchear SessionLocal a secas cerraría la sesión de la fixture y
    cualquier aserción posterior fallaría con "session is closed". El proxy
    deja pasar todo menos close().
    """
    class _NoClose:
        def __init__(self, inner):
            self._inner = inner

        def __getattr__(self, name):
            return getattr(self._inner, name)

        def close(self):
            pass

    monkeypatch.setattr("itcj2.database.SessionLocal", lambda: _NoClose(db_session))
    return db_session


# ---------------------------------------------------------------------------
# _is_that_coordinator_sync
# ---------------------------------------------------------------------------
def test_coordinator_can_join_own_room(acl_session, coord_setup):
    ctx = coord_setup(n_programs=1)
    assert _is_that_coordinator_sync(_user(ctx["user"].id), ctx["coord"].id) is True


def test_coordinator_cannot_join_another_coordinators_room(acl_session, coord_setup,
                                                           make_program, make_coordinator):
    ctx = coord_setup(n_programs=1)
    otro_prog = make_program("Carrera Ajena ACL")
    otro_coord, _ = make_coordinator([otro_prog.id], first_name="OTRO", last_name="COORD")
    assert _is_that_coordinator_sync(_user(ctx["user"].id), otro_coord.id) is False


def test_student_cannot_join_any_coordinator_room(acl_session, coord_setup, make_user):
    """El vector del IDOR: un alumno iterando coord_id."""
    ctx = coord_setup(n_programs=1)
    alumno = make_user(first_name="ESPIA", last_name="ACL", control_number="20990300")
    assert _is_that_coordinator_sync(_user(alumno.id, role="student"), ctx["coord"].id) is False


def test_no_session_is_rejected():
    """Sin sesión no hay identidad: fail-closed."""
    assert _is_that_coordinator_sync(None, 1) is False


def test_global_admin_can_join(acl_session, coord_setup):
    """El admin global bypasea, como en require_perms."""
    ctx = coord_setup(n_programs=1)
    assert _is_that_coordinator_sync(_user(999999, role="admin"), ctx["coord"].id) is True


# ---------------------------------------------------------------------------
# _can_read_social_sync
# ---------------------------------------------------------------------------
def test_student_cannot_read_social_rooms(acl_session, make_user):
    alumno = make_user(first_name="ALUM", last_name="SOCIAL", control_number="20990301")
    assert _can_read_social_sync(_user(alumno.id, role="student")) is False


def test_no_session_cannot_read_social():
    assert _can_read_social_sync(None) is False


def test_admin_can_read_social():
    assert _can_read_social_sync(_user(1, role="admin")) is True


# ---------------------------------------------------------------------------
# Los handlers realmente invocan el ACL
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("handler,expected_guard", [
    ("on_join_ap_day", "_is_that_coordinator_sync"),
    ("on_join_drops", "_is_that_coordinator_sync"),
    ("on_join_social_ap_day", "_can_read_social_sync"),
])
def test_join_handlers_call_the_acl(handler, expected_guard):
    """Sin esto, los helpers podrían estar perfectos y no usarse.

    Se inspecciona el código fuente de los handlers registrados: es la forma
    de comprobar el cableado sin levantar un servidor Socket.IO real.
    """
    registered = {}

    class _FakeServer:
        def on(self, event, namespace=None):
            def deco(fn):
                registered[fn.__name__] = fn
                return fn
            return deco

    register_request_namespace(_FakeServer())

    assert handler in registered, f"{handler} no quedó registrado"
    src = inspect.getsource(registered[handler])
    assert expected_guard in src, f"{handler} no llama a {expected_guard}"
    assert "forbidden" in src, f"{handler} no rechaza con 'forbidden'"


def test_leave_handlers_do_not_need_acl():
    """Salirse de un room ajeno es inofensivo: no hay que bloquearlo.

    Documenta la decisión para que nadie "arregle" lo que no está roto.
    """
    registered = {}

    class _FakeServer:
        def on(self, event, namespace=None):
            def deco(fn):
                registered[fn.__name__] = fn
                return fn
            return deco

    register_request_namespace(_FakeServer())
    src = inspect.getsource(registered["on_leave_ap_day"])
    assert "_is_that_coordinator_sync" not in src
