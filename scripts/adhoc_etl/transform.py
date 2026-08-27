"""Convierte el legacy extraído en los `.sql` del import.

Fase F4 del ETL de Calidad. Lee `build/adhoc_legacy/*.json` (que produce
`extract.py`) más `_identity_map.json` (que produce `identities.py`) y escribe
`database/DML/adhoc/legacy_import/*.sql`.

## Por qué genera SQL y no inserta directo

El entregable pedido es un `.sql` que se pueda correr en el servidor de
producción. Ese servidor no tiene acceso al SQL Server del proveedor, así que
un script que se conecte a las dos bases no sirve allá. El `.sql` sí es
portable, y además queda auditable antes de ejecutarse.

Tampoco se puede importar por la API: `document_service.bulk_create` fuerza
`status='Borrador'` ignorando el payload, así que ningún documento aprobado
entraría por endpoint.

## Mapeo de usuarios

`core_users` NO se trunca, así que sus ids no se pueden fijar desde aquí. Los
placeholders se insertan con `ON CONFLICT (username) DO NOTHING` y el mapa
legacy→core se materializa en una tabla temporal `_adhoc_user_map`, que el
resto de los archivos consultan con un JOIN. Eso mantiene el import idempotente
aunque los ids de `core_users` cambien entre corridas.

Los 14 archivos corren en UNA transacción y UNA conexión (ver el ejecutor en
`itcj2/cli/adhoc.py`), que es lo que hace válida la tabla temporal.

## Gotchas del legacy que este módulo aplica

- 13 columnas guardan números como texto (`au_step`, `task_status`,
  `usuarios.area`…). Todo pasa por `as_int()`.
- `a_done` está invertido: 1 = pendiente, 0 = ejecutada.
- `td_tarea` apunta al COMENTARIO, no a la tarea.
- `dap_parent` es la raíz de la cadena, no el predecesor.
- `dap_end_date` es la fecha de aprobación, no de fin.
"""
from __future__ import annotations

import json
import re
import unicodedata
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "build" / "adhoc_legacy"
OUT = ROOT / "database" / "DML" / "adhoc" / "legacy_import"

# Basura de pruebas de 2015: apuntan a área y proceso inexistentes y sus
# archivos ni siquiera están en disco.
TEST_DOCUMENT_IDS = {1, 2, 6, 9}
# Proceso 'Pruebas': ningún documento real lo usa.
TEST_PROCESS_IDS = {15}

AREA_DEFAULT_COLOR = "#4834d4"
PROCESS_DEFAULT_COLOR = "#b2bec3"


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------

def load(table: str) -> list[dict]:
    return json.loads((DATA / f"{table}.json").read_text(encoding="utf-8"))


def as_int(value: Any) -> int | None:
    """Castea los enteros-guardados-como-texto del legacy (§1.2 del diseño)."""
    if value is None or value == "":
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def q(value: Any) -> str:
    """Literal SQL. `None` → NULL; el resto va escapado."""
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, datetime):
        return "'" + value.isoformat(sep=" ") + "'"
    if isinstance(value, date):
        # `date.isoformat()` no acepta `sep`; hay que distinguirlo de datetime.
        return "'" + value.isoformat() + "'"
    text = str(value)
    # Los caracteres de control rompen el literal; el legacy tiene \r\n dentro
    # de comentarios multilínea, que sí queremos conservar.
    text = text.replace("\x00", "")
    return "'" + text.replace("'", "''") + "'"


def trim(value: Any) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).split())
    return text or None


def clip(value: Any, length: int) -> str | None:
    """Trunca respetando el límite de la columna, marcando el corte."""
    text = trim(value)
    if text is None:
        return None
    if len(text) <= length:
        return text
    return text[: length - 3] + "..."


def parse_dt(value: Any) -> datetime | None:
    """Parsea las fechas del legacy.

    `FOR JSON PATH` de SQL Server emite ISO 8601 con la `T` separadora
    (`2016-06-18T00:00:00`), no el `YYYY-MM-DD HH:MM:SS` de `sqlcmd` en modo
    tabla. Sin contemplarlo, TODAS las fechas salen NULL en silencio y los
    acuses (que exigen fecha) quedan en cero.
    """
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    text = str(value).strip()
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d",
                "%d/%m/%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def parse_date(value: Any) -> date | None:
    dt = parse_dt(value)
    return dt.date() if dt else None


def norm_name(value: Any) -> str:
    """Normaliza para deduplicar catálogos: sin acentos, mayúsculas, sin dobles espacios."""
    text = trim(value) or ""
    text = "".join(
        c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)
    )
    return re.sub(r"\s+", " ", text).upper()


class SqlFile:
    """Acumula sentencias y las escribe con cabecera."""

    def __init__(self, name: str, title: str, notes: str = "") -> None:
        self.name = name
        self.title = title
        self.notes = notes
        self.lines: list[str] = []

    def add(self, statement: str) -> None:
        self.lines.append(statement.rstrip())

    def insert_many(
        self, table: str, columns: Iterable[str], rows: list[tuple],
        *, batch: int = 500, suffix: str = "",
    ) -> None:
        """INSERT multi-fila en lotes.

        Multi-fila y no una sentencia por fila: el archivo de acuses pasa de
        ~2 MB a ~0.7 MB y de 12k sentencias a 25. `COPY FROM STDIN` no es
        alternativa — psycopg2 lo rechaza por `execute()` y `psql` no existe en
        el contenedor del backend.
        """
        if not rows:
            self.add(f"-- {table}: sin filas que insertar")
            return
        cols = ", ".join(columns)
        for start in range(0, len(rows), batch):
            chunk = rows[start : start + batch]
            values = ",\n  ".join("(" + ", ".join(chunk_row) + ")" for chunk_row in chunk)
            self.add(f"INSERT INTO {table} ({cols}) VALUES\n  {values}{suffix};")

    def write(self) -> int:
        OUT.mkdir(parents=True, exist_ok=True)
        header = [
            "-- " + "=" * 74,
            f"-- {self.title}",
            "-- " + "=" * 74,
            "-- GENERADO por scripts/adhoc_etl/transform.py — no editar a mano.",
            "-- Corre dentro de la transacción única de `adhoc import-legacy`.",
        ]
        if self.notes:
            header += ["--"] + [f"-- {line}" for line in self.notes.strip().splitlines()]
        header.append("")
        body = "\n".join(header + self.lines) + "\n"
        (OUT / self.name).write_text(body, encoding="utf-8")
        return len(body)


# ---------------------------------------------------------------------------
# Estado compartido entre pasos
# ---------------------------------------------------------------------------

class Ctx:
    """Mapas id_legacy → id_nuevo que el resto de los pasos necesita."""

    def __init__(self) -> None:
        self.area: dict[int, int] = {}
        self.process: dict[int, int] = {}
        self.doc_category: dict[int, int] = {}
        self.doc_classification: dict[int, int] = {}
        self.incident_category: dict[int, int] = {}
        self.program_category: dict[int, int] = {}
        self.flow: dict[int, int] = {}
        self.step: dict[int, int] = {}
        self.document: dict[int, int] = {}
        self.incident: dict[int, int] = {}
        self.program: dict[int, int] = {}
        self.year: dict[int, int] = {}
        self.indicator: dict[int, int] = {}
        self.task: dict[str, int] = {}
        self.comment: dict[str, int] = {}
        self.stats: dict[str, int] = {}
        self.users: dict[int, dict] = {}

    def user_expr(self, legacy_user: Any) -> str:
        """Referencia SQL al `core_users.id` de un usuario legacy."""
        uid = as_int(legacy_user)
        if uid is None or uid not in self.users:
            return "NULL"
        return f"(SELECT user_id FROM _adhoc_user_map WHERE legacy_id = {uid})"

    def user_expr_required(self, legacy_user: Any) -> str:
        """Como `user_expr`, pero para columnas NOT NULL.

        `adhoc_task_comments.user_id` no admite NULL: un autor irresoluble
        cuelga del usuario tecnico en vez de tumbar el import. Perder el
        comentario tampoco seria gratis — una tarea sin ningun comentario queda
        bloqueada en `task_workflow_service.py:99-103`.
        """
        uid = as_int(legacy_user)
        if uid is None or uid not in self.users:
            uid = 2      # id fantasma, mapeado al usuario tecnico
        return f"(SELECT user_id FROM _adhoc_user_map WHERE legacy_id = {uid})"

    def identity_key(self, legacy_user: Any) -> str | None:
        """Identidad RESUELTA de un usuario legacy.

        Deduplicar por `id_usuario` del legacy no basta: dos cuentas distintas
        pueden ser la misma persona (D6 fusiona vreyes+vuribe y
        dbecerra+fbecerra), asi que colapsan contra los UNIQUE de acuses,
        visibilidad y usuario-area. Hay que agrupar por esto, no por el id.
        """
        uid = as_int(legacy_user)
        entry = self.users.get(uid) if uid is not None else None
        return (entry or {}).get("resolved_username")

    def has_user(self, legacy_user: Any) -> bool:
        return as_int(legacy_user) in self.users
