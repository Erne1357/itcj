"""Un cambio de puesto invalida el caché de SUS OCUPANTES, no el del mundo.

Antes, las siete mutaciones de configuración de un puesto llamaban a
`invalidate_all()`, que barre `authz:v1:{roles,perms,has}:*` — la caché de las
seis apps y de todos los usuarios. Correcto pero desproporcionado: propaga un
cambio que toca a un puñado de personas tirando la caché de miles, y el
`scan_iter` sobre todo el keyspace corre en el hilo único de Redis, compartido
con Socket.IO, Celery y los holds de AgendaTec.

Estos tests fijan el alcance nuevo:

- rol/permiso EN una app  → `invalidate_user_app(uid, app_key)` por ocupante.
- activar/desactivar/borrar el puesto → `invalidate_user(uid)` (cruza apps).
- las mutaciones que DESASIGNAN a los ocupantes leen la lista ANTES de hacerlo.
- si la lista no se puede resolver, se cae a `invalidate_all()` (enfriar de más
  es aceptable; servir un permiso revocado hasta el TTL no).

Ninguna toca la época de sesión: eso es el keyspace de `session_service` y lo
cubre `test_authz_cache_keyspace_isolation.py`.
"""
from datetime import date
from unittest.mock import patch

import pytest

import itcj2.models  # noqa: F401
from itcj2.core.models.app import App
from itcj2.core.models.permission import Permission
from itcj2.core.models.position import Position, PositionAppPerm, PositionAppRole, UserPosition
from itcj2.core.models.role import Role
from itcj2.core.models.user import User
from itcj2.core.services import positions_service as ps

APP = "helpdesk"


@pytest.fixture()
def busts():
    """Espía las tres funciones de invalidación del caché de authz.

    Se parchean en `authz_cache` (no en `positions_service`) porque el import es
    local dentro de `_bust_position`: parchear el nombre en el módulo llamador
    no interceptaría nada.
    """
    with patch("itcj2.core.services.authz_cache.invalidate_user_app") as ua, \
         patch("itcj2.core.services.authz_cache.invalidate_user") as u, \
         patch("itcj2.core.services.authz_cache.invalidate_all") as all_:
        yield ua, u, all_


def _user(db, last):
    u = User(first_name="P", last_name=last, is_active=True)
    db.add(u); db.commit(); db.refresh(u)
    return u


def _position(db, code):
    p = Position(code=code, title=code, is_active=True, allows_multiple=True)
    db.add(p); db.commit(); db.refresh(p)
    return p


def _assign(db, user, position):
    db.add(UserPosition(user_id=user.id, position_id=position.id,
                        start_date=date.today(), is_active=True))
    db.commit()


def _role(db, name):
    r = db.query(Role).filter_by(name=name).first()
    if not r:
        r = Role(name=name)
        db.add(r); db.commit(); db.refresh(r)
    return r


def _perm(db, code):
    app = db.query(App).filter_by(key=APP).one()
    p = db.query(Permission).filter_by(app_id=app.id, code=code).first()
    if not p:
        p = Permission(app_id=app.id, code=code, name=code, description=code)
        db.add(p); db.commit(); db.refresh(p)
    return p


def _occupied(db, code, n=2):
    """Puesto con `n` ocupantes vivos. Devuelve (position, [user_ids])."""
    pos = _position(db, code)
    uids = []
    for i in range(n):
        u = _user(db, f"{code}{i}")
        _assign(db, u, pos)
        uids.append(u.id)
    return pos, uids


# ---------------------------------------------------------------------------
# Rol / permiso EN una app → acotado a (ocupantes × esa app)
# ---------------------------------------------------------------------------
def test_assign_role_to_position_busts_only_occupants_in_that_app(db_session, busts):
    ua, u, all_ = busts
    pos, uids = _occupied(db_session, "pis_assign_role")
    _role(db_session, "student")

    assert ps.assign_role_to_position(db_session, pos.id, APP, "student") is True

    assert {c.args for c in ua.call_args_list} == {(uid, APP) for uid in uids}
    all_.assert_not_called()
    u.assert_not_called()


def test_remove_role_from_position_busts_only_occupants_in_that_app(db_session, busts):
    ua, u, all_ = busts
    pos, uids = _occupied(db_session, "pis_remove_role")
    role = _role(db_session, "student")
    app = db_session.query(App).filter_by(key=APP).one()
    db_session.add(PositionAppRole(position_id=pos.id, app_id=app.id, role_id=role.id))
    db_session.commit()
    ua.reset_mock()

    assert ps.remove_role_from_position(db_session, pos.id, APP, "student") is True

    assert {c.args for c in ua.call_args_list} == {(uid, APP) for uid in uids}
    all_.assert_not_called()


def test_remove_role_that_was_not_assigned_busts_nothing(db_session, busts):
    """Sin borrado no hay cambio que propagar — ni acotado ni global."""
    ua, u, all_ = busts
    pos, _uids = _occupied(db_session, "pis_remove_noop")
    _role(db_session, "student")

    assert ps.remove_role_from_position(db_session, pos.id, APP, "student") is False

    ua.assert_not_called()
    all_.assert_not_called()


def test_assign_permission_to_position_busts_only_occupants_in_that_app(db_session, busts):
    ua, u, all_ = busts
    pos, uids = _occupied(db_session, "pis_assign_perm")
    _perm(db_session, "pis.perm.alta")
    ua.reset_mock()

    assert ps.assign_permission_to_position(db_session, pos.id, APP, "pis.perm.alta") is True

    assert {c.args for c in ua.call_args_list} == {(uid, APP) for uid in uids}
    all_.assert_not_called()


def test_flipping_allow_on_existing_position_perm_also_busts_occupants(db_session, busts):
    """La rama de UPDATE (`existing.allow = allow`) es un DENY nuevo: propagar."""
    ua, u, all_ = busts
    pos, uids = _occupied(db_session, "pis_flip_perm")
    perm = _perm(db_session, "pis.perm.flip")
    app = db_session.query(App).filter_by(key=APP).one()
    db_session.add(PositionAppPerm(position_id=pos.id, app_id=app.id,
                                   perm_id=perm.id, allow=True))
    db_session.commit()
    ua.reset_mock()

    assert ps.assign_permission_to_position(
        db_session, pos.id, APP, "pis.perm.flip", allow=False) is True

    assert {c.args for c in ua.call_args_list} == {(uid, APP) for uid in uids}
    all_.assert_not_called()


def test_position_without_occupants_busts_nobody(db_session, busts):
    """Configurar un puesto vacío no debe tocar la caché de nadie."""
    ua, u, all_ = busts
    pos = _position(db_session, "pis_vacio")
    _role(db_session, "student")

    ps.assign_role_to_position(db_session, pos.id, APP, "student")

    ua.assert_not_called()
    u.assert_not_called()
    all_.assert_not_called()


# ---------------------------------------------------------------------------
# Ciclo de vida del puesto → ocupantes en TODAS las apps
# ---------------------------------------------------------------------------
def test_toggling_position_active_busts_occupants_across_apps(db_session, busts):
    ua, u, all_ = busts
    pos, uids = _occupied(db_session, "pis_toggle")

    ps.update_position(db_session, pos.id, is_active=False)

    assert {c.args[0] for c in u.call_args_list} == set(uids)
    ua.assert_not_called()   # sin app_key: el puesto puede conceder en varias
    all_.assert_not_called()


def test_updating_a_field_that_is_not_is_active_busts_nothing(db_session, busts):
    ua, u, all_ = busts
    pos, _uids = _occupied(db_session, "pis_rename")

    ps.update_position(db_session, pos.id, title="Otro titulo")

    u.assert_not_called()
    ua.assert_not_called()
    all_.assert_not_called()


def test_deactivate_position_reads_occupants_before_unassigning_them(db_session, busts):
    """Regresión de ORDEN: `deactivate_position` apaga las `UserPosition` en el
    mismo commit. Leer la lista DESPUÉS devuelve vacío y no se invalidaría a
    nadie — el permiso retirado seguiría autorizando hasta el TTL (300s)."""
    ua, u, all_ = busts
    pos, uids = _occupied(db_session, "pis_deactivate")

    assert ps.deactivate_position(db_session, pos.id) is True

    assert {c.args[0] for c in u.call_args_list} == set(uids)
    assert ps.position_user_ids(db_session, pos.id) == []  # ya no hay a quién leer
    all_.assert_not_called()


def test_delete_position_reads_occupants_before_the_cascade(db_session, busts):
    """Mismo orden que el anterior, pero aquí el CASCADE borra las filas."""
    ua, u, all_ = busts
    pos, uids = _occupied(db_session, "pis_delete")
    pos_id = pos.id

    assert ps.delete_position(db_session, pos_id) is True

    assert {c.args[0] for c in u.call_args_list} == set(uids)
    all_.assert_not_called()


# ---------------------------------------------------------------------------
# Fallback
# ---------------------------------------------------------------------------
def test_falls_back_to_invalidate_all_when_occupants_cannot_be_resolved(db_session, busts):
    """Si la consulta de ocupantes truena, enfriar de más > servir stale."""
    ua, u, all_ = busts
    with patch.object(ps, "position_user_ids", side_effect=RuntimeError("db caida")):
        ps._bust_position(db_session, 12345, APP)
    all_.assert_called_once()
    ua.assert_not_called()


def test_bust_position_never_raises_into_the_mutation(db_session, busts):
    """Ni el fallback puede tumbar la mutación que ya se commiteó."""
    ua, u, all_ = busts
    all_.side_effect = RuntimeError("redis caido")
    with patch.object(ps, "position_user_ids", side_effect=RuntimeError("db caida")):
        ps._bust_position(db_session, 12345, APP)  # no debe propagar
