"""Escucha `after_flush` de la bitácora: espejo de `ProcessEvent` + red ORM (spec 2026-10-07 §4.4).

Un solo `after_flush` global sobre `sqlalchemy.orm.Session`. Lo instala
`install()` al final de `itcj2/apps/titulatec/models/__init__.py`: cualquier
import de un modelo de TitulaTec pasa antes por ese paquete, así que la escucha
existe en todo proceso (HTTP, Celery, CLI, pruebas) ANTES del primer flush que
pueda tocar una tabla `titulatec_*`. En un proceso que nunca carga esos modelos
no hay nada que auditar.

Qué escribe, en la MISMA transacción del cambio (D8):
1. Espejo: cada `ProcessEvent` nuevo -> fila `source='process_event'`,
   `action='process.<event_type>'`, módulo por prefijo, `reason` de
   `payload.reason`/`payload.note`, payload copiado (enmascarado). El actor es
   el del EVENTO: un evento con `actor_id` NULL lo hizo el sistema (`system`, o
   el canal `public`/`cli`/`celery`), no quien hizo la petición; la petición
   sigue a la vista por `request_id`/`ip`/`route`.
2. Red ORM: cada fila nueva/modificada/borrada de una tabla `titulatec_*` que no
   esté en `NET_EXCLUDED_TABLES` -> `source='data'`, `action='data.insert|update|
   delete'`, con el diff por columna (sin `updated_at`; un cambio sin diff no deja
   fila), a nombre de quien opera (el contexto). Columnas sensibles como "***" (D9).
3. Todo en UN `INSERT` multi-fila por `session.connection()` (Core): +1 sentencia
   por flush con escrituras titulatec, 0 en lecturas. Nunca `session.add` dentro
   del flush. (Las filas de `AuditService.record` del mismo flush van aparte, en
   UN `INSERT` del ORM: todas llevan el mismo juego de llaves.)
4. Un error de Python al armar UNA fila se loguea y esa fila se omite: la
   operación de negocio sigue. Sin SAVEPOINT (costaría 2 viajes por flush), así
   que un error de la BD en el INSERT sí revierte la operación — con las filas ya
   saneadas y recortadas a sus columnas no debería ocurrir.

Lo que NO ve (lo cubren acciones explícitas de cada service): `query.update()` /
`query.delete()` masivos, SQL crudo (`text(...)`, seeders DML, `INSERT ... ON
CONFLICT` de los contadores de folios) y `bulk_save_objects`/`bulk_*`.

Lee SOLO el estado ya cargado de cada objeto (`state.dict` y la historia de
atributos): nunca dispara una consulta dentro del flush.
"""
from __future__ import annotations

import logging
from typing import Any

import json

from sqlalchemy import event, insert
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import Session

from itcj2.apps.titulatec.services.audit_actions import (
    NET_EXCLUDED_TABLES,
    PROCESS_EVENT_PREFIX,
    TABLE_MODULES,
    process_event_module,
)
from itcj2.apps.titulatec.services.audit_context import (
    INT32, INT64, AuditCtx, current_audit_context, to_db_int,
)
from itcj2.apps.titulatec.services.audit_service import AuditService, _masked

logger = logging.getLogger(__name__)

_AUDIT_TABLE = "titulatec_audit_log"
_EVENTS_TABLE = "titulatec_process_events"
_PROCESSES_TABLE = "titulatec_processes"
_PREFIX = "titulatec_"

# Columnas que no entran al diff de un cambio, ni a la foto de un alta: son el
# reloj de la propia fila y en ese momento valen lo mismo que `occurred_at`
# (PostgreSQL devuelve los defaults del servidor por RETURNING, así que SÍ están
# cargados). En una baja se conservan: ahí dicen cuándo nació lo que se borró.
_DIFF_IGNORED = frozenset({"updated_at"})
_INSERT_IGNORED = frozenset({"created_at", "updated_at"})

# Cache por mapper: nombre de su tabla (o None si no es una tabla simple).
_TABLE_OF_MAPPER: dict = {}


def _table_name(mapper) -> str | None:
    try:
        return _TABLE_OF_MAPPER[mapper]
    except KeyError:
        name = getattr(mapper.local_table, "name", None)
        _TABLE_OF_MAPPER[mapper] = name
        return name


# Longitud de `entity_type` (String(48)): el nombre de una tabla futura más
# largo no puede tumbar cada flush que la toque.
_ENTITY_TYPE_MAX = 48

# Tipos de actor que dicen POR DÓNDE entró algo aunque no haya persona detrás.
_CHANNEL_KINDS = ("cli", "celery")


# ---------------------------------------------------------------------------
# Armado de filas
# ---------------------------------------------------------------------------
def _actor_fields(ctx: AuditCtx, actor_id: int | None, *, own_actor: bool) -> tuple:
    """(actor_id, actor_kind, actor_label) de una fila.

    - Red ORM (`own_actor=False`): el cambio lo hizo quien opera -> el del contexto.
    - Espejo (`own_actor=True`): manda el `actor_id` del EVENTO. Con persona,
      `user` (o el canal, si entró por CLI/Celery). Sin persona (`actor_id`
      NULL) el evento lo hizo el sistema, aunque haya corrido dentro de la
      petición de alguien: NO se le acredita al usuario de la petición (el
      backfill de `tt20261007b` dice `system` para esos mismos eventos). Se
      conserva el canal si es `public`/`cli`/`celery`; si no, `system`.
    """
    if not own_actor:
        return ctx.actor_id, ctx.actor_kind, ctx.actor_label
    if actor_id is not None:
        kind = ctx.actor_kind if ctx.actor_kind in _CHANNEL_KINDS else "user"
        return actor_id, kind, ctx.actor_label if kind in _CHANNEL_KINDS else None
    kind = ctx.actor_kind if ctx.actor_kind in ("public", *_CHANNEL_KINDS) else "system"
    return None, kind, ctx.actor_label if kind in _CHANNEL_KINDS else None


def _base_row(ctx: AuditCtx, *, source: str, action: str, module: str,
              actor_id: int | None = None, own_actor: bool = False) -> dict[str, Any]:
    """Fila con TODAS las llaves (el executemany exige el mismo juego en cada una).

    `request_id`/`ip`/`user_agent`/`route` salen SIEMPRE del contexto: aunque
    un evento sin persona se acredite al sistema, la petición que lo disparó se
    sigue viendo en «otros registros de la misma operación».
    """
    actor_id, kind, label = _actor_fields(ctx, actor_id, own_actor=own_actor)
    return {
        "source": source,
        "action": action[:64],
        "module": module,
        "actor_id": actor_id,
        "actor_kind": kind,
        "actor_label": label,
        "entity_type": None,
        "entity_id": None,
        "process_id": None,
        "subject_label": None,
        "reason": None,
        "before": None,
        "after": None,
        "payload": None,
        "request_id": ctx.request_id,
        "ip": ctx.ip,
        "user_agent": ctx.user_agent,
        "route": ctx.route,
    }


def _reason_text(motivo) -> str | None:
    """`reason` de un payload: el texto tal cual; cualquier otra cosa, como JSON
    ya saneado (y enmascarado), nunca su `repr`."""
    if motivo is None:
        return None
    if isinstance(motivo, str):
        return AuditService.safe(motivo) or None
    try:
        return AuditService.safe(json.dumps(AuditService.safe(motivo), ensure_ascii=False))
    except Exception:
        return None


def _event_row(state, ctx: AuditCtx) -> dict[str, Any]:
    """Fila espejo de un `ProcessEvent` recién insertado."""
    d = state.dict
    event_type = str(d.get("event_type") or "")
    payload = d.get("payload")
    row = _base_row(ctx, source="process_event",
                    action=PROCESS_EVENT_PREFIX + event_type,
                    module=process_event_module(event_type),
                    actor_id=to_db_int(d.get("actor_id"), INT64), own_actor=True)
    row["process_id"] = to_db_int(d.get("process_id"), INT32)
    if isinstance(payload, dict):
        row["reason"] = _reason_text(payload.get("reason") or payload.get("note"))
    clean = AuditService.safe(payload) if payload is not None else None
    # La fase vive en su propia columna del evento (`PhaseService._log` no la
    # repite en el payload): sin esto la bitácora diría «Fase aprobada» sin decir
    # cuál. Se agrega solo si el payload no trae ya esa llave. (Las filas del
    # backfill de `tt20261007b` copiaron el payload tal cual, sin ella.)
    phase = to_db_int(d.get("phase_number"), INT32)
    if phase is not None:
        if clean is None:
            clean = {"phase_number": phase}
        elif isinstance(clean, dict) and "phase_number" not in clean:
            clean["phase_number"] = phase
    row["payload"] = clean if clean not in ({}, []) else None
    return row


def _column_keys(mapper) -> list[tuple[str, str]]:
    """[(llave del atributo, nombre de la columna)] de las propiedades de columna."""
    out = []
    for prop in mapper.column_attrs:
        out.append((prop.key, prop.columns[0].name))
    return out


def _pk_of(state, mapper) -> tuple[int | None, dict | None]:
    """(entity_id, pk compuesta). Lee del dict: en `after_flush` la llave de
    identidad de un objeto nuevo todavía no está asignada, pero sus columnas
    PK sí."""
    d = state.dict
    pk_vals = {}
    for col in mapper.primary_key:
        prop = mapper.get_property_by_column(col)
        pk_vals[col.name] = d.get(prop.key)
    if len(pk_vals) == 1:
        (val,) = pk_vals.values()
        ent = to_db_int(val, INT64)
        if ent is not None:
            return ent, None
    return None, AuditService.safe(pk_vals)


def _data_row(state, table: str, op: str, ctx: AuditCtx) -> dict[str, Any] | None:
    """Fila de la red ORM, o `None` si no hay diff que contar."""
    mapper = state.mapper
    d = state.dict
    before: dict | None = None
    after: dict | None = None

    if op == "insert":
        after = {}
        for key, name in _column_keys(mapper):
            value = d.get(key)
            if value is not None and name not in _INSERT_IGNORED:
                after[name] = _masked(name, value)
    elif op == "delete":
        before = {}
        for key, name in _column_keys(mapper):
            value = d.get(key)
            if value is not None:
                before[name] = _masked(name, value)
    else:
        before, after = {}, {}
        for key, name in _column_keys(mapper):
            if name in _DIFF_IGNORED:
                continue
            hist = state.attrs[key].history
            if not hist.has_changes():
                continue
            old = hist.deleted[0] if hist.deleted else None
            new = hist.added[0] if hist.added else None
            before[name] = _masked(name, old)
            after[name] = _masked(name, new)
        if not after and not before:
            return None

    entity_id, pk = _pk_of(state, mapper)
    row = _base_row(ctx, source="data", action=f"data.{op}",
                    module=TABLE_MODULES.get(table, "data"))
    row["entity_type"] = table[:_ENTITY_TYPE_MAX]
    row["entity_id"] = entity_id
    if table == _PROCESSES_TABLE:
        row["process_id"] = entity_id
    else:
        row["process_id"] = to_db_int(d.get("process_id"), INT32)
    row["before"] = before or None
    row["after"] = after or None
    if pk is not None:
        row["payload"] = {"pk": pk}
    return row


def _collect(session, flush_context) -> list[dict[str, Any]]:
    """Filas de bitácora de este flush (red primero, espejo después)."""
    new_states, dirty_states, deleted_states, event_states = [], [], [], []

    def _net_table(state) -> str | None:
        """Tabla de la red ORM, o `None` si este objeto no le toca."""
        table = _table_name(state.mapper)
        if not table or not table.startswith(_PREFIX) or table in NET_EXCLUDED_TABLES:
            return None
        return table

    # Bajas: las de `session.delete()` y además las que decidió el propio flush
    # (cascadas a hijos que no estaban cargados y huérfanos de `delete-orphan`),
    # que no aparecen en `session.deleted`. El UOW las registra con
    # `isdelete=True` en `flush_context.states`.
    # Cada objeto se clasifica dentro de su propio `try`: un objeto raro pierde
    # SU fila, no las de todo el flush (espejo incluido).
    deleting: dict[int, Any] = {}
    for obj in session.deleted:
        try:
            state = sa_inspect(obj)
            deleting[id(state)] = state
        except Exception:
            logger.exception("bitácora: no se pudo clasificar una baja; se omite")
    try:
        for state, (isdelete, listonly) in getattr(flush_context, "states", {}).items():
            if isdelete and not listonly:
                deleting.setdefault(id(state), state)
    except Exception:
        logger.exception("bitácora: no se pudieron leer las bajas en cascada del flush")
    for state in deleting.values():
        try:
            if (table := _net_table(state)) is not None:
                deleted_states.append((state, table))
        except Exception:
            logger.exception("bitácora: no se pudo clasificar una baja; se omite")

    for obj in session.new:
        try:
            state = sa_inspect(obj)
            if _table_name(state.mapper) == _EVENTS_TABLE:
                event_states.append(state)
            elif (table := _net_table(state)) is not None:
                new_states.append((state, table))
        except Exception:
            logger.exception("bitácora: no se pudo clasificar un alta; se omite")
    for obj in session.dirty:
        try:
            state = sa_inspect(obj)
            if id(state) in deleting:
                continue
            table = _net_table(state)
            if table is None or not session.is_modified(obj, include_collections=False):
                continue
            dirty_states.append((state, table))
        except Exception:
            logger.exception("bitácora: no se pudo clasificar un cambio; se omite")

    if not (new_states or dirty_states or deleted_states or event_states):
        return []

    ctx = current_audit_context()
    rows: list[dict[str, Any]] = []
    for bucket, op in ((new_states, "insert"), (dirty_states, "update"),
                       (deleted_states, "delete")):
        for state, table in bucket:
            try:
                row = _data_row(state, table, op, ctx)
            except Exception:
                logger.exception("bitácora: no se pudo armar la fila de %s (%s); se omite",
                                 table, op)
                continue
            if row is not None:
                rows.append(row)
    for state in event_states:
        try:
            rows.append(_event_row(state, ctx))
        except Exception:
            logger.exception("bitácora: no se pudo espejar un evento de proceso; se omite")
    return rows


def _after_flush(session, flush_context) -> None:
    """La escucha. Ver el docstring del módulo."""
    try:
        rows = _collect(session, flush_context)
    except Exception:
        logger.exception("bitácora: falló el armado de filas del flush; no se registra")
        return
    if not rows:
        return
    from itcj2.apps.titulatec.models.audit_log import TitulatecAuditLog
    # La tabla del modelo: sus JSON son `none_as_null=True`, así que un `None`
    # del executemany es NULL de SQL. Sin `id` (secuencia) ni `occurred_at`
    # (`NOW()` del servidor) en las filas.
    conn = session.connection(bind_arguments={"mapper": TitulatecAuditLog})
    conn.execute(insert(TitulatecAuditLog.__table__), rows)


def install() -> None:
    """Engancha `_after_flush` a `Session` (global). Idempotente."""
    if not event.contains(Session, "after_flush", _after_flush):
        event.listen(Session, "after_flush", _after_flush)


def is_installed() -> bool:
    return event.contains(Session, "after_flush", _after_flush)
