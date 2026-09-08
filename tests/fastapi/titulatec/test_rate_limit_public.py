"""Contrato del limitador por ventana reusable (`rate_limit.check_and_count`).

Por qué existe
--------------
Las rutas públicas de la encuesta y de la inscripción son escrituras ANÓNIMAS
que disparan correos. El único limitador del repo contaba fallos de LOGIN y
falla ABIERTO a propósito: que una caída de Redis deje sin login a todo el
instituto es peor que quedarse sin rate limit un rato. En una escritura anónima
ese mismo intercambio significa que una caída de Redis elimina el único control
que hay — de ahí `fail_open=False` (E2 del spec).

Cómo se simula que Redis falla
------------------------------
Hay DOS modos de fallo, y los dos importan porque `check_and_count` honra
`fail_open` en los dos sitios:

1. **No hay cliente.** `rate_limit._redis()` envuelve el import Y la llamada en
   un `try/except Exception`, así que un `get_redis` que lanza devuelve `None`
   y se toma la guardia `if r is None`. Es lo que hace `_redis_caido`.
2. **El cliente revienta a mitad.** `get_redis` devuelve un objeto vivo cuyo
   `incr` lanza, y entonces se toma el `except` de DENTRO de la función. Es un
   camino distinto: los tests del punto 1 no lo rozan siquiera, porque nunca
   llegan a tener cliente. Es lo que hace `_RedisQueRevientaAlContar`.

Dónde parchear
--------------
`rate_limit._redis()` (`itcj2/core/utils/rate_limit.py:16-21`) importa
`get_redis` DENTRO de la función, así que el nombre se resuelve en cada llamada
y el punto de parcheo es el módulo ORIGEN,
`itcj2.core.utils.redis_conn.get_redis`. Parchear
`itcj2.core.utils.rate_limit.get_redis` no sirve, pero NO porque se cuele en
silencio: ese atributo no existe en el módulo, y `monkeypatch.setattr` levanta
`AttributeError` en el acto con su `raising=True` por omisión. El test se cae
con un error ruidoso; no pasa en verde contra un Redis vivo.

Fugas entre tests
-----------------
El autouse `_clear_authz_cache` (`tests/fastapi/conftest.py:65-79`) barre `rl:*`
antes y después de CADA test (`:57`). Además cada test usa una clave
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


class _RedisQueRevientaAlContar:
    """Cliente VIVO cuyo `incr` lanza, para ejercitar el `except` de dentro.

    `_redis_caido` no sirve para esto: ahí quien lanza es `get_redis`, el
    `try/except` de `_redis()` lo convierte en `None` y la llamada sale por la
    guardia `if r is None` sin pisar jamás el bloque `try` real.
    """

    def __init__(self):
        self.incr_llamado = False

    def incr(self, key):
        self.incr_llamado = True
        raise RuntimeError("conexion perdida a mitad del INCR")

    def expire(self, key, window):  # pragma: no cover
        raise AssertionError("inalcanzable: incr revienta antes")

    def ttl(self, key):  # pragma: no cover
        raise AssertionError("inalcanzable: incr revienta antes")


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
    """Un intento de más no reinicia la ventana."""
    key = _key()
    for _ in range(2):
        rate_limit.check_and_count("enroll:cn", key, limit=2, window=600)

    assert rate_limit.check_and_count("enroll:cn", key, limit=2, window=600)[0] is False
    assert rate_limit.check_and_count("enroll:cn", key, limit=2, window=600)[0] is False


def test_cada_scope_cuenta_por_separado():
    """`rl:{scope}:{key}`: el presupuesto por IP del reenvío no puede gastarse
    con los envíos de la inscripción, y viceversa (§8.1 del spec)."""
    key = _key()
    assert rate_limit.check_and_count("enroll:ip", key, limit=1, window=600)[0] is True
    assert rate_limit.check_and_count("enroll:ip", key, limit=1, window=600)[0] is False
    # Mismo `key`, otro `scope` -> otra clave, contador limpio.
    assert rate_limit.check_and_count(
        "enroll_resend:ip", key, limit=1, window=600)[0] is True


def test_fail_open_permite_cuando_redis_no_responde(monkeypatch):
    """El valor por omisión conserva el intercambio del login: disponibilidad."""
    monkeypatch.setattr("itcj2.core.utils.redis_conn.get_redis", _redis_caido())

    allowed, retry_after = rate_limit.check_and_count(
        "survey:ip", _key(), limit=1, window=3600, fail_open=True)

    assert allowed is True
    assert retry_after == 0


def test_fail_closed_niega_cuando_redis_no_responde(monkeypatch):
    """E2: en una escritura anónima, sin Redis no queda NINGÚN control. La ruta
    pública prefiere responder 429 a quedarse sin puerta."""
    monkeypatch.setattr("itcj2.core.utils.redis_conn.get_redis", _redis_caido())

    allowed, retry_after = rate_limit.check_and_count(
        "enroll:ip", _key(), limit=5, window=3600, fail_open=False)

    assert allowed is False
    # Sin Redis no hay TTL que consultar: se devuelve la ventana completa, para
    # que el `Retry-After` siga siendo un numero util.
    assert retry_after == 3600


def test_fail_open_permite_si_el_cliente_revienta_a_mitad(monkeypatch):
    """El `except` de dentro de `check_and_count` también honra `fail_open`.

    Camino distinto al de `test_fail_open_permite_cuando_redis_no_responde`:
    aquí SÍ hay cliente, y revienta al ejecutar el comando.
    """
    fake = _RedisQueRevientaAlContar()
    monkeypatch.setattr("itcj2.core.utils.redis_conn.get_redis", lambda: fake)

    allowed, retry_after = rate_limit.check_and_count(
        "survey:ip", _key(), limit=1, window=3600, fail_open=True)

    assert fake.incr_llamado, "se colo por la guardia r is None: el except no se probo"
    assert allowed is True
    assert retry_after == 0


def test_fail_closed_niega_si_el_cliente_revienta_a_mitad(monkeypatch):
    """El caso que de verdad protege la escritura anónima.

    Un Redis que acepta conexiones pero falla en cada comando NO da `None` en
    `_redis()`: llega al `try` y sale por el `except`. Si alguien simplifica
    ese bloque a fallar siempre abierto, el endpoint público se queda sin
    puerta y ningún otro test lo nota. Este se pone rojo.
    """
    fake = _RedisQueRevientaAlContar()
    monkeypatch.setattr("itcj2.core.utils.redis_conn.get_redis", lambda: fake)

    allowed, retry_after = rate_limit.check_and_count(
        "enroll:ip", _key(), limit=5, window=3600, fail_open=False)

    assert fake.incr_llamado, "se colo por la guardia r is None: el except no se probo"
    assert allowed is False
    assert retry_after == 3600


def test_el_login_sigue_fallando_abierto_sin_redis(monkeypatch):
    """Las TRES funciones de login quedan intactas: sin Redis siguen dejando
    pasar y ninguna lanza. Si esto se rompe, el cambio dejó de ser aditivo."""
    monkeypatch.setattr("itcj2.core.utils.redis_conn.get_redis", _redis_caido())

    assert rate_limit.check_login_allowed("10.0.0.1", "cuenta_prueba") is True
    rate_limit.note_login_failure("10.0.0.1", "cuenta_prueba")     # no lanza
    rate_limit.reset_login_failures("10.0.0.1", "cuenta_prueba")   # no lanza
