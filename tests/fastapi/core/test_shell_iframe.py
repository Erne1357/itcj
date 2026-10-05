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


def test_desktop_window_iframe_sin_sandbox():
    tag = _tag(DASHBOARD_JS.read_text(encoding="utf-8"), 'class="window-iframe"')
    assert not re.search(r"\bsandbox\s*=", tag)
    assert 'allow="fullscreen"' in tag
    assert 'referrerpolicy="same-origin"' in tag


def test_mobile_app_frame_sin_sandbox():
    tag = _tag(BASE_MOBILE.read_text(encoding="utf-8"), 'id="mobileAppFrame"')
    assert not re.search(r"\bsandbox\s*=", tag)
    assert 'allow="fullscreen"' in tag
