"""Icono propio de TitulaTec en vez del `bi-mortarboard` de Bootstrap Icons.

El PNG `itcj2/apps/titulatec/static/images/titulatec-claro-1024.png` es la marca de
la app en los lugares donde se presenta:

* escritorio del core (`core/dashboard/dashboard.html`) — el tile estaba comentado
  desde `bd6dc8e5` porque la app aun no se desplegaba;
* tarjeta del dashboard movil (`core/mobile/components/app_card.html`) — por ahi
  entra el egresado;
* shell del alumno (`titulatec/student/base_student.html`): titulo del drawer
  (movil) y logo del rail (escritorio);
* favicon de toda la app (`titulatec/base.html`, raiz de todas las paginas).

Contratos de markup sin BD: las plantillas se leen tal cual (como
`test_admin_nav_swap`) y la macro movil se renderiza con un `url_for` de mentira.
"""
import re
from pathlib import Path

import lxml.html
from jinja2 import Environment, FileSystemLoader

ROOT = Path(__file__).resolve().parents[3]
PNG_REL = "titulatec/images/titulatec-claro-1024.png"      # relativo a /static/
PNG = ROOT / "itcj2/apps/titulatec/static/images/titulatec-claro-1024.png"
CORE_TPL = ROOT / "itcj2/core/templates"
TT_TPL = ROOT / "itcj2/apps/titulatec/templates/titulatec"
TT_CSS = ROOT / "itcj2/apps/titulatec/static/css/titulatec.css"
MOBILE_CSS = ROOT / "itcj2/core/static/css/mobile/mobile-base.css"


def _doc(path: Path):
    """Plantilla Jinja -> arbol lxml. Un comentario HTML no produce elementos, asi
    que lo comentado no se encuentra (que es justo lo que se quiere comprobar)."""
    return lxml.html.document_fromstring(path.read_text(encoding="utf-8"))


def _regla(css: str, selector: str) -> str:
    """Cuerpo de la PRIMERA regla cuyo selector es exactamente `selector`."""
    m = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", css)
    assert m, f"no hay regla para `{selector}`"
    return m.group(1)


def test_el_png_de_la_marca_existe():
    assert PNG.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


# ---------------------------------------------------------------------------
# 1 - Escritorio del core
# ---------------------------------------------------------------------------
def test_escritorio_muestra_titulatec_con_el_png():
    """Descomentado y con el PNG, del mismo tamano que los tiles hermanos."""
    tiles = _doc(CORE_TPL / "core/dashboard/dashboard.html").xpath(
        '//div[@id="desktop-grid"]/div[contains(@class,"desktop-icon")][@data-app="titulatec"]')
    assert len(tiles) == 1, "el tile de TitulaTec sigue comentado (o esta duplicado)"
    (img,) = tiles[0].xpath('.//img')
    src = img.get("src")
    assert PNG_REL in src
    assert "?v={{ sv('titulatec', 'images/titulatec-claro-1024.png') }}" in src
    assert "width:45px" in img.get("style", "").replace(" ", "")
    assert img.get("alt") == "TitulaTec"
    assert not tiles[0].xpath('.//i'), "sigue pintando el glifo de Bootstrap Icons"


def test_escritorio_vistetec_sigue_oculto():
    """El `<!--` de TitulaTec se comia tambien el tile de VisteTec (llegaba hasta su
    `</div-->`). Al quitarlo, VisteTec debe quedar en su propio comentario."""
    doc = _doc(CORE_TPL / "core/dashboard/dashboard.html")
    assert not doc.xpath('//div[@data-app="vistetec"]')


# ---------------------------------------------------------------------------
# 2 - Tarjeta del dashboard movil
# ---------------------------------------------------------------------------
def _app_card(key: str, name: str):
    env = Environment(loader=FileSystemLoader(str(CORE_TPL)), autoescape=True)
    env.globals["url_for"] = lambda endpoint, **kw: f"/static/{kw['filename']}"
    macro = env.get_template("core/mobile/components/app_card.html").module.render_app_card
    html = str(macro({"key": key, "name": name, "mobile_url": f"/{key}/",
                      "color": None, "icon_class": "bi-app"}))
    return lxml.html.fragment_fromstring(html.strip())


def _icono(card):
    (icono,) = card.xpath('.//div[contains(@class,"mobile-app-card-icon")]')
    return icono, icono.get("class").split()


def test_tarjeta_movil_de_titulatec_usa_el_png_con_su_propio_tile():
    icono, clases = _icono(_app_card("titulatec", "TitulaTec"))
    assert "has-img" in clases and "has-own-tile" in clases
    (img,) = icono.xpath('.//img')
    assert img.get("src") == f"/static/{PNG_REL}"
    assert not icono.xpath('.//i'), "sigue pintando el glifo de Bootstrap Icons"


def test_tarjeta_movil_de_helpdesk_sigue_en_tile_blanco():
    """El tile propio es solo para los PNG que ya traen fondo y borde; los demas
    conservan el tile blanco de `.has-img` con la imagen contenida."""
    _, clases = _icono(_app_card("helpdesk", "Help Desk"))
    assert "has-img" in clases
    assert "has-own-tile" not in clases


def test_el_tile_propio_tiene_estilo_en_el_css_movil():
    """Sin estas reglas el PNG quedaria al 74% dentro del tile blanco: un marco
    dentro de otro."""
    css = MOBILE_CSS.read_text(encoding="utf-8")
    assert "border" in _regla(css, ".mobile-app-card-icon.has-own-tile")
    assert "100%" in _regla(css, ".mobile-app-card-icon.has-own-tile .mobile-app-card-img")


# ---------------------------------------------------------------------------
# 3 - Shell del alumno: drawer (movil) y rail (escritorio)
# ---------------------------------------------------------------------------
def _marca(xpath_contenedor: str):
    doc = _doc(TT_TPL / "student/base_student.html")
    (cont,) = doc.xpath(xpath_contenedor)
    (img,) = cont.xpath('.//img')
    return cont, img


def test_drawer_del_alumno_usa_el_png():
    titulo, img = _marca('//h5[contains(@class,"app-sidebar-title")]')
    assert "tt-brand-img" in img.get("class").split()
    assert img.get("src").startswith(f"/static/{PNG_REL}?v={{{{ sv(")
    assert img.get("alt") == "", "decorativa: el texto «TitulaTec» va al lado"
    assert not titulo.xpath('.//i'), "sigue pintando el glifo de Bootstrap Icons"


def test_rail_del_alumno_usa_el_png():
    marca, img = _marca('//div[contains(@class,"tt-rail-brand")]')
    assert "tt-brand-img" in img.get("class").split()
    assert img.get("src").startswith(f"/static/{PNG_REL}?v={{{{ sv(")
    assert img.get("alt") == ""
    assert "TT" not in marca.text_content().split(), "sigue el monograma «TT»"


def test_la_marca_del_alumno_tiene_tamano_en_css():
    """Sin tamano explicito el `<img>` se pintaria a 1024 px dentro del drawer."""
    css = TT_CSS.read_text(encoding="utf-8")
    for selector in (".app-sidebar-title .tt-brand-img", ".tt-rail-brand .tt-brand-img"):
        cuerpo = _regla(css, selector)
        assert "width" in cuerpo and "height" in cuerpo, selector


# ---------------------------------------------------------------------------
# 4 - Favicon
# ---------------------------------------------------------------------------
def test_favicon_de_titulatec():
    """`base.html` es la raiz de todas las paginas (admin, alumno y publicas)."""
    (link,) = _doc(TT_TPL / "base.html").xpath('//link[@rel="icon"]')
    assert link.get("type") == "image/png"
    assert link.get("href") == (f"/static/{PNG_REL}"
                                "?v={{ sv('images/titulatec-claro-1024.png') }}")
