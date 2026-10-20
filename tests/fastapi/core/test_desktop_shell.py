"""Shell del escritorio (`/itcj/dashboard`): contrato de markup que consumen el JS
del escritorio, `must_change.js`, el tutorial, el widget de notificaciones y los
tests e2e.

Se renderiza la página real (TestClient) con la sesión del test atada por gate y
por cuerpo, y un rol de escritorio en `itcj` (sin él la ruta manda al móvil).
"""
import json
import re
from unittest.mock import patch

import lxml.html
import pytest

from itcj2.core.services import desktop_service as ds
from itcj2.database import get_db
from tests.conftest import make_jwt

APP_KEYS = ["agendatec", "helpdesk", "maint", "directory", "titulatec"]

# Sprite del contrato compartido (plan, "Contratos compartidos").
SPRITE = ("menu search bell wifi wifi-off minus square restore x refresh external trash user "
          "settings log-out check-check inbox help calendar ticket wrench book graduation grid "
          "briefcase chevron-right").split()


@pytest.fixture()
def client(app_client, db_session, patched_session_local):
    def _override():
        yield db_session

    app_client.app.dependency_overrides[get_db] = _override
    yield app_client
    app_client.app.dependency_overrides.pop(get_db, None)


@pytest.fixture()
def page_html(client):
    """HTML del escritorio para un admin. Sin claim `sv` en el JWT: el middleware
    no consulta revocación (no depende de Redis ni de una fila en core_users)."""
    cookie = {"Cookie": f"itcj_token={make_jwt(user_id=200, role='admin', name='PEREZ LOPEZ ANA')}"}
    with patch("itcj2.core.services.authz_service.user_roles_in_app", return_value={"admin"}):
        resp = client.get("/itcj/dashboard", headers=cookie, follow_redirects=False)
    assert resp.status_code == 200, resp.text[:300]
    return resp.text


@pytest.fixture()
def doc(page_html):
    return lxml.html.document_fromstring(page_html)


def _one(doc, xpath):
    found = doc.xpath(xpath)
    assert len(found) == 1, f"{xpath}: {len(found)} coincidencias"
    return found[0]


# ---------------------------------------------------------------------------
# Tiles del escritorio
# ---------------------------------------------------------------------------
def test_cinco_tiles_de_apps_mas_la_papelera_en_el_grid(doc):
    tiles = doc.xpath('//*[@id="desktop-grid"]/*[contains(concat(" ", @class, " "), " desktop-icon ")]')
    keys = [t.get("data-app") for t in tiles]
    assert keys[0] == "papelera", "la Papelera decorativa va primero"
    assert keys[1:] == APP_KEYS
    assert "vistetec" not in keys and "app_prueba" not in keys


def test_tile_con_imagen_optimizada_y_badge_por_app(doc):
    por = {a["key"]: a for a in ds.build_apps_payload()}
    for key in APP_KEYS:
        tile = _one(doc, f'//*[@id="desktop-grid"]/*[@data-app="{key}"]')
        (img,) = tile.xpath(".//img")
        assert img.get("src") == por[key]["image"]
        assert img.get("width") == "48" and img.get("height") == "48"
        assert img.get("alt") == por[key]["name"]
        badge = _one(doc, f'//*[@id="badge-{key}"]')
        assert badge.get("data-badge-for") == key
        assert "hidden" in badge.attrib
        assert "desktop-badge" in badge.get("class").split()


# ---------------------------------------------------------------------------
# Registro para el JS
# ---------------------------------------------------------------------------
def test_json_del_registro_parseable_con_las_keys(doc):
    data = json.loads(_one(doc, '//script[@id="desktop-apps-data"]').text)
    assert [a["key"] for a in data] == [a["key"] for a in ds.DESKTOP_APPS]
    helpdesk = next(a for a in data if a["key"] == "helpdesk")
    assert set(helpdesk) >= {"key", "name", "url", "prefixes", "icon", "image", "pinned",
                             "on_desktop", "badge_key", "system"}


# ---------------------------------------------------------------------------
# Carga: scripts, CSS, lucide, preload, splash
# ---------------------------------------------------------------------------
def test_scripts_locales_con_defer(doc):
    scripts = doc.xpath("//script[@src]")
    assert scripts
    locales = [s for s in scripts if s.get("src").startswith("/")]
    assert locales, "no hay scripts locales"
    sin_defer = [s.get("src") for s in locales if "defer" not in s.attrib]
    assert not sin_defer, sin_defer


def test_sin_lucide_ni_shepherd_en_la_plantilla(page_html):
    assert "unpkg.com/lucide" not in page_html
    assert "data-lucide" not in page_html
    assert "shepherd.min.js" not in page_html and "shepherd.css" not in page_html


def test_bootstrap_antes_del_css_propio(page_html):
    i_bs = page_html.index("bootstrap@5.3.3/dist/css/bootstrap.min.css")
    i_dash = page_html.index("core/css/dashboard/dashboard.css")
    i_win = page_html.index("core/css/dashboard/desktop-windows.css")
    i_start = page_html.index("core/css/dashboard/start-menu.css")
    assert i_bs < i_dash < i_win < i_start


def test_preload_del_fondo_y_splash(doc):
    link = _one(doc, '//link[@rel="preload"][@as="image"]')
    assert "core/images/windows.webp?v=" in link.get("href")
    assert link.get("fetchpriority") == "high"
    _one(doc, '//*[@id="desktop-splash"]')
    _one(doc, '//*[contains(concat(" ", @class, " "), " desktop-shell ")]')


def test_body_lleva_usuario(doc):
    body = doc.body
    assert body.get("data-user-id") == "200"
    assert "itcj-desktop" in body.get("class").split()
    assert body.get("data-user-name")


# ---------------------------------------------------------------------------
# Barra, sprite y selectores que no cambian
# ---------------------------------------------------------------------------
def test_barra_win11_con_anclados_del_registro(doc):
    apps = doc.xpath('//*[@id="taskbarApps"]/*[contains(concat(" ", @class, " "), " taskbar-app ")]')
    assert [b.get("data-app") for b in apps] == APP_KEYS
    for b in apps:
        assert b.xpath('.//*[contains(@class, "taskbar-app-indicator")]')
        (badge,) = b.xpath('.//*[contains(@class, "taskbar-badge")]')
        assert badge.get("data-badge-for") == b.get("data-app")
    search = _one(doc, '//input[@id="taskbarSearch"]')
    assert search.get("placeholder") == "Buscar aplicaciones…"
    _one(doc, '//*[@id="trayConnection"]')
    _one(doc, '//*[@id="time"]')
    _one(doc, '//*[@id="date"]')


@pytest.mark.parametrize("selector", [
    '//*[contains(concat(" ", @class, " "), " taskbar ")]',
    '//*[contains(concat(" ", @class, " "), " start-button ")]',
    '//*[@id="notificationBell"]',
    '//*[@id="globalNotificationBadge"]',
    '//*[@id="dashboardTutorialButton"]',
    '//*[@id="forcePwModal"]',
    '//*[@id="newPw"]',
    '//*[@id="confirmPw"]',
    '//*[@id="pwErr"]',
    '//*[@id="btnSavePw"]',
    '//*[@id="windows-container"]',
])
def test_selectores_que_no_cambian(doc, selector):
    _one(doc, selector)


def test_tutorial_se_carga_bajo_demanda(doc):
    btn = _one(doc, '//*[@id="dashboardTutorialButton"]')
    assert "core/js/dashboard/dashboard_tutorial.js?v=" in btn.get("data-tutorial-src")


def test_menu_inicio_stub_incluido_y_oculto(doc, page_html):
    menu = _one(doc, '//*[@id="startMenu"]')
    assert "hidden" in menu.attrib
    for js in ("icons", "registry", "session", "window-manager", "taskbar", "desktop-grid",
               "start-menu", "tutorial-loader", "boot"):
        assert f"core/js/dashboard/desktop/{js}.js" in page_html, js
    assert "profile-menu" not in page_html
    assert "core/js/dashboard/dashboard.js" not in page_html


def test_sprite_con_los_simbolos_del_contrato(doc):
    ids = {s.get("id") for s in doc.xpath("//symbol")}
    faltan = [n for n in SPRITE if f"i-{n}" not in ids]
    assert not faltan, faltan
    for s in doc.xpath("//symbol"):
        # El parser HTML de lxml baja a minúsculas los nombres de atributo.
        assert (s.get("viewbox") or s.get("viewBox")) == "0 0 24 24", s.get("id")


def test_modal_de_contrasena_fuera_del_shell(doc):
    """El shell arranca en opacity:0 hasta `desktop-ready`; el modal no puede vivir
    dentro o quedaria invisible mientras carga."""
    modal = _one(doc, '//*[@id="forcePwModal"]')
    ancestros = [a.get("class") or "" for a in modal.iterancestors()]
    assert not any("desktop-shell" in c.split() for c in ancestros)


def test_sin_estilos_inline_de_badge_heredados(page_html):
    """Los badges se muestran con `hidden` (T5), no con `style="display:none"`."""
    assert not re.search(r'id="badge-[a-z]+"[^>]*style=', page_html)
