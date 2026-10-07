"""Bitácora de TitulaTec: registrar «qué, quién y por qué» (spec 2026-10-07 §4.2).

`AuditService.record` es la llamada explícita, con semántica de negocio
(`cohort.window_changed`, `officer.account_reactivated`…). Va en el SERVICE,
justo antes de su `db.commit()`, para cubrir todas las rutas que lo llaman.

Reglas (D8/D9):
- `record` solo hace `db.add(...)`: **nunca** `flush` ni `commit`. La fila viaja
  en la transacción del cambio; si la operación revierte, su rastro también.
- Nunca secretos: toda clave que contenga password/nip/token/secret/hash sale
  como "***" (`audit_actions.SENSITIVE_KEY_PARTS`), en `payload`, `before`,
  `after` y en lo que arme `snapshot`. El texto libre de `reason`/`subject` no se
  puede revisar: no pongas ahí un NIP ni una liga firmada.
- Armar la fila nunca truena por los DATOS (`safe` sanea todo a JSON). Lo único
  que truena es un código fuera de `AUDIT_ACTIONS`, y solo en pruebas/dev.

Quién lo hizo sale del contexto (`audit_context.current_audit_context`): la
petición HTTP en curso, el comando de consola o la tarea de Celery. Un
`actor_id` explícito gana.

`process.*` (espejo de `ProcessEvent`) y `data.*` (red ORM) NO pasan por aquí:
los escribe `audit_listeners` en el `after_flush`, reutilizando `safe`.
"""
from __future__ import annotations

import logging
import math
import sys
import uuid
from collections.abc import Iterable, Mapping
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from enum import Enum
from typing import Any

from itcj2.apps.titulatec.services.audit_actions import AUDIT_ACTIONS, is_sensitive_key
from itcj2.apps.titulatec.services.audit_context import current_audit_context

logger = logging.getLogger(__name__)

MASK = "***"

# Topes del saneo: una fila de bitácora nunca puede volverse enorme ni recursiva.
_STR_MAX = 2000
_ITEMS_MAX = 500
_DEPTH_MAX = 8

# Longitudes de las columnas String de `titulatec_audit_log`.
_ACTION_MAX = 64
_ENTITY_TYPE_MAX = 48
_SUBJECT_MAX = 160
_LABEL_MAX = 120
_REASON_MAX = 2000

# Entornos donde un código fuera del vocabulario debe tronar en voz alta.
_STRICT_ENVS = frozenset({"development", "testing", "test"})


def _strict() -> bool:
    """¿Una acción desconocida es un error (pruebas/dev) o solo un aviso (prod)?"""
    if "pytest" in sys.modules:
        return True
    try:
        from itcj2.config import get_settings
        return (get_settings().FLASK_ENV or "").lower() in _STRICT_ENVS
    except Exception:
        return False


def _clean_str(value: str, limit: int = _STR_MAX) -> str:
    """Sin NUL (PostgreSQL no lo acepta), sin sustitutos sueltos (no se pueden
    codificar en UTF-8) y recortada."""
    s = value.replace("\x00", "")
    if not s.isascii():
        s = s.encode("utf-8", "replace").decode("utf-8")
    return s[:limit]


def _clip(value, limit: int) -> str | None:
    """Para columnas String: texto limpio y recortado, o `None` si queda vacío."""
    if value is None:
        return None
    try:
        s = _clean_str(str(value), limit).strip()
    except Exception:
        return None
    return s or None


def _to_int(value) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe(value: Any, depth: int = 0) -> Any:
    """Saneo recursivo; ver `AuditService.safe`."""
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, str):
        return _clean_str(value)
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, timedelta):
        return value.total_seconds()
    if isinstance(value, Enum):
        return _safe(value.value, depth + 1)
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return f"<{len(value)} bytes>"
    if depth >= _DEPTH_MAX:
        return _clean_str(_text_of(value))
    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        for i, (k, v) in enumerate(value.items()):
            if i >= _ITEMS_MAX:
                out["…"] = f"{len(value) - _ITEMS_MAX} más"
                break
            key = _clean_str(str(k), 200)
            out[key] = _masked(key, v, depth + 1)
        return out
    if isinstance(value, (list, tuple, set, frozenset)):
        seq = list(value)
        out_list = [_safe(v, depth + 1) for v in seq[:_ITEMS_MAX]]
        if len(seq) > _ITEMS_MAX:
            out_list.append(f"… {len(seq) - _ITEMS_MAX} más")
        return out_list
    return _clean_str(_text_of(value))


def _text_of(value: Any) -> str:
    """`str(value)` que nunca truena."""
    try:
        return str(value)
    except Exception:
        try:
            return repr(value)
        except Exception:
            return f"<{type(value).__name__} no serializable>"


def _masked(key, value: Any, depth: int = 0) -> Any:
    """El valor de un campo con nombre: "***" si el nombre es sensible (D9) y
    hay algo que ocultar; si no, saneado."""
    if is_sensitive_key(key):
        return None if value is None else MASK
    return _safe(value, depth)


def _json_or_none(value: Any):
    """Saneado para una columna JSON; vacío -> `None` (NULL de SQL)."""
    if value is None:
        return None
    out = AuditService.safe(value)
    if out in ({}, [], ""):
        return None
    return out


class AuditService:
    """Registro explícito de la bitácora y utilidades de saneo."""

    @staticmethod
    def safe(value: Any) -> Any:
        """Copia JSON-segura de `value`, con la máscara D9 aplicada.

        Dicts: llaves a texto y valores de llaves sensibles como "***" (en
        cualquier nivel). `Decimal` -> texto, fechas -> ISO, conjuntos y tuplas
        -> lista, bytes -> «<N bytes>», cualquier otro objeto -> su texto.
        Cadenas sin NUL y a 2000 caracteres; hasta 500 elementos y 8 niveles.
        Nunca truena.
        """
        try:
            return _safe(value)
        except Exception:
            return _clean_str(_text_of(value))

    @staticmethod
    def changes(before: dict, after: dict) -> tuple[dict, dict]:
        """Solo las llaves que difieren -> `(antes, después)`.

        Una llave que solo está de un lado vale `None` del otro. No sanea: lo
        hace `record`.
        """
        before = before or {}
        after = after or {}
        keys = list(before) + [k for k in after if k not in before]
        b: dict = {}
        a: dict = {}
        for k in keys:
            old, new = before.get(k), after.get(k)
            try:
                same = bool(old == new)
            except Exception:
                same = False
            if not same:
                b[k] = old
                a[k] = new
        return b, a

    @staticmethod
    def snapshot(obj, fields: Iterable[str]) -> dict:
        """`{campo: valor}` JSON-seguro y enmascarado de `obj` (atributo que no
        existe -> `None`). Ojo: leer una relación o un atributo expirado puede
        consultar la BD; eso es del llamador."""
        out: dict = {}
        for f in fields:
            try:
                value = getattr(obj, f, None)
            except Exception:
                value = None
            out[f] = _masked(f, value)
        return out

    @staticmethod
    def record(db, action: str, *, entity_type=None, entity_id=None, process_id=None,
               subject=None, reason=None, before=None, after=None, payload=None,
               actor_id=None) -> None:
        """Agrega UNA fila `source='action'` a la sesión. Sin flush ni commit.

        `subject` va a `subject_label` («20111234 · Juan Pérez», solo si el
        llamador ya lo tiene sin consultar). `before`/`after` = solo lo que
        cambió (ver `changes`/`snapshot`). `actor_id` explícito gana al del
        contexto; el tipo de actor sigue diciendo por dónde entró (`cli`/`celery`)
        o pasa a `user`.
        """
        from itcj2.apps.titulatec.models.audit_log import TitulatecAuditLog

        if not isinstance(action, str) or action not in AUDIT_ACTIONS:
            if _strict():
                raise ValueError(
                    f"acción de bitácora desconocida: {action!r}; regístrala en "
                    "services/audit_actions.py::AUDIT_ACTIONS")
            logger.warning("bitácora: acción desconocida %r; se registra en 'system'", action)
            module = "system"
        else:
            module = AUDIT_ACTIONS[action][0]

        ctx = current_audit_context()
        explicit_actor = _to_int(actor_id)
        if explicit_actor is not None:
            kind = ctx.actor_kind if ctx.actor_kind in ("cli", "celery") else "user"
            label = ctx.actor_label if kind in ("cli", "celery") else None
        else:
            explicit_actor = ctx.actor_id
            kind, label = ctx.actor_kind, ctx.actor_label

        cols: dict[str, Any] = dict(
            source="action",
            action=_clip(action, _ACTION_MAX) or "system.unknown",
            module=module,
            actor_id=explicit_actor,
            actor_kind=kind,
            actor_label=_clip(label, _LABEL_MAX),
            entity_type=_clip(entity_type, _ENTITY_TYPE_MAX),
            entity_id=_to_int(entity_id),
            process_id=_to_int(process_id),
            subject_label=_clip(subject, _SUBJECT_MAX),
            reason=_clip(reason, _REASON_MAX),
            request_id=ctx.request_id,
            ip=ctx.ip,
            user_agent=ctx.user_agent,
            route=ctx.route,
        )
        # Las JSON solo si traen algo: asignar `None` a una columna JSON guarda el
        # JSON `null`, no el NULL de SQL.
        for name, value in (("before", before), ("after", after), ("payload", payload)):
            clean = _json_or_none(value)
            if clean is not None:
                cols[name] = clean
        db.add(TitulatecAuditLog(**cols))
