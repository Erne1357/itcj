"""Sonda de lag del event loop (plan Fase 3).

Pide dormir `LAG_INTERVAL_SECONDS` y mide cuánto de más tardó el loop en
despertarla: ese exceso es el tiempo en que el loop estuvo ocupado con código
síncrono y no pudo atender a nadie. Es la métrica que hace falsable el
arreglo de la Fase 6 (las llamadas síncronas del middleware de sesión).

No todo el lag será de la Fase 6: los handlers `connect`/`disconnect` de
`/notify` (`itcj2/sockets/notifications.py`) hacen llamadas síncronas cortas
a Redis dentro del loop a propósito (patrón de `slots.py`). Un lag algo alto
en ráfagas de conexión después de la Fase 6 no significa que no funcionó.

La misma tarea refresca la saturación cada `SATURATION_EVERY` vueltas, para
no añadir un segundo temporizador.
"""
import asyncio
import logging
import time

from itcj2.observability import metrics, saturation

logger = logging.getLogger("itcj2.observability")

LAG_INTERVAL_SECONDS = 0.25
# 20 × 0,25 s = 5 s entre muestras de saturación.
SATURATION_EVERY = 20
# Nombre de la tarea: la encuentra quien inspeccione `asyncio.all_tasks()`.
PROBE_TASK_NAME = "itcj-loop-lag"


async def run_probe(
    interval: float = LAG_INTERVAL_SECONDS,
    saturation_every: int = SATURATION_EVERY,
) -> None:
    """Corre hasta que la cancelen (el `lifespan`, en el apagado)."""
    iteration = 0
    while True:
        # El `await` va FUERA del try: si un ciclo lanzara antes de ceder el
        # control, un `except` que atrapa y sigue sería un bucle infinito
        # que nunca suelta el loop. `asyncio.sleep` solo lanza
        # `CancelledError`, que no es `Exception` y sale limpio.
        start = time.perf_counter()
        await asyncio.sleep(interval)
        lag = time.perf_counter() - start - interval
        try:
            # El loop puede despertar un pelo antes (resolución de su
            # reloj): un negativo restaría a la suma del histograma.
            metrics.EVENT_LOOP_LAG.observe(max(lag, 0.0))
            if iteration % saturation_every == 0:
                saturation.update_gauges()
        except Exception:
            # Nunca muere por un ciclo: una sonda muerta deja los Gauges
            # congelados en su último valor sin que nada avise.
            logger.exception("sonda de lag: ciclo fallido")
        iteration += 1
