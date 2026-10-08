"""Instrumentación del tier de Socket.IO (plan Fase 5c).

Un único punto para los 6 namespaces: `InstrumentedAsyncServer` sobrescribe
`_trigger_event`, por donde python-socketio 5.17 despacha TODO handler
(`_handle_event_internal` para eventos, `_handle_connect` para connect,
`_handle_disconnect` y el cierre del servidor para disconnect) con la firma
`_trigger_event(self, event, namespace, *args)`; `args[0]` es el `sid`. Es un
método privado: al subir python-socketio hay que re-verificar esa firma (el
test de este módulo lo ejerce por el despacho real). Así no se toca ningún
handler, ni los de `/system`, registrados desde dos módulos.

Cada evento acuña una raíz de trace nueva: no hay petición HTTP detrás y un
evento no es hijo de nadie. Sin esto las líneas de log de los handlers salen
sin `trace_id` ni `request_id` y no se pueden buscar en Loki.

Decisiones:
- Un rechazo de conexión (`return False`, `ConnectionRefusedError`) es `ok`:
  es la autenticación funcionando, no un fallo del servidor. Cualquier otra
  excepción es `error` y se re-lanza tal cual.
- `connect(sid, environ, auth)` falla con `TypeError` en handlers de firma
  vieja y python-socketio reintenta sin `auth`: ese primer intento no es un
  evento y no se cuenta (si no, cada conexión sumaría un `error` falso).
- `user_id` sale de la sesión que los handlers `connect` ya guardan con
  `save_session` (memoria del servidor, sin E/S). Durante `connect` aún no
  hay sesión y queda vacío.
- Nada de la instrumentación rompe ni silencia al handler: todo va en
  `try/except Exception` y la excepción original sube intacta.
"""
import logging
from time import perf_counter

import socketio

from itcj2.observability import context

logger = logging.getLogger("itcj2.sockets.instrumentation")

# Conjunto CERRADO de namespaces (R-cardinalidad): un cliente puede pedir
# cualquier nombre y no debe abrir series.
NAMESPACES = frozenset(
    {"/helpdesk", "/maint", "/notify", "/requests", "/slots", "/system"}
)
OTHER = "otro"

_REFUSALS = (socketio.exceptions.ConnectionRefusedError, ConnectionRefusedError)


def _labels(server, event, namespace) -> tuple[str, str]:
    """`(namespace, event)` ya colapsados a sus conjuntos cerrados.

    El evento es válido solo si hay un handler registrado para él en ese
    namespace (`connect` y `disconnect` incluidos): lo emitido por un cliente
    sin handler cuenta como "otro".
    """
    ns = namespace if namespace in NAMESPACES else OTHER
    if ns == OTHER:
        return OTHER, OTHER
    handlers = server.handlers.get(namespace) or {}
    return ns, event if event in handlers else OTHER


async def _user_id(server, event, namespace, args) -> str:
    if event == "connect" or not args:
        return ""
    try:
        session = await server.get_session(args[0], namespace=namespace)
        sub = ((session or {}).get("user") or {}).get("sub")
        return "" if sub is None else str(sub)
    except Exception:
        return ""


def _is_signature_mismatch(exc: TypeError) -> bool:
    """¿El `TypeError` lo levantó la LLAMADA al handler y no su cuerpo?

    En ese caso el traceback termina en el propio `_trigger_event` de
    python-socketio (no hay frame del handler debajo).
    """
    tb = exc.__traceback__
    if tb is None:
        return False
    while tb.tb_next is not None:
        tb = tb.tb_next
    return tb.tb_frame.f_code is socketio.AsyncServer._trigger_event.__code__


def _record(namespace, event, status, started) -> None:
    from itcj2.observability.metrics import SOCKET_EVENT_DURATION, SOCKET_EVENTS

    SOCKET_EVENTS.labels(namespace=namespace, event=event, status=status).inc()
    SOCKET_EVENT_DURATION.labels(namespace=namespace, event=event).observe(
        perf_counter() - started
    )


class InstrumentedAsyncServer(socketio.AsyncServer):
    async def _trigger_event(self, event, namespace, *args):
        tokens = None
        labels = (OTHER, OTHER)
        started = perf_counter()
        try:
            trace_id, span_id = context.new_ids()
            user_id = await _user_id(self, event, namespace, args)
            # `scope` mínimo con la forma que lee el filtro de logs: así
            # `user_id` sale en cada línea de log del handler.
            scope = {"state": {"current_user": {"sub": user_id or None}}}
            tokens = context.bind(
                trace_id=trace_id,
                span_id=span_id,
                request_id=context.new_ids()[0],
                scope=scope,
                sid=str(args[0]) if args else "",
            )
            labels = _labels(self, event, namespace)
        except Exception:
            logger.warning("socket: no se pudo ligar el contexto", exc_info=True)

        status = "ok"
        counted = True
        try:
            return await super()._trigger_event(event, namespace, *args)
        except Exception as exc:
            if isinstance(exc, _REFUSALS):
                pass
            elif (
                event == "connect"
                and isinstance(exc, TypeError)
                and _is_signature_mismatch(exc)
            ):
                counted = False
            else:
                status = "error"
            raise
        except BaseException:
            # Cancelación (cierre del servidor): ni éxito ni fallo del handler.
            counted = False
            raise
        finally:
            try:
                if counted:
                    _record(*labels, status, started)
            except Exception:
                logger.warning("socket: no se pudo registrar la métrica", exc_info=True)
            if tokens is not None:
                try:
                    context.reset(tokens)
                except Exception:
                    logger.warning("socket: no se pudo limpiar el contexto", exc_info=True)
