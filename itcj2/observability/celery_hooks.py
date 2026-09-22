"""Contexto de la petición a través de Celery (Fase 5a).

Celery corre el cuerpo de una tarea en OTRO proceso (el worker), que no hereda
ningún ContextVar de quien la encoló: sin esto, las líneas del worker salen con
`trace_id`/`request_id` vacíos y no hay forma de unir en Loki la petición HTTP
con la tarea que disparó. Tres receptores de señales cruzan esa frontera sin
tocar ninguno de los sitios que encolan:

- `before_task_publish` (en quien encola) copia `snapshot()` a la cabecera
  `itcj_ctx` del mensaje.
- `task_prerun` (en el worker) liga los ids de esa cabecera antes del cuerpo.
  Corre ANTES de `LoggedTask.before_start` (orden fijo de
  `celery/app/trace.py`), así que `before_start`, `on_success` y
  `_publish_task_event` ya ven los ids restaurados.
- `task_postrun` deshace exactamente lo que ligó `task_prerun`: el proceso del
  worker ejecuta una tarea tras otra y la siguiente no puede heredar nada.

Casos que explican la forma:

- Beat y el CLI encolan sin petición: el mensaje llega sin cabecera y
  `task_prerun` acuña una raíz nueva (trace/span/request). El beat importa la
  misma `itcj2.celery_app`, así que estos receptores también están ahí; como
  no tiene nada ligado, no agrega la cabecera.
- `Task.retry()` re-publica desde dentro de la tarea, con los ids ya
  restaurados: el reintento continúa la misma traza.
- Sin cabecera se acuña la raíz SIEMPRE, sin mirar lo que ya esté ligado en
  el hilo: si un `reset` de `task_postrun` fallara alguna vez, el worker
  quedaría con ids ligados entre tareas, y heredarlos pegaría en silencio las
  tareas del beat a la traza de otra.
- En eager (`.apply()`, `task_always_eager`) Celery NO dispara
  `before_task_publish` (medido en 5.6.3): no hay cabecera y la tarea acuña
  su raíz aunque corra inline dentro de una petición; `task_postrun` le
  devuelve a quien la llamó sus propios ids.

Regla de oro 1: este módulo está en la cadena de imports de Celery (lo importa
`itcj2/celery_app.py`) y no puede cargar `prometheus_client`; de itcj2 solo
importa `context` (lo vigila `test_celery_context.py`).

Regla de oro 2: la instrumentación nunca cambia el negocio. El cuerpo entero
de cada receptor va en `try/except Exception`: un fallo se loguea y la tarea
se encola y se ejecuta igual. (El `send` de Celery 5.6 ya atrapa lo que lance
un receptor, pero es un detalle de su implementación: la regla no depende de
él.)
"""
import logging
import secrets

from celery.signals import before_task_publish, task_postrun, task_prerun

from itcj2.observability.context import bind, new_ids, reset, snapshot

logger = logging.getLogger(__name__)

HEADER = "itcj_ctx"

# Tokens de `bind()` de cada ejecución en curso, por `id()` de su
# `task.request`: Celery arma un `Context` nuevo por ejecución y es el mismo
# objeto en `task_prerun` y en `task_postrun` (lo saca de la pila después de
# `task_postrun`). Por ejecución y no por `task_id`: un reintento eager corre
# ANIDADO dentro de la ejecución original, con el mismo `task_id`. Tampoco se
# cuelgan del propio `task.request`: `Task.__call__` copia su `__dict__` en la
# petición de una llamada directa, y los tokens viajarían con ella.
_tokens: dict[int, dict] = {}


def _carried_ids(value) -> dict:
    """`trace_id`/`request_id` utilizables de un snapshot, o `{}`.

    Tolera lo que mande un productor viejo o ajeno (sin cabecera, `None`, algo
    que no es un dict, ids que no son cadenas): nada de eso tumba la tarea,
    solo hace que se acuñe una raíz.
    """
    if not isinstance(value, dict):
        return {}
    return {
        name: value[name]
        for name in ("trace_id", "request_id")
        if isinstance(value.get(name), str) and value[name]
    }


@before_task_publish.connect(weak=False, dispatch_uid="itcj2.observability.inject")
def _inject_context(headers=None, **kwargs) -> None:
    try:
        if headers is None:
            return
        snap = snapshot()
        # Sin nada ligado (beat, CLI) no se manda cabecera: el worker acuña la
        # raíz igual, y no se agregan bytes vacíos a cada mensaje del beat.
        if any(snap.values()):
            headers[HEADER] = snap
    except Exception:
        logger.exception("celery_hooks: no se pudo adjuntar el contexto al mensaje")


@task_prerun.connect(weak=False, dispatch_uid="itcj2.observability.restore")
def _bind_task_context(task=None, **kwargs) -> None:
    try:
        request = task.request
        # `.get()` y no `request.headers`: Celery vuelca las cabeceras del
        # mensaje como atributos del `Context` y en `request.headers` deja
        # solo las que no reconoce como suyas; el atributo no depende de esa
        # clasificación.
        carried = _carried_ids(request.get(HEADER))
        trace_id, span_id = new_ids()
        # La tarea abre su propio span: el del snapshot es el de quien encoló
        # (su padre), igual que un `traceparent` entrante en el middleware.
        tokens = bind(
            trace_id=carried.get("trace_id", trace_id),
            span_id=span_id,
            request_id=carried.get("request_id", secrets.token_hex(16)),
        )
        _tokens[id(request)] = tokens
    except Exception:
        logger.exception("celery_hooks: no se pudo ligar el contexto de la tarea")


@task_postrun.connect(weak=False, dispatch_uid="itcj2.observability.reset")
def _reset_task_context(task=None, **kwargs) -> None:
    try:
        tokens = _tokens.pop(id(task.request), None)
        if tokens:
            reset(tokens)
    except Exception:
        logger.exception("celery_hooks: no se pudo limpiar el contexto de la tarea")
