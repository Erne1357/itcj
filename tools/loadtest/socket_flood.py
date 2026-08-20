"""Abre N clientes Socket.IO REALES (con namespace, ping/pong y todo) contra el
nginx replica del host, cada uno con un usuario distinto.

  python socket_flood.py <n> <segundos_sostenido> <namespace> [dia]

  namespace = notify  -> el socket global de notificaciones que trae TODO usuario
  namespace = slots   -> el de AgendaTec: connect + join_day (2 golpes a la BD
                         por alumno, via asyncio.to_thread)

Deja /tmp/flood_stats.json con el resultado para leerlo desde fuera.
"""
import asyncio
import json
import sys
import time

import socketio

from itcj2.core.utils.jwt_tools import encode_jwt

N = int(sys.argv[1])
HOLD = int(sys.argv[2])
NS = "/" + (sys.argv[3] if len(sys.argv) > 3 else "notify")
DAY = sys.argv[4] if len(sys.argv) > 4 else "2026-08-20"
URL = "http://itcj-hostsim"

ok = 0
fail = {}
recibidos = 0
clientes = []
lock = asyncio.Lock()


async def uno(i: int):
    global ok, recibidos
    uid = 100000 + i                       # usuario distinto por cliente
    tok = encode_jwt({"sub": str(uid), "role": "student", "cn": f"T{uid}"})
    c = socketio.AsyncClient(reconnection=False)

    @c.on("notify", namespace=NS)
    async def _n(data):
        global recibidos
        async with lock:
            recibidos += 1

    @c.on("slots_snapshot", namespace=NS)
    async def _s(data):
        global recibidos
        async with lock:
            recibidos += 1

    try:
        await c.connect(
            URL, namespaces=[NS],
            headers={"Cookie": f"itcj_token={tok}"},
            transports=["websocket"],
        )
        if NS == "/slots":
            await c.emit("join_day", {"day": DAY}, namespace=NS)
        async with lock:
            ok += 1
        clientes.append(c)
    except Exception as e:
        k = f"{type(e).__name__}: {str(e)[:60]}"
        async with lock:
            fail[k] = fail.get(k, 0) + 1


async def main():
    t0 = time.time()
    # En oleadas de 50: un herd real tampoco llega en el mismo microsegundo.
    for base in range(0, N, 50):
        await asyncio.gather(*(uno(i) for i in range(base, min(base + 50, N))))
    dur = time.time() - t0
    print(f"CONECTADOS {ok}/{N} en {dur:.1f}s", flush=True)
    if fail:
        print("FALLOS:", fail, flush=True)

    with open("/tmp/flood_stats.json", "w") as f:
        json.dump({"ok": ok, "n": N, "dur": dur, "fail": fail}, f)

    print(f"SOSTENIENDO {HOLD}s...", flush=True)
    await asyncio.sleep(HOLD)
    print(f"eventos recibidos durante el hold: {recibidos}", flush=True)

    await asyncio.gather(*(c.disconnect() for c in clientes), return_exceptions=True)
    print("DESCONECTADOS", flush=True)


asyncio.run(main())
