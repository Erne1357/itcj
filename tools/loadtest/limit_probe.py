"""Sonda de limites del nginx del host (solo stdlib).

Simula el peor caso de NAT: todas las conexiones salen de la MISMA IP, que es
justo lo que le pasaria al campus si sale por un solo egress.

  python limit_probe.py ws 50 8090      -> abre 50 WebSockets y los DEJA abiertos
  python limit_probe.py burst 100 8090  -> 100 GET seguidos (prueba limit_req)

El handshake WS de engine.io (?EIO=4&transport=websocket) no necesita auth: la
autenticacion del namespace ocurre despues, en la capa socket.io. Para
`limit_conn` lo que cuenta es la conexion, que es exactamente lo que sostiene
un usuario real con la campanita abierta.
"""
import base64
import os
import socket
import sys
import time
from collections import Counter

MODE = sys.argv[1] if len(sys.argv) > 1 else "ws"
N = int(sys.argv[2]) if len(sys.argv) > 2 else 50
PORT = int(sys.argv[3]) if len(sys.argv) > 3 else 8090
HOST = "127.0.0.1"


def status_of(raw: bytes) -> str:
    first = raw.split(b"\r\n", 1)[0].decode("latin1", "replace")
    parts = first.split(" ")
    return parts[1] if len(parts) > 1 else first or "sin-respuesta"


def open_ws():
    """Abre una conexion WebSocket y la devuelve viva (no la cierra)."""
    key = base64.b64encode(os.urandom(16)).decode()
    req = (
        "GET /socket.io/?EIO=4&transport=websocket HTTP/1.1\r\n"
        f"Host: {HOST}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        "Sec-WebSocket-Version: 13\r\n"
        "Origin: http://localhost:8080\r\n"
        "\r\n"
    ).encode()
    s = socket.create_connection((HOST, PORT), timeout=8)
    s.sendall(req)
    return s, status_of(s.recv(4096))


def plain_get(path="/itcj/login"):
    req = (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {HOST}\r\n"
        "Connection: close\r\n"
        "\r\n"
    ).encode()
    s = socket.create_connection((HOST, PORT), timeout=8)
    try:
        s.sendall(req)
        return status_of(s.recv(4096))
    finally:
        s.close()


if MODE == "ws":
    vivos, codigos = [], Counter()
    primer_rechazo = None
    for i in range(1, N + 1):
        try:
            s, code = open_ws()
        except Exception as e:  # conexion rechazada a nivel TCP
            code = f"error:{type(e).__name__}"
            s = None
        codigos[code] += 1
        if code == "101":
            vivos.append(s)
        elif primer_rechazo is None:
            primer_rechazo = i
            if s:
                s.close()
        elif s:
            s.close()

    print(f"WebSockets intentados: {N}  (todos desde la MISMA IP)")
    for code, n in sorted(codigos.items()):
        print(f"  HTTP {code}: {n}")
    print(f"  aceptados y vivos: {len(vivos)}")
    if primer_rechazo:
        print(f"  primer rechazo en la conexion #{primer_rechazo}")
    else:
        print("  ningun rechazo -> no hay tope por IP para WebSockets")

    time.sleep(3)  # mantenerlas abiertas para poder mirar el error.log
    for s in vivos:
        s.close()

elif MODE == "burst":
    codigos = Counter()
    t0 = time.time()
    for _ in range(N):
        try:
            codigos[plain_get()] += 1
        except Exception as e:
            codigos[f"error:{type(e).__name__}"] += 1
    dur = time.time() - t0
    print(f"{N} GET en {dur:.2f}s (~{N/dur:.0f} req/s desde una sola IP)")
    for code, n in sorted(codigos.items()):
        print(f"  HTTP {code}: {n}")
