"""El enrutador se precalienta al arrancar (rendimiento 2026-10-14).

fastapi 0.142 arma PEREZOSAMENTE el estado de cada ruta (`get_dependant` y un
`TypeAdapter` de pydantic por parámetro) la primera vez que el enrutador la
recorre. Con ~560 rutas, la primera petición de cada worker pagaba ~350 ms:
en Tempo, tras el deploy del 2026-10-13, las primeras peticiones de los 4
workers nuevos tardaron 0.36-1.3 s con un hueco sin span antes de su primera
consulta (`/itcj/dashboard` 366 ms contra ~12 ms en caliente). El `lifespan`
llama `_warm_routes`, que lo arma antes de servir (blue/green no promueve un
color hasta que `/ready` responde, así que nadie lo paga).

Se cuenta `fastapi.routing._populate_api_route_state`, lo que de verdad arma el
estado. El control fija la suposición: si fastapi deja de ser perezoso, el
control falla y `_warm_routes` sobra.
"""
from fastapi.testclient import TestClient

# Una muestra de rutas de varias apps y un 404 (recorre TODO el árbol).
_RUTAS = ("/health", "/itcj/login", "/api/core/v2/user/me", "/titulatec/",
          "/help-desk/", "/no-existe-precalentamiento")


def _espia_de_rutas(monkeypatch) -> list:
    import fastapi.routing as fastapi_routing

    llamadas = []
    real = fastapi_routing._populate_api_route_state

    def _espia(*args, **kwargs):
        llamadas.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(fastapi_routing, "_populate_api_route_state", _espia)
    return llamadas


def test_control_sin_precalentar_la_primera_peticion_arma_las_rutas(monkeypatch):
    from itcj2.main import create_app

    app = create_app()
    llamadas = _espia_de_rutas(monkeypatch)

    TestClient(app).get("/no-existe-precalentamiento")

    assert len(llamadas) > 100, (
        "fastapi ya no arma las rutas en la primera petición: `_warm_routes` sobra")


def test_precalentada_ninguna_peticion_arma_rutas(monkeypatch):
    from itcj2.main import _warm_routes, create_app

    app = create_app()
    _warm_routes(app)
    llamadas = _espia_de_rutas(monkeypatch)

    cliente = TestClient(app)
    for ruta in _RUTAS:
        cliente.get(ruta, follow_redirects=False)

    assert llamadas == []


def test_el_lifespan_precalienta_antes_de_servir(monkeypatch):
    from itcj2.main import create_app

    app = create_app()
    with TestClient(app) as cliente:            # corre el lifespan
        llamadas = _espia_de_rutas(monkeypatch)
        for ruta in _RUTAS:
            cliente.get(ruta, follow_redirects=False)

    assert llamadas == []
