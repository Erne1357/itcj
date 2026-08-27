"""Extrae el legacy `ControlDocumental` (SQL Server) a JSON crudo.

Fase F3 del ETL de Calidad (ver docs/superpowers/specs/2026-08-27-adhoc-etl-legacy-design.md).
Este paso NO transforma nada: saca los datos tal cual para que el resto del
pipeline trabaje sobre archivos, sin depender de que el contenedor siga arriba.

Por que via `sqlcmd -o` + `docker cp` y no por stdout:
`ver_doctos` son 30 541 filas y su JSON pesa ~2 MB. Pasar eso por el stdout de
`docker exec` lo trunca y lo re-codifica segun la consola de Windows. Escribir
dentro del contenedor y copiar el archivo evita las dos cosas.

Gotchas de sqlcmd aprendidos a golpes:
- `-y 0` (sin limite de ancho) es INCOMPATIBLE con `-h -1` y con `-W`. Hay que
  usar `-y 0` solo y limpiar el encabezado a mano.
- `FOR JSON PATH` omite las columnas NULL salvo que se pida
  `INCLUDE_NULL_VALUES`. Sin eso, una fila con `area = NULL` simplemente no
  trae la llave `area` y el transform revienta con KeyError.
- Las columnas `text` (tipo obsoleto) no aceptan `LEFT()` ni `LTRIM()` sin un
  `CAST(... AS varchar(max))` previo.

Uso:
    python scripts/adhoc_etl/extract.py                 # todas las tablas
    python scripts/adhoc_etl/extract.py usuarios areas  # solo algunas
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

CONTAINER = "sqlserver_db"
DATABASE = "ControlDocumental"
SQLCMD = "/opt/mssql-tools18/bin/sqlcmd"
# Credencial del contenedor local de analisis, no de un sistema real.
SA_PASSWORD = "TuPasswordSegura123!"

OUT_DIR = Path(__file__).resolve().parents[2] / "build" / "adhoc_legacy"

# Nota sobre TRIM: varias columnas del legacy traen espacio final y el destino
# las mete en columnas UNIQUE (`adhoc_areas.name`, `adhoc_processes.name`).
# Se limpia aqui, en la extraccion, para que el transform no tenga que
# acordarse de hacerlo en cada uso.
TABLES: dict[str, str] = {
    # --- identidades y estructura ---
    "usuarios": """
        SELECT id_usuario, LTRIM(RTRIM(username)) AS username,
               LTRIM(RTRIM(nombre)) AS nombre, LTRIM(RTRIM(apellidos)) AS apellidos,
               LTRIM(RTRIM(extra)) AS email, activo, nivel, [level],
               LTRIM(RTRIM(area)) AS area, LTRIM(RTRIM(puesto)) AS puesto,
               ac_docs, ac_inci, ac_repo, f_registro
        FROM usuarios
    """,
    "areas": "SELECT id_area, LTRIM(RTRIM(nom_area)) AS nom_area, responsable FROM areas",
    "procesos": """
        SELECT id_proceso, LTRIM(RTRIM(proc_nom)) AS proc_nom, proc_color
        FROM procesos
    """,
    # --- catalogos ---
    "doctypes": "SELECT dt_id, LTRIM(RTRIM(dt_name)) AS dt_name FROM doctypes",
    "docclass": "SELECT dc_id, LTRIM(RTRIM(dc_name)) AS dc_name FROM docclass",
    "incitypes": "SELECT it_id, LTRIM(RTRIM(it_name)) AS it_name FROM incitypes",
    "progtypes": "SELECT pt_id, LTRIM(RTRIM(pt_name)) AS pt_name FROM progtypes",
    "anios": "SELECT an_id, LTRIM(RTRIM(an_anio)) AS an_anio FROM anios",
    "tablero_frecuencias": "SELECT tfrec_id, LTRIM(RTRIM(tfrec_nombre)) AS tfrec_nombre FROM tablero_frecuencias",
    # --- documentos y flujo ---
    "doc_approve": """
        SELECT dap_id, LTRIM(RTRIM(dap_clave)) AS dap_clave,
               LTRIM(RTRIM(dap_titulo)) AS dap_titulo, dap_area, dap_proceso,
               LTRIM(RTRIM(dap_tipo)) AS dap_tipo, dap_clase, dap_categoria,
               dap_status, dap_approval_status, dap_parent,
               LTRIM(RTRIM(dap_documento)) AS dap_documento,
               dap_start_ver, dap_start_date, dap_end_date, dap_vigencia,
               CAST(dap_desc AS varchar(max)) AS dap_desc
        FROM doc_approve
    """,
    "rutas_apro": "SELECT ruta_id, LTRIM(RTRIM(ruta_nombre)) AS ruta_nombre FROM rutas_apro",
    "appr_steps_config": """
        SELECT as_id, LTRIM(RTRIM(as_name)) AS as_name, as_docto, as_ordenar, as_limit
        FROM appr_steps_config
    """,
    "appr_usrs": "SELECT au_id, au_user, au_docto, au_step FROM appr_usrs",
    "appr_usrs_boss": "SELECT au_id, au_user, au_docto, au_step FROM appr_usrs_boss",
    "doc_route": "SELECT dr_id, dr_docid, dr_routeid, dr_startdate FROM doc_route",
    "indiceprin": """
        SELECT accion_id, a_user, a_docto, a_tarea, a_prog, a_parent, a_type,
               a_done, a_done_date, a_start_date, a_end_date, a_appr, a_resp,
               a_doc_noti, a_acuse
        FROM indiceprin
    """,
    "ver_doctos": "SELECT vd_id, vd_docto, vd_user FROM ver_doctos",
    "doc_com": """
        SELECT tc_llave, tc_tarea, CAST(tc_comentario AS varchar(max)) AS tc_comentario,
               tc_user, tc_fecha, tc_action
        FROM doc_com
    """,
    # --- incidencias y tareas ---
    "proyectos": """
        SELECT proj_id, LTRIM(RTRIM(proj_clave)) AS proj_clave,
               LTRIM(RTRIM(proj_titulo)) AS proj_titulo, proj_area, proj_prioridad,
               proj_start_date, proj_end_date, proj_finish_date, proj_status,
               proj_grupo, proj_categoria, proj_resp,
               CAST(proj_desc AS varchar(max)) AS proj_desc
        FROM proyectos
    """,
    "tareas": """
        SELECT task_id, LTRIM(RTRIM(task_name)) AS task_name, task_resp, task_solicit,
               task_status, task_orden, task_proyecto,
               task_start_date, task_end_date, task_real_date
        FROM tareas
    """,
    "tareas_usrs": "SELECT tu_id, tu_task, tu_usr FROM tareas_usrs",
    "tareas_admins": "SELECT tu_id, tu_task, tu_usr FROM tareas_admins",
    "tareas_com": """
        SELECT tc_llave, tc_tarea, CAST(tc_comentario AS varchar(max)) AS tc_comentario,
               tc_user, tc_fecha, tc_action
        FROM tareas_com
    """,
    "tareas_doc": """
        SELECT td_llave, td_tarea, LTRIM(RTRIM(td_doc)) AS td_doc,
               LTRIM(RTRIM(td_nombre)) AS td_nombre, td_user
        FROM tareas_doc
    """,
    "inci_files": """
        SELECT inf_id, inf_inci, LTRIM(RTRIM(inf_file)) AS inf_file,
               LTRIM(RTRIM(inf_name)) AS inf_name
        FROM inci_files
    """,
    # --- programa ---
    "programas": """
        SELECT proj_id, LTRIM(RTRIM(proj_clave)) AS proj_clave,
               LTRIM(RTRIM(proj_titulo)) AS proj_titulo, proj_area, proj_prioridad,
               proj_start_date, proj_end_date, proj_finish_date, proj_status,
               proj_categoria, proj_resp, CAST(proj_desc AS varchar(max)) AS proj_desc
        FROM programas
    """,
    "tareas_prog": """
        SELECT task_id, LTRIM(RTRIM(task_name)) AS task_name, task_resp, task_solicit,
               task_status, task_orden, task_proyecto,
               task_start_date, task_end_date, task_real_date
        FROM tareas_prog
    """,
    "tareas_prog_usrs": "SELECT tu_id, tu_task, tu_usr FROM tareas_prog_usrs",
    "tareas_prog_admins": "SELECT tu_id, tu_task, tu_usr FROM tareas_prog_admins",
    "tareas_prog_com": """
        SELECT tc_llave, tc_tarea, CAST(tc_comentario AS varchar(max)) AS tc_comentario,
               tc_user, tc_fecha, tc_action
        FROM tareas_prog_com
    """,
    "tareas_prog_doc": """
        SELECT td_llave, td_tarea, LTRIM(RTRIM(td_doc)) AS td_doc,
               LTRIM(RTRIM(td_nombre)) AS td_nombre, td_user
        FROM tareas_prog_doc
    """,
    "prog_files": """
        SELECT inf_id, inf_inci, LTRIM(RTRIM(inf_file)) AS inf_file,
               LTRIM(RTRIM(inf_name)) AS inf_name
        FROM prog_files
    """,
    # --- indicadores ---
    # `tableros` tiene ~75 columnas (v1..v12 x 5 variantes). SELECT * a proposito:
    # el transform decide que hacer con cada una y no queremos mantener la lista
    # a mano en dos lugares.
    "tableros": "SELECT * FROM tableros",
}


def run_extract(table: str, select_sql: str) -> list[dict]:
    """Ejecuta el SELECT como JSON dentro del contenedor y devuelve las filas."""
    remote = f"/tmp/adhoc_extract_{table}.json"
    query = (
        "SET NOCOUNT ON; "
        f"{' '.join(select_sql.split())} "
        "FOR JSON PATH, INCLUDE_NULL_VALUES"
    )

    subprocess.run(
        [
            "docker", "exec", CONTAINER, SQLCMD,
            "-S", "localhost", "-U", "sa", "-P", SA_PASSWORD, "-C",
            "-d", DATABASE,
            "-y", "0",          # sin limite de ancho; incompatible con -h -1 y -W
            "-Q", query,
            "-o", remote,
        ],
        check=True,
        capture_output=True,
    )

    local = OUT_DIR / f"{table}.json"
    subprocess.run(
        ["docker", "cp", f"{CONTAINER}:{remote}", str(local)],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["docker", "exec", CONTAINER, "rm", "-f", remote],
        check=False,
        capture_output=True,
    )

    raw = local.read_text(encoding="utf-8-sig")
    # sqlcmd antepone el nombre autogenerado de la columna JSON y una linea de
    # guiones. Ninguno de los dos es parte del documento.
    body = "".join(
        line for line in raw.splitlines()
        if not line.startswith("JSON_F52E2B61") and not set(line.strip()) <= {"-"}
    ).strip()

    rows = json.loads(body) if body else []
    local.write_text(
        json.dumps(rows, ensure_ascii=False, indent=1, default=str),
        encoding="utf-8",
    )
    return rows


def main(argv: list[str]) -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    wanted = argv[1:] or list(TABLES)

    unknown = [t for t in wanted if t not in TABLES]
    if unknown:
        print(f"Tablas desconocidas: {', '.join(unknown)}", file=sys.stderr)
        return 2

    manifest: dict[str, int] = {}
    for table in wanted:
        try:
            rows = run_extract(table, TABLES[table])
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or b"").decode("utf-8", "replace").strip()
            print(f"  {table:<22} FALLO: {detail[:200]}", file=sys.stderr)
            return 1
        manifest[table] = len(rows)
        print(f"  {table:<22} {len(rows):>6} filas")

    (OUT_DIR / "_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(f"\n{len(manifest)} tablas -> {OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
