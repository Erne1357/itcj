"""Contrato del limitador por ventana reusable (`rate_limit.check_and_count`).

Por que existe
--------------
Las rutas publicas de la encuesta y de la inscripcion son escrituras ANONIMAS
que disparan correos. El unico limitador del repo contaba fallos de LOGIN y
falla ABIERTO a proposito: que una caida de Redis deje sin login a todo el
instituto es peor que quedarse sin rate limit un rato. En una escritura anonima
ese mismo intercambio significa que una caida de Redis elimina el unico control
que hay — de ahi `fail_open=False` (E2 del spec).

Como se simula que Redis no esta
--------------------------------
`rate_limit._redis()` (`itcj2/core/utils/rate_limit.py:16-21`) importa
`get_redis` DENTRO de la funcion, asi que el nombre se resuelve en cada llamada.
El punto de parcheo es por tanto el modulo ORIGEN,
`itcj2.core.utils.redis_conn.get_redis`. Parchear
`itcj2.core.utils.rate_limit.get_redis` no haria absolutamente nada: ese
atributo no existe en el modulo, y el test pasaria en verde contra un Redis
perfectamente vivo.

`_redis()` envuelve el import Y la llamada en un `try/except Exception`, asi que
un `get_redis` que lanza devuelve `None`, que es la senal de "no hay Redis".

Fugas entre tests
-----------------
El autouse `_clear_authz_cache` (`tests/fastapi/conftest.py:65-79`) barre `rl:*`
antes y despues de CADA test (`:57`). Ademas cada test usa una clave
irrepetible, para no depender de eso.
"""
from __future__ import annotations

import uuid

from itcj2.core.utils import rate_limit


def _key() -> str:
    """Clave irrepetible por test."""
    return uuid.uuid4().hex


def _redis_caido():
    """Sustituto de `get_redis` que revienta, como cuando Redis no responde."""
    def _boom():
        raise RuntimeError("redis caido")
    return _boom


def test_cuenta_bajo_el_limite_y_permite():
    key = _key()
    for intento in range(1, 4):
        allowed, retry_after = rate_limit.check_and_count(
            "survey:ip", key, limit=3, window=3600)
        assert allowed is True, f"el intento {intento} de 3 deberia pasar"
        assert retry_after == 0


def test_bloquea_al_pasar_el_limite_y_devuelve_retry_after():
    key = _key()
    for _ in range(3):
        rate_limit.check_and_count("survey:ip", key, limit=3, window=3600)

    allowed, retry_after = rate_limit.check_and_count(
        "survey:ip", key, limit=3, window=3600)

    assert allowed is False
    # Sale del TTL REAL de la clave, no de una constante: es lo que la ruta
    # publica pone en la cabecera `Retry-After` (E4).
    assert 0 < retry_after <= 3600


def test_sigue_bloqueado_en_los_intentos_siguientes():
    """Un intento de mas no reinicia la ventana."""
    key = _key()
    for _ in range(2):
        rate_limit.check_and_count("enroll:cn", key, limit=2, window=600)

    assert rate_limit.check_and_count("enroll:cn", key, limit=2, window=600)[0] is False
    assert rate_limit.check_and_count("enroll:cn", key, limit=2, window=600)[0] is False


def test_cada_scope_cuenta_por_separado():
    """`rl:{scope}:{key}`: el presupuesto por IP del reenvio no puede gastarse
    con los envios de la inscripcion, y viceversa (§8.1 del spec)."""
    key = _key()
    assert rate_limit.check_and_count("enroll:ip", key, limit=1, window=600)[0] is True
    assert rate_limit.check_and_count("enroll:ip", key, limit=1, window=600)[0] is False
    # Mismo `key`, otro `scope` -> otra clave, contador limpio.
    assert rate_limit.check_and_count(
        "enroll_resend:ip", key, limit=1, window=600)[0] is True


def test_fail_open_permite_cuando_redis_no_responde(monkeypatch):
    """El valor por omision conserva el intercambio del login: disponibilidad."""
    monkeypatch.setattr("itcj2.core.utils.redis_conn.get_redis", _redis_caido())

    allowed, retry_after = rate_limit.check_and_count(
        "survey:ip", _key(), limit=1, window=3600, fail_open=True)

    assert allowed is True
    assert retry_after == 0


def test_fail_closed_niega_cuando_redis_no_responde(monkeypatch):
    """E2: en una escritura anonima, sin Redis no queda NINGUN control. La ruta
    publica prefiere responder 429 a quedarse sin puerta."""
    monkeypatch.setattr("itcj2.core.utils.redis_conn.get_redis", _redis_caido())

    allowed, retry_after = rate_limit.check_and_count(
        "enroll:ip", _key(), limit=5, window=3600, fail_open=False)

    assert allowed is False
    # Sin Redis no hay TTL que consultar: se devuelve la ventana completa, para
    # que el `Retry-After` siga siendo un numero util.
    assert retry_after == 3600


def test_el_login_sigue_fallando_abierto_sin_redis(monkeypatch):
    """Las TRES funciones de login quedan intactas: sin Redis siguen dejando
    pasar y ninguna lanza. Si esto se rompe, el cambio dejo de ser aditivo."""
    monkeypatch.setattr("itcj2.core.utils.redis_conn.get_redis", _redis_caido())

    assert rate_limit.check_login_allowed("10.0.0.1", "cuenta_prueba") is True
    rate_limit.note_login_failure("10.0.0.1", "cuenta_prueba")     # no lanza
    rate_limit.reset_login_failures("10.0.0.1", "cuenta_prueba")   # no lanza
