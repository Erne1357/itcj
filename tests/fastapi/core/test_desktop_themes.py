"""Plantillas del escritorio y del shell móvil con un tema activo: versionado de
los estáticos del tema (clave del manifiesto relativa a `core/`) y capa de
decoraciones `#theme-decor` dentro de `.desktop-shell`."""
from types import SimpleNamespace
from unittest.mock import patch

import lxml.html
import pytest

from itcj2.database import get_db
from tests.conftest import make_jwt

CSS = "css/dashboard/themes/x.css"
JS = "js/dashboard/themes/x.js"
THEME = {
    "id": 1, "name": "x", "css_file": f"core/{CSS}", "js_file": f"core/{JS}",
    "custom_css": None,
}
MANIFEST = {"core": {CSS: "abc12345", JS: "def67890"}}


@pytest.fixture()
def client(app_client, db_session, patched_session_local):
    def _override():
        yield db_session

    app_client.app.dependency_overrides[get_db] = _override
    yield app_client
    app_client.app.dependency_overrides.pop(get_db, None)


def _dashboard(client, theme):
    cookie = {"Cookie": f"itcj_token={make_jwt(user_id=200, role='admin', name='PEREZ LOPEZ ANA')}"}
    with patch("itcj2.core.services.authz_service.user_roles_in_app", return_value={"admin"}), \
         patch("itcj2.templates._get_active_theme", return_value=theme), \
         patch("itcj2.templates._get_manifest", return_value=MANIFEST):
        resp = client.get("/itcj/dashboard", headers=cookie, follow_redirects=False)
    assert resp.status_code == 200, resp.text[:300]
    return lxml.html.document_fromstring(resp.text)


def test_estaticos_del_tema_llevan_hash_del_manifiesto(client):
    doc = _dashboard(client, THEME)
    link = doc.xpath(f"//link[contains(@href, 'themes/x.css')]")
    script = doc.xpath(f"//script[contains(@src, 'themes/x.js')]")
    assert len(link) == 1 and link[0].get("href").endswith("?v=abc12345")
    assert len(script) == 1 and script[0].get("src").endswith("?v=def67890")


def test_capa_de_decoraciones_es_primer_hijo_del_shell(client):
    doc = _dashboard(client, THEME)
    shell = doc.xpath("//div[contains(concat(' ', @class, ' '), ' desktop-shell ')]")
    assert len(shell) == 1
    first = shell[0].xpath("./*[1]")[0]
    assert first.get("id") == "theme-decor"
    assert "theme-decor" in first.get("class").split()
    assert first.get("aria-hidden") == "true"


def test_sin_tema_no_hay_capa(client):
    doc = _dashboard(client, None)
    assert not doc.xpath("//*[@id='theme-decor']")


def test_plantilla_movil_versiona_el_tema(client):
    cookie = {"Cookie": f"itcj_token={make_jwt(user_id=200, role='admin', name='PEREZ LOPEZ ANA')}"}
    user = SimpleNamespace(id=200, first_name="ANA", last_name="PEREZ", full_name="ANA PEREZ",
                           username="ana", email=None, control_number=None,
                           get_position_title=lambda: "", get_current_department=lambda: None)
    with patch("itcj2.core.services.mobile_service.get_user_for_mobile", return_value=user), \
         patch("itcj2.core.services.mobile_service.get_user_type", return_value="staff"), \
         patch("itcj2.core.services.mobile_service.get_mobile_apps_for_user", return_value=[]), \
         patch("itcj2.templates._get_active_theme", return_value=THEME), \
         patch("itcj2.templates._get_manifest", return_value=MANIFEST):
        resp = client.get("/itcj/m/", headers=cookie, follow_redirects=False)
    assert resp.status_code == 200, resp.text[:300]
    doc = lxml.html.document_fromstring(resp.text)
    link = doc.xpath("//link[contains(@href, 'themes/x.css')]")
    script = doc.xpath("//script[contains(@src, 'themes/x.js')]")
    assert link and link[0].get("href").endswith("?v=abc12345")
    assert script and script[0].get("src").endswith("?v=def67890")
