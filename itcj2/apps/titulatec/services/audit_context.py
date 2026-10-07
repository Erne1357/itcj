"""Contexto de la bitácora: quién, desde dónde y en qué operación (spec 2026-10-07 §4.3, D10).

Los services no reciben `request`: el actor, la IP, el navegador, la ruta y el
`request_id` salen solos de aquí. `current_audit_context()` resuelve en orden:

1. Un contexto explícito de `audit_context(...)` (CLI, Celery, scripts).
2. La petición HTTP en curso, vía las ContextVars que liga
   `observability.middleware.ObservabilityMiddleware`: usuario del JWT
   (`user_id_from_scope`), `request_id` de la petición (el mismo de Loki y de la
   cabecera `X-Request-ID`), IP con la regla de `core/utils/client_ip.py`,
   navegador y la plantilla de ruta (`observability.route.normalize_route`).
   Sin usuario en la sesión -> `public`.
3. Nada de lo anterior -> `system`.

Hilos: las ContextVars viajan solas a `anyio.to_thread` / `run_in_threadpool`
(ahí corren las rutas `def` de TitulaTec), que copian el contexto. Un
`threading.Thread` crudo NO hereda nada y cae en `system`.

Sin modelos: lo importa la escucha, que se instala al cargar `models/`.
"""
from __future__ import annotations

import logging
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Iterator

from itcj2.apps.titulatec.services.audit_actions import ACTOR_KINDS

logger = logging.getLogger(__name__)

# Longitudes de las columnas de `titulatec_audit_log` (models/audit_log.py).
_LABEL_MAX = 120
_REQUEST_ID_MAX = 64
_IP_MAX = 45
_UA_MAX = 200
_ROUTE_MAX = 160


@dataclass(frozen=True)
class AuditCtx:
    """Lo que la bitácora sabe del «quién» de una operación."""
    actor_id: int | None
    actor_kind: str              # ACTOR_KINDS: user | public | system | cli | celery
    actor_label: str | None      # solo no-usuarios: «cli: init-bitacora (root)»
    request_id: str | None       # agrupa «todo lo de la misma operación»
    ip: str | None
    user_agent: str | None
    route: str | None


_EXPLICIT: ContextVar[AuditCtx | None] = ContextVar("titulatec_audit_ctx", default=None)


def _clip(value, limit: int) -> str | None:
    if value is None:
        return None
    s = str(value).replace("\x00", "").strip()
    return s[:limit] or None


@contextmanager
def audit_context(kind: str, label: str | None = None,
                  actor_id: int | None = None) -> Iterator[AuditCtx]:
    """Liga un contexto explícito mientras dura el `with` (CLI, Celery, scripts).

    Cada entrada genera su propio `request_id` (uuid): todo lo que se registre
    adentro queda agrupado como una sola operación. Anidar es válido; al salir
    se restaura el de afuera.
    """
    if kind not in ACTOR_KINDS:
        raise ValueError(f"tipo de actor desconocido para la bitácora: {kind!r}")
    ctx = AuditCtx(
        actor_id=int(actor_id) if actor_id is not None else None,
        actor_kind=kind,
        actor_label=_clip(label, _LABEL_MAX),
        request_id=uuid.uuid4().hex,
        ip=None,
        user_agent=None,
        route=None,
    )
    token = _EXPLICIT.set(ctx)
    try:
        yield ctx
    finally:
        _EXPLICIT.reset(token)


def _from_scope(scope: dict) -> AuditCtx:
    """Contexto de una petición HTTP a partir de su `scope` de ASGI."""
    from starlette.requests import Request

    from itcj2.core.utils.client_ip import client_ip
    from itcj2.observability.context import current_request_id, user_id_from_scope
    from itcj2.observability.route import UNMATCHED, normalize_route

    sub = user_id_from_scope(scope)
    try:
        actor_id = int(sub) if sub else None
    except (TypeError, ValueError):
        actor_id = None

    ip = user_agent = route = None
    try:
        request = Request(scope)
        ip = client_ip(request)
        if ip == "unknown":
            ip = None
        user_agent = request.headers.get("user-agent")
    except Exception:
        logger.debug("bitácora: no se pudieron leer las cabeceras del scope", exc_info=True)
    try:
        route = normalize_route(scope)
        if route == UNMATCHED:
            route = scope.get("path")
    except Exception:
        route = scope.get("path")

    return AuditCtx(
        actor_id=actor_id,
        actor_kind="user" if actor_id is not None else "public",
        actor_label=None,
        request_id=_clip(current_request_id(), _REQUEST_ID_MAX),
        ip=_clip(ip, _IP_MAX),
        user_agent=_clip(user_agent, _UA_MAX),
        route=_clip(route, _ROUTE_MAX),
    )


def _system() -> AuditCtx:
    """Sin contexto explícito ni petición. Si la observabilidad ligó un
    `request_id` (p. ej. el de la ejecución de una tarea de Celery), se usa
    para agrupar; si no, queda vacío."""
    from itcj2.observability.context import current_request_id
    return AuditCtx(actor_id=None, actor_kind="system", actor_label=None,
                    request_id=_clip(current_request_id(), _REQUEST_ID_MAX),
                    ip=None, user_agent=None, route=None)


def current_audit_context() -> AuditCtx:
    """El contexto vigente. Nunca truena: ante cualquier falla, `system`."""
    explicit = _EXPLICIT.get()
    if explicit is not None:
        return explicit
    try:
        from itcj2.observability.context import current_scope
        scope = current_scope()
        if scope is not None and scope.get("type") == "http":
            return _from_scope(scope)
    except Exception:
        logger.exception("bitácora: no se pudo resolver el contexto HTTP; se usa 'system'")
    try:
        return _system()
    except Exception:
        return AuditCtx(None, "system", None, None, None, None, None)
