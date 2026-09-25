"""Conector del SII (spec 2026-09-25 §3.1).

Tres backends, elegidos por `TITULATEC_SII_BACKEND` en `get_sii_client()`:

- `odbc` → `OdbcSiiClient`: `pyodbc` + FreeTDS (Sybase ASE, TDS 5.0) o el
  driver que diga la cadena `TITULATEC_SII_ODBC`. `pyodbc` se importa
  PEREZOSAMENTE, en la primera conexión: el backend y la suite corren sin el
  driver instalado.
- `fake` → `FakeSiiClient`: un JSON local (`TITULATEC_SII_FAKE_FILE`) con
  filas por consulta y número de control, para dev, demo, E2E y pruebas.
- `disabled` (default) → `get_sii_client()` lanza `SiiUnavailable`.

La configuración se lee SOLO por los métodos estáticos de `SiiConfig` (los
tests los parchean; nadie más llama a `get_settings()` para esto).

Errores: `SiiUnavailable` (sin driver, sin conexión, timeout: reintentable) vs
`SiiQueryError` (SQL inválido). Su mensaje va SANEADO: nunca la cadena de
conexión ni la contraseña, y se re-lanzan `from None` para que el traceback no
arrastre la excepción cruda del driver.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Protocol, Sequence

from pydantic import SecretStr

from itcj2.apps.titulatec.services.sii.errors import SiiQueryError, SiiUnavailable

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[5]
MASK = "****"
_MAX_ERROR_LEN = 400
_SECRET_KEYS = ("pwd", "password")
_SECRET_KV_RE = re.compile(r"(?i)\b(PWD|PASSWORD)\s*=\s*(\{[^}]*\}|[^;\s'\")]*)")


def _resolve(path: str | Path) -> Path:
    p = Path(path)
    return p if p.is_absolute() else PROJECT_ROOT / p


class SiiConfig:
    """Único punto que lee los settings del SII (los tests parchean esto)."""

    @staticmethod
    def backend() -> str:
        from itcj2.config import get_settings
        return get_settings().TITULATEC_SII_BACKEND

    @staticmethod
    def odbc_connection_string() -> str:
        from itcj2.config import get_settings
        return get_settings().TITULATEC_SII_ODBC.get_secret_value()

    @staticmethod
    def fake_file() -> Path:
        from itcj2.config import get_settings
        return _resolve(get_settings().TITULATEC_SII_FAKE_FILE)

    @staticmethod
    def rules_dir() -> Path:
        from itcj2.config import get_settings
        return _resolve(get_settings().TITULATEC_SII_RULES_DIR)

    @staticmethod
    def connect_timeout() -> int:
        from itcj2.config import get_settings
        return get_settings().TITULATEC_SII_CONNECT_TIMEOUT_S

    @staticmethod
    def query_timeout() -> int:
        from itcj2.config import get_settings
        return get_settings().TITULATEC_SII_QUERY_TIMEOUT_S


class SiiClient(Protocol):
    """Lo que el motor de reglas necesita del SII."""

    def ping(self) -> None:
        """Lanza `SiiUnavailable` si no se puede hablar con el SII."""

    def query(self, sql: str, params: Sequence[Any], *,
              query_id: str | None = None) -> list[dict]:
        """Filas como dicts (columnas en minúsculas). `query_id` es el id del
        `[[query]]`; el ODBC lo ignora, el falso lo usa como llave."""

    def close(self) -> None:
        ...


class _ContextMixin:
    def __enter__(self):
        return self

    def __exit__(self, *exc) -> bool:
        self.close()
        return False


# ---------------------------------------------------------------------------
# ODBC
# ---------------------------------------------------------------------------
def _secret_values(conn: str) -> list[str]:
    out = []
    for part in conn.split(";"):
        key, sep, value = part.partition("=")
        if sep and key.strip().lower() in _SECRET_KEYS and value.strip():
            value = value.strip()
            out.append(value)
            if value.startswith("{") and value.endswith("}") and len(value) > 2:
                out.append(value[1:-1])
    return sorted(out, key=len, reverse=True)


def _sanitize(text: str, conn: str) -> str:
    """Quita la cadena de conexión, los `PWD=…` y el valor suelto de la
    contraseña de un mensaje del driver."""
    out = text
    if conn:
        out = out.replace(conn, "<cadena ODBC>")
    for secret in _secret_values(conn):
        out = out.replace(secret, MASK)
    out = _SECRET_KV_RE.sub(lambda m: f"{m.group(1)}={MASK}", out)
    if len(out) > _MAX_ERROR_LEN:
        out = out[:_MAX_ERROR_LEN] + "…"
    return out


def _describe(prefix: str, exc: BaseException, conn: str) -> str:
    # pyodbc: args = (sqlstate, mensaje). Otros: lo que traigan.
    raw = " ".join(str(a) for a in exc.args) if exc.args else ""
    detail = _sanitize(raw, conn).strip()
    return f"{prefix} ({type(exc).__name__}{': ' + detail if detail else ''})."


def _clean(value: Any) -> Any:
    # CHAR de Sybase llega con relleno a la derecha ('EGRESADO   ').
    return value.rstrip() if isinstance(value, str) else value


class OdbcSiiClient(_ContextMixin):
    """Cliente ODBC de solo lectura. Una conexión perezosa y reutilizada;
    tras un `SiiUnavailable` se descarta para que el siguiente intento
    reconecte."""

    def __init__(self, connection_string: str, *, connect_timeout: int, query_timeout: int):
        self._conn_str = SecretStr(connection_string)
        self.connect_timeout = int(connect_timeout)
        self.query_timeout = int(query_timeout)
        self._conn = None

    def __repr__(self) -> str:
        return (f"OdbcSiiClient(connect_timeout={self.connect_timeout}, "
                f"query_timeout={self.query_timeout})")

    @staticmethod
    def _driver():
        try:
            import pyodbc  # noqa: PLC0415 — perezoso a propósito
        except ImportError:
            raise SiiUnavailable(
                "El driver pyodbc no está instalado en este proceso (imagen sin "
                "FreeTDS/pyodbc)."
            ) from None
        return pyodbc

    def _connection(self):
        if self._conn is None:
            pyodbc = self._driver()
            conn_str = self._conn_str.get_secret_value()
            try:
                conn = pyodbc.connect(conn_str, timeout=self.connect_timeout,
                                      autocommit=True, readonly=True)
                conn.timeout = self.query_timeout
            except Exception as exc:  # noqa: BLE001 — todo error de conexión
                msg = _describe("No se pudo conectar al SII", exc, conn_str)
                logger.warning("SII: %s", msg)
                raise SiiUnavailable(msg) from None
            self._conn = conn
        return self._conn

    def _discard(self) -> None:
        conn, self._conn = self._conn, None
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass

    def ping(self) -> None:
        self.query("SELECT 1", [])

    def query(self, sql: str, params: Sequence[Any], *,
              query_id: str | None = None) -> list[dict]:
        conn = self._connection()
        pyodbc = self._driver()
        unavailable = tuple(
            cls for cls in (getattr(pyodbc, "OperationalError", None),
                            getattr(pyodbc, "InterfaceError", None))
            if isinstance(cls, type)
        )
        cursor = None
        try:
            cursor = conn.cursor()
            cursor.execute(sql, *params)
            cols = [str(d[0]).lower() for d in (cursor.description or [])]
            return [{c: _clean(v) for c, v in zip(cols, row)} for row in cursor.fetchall()]
        except Exception as exc:  # noqa: BLE001 — se clasifica y se sanea
            conn_str = self._conn_str.get_secret_value()
            where = f" '{query_id}'" if query_id else ""
            if unavailable and isinstance(exc, unavailable):
                self._discard()
                msg = _describe(f"El SII no respondió a la consulta{where}", exc, conn_str)
                logger.warning("SII: %s", msg)
                raise SiiUnavailable(msg) from None
            msg = _describe(f"Consulta{where} inválida en el SII", exc, conn_str)
            logger.warning("SII: %s", msg)
            raise SiiQueryError(msg) from None
        finally:
            if cursor is not None:
                try:
                    cursor.close()
                except Exception:  # noqa: BLE001
                    pass

    def close(self) -> None:
        self._discard()


# ---------------------------------------------------------------------------
# SII falso
# ---------------------------------------------------------------------------
class FakeSiiClient(_ContextMixin):
    """SII de mentira sobre un JSON::

        {"queries": {"<id de [[query]]>": {"<valor del parámetro>": [ {fila}, … ],
                                           "<otro>": {"error": "unavailable"|"query"}}}}

    Con varios parámetros la llave es `valor1|valor2`. Consulta o número de
    control que no aparece → 0 filas. Se lee una vez, en el primer uso.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._data: dict | None = None

    def __repr__(self) -> str:
        return f"FakeSiiClient({self.path.name!r})"

    def _load(self) -> dict:
        if self._data is None:
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
            except FileNotFoundError:
                raise SiiUnavailable(f"No existe el archivo del SII falso: {self.path}") from None
            except (OSError, ValueError) as exc:
                raise SiiUnavailable(
                    f"No se pudo leer el archivo del SII falso ({type(exc).__name__})."
                ) from None
            queries = raw.get("queries") if isinstance(raw, dict) else None
            if not isinstance(queries, dict):
                raise SiiUnavailable("El archivo del SII falso debe tener un objeto `queries`.")
            self._data = queries
        return self._data

    def ping(self) -> None:
        self._load()

    def query(self, sql: str, params: Sequence[Any], *,
              query_id: str | None = None) -> list[dict]:
        if not query_id:
            raise SiiQueryError("El SII falso necesita el id de la consulta (query_id).")
        by_key = self._load().get(query_id)
        if not isinstance(by_key, dict):
            return []
        entry = by_key.get("|".join(str(p) for p in params), [])
        if isinstance(entry, dict):
            if entry.get("error") == "unavailable":
                raise SiiUnavailable("SII falso: no disponible (simulado).")
            raise SiiQueryError("SII falso: consulta inválida (simulada).")
        return [{str(k).lower(): v for k, v in dict(r).items()} for r in entry]

    def close(self) -> None:
        return None


def get_sii_client() -> SiiClient:
    """El cliente del backend configurado. `disabled` lanza `SiiUnavailable`.
    No conecta: la primera consulta (o `ping()`) lo hace."""
    backend = SiiConfig.backend()
    if backend == "fake":
        return FakeSiiClient(SiiConfig.fake_file())
    if backend == "odbc":
        conn_str = SiiConfig.odbc_connection_string()
        if not conn_str or not conn_str.strip():
            raise SiiUnavailable("TITULATEC_SII_ODBC está vacío: no hay cadena de conexión al SII.")
        return OdbcSiiClient(conn_str, connect_timeout=SiiConfig.connect_timeout(),
                             query_timeout=SiiConfig.query_timeout())
    raise SiiUnavailable(
        "La consulta al SII está deshabilitada (TITULATEC_SII_BACKEND=disabled)."
    )
