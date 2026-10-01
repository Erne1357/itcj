"""Generadores de los `.sql` del import del SGC legacy.

Un `step_*` por archivo de `database/DML/adhoc/legacy_import/`. Todos reciben
el :class:`~scripts.adhoc_etl.transform.Ctx` y van dejando en él los mapas
`id_legacy → id_nuevo` que los pasos siguientes necesitan.

El orden de `ORDER` (abajo) no es estético: es el de las dependencias reales de
FK, y `adhoc_indicators.process_id` es NOT NULL, así que estructura va antes que
indicadores.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict

from transform import (
    AREA_DEFAULT_COLOR, DATA, PROCESS_DEFAULT_COLOR, SqlFile, TEST_DOCUMENT_IDS,
    TEST_PROCESS_IDS, Ctx, as_int, clip, load, norm_name, parse_date, parse_dt, q, trim,
)

UNKNOWN_USERNAME = "legacy_desconocido"


# ---------------------------------------------------------------------------
# 00 — TRUNCATE
# ---------------------------------------------------------------------------

#: Tablas de DATOS que el import vacía. `adhoc_mail_config` NO está: es el
#: interruptor global de correo del SGC, no dato del legacy, y truncarlo deja
#: el panel de correo en 503 sin que ningún archivo del import lo reponga.
TRUNCATE_TABLES = [
    "adhoc_task_comment_files", "adhoc_task_approvals", "adhoc_task_comments",
    "adhoc_task_assignees", "adhoc_tasks",
    "adhoc_incident_files", "adhoc_incidents", "adhoc_incident_categories",
    "adhoc_program_event_files", "adhoc_program_events", "adhoc_program_categories",
    "adhoc_indicator_trackings", "adhoc_indicators", "adhoc_indicator_years",
    "adhoc_document_acknowledgements", "adhoc_document_visibility",
    "adhoc_documents", "adhoc_document_categories", "adhoc_document_classifications",
    "adhoc_flow_step_assignees", "adhoc_approval_flow_steps", "adhoc_approval_flows",
    "adhoc_user_areas", "adhoc_areas", "adhoc_processes",
]


def step_truncate(ctx: Ctx) -> SqlFile:
    f = SqlFile(
        "00_truncate.sql",
        "Vaciado de las tablas de datos de adhoc",
        "adhoc_mail_config NO se toca: es configuracion del SGC, no dato del legacy.\n"
        "Truncarla deja el panel de correo en 503 (api/mail.py:52-57) y ningun\n"
        "archivo del import la repone.\n"
        "RESTART IDENTITY para que los ids explicitos del import empiecen limpios.",
    )
    f.add("TRUNCATE TABLE\n  " + ",\n  ".join(TRUNCATE_TABLES) + "\n  RESTART IDENTITY CASCADE;")
    f.add(
        "\n-- Reposicion defensiva del singleton de correo.\n"
        "INSERT INTO adhoc_mail_config (id, is_enabled) VALUES (1, true)\n"
        "ON CONFLICT (id) DO NOTHING;"
    )
    return f


# ---------------------------------------------------------------------------
# 01 / 02 — identidades y acceso
# ---------------------------------------------------------------------------

def _roles_for(flags: dict) -> list[str]:
    """Traduce ac_docs / ac_inci / ac_repo a roles de adhoc.

    `core_user_app_roles` tiene PK (user_id, app_id, role_id), o sea admite
    VARIOS roles por app: los flags combinados no necesitan un rol nuevo.
    """
    docs = (flags.get("ac_docs") or "").strip().upper() == "Y"
    inci = (flags.get("ac_inci") or "").strip().upper() == "Y"
    repo = (flags.get("ac_repo") or "").strip().upper() == "Y"
    if docs and inci and repo:
        return ["admin"]
    roles = []
    if docs:
        roles.append("supervisor_doc")
    if inci:
        roles.append("supervisor_inc")
    if repo:
        # `ac_repo` = "reportes" en el legacy; supervisor_prog es el supervisor
        # de modulo mas cercano en adhoc (supuesto pendiente de Calidad).
        roles.append("supervisor_prog")
    return roles or ["consult"]


def step_users(ctx: Ctx) -> list[SqlFile]:
    entries = json.loads((DATA / "_identity_map.json").read_text(encoding="utf-8"))
    by_username = {e["username"]: e for e in entries}

    for entry in entries:
        if entry["verdict"] == "merge":
            found = re.search(r"'([^']+)'", entry.get("note") or "")
            target = by_username.get(found.group(1)) if found else None
            entry["resolved_username"] = (
                (target or {}).get("core_username") or (target or {}).get("username")
            )
        elif entry["verdict"] == "match":
            # El username del CORE, no el del legacy: el empate por nombre
            # resuelve lvillarreal->dbustillos, ghernandez->gcruz,
            # jcpizarro->jpizarro. Con el username legacy el JOIN falla y esos
            # usuarios caen al tecnico, colapsando sus pares contra los UNIQUE.
            entry["resolved_username"] = entry.get("core_username") or entry["username"]
        else:
            entry["resolved_username"] = f"legacy_{entry['username']}"[:60]
    ctx.users = {e["legacy_id"]: e for e in entries}

    f = SqlFile(
        "01_users_placeholder.sql",
        "Identidades: placeholders en core_users y mapa legacy -> core",
        "core_users NO se trunca, asi que sus ids no se pueden fijar desde aqui. Los\n"
        "placeholders se insertan SIN id explicito y con ON CONFLICT (username) DO\n"
        "NOTHING, y el mapa se materializa en una tabla TEMPORAL que el resto de los\n"
        "archivos consulta por JOIN: asi el import es idempotente aunque los ids de\n"
        "core_users cambien entre corridas.\n"
        "La tabla temporal solo es valida porque los archivos corren en UNA conexion\n"
        "y UNA transaccion (ejecutor de itcj2/cli/adhoc.py).",
    )

    rows = []
    for e in entries:
        if e["verdict"] != "placeholder":
            continue
        name = (e["name"] or e["username"] or "?").strip()
        parts = name.split()
        first = " ".join(parts[:-1]) if len(parts) > 1 else (parts[0] if parts else e["username"])
        last = parts[-1] if len(parts) > 1 else ""
        rows.append((
            q(e["resolved_username"]), q(first[:120]), q(last[:120]),
            q(e["email"] or None), "false",
        ))
    rows.append((q(UNKNOWN_USERNAME), q("Usuario"), q("no conservado"), "NULL", "false"))

    f.add(
        "-- Personas y cuentas del SGC legacy que no existen en core_users. Entran\n"
        "-- INACTIVAS: conservan la autoria del historial sin poder iniciar sesion.\n"
        "-- password_hash queda NULL a proposito: no hay hash valido posible."
    )
    f.insert_many(
        "core_users", ("username", "first_name", "last_name", "email", "is_active"),
        rows, suffix="\nON CONFLICT (username) DO NOTHING",
    )

    f.add(
        "\nCREATE TEMPORARY TABLE _adhoc_user_map (\n"
        "  legacy_id INTEGER PRIMARY KEY,\n"
        "  user_id   BIGINT NOT NULL\n"
        ") ON COMMIT DROP;"
    )
    pairs = [(e["legacy_id"], e["resolved_username"]) for e in entries if e["resolved_username"]]
    f.add(
        "INSERT INTO _adhoc_user_map (legacy_id, user_id)\n"
        "SELECT v.legacy_id, u.id\n"
        "FROM (VALUES\n  "
        + ",\n  ".join(f"({lid}, {q(name)})" for lid, name in pairs)
        + "\n) AS v(legacy_id, username)\n"
        "JOIN core_users u ON lower(u.username) = lower(v.username)\n"
        "ON CONFLICT (legacy_id) DO NOTHING;"
    )
    # El mapa tiene que ser EXHAUSTIVO: `adhoc_task_comments.user_id` es NOT
    # NULL, asi que un id legacy sin fila aqui tumba el import entero. Se cubre
    # todo id conocido (por si su placeholder no llego a insertarse) mas los
    # fantasmas 2, 6, 9, 11 y 57, que ya no existen ni en `usuarios` del legacy
    # pero acumulan 133 referencias.
    fallback_ids = sorted(set(ctx.users) | {2, 6, 9, 11, 57})
    f.add(
        "\n-- Red de seguridad: todo id legacy resuelve, al usuario real o al tecnico.\n"
        "INSERT INTO _adhoc_user_map (legacy_id, user_id)\n"
        "SELECT v.legacy_id, u.id FROM (VALUES\n  "
        + ",".join(f"({i})" for i in fallback_ids)
        + "\n) AS v(legacy_id)\n"
        f"CROSS JOIN (SELECT id FROM core_users WHERE username = {q(UNKNOWN_USERNAME)}) u\n"
        "ON CONFLICT (legacy_id) DO NOTHING;"
    )
    ctx.stats["core_users"] = len(rows)

    g = SqlFile(
        "02_user_app_roles.sql",
        "Acceso a la app segun los flags ac_docs / ac_inci / ac_repo",
        "Solo reciben rol los usuarios ACTIVOS del legacy; los placeholders inactivos\n"
        "conservan el historial pero no entran a la app.",
    )
    grants = []
    for e in entries:
        if not e["active"] or e["verdict"] == "merge":
            continue
        for role in _roles_for(e.get("flags") or {}):
            grants.append((e["legacy_id"], role))
    if grants:
        g.add(
            "INSERT INTO core_user_app_roles (user_id, app_id, role_id)\n"
            "SELECT m.user_id, a.id, r.id\n"
            "FROM (VALUES\n  "
            + ",\n  ".join(f"({lid}, {q(role)})" for lid, role in grants)
            + "\n) AS v(legacy_id, role_name)\n"
            "JOIN _adhoc_user_map m ON m.legacy_id = v.legacy_id\n"
            "JOIN core_roles r ON r.name = v.role_name\n"
            "CROSS JOIN (SELECT id FROM core_apps WHERE key = 'adhoc') a\n"
            "ON CONFLICT DO NOTHING;"
        )
    ctx.stats["core_user_app_roles"] = len(grants)
    return [f, g]


# ---------------------------------------------------------------------------
# 03 — catálogos
# ---------------------------------------------------------------------------

def _catalog(f: SqlFile, table: str, source: list[dict], id_key: str, name_key: str,
             target: dict[int, int], label: str) -> None:
    """Catálogo de nombre único, deduplicando por nombre normalizado."""
    seen: dict[str, int] = {}
    rows = []
    next_id = 1
    for row in source:
        name = trim(row.get(name_key))
        if not name:
            continue
        key = norm_name(name)
        if key in seen:
            target[row[id_key]] = seen[key]
            continue
        seen[key] = next_id
        target[row[id_key]] = next_id
        rows.append((str(next_id), q(name[:100])))
        next_id += 1
    f.add(f"\n-- {label}: {len(rows)} de {len(source)} del legacy")
    f.insert_many(table, ("id", "name"), rows)
    f.add(
        f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
        f"GREATEST((SELECT COALESCE(MAX(id), 1) FROM {table}), 1));"
    )


def step_catalogs(ctx: Ctx) -> SqlFile:
    f = SqlFile(
        "03_catalogs.sql",
        "Catalogos del SGC: tipos de documento, clase, incidencia y programa",
        "Solo los del legacy (D10): las semillas genericas ISO se fueron en el\n"
        "TRUNCATE. Son los nombres que la gente de Calidad reconoce y los que usan\n"
        "de verdad sus 206 documentos y 262 incidencias.\n"
        "Se deduplica por nombre normalizado (sin acentos, mayusculas) porque `name`\n"
        "es UNIQUE y el legacy tiene pares como 'Accion Preventiva' / 'Acción Preventiva'.",
    )
    _catalog(f, "adhoc_document_categories", load("doctypes"), "dt_id", "dt_name",
             ctx.doc_category, "Tipos de documento")
    _catalog(f, "adhoc_document_classifications", load("docclass"), "dc_id", "dc_name",
             ctx.doc_classification, "Clases de documento")
    _catalog(f, "adhoc_incident_categories", load("incitypes"), "it_id", "it_name",
             ctx.incident_category, "Tipos de incidencia")
    _catalog(f, "adhoc_program_categories", load("progtypes"), "pt_id", "pt_name",
             ctx.program_category, "Tipos de programa")
    return f


# ---------------------------------------------------------------------------
# 04 — estructura
# ---------------------------------------------------------------------------

def step_structure(ctx: Ctx) -> SqlFile:
    f = SqlFile(
        "04_structure.sql",
        "Areas, procesos y la asignacion usuario-area",
        "`areas.responsable` es 100% NULL en el legacy y el destino tampoco tiene esa\n"
        "columna: se descarta.\n"
        "El proceso 'Pruebas' (id 15) no se migra: ningun documento real lo usa.\n"
        "adhoc_user_areas sale de `usuarios.area`, NO de `areas_usrs`: esa tabla\n"
        "apunta a `grupos`, que tiene 0 filas, y solo 20 de sus 51 filas coinciden.\n"
        "OJO: `usuarios.area` es varchar en el legacy (gotcha de tipos).",
    )

    areas = load("areas")
    rows = []
    for i, a in enumerate(areas, start=1):
        name = trim(a.get("nom_area"))
        if not name:
            continue
        ctx.area[a["id_area"]] = i
        rows.append((str(i), q(name[:100]), q(AREA_DEFAULT_COLOR), "true", str(a["id_area"])))
    f.add(f"\n-- Areas: {len(rows)}. TRIM obligatorio: 3 traen espacio final y `name` es UNIQUE.")
    f.insert_many("adhoc_areas", ("id", "name", "color", "is_active", "legacy_id"), rows)
    f.add("SELECT setval(pg_get_serial_sequence('adhoc_areas', 'id'), "
          "GREATEST((SELECT COALESCE(MAX(id), 1) FROM adhoc_areas), 1));")

    rows = []
    next_id = 1
    for p in load("procesos"):
        if p["id_proceso"] in TEST_PROCESS_IDS:
            continue
        name = trim(p.get("proc_nom"))
        if not name:
            continue
        ctx.process[p["id_proceso"]] = next_id
        color = trim(p.get("proc_color")) or PROCESS_DEFAULT_COLOR
        rows.append((str(next_id), q(name[:100]), q(color[:7]), str(p["id_proceso"])))
        next_id += 1
    f.add(f"\n-- Procesos: {len(rows)}. `proc_color` SI es columna real en esta base\n"
          "-- (el docstring del modelo dice que el legacy lo empacaba en description:\n"
          "-- aqui es falso, y `procpr_desc` esta 100% vacia).")
    f.insert_many("adhoc_processes", ("id", "name", "color", "legacy_id"), rows)
    f.add("SELECT setval(pg_get_serial_sequence('adhoc_processes', 'id'), "
          "GREATEST((SELECT COALESCE(MAX(id), 1) FROM adhoc_processes), 1));")

    pairs = []
    seen_areas: set[tuple[str, int]] = set()
    for u in load("usuarios"):
        area_id = as_int(u.get("area"))
        if area_id not in ctx.area or u["id_usuario"] not in ctx.users:
            continue
        # Por identidad resuelta: las cuentas fusionadas de D6 chocarian contra
        # la PK compuesta de adhoc_user_areas.
        key = (ctx.identity_key(u["id_usuario"]), ctx.area[area_id])
        if key in seen_areas:
            continue
        seen_areas.add(key)
        pairs.append((u["id_usuario"], ctx.area[area_id]))
    if pairs:
        f.add(f"\n-- Usuario-area: {len(pairs)} de 59 usuarios tienen area resoluble.")
        f.add(
            "INSERT INTO adhoc_user_areas (user_id, area_id)\n"
            "SELECT m.user_id, v.area_id\n"
            "FROM (VALUES\n  "
            + ",\n  ".join(f"({lid}, {aid})" for lid, aid in pairs)
            + "\n) AS v(legacy_id, area_id)\n"
            "JOIN _adhoc_user_map m ON m.legacy_id = v.legacy_id\n"
            "ON CONFLICT DO NOTHING;"
        )
    ctx.stats["adhoc_areas"] = len(ctx.area)
    ctx.stats["adhoc_processes"] = len(ctx.process)
    ctx.stats["adhoc_user_areas"] = len(pairs)
    return f


# ---------------------------------------------------------------------------
# 05 — flujos de aprobación
# ---------------------------------------------------------------------------

def step_flows(ctx: Ctx) -> SqlFile:
    f = SqlFile(
        "05_flows.sql",
        "Rutas de aprobacion, sus pasos y los validadores de cada paso",
        "Solo los 81 pasos cuya ruta sobrevive (D15): los otros 119 apuntan a 48\n"
        "`as_docto` de rutas ya borradas, y flow_id es NOT NULL.\n"
        "`as_ordenar` es un contador GLOBAL 1..215, no un orden por flujo: se\n"
        "renumera 1..N por ruta o la UI de reordenamiento queda sin sentido.\n"
        "`as_limit` (1..15 dias) SI se migra: sin el los pasos heredan un SLA\n"
        "inventado de 3 dias.\n"
        "OJO: `appr_usrs.au_step` es varchar y `as_id` es int (gotcha de tipos).",
    )

    rows = []
    for i, r in enumerate(load("rutas_apro"), start=1):
        name = trim(r.get("ruta_nombre")) or f"Ruta {r['ruta_id']}"
        ctx.flow[r["ruta_id"]] = i
        rows.append((str(i), q(name[:100]), str(r["ruta_id"])))
    f.add(f"\n-- Rutas: {len(rows)}")
    f.insert_many("adhoc_approval_flows", ("id", "name", "legacy_id"), rows)
    f.add("SELECT setval(pg_get_serial_sequence('adhoc_approval_flows', 'id'), "
          "GREATEST((SELECT COALESCE(MAX(id), 1) FROM adhoc_approval_flows), 1));")

    steps = [s for s in load("appr_steps_config") if s.get("as_docto") in ctx.flow]
    by_flow: dict[int, list[dict]] = defaultdict(list)
    for s in steps:
        by_flow[s["as_docto"]].append(s)
    rows = []
    next_id = 1
    for flow_legacy, group in by_flow.items():
        group.sort(key=lambda s: (as_int(s.get("as_ordenar")) or 0, s["as_id"]))
        for order, s in enumerate(group, start=1):
            ctx.step[s["as_id"]] = next_id
            days = as_int(s.get("as_limit")) or 3
            rows.append((
                str(next_id), str(ctx.flow[flow_legacy]),
                q(trim(s.get("as_name")) or f"Paso {order}"),
                str(days), str(order),
            ))
            next_id += 1
    f.add(f"\n-- Pasos: {len(rows)} de 200 (D15). step_order renumerado con DENSE_RANK por ruta.")
    f.insert_many("adhoc_approval_flow_steps",
                  ("id", "flow_id", "name", "days_limit", "step_order"), rows)
    f.add("SELECT setval(pg_get_serial_sequence('adhoc_approval_flow_steps', 'id'), "
          "GREATEST((SELECT COALESCE(MAX(id), 1) FROM adhoc_approval_flow_steps), 1));")

    # Validadores: appr_usrs normales + los "jefes" con notify_on_overdue.
    assignees: dict[tuple[int, int], bool] = {}
    for u in load("appr_usrs"):
        step = ctx.step.get(as_int(u.get("au_step")))
        if step and ctx.users.get(as_int(u.get("au_user"))):
            assignees.setdefault((step, as_int(u["au_user"])), False)
    for b in load("appr_usrs_boss"):
        step = ctx.step.get(as_int(b.get("au_step")))
        if step and ctx.users.get(as_int(b.get("au_user"))):
            assignees[(step, as_int(b["au_user"]))] = True
    if assignees:
        f.add(
            f"\n-- Validadores: {len(assignees)} pares. Los 'jefes' de appr_usrs_boss\n"
            "-- entran con notify_on_overdue=true. Deduplicado: appr_usrs trae 1 par\n"
            "-- (au_step, au_user) repetido y la PK destino es compuesta."
        )
        f.add(
            "INSERT INTO adhoc_flow_step_assignees (step_id, user_id, notify_on_overdue)\n"
            "SELECT v.step_id, m.user_id, v.notify\n"
            "FROM (VALUES\n  "
            + ",\n  ".join(
                f"({step}, {luser}, {'true' if notify else 'false'})"
                for (step, luser), notify in sorted(assignees.items())
            )
            + "\n) AS v(step_id, legacy_id, notify)\n"
            "JOIN _adhoc_user_map m ON m.legacy_id = v.legacy_id\n"
            "ON CONFLICT DO NOTHING;"
        )
    ctx.stats["adhoc_approval_flows"] = len(ctx.flow)
    ctx.stats["adhoc_approval_flow_steps"] = len(ctx.step)
    ctx.stats["adhoc_flow_step_assignees"] = len(assignees)
    return f
