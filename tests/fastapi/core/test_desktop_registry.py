"""Registro de apps del escritorio (servidor): claves, iconos optimizados, LQIP y tarjeta de usuario."""
import struct
from pathlib import Path

from itcj2.core.models.department import Department
from itcj2.core.models.position import Position, UserPosition
from itcj2.core.models.user import User
from itcj2.core.services import desktop_service as ds

STATIC = Path(__file__).resolve().parents[3] / "itcj2/core/static"


def test_keys_unicas_y_set_exacto():
    keys = [a["key"] for a in ds.DESKTOP_APPS]
    assert len(keys) == len(set(keys))
    assert set(keys) == {"agendatec", "helpdesk", "maint", "directory", "titulatec", "prorrogas_tec",
                         "profile", "settings"}


def test_banderas_de_apps_y_sistema():
    por = {a["key"]: a for a in ds.DESKTOP_APPS}
    for k in ("agendatec", "helpdesk", "maint", "directory", "titulatec", "prorrogas_tec"):
        a = por[k]
        assert a["pinned"] and a["on_desktop"] and not a["system"] and a["badge_key"] == k
        assert a["image"] == f"core/images/app-icons/{k}.webp"
    for k in ("profile", "settings"):
        a = por[k]
        assert a["system"] and not a["pinned"] and not a["on_desktop"] and a["image"] is None
    assert por["helpdesk"]["prefixes"] == ["/help-desk"]


def test_imagenes_son_webp_96_rgba_y_livianas():
    for a in ds.DESKTOP_APPS:
        if not a["image"]:
            continue
        p = STATIC / a["image"].removeprefix("core/")
        assert p.exists(), p
        data = p.read_bytes()
        assert len(data) < 12 * 1024
        assert data[:4] == b"RIFF" and data[8:12] == b"WEBP"
        from PIL import Image
        im = Image.open(p)
        assert im.format == "WEBP" and im.size == (96, 96) and im.mode == "RGBA"


def test_prefijos_no_se_pisan_entre_apps():
    """Ningun prefijo de una app es prefijo de otro de distinta app. Si ocurriera,
    el registro (resolve en JS) debe preferir el mas largo; hoy no ocurre."""
    pares = [(p, a["key"]) for a in ds.DESKTOP_APPS for p in a["prefixes"]]
    for p1, k1 in pares:
        for p2, k2 in pares:
            if k1 != k2:
                assert not p2.startswith(p1 + "/") and p1 != p2, (p1, p2)
    assert all(not p.endswith("/") for p, _ in pares)


def test_lqip_y_color_del_fondo():
    bg = ds.DESKTOP_BACKGROUND
    assert bg["url_path"] == "core/images/windows.webp"
    assert bg["lqip"].startswith("data:image/webp;base64,") and len(bg["lqip"]) < 1500
    assert len(bg["color"]) == 7 and bg["color"].startswith("#")


def test_payload_resuelve_image_a_url_versionada():
    por = {a["key"]: a for a in ds.build_apps_payload()}
    assert por["helpdesk"]["image"].startswith("/static/core/images/app-icons/helpdesk.webp?v=")
    assert por["profile"]["image"] is None
    # el estatico no se muta
    assert ds.DESKTOP_APPS[1]["image"] == "core/images/app-icons/helpdesk.webp"


def _user(db, **kw):
    u = User(is_active=True, **kw)
    db.add(u); db.commit(); db.refresh(u)
    return u


def test_user_card_con_puesto(db_session):
    dept = Department(code="dsk_d", name="Depto Escritorio", is_active=True)
    db_session.add(dept); db_session.commit()
    pos = Position(code="dsk_p", title="Jefa de prueba", department_id=dept.id,
                   is_active=True, allows_multiple=True)
    db_session.add(pos); db_session.commit()
    u = _user(db_session, first_name="Ana", last_name="Lopez")
    db_session.add(UserPosition(user_id=u.id, position_id=pos.id, is_active=True))
    db_session.commit()
    card = ds.get_user_card(db_session, {"sub": str(u.id), "name": "Respaldo"})
    assert card == {"full_name": "Lopez Ana", "initials": "LA",
                    "position": "Jefa de prueba", "department": "Depto Escritorio"}


def test_user_card_sin_puesto(db_session):
    u = _user(db_session, first_name="Beto", last_name="Ruiz")
    card = ds.get_user_card(db_session, {"sub": str(u.id), "name": "Respaldo"})
    assert card["full_name"] == "Ruiz Beto" and card["initials"] == "RB"
    assert card["position"] == "" and card["department"] == ""


def test_user_card_usuario_inexistente_usa_respaldo(db_session):
    card = ds.get_user_card(db_session, {"sub": "999999999", "name": "Carla Mendez"})
    assert card["full_name"] == "Carla Mendez" and card["initials"] == "CM"
