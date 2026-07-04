"""Migración o1s2c3p4e004: columnas color/icon_class en core_apps (C4)."""
from itcj2.core.models.app import App


def test_app_style_columns_roundtrip(db_session):
    a = App(key="stylecol1", name="StyleCol", is_active=True,
            color="#198754", icon_class="bi-headset")
    db_session.add(a)
    db_session.commit()
    db_session.refresh(a)
    assert a.color == "#198754"
    assert a.icon_class == "bi-headset"


def test_app_style_columns_nullable(db_session):
    a = App(key="stylecol2", name="StyleCol2", is_active=True)
    db_session.add(a)
    db_session.commit()
    db_session.refresh(a)
    assert a.color is None
    assert a.icon_class is None


def test_app_to_dict_includes_style(db_session):
    a = App(key="stylecol3", name="StyleCol3", is_active=True,
            color="#546E7A", icon_class="bi-tools")
    db_session.add(a)
    db_session.commit()
    d = a.to_dict()
    assert d["color"] == "#546E7A"
    assert d["icon_class"] == "bi-tools"
