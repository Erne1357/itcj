"""Motor declarativo de reglas de elegibilidad del SII (spec 2026-09-25 §3.2).

Las reglas NO son código: `rules.toml` declara consultas (`[[query]]`, un
`.sql` de solo lectura cada una), reglas (`[[rule]]`, un criterio de un
vocabulario cerrado + un mensaje con placeholders de columnas), y opcionalmente
de dónde sale el NIP (`[credential]`), la identidad (`[identity]`) y los hechos
que se guardan para auditoría (`[facts]`). Formato completo:
`itcj2/apps/titulatec/docs/sii_rules_format.md`.

Garantías que el resto del sistema da por hechas:

- `evaluate()` NUNCA lanza por el SII ni por una regla mal escrita: devuelve
  `Verdict(status="error", …)`. Solo `apt` aprueba, y solo sale cuando TODAS
  las reglas cumplen sobre datos que el SII sí devolvió (fail-closed: una
  comparación sin filas no cumple; NULL no cumple ninguna comparación).
- Cada `[[query]]` se ejecuta a lo más UNA vez por evaluación y la comparten
  sus reglas; parámetros siempre enlazados (`?`), nunca interpolados.
- La consulta de `[credential]` no corre al evaluar y no puede alimentar
  reglas, hechos ni identidad (el validador lo impide). El NIP solo sale de
  `fetch_credential()`, envuelto en `Secret` (repr/str `****`).
"""
from __future__ import annotations

import logging
import re
import tomllib
from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from itcj2.apps.titulatec.services.sii.errors import SiiError, SiiRulesError

logger = logging.getLogger(__name__)

RULES_FILE = "rules.toml"
ALLOWED_PARAMS = frozenset({"control_number", "curp"})
DEFAULT_OK_MESSAGE = "Cumple."
MASK = "****"
VERSION_MAX_LEN = 40

_PRESENCE = frozenset({"exists", "not_exists"})
_BINARY = frozenset({"equals", "not_equals", "gte", "lte"})
_SET = frozenset({"in", "not_in"})
_UNARY = frozenset({"truthy", "falsy"})
KINDS = _PRESENCE | _BINARY | _SET | _UNARY
MODES = frozenset({"all", "any"})

_ID_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_PLACEHOLDER_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
_FALSE_WORDS = frozenset({"", "0", "n", "no", "f", "false", "falso"})

# Heurística del validador de SQL (documentada en sii_rules_format.md). La
# defensa de verdad es el usuario de SOLO LECTURA del lado del SII (spec §5):
# esto atrapa errores y descuidos, no a un atacante con acceso a la carpeta.
# T-SQL (Sybase) NO necesita `;` entre sentencias —`SELECT 1 DELETE FROM x`
# son dos—, así que la lista de verbos prohibidos es lo que cierra ese hueco.
_FORBIDDEN_WORDS = frozenset({
    "INSERT", "UPDATE", "DELETE", "MERGE", "UPSERT", "TRUNCATE", "DROP", "ALTER",
    "CREATE", "GRANT", "REVOKE", "EXEC", "EXECUTE", "CALL", "INTO", "SET",
    "DECLARE", "USE", "DUMP", "LOAD", "SHUTDOWN", "KILL", "RECONFIGURE",
    "WAITFOR", "BEGIN", "COMMIT", "ROLLBACK", "SAVE", "DBCC", "DISK",
    "CHECKPOINT", "WRITETEXT", "READTEXT", "BULK", "PREPARE", "DEALLOCATE",
    "LOCK", "UNLOCK", "RENAME",
})

_TOP_KEYS = {"version", "query", "rule", "credential", "identity", "facts"}
_QUERY_KEYS = {"id", "file", "params"}
_RULE_KEYS = {"id", "query", "criterion", "message", "ok_message"}
_CRIT_KEYS = {"kind", "column", "value", "value_column", "mode"}


# ---------------------------------------------------------------------------
# Tipos públicos
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class RuleResult:
    rule: str
    ok: bool
    message: str


@dataclass(frozen=True)
class Verdict:
    """Resultado de una evaluación. `status`: `apt` | `not_apt` | `error`.

    `facts` e `identity` son JSON-serializables (se persisten tal cual).
    `warnings` junta lo que solo se detecta al ejecutar (p. ej. un
    placeholder del mensaje que la consulta no devuelve); no cambia el
    estado.
    """

    status: str
    results: list[RuleResult] = field(default_factory=list)
    facts: dict = field(default_factory=dict)
    identity: dict = field(default_factory=dict)
    rules_version: str = ""
    error: str | None = None
    warnings: list[str] = field(default_factory=list)

    def results_as_dicts(self) -> list[dict]:
        """`[{rule, ok, message}]`, la forma de la columna JSON `results`."""
        return [{"rule": r.rule, "ok": r.ok, "message": r.message} for r in self.results]


class Secret:
    """Un valor sensible (el NIP del SII). `repr`/`str`/`format` → `****`.

    Solo `reveal()` entrega el valor, y solo debe llamarse justo antes de
    hashearlo. No se deja serializar (pickle/celery/copy) para que no viaje
    por accidente fuera del proceso.
    """

    __slots__ = ("_value",)

    def __init__(self, value: str):
        self._value = value

    def reveal(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return MASK

    __str__ = __repr__

    def __format__(self, spec: str) -> str:
        return MASK

    def __reduce_ex__(self, protocol):
        raise TypeError("Secret no se serializa.")


# ---------------------------------------------------------------------------
# Estructuras internas (ya validadas)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class _Query:
    id: str
    file: str
    params: tuple[str, ...]
    sql: str


@dataclass(frozen=True)
class _Rule:
    id: str
    query: str
    kind: str
    column: str | None
    value: Any
    value_column: str | None
    mode: str
    message: str
    ok_message: str | None


@dataclass(frozen=True)
class _Projection:
    """`[credential]`, `[identity]` o `[facts]`: una consulta + columnas."""

    query: str
    columns: dict[str, str]  # clave de salida → columna (facts: columna → columna)


class _EvalError(Exception):
    """Regla que no se puede evaluar con lo que devolvió el SII (columna que
    no viene, tipos no comparables, parámetro faltante). Termina en `error`."""


# ---------------------------------------------------------------------------
# Validación de SQL
# ---------------------------------------------------------------------------
def _strip_sql(sql: str) -> str:
    """Quita comentarios (`--`, `/* */`) y el CONTENIDO de literales e
    identificadores entre comillas (`'…'`, `"…"`, `[…]`), para que ni un
    `;` ni un `UPDATE` ni un `?` dentro de un texto cuenten. Lanza
    ValueError si algo queda sin cerrar."""
    out: list[str] = []
    i, n = 0, len(sql)
    while i < n:
        c = sql[i]
        if c == "-" and sql.startswith("--", i):
            j = sql.find("\n", i)
            i = n if j == -1 else j
            out.append(" ")
        elif c == "/" and sql.startswith("/*", i):
            j = sql.find("*/", i + 2)
            if j == -1:
                raise ValueError("comentario /* sin cerrar")
            i = j + 2
            out.append(" ")
        elif c in ("'", '"', "["):
            close = "]" if c == "[" else c
            j = i + 1
            while True:
                k = sql.find(close, j)
                if k == -1:
                    raise ValueError(f"literal {c}… sin cerrar")
                if close != "]" and sql.startswith(close * 2, k):
                    j = k + 2  # comilla escapada ('' o "")
                    continue
                break
            i = k + 1
            out.append(" '' ")
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _sql_errors(sql: str, n_params: int) -> list[str]:
    try:
        clean = _strip_sql(sql)
    except ValueError as exc:
        return [str(exc)]
    body = clean.strip()
    if body.endswith(";"):
        body = body[:-1].rstrip()
    if not body:
        return ["está vacío"]
    errors: list[str] = []
    if ";" in body:
        errors.append("tiene más de una sentencia (`;` intermedio)")
    first = re.match(r"[A-Za-z_]+", body)
    if not first or first.group(0).upper() not in ("SELECT", "WITH"):
        errors.append("debe empezar con SELECT o WITH")
    bad = sorted({w.upper() for w in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", body)}
                 & _FORBIDDEN_WORDS)
    if bad:
        errors.append("contiene palabras no permitidas en una consulta de solo "
                      "lectura: " + ", ".join(bad))
    marks = body.count("?")
    if marks != n_params:
        errors.append(f"tiene {marks} marcador(es) `?` pero declara {n_params} parámetro(s)")
    return errors


# ---------------------------------------------------------------------------
# Comparaciones
# ---------------------------------------------------------------------------
def _num(v: Any) -> Decimal | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, Decimal)):
        d = Decimal(v)
    elif isinstance(v, float):
        d = Decimal(str(v))
    elif isinstance(v, str):
        try:
            d = Decimal(v.strip())
        except InvalidOperation:
            return None
    else:
        return None
    return d if d.is_finite() else None


def _text(v: Any) -> str:
    return str(v).strip().casefold()


def _truthy(v: Any) -> bool:
    if v is None:
        return False
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float, Decimal)):
        return v != 0
    if isinstance(v, str):
        return _text(v) not in _FALSE_WORDS
    return bool(v)


def _eq(a: Any, b: Any) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return _truthy(a) == _truthy(b)
    na, nb = _num(a), _num(b)
    if na is not None and nb is not None:
        return na == nb
    return _text(a) == _text(b)


def _cmp(a: Any, b: Any) -> int:
    na, nb = _num(a), _num(b)
    if na is not None and nb is not None:
        return (na > nb) - (na < nb)
    if isinstance(a, date) and isinstance(b, date):
        if isinstance(a, datetime) != isinstance(b, datetime):
            a = a.date() if isinstance(a, datetime) else a
            b = b.date() if isinstance(b, datetime) else b
        return (a > b) - (a < b)
    if isinstance(a, str) and isinstance(b, str):
        ta, tb = _text(a), _text(b)
        return (ta > tb) - (ta < tb)
    raise _EvalError(f"no se puede comparar {type(a).__name__} con {type(b).__name__}")


def _jsonable(v: Any) -> Any:
    if v is None or isinstance(v, (bool, int, str)):
        return v
    if isinstance(v, float):
        return v
    if isinstance(v, Decimal):
        if not v.is_finite():
            return str(v)
        return int(v) if v == v.to_integral_value() else float(v)
    if isinstance(v, (datetime, date, time)):
        return v.isoformat()
    return str(v)


def _display(v: Any) -> str:
    if v is None:
        return "—"
    j = _jsonable(v)
    return str(j)


def _norm_rows(rows) -> list[dict]:
    """Columnas en minúsculas: el SII puede devolver `NoControl` o `NOCONTROL`
    según el driver; las reglas se escriben en minúsculas."""
    return [{str(k).lower(): val for k, val in dict(r).items()} for r in rows]


# ---------------------------------------------------------------------------
# RuleSet
# ---------------------------------------------------------------------------
class RuleSet:
    """Reglas cargadas de una carpeta con `rules.toml` + `queries/*.sql`."""

    def __init__(self, path: Path, data: dict):
        self.path = path
        self._data = data
        self._errors: list[str] = []
        self._queries: dict[str, _Query] = {}
        self._rules: list[_Rule] = []
        self._credential: _Projection | None = None
        self._identity: _Projection | None = None
        self._facts: _Projection | None = None
        raw_version = data.get("version")
        self.version: str = raw_version.strip() if isinstance(raw_version, str) else ""
        self._compile()

    def __repr__(self) -> str:
        return (f"RuleSet(version={self.version!r}, queries={len(self._queries)}, "
                f"rules={len(self._rules)}, errors={len(self._errors)})")

    # -- carga -------------------------------------------------------------
    @classmethod
    def load(cls, path: str | Path) -> "RuleSet":
        """Lee `<path>/rules.toml`. Lanza `SiiRulesError` si no existe o no es
        TOML; los errores de CONTENIDO los reporta `validate()`."""
        base = Path(path)
        rules_file = base / RULES_FILE
        if not rules_file.is_file():
            raise SiiRulesError(f"No existe {rules_file}.")
        try:
            data = tomllib.loads(rules_file.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as exc:
            raise SiiRulesError(f"{RULES_FILE} no es TOML válido: {exc}") from None
        except (OSError, UnicodeDecodeError) as exc:
            raise SiiRulesError(f"No se pudo leer {rules_file}: {type(exc).__name__}") from None
        return cls(base, data)

    def validate(self) -> list[str]:
        """Errores legibles; `[]` = válido. Un RuleSet con errores nunca
        aprueba: `evaluate()` devuelve `error` sin consultar al SII."""
        return list(self._errors)

    @property
    def queries(self) -> list[str]:
        return list(self._queries)

    @property
    def rules(self) -> list[str]:
        return [r.id for r in self._rules]

    @property
    def has_credential(self) -> bool:
        return self._credential is not None

    # -- compilación / validación -----------------------------------------
    def _compile(self) -> None:  # noqa: C901 — un solo recorrido, lineal
        err = self._errors.append
        data = self._data

        for key in sorted(set(data) - _TOP_KEYS):
            err(f"Clave desconocida en rules.toml: '{key}'.")
        if not self.version:
            err("Falta `version` (texto no vacío).")
        elif len(self.version) > VERSION_MAX_LEN:
            err(f"`version` excede {VERSION_MAX_LEN} caracteres.")

        # [[query]]
        raw_queries = data.get("query", [])
        if not isinstance(raw_queries, list) or not raw_queries:
            err("Debe haber al menos una consulta `[[query]]`.")
            raw_queries = []
        base = self.path.resolve()
        for i, q in enumerate(raw_queries, 1):
            where = f"[[query]] #{i}"
            if not isinstance(q, dict):
                err(f"{where}: debe ser una tabla.")
                continue
            for key in sorted(set(q) - _QUERY_KEYS):
                err(f"{where}: clave desconocida '{key}'.")
            qid = q.get("id")
            if not isinstance(qid, str) or not _ID_RE.match(qid):
                err(f"{where}: `id` inválido (letras, dígitos y _).")
                continue
            where = f"Consulta '{qid}'"
            if qid in self._queries:
                err(f"{where}: id duplicado.")
                continue
            params = q.get("params")
            if (not isinstance(params, list) or not params
                    or not all(isinstance(p, str) for p in params)):
                err(f"{where}: `params` debe ser una lista no vacía de nombres.")
                params = []
            bad = [p for p in params if p not in ALLOWED_PARAMS]
            if bad:
                err(f"{where}: parámetro(s) no permitido(s) {bad}; solo "
                    f"{sorted(ALLOWED_PARAMS)}.")
            file = q.get("file")
            sql = None
            if not isinstance(file, str) or not file.endswith(".sql"):
                err(f"{where}: `file` debe ser la ruta relativa de un .sql.")
            else:
                target = (self.path / file).resolve()
                if not target.is_relative_to(base):
                    err(f"{where}: `{file}` queda fuera de la carpeta de reglas.")
                elif not target.is_file():
                    err(f"{where}: no existe el archivo `{file}`.")
                else:
                    try:
                        sql = target.read_text(encoding="utf-8")
                    except (OSError, UnicodeDecodeError) as exc:
                        err(f"{where}: no se pudo leer `{file}` ({type(exc).__name__}).")
                    else:
                        for e in _sql_errors(sql, len(params)):
                            err(f"{where} (`{file}`): {e}.")
            self._queries[qid] = _Query(qid, str(file), tuple(params), sql or "")

        # [[rule]]
        raw_rules = data.get("rule", [])
        if not isinstance(raw_rules, list) or not raw_rules:
            err("Debe haber al menos una regla `[[rule]]`.")
            raw_rules = []
        seen: set[str] = set()
        for i, r in enumerate(raw_rules, 1):
            rule = self._compile_rule(i, r, seen)
            if rule is not None:
                self._rules.append(rule)

        # [credential] / [identity] / [facts]
        self._credential = self._compile_projection("credential", mapping=False, single=True)
        self._identity = self._compile_projection("identity", mapping=True)
        self._facts = self._compile_projection("facts", mapping=False)

        cred = self._credential
        if cred is not None:
            cred_col = next(iter(cred.columns.values()))
            users = [f"la regla '{r.id}'" for r in self._rules if r.query == cred.query]
            for name, proj in (("[identity]", self._identity), ("[facts]", self._facts)):
                if proj is None:
                    continue
                if proj.query == cred.query:
                    users.append(name)
                if cred_col in proj.columns.values():
                    err(f"{name} no puede incluir la columna de la credencial '{cred_col}'.")
            if users:
                err(f"La consulta de la credencial '{cred.query}' no puede alimentar "
                    f"reglas, identidad ni hechos (la usa {', '.join(users)}); dale una "
                    "consulta propia.")

    def _compile_rule(self, i: int, r: Any, seen: set[str]) -> _Rule | None:
        err = self._errors.append
        where = f"[[rule]] #{i}"
        if not isinstance(r, dict):
            err(f"{where}: debe ser una tabla.")
            return None
        rid = r.get("id")
        if isinstance(rid, str) and _ID_RE.match(rid):
            where = f"Regla '{rid}'"
            if rid in seen:
                err(f"{where}: id duplicado.")
            seen.add(rid)
        else:
            err(f"{where}: `id` inválido (letras, dígitos y _).")
        ok = True
        for key in sorted(set(r) - _RULE_KEYS):
            err(f"{where}: clave desconocida '{key}'.")
            ok = False
        query = r.get("query")
        if query not in self._queries:
            err(f"{where}: la consulta '{query}' no está declarada en [[query]].")
            ok = False
        message = r.get("message")
        if not isinstance(message, str) or not message.strip():
            err(f"{where}: falta `message`.")
            ok = False
        ok_message = r.get("ok_message")
        if ok_message is not None and not isinstance(ok_message, str):
            err(f"{where}: `ok_message` debe ser texto.")
            ok = False

        crit = r.get("criterion")
        if not isinstance(crit, dict):
            err(f"{where}: falta `criterion` (tabla con `kind`).")
            return None
        for key in sorted(set(crit) - _CRIT_KEYS):
            err(f"{where}: clave desconocida en criterion '{key}'.")
            ok = False
        kind = crit.get("kind")
        if kind not in KINDS:
            err(f"{where}: kind '{kind}' desconocido; válidos: {sorted(KINDS)}.")
            return None
        column = crit.get("column")
        value = crit.get("value")
        value_column = crit.get("value_column")
        mode = crit.get("mode", "all")

        def bad(msg: str) -> None:
            nonlocal ok
            err(f"{where}: {msg}")
            ok = False

        if kind in _PRESENCE:
            extra = [k for k in ("column", "value", "value_column", "mode") if k in crit]
            if extra:
                bad(f"`{kind}` no admite {extra}.")
        else:
            if not isinstance(column, str) or not _ID_RE.match(column):
                bad(f"`{kind}` necesita `column` (nombre de columna).")
            if mode not in MODES:
                bad(f"mode '{mode}' inválido; válidos: all, any.")
            if kind in _BINARY:
                if ("value" in crit) == ("value_column" in crit):
                    bad(f"`{kind}` necesita exactamente uno de `value` o `value_column`.")
                elif "value" in crit and isinstance(value, (list, dict)):
                    bad("`value` debe ser un valor simple (texto, número, fecha o booleano).")
                elif "value_column" in crit and (
                        not isinstance(value_column, str) or not _ID_RE.match(value_column)):
                    bad("`value_column` debe ser un nombre de columna.")
            elif kind in _SET:
                if "value_column" in crit:
                    bad(f"`{kind}` no admite `value_column`.")
                if (not isinstance(value, list) or not value
                        or any(isinstance(v, (list, dict)) for v in value)):
                    bad(f"`{kind}` necesita `value` como lista no vacía de valores simples.")
            elif kind in _UNARY:
                extra = [k for k in ("value", "value_column") if k in crit]
                if extra:
                    bad(f"`{kind}` no admite {extra}.")
        if not ok:
            return None
        return _Rule(
            id=rid, query=query, kind=kind,
            column=column.lower() if isinstance(column, str) else None,
            value=value,
            value_column=value_column.lower() if isinstance(value_column, str) else None,
            mode=mode if kind not in _PRESENCE else "all",
            message=message, ok_message=ok_message,
        )

    def _compile_projection(self, name: str, *, mapping: bool,
                            single: bool = False) -> _Projection | None:
        raw = self._data.get(name)
        if raw is None:
            return None
        err = self._errors.append
        where = f"[{name}]"
        if not isinstance(raw, dict):
            err(f"{where}: debe ser una tabla.")
            return None
        allowed = {"query", "column"} if single else {"query", "columns"}
        for key in sorted(set(raw) - allowed):
            err(f"{where}: clave desconocida '{key}'.")
        query = raw.get("query")
        if query not in self._queries:
            err(f"{where}: la consulta '{query}' no está declarada en [[query]].")
            return None
        if single:
            col = raw.get("column")
            if not isinstance(col, str) or not _ID_RE.match(col):
                err(f"{where}: falta `column`.")
                return None
            return _Projection(query, {"value": col.lower()})
        cols = raw.get("columns")
        if mapping:
            if (not isinstance(cols, dict) or not cols
                    or not all(isinstance(k, str) and _ID_RE.match(k)
                               and isinstance(v, str) and _ID_RE.match(v)
                               for k, v in cols.items())):
                err(f"{where}: `columns` debe ser una tabla clave = \"columna\".")
                return None
            return _Projection(query, {k: v.lower() for k, v in cols.items()})
        if (not isinstance(cols, list) or not cols
                or not all(isinstance(c, str) and _ID_RE.match(c) for c in cols)):
            err(f"{where}: `columns` debe ser una lista de columnas.")
            return None
        return _Projection(query, {c.lower(): c.lower() for c in cols})

    # -- ejecución ---------------------------------------------------------
    @staticmethod
    def _args(q: _Query, control_number: str, curp: str | None) -> list[str]:
        values = {"control_number": control_number, "curp": curp}
        args = []
        for p in q.params:
            v = values.get(p)
            if v is None or not str(v).strip():
                raise _EvalError(f"la consulta '{q.id}' necesita '{p}' y no se proporcionó")
            args.append(str(v).strip())
        return args

    def evaluate(self, client, control_number: str, *, curp: str | None = None) -> Verdict:
        """Corre las reglas contra el SII. Nunca lanza por el SII: cualquier
        falla de consulta o de regla es `Verdict(status="error")`."""
        if self._errors:
            return Verdict(status="error", rules_version=self.version,
                           error="Reglas inválidas: " + " | ".join(self._errors))

        cache: dict[str, list[dict]] = {}
        current = {"query": None}

        def rows_for(qid: str) -> list[dict]:
            if qid not in cache:
                current["query"] = qid
                q = self._queries[qid]
                cache[qid] = _norm_rows(
                    client.query(q.sql, self._args(q, control_number, curp), query_id=qid))
                current["query"] = None
            return cache[qid]

        warnings: list[str] = []
        try:
            results = [self._eval_rule(rule, rows_for(rule.query), warnings)
                       for rule in self._rules]
            identity = self._project(self._identity, rows_for, warnings)
            facts = self._project(self._facts, rows_for, warnings)
        except _EvalError as exc:
            return Verdict(status="error", rules_version=self.version, error=str(exc))
        except SiiError as exc:
            where = f"consulta '{current['query']}': " if current["query"] else ""
            detail = str(exc) or type(exc).__name__
            logger.warning("SII: %s%s (%s)", where, detail, type(exc).__name__)
            return Verdict(status="error", rules_version=self.version,
                           error=f"{where}{detail}")
        except Exception as exc:  # noqa: BLE001 — "nunca lanza por el SII"
            # Mensaje crudo fuera: un error inesperado del cliente puede traer
            # cualquier cosa (cadena de conexión, datos). Solo el tipo.
            logger.warning("SII: error inesperado al evaluar (%s)", type(exc).__name__)
            return Verdict(status="error", rules_version=self.version,
                           error=f"Error inesperado al consultar el SII ({type(exc).__name__}).")

        status = "apt" if all(r.ok for r in results) else "not_apt"
        return Verdict(status=status, results=results, facts=facts, identity=identity,
                       rules_version=self.version, warnings=warnings)

    def _eval_rule(self, rule: _Rule, rows: list[dict], warnings: list[str]) -> RuleResult:
        if rule.kind == "exists":
            ok = bool(rows)
        elif rule.kind == "not_exists":
            ok = not rows
        elif not rows:
            ok = False  # fail-closed: `all` sobre 0 filas sería verdad vacía
        else:
            checks = [self._check_row(rule, row) for row in rows]
            ok = all(checks) if rule.mode == "all" else any(checks)
        template = rule.message if not ok else (rule.ok_message or DEFAULT_OK_MESSAGE)
        return RuleResult(rule=rule.id, ok=ok,
                          message=self._render(template, rule, rows, warnings))

    @staticmethod
    def _check_row(rule: _Rule, row: dict) -> bool:
        for col in (rule.column, rule.value_column):
            if col is not None and col not in row:
                raise _EvalError(f"la regla '{rule.id}' usa la columna '{col}' que la "
                                 f"consulta '{rule.query}' no devuelve")
        left = row[rule.column]
        if rule.kind == "truthy":
            return _truthy(left)
        if rule.kind == "falsy":
            return not _truthy(left)
        if left is None:
            return False  # NULL no cumple ninguna comparación (como en SQL)
        try:
            if rule.kind in _SET:
                hit = any(_eq(left, v) for v in rule.value)
                return hit if rule.kind == "in" else not hit
            right = row[rule.value_column] if rule.value_column else rule.value
            if right is None:
                return False
            if rule.kind == "equals":
                return _eq(left, right)
            if rule.kind == "not_equals":
                return not _eq(left, right)
            c = _cmp(left, right)
            return c >= 0 if rule.kind == "gte" else c <= 0
        except _EvalError as exc:
            raise _EvalError(f"la regla '{rule.id}': {exc}") from None

    def _render(self, template: str, rule: _Rule, rows: list[dict],
                warnings: list[str]) -> str:
        """`{columna}` → valor de la PRIMERA fila; lo que no viene queda
        literal (nunca KeyError). Solo nombres simples: `{a.b}`/`{a[0]}` no
        se evalúan (por eso no es `str.format_map`)."""
        first = rows[0] if rows else None
        masked = (self._credential.columns["value"] if self._credential else None)

        def sub(m: re.Match) -> str:
            col = m.group(1).lower()
            if first is None:
                return m.group(0)
            if col not in first:
                warnings.append(f"La regla '{rule.id}': el mensaje usa {{{m.group(1)}}} "
                                f"que la consulta '{rule.query}' no devuelve.")
                return m.group(0)
            if col == masked:
                return MASK
            return _display(first[col])

        return _PLACEHOLDER_RE.sub(sub, template)

    @staticmethod
    def _project(proj: _Projection | None, rows_for, warnings: list[str]) -> dict:
        if proj is None:
            return {}
        rows = rows_for(proj.query)
        if not rows:
            return {}
        first = rows[0]
        out = {}
        for key, col in proj.columns.items():
            if col not in first:
                warnings.append(f"La consulta '{proj.query}' no devuelve la columna '{col}'.")
            out[key] = _jsonable(first.get(col))
        return out

    def fetch_credential(self, client, control_number: str, *,
                         curp: str | None = None) -> Secret | None:
        """El NIP del SII, o None si no hay `[credential]` o el SII no lo da.

        Las fallas del SII SÍ se propagan (`SiiUnavailable`/`SiiQueryError`):
        quien aprueba debe distinguir «no tiene NIP» de «no se pudo
        preguntar». La consulta va en modo `sensitive` (el cliente no pone el
        texto del driver, que puede traer el NIP, en el log ni en el error).
        Nada aquí registra ni guarda el valor.
        """
        if self._errors:
            raise SiiRulesError("Reglas inválidas: " + " | ".join(self._errors))
        if self._credential is None:
            return None
        q = self._queries[self._credential.query]
        try:
            args = self._args(q, control_number, curp)
        except _EvalError as exc:
            raise SiiRulesError(str(exc)) from None
        rows = _norm_rows(client.query(q.sql, args, query_id=q.id, sensitive=True))
        if not rows:
            return None
        raw = rows[0].get(self._credential.columns["value"])
        if raw is None:
            return None
        text = str(_jsonable(raw)).strip()
        return Secret(text) if text else None
