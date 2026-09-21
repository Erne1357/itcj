"""Invariantes de infraestructura para observabilidad (Fase 0 en adelante).

nginx (F0) y arranque de Celery (F1c).

`/metrics`, cuando exista, no debe ser alcanzable desde el hostname público:
`location /` (más abajo, en el mismo `server`) proxea absolutamente todo al
backend, así que sin un bloque que lo intercepte antes, la app publicaría en
internet el inventario completo de rutas con su tráfico y su latencia — mejor
mapa de la app que el Swagger que ya se apaga en producción.

Se lee el archivo como texto (mismo patrón que `test_compose_prod_invariants.py`):
NO se usa PyYAML porque no está en requirements.txt y CI instala solo eso, y
nginx no es YAML de todos modos. Este archivo lo amplían tareas posteriores
(T4, T6) con más invariantes de observabilidad; se mantiene en helpers chicos,
uno por invariante, para que crezca sin volverse un solo test gigante.
"""
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
NGINX_PROD_CONF = REPO_ROOT / "docker" / "nginx" / "nginx.prod.conf"
CELERY_APP = REPO_ROOT / "itcj2" / "celery_app.py"


def _find_matching_brace(text: str, open_index: int) -> int:
    """Índice del `}` que cierra el `{` en `open_index` (conteo balanceado).

    Necesario porque un bloque nginx (`server { ... location { ... } ... }`)
    anida llaves: el primer `}` después de la apertura casi nunca es el que
    cierra ese bloque.
    """
    depth = 0
    for i in range(open_index, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return i
    raise AssertionError(f"llave sin cerrar a partir del índice {open_index}")


def _extract_block(text: str, header: str, start: int = 0) -> tuple[str, int, int]:
    """Cuerpo (sin llaves) e (inicio, fin) del primer bloque `header ... }`.

    `header` debe incluir la `{` de apertura literal (p. ej. ``"server {"`` o
    ``"location = /metrics {"``). Match por substring literal, NO regex: así
    ``"location = /metrics"`` (match exacto de nginx) nunca se confunde con
    ``"location /metrics"`` (prefijo) ni ``"server_tokens"`` con ``"server {"``.
    Lanza ``ValueError`` si el header no aparece — eso es lo que hace fallar el
    test hoy, antes de que el bloque exista.
    """
    header_index = text.index(header, start)
    open_index = header_index + len(header) - 1  # la '{' es el último char del header
    close_index = _find_matching_brace(text, open_index)
    return text[open_index + 1 : close_index], header_index, close_index


def _server_block(text: str) -> tuple[str, int, int]:
    """El único `server { ... }` que sirve la app (nginx.prod.conf no tiene más)."""
    return _extract_block(text, "server {")


def test_nginx_bloquea_metrics():
    """`/metrics` responde 404 desde nginx, sin llegar nunca al backend.

    Falla hoy porque el archivo no tiene ninguna `location` que mencione
    `/metrics`: `location /` (la última del `server`) proxea todo a
    `upstream backend`, así que en cuanto la app registre `/metrics` quedaría
    publicado en el hostname público sin este bloque.
    """
    full_text = NGINX_PROD_CONF.read_text(encoding="utf-8")
    _, server_start, server_end = _server_block(full_text)

    metrics_body, metrics_start, metrics_end = _extract_block(
        full_text, "location = /metrics {"
    )

    assert server_start < metrics_start and metrics_end < server_end, (
        "el bloque 'location = /metrics' debe estar DENTRO del server que sirve la app"
    )
    assert "return 404" in metrics_body, "el bloque debe cortar en seco con 404"
    assert "proxy_pass" not in metrics_body, (
        "el bloque no debe reenviar al backend (dejaría de estar cerrado)"
    )


def test_celery_configura_logging_por_la_senal_setup_logging():
    """Una llamada suelta a `configure_logging()` al importar `celery_app.py`
    la borra el worker al arrancar (`worker_hijack_root_logger`, activo por
    defecto): el worker nunca emitiría JSON. Con un receptor conectado a
    `celery.signals.setup_logging`, Celery se salta ese secuestro."""
    text = CELERY_APP.read_text(encoding="utf-8")

    assert re.search(r"\bsetup_logging\.connect\b", text), (
        "celery_app.py debe conectar un receptor a celery.signals.setup_logging"
    )
    # Sentencias de nivel de módulo = líneas sin sangría.
    module_level_calls = re.findall(
        r"^(?![#\s]|def |class |@).*\bconfigure_logging\(", text, re.MULTILINE
    )
    assert module_level_calls == [], (
        "configure_logging() a nivel de módulo la borra el worker al arrancar"
    )
