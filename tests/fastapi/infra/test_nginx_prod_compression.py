"""Compresión del nginx interno de producción (plan de rendimiento TitulaTec, R1).

Evidencia (H1): el borde (`platform/edge`, fuera del repo) le habla a este nginx
en HTTP/1.0. `gzip_http_version` vale 1.1 por omisión, así que sin subirlo a la
1.0 el nginx interno NUNCA comprime lo que le pide el borde: una bandeja de
Solicitudes viaja entera (1469 KB que con gzip serían ~35 KB). Tampoco comprime
el borde, así que esta es la única capa donde se puede arreglar desde el repo.

Se lee el archivo como texto (mismo patrón que `test_observability_invariants.py`,
cuyos ayudantes de llaves se reutilizan): nginx no es YAML ni hay un binario de
nginx en CI. `nginx.dev.conf` no se mira: no se toca en este cambio.
"""
import re
from pathlib import Path

from tests.fastapi.infra.test_observability_invariants import (
    NGINX_PROD_CONF,
    _extract_block,
)


def _directives(body: str, name: str) -> list[str]:
    """Valores de la directiva `name` en `body`, sin contar comentarios.

    Las sentencias de nginx terminan en `;` y pueden partirse en varias líneas
    (`gzip_types` lo hace), así que se quitan los comentarios línea a línea, se
    unen y se parte por `;`.
    """
    code = " ".join(line.split("#", 1)[0] for line in body.splitlines())
    found = []
    for statement in code.split(";"):
        match = re.fullmatch(rf"\s*{re.escape(name)}\s+(.+?)\s*", statement, re.DOTALL)
        if match:
            found.append(" ".join(match.group(1).split()))
    return found


def _http_level_text() -> str:
    """El cuerpo del `http { ... }` HASTA el primer `server {`: el nivel `http`
    propiamente dicho. Una directiva dentro de un `server`/`location` no
    protege a las demás rutas, y es justo donde se perdería en una edición."""
    full = Path(NGINX_PROD_CONF).read_text(encoding="utf-8")
    http_body, _, _ = _extract_block(full, "http {")
    return http_body[: http_body.index("server {")]


def test_gzip_sigue_encendido_en_el_contexto_http():
    assert _directives(_http_level_text(), "gzip") == ["on"]


def test_gzip_acepta_peticiones_http_1_0_del_borde():
    """Sin esto el nginx interno nunca comprime para el borde (H1)."""
    assert _directives(_http_level_text(), "gzip_http_version") == ["1.0"]


def test_gzip_no_comprime_respuestas_diminutas():
    """Por debajo de 1 KB la cabecera cuesta más de lo que ahorra."""
    assert _directives(_http_level_text(), "gzip_min_length") == ["1024"]


def test_gzip_conserva_proxied_any_y_los_tipos_de_texto():
    """El borde manda `Via`: sin `gzip_proxied any` no se comprimiría nada de lo
    que llega por proxy. HTML va implícito en gzip_types; el resto, explícito."""
    http_level = _http_level_text()
    assert _directives(http_level, "gzip_proxied") == ["any"]
    types = " ".join(_directives(http_level, "gzip_types"))
    for mime in ("text/css", "application/json", "application/javascript"):
        assert mime in types
