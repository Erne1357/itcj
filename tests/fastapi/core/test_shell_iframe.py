"""El shell del escritorio no debe encerrar las apps en sandbox (visor PDF)."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3] / "itcj2" / "core"
DASHBOARD_JS = ROOT / "static" / "js" / "dashboard" / "dashboard.js"
BASE_MOBILE = ROOT / "templates" / "core" / "mobile" / "base_mobile.html"


def _tag(text: str, marker: str) -> str:
    start = text.index(marker)
    begin = text.rindex("<iframe", 0, start + 1)
    return text[begin:text.index(">", start)]


def test_desktop_window_iframe_sandbox_solo_cross_origin():
    js = DASHBOARD_JS.read_text(encoding="utf-8")
    tag = _tag(js, 'class="window-iframe"')
    # El tag no lleva sandbox fijo (same-origin): lo inyecta ${iframeSandbox}.
    assert not re.search(r"sandbox\s*=", tag)
    assert "${iframeSandbox}" in tag
    # Cross-origin => sandbox con allow-*; same-origin => cadena vacia.
    m = re.search(r"const iframeSandbox = iframeIsCrossOrigin\s*\?\s*'([^']*)'\s*:\s*\"\"", js)
    assert m, "iframeSandbox debe ser condicional a iframeIsCrossOrigin"
    assert m.group(1).startswith('sandbox="')
    for permiso in ("allow-scripts", "allow-same-origin", "allow-forms", "allow-popups",
                    "allow-popups-to-escape-sandbox", "allow-downloads"):
        assert permiso in m.group(1), permiso
    assert ".origin !== globalThis.location.origin" in js
    assert 'allow="fullscreen"' in tag
    assert 'referrerpolicy="same-origin"' in tag


def test_mobile_app_frame_sin_sandbox():
    tag = _tag(BASE_MOBILE.read_text(encoding="utf-8"), 'id="mobileAppFrame"')
    assert not re.search(r"\bsandbox\s*=", tag)
    assert 'allow="fullscreen"' in tag
