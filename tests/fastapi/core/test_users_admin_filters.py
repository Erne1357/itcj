"""F4 Task 1: list_users acepta q (alias canonico de search) y filtro app= real.

Direct-call style (patron F1b): se invoca la funcion del endpoint con la
db_session real-PG (savepoint); require_perms no aplica en llamada directa.
Los asserts de lista son tolerantes al envelope (pre/post flip de Task 4):
la forma exacta del envelope se fija en test_users_envelope_flip.py (Task 4).
"""
from datetime import date, timedelta

import pytest

from itcj2.core.api import users_admin


def _users_of(resp):
    data = resp["data"]
    return data if isinstance(data, list) else data["users"]


def _mk_user(db, first, last, username=None):
    from itcj2.core.models.user import User
    u = User(first_name=first, last_name=last, username=username, is_active=True)
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _mk_app(db, key):
    from itcj2.core.models.app import App
    a = App(key=key, name=key.upper(), is_active=True)
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


def _mk_role(db, name):
    from itcj2.core.models.role import Role
    r = Role(name=name)
    db.add(r)
    db.commit()
    db.refresh(r)
    return r


def _call(db, **kw):
    args = dict(search="", q=None, role=None, status=None, app=None,
                only_staff=False, page=1, per_page=50,
                user={"sub": "1"}, db=db)
    args.update(kw)
    return users_admin.list_users(**args)


def test_q_filters_like_search(db_session):
    _mk_user(db_session, "ZZF4Q", "ALPHA", username="zzf4_alpha")
    _mk_user(db_session, "ZZF4Q", "BETA", username="zzf4_beta")

    # full_name se serializa como "{last} {first}" (User.full_name) → el termino
    # multi-palabra respeta ese orden real del modelo.
    resp = _call(db_session, q="ALPHA ZZF4Q")
    names = [u["full_name"] for u in _users_of(resp)]
    assert any("ALPHA" in n for n in names)
    assert not any("BETA" in n for n in names)


def test_q_takes_precedence_over_search(db_session):
    _mk_user(db_session, "ZZF4Q", "GAMMA", username="zzf4_gamma")
    resp = _call(db_session, q="GAMMA ZZF4Q", search="zz_no_such_user_xyz")
    assert len(_users_of(resp)) >= 1


def test_app_filter_direct_role(db_session):
    app = _mk_app(db_session, "zzf4app")
    role = _mk_role(db_session, "zzf4role")
    u_in = _mk_user(db_session, "ZZF4APP", "CON", username="zzf4_con")
    _mk_user(db_session, "ZZF4APP", "SIN", username="zzf4_sin")

    from itcj2.core.models.user_app_role import UserAppRole
    db_session.add(UserAppRole(user_id=u_in.id, app_id=app.id, role_id=role.id))
    db_session.commit()

    resp = _call(db_session, q="ZZF4APP", app="zzf4app")
    assert [u["id"] for u in _users_of(resp)] == [u_in.id]


def test_app_filter_via_position(db_session):
    app = _mk_app(db_session, "zzf4app2")
    role = _mk_role(db_session, "zzf4role2")
    u_pos = _mk_user(db_session, "ZZF4POS", "PUESTO", username="zzf4_pos")

    from itcj2.core.models.position import Position, UserPosition, PositionAppRole
    pos = Position(code="zzf4_pos_code", title="ZZF4 Pos", is_active=True, allows_multiple=True)
    db_session.add(pos)
    db_session.flush()
    db_session.add(UserPosition(user_id=u_pos.id, position_id=pos.id,
                                start_date=date.today(), is_active=True))
    db_session.add(PositionAppRole(position_id=pos.id, app_id=app.id, role_id=role.id))
    db_session.commit()

    resp = _call(db_session, q="ZZF4POS", app="zzf4app2")
    assert [u["id"] for u in _users_of(resp)] == [u_pos.id]


def test_app_filter_excludes_expired_position(db_session):
    """F4/1.2: puesto is_active=True pero end_date vencido NO debe otorgar acceso.

    Espeja _active_position_filter() (authz_service.py) — la fuente de verdad
    de has_any_assignment. Antes del fix, _app_access_user_ids solo miraba
    UserPosition.is_active y colaba usuarios con ventana vencida.
    """
    app = _mk_app(db_session, "zzf4app_exp")
    role = _mk_role(db_session, "zzf4role_exp")
    u_pos = _mk_user(db_session, "ZZF4EXP", "VENCIDO", username="zzf4_exp")

    from itcj2.core.models.position import Position, UserPosition, PositionAppRole
    pos = Position(code="zzf4_exp_code", title="ZZF4 Exp", is_active=True, allows_multiple=True)
    db_session.add(pos)
    db_session.flush()
    db_session.add(UserPosition(
        user_id=u_pos.id, position_id=pos.id,
        start_date=date.today() - timedelta(days=30),
        end_date=date.today() - timedelta(days=1),
        is_active=True,
    ))
    db_session.add(PositionAppRole(position_id=pos.id, app_id=app.id, role_id=role.id))
    db_session.commit()

    resp = _call(db_session, q="ZZF4EXP", app="zzf4app_exp")
    assert _users_of(resp) == []


def test_app_filter_includes_position_with_null_or_future_end_date(db_session):
    """F4/1.2: puesto vigente (end_date NULL o futuro) SI otorga acceso."""
    app = _mk_app(db_session, "zzf4app_fut")
    role = _mk_role(db_session, "zzf4role_fut")
    u_null = _mk_user(db_session, "ZZF4FUT", "NULLEND", username="zzf4_fut_null")
    u_future = _mk_user(db_session, "ZZF4FUT", "FUTUREEND", username="zzf4_fut_future")

    from itcj2.core.models.position import Position, UserPosition, PositionAppRole
    pos = Position(code="zzf4_fut_code", title="ZZF4 Fut", is_active=True, allows_multiple=True)
    db_session.add(pos)
    db_session.flush()
    db_session.add(UserPosition(
        user_id=u_null.id, position_id=pos.id,
        start_date=date.today() - timedelta(days=5), end_date=None, is_active=True,
    ))
    db_session.add(UserPosition(
        user_id=u_future.id, position_id=pos.id,
        start_date=date.today() - timedelta(days=5),
        end_date=date.today() + timedelta(days=5), is_active=True,
    ))
    db_session.add(PositionAppRole(position_id=pos.id, app_id=app.id, role_id=role.id))
    db_session.commit()

    resp = _call(db_session, q="ZZF4FUT", app="zzf4app_fut")
    ids = {u["id"] for u in _users_of(resp)}
    assert ids == {u_null.id, u_future.id}


def test_app_filter_unknown_key_returns_empty(db_session):
    _mk_user(db_session, "ZZF4NADA", "X", username="zzf4_nada")
    resp = _call(db_session, q="ZZF4NADA", app="zz_app_inexistente")
    assert _users_of(resp) == []


def test_by_app_still_lists_assigned_users(db_session):
    """Regresion: list_users_by_app sigue funcionando tras extraer el helper."""
    app = _mk_app(db_session, "zzf4app3")
    role = _mk_role(db_session, "zzf4role3")
    u = _mk_user(db_session, "ZZF4BYAPP", "UNO", username="zzf4_byapp")

    from itcj2.core.models.user_app_role import UserAppRole
    db_session.add(UserAppRole(user_id=u.id, app_id=app.id, role_id=role.id))
    db_session.commit()

    resp = users_admin.list_users_by_app(
        app_key="zzf4app3", search="", page=1, per_page=20,
        user={"sub": "1", "role": "admin"}, db=db_session,
    )
    assert u.id in [x["id"] for x in _users_of(resp)]
