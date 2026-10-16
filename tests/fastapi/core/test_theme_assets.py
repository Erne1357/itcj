"""Guarda de los estáticos de los temas estacionales del escritorio.

Cada clase o id que estiliza el CSS de un tema tiene que existir en el DOM
vigente: o lo crea el JS del mismo tema, o vive en las plantillas del escritorio
y del shell móvil, o lo crea el JS del escritorio. Así un selector del DOM viejo
(`.search-input`, `.icon-container`) no sobrevive en silencio cuando el
escritorio cambia.

También fija el contrato con la capa de decoraciones (`#theme-decor`, Task 1):
cada tema define `--theme-band` y su JS cuelga las decoraciones de la capa.
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
CORE = ROOT / "itcj2" / "core"
THEMES_CSS = CORE / "static" / "css" / "dashboard" / "themes"
THEMES_JS = CORE / "static" / "js" / "dashboard" / "themes"

# CSS del tema -> JS del mismo tema (core_themes.css_file / js_file).
PAIRS = {
    "christmas-decorations.css": "christmas-snow.js",
    "valentine-decorations.css": "valentine-hearts.js",
    "mundial-decorations.css": "mundial-soccer.js",
}

# DOM vigente fuera del tema: plantillas (atributos class/id) y JS del escritorio.
TEMPLATE_GLOBS = ("templates/core/dashboard/*.html", "templates/core/mobile/*.html")
SHARED_JS_GLOBS = ("static/js/dashboard/desktop/*.js", "static/js/dashboard/notification-widget.js")

# Clases que crea una librería en tiempo de ejecución, no nuestro código.
WHITELIST = {
    "modal-backdrop",  # Bootstrap: backdrop del modal de resultados del Mundial
}

_CSS_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_JS_LINE_COMMENT = re.compile(r"(?m)(?:^|(?<=\s))//.*$")
_WORD = re.compile(r"[A-Za-z0-9_-]+")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def selector_names(css: str) -> set[str]:
    """Clases e ids de los selectores (sin comentarios, @-reglas ni keyframes)."""
    css = _CSS_COMMENT.sub("", css)
    names: set[str] = set()
    for match in re.finditer(r"([^{};]*)\{", css):
        prelude = match.group(1).strip()
        if not prelude or prelude.startswith("@"):
            continue
        prelude = re.sub(r"\[[^\]]*\]", "", prelude)  # [atributo="x.y"] no aporta nombres
        names.update(re.findall(r"[.#](-?[A-Za-z_][\w-]*)", prelude))
    return names


def js_words(js: str) -> set[str]:
    """Palabras del código JS (sin comentarios): nombres de clase/id que puede crear."""
    js = _CSS_COMMENT.sub("", js)
    js = _JS_LINE_COMMENT.sub("", js)
    return set(_WORD.findall(js))


def template_names(html: str) -> set[str]:
    names: set[str] = set()
    for match in re.finditer(r'\b(?:class|id)\s*=\s*"([^"]*)"', html):
        names.update(_WORD.findall(match.group(1)))
    return names


def shared_dom_names() -> set[str]:
    names: set[str] = set()
    for pattern in TEMPLATE_GLOBS:
        for path in CORE.glob(pattern):
            names |= template_names(_read(path))
    for pattern in SHARED_JS_GLOBS:
        for path in CORE.glob(pattern):
            names |= js_words(_read(path))
    return names


def missing_selectors(css: str, own_js: str, shared: set[str]) -> list[str]:
    own = js_words(own_js)
    return sorted(n for n in selector_names(css) if n not in own and n not in shared and n not in WHITELIST)


def test_cada_css_de_tema_tiene_su_js():
    assert {p.name for p in THEMES_CSS.glob("*.css")} == set(PAIRS)
    for js_name in PAIRS.values():
        assert (THEMES_JS / js_name).is_file(), js_name


def test_la_guarda_detecta_selectores_muertos():
    """La guarda misma: un selector del DOM viejo se reporta; uno vigente no."""
    shared = shared_dom_names()
    css = ".search-input::placeholder { opacity: 1 } .desktop-icon-img::before { content: '' }"
    assert missing_selectors(css, "", shared) == ["search-input"]


@pytest.mark.parametrize("css_name", sorted(PAIRS))
def test_selectores_del_tema_existen_en_el_dom_vigente(css_name):
    css = _read(THEMES_CSS / css_name)
    own_js = _read(THEMES_JS / PAIRS[css_name])
    missing = missing_selectors(css, own_js, shared_dom_names())
    assert not missing, f"{css_name}: selectores sin elemento en el DOM vigente: {missing}"


@pytest.mark.parametrize("css_name", sorted(PAIRS))
def test_tema_define_su_banda(css_name):
    css = _CSS_COMMENT.sub("", _read(THEMES_CSS / css_name))
    root = re.search(r":root\s*\{([^}]*)\}", css)
    assert root and re.search(r"--theme-band\s*:\s*\d+px", root.group(1)), css_name


@pytest.mark.parametrize("js_name", sorted(PAIRS.values()))
def test_js_del_tema_usa_la_capa_de_decoraciones(js_name):
    js = _read(THEMES_JS / js_name)
    assert re.search(r"getElementById\(\s*['\"]theme-decor['\"]\s*\)\s*\|\|\s*document\.body", js), js_name


def test_mundial_sin_emoji_de_bandera():
    """Windows no trae glifos de banderas: un indicador regional se ve como letras."""
    js = _read(THEMES_JS / "mundial-soccer.js")
    css = _read(THEMES_CSS / "mundial-decorations.css")
    assert not re.search("[\U0001F1E6-\U0001F1FF]", js + css)
