"""Igual que pageload_probe pero CONCURRENTE: N usuarios sueltos a la vez tras
una barrera, que es el patron real de la apertura de AgendaTec (todos recargan
en el mismo segundo), no una llegada escalonada.

  python pageload_conc.py <n_usuarios> <puerto> <token>
"""
import http.client
import re
import sys
import threading
import time
from collections import Counter

N = int(sys.argv[1]) if len(sys.argv) > 1 else 50
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 8090
TOKEN = sys.argv[3] if len(sys.argv) > 3 else ""
PAGE = "/itcj/dashboard"
REF = re.compile(r'(?:src|href)="(/[^"]+)"')

codes = Counter()
lock = threading.Lock()
barrera = threading.Barrier(N + 1)


def fetch(conn, path):
    conn.request("GET", path, headers={"Cookie": f"itcj_token={TOKEN}"})
    r = conn.getresponse()
    r.read()
    return r.status


c0 = http.client.HTTPConnection("127.0.0.1", PORT, timeout=15)
c0.request("GET", PAGE, headers={"Cookie": f"itcj_token={TOKEN}"})
r0 = c0.getresponse()
assets = sorted(set(REF.findall(r0.read().decode("utf-8", "replace"))))
c0.close()


def usuario():
    local = Counter()
    barrera.wait()          # todos arrancan en el mismo instante
    try:
        conn = http.client.HTTPConnection("127.0.0.1", PORT, timeout=15)
        local[fetch(conn, PAGE)] += 1
        for a in assets:
            local[fetch(conn, a)] += 1
        conn.close()
    except Exception as e:
        local[f"error:{type(e).__name__}"] += 1
    with lock:
        codes.update(local)


hilos = [threading.Thread(target=usuario, daemon=True) for _ in range(N)]
for h in hilos:
    h.start()
barrera.wait()
t0 = time.time()
for h in hilos:
    h.join(timeout=60)
dur = time.time() - t0

total = sum(codes.values())
malos = codes.get(429, 0)
print(f"{N} usuarios SIMULTANEOS x {len(assets)+1} peticiones = {total} en {dur:.2f}s (~{total/dur:.0f} req/s)")
for k, v in sorted(codes.items(), key=lambda x: str(x[0])):
    print(f"  HTTP {k}: {v}")
print(f"  => {malos} en 429 ({malos*100//total if total else 0}%)")
