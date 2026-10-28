"""
Tests API de configuracion de asignacion automatica y correo al asignar
(`/api/help-desk/v2/config/auto-assign` y `/assignment-email`). Prefijo de datos: aa6_.
"""
import time
from unittest.mock import patch

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func

import itcj2.models  # noqa: F401
from itcj2.apps.helpdesk.models.area import Area
from itcj2.apps.helpdesk.models.assignment_rule import AssignmentRule
from itcj2.apps.helpdesk.models.config_change_log import ConfigChangeLog
from itcj2.apps.helpdesk.models.helpdesk_settings import HelpdeskSettings
from itcj2.config import get_settings
from itcj2.core.models.app import App
from itcj2.core.models.user import User
from itcj2.core.models.user_app_role import UserAppRole
from itcj2.database import get_db
from itcj2.main import create_app

from ._catalog import ensure_helpdesk_category, ensure_helpdesk_priority, ensure_role

BASE = "/api/help-desk/v2/config"


@pytest.fixture()
def client(db_session):
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _headers(user_id):
    # JWT admin de un usuario REAL (rule.created_by_id y el log tienen FK a core_users).
    now = int(time.time())
    token = jwt.encode(
        {"sub": str(user_id), "role": "admin", "cn": None, "name": "Admin",
         "iat": now, "exp": now + 3600},
        get_settings().SECRET_KEY, algorithm="HS256")
    return {"Cookie": f"itcj_token={token}"}


def _user(db, last, email=None, active=True):
    u = User(first_name="T", last_name=f"aa6_{last}", email=email, is_active=active)
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _tech(db, user, role_name):
    app = db.query(App).filter_by(key="helpdesk").first()
    role = ensure_role(db, role_name)
    db.add(UserAppRole(user_id=user.id, app_id=app.id, role_id=role.id))
    db.commit()


@pytest.fixture()
def world(db_session):
    db = db_session
    for code in ("DESARROLLO", "SOPORTE"):
        if not db.query(Area).filter_by(code=code).first():
            db.add(Area(code=code, label=code.capitalize(), is_active=True))
    db.commit()
    ensure_helpdesk_priority(db, "ALTA")
    admin = _user(db, "admin")
    a = _user(db, "A", email="a@x.mx")
    b = _user(db, "B")  # sin correo
    c = _user(db, "C", email="c@x.mx")
    outsider = _user(db, "Z")
    _tech(db, a, "tech_desarrollo")
    _tech(db, b, "tech_desarrollo")
    _tech(db, c, "tech_soporte")
    _tech(db, a, "tech_soporte")  # A con los dos roles
    cat = ensure_helpdesk_category(db, "aa6_sii", "DESARROLLO")
    cat_sop = ensure_helpdesk_category(db, "aa6_hw", "SOPORTE")
    # Base dev con datos reales: se vacían dentro de la transacción del test.
    db.query(HelpdeskSettings).delete()
    db.query(AssignmentRule).delete()
    db.commit()
    audit_mark = db.query(func.max(ConfigChangeLog.id)).scalar() or 0
    return dict(admin=admin, a=a, b=b, c=c, out=outsider, cat=cat, cat_sop=cat_sop,
                h=_headers(admin.id), audit_mark=audit_mark)


def _body(w, **kw):
    d = {"area": "DESARROLLO", "category_id": w["cat"].id, "priority": None,
         "strategy": "round_robin", "technician_ids": [w["a"].id, w["b"].id]}
    d.update(kw)
    return d


def _post(client, w, **kw):
    return client.post(f"{BASE}/auto-assign/rules", json=_body(w, **kw), headers=w["h"])


class TestAutoAssign:
    def test_get_sin_fila_settings_da_defaults(self, client, world):
        r = client.get(f"{BASE}/auto-assign", headers=world["h"])
        assert r.status_code == 200
        d = r.json()["data"]
        assert d["enabled"] is False and d["rules"] == []
        cats = d["catalogs"]
        assert {"areas", "categories", "priorities", "technicians_by_area"} <= cats.keys()
        assert world["a"].id in [t["id"] for t in cats["technicians_by_area"]["DESARROLLO"]]
        assert world["a"].id in [t["id"] for t in cats["technicians_by_area"]["SOPORTE"]]
        assert "ALTA" in [p["code"] for p in cats["priorities"]]

    def test_switch_maestro_audita(self, client, db_session, world):
        r = client.patch(f"{BASE}/auto-assign/settings", json={"enabled": True}, headers=world["h"])
        assert r.status_code == 200
        assert client.get(f"{BASE}/auto-assign", headers=world["h"]).json()["data"]["enabled"] is True
        assert db_session.query(ConfigChangeLog).filter(
            ConfigChangeLog.entity_type == "helpdesk_settings",
            ConfigChangeLog.id > world["audit_mark"]).count() == 1

    def test_crud_feliz_y_auditoria(self, client, db_session, world):
        r = _post(client, world)
        assert r.status_code == 201
        rid = r.json()["data"]["id"]
        r = client.patch(f"{BASE}/auto-assign/rules/{rid}",
                         json={"strategy": "least_loaded", "is_active": False}, headers=world["h"])
        assert r.status_code == 200
        rules = client.get(f"{BASE}/auto-assign", headers=world["h"]).json()["data"]["rules"]
        assert len(rules) == 1
        rule = rules[0]
        assert rule["strategy"] == "least_loaded" and rule["is_active"] is False
        assert rule["category_name"] == world["cat"].name
        assert [t["id"] for t in rule["technicians"]] == [world["a"].id, world["b"].id]
        assert all(t["eligible"] for t in rule["technicians"])
        assert rule["last_assigned_name"] is None
        assert client.delete(f"{BASE}/auto-assign/rules/{rid}", headers=world["h"]).status_code == 200
        assert db_session.query(AssignmentRule).count() == 0
        acts = [l.action for l in db_session.query(ConfigChangeLog)
                .filter_by(entity_type="assignment_rule").order_by(ConfigChangeLog.id)]
        assert acts == ["create", "update", "delete"]

    def test_terna_repetida_409_tambien_con_nulls(self, client, world):
        assert _post(client, world).status_code == 201
        assert _post(client, world).status_code == 409
        assert _post(client, world, category_id=None).status_code == 201
        assert _post(client, world, category_id=None).status_code == 409
        assert _post(client, world, category_id=None, priority="ALTA").status_code == 201
        assert _post(client, world, category_id=None, priority="ALTA").status_code == 409

    def test_patch_a_terna_ocupada_409(self, client, world):
        _post(client, world)
        rid = _post(client, world, category_id=None).json()["data"]["id"]
        r = client.patch(f"{BASE}/auto-assign/rules/{rid}",
                         json={"category_id": world["cat"].id}, headers=world["h"])
        assert r.status_code == 409

    def test_validaciones_400(self, client, world):
        w = world
        casos = [
            dict(category_id=w["cat_sop"].id),               # categoria de otra area
            dict(priority="NOEXISTE"),
            dict(area="INEXISTENTE"),
            dict(technician_ids=[w["c"].id]),                # sin rol del area
            dict(technician_ids=[w["out"].id]),
            dict(technician_ids=[w["a"].id, w["a"].id]),     # duplicados
            dict(category_id=999999999),
        ]
        for kw in casos:
            assert _post(client, w, **kw).status_code == 400, kw

    def test_422_estrategia_o_lista_vacia(self, client, world):
        assert _post(client, world, strategy="foo").status_code == 422
        assert _post(client, world, technician_ids=[]).status_code == 422

    def test_404_patch_y_delete(self, client, world):
        assert client.patch(f"{BASE}/auto-assign/rules/999999", json={"is_active": True},
                            headers=world["h"]).status_code == 404
        assert client.delete(f"{BASE}/auto-assign/rules/999999", headers=world["h"]).status_code == 404

    def _rule(self, client, world, rid):
        rules = client.get(f"{BASE}/auto-assign", headers=world["h"]).json()["data"]["rules"]
        return next(r for r in rules if r["id"] == rid)

    def test_tecnico_que_pierde_rol_sale_no_elegible(self, client, db_session, world):
        rid = _post(client, world).json()["data"]["id"]
        db_session.query(UserAppRole).filter_by(user_id=world["b"].id).delete()
        db_session.commit()
        el = {t["id"]: t["eligible"] for t in self._rule(client, world, rid)["technicians"]}
        assert el == {world["a"].id: True, world["b"].id: False}

    def test_regla_con_tecnico_sin_rol_se_puede_desactivar(self, client, db_session, world):
        rid = _post(client, world).json()["data"]["id"]
        db_session.query(UserAppRole).filter_by(user_id=world["b"].id).delete()
        db_session.commit()
        r = client.patch(f"{BASE}/auto-assign/rules/{rid}", json={"is_active": False},
                         headers=world["h"])
        assert r.status_code == 200, r.text
        assert r.json()["data"]["is_active"] is False
        # Editar los técnicos sí revalida.
        r = client.patch(f"{BASE}/auto-assign/rules/{rid}",
                         json={"technician_ids": [world["a"].id, world["b"].id]},
                         headers=world["h"])
        assert r.status_code == 400

    def test_last_assigned_name(self, client, db_session, world):
        rid = _post(client, world).json()["data"]["id"]
        db_session.get(AssignmentRule, rid).last_assigned_user_id = world["a"].id
        db_session.commit()
        assert self._rule(client, world, rid)["last_assigned_name"] == world["a"].full_name


class TestAssignmentEmail:
    def test_get_conectado_y_tecnicos_sin_duplicados(self, client, world):
        info = {"username": "hd@itcj.mx", "name": "Help Desk"}
        with patch("itcj2.core.utils.msgraph_mail.read_account_info", return_value=info):
            r = client.get(f"{BASE}/assignment-email", headers=world["h"])
        d = r.json()["data"]
        assert d["connected"] is True and d["account"] == info
        assert d["config_url"] == "/itcj/config/email"
        mine = [t for t in d["technicians"] if "aa6_" in t["name"]]
        ids = [t["id"] for t in mine]
        assert sorted(ids) == sorted([world["a"].id, world["b"].id, world["c"].id])
        a = next(t for t in mine if t["id"] == world["a"].id)
        assert a["areas"] == ["DESARROLLO", "SOPORTE"] and a["email"] == "a@x.mx"
        assert a["enabled"] is False
        assert [t["name"] for t in mine] == sorted(t["name"] for t in mine)

    def test_get_sin_cuenta(self, client, world):
        with patch("itcj2.core.utils.msgraph_mail.read_account_info", return_value=None):
            d = client.get(f"{BASE}/assignment-email", headers=world["h"]).json()["data"]
        assert d["connected"] is False and d["account"] is None

    def test_put_guarda_audita_y_refleja(self, client, db_session, world):
        r = client.put(f"{BASE}/assignment-email", json={"user_ids": [world["a"].id]},
                       headers=world["h"])
        assert r.status_code == 200
        with patch("itcj2.core.utils.msgraph_mail.read_account_info", return_value=None):
            d = client.get(f"{BASE}/assignment-email", headers=world["h"]).json()["data"]
        assert [t["id"] for t in d["technicians"] if t["enabled"]] == [world["a"].id]
        assert db_session.query(ConfigChangeLog).filter(
            ConfigChangeLog.entity_type == "assignment_email",
            ConfigChangeLog.id > world["audit_mark"]).count() == 1

    def test_put_con_no_tecnico_400(self, client, world):
        r = client.put(f"{BASE}/assignment-email", json={"user_ids": [world["out"].id]},
                       headers=world["h"])
        assert r.status_code == 400
