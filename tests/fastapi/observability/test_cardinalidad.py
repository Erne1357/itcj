"""Guardián del presupuesto de series de Prometheus (plan Fase 2 test 3, §6).

Si alguien añade 200 rutas nuevas o cuela un id en una plantilla, esto salta
AQUÍ y no en el `mem_limit` de Prometheus a las tres de la mañana: el tope de
disco de Prometheus es GLOBAL, y si ITCJ se pasa se pierde la historia de
TODO el stack (node, cAdvisor, Postgres, Redis), no solo la de ITCJ.

Las plantillas salen del mapa de `itcj2.observability.route` (el mismo que
usa el middleware para etiquetar), importado — nunca un recorrido propio del
árbol de routers, que podría divergir del de producción en silencio.
"""
import pytest

from itcj2.main import create_app
from itcj2.observability.metrics import DURATION_BUCKETS, LOOP_LAG_BUCKETS
from itcj2.observability.middleware import METRIC_METHODS
from itcj2.observability.route import _KEYS, _route_method_pairs, build_route_map

# R8: ~21 % sobre las ~16.500 series proyectadas de hoy. Son 804 pares
# (método, ruta) contando `/metrics`, que no genera series (SKIP_PATHS): un
# par de margen a favor.
MAX_SERIES_PER_TARGET = 20_000

# Peor caso de estados distintos por par (método, ruta) en el contador (§6).
MAX_STATUS = 6

# Series que no escalan con las rutas (§6, tabla "Cuánto añade cada fase"):
IN_FLIGHT_SERIES = len(_KEYS) + 1          # una por app_key, más "otro"
# Estados que un cliente ANÓNIMO puede producir en "__unmatched__" (sin ruta
# matcheada): 404; 405 (colapsado a propósito, ver middleware); 307 (redirect
# de barra final de Starlette); 200 y 400 (preflight CORS de origen permitido
# y no permitido: CORSMiddleware responde antes de enrutar); 500; y las
# respuestas tempranas de JWTMiddleware (antes de enrutar).
UNMATCHED_STATUSES = 7
# "__unmatched__": histograma + estados, por cada método que el middleware
# guarda tal cual más "OTHER".
UNMATCHED_SERIES = (len(METRIC_METHODS) + 1) * (
    len(DURATION_BUCKETS) + 3 + UNMATCHED_STATUSES
)
EXCEPTION_SERIES = 200                     # disperso: solo rutas que revientan
# Una vez por target, sin etiquetas que crezcan (peor caso: rol `all`, que
# publica también presencia y sockets):
FIXED_SERIES = (
    3 + 3 + 5                              # saturación: anyio, asyncio, pool de BD
    + 2                                    # uso del dir de mmap (R25)
    + len(LOOP_LAG_BUCKETS) + 3            # histograma de lag del loop
    + 4                                    # itcj_presence_users (buckets)
    + 6                                    # itcj_socket_connections (namespaces hoy)
)
EXTRA_SERIES = IN_FLIGHT_SERIES + UNMATCHED_SERIES + EXCEPTION_SERIES + FIXED_SERIES

RUTAS_CON_NUMERO_ESTATICO = {
    # El "1" es el número de fase, no un id: /phase/2/… no existe como ruta
    # hermana parametrizada. Reconfirmado el 2026-09-21 enumerando el mapa de
    # create_app(): es la ÚNICA plantilla de la app con un segmento numérico.
    "/titulatec/student/phase/1/submit",
}


@pytest.fixture(scope="module")
def app():
    return create_app()


def _numeric_where_sibling_has_param(templates) -> list:
    """Plantillas con un segmento numérico en una posición donde una hermana
    (misma ruta padre hasta ese punto) lleva un `{param}`: el síntoma de un
    id que se coló sin plantillar.

    La regla NO es "ningún segmento numérico": la app tiene un número de fase
    estático legítimo y el test nacería en rojo por un falso positivo.
    """
    split = [t.split("/") for t in templates]
    param_positions = set()
    for segments in split:
        for i, segment in enumerate(segments):
            if segment.startswith("{"):
                param_positions.add((tuple(segments[:i]), i))

    offenders = []
    for template, segments in zip(templates, split):
        for i, segment in enumerate(segments):
            if segment.isdigit() and (tuple(segments[:i]), i) in param_positions:
                offenders.append(template)
                break
    return offenders


@pytest.mark.parametrize(
    "templates, expected",
    [
        (["/x/{id}", "/x/7"], ["/x/7"]),
        (["/x/{id}/edit", "/x/7/edit"], ["/x/7/edit"]),
        (["/x/{id}", "/y/7"], []),                # otra rama: no es hermana
        (["/x/phase/1/submit", "/x/{id}"], []),   # el param está un nivel arriba
    ],
)
def test_sibling_rule_detects_leaked_ids(templates, expected):
    # Sin esto la regla podría estar rota y el test de la app pasaría en
    # vacío (la app real no tiene infractores).
    assert _numeric_where_sibling_has_param(templates) == expected


def test_no_numeric_segment_where_a_sibling_has_a_param(app):
    templates = sorted(set(build_route_map(app).values()))

    offenders = [
        t for t in _numeric_where_sibling_has_param(templates)
        if t not in RUTAS_CON_NUMERO_ESTATICO
    ]

    assert not offenders, (
        f"Plantillas con un número donde una ruta hermana lleva {{param}}: "
        f"{offenders}. Casi seguro es un id escrito a mano en la ruta: "
        "decláralo como parámetro de path. Si de verdad es un segmento "
        "estático, añádelo a RUTAS_CON_NUMERO_ESTATICO con el porqué."
    )


def test_numeric_whitelist_is_not_stale(app):
    # Una lista blanca que ya no corresponde a ninguna ruta es una excepción
    # esperando a que alguien la reuse sin mirar.
    templates = set(build_route_map(app).values())

    stale = sorted(RUTAS_CON_NUMERO_ESTATICO - templates)

    assert not stale, (
        f"{stale} ya no existe en la app: quítalo de RUTAS_CON_NUMERO_ESTATICO."
    )


def test_projected_series_fit_the_budget(app):
    pairs = len(_route_method_pairs(app))
    # +3: el bucket +Inf, `_sum` y `_count` de cada juego de etiquetas.
    histogram = pairs * (len(DURATION_BUCKETS) + 3)
    counter = pairs * MAX_STATUS
    projected = histogram + counter + EXTRA_SERIES

    assert projected < MAX_SERIES_PER_TARGET, (
        f"Proyección de {projected} series por target con {pairs} pares "
        f"(método, ruta): supera MAX_SERIES_PER_TARGET={MAX_SERIES_PER_TARGET}. "
        "Palancas del plan §6, en este orden: (1) medir la cardinalidad REAL "
        "a las 24 h con count({__name__=~\"itcj_.*\"}) y "
        "prometheus_tsdb_head_series antes de decidir; (2) subir "
        "--storage.tsdb.retention.size en platform/docker-compose.yml si "
        "`df -h` da holgura, y entonces subir este tope; (3) recortar "
        "DURATION_BUCKETS en itcj2/observability/metrics.py (última opción: "
        "se pierde resolución en la cola). NUNCA bajar `route` a nivel de app."
    )
