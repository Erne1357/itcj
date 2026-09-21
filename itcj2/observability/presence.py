"""Colector de `/metrics` para presencia y conexiones de Socket.IO (Task 8).

Decisión del dueño 2026-09-21: saber CUÁNTOS hay conectados, nunca QUIÉNES.
Ninguna etiqueta lleva uid ni sid — solo `bucket`/`namespace` y un conteo.

R14: colector evaluado A LA HORA DEL SCRAPE (no Gauges reales actualizados
por una sonda, como `saturation.py`). Encaja aquí aunque el plan descarte
colectores para la saturación: la presencia vive en Redis, compartida por
todos los workers que la escriben (no hay "un pool por proceso" que un
`livesum` tenga que sumar), y el conteo de sockets es del ÚNICO worker del
tier `sockets` — no hay nada que agregar entre procesos.

El filtro por `APP_ROLE` se comprueba DENTRO de `collect()`, en cada scrape,
en vez de condicionar el alta en `metrics.register_scrape_collector()`: este
mismo objeto se registra siempre (ver `metrics.py`), y así un test puede
alternar `APP_ROLE` con un simple `monkeypatch.setattr(get_settings(), ...)`
sin reimportar módulos ni lanzar un subproceso — el patrón que ya usan los
tests de `saturation.py`. El costo es un `get_settings()` de más por scrape
(cada 30 s), insignificante.
"""
import logging

from prometheus_client.core import GaugeMetricFamily

from itcj2.config import get_settings

logger = logging.getLogger("itcj2.observability")

# Buckets del contrato de métricas (§ global-constraints). "all" no es un
# bucket de presence_service: es `total` (la UNIÓN de uids vigentes, no la
# suma de los tres) renombrado para la etiqueta.
_BUCKET_LABELS = ("students", "staff", "admins", "all")

_ROLES_WITH_PRESENCE = ("socket", "all")


class PresenceCollector:
    """`collect()` corre en el hilo del scrape (`/metrics` es `def`, no
    `async def`) mientras el loop de asyncio sigue conectando/desconectando
    clientes de Socket.IO en otra tarea. Por eso el conteo de sockets nunca
    ITERA `sio.manager.rooms`: solo toma `len()` de los dicts/bidicts
    relevantes, que bajo el GIL es una lectura atómica del tamaño y no puede
    chocar con una mutación a medio hacer (a diferencia de iterar sus
    claves, que sí puede lanzar "dictionary changed size during
    iteration")."""

    def collect(self):
        if get_settings().APP_ROLE not in _ROLES_WITH_PRESENCE:
            return

        presence_family = self._presence_family()
        if presence_family is not None:
            yield presence_family

        socket_family = self._socket_family()
        if socket_family is not None:
            yield socket_family

    def _presence_family(self):
        try:
            # Imports locales: evitan cargar `itcj2.core` (y su cadena de
            # modelos/BD) al importar `itcj2.observability.metrics`, que
            # importa este módulo a nivel de paquete (ver metrics.py).
            from itcj2.core.services.presence_service import get_counts
            from itcj2.core.utils.redis_conn import get_redis

            counts = get_counts(get_redis())
        except Exception:
            # Redis caído: el scrape sigue respondiendo 200 sin esta familia
            # (contrato de la Task 8) — un panel con un hueco es mejor que un
            # `/metrics` que Prometheus marca `up=0` por completo por culpa
            # de una dependencia que ni siquiera es la que se quiere medir.
            logger.exception(
                "presencia: no se pudo leer Redis, familia itcj_presence_users omitida"
            )
            return None

        family = GaugeMetricFamily(
            "itcj_presence_users",
            "Usuarios conectados vigentes (poda en lectura, ventana "
            "PRESENCE_WINDOW_SECONDS). Solo conteos, nunca identidades.",
            labels=["bucket"],
        )
        # `total` de `get_counts()` es la UNIÓN de uids vigentes (no la suma
        # de los tres buckets): se expone como `all`, el nombre del contrato.
        values = {**counts, "all": counts["total"]}
        for bucket in _BUCKET_LABELS:
            family.add_metric([bucket], values[bucket])
        return family

    def _socket_family(self):
        try:
            # Import local: importar `itcj2.sockets.server` dispara la
            # inicialización del paquete `itcj2.sockets` (registra los 6
            # namespaces sobre el `sio` compartido) si nadie lo hizo antes —
            # en un worker `http` eso nunca pasa porque `collect()` ya
            # retornó arriba sin llegar aquí.
            from itcj2.sockets.server import sio

            rooms = sio.manager.rooms
            # `sio.handlers` es la lista ESTÁTICA de namespaces con handlers
            # registrados (`.on(..., namespace=NAMESPACE)`, todo al importar
            # el paquete): a diferencia de `sio.manager.rooms`, no depende de
            # que haya al menos una conexión viva, así que un namespace vacío
            # sigue apareciendo en `/metrics` con 0 en vez de faltar de la
            # serie.
            counts = {
                # `rooms[namespace][None]` es la sala implícita de
                # python-socketio con TODOS los sids conectados a ese
                # namespace (ver `base_manager.py::connect`/`is_connected`);
                # ausente hasta la primera conexión, de ahí los
                # `.get(..., {})` encadenados.
                namespace: len(rooms.get(namespace, {}).get(None, {}))
                for namespace in sio.handlers
            }
        except Exception:
            # Mismo contrato que `_presence_family()`: `sio.manager.rooms` lo
            # muta el loop de asyncio en otra tarea mientras este scrape corre
            # en el threadpool (ver docstring de la clase) — una lectura que
            # choque con una estructura inesperada no debe tirar TODO el
            # scrape (RED, saturación y lag también se sirven desde aquí).
            logger.exception(
                "sockets: no se pudo leer sio.manager.rooms, familia "
                "itcj_socket_connections omitida"
            )
            return None

        family = GaugeMetricFamily(
            "itcj_socket_connections",
            "Sockets conectados por namespace, en el worker de ESTE proceso.",
            labels=["namespace"],
        )
        for namespace, connected in counts.items():
            family.add_metric([namespace], connected)
        return family
