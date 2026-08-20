"""Swagger/ReDoc/openapi.json solo fuera de producción.

Invariante de seguridad introducida en 7b5606c: esos tres endpoints exponen sin
auth el inventario completo de rutas, parámetros y schemas — un mapa listo para
un escáner. `create_app()` los deja en 404 cuando ``FLASK_ENV == "production"``.

No tenía ningún test, y su primer efecto colateral fue tumbar el gate de CI:
`tests/fastapi/directory/test_pages.py` leía `/api/openapi.json` para listar
rutas y pasaba solo en local, donde `.env` trae `FLASK_ENV=development`. En CI
no se define esa variable, gana el default de `config.py` ("production"), el
endpoint da 404 y el test veía cero rutas.

El test se adapta al entorno en vez de asumir uno: en CI cubre la rama de
producción (la que importa), en local la de desarrollo. No toca BD ni datos.
"""


def test_docs_coherentes_con_flask_env(app_client):
    from itcj2.config import get_settings

    app = app_client.app
    urls = (app.openapi_url, app.docs_url, app.redoc_url)

    if get_settings().FLASK_ENV == "production":
        assert urls == (None, None, None), (
            f"FLASK_ENV=production debe dejar docs/redoc/openapi en 404, hay {urls}"
        )
    else:
        assert app.openapi_url == "/api/openapi.json"
        assert app.docs_url == "/api/docs"
        assert app.redoc_url == "/api/redoc"


def test_openapi_responde_404_en_produccion(app_client):
    """Comprobación por HTTP, no por atributo: es lo que ve un escáner."""
    from itcj2.config import get_settings

    if get_settings().FLASK_ENV != "production":
        return  # en local los docs SÍ se montan; la rama de prod la cubre CI

    for path in ("/api/openapi.json", "/api/docs", "/api/redoc"):
        assert app_client.get(path).status_code == 404, f"{path} sigue expuesto"
