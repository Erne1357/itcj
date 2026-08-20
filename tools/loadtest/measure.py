"""Cuenta conexiones TCP reales del proceso leyendo /proc/net/tcp{,6}.
Sin dependencias: la imagen no trae `ss` ni `netstat`."""
import sys

PORT_DB = 5432
PORT_APP = 8001


def leer():
    filas = []
    for p in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            with open(p) as f:
                filas += [l.split() for l in f.read().splitlines()[1:]]
        except FileNotFoundError:
            pass
    return filas


filas = leer()
est = [f for f in filas if f[3] == "01"]          # 01 = ESTABLISHED
salientes_db = sum(1 for f in est if int(f[2].split(":")[1], 16) == PORT_DB)
entrantes_app = sum(1 for f in est if int(f[1].split(":")[1], 16) == PORT_APP)
print(f"conexiones a pgbouncer:5432 = {salientes_db}")
print(f"conexiones entrantes :8001  = {entrantes_app}")
