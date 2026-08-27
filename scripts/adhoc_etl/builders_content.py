"""Pasos 06-10 del import: documentos, acuses, incidencias, programa, indicadores."""
from __future__ import annotations

import re
import unicodedata
from collections import defaultdict

from transform import (
    DATA, SqlFile, TEST_DOCUMENT_IDS, Ctx, as_int, clip, load, norm_name,
    parse_date, parse_dt, q, trim,
)

# Vocabularios destino (utils/constants.py). Se escriben literales aquí porque
# este script corre fuera del contenedor y no importa la app.
DOC_DRAFT, DOC_APPROVED, DOC_OBSOLETE = "Borrador", "Aprobado", "Obsoleto"

#: `proj_prioridad` 1/2/3 → vocabulario destino. Orden ascendente, deducido de
#: los datos: las de prioridad 3 cierran en 181 días promedio y las de 2 en 303.
INCIDENT_PRIORITY = {1: "Baja", 2: "Media", 3: "Alta"}
#: `proj_status` 0/1/2. Las 140 de estatus 1 son EXACTAMENTE las que tienen
#: `proj_finish_date`; 52 de las 58 de estatus 2 no tienen ninguna tarea.
INCIDENT_STATUS = {0: "Iniciada", 1: "Cerrada", 2: "No Iniciada"}
PROGRAM_STATUS = {0: "En Proceso", 1: "Completado", 2: "Planeado"}


def secure_name(name: str) -> str:
    """Equivalente a `werkzeug.secure_filename` para el nombre en disco.

    La app sanea así al subir, y `open_stored` lee lo que haya en la columna,
    así que el archivo migrado tiene que llamarse igual que si lo hubieran
    subido por la web.
    """
    text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", text).strip("._")
    return text or "archivo"


# ---------------------------------------------------------------------------
# 06 — documentos
# ---------------------------------------------------------------------------

def _document_status(row: dict) -> tuple[str, bool]:
    """(status, is_current) a partir del cross-tab real del legacy.

    Solo se dan tres combinaciones de (dap_status, dap_approval_status):
    (0,0)=6 en captura, (1,1)=141 vigentes, (1,2)=59 superados. Ningun documento
    del legacy es 'En Revision' ni 'Rechazado'.
    """
    approval = as_int(row.get("dap_approval_status"))
    if approval == 2:
        return DOC_OBSOLETE, False
    if approval == 1:
        return DOC_APPROVED, True
    return DOC_DRAFT, True


def step_documents(ctx: Ctx, file_plan: list[dict]) -> SqlFile:
    f = SqlFile(
        "06_documents.sql",
        "Documentos controlados del SGC",
        "`dap_end_date` es la fecha de APROBACION, no de fin: en 64 de 206 filas es\n"
        "anterior a dap_start_date.\n"
        "`dap_tipo` guarda el NOMBRE del tipo, no el dt_id, y 2 de sus 14 valores ni\n"
        "siquiera existen en doctypes: el empate va por nombre normalizado.\n"
        "`dap_parent` es la RAIZ de la cadena, no el predecesor: arbol de 2 niveles\n"
        "con 145 raices que se apuntan a si mismas.\n"
        "is_current sale de dap_approval_status=2 (superado), que es el propio\n"
        "marcador del legacy.\n"
        "El parent_id se resuelve en una SEGUNDA pasada: es autoreferencia y asi se\n"
        "evita ordenar topologicamente.",
    )

    docs = [d for d in load("doc_approve") if d["dap_id"] not in TEST_DOCUMENT_IDS]
    doctypes = {norm_name(t["dt_name"]): ctx.doc_category.get(t["dt_id"])
                for t in load("doctypes")}

    # Autor: primer `indiceprin.a_user` del documento (unica pista disponible).
    first_actor: dict[int, int] = {}
    for r in sorted(load("indiceprin"), key=lambda r: r["accion_id"]):
        doc = as_int(r.get("a_docto"))
        user = as_int(r.get("a_user"))
        if doc and user and doc not in first_actor and user in ctx.users:
            first_actor[doc] = user

    flow_of_doc = {}
    for r in load("doc_route"):
        flow = ctx.flow.get(r.get("dr_routeid"))
        if flow:
            flow_of_doc[r.get("dr_docid")] = (flow, parse_dt(r.get("dr_startdate")))

    staged = {int(p.name): p for p in (DATA.parent / "adhoc_legacy_files" / "doc_approve").iterdir()
              if p.is_dir() and p.name.isdigit()} if (DATA.parent / "adhoc_legacy_files" / "doc_approve").exists() else {}

    rows = []
    parent_pairs: list[tuple[int, int]] = []
    for i, d in enumerate(docs, start=1):
        ctx.document[d["dap_id"]] = i

    # UNA sola punta por cadena. `dap_approval_status = 2` marca lo superado,
    # pero hay al menos una cadena donde dos versiones quedaron sin marcar: se
    # queda vigente la de dap_id mayor (la mas reciente) y el resto pasa a
    # 'Obsoleto'. Sin esto la lista de documentos muestra duplicados.
    chains: dict[int, list[dict]] = defaultdict(list)
    for d in docs:
        root = as_int(d.get("dap_parent"))
        chains[root if root in ctx.document else d["dap_id"]].append(d)
    current_ids: set[int] = set()
    for group in chains.values():
        candidates = [d for d in group if _document_status(d)[1]]
        winner = max(candidates or group, key=lambda d: d["dap_id"])
        current_ids.add(winner["dap_id"])

    for d in docs:
        new_id = ctx.document[d["dap_id"]]
        status, _ = _document_status(d)
        is_current = d["dap_id"] in current_ids
        if not is_current and status == DOC_APPROVED:
            status = DOC_OBSOLETE
        version = trim(d.get("dap_start_ver")) or "1.0"
        category = doctypes.get(norm_name(d.get("dap_tipo"))) if d.get("dap_tipo") else None
        flow, started = flow_of_doc.get(d["dap_id"], (None, None))

        file_url = None
        folder = staged.get(d["dap_id"])
        if folder is not None:
            names = sorted(p.name for p in folder.iterdir() if p.is_file())
            if names:
                safe = secure_name(names[0])
                file_url = f"{new_id}/{safe}"
                file_plan.append({
                    "src": str(folder / names[0]), "kind": "documents",
                    "entity_id": new_id, "name": safe,
                })

        created = parse_dt(d.get("dap_start_date")) or started
        rows.append((
            str(new_id), q(clip(d.get("dap_clave"), 50)), q(clip(d.get("dap_titulo"), 200) or "(sin título)"),
            q(version[:10]), q(status), "true" if is_current else "false",
            q(parse_dt(d.get("dap_end_date"))), q(parse_date(d.get("dap_vigencia"))),
            q(file_url), q(trim(d.get("dap_desc"))),
            str(category) if category else "NULL",
            str(ctx.doc_classification.get(as_int(d.get("dap_clase")))) if ctx.doc_classification.get(as_int(d.get("dap_clase"))) else "NULL",
            str(ctx.area.get(as_int(d.get("dap_area")))) if ctx.area.get(as_int(d.get("dap_area"))) else "NULL",
            str(ctx.process.get(as_int(d.get("dap_proceso")))) if ctx.process.get(as_int(d.get("dap_proceso"))) else "NULL",
            str(flow) if flow else "NULL",
            ctx.user_expr(first_actor.get(d["dap_id"])),
            q(created) if created else "now()",
            str(d["dap_id"]),
        ))
        parent = as_int(d.get("dap_parent"))
        if parent and parent != d["dap_id"] and parent in ctx.document:
            parent_pairs.append((new_id, ctx.document[parent]))

    f.add(f"\n-- Documentos: {len(rows)} de 206 (fuera los 4 de prueba de 2015).")
    f.insert_many(
        "adhoc_documents",
        ("id", "code", "title", "version", "status", "is_current", "approval_date",
         "expiration_date", "file_url", "notes", "category_id", "classification_id",
         "area_id", "process_id", "flow_id", "author_id", "created_at", "legacy_id"),
        rows, batch=200,
    )
    f.add("SELECT setval(pg_get_serial_sequence('adhoc_documents', 'id'), "
          "GREATEST((SELECT COALESCE(MAX(id), 1) FROM adhoc_documents), 1));")

    if parent_pairs:
        f.add(f"\n-- Cadenas de version: {len(parent_pairs)} hijas. Segunda pasada.")
        f.add(
            "UPDATE adhoc_documents d SET parent_id = v.parent_id\n"
            "FROM (VALUES\n  "
            + ",\n  ".join(f"({child}, {parent})" for child, parent in parent_pairs)
            + "\n) AS v(child_id, parent_id)\n"
            "WHERE d.id = v.child_id;"
        )
    ctx.stats["adhoc_documents"] = len(rows)
    return f


# ---------------------------------------------------------------------------
# 07 — acuses y visibilidad
# ---------------------------------------------------------------------------

def step_acknowledgements(ctx: Ctx) -> SqlFile:
    f = SqlFile(
        "07_document_acks.sql",
        "Acuses de recibo y visibilidad de documentos",
        "SON DOS COSAS DISTINTAS (D13).\n"
        "Acuse: accion de difusion de `indiceprin` con fecha real. Solo entra lo que\n"
        "trae `a_done_date`: los pendientes no son evidencia de nada.\n"
        "Visibilidad: `ver_doctos`, que el analisis inicial tomo por acuses. 126\n"
        "documentos tienen exactamente los mismos 51 usuarios y 33 personas aparecen\n"
        "en mas de 600 de 742 documentos: es la plantilla asignada por documento, no\n"
        "gente leyendo. La vista del proveedor se llamaba UsuariosxDocumento.",
    )

    acks: dict[tuple[int, int], str] = {}
    for r in load("indiceprin"):
        if r.get("a_type") is not None:
            continue
        doc = ctx.document.get(as_int(r.get("a_docto")))
        user = as_int(r.get("a_user"))
        when = parse_dt(r.get("a_done_date"))
        if not doc or user not in ctx.users or when is None:
            continue
        # Agrupado por identidad RESUELTA, no por id legacy: dos cuentas
        # fusionadas (D6: vreyes+vuribe, dbecerra+fbecerra) son la misma persona
        # y colapsarian contra UNIQUE(document_id, user_id).
        key = (doc, ctx.identity_key(user))
        if key not in acks or when > parse_dt(acks[key][1]):
            acks[key] = (user, when.isoformat(sep=" "))
    if acks:
        f.add(f"\n-- Acuses con fecha real: {len(acks)}")
        f.add(
            "INSERT INTO adhoc_document_acknowledgements (document_id, user_id, acknowledged_at)\n"
            "SELECT v.document_id, m.user_id, v.ts::timestamp\n"
            "FROM (VALUES\n  "
            + ",\n  ".join(f"({doc}, {user}, {q(ts)})"
                           for (doc, _), (user, ts) in sorted(acks.items()))
            + "\n) AS v(document_id, legacy_id, ts)\n"
            "JOIN _adhoc_user_map m ON m.legacy_id = v.legacy_id\n"
            "ON CONFLICT DO NOTHING;"
        )

    seen_visibility: set[tuple[int, str]] = set()
    visibility: list[tuple[int, int]] = []
    for r in load("ver_doctos"):
        doc = ctx.document.get(as_int(r.get("vd_docto")))
        user = as_int(r.get("vd_user"))
        if not doc or user not in ctx.users:
            continue
        key = (doc, ctx.identity_key(user))
        if key in seen_visibility:
            continue
        seen_visibility.add(key)
        visibility.append((doc, user))
    if visibility:
        f.add(f"\n-- Visibilidad: {len(visibility)} pares unicos de 30541 filas del legacy\n"
              "-- (el 68% apunta a documentos ya borrados: inmigrable por FK rota).")
        f.add(
            "INSERT INTO adhoc_document_visibility (document_id, user_id)\n"
            "SELECT v.document_id, m.user_id\n"
            "FROM (VALUES\n  "
            + ",\n  ".join(f"({doc}, {user})" for doc, user in sorted(visibility))
            + "\n) AS v(document_id, legacy_id)\n"
            "JOIN _adhoc_user_map m ON m.legacy_id = v.legacy_id\n"
            "ON CONFLICT DO NOTHING;"
        )
    ctx.stats["adhoc_document_acknowledgements"] = len(acks)
    ctx.stats["adhoc_document_visibility"] = len(visibility)
    return f


# ---------------------------------------------------------------------------
# 08 — incidencias
# ---------------------------------------------------------------------------

def step_incidents(ctx: Ctx) -> SqlFile:
    f = SqlFile(
        "08_incidents.sql",
        "Incidencias (no conformidades)",
        "`proyectos` son TODAS incidencias: proj_categoria es FK a incitypes al 100%,\n"
        "sin un solo NULL. El analisis previo decia que la tabla hacia doble funcion\n"
        "con proyectos; es falso, los programas viven en `programas`.\n"
        "`proj_grupo` (candidato natural a process_id) apunta a `grupos`, que tiene 0\n"
        "filas: process_id queda NULL en las 262. Trampa: 118 de 262 coinciden\n"
        "numericamente con procesos.id_proceso, pero es solape accidental de rangos.\n"
        "67 titulos superan los 200 chars del destino: se truncan y el integro va al\n"
        "inicio de la descripcion.",
    )

    incidents = load("proyectos")
    rows = []

    # Los placeholder van PRIMERO en el espacio de ids, no al final. La lista
    # ordena por id descendente (igual que documentos y programa), asi que con
    # los ids altos lo primero que veria Calidad al entrar serian 14 filas
    # "registro no conservado". Con los ids bajos quedan hasta el fondo.
    orphan_parents = sorted({
        as_int(t.get("task_proyecto")) for t in load("tareas")
        if as_int(t.get("task_proyecto"))
        and as_int(t.get("task_proyecto")) not in {p["proj_id"] for p in incidents}
    })
    for i, legacy in enumerate(orphan_parents, start=1):
        ctx.incident[legacy] = i
        rows.append((
            str(i), "NULL",
            q(f"Incidencia legacy #{legacy} — registro no conservado"),
            q("El registro original fue borrado del sistema legacy. Este marcador "
              "existe solo para conservar las tareas y comentarios que colgaban de él."),
            "NULL", "NULL", "NULL", q("Media"), q("Cerrada"), "NULL", "NULL", "NULL",
            str(-legacy),
        ))

    offset = len(orphan_parents)
    for i, p in enumerate(incidents, start=offset + 1):
        ctx.incident[p["proj_id"]] = i
    for p in incidents:
        new_id = ctx.incident[p["proj_id"]]
        full_title = trim(p.get("proj_titulo")) or "(sin título)"
        title = clip(full_title, 200)
        desc = trim(p.get("proj_desc"))
        if len(full_title) > 200:
            desc = f"{full_title}\n\n{desc or ''}".strip()
        rows.append((
            str(new_id), q(clip(p.get("proj_clave"), 50)), q(title),
            q(desc), q(parse_date(p.get("proj_start_date"))),
            q(parse_date(p.get("proj_end_date"))), q(parse_date(p.get("proj_finish_date"))),
            q(INCIDENT_PRIORITY.get(as_int(p.get("proj_prioridad")), "Media")),
            q(INCIDENT_STATUS.get(as_int(p.get("proj_status")), "No Iniciada")),
            str(ctx.incident_category.get(as_int(p.get("proj_categoria")))) if ctx.incident_category.get(as_int(p.get("proj_categoria"))) else "NULL",
            str(ctx.area.get(as_int(p.get("proj_area")))) if ctx.area.get(as_int(p.get("proj_area"))) else "NULL",
            ctx.user_expr(p.get("proj_resp")),
            str(p["proj_id"]),
        ))

    f.add(f"\n-- Incidencias: {len(incidents)} reales + {len(orphan_parents)} placeholder (D12),\n"
          "-- estos ultimos con los ids BAJOS para que el orden descendente los deje al fondo.")
    f.insert_many(
        "adhoc_incidents",
        ("id", "folio", "title", "description", "start_date", "commitment_date",
         "real_date", "priority", "status", "category_id", "area_id",
         "responsible_id", "legacy_id"),
        rows, batch=200,
    )
    f.add("SELECT setval(pg_get_serial_sequence('adhoc_incidents', 'id'), "
          "GREATEST((SELECT COALESCE(MAX(id), 1) FROM adhoc_incidents), 1));")
    ctx.stats["adhoc_incidents"] = len(rows)
    return f


# ---------------------------------------------------------------------------
# 09 — programa
# ---------------------------------------------------------------------------

def step_program(ctx: Ctx) -> SqlFile:
    f = SqlFile(
        "09_program.sql",
        "Eventos del programa de trabajo",
        "Solo 3 eventos reales en el legacy. Los 10 placeholder rescatan 19 tareas\n"
        "programadas cuyo padre ya no existe (D12).",
    )
    events = load("programas")
    rows = []

    # Mismo criterio que incidencias: los placeholder ocupan los ids bajos para
    # que el listado descendente muestre primero los eventos de verdad.
    orphans = sorted({
        as_int(t.get("task_proyecto")) for t in load("tareas_prog")
        if as_int(t.get("task_proyecto"))
        and as_int(t.get("task_proyecto")) not in {p["proj_id"] for p in events}
    })
    for i, legacy in enumerate(orphans, start=1):
        ctx.program[legacy] = i
        rows.append((
            str(i), "NULL",
            q(f"Programa legacy #{legacy} — registro no conservado"),
            q("El registro original fue borrado del sistema legacy. Marcador para "
              "conservar sus tareas y comentarios."),
            "NULL", "NULL", "NULL", q("Media"), q("Completado"), "NULL", "NULL", "NULL",
            str(-legacy),
        ))

    offset = len(orphans)
    for i, p in enumerate(events, start=offset + 1):
        ctx.program[p["proj_id"]] = i
    for p in events:
        new_id = ctx.program[p["proj_id"]]
        rows.append((
            str(new_id), q(clip(p.get("proj_clave"), 50)),
            q(clip(p.get("proj_titulo"), 200) or "(sin título)"), q(trim(p.get("proj_desc"))),
            q(parse_date(p.get("proj_start_date"))), q(parse_date(p.get("proj_end_date"))),
            q(parse_date(p.get("proj_finish_date"))),
            q("Media"), q(PROGRAM_STATUS.get(as_int(p.get("proj_status")), "Planeado")),
            str(ctx.program_category.get(as_int(p.get("proj_categoria")))) if ctx.program_category.get(as_int(p.get("proj_categoria"))) else "NULL",
            str(ctx.area.get(as_int(p.get("proj_area")))) if ctx.area.get(as_int(p.get("proj_area"))) else "NULL",
            ctx.user_expr(p.get("proj_resp")),
            str(p["proj_id"]),
        ))
    f.add(f"\n-- Eventos: {len(events)} reales + {len(orphans)} placeholder (ids bajos).")
    f.insert_many(
        "adhoc_program_events",
        ("id", "folio", "title", "description", "start_date", "commitment_date",
         "real_date", "priority", "status", "category_id", "area_id",
         "responsible_id", "legacy_id"),
        rows,
    )
    f.add("SELECT setval(pg_get_serial_sequence('adhoc_program_events', 'id'), "
          "GREATEST((SELECT COALESCE(MAX(id), 1) FROM adhoc_program_events), 1));")
    ctx.stats["adhoc_program_events"] = len(rows)
    return f


# ---------------------------------------------------------------------------
# 10 — indicadores
# ---------------------------------------------------------------------------

FREQ_MAP = {"MENSUAL": "Mensual", "ANUAL": "Anual", "SEMANAL": "Semanal"}


def step_indicators(ctx: Ctx) -> SqlFile:
    f = SqlFile(
        "10_indicators.sql",
        "Anios, indicadores y celdas de seguimiento",
        "`anios.an_id=3` vale 'AGO-DIC 21', que no es un entero y el destino exige\n"
        "INTEGER UNIQUE: se mapea a 2021 y se fusiona con an_id=2, que ya es 2021.\n"
        "Los 4 umbrales del legacy estan POR PERIODO (12x4 = 48 columnas) y el\n"
        "destino tiene un solo juego por indicador. El plegado es lossy en el\n"
        "esquema pero lossless con estos datos: solo el periodo 1 esta poblado.\n"
        "En los tableros 1,2,3 y 5 los datos estan descolocados (objetivo dice '6',\n"
        "criterios dice 'Anual'): se anotan en notas en vez de ensuciar los campos.\n"
        "`tablero_frecuencia` es varchar (gotcha de tipos).",
    )

    years: dict[int, int] = {}
    rows = []
    next_id = 1
    for a in load("anios"):
        raw = trim(a.get("an_anio")) or ""
        found = re.search(r"(19|20)\d{2}", raw)
        if not found:
            found = re.search(r"(\d{2})\s*$", raw)
            year = 2000 + int(found.group(1)) if found else None
        else:
            year = int(found.group(0))
        if year is None:
            continue
        if year in years.values():
            ctx.year[a["an_id"]] = next(k for k, v in years.items() if v == year)
            continue
        years[next_id] = year
        ctx.year[a["an_id"]] = next_id
        rows.append((str(next_id), str(year)))
        next_id += 1
    f.add(f"\n-- Anios: {len(rows)} de 6 (an_id=3 'AGO-DIC 21' se fusiona con 2021).")
    f.insert_many("adhoc_indicator_years", ("id", "year"), rows)
    f.add("SELECT setval(pg_get_serial_sequence('adhoc_indicator_years', 'id'), "
          "GREATEST((SELECT COALESCE(MAX(id), 1) FROM adhoc_indicator_years), 1));")

    rows, tracking = [], []
    next_id = 1
    for t in load("tableros"):
        year = ctx.year.get(as_int(t.get("tablero_anio")))
        process = ctx.process.get(as_int(t.get("tablero_proceso")))
        if year is None or process is None:
            continue     # year_id y process_id son NOT NULL en el destino
        ctx.indicator[t.get("tablero_id")] = next_id
        freq_raw = norm_name(t.get("tablero_frecuencia") or t.get("tablero_criterios") or "")
        frequency = FREQ_MAP.get(freq_raw)
        rows.append((
            str(next_id), str(year), str(process),
            q(clip(t.get("tablero_objetivo"), 255)),
            q(clip(t.get("tablero_resultados"), 255)),
            q(clip(t.get("tablero_unidad"), 255)),
            q(clip(t.get("tablero_responsable"), 255)),
            q(clip(t.get("tablero_facilitador"), 255)),
            q(clip(t.get("tablero_fuente"), 255)),
            q(frequency),
            q(clip(t.get("tablero_v1d"), 50)), q(clip(t.get("tablero_v1r"), 50)),
            q(clip(t.get("tablero_v1a"), 50)), q(clip(t.get("tablero_v1v"), 50)),
            str(t.get("tablero_id")) if t.get("tablero_id") else "NULL",
        ))
        real = trim(t.get("tablero_v1"))
        if real:
            tracking.append((str(next_id), "0", q(real[:100]), q("blanco")))
        next_id += 1

    f.add(f"\n-- Indicadores: {len(rows)} de 7 (year_id y process_id son NOT NULL).")
    f.insert_many(
        "adhoc_indicators",
        ("id", "year_id", "process_id", "objective", "prev_results", "unit_calc",
         "responsible", "facilitator", "source", "frequency",
         "planned_white", "planned_red", "planned_yellow", "planned_green", "legacy_id"),
        rows,
    )
    f.add("SELECT setval(pg_get_serial_sequence('adhoc_indicators', 'id'), "
          "GREATEST((SELECT COALESCE(MAX(id), 1) FROM adhoc_indicators), 1));")
    if tracking:
        f.add(f"\n-- Seguimiento: {len(tracking)} celdas con dato real (solo el periodo 1).")
        f.insert_many("adhoc_indicator_trackings",
                      ("indicator_id", "period_index", "real_value", "color"), tracking)
    ctx.stats["adhoc_indicator_years"] = len(years)
    ctx.stats["adhoc_indicators"] = len(rows)
    ctx.stats["adhoc_indicator_trackings"] = len(tracking)
    return f
