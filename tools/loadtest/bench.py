"""Bench A/B del tier HTTP: C hilos x R peticiones a una pagina real.

  python bench.py <puerto> <concurrencia> <peticiones_por_hilo> <token> [ruta]

Mide throughput y p95. Es DIRECCIONAL, no un numero de capacidad: corre en
Docker Desktop sobre Windows, con el codigo en bind-mount y la BD de dev.
"""
import http.client
import statistics
import sys
import threading
import time
from collections import Counter

PORT = int(sys.argv[1])
C = int(sys.argv[2])
R = int(sys.argv[3])
TOKEN = sys.argv[4]
PATH = sys.argv[5] if len(sys.argv) > 5 else "/itcj/dashboard"

codes = Counter()
lat = []
lock = threading.Lock()
barrera = threading.Barrier(C + 1)


def worker():
    mine, mylat = Counter(), []
    conn = http.client.HTTPConnection("127.0.0.1", PORT, timeout=30)
    barrera.wait()
    for _ in range(R):
        t = time.time()
        try:
            conn.request("GET", PATH, headers={"Cookie": f"itcj_token={TOKEN}"})
            r = conn.getresponse()
            r.read()
            mine[r.status] += 1
        except Exception as e:
            mine[f"error:{type(e).__name__}"] += 1
            try:
                conn.close()
            except Exception:
                pass
            conn = http.client.HTTPConnection("127.0.0.1", PORT, timeout=30)
        mylat.append(time.time() - t)
    try:
        conn.close()
    except Exception:
        pass
    with lock:
        codes.update(mine)
        lat.extend(mylat)


hilos = [threading.Thread(target=worker, daemon=True) for _ in range(C)]
for h in hilos:
    h.start()
barrera.wait()
t0 = time.time()
for h in hilos:
    h.join(timeout=180)
dur = time.time() - t0

n = sum(codes.values())
ordenadas = sorted(lat)
p50 = statistics.median(ordenadas) if ordenadas else 0
p95 = ordenadas[int(len(ordenadas) * 0.95)] if ordenadas else 0
print(f"  {n} peticiones en {dur:.2f}s -> {n/dur:.1f} req/s | p50 {p50*1000:.0f}ms | p95 {p95*1000:.0f}ms")
print(f"  {dict(codes)}")
