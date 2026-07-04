"""Color/icon_class de apps: bodies, serializers y validación hex (D7/C4)."""
import pytest
from pydantic import ValidationError

from itcj2.core.api import authz as authz_api
from itcj2.core.api.authz import AppCreateBody, AppUpdateBody
from itcj2.core.models.app import App


def test_create_app_roundtrips_style(db_session):
    body = AppCreateBody(key="styl1", name="Style App",
                         color="#198754", icon_class="bi-headset")
    resp = authz_api.create_app(body=body, user={"sub": "1"}, db=db_session)
    assert resp["data"]["color"] == "#198754"
    assert resp["data"]["icon_class"] == "bi-headset"


def test_list_apps_includes_style(db_session):
    db_session.add(App(key="styl2", name="S2", is_active=True,
                       color="#0d6efd", icon_class="bi-app"))
    db_session.commit()
    resp = authz_api.list_apps(user={"sub": "1"}, db=db_session)
    row = next(a for a in resp["data"] if a["key"] == "styl2")
    assert row["color"] == "#0d6efd"
    assert row["icon_class"] == "bi-app"


def test_update_app_style_and_clear(db_session):
    db_session.add(App(key="styl3", name="S3", is_active=True, color="#111111"))
    db_session.commit()
    resp = authz_api.update_app(app_key="styl3", body=AppUpdateBody(color="#222222"),
                                user={"sub": "1"}, db=db_session)
    assert resp["data"]["color"] == "#222222"
    resp = authz_api.update_app(app_key="styl3", body=AppUpdateBody(color=""),
                                user={"sub": "1"}, db=db_session)
    assert resp["data"]["color"] is None  # "" limpia


def test_invalid_color_rejected():
    with pytest.raises(ValidationError):
        AppCreateBody(key="x", name="x", color="verde")
    with pytest.raises(ValidationError):
        AppUpdateBody(color="#12345")  # 5 hex digits


def test_valid_icon_class_accepted():
    # una clase y multi-clase (espacio) son válidas
    assert AppCreateBody(key="x", name="x", icon_class="bi-headset").icon_class == "bi-headset"
    assert AppCreateBody(key="x", name="x",
                         icon_class="bi-star-fill bi-lg").icon_class == "bi-star-fill bi-lg"


def test_icon_class_clear_sentinel():
    # "" (sentinel de limpiar en update) sobrevive la validación, como color
    assert AppUpdateBody(icon_class="").icon_class == ""


def test_invalid_icon_class_rejected():
    with pytest.raises(ValidationError):
        AppCreateBody(key="x", name="x", icon_class="bi-<script>")  # charset inválido
    with pytest.raises(ValidationError):
        AppUpdateBody(icon_class="a" * 51)  # excede el largo de la columna (50)
