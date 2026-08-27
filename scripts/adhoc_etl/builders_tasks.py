"""Pasos 11-13 y 99 del import: tareas, comentarios, archivos, aprobaciones y verificación."""
from __future__ import annotations

import json
import mimetypes
from collections import defaultdict

from builders_content import secure_name
from transform import (
    DATA, SqlFile, Ctx, as_int, clip, load, parse_date, parse_dt, q, trim,
)

TASK_PENDING, TASK_IN_REVIEW = "Pendiente", "En Revisión"
TASK_WAITING, TASK_COMPLETED, TASK_REJECTED = "En Espera", "Completada", "Rechazada"


# ---------------------------------------------------------------------------
# 11 — tareas
# ---------------------------------------------------------------------------

def _task_status(row: dict) -> tuple[str, object]:
    """Estatus de una tarea de incidencia o programa.

    El legacy solo tiene '0' y '1' (y como TEXTO, gotcha de tipos). 160 tareas
    con estatus 0 SI tienen fecha real, y 132 de ellas pertenecen a incidencias
    ya cerradas: se toman como completadas, no como pendientes eternas.
    """
    done = parse_dt(row.get("task_real_date"))
    if as_int(row.get("task_status")) == 1 or done:
        return TASK_COMPLETED, done
    return TASK_PENDING, None


def step_tasks(ctx: Ctx) -> SqlFile:
    f = SqlFile(
        "11_tasks.sql",
        "Tareas de los tres origenes y sus asignados",
        "adhoc_tasks.legacy_id va prefijado porque las tareas vienen de TRES tablas\n"
        "cuyos espacios de id se solapan: t: (tareas), tp: (tareas_prog) e ip:\n"
        "(indiceprin, pasos de aprobacion documental).\n"
        "`task_resp` (481/481 poblada) entra como asignado: sin ella 393 de las 481\n"
        "tareas quedarian sin nadie, porque tareas_usrs solo cubre 33.\n"
        "`task_solicit` es el solicitante -> created_by_id (difiere de task_resp en\n"
        "198 filas, o sea es dato propio).\n"
        "`indiceprin.a_done` esta INVERTIDO: 1 = pendiente, 0 = ejecutada.",
    )

    rows: list[tuple] = []
    assignees: dict[tuple[str, int], bool] = {}
    next_id = 1

    def add_task(legacy_key: str, description: str, status: str, completed,
                 start, due, created_by, parent_col: str, parent_id: int,
                 flow_step: int | None = None, priority: str = "Media") -> int:
        nonlocal next_id
        ctx.task[legacy_key] = next_id
        rows.append((
            str(next_id), q(clip(description, 255) or "(sin descripción)"),
            q(status), q(priority), q(start), q(due), q(completed),
            created_by,
            str(parent_id) if parent_col == "incident_id" else "NULL",
            str(parent_id) if parent_col == "program_id" else "NULL",
            str(parent_id) if parent_col == "document_id" else "NULL",
            str(flow_step) if flow_step else "NULL",
            q(legacy_key),
        ))
        next_id += 1
        return next_id - 1

    # --- incidencias -----------------------------------------------------
    for t in load("tareas"):
        parent = ctx.incident.get(as_int(t.get("task_proyecto")))
        if not parent:
            continue
        status, completed = _task_status(t)
        key = f"t:{t['task_id']}"
        add_task(key, t.get("task_name"), status, completed,
                 parse_date(t.get("task_start_date")), parse_date(t.get("task_end_date")),
                 ctx.user_expr(t.get("task_solicit")), "incident_id", parent)
        for source in ("task_resp",):
            user = as_int(t.get(source))
            if user in ctx.users:
                assignees.setdefault((key, user), False)

    # --- programa --------------------------------------------------------
    for t in load("tareas_prog"):
        parent = ctx.program.get(as_int(t.get("task_proyecto")))
        if not parent:
            continue
        status, completed = _task_status(t)
        key = f"tp:{t['task_id']}"
        add_task(key, t.get("task_name"), status, completed,
                 parse_date(t.get("task_start_date")), parse_date(t.get("task_end_date")),
                 ctx.user_expr(t.get("task_solicit")), "program_id", parent)
        user = as_int(t.get("task_resp"))
        if user in ctx.users:
            assignees.setdefault((key, user), False)

    # --- pasos de aprobacion documental ----------------------------------
    titles = {ctx.document[d["dap_id"]]: trim(d.get("dap_titulo"))
              for d in load("doc_approve") if d["dap_id"] in ctx.document}
    step_names = {ctx.step[s["as_id"]]: trim(s.get("as_name"))
                  for s in load("appr_steps_config") if s["as_id"] in ctx.step}
    for r in load("indiceprin"):
        if r.get("a_type") not in ("D", "DS"):
            continue
        doc = ctx.document.get(as_int(r.get("a_docto")))
        if not doc:
            continue
        step = ctx.step.get(as_int(r.get("a_prog")))
        done_at = parse_dt(r.get("a_done_date"))
        if (r.get("a_appr") or "").strip().upper() == "N":
            status, completed = TASK_REJECTED, None
        elif done_at:
            status, completed = TASK_COMPLETED, done_at
        else:
            status, completed = TASK_IN_REVIEW, None
        key = f"ip:{r['accion_id']}"
        add_task(
            key,
            f"Aprobar Documento: {titles.get(doc) or doc} "
            f"(Paso: {step_names.get(step) or 'sin paso'})",
            status, completed,
            parse_date(r.get("a_start_date")), parse_date(r.get("a_end_date")),
            ctx.user_expr(r.get("a_resp")), "document_id", doc,
            flow_step=step, priority="Alta",
        )
        user = as_int(r.get("a_user"))
        if user in ctx.users:
            assignees.setdefault((key, user), False)

    f.add(f"\n-- Tareas: {len(rows)}. El CheckConstraint exige EXACTAMENTE un padre.")
    f.insert_many(
        "adhoc_tasks",
        ("id", "description", "status", "priority", "start_date", "due_date",
         "completed_at", "created_by_id", "incident_id", "program_id",
         "document_id", "flow_step_id", "legacy_id"),
        rows, batch=200,
    )
    f.add("SELECT setval(pg_get_serial_sequence('adhoc_tasks', 'id'), "
          "GREATEST((SELECT COALESCE(MAX(id), 1) FROM adhoc_tasks), 1));")

    # Asignados adicionales de las tablas puente.
    for table, prefix in (("tareas_usrs", "t"), ("tareas_admins", "t"),
                          ("tareas_prog_usrs", "tp"), ("tareas_prog_admins", "tp")):
        for r in load(table):
            key = f"{prefix}:{as_int(r.get('tu_task'))}"
            user = as_int(r.get("tu_usr"))
            if key in ctx.task and user in ctx.users:
                assignees.setdefault((key, user), False)

    pairs = [(ctx.task[key], user) for (key, user) in assignees if key in ctx.task]
    if pairs:
        f.add(f"\n-- Asignados: {len(pairs)} pares.")
        f.add(
            "INSERT INTO adhoc_task_assignees (task_id, user_id)\n"
            "SELECT v.task_id, m.user_id\n"
            "FROM (VALUES\n  "
            + ",\n  ".join(f"({tid}, {uid})" for tid, uid in sorted(set(pairs)))
            + "\n) AS v(task_id, legacy_id)\n"
            "JOIN _adhoc_user_map m ON m.legacy_id = v.legacy_id\n"
            "ON CONFLICT DO NOTHING;"
        )
    ctx.stats["adhoc_tasks"] = len(rows)
    ctx.stats["adhoc_task_assignees"] = len(set(pairs))
    return f


# ---------------------------------------------------------------------------
# 12 — comentarios y archivos
# ---------------------------------------------------------------------------

def step_comments_and_files(ctx: Ctx, file_plan: list[dict]) -> SqlFile:
    f = SqlFile(
        "12_comments_and_files.sql",
        "Comentarios de tarea y adjuntos",
        "`doc_com` (2297 filas) faltaba por completo del censo original: es el texto\n"
        "que el aprobador escribio en cada paso del flujo documental. `tc_action`\n"
        "apunta a `indiceprin.accion_id`, la misma llave con la que se crean las\n"
        "tareas ip:.\n"
        "`tareas_doc.td_tarea` apunta al COMENTARIO, no a la tarea (522/522 resuelven\n"
        "contra tc_llave y solo 264 contra task_id, que es solape de rango). El\n"
        "analisis previo se equivocaba: si se hace ese join, 522 adjuntos cuelgan de\n"
        "tareas ajenas.\n"
        "file_path NULL = el binario ya no esta en el servidor del proveedor.\n"
        "NO entran los 995 comentarios de doc_com que cuelgan de una accion de ACUSE\n"
        "(a_type NULL) en vez de un paso de aprobacion: no son comentarios de tarea y\n"
        "ademas son ruido puro. 856 de los 995 dicen literalmente 'Enterado sin\n"
        "comentario.', solo hay 17 textos distintos y apenas 2 tienen contenido real.\n"
        "El acuse en si ya es la evidencia; el texto no agrega nada.",
    )

    rows: list[tuple] = []
    next_id = 1
    for table, prefix, task_col in (("tareas_com", "t", "tc_tarea"),
                                    ("tareas_prog_com", "tp", "tc_tarea"),
                                    ("doc_com", "ip", "tc_action")):
        for c in load(table):
            key = f"{prefix}:{as_int(c.get(task_col))}"
            task = ctx.task.get(key)
            user = as_int(c.get("tc_user"))
            if not task:
                continue
            text = trim(c.get("tc_comentario")) or "(sin texto — migrado del legacy)"
            ctx.comment[f"{table}:{c['tc_llave']}"] = next_id
            rows.append((
                str(next_id), str(task),
                ctx.user_expr_required(user),
                q(text), q(parse_dt(c.get("tc_fecha"))),
            ))
            next_id += 1

    f.add(f"\n-- Comentarios: {len(rows)}. user_id es NOT NULL: los de autor\n"
          "-- irresoluble cuelgan del usuario tecnico en vez de perderse (y una tarea\n"
          "-- sin ningun comentario queda bloqueada en task_workflow_service.py:99-103).")
    f.insert_many(
        "adhoc_task_comments", ("id", "task_id", "user_id", "comment", "created_at"),
        rows, batch=200,
    )
    f.add("SELECT setval(pg_get_serial_sequence('adhoc_task_comments', 'id'), "
          "GREATEST((SELECT COALESCE(MAX(id), 1) FROM adhoc_task_comments), 1));")
    ctx.stats["adhoc_task_comments"] = len(rows)

    # ---- archivos -------------------------------------------------------
    manifest_path = DATA / "_files_manifest.json"
    downloaded = {}
    if manifest_path.exists():
        for entry in json.loads(manifest_path.read_text(encoding="utf-8")):
            downloaded[(entry["source"], entry["row_id"])] = entry

    def plan(kind: str, entity_id: int, entry: dict | None, name: str):
        if not entry or not entry.get("saved"):
            return "NULL", "NULL", "NULL"
        safe = secure_name(name)
        file_plan.append({"src": str(DATA.parent.parent / entry["saved"]), "kind": kind,
                          "entity_id": entity_id, "name": safe})
        mime = mimetypes.guess_type(name)[0]
        return q(f"{entity_id}/{safe}"), q(mime), str(entry["bytes"])

    inci_rows = []
    for r in load("inci_files"):
        incident = ctx.incident.get(as_int(r.get("inf_inci")))
        name = trim(r.get("inf_file"))
        if not incident or not name:
            continue
        path, mime, size = plan("incidents", incident, downloaded.get(("inci_files", r["inf_id"])), name)
        inci_rows.append((str(incident), path, q(clip(r.get("inf_name") or name, 255)), mime, size))
    f.add(f"\n-- Archivos de incidencia: {len(inci_rows)}")
    f.insert_many("adhoc_incident_files",
                  ("incident_id", "file_path", "original_name", "mime_type", "size_bytes"),
                  inci_rows, batch=200)
    ctx.stats["adhoc_incident_files"] = len(inci_rows)

    comment_rows = []
    for table, source in (("tareas_com", "tareas_doc"), ("tareas_prog_com", "tareas_prog_doc")):
        for r in load(source):
            comment = ctx.comment.get(f"{table}:{as_int(r.get('td_tarea'))}")
            name = trim(r.get("td_doc"))
            if not comment or not name:
                continue
            path, mime, size = plan("task_comments", comment, downloaded.get((source, r["td_llave"])), name)
            comment_rows.append((
                str(comment), path, q(clip(r.get("td_nombre") or name, 255)), mime, size,
                ctx.user_expr(r.get("td_user")),
            ))
    f.add(f"\n-- Adjuntos de comentario: {len(comment_rows)}")
    f.insert_many("adhoc_task_comment_files",
                  ("task_comment_id", "file_path", "original_name", "mime_type",
                   "size_bytes", "uploaded_by_id"),
                  comment_rows, batch=200)
    ctx.stats["adhoc_task_comment_files"] = len(comment_rows)

    prog_rows = []
    for r in load("prog_files"):
        event = ctx.program.get(as_int(r.get("inf_inci")))
        name = trim(r.get("inf_file"))
        if not event or not name:
            continue
        path, mime, size = plan("program_events", event, downloaded.get(("prog_files", r["inf_id"])), name)
        prog_rows.append((str(event), path, q(clip(r.get("inf_name") or name, 255)), mime, size))
    f.add(f"\n-- Archivos de evento de programa: {len(prog_rows)}")
    f.insert_many("adhoc_program_event_files",
                  ("event_id", "file_path", "original_name", "mime_type", "size_bytes"),
                  prog_rows)
    ctx.stats["adhoc_program_event_files"] = len(prog_rows)
    return f


# ---------------------------------------------------------------------------
# 13 — aprobaciones
# ---------------------------------------------------------------------------

def step_approvals(ctx: Ctx) -> SqlFile:
    f = SqlFile(
        "13_task_approvals.sql",
        "Decisiones de aprobacion del flujo documental",
        "Va DESPUES de los comentarios: comment_id es FK a adhoc_task_comments.\n"
        "No se infiere ninguna decision. Se transcribe la que quedo escrita:\n"
        "  a_appr = 'N'                      -> rechazado (9 casos ciertos)\n"
        "  paso ejecutado CON comentario     -> aprobado, con el comentario que lo\n"
        "                                       respalda ('Perfecto. Aprobado.',\n"
        "                                       'OK, el documento cuenta con todo')\n"
        "  paso ejecutado SIN comentario     -> sin fila; no hay nada que transcribir",
    )

    comment_by_action: dict[int, int] = {}
    for c in load("doc_com"):
        action = as_int(c.get("tc_action"))
        cid = ctx.comment.get(f"doc_com:{c['tc_llave']}")
        if action and cid and action not in comment_by_action:
            comment_by_action[action] = cid

    rows = []
    for r in load("indiceprin"):
        if r.get("a_type") not in ("D", "DS"):
            continue
        task = ctx.task.get(f"ip:{r['accion_id']}")
        user = as_int(r.get("a_user"))
        if not task or user not in ctx.users:
            continue
        comment = comment_by_action.get(r["accion_id"])
        if (r.get("a_appr") or "").strip().upper() == "N":
            decision = "rechazado"
        elif parse_dt(r.get("a_done_date")) and comment:
            decision = "aprobado"
        else:
            continue
        rows.append((str(task), str(user), q(decision),
                     str(comment) if comment else "NULL",
                     q(parse_dt(r.get("a_done_date")))))
    if rows:
        f.add(f"\n-- Aprobaciones: {len(rows)}")
        f.add(
            "INSERT INTO adhoc_task_approvals (task_id, user_id, decision, comment_id, created_at)\n"
            "SELECT v.task_id, m.user_id, v.decision, v.comment_id, "
            "COALESCE(v.created_at::timestamp, now())\n"
            "FROM (VALUES\n  "
            + ",\n  ".join(
                f"({t}, {u}, {d}, {c}, {ts})" for t, u, d, c, ts in rows
            )
            + "\n) AS v(task_id, legacy_id, decision, comment_id, created_at)\n"
            "JOIN _adhoc_user_map m ON m.legacy_id = v.legacy_id\n"
            "ON CONFLICT DO NOTHING;"
        )
    ctx.stats["adhoc_task_approvals"] = len(rows)
    return f


# ---------------------------------------------------------------------------
# 99 — verificación
# ---------------------------------------------------------------------------

SEQUENCE_TABLES = [
    "adhoc_areas", "adhoc_processes", "adhoc_document_categories",
    "adhoc_document_classifications", "adhoc_approval_flows",
    "adhoc_approval_flow_steps", "adhoc_documents", "adhoc_incident_categories",
    "adhoc_incidents", "adhoc_program_categories", "adhoc_program_events",
    "adhoc_indicator_years", "adhoc_indicators", "adhoc_tasks", "adhoc_task_comments",
]


def step_verify(ctx: Ctx) -> SqlFile:
    f = SqlFile(
        "99_verify.sql",
        "Verificacion: aborta el import si algo no cuadra",
        "No es opcional. Si un conteo no coincide o un invariante se rompe, la\n"
        "transaccion entera se revierte y no queda media migracion en la base.\n"
        "El chequeo de secuencias es el que mas importa: en dev estan quemadas muy\n"
        "por encima del volumen del ETL, asi que un setval olvidado pasa inadvertido\n"
        "aqui y revienta en el primer alta de produccion.",
    )
    checks = "\n".join(
        f"    ('{table}', {count})," for table, count in sorted(ctx.stats.items())
        if table.startswith("adhoc_")
    ).rstrip(",")

    f.add(f"""DO $$
DECLARE
    r          RECORD;
    v_actual   BIGINT;
    v_problems TEXT := '';
BEGIN
    -- 1. Conteos por tabla contra lo que el transform calculo.
    FOR r IN SELECT * FROM (VALUES
{checks}
    ) AS t(tabla, esperado) LOOP
        EXECUTE format('SELECT count(*) FROM %I', r.tabla) INTO v_actual;
        IF v_actual <> r.esperado THEN
            v_problems := v_problems || format(
                E'\\n  %s: esperaba %s filas, hay %s', r.tabla, r.esperado, v_actual);
        END IF;
    END LOOP;

    -- 2. Toda secuencia por encima del MAX(id): si no, el primer alta choca.
    FOR r IN SELECT * FROM (VALUES
{chr(10).join(f"        ('{t}')," for t in SEQUENCE_TABLES).rstrip(',')}
    ) AS t(tabla) LOOP
        -- %s y no %I para la secuencia: pg_get_serial_sequence ya devuelve el
        -- nombre calificado y citado ('public.adhoc_areas_id_seq'), asi que %I
        -- lo entrecomillaria entero como un solo identificador inexistente.
        EXECUTE format(
            'SELECT (SELECT last_value FROM %s) - (SELECT COALESCE(MAX(id),0) FROM %I)',
            pg_get_serial_sequence(r.tabla, 'id'), r.tabla) INTO v_actual;
        IF v_actual < 0 THEN
            v_problems := v_problems || format(
                E'\\n  %s: la secuencia quedo por DEBAJO del max(id)', r.tabla);
        END IF;
    END LOOP;

    -- 3. Ninguna cadena de version puede tener dos puntas.
    SELECT count(*) INTO v_actual FROM (
        SELECT parent_id FROM adhoc_documents
        WHERE parent_id IS NOT NULL AND is_current
        GROUP BY parent_id HAVING count(*) > 1
    ) x;
    IF v_actual > 0 THEN
        v_problems := v_problems || format(
            E'\\n  adhoc_documents: %s cadenas con mas de una version vigente', v_actual);
    END IF;

    -- 4. Todo acuse tiene fecha (la columna es NOT NULL, esto es cinturon).
    SELECT count(*) INTO v_actual
    FROM adhoc_document_acknowledgements WHERE acknowledged_at IS NULL;
    IF v_actual > 0 THEN
        v_problems := v_problems || format(
            E'\\n  adhoc_document_acknowledgements: %s sin fecha', v_actual);
    END IF;

    -- 5. Ninguna tarea con cero o dos padres (lo cubre el CheckConstraint, pero
    --    un fallo aqui da un mensaje legible en vez de un error de constraint).
    SELECT count(*) INTO v_actual FROM adhoc_tasks
    WHERE (incident_id IS NOT NULL)::int + (program_id IS NOT NULL)::int
        + (document_id IS NOT NULL)::int <> 1;
    IF v_actual > 0 THEN
        v_problems := v_problems || format(
            E'\\n  adhoc_tasks: %s sin exactamente un padre', v_actual);
    END IF;

    IF v_problems <> '' THEN
        RAISE EXCEPTION E'El import no cuadra:%s', v_problems;
    END IF;

    RAISE NOTICE 'Import del SGC legacy verificado: todos los conteos e invariantes cuadran.';
END $$;""")
    return f
