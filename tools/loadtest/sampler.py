"""Muestrea /proc/net/tcp cada 100ms y reporta el PICO de conexiones a la BD.
El pico ocurre durante la rafaga de connects (2-3s), no se ve midiendo despues."""
import json
import sys
import time

SEGUNDOS = float(sys.argv[1]) if len(sys.argv) > 1 else 30


def contar():
    db = app = 0
    for p in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            with open(p) as f:
                for l in f.read().splitlines()[1:]:
                    c = l.split()
                    if c[3] != "01":
                        continue
                    if int(c[2].split(":")[1], 16) == 5432:
                        db += 1
                    if int(c[1].split(":")[1], 16) == 8001:
                        app += 1
        except FileNotFoundError:
            pass
    return db, app


pico_db = pico_app = 0
serie = []
fin = time.time() + SEGUNDOS
while time.time() < fin:
    db, app = contar()
    pico_db = max(pico_db, db)
    pico_app = max(pico_app, app)
    serie.append(db)
    time.sleep(0.1)

with open("/tmp/sampler.json", "w") as f:
    json.dump({"pico_db": pico_db, "pico_sockets": pico_app,
               "muestras_con_db>0": sum(1 for x in serie if x > 0),
               "muestras": len(serie)}, f)
print(f"PICO conexiones a pgbouncer: {pico_db}")
print(f"PICO sockets entrantes     : {pico_app}")
