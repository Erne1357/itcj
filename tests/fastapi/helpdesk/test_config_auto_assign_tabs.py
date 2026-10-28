"""Pestañas «Correo» y «Asignación automática» de /help-desk/admin/config (T8)."""
import re
from pathlib import Path

from itcj2.apps.helpdesk.pages.nav import HD_PAGE_MODULES

from .test_htmx_nav import ADMIN, patched_authz

JS_DIR = Path(__file__).resolve().parents[3] / "itcj2/apps/helpdesk/static/js/admin/config"
NEW_JS = ["assignment_email_tab.js", "auto_assign_tab.js"]
CONFIG_PERMS = {"helpdesk.config.page.view"}


def test_config_page_has_new_tabs_and_modal(app_client):
    with patched_authz(CONFIG_PERMS):
        resp = app_client.get("/help-desk/admin/config", headers=ADMIN)
    assert resp.status_code == 200
    for needle in ("tab-correo-btn", "tab-autoasig-btn", "correo-root",
                   "autoasig-root", "modal-assign-rule"):
        assert f'id="{needle}"' in resp.text, needle


def test_nav_loads_new_js_before_config_main():
    mods = HD_PAGE_MODULES["admin_config"]
    main = mods.index("js/admin/config/config_main.js")
    for name in NEW_JS:
        path = f"js/admin/config/{name}"
        assert path in mods and mods.index(path) < main
        assert (JS_DIR / name).is_file()


def test_new_js_has_no_native_dialogs():
    for name in NEW_JS:
        src = (JS_DIR / name).read_text(encoding="utf-8")
        assert not re.search(r"(?<![\w.])(alert|confirm|prompt)\s*\(", src), name
