"""HTML enriquecido de TitulaTec: sanitización con lista blanca (nh3).

Hoy lo usa la «Información para el alumno» de los requisitos de cotejo
(`CotejoRequirement.info_html`): Servicios Escolares la escribe en un editor
visual (Quill 2, `static/js/admin/cotejo-info-editor.js`) y el alumno la ve con
`|safe` en su página de cita. Lo que llega del navegador NO es de confianza, así
que se sanitiza DOS veces:

* al GUARDAR, en `CotejoRequirementService` (con tope de tamaño);
* al PINTAR, en las vistas (`max_len=None`), para que una fila escrita por fuera
  del editor —un UPDATE a mano, un DML— tampoco inyecte.

Lista blanca: p, br, strong, b, em, i, u, ul, ol, li, a. En <a> solo `href`
http/https/mailto, con `rel="noopener noreferrer"` y `target="_blank"` forzados.
Sin estilos, sin clases, sin atributos genéricos. Lo fija
`tests/fastapi/titulatec/test_rich_text.py`.
"""
from __future__ import annotations

import html
import re

import nh3

# Tope sobre el HTML CRUDO que manda el editor. Holgado para varios párrafos con
# listas y ligas; por encima se rechaza (400 en la ruta), nunca se trunca.
MAX_INFO_HTML_LEN = 20_000

ALLOWED_TAGS = frozenset({"p", "br", "strong", "b", "em", "i", "u", "ul", "ol", "li", "a"})
ALLOWED_URL_SCHEMES = frozenset({"http", "https", "mailto"})

# Etiquetas que se van CON su contenido; el resto de las no permitidas se
# desenvuelve y conserva el texto. `script` y `style` son el default de ammonia,
# y hay que repetirlos al pasar la lista. Los demás son contenedores cuyo texto
# no tiene sentido como prosa (el `<text>` de un `<svg>`, el HTML de reserva de
# un `<iframe>`, lo que haya en un `<noscript>`...).
_DROP_WITH_CONTENT = frozenset({
    "script", "style", "iframe", "noscript", "template", "svg", "math", "object",
    "embed", "textarea", "select", "title", "xmp", "noembed", "noframes",
})

# Esquema al inicio de una URL (RFC 3986 §3.1).
_SCHEME_RE = re.compile(r"^([a-zA-Z][a-zA-Z0-9+.\-]*):")
# Parser de URL de WHATWG: el navegador quita tab/LF/CR en CUALQUIER punto y los
# controles C0 + espacio de los extremos antes de leer el esquema, así que
# «java\tscript:» ES «javascript:». Se imita para decidir igual que él.
_URL_STRIP_INSIDE = re.compile(r"[\t\n\r]")
_C0_AND_SPACE = "".join(chr(c) for c in range(0x21))
# Invisibles que un editor puede dejar sin que haya texto de verdad.
_INVISIBLE = ("​", "﻿")


class InfoHtmlTooLong(ValueError):
    """El HTML crudo excede `max_len`. Nunca se trunca: cortar HTML lo rompe.

    El mensaje es para la persona usuaria: las rutas lo mandan tal cual en
    `X-Tt-Error`, como los `ValueError` de los demás servicios de la app.
    """

    def __init__(self, length: int, max_len: int):
        self.length = length
        self.max_len = max_len
        tope = f"{max_len:,}".replace(",", " ")
        super().__init__(
            f"La información para el alumno es demasiado larga (máximo {tope} "
            "caracteres, contando el formato). Acórtala y vuelve a guardar.")


def _href_permitido(value: str) -> bool:
    url = _URL_STRIP_INSIDE.sub("", value).strip(_C0_AND_SPACE)
    m = _SCHEME_RE.match(url)
    return bool(m) and m.group(1).lower() in ALLOWED_URL_SCHEMES


def _attribute_filter(tag: str, attr: str, value: str) -> str | None:
    """Última palabra sobre cada atributo que ammonia dejaría pasar.

    Dos huecos que el Cleaner NO cierra por sí solo (medido con nh3 0.3.7):
    deja pasar las URL RELATIVAS (`/ruta`, `//host`, `#ancla`), y el contrato es
    «solo http/https/mailto»; y conserva `title`/`lang` como atributos
    genéricos. `rel` y `target` los pone el propio Cleaner.
    """
    if tag != "a":
        return None
    if attr == "href":
        return value if _href_permitido(value) else None
    if attr in ("rel", "target"):
        return value
    return None


def _es_vacio(fragment: str) -> bool:
    """Sin texto legible: `<p><br></p>`, espacios, una liga sin texto..."""
    texto = html.unescape(nh3.clean(fragment, tags=set()))
    for ch in _INVISIBLE:
        texto = texto.replace(ch, "")
    return not texto.strip()


def sanitize_info_html(raw: str | None, *,
                       max_len: int | None = MAX_INFO_HTML_LEN) -> str | None:
    """Limpia `raw` contra la lista blanca. `None` si no queda nada legible.

    * `max_len` es el tope sobre el HTML CRUDO. Al guardar se deja el default y
      excederlo levanta `InfoHtmlTooLong`; al pintar se pasa `max_len=None`,
      porque una fila ya guardada nunca debe tumbar la página.
    * `&nbsp;` se vuelve espacio normal: Quill 2.0.3 serializa CADA espacio así
      (`getSemanticHTML`) y el párrafo dejaría de partirse en líneas.
    * Devuelve `str`, no `Markup`: el mismo valor viaja escapado en el `value`
      del input oculto del editor, y un `Markup` se colaría ahí sin escapar.
    * Idempotente: limpiar lo ya limpio no lo cambia.
    """
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise TypeError(f"info_html debe ser str, no {type(raw).__name__}")
    if max_len is not None and len(raw) > max_len:
        raise InfoHtmlTooLong(len(raw), max_len)

    limpio = nh3.clean(
        raw,
        tags=set(ALLOWED_TAGS),
        clean_content_tags=set(_DROP_WITH_CONTENT),
        # `"*": set()` vacía los atributos genéricos (sin la llave, ammonia
        # conserva `title` y `lang` en cualquier etiqueta).
        attributes={"*": set(), "a": {"href"}},
        attribute_filter=_attribute_filter,
        url_schemes=set(ALLOWED_URL_SCHEMES),
        link_rel="noopener noreferrer",
        set_tag_attribute_values={"a": {"target": "_blank"}},
        strip_comments=True,
    )
    limpio = limpio.replace("&nbsp;", " ").strip()
    if _es_vacio(limpio):
        return None
    return limpio
