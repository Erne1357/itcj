"""La aplicación arranca completa y `/ready` alcanza la BD y Redis.

Es el humo del carril de emergencia del CI (`deploy.yml`, label `hotfix`): ese
carril solo corre `tests/fastapi/infra/` antes de desplegar, así que este test
es la prueba de que `create_app()` registra todos los routers sin tronar y de
que el proceso puede servir. `compileall` solo ataja errores de sintaxis; un
import roto o una dependencia caída se ven aquí.
"""


def test_la_app_arranca_y_responde_health(app_client):
    r = app_client.get("/health")
    assert r.status_code == 200, r.text


def test_ready_alcanza_la_bd_y_redis(app_client):
    r = app_client.get("/ready")
    assert r.status_code == 200, r.text
    assert r.json() == {"ready": True}
