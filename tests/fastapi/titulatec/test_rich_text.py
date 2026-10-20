"""`utils/rich_text.sanitize_info_html`: la unica puerta del HTML enriquecido.

La «Informacion para el alumno» de un requisito de cotejo la escribe Servicios
Escolares en un editor visual (Quill 2) y el alumno la ve pintada con `|safe`.
Todo lo que entra se limpia con `nh3` contra una lista blanca DOS veces: al
guardar (`CotejoRequirementService`) y al pintar (las vistas), para que una fila
escrita por fuera del editor tampoco inyecte.

Contrato que fija este archivo:
  * etiquetas: p, br, strong, b, em, i, u, ul, ol, li, a — nada mas;
  * en <a> solo `href` http/https/mailto, y SIEMPRE rel="noopener noreferrer" y
    target="_blank"; sin estilos, clases ni atributos genericos (title, lang);
  * vacio (espacios, `<p><br></p>`) -> None;
  * por encima del tope -> `InfoHtmlTooLong` (un ValueError); nunca se trunca;
  * idempotente: limpiar lo ya limpio no lo cambia.

Tests puros: no tocan la BD.
"""
from __future__ import annotations

from html.parser import HTMLParser

import pytest

from itcj2.apps.titulatec.utils.rich_text import (
    MAX_INFO_HTML_LEN,
    InfoHtmlTooLong,
    sanitize_info_html,
)


class _Arbol(HTMLParser):
    """Etiquetas y atributos del fragmento, sin depender del orden de serializacion."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tags: list[tuple[str, dict]] = []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


def _parse(fragment: str) -> list[tuple[str, dict]]:
    arbol = _Arbol()
    arbol.feed(fragment or "")
    arbol.close()
    return arbol.tags


def _tags(fragment: str) -> list[str]:
    return [t for t, _a in _parse(fragment)]


def _links(fragment: str) -> list[dict]:
    return [a for t, a in _parse(fragment) if t == "a"]


FORZADOS = {"rel": "noopener noreferrer", "target": "_blank"}


class TestCasosFelices:
    def test_la_lista_blanca_pasa_intacta(self):
        crudo = ("<p>Hola <strong>fuerte</strong> <b>b</b> <em>em</em> <i>i</i> "
                 "<u>sub</u><br>linea</p><ul><li>uno</li></ul><ol><li>dos</li></ol>")

        assert sanitize_info_html(crudo) == crudo

    @pytest.mark.parametrize("href", [
        "https://www.itcj.edu.mx/biblioteca",
        "http://biblioteca.itcj.edu.mx",
        "HTTPS://WWW.ITCJ.EDU.MX",
        "mailto:escolares@itcj.edu.mx",
    ])
    def test_liga_permitida_sale_con_rel_y_target_forzados(self, href):
        limpio = sanitize_info_html(f'<p><a href="{href}">liga</a></p>')

        assert _links(limpio) == [{"href": href, **FORZADOS}]

    def test_el_rel_y_el_target_del_cliente_se_sustituyen(self):
        limpio = sanitize_info_html(
            '<a href="https://x.mx" target="_self" rel="opener" title="t">x</a>')

        assert _links(limpio) == [{"href": "https://x.mx", **FORZADOS}]

    def test_es_idempotente(self):
        crudo = ('<p>Trae <strong>original</strong> &amp; copia &lt;2&gt; '
                 '<a href="https://x.mx/?a=1&b=2">aqui</a></p><p>otra</p>')

        una = sanitize_info_html(crudo)

        assert una is not None
        assert sanitize_info_html(una) == una

    def test_acentos_y_signos_se_quedan_como_texto(self):
        crudo = "<p>Llévalo en original: ¿dudas? ñ</p>"

        assert sanitize_info_html(crudo) == crudo

    def test_el_nbsp_de_quill_se_vuelve_espacio_normal(self):
        """Quill 2.0.3 serializa CADA espacio como `&nbsp;` (getSemanticHTML).

        Sin esto el parrafo no se parte en lineas: en el movil del alumno una
        frase larga desborda el modal y rompe `scrollWidth <= innerWidth`.
        """
        limpio = sanitize_info_html("<p>Trae&nbsp;tu acta&nbsp;&nbsp;original</p>")

        assert limpio == "<p>Trae tu acta  original</p>"

    def test_las_etiquetas_ajenas_se_desenvuelven_sin_perder_el_texto(self):
        limpio = sanitize_info_html('<div><span class="x">Hola</span> <h1>mundo</h1></div>')

        assert _tags(limpio) == []
        assert "Hola" in limpio and "mundo" in limpio


class TestVacio:
    @pytest.mark.parametrize("crudo", [
        None, "", "   ", "\n\t", "<p><br></p>", "<p></p>", "<p>&nbsp;</p>",
        "<p> <br> </p>", "<ul><li></li></ul>", '<p><a href="https://x.mx"></a></p>',
        "<script>alert(1)</script>", "<!-- solo un comentario -->",
    ])
    def test_devuelve_none(self, crudo):
        """NULL = sin informacion = el alumno no ve boton «i»."""
        assert sanitize_info_html(crudo) is None


class TestXss:
    def test_script_se_va_con_su_contenido(self):
        assert sanitize_info_html("<p>ok</p><script>alert('xss')</script>") == "<p>ok</p>"

    def test_manejadores_de_evento_e_img_onerror(self):
        limpio = sanitize_info_html(
            '<p onclick="alert(1)" onmouseover="x()">ok</p><img src=x onerror=alert(1)>')

        assert limpio == "<p>ok</p>"

    @pytest.mark.parametrize("href", [
        "javascript:alert(1)",
        "JaVaScRiPt:alert(1)",
        " javascript:alert(1)",
        "java&#x09;script:alert(1)",
        "&#106;avascript:alert(1)",
        "vbscript:msgbox(1)",
        "data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==",
        "/titulatec/admin",        # relativa: solo http/https/mailto
        "//evil.example/x",        # relativa al esquema
        "#ancla",
        "tel:6561234567",
    ])
    def test_href_fuera_de_la_lista_se_cae_y_el_texto_queda(self, href):
        limpio = sanitize_info_html(f'<p><a href="{href}">pulsa</a></p>')

        assert "href" not in limpio
        assert "pulsa" in limpio
        assert "javascript" not in limpio.lower() and "data:" not in limpio

    def test_style_en_etiqueta_y_en_atributo_clases_y_genericos(self):
        limpio = sanitize_info_html(
            '<style>p{color:red}</style>'
            '<p style="color:red" class="x" id="y" title="t" lang="en">ok</p>')

        assert limpio == "<p>ok</p>"

    def test_iframe_svg_y_compania_se_van_con_su_contenido(self):
        limpio = sanitize_info_html(
            '<iframe src="https://evil.example">texto</iframe>'
            '<svg onload="alert(1)"><script>alert(2)</script><text>svg</text></svg>'
            '<math><mi>x</mi></math><object data="x"></object><embed src="x">'
            '<noscript><img src=x onerror=alert(3)></noscript><p>ok</p>')

        assert limpio == "<p>ok</p>"

    def test_nada_peligroso_sobrevive_en_un_popurri(self):
        crudo = ('<p><a href="javascript:alert(1)" onclick="x">a</a>'
                 '<img src="x" onerror="alert(1)"><svg/onload=alert(1)>'
                 '<iframe srcdoc="<script>alert(1)</script>"></iframe>'
                 '<a href="data:text/html,<script>alert(1)</script>">b</a>'
                 '<u style="background:url(javascript:alert(1))">c</u></p>')

        limpio = sanitize_info_html(crudo)

        assert limpio is not None, "algo del texto tenia que sobrevivir"
        for veneno in ("<script", "onerror", "onload", "onclick", "javascript:",
                       "data:", "<iframe", "<svg", "<img", "style="):
            assert veneno not in limpio.lower(), veneno


class TestTope:
    def test_el_tope_es_de_20_mil_caracteres(self):
        assert MAX_INFO_HTML_LEN == 20_000

    def test_por_encima_del_tope_se_niega_y_no_trunca(self):
        crudo = "<p>" + "a" * MAX_INFO_HTML_LEN + "</p>"

        with pytest.raises(InfoHtmlTooLong) as exc:
            sanitize_info_html(crudo)

        assert isinstance(exc.value, ValueError), (
            "InfoHtmlTooLong es un ValueError: el servicio no debe escribir nada")
        assert exc.value.max_len == MAX_INFO_HTML_LEN

    def test_justo_en_el_tope_pasa_completo(self):
        crudo = "<p>" + "a" * (MAX_INFO_HTML_LEN - len("<p></p>")) + "</p>"
        assert len(crudo) == MAX_INFO_HTML_LEN

        assert sanitize_info_html(crudo) == crudo

    def test_al_pintar_no_hay_tope(self):
        """Una fila guardada por fuera que exceda el tope NO puede tumbar la pagina."""
        crudo = "<p>" + "a" * (MAX_INFO_HTML_LEN + 10) + "</p>"

        assert sanitize_info_html(crudo, max_len=None) == crudo

    def test_un_valor_que_no_es_texto_se_rechaza(self):
        with pytest.raises(TypeError):
            sanitize_info_html(123)  # type: ignore[arg-type]
