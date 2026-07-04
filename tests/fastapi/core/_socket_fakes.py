"""Doble de socketio.AsyncServer para testear handlers de namespaces sin red.

Reproduce el subset que usan los handlers: on() como decorador-registrador,
save_session/get_session, enter_room (alimenta manager.rooms) y emit (grabado).
IMPORTANTE: igual que python-socketio real, el sid que se está desconectando
AÚN aparece en manager.get_participants durante el handler de disconnect
(la limpieza de rooms ocurre después del trigger del evento).
"""
from itcj2.core.utils.jwt_tools import encode_jwt


class FakeManager:
    def __init__(self):
        self.rooms = {}  # (namespace, room) -> list[(sid, eio_sid)]

    def get_participants(self, namespace, room):
        return iter(self.rooms.get((namespace, room), []))


class FakeSio:
    def __init__(self):
        self.handlers = {}   # (namespace, event) -> coroutine fn
        self.sessions = {}   # (namespace, sid) -> dict
        self.emitted = []    # [{"event","data","to","namespace"}]
        self.manager = FakeManager()

    def on(self, event, namespace=None):
        def decorator(fn):
            self.handlers[(namespace, event)] = fn
            return fn
        return decorator

    async def save_session(self, sid, session, namespace=None):
        self.sessions[(namespace, sid)] = session

    async def get_session(self, sid, namespace=None):
        return self.sessions.get((namespace, sid), {})

    async def enter_room(self, sid, room, namespace=None):
        self.manager.rooms.setdefault((namespace, room), []).append((sid, sid))

    async def emit(self, event, data=None, to=None, room=None, namespace=None):
        self.emitted.append({"event": event, "data": data, "to": to, "namespace": namespace})


def environ_for(uid, role="staff", cn=None):
    """Environ WS con cookie itcj_token firmada con el SECRET del container."""
    token = encode_jwt({"sub": str(uid), "role": role, "cn": cn, "name": "X"}, hours=1)
    return {"HTTP_COOKIE": f"itcj_token={token}"}
