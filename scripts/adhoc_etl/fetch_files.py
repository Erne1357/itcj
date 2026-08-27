"""Descarga los adjuntos del sistema legacy de Calidad (`calidad.com.mx/itcj`).

Fase F6 del ETL. Los binarios de incidencias y programa NO vinieron en el
respaldo que nos pasaron: de ~870 nombres solo 8 estan en el volcado local, y
esos 8 son documentos del SGC con nombre coincidente. Siguen vivos en el
servidor del proveedor y responden sin sesion.

## Layout del legacy (confirmado con URLs reales del sistema en vivo)

Tres carpetas raiz, una por MODULO — no una por tabla:

    inci_doctos/   -> inci_files  Y  tareas_doc        (incidencias)
    prog_doctos/   -> prog_files  Y  tareas_prog_doc   (programa)
    documentos/    -> doc_approve                      (ya en volcado local)

Y dentro de cada raiz el archivo puede estar en DOS formas, que conviven:

    {raiz}/{id_padre}/{archivo}     anidado
    {raiz}/{archivo}                plano

Es el mismo trabajo a medias que se ve en el volcado local de `documentos/`
(17 subcarpetas vacias y una, la 796, con el archivo que tambien esta en la
raiz): el proveedor empezo a mover todo a subcarpetas por id y lo dejo asi.
Por eso la regla es intentar anidado y caer a plano. Dos candidatas
deterministas por archivo.

## Trampa importante

El servidor responde **200 con el HTML del login** cuando la ruta no existe
(`/itcj/` -> 200 pero es `login.php?info=DENIED`). Sin detectarlo, guardariamos
931 copias del login creyendo que son documentos. Se valida content-type y se
descarta cualquier `text/html`.

Uso:
    python scripts/adhoc_etl/fetch_files.py            # todo
    python scripts/adhoc_etl/fetch_files.py --limit 5  # piloto
    python scripts/adhoc_etl/fetch_files.py --retry    # solo los que fallaron
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "build" / "adhoc_legacy"
FILES_DIR = ROOT / "build" / "adhoc_legacy_files"
MANIFEST = DATA_DIR / "_files_manifest.json"

BASE = "https://calidad.com.mx/itcj"
USER_AGENT = "ITCJ-adhoc-migration/1.0 (+migracion interna del SGC)"
TIMEOUT = 60
WORKERS = 4
DELAY = 0.25          # cortesia con el servidor del proveedor
MAX_HTML_SNIFF = 512


def load(table: str) -> list[dict]:
    return json.loads((DATA_DIR / f"{table}.json").read_text(encoding="utf-8"))


def build_worklist() -> list[dict]:
    """Cada fila de adjunto con su carpeta raiz y el id de su padre.

    Para los adjuntos de comentario hay que subir dos saltos, porque
    `td_tarea` NO apunta a la tarea sino al comentario (el analisis previo se
    equivocaba en esto: 522/522 resuelven contra `tareas_com.tc_llave`, solo
    264/522 contra `tareas.task_id`, y esos son solape de rango).
    """
    work: list[dict] = []

    # --- incidencias: archivo directo de la incidencia ---
    for row in load("inci_files"):
        if not row.get("inf_file"):
            continue
        work.append({
            "source": "inci_files", "row_id": row["inf_id"],
            "parent_id": row.get("inf_inci"), "root": "inci_doctos",
            "filename": row["inf_file"], "original_name": row.get("inf_name"),
        })

    # --- incidencias: adjunto de comentario de tarea ---
    task_of_comment = {c["tc_llave"]: c.get("tc_tarea") for c in load("tareas_com")}
    incident_of_task = {t["task_id"]: t.get("task_proyecto") for t in load("tareas")}
    for row in load("tareas_doc"):
        if not row.get("td_doc"):
            continue
        task_id = task_of_comment.get(row["td_tarea"])
        work.append({
            "source": "tareas_doc", "row_id": row["td_llave"],
            "parent_id": incident_of_task.get(task_id), "root": "inci_doctos",
            "filename": row["td_doc"], "original_name": row.get("td_nombre"),
        })

    # --- programa: archivo directo del programa ---
    for row in load("prog_files"):
        if not row.get("inf_file"):
            continue
        work.append({
            "source": "prog_files", "row_id": row["inf_id"],
            "parent_id": row.get("inf_inci"), "root": "prog_doctos",
            "filename": row["inf_file"], "original_name": row.get("inf_name"),
        })

    # --- programa: adjunto de comentario de tarea programada ---
    ptask_of_comment = {c["tc_llave"]: c.get("tc_tarea") for c in load("tareas_prog_com")}
    program_of_task = {t["task_id"]: t.get("task_proyecto") for t in load("tareas_prog")}
    for row in load("tareas_prog_doc"):
        if not row.get("td_doc"):
            continue
        task_id = ptask_of_comment.get(row["td_tarea"])
        work.append({
            "source": "tareas_prog_doc", "row_id": row["td_llave"],
            "parent_id": program_of_task.get(task_id), "root": "prog_doctos",
            "filename": row["td_doc"], "original_name": row.get("td_nombre"),
        })

    return work


def candidate_urls(item: dict) -> list[tuple[str, str]]:
    """(forma, url) en orden de preferencia: anidado y luego plano."""
    name = urllib.parse.quote(item["filename"], safe="")
    urls = []
    parent = item.get("parent_id")
    # Los ids basura tipo timestamp de `inci_files` (911640066, 1585109814...)
    # son subidas hechas antes de guardar la incidencia: no hay carpeta que
    # buscar, solo aplica la forma plana.
    if isinstance(parent, int) and 0 < parent < 100000:
        urls.append(("nested", f"{BASE}/{item['root']}/{parent}/{name}"))
    urls.append(("flat", f"{BASE}/{item['root']}/{name}"))
    return urls


def fetch(url: str) -> tuple[int, bytes, str]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return response.status, response.read(), response.headers.get("Content-Type", "")
    except urllib.error.HTTPError as exc:
        return exc.code, b"", exc.headers.get("Content-Type", "") if exc.headers else ""
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return 0, b"", f"error: {exc}"


def looks_like_login(body: bytes, content_type: str) -> bool:
    """El servidor responde 200 con el HTML del login si la ruta no existe."""
    if "text/html" in content_type.lower():
        return True
    head = body[:MAX_HTML_SNIFF].lower()
    return b"<html" in head or b"kt_login_user" in head


_print_lock = Lock()


def download(item: dict) -> dict:
    result = dict(item)
    result.update(status=None, url=None, form=None, bytes=0, sha256=None,
                  content_type=None, saved=None, error=None)

    for form, url in candidate_urls(item):
        time.sleep(DELAY)
        status, body, content_type = fetch(url)
        if status == 200 and body and not looks_like_login(body, content_type):
            target = FILES_DIR / item["source"] / str(item["row_id"]) / item["filename"]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(body)
            result.update(
                status=200, url=url, form=form, bytes=len(body),
                sha256=hashlib.sha256(body).hexdigest(),
                content_type=content_type,
                saved=str(target.relative_to(ROOT)).replace("\\", "/"),
            )
            return result
        result.update(status=status, url=url, content_type=content_type)

    result["error"] = "no encontrado en ninguna de las formas"
    return result


LOCAL_DUMP = ROOT.parent / "adhoc" / "documentos"


def match_key(name: str) -> str:
    """Clave de comparacion tolerante para nombres de archivo del legacy.

    El volcado local y la BD no siempre coinciden byte a byte: `doc_approve`
    dice 'FORMATO LISTA DE ASISTENCIA.xlsx' y el archivo real (en disco Y en el
    servidor) se llama 'FORMATO LISTA DE ASISTENCIA .xlsx', con un espacio
    antes de la extension. Se normaliza espacio en blanco alrededor del punto
    final y se compara sin distinguir mayusculas.
    """
    stem, dot, ext = name.rpartition(".")
    if not dot:
        return " ".join(name.split()).lower()
    return f"{' '.join(stem.split())}.{ext}".lower()


def stage_documents() -> int:
    """Coloca los documentos de `doc_approve` en el staging, desde el volcado local.

    Decision del usuario: usar el volcado local y bajar del servidor solo lo que
    falte. Hoy no falta nada — los 201 documentos con nombre de archivo estan en
    disco (200 con match exacto y 1 por el espacio antes de la extension).
    """
    docs = load("doc_approve")
    on_disk = {match_key(p.name): p for p in LOCAL_DUMP.iterdir() if p.is_file()}

    staged = missing = no_name = 0
    for doc in docs:
        filename = doc.get("dap_documento")
        if not filename:
            no_name += 1
            continue
        source = on_disk.get(match_key(filename))
        if source is None:
            missing += 1
            print(f"  SIN ARCHIVO  dap_id={doc['dap_id']}  {filename}")
            continue
        target = FILES_DIR / "doc_approve" / str(doc["dap_id"]) / source.name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
        staged += 1

    referenced = {match_key(d["dap_documento"]) for d in docs if d.get("dap_documento")}
    orphans = [p for k, p in on_disk.items() if k not in referenced]
    orphan_bytes = sum(p.stat().st_size for p in orphans)

    print(f"\n{staged} documentos en staging · {no_name} sin nombre en BD · {missing} sin archivo")
    print(f"{len(orphans)} huerfanos en el volcado local ({orphan_bytes/1048576:.1f} MB) — "
          f"NO se migran, archivar aparte")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="piloto: solo N archivos")
    parser.add_argument("--retry", action="store_true", help="reintentar solo los fallidos")
    parser.add_argument("--documents", action="store_true",
                        help="staging de doc_approve desde el volcado local (no descarga)")
    args = parser.parse_args()

    if args.documents:
        FILES_DIR.mkdir(parents=True, exist_ok=True)
        return stage_documents()

    work = build_worklist()

    if args.retry and MANIFEST.exists():
        previous = json.loads(MANIFEST.read_text(encoding="utf-8"))
        ok = {(r["source"], r["row_id"]) for r in previous if r.get("saved")}
        work = [w for w in work if (w["source"], w["row_id"]) not in ok]
        print(f"reintento: {len(work)} pendientes de {len(previous)}")

    if args.limit:
        # Piloto representativo: los primeros N de CADA origen, no los N
        # primeros a secas (que serian todos de inci_files).
        sampled: list[dict] = []
        for source in ("inci_files", "tareas_doc", "prog_files", "tareas_prog_doc"):
            sampled += [w for w in work if w["source"] == source][: args.limit]
        work = sampled

    FILES_DIR.mkdir(parents=True, exist_ok=True)
    print(f"{len(work)} archivos por descargar ({WORKERS} en paralelo)\n")

    results = []
    done = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for result in pool.map(download, work):
            results.append(result)
            done += 1
            if result["saved"]:
                mark = f"OK   {result['form']:<6} {result['bytes']:>9,} B"
            else:
                mark = f"FALLA {result['status']}"
            with _print_lock:
                print(f"[{done:>4}/{len(work)}] {mark}  {result['source']}/{result['row_id']}  "
                      f"{result['filename'][:58]}")

    got = [r for r in results if r["saved"]]
    by_form: dict[str, int] = {}
    for r in got:
        by_form[r["form"]] = by_form.get(r["form"], 0) + 1

    if not args.limit:
        MANIFEST.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")

    total_bytes = sum(r["bytes"] for r in got)
    unique = len({r["sha256"] for r in got})
    print(f"\n{len(got)}/{len(results)} descargados · {total_bytes/1048576:.1f} MB · "
          f"{unique} contenidos distintos · formas: {by_form}")

    failed = [r for r in results if not r["saved"]]
    if failed:
        print(f"\n{len(failed)} sin encontrar:")
        for r in failed[:20]:
            print(f"  {r['source']}/{r['row_id']:<8} parent={r['parent_id']}  {r['filename'][:60]}")
        if len(failed) > 20:
            print(f"  ... y {len(failed) - 20} mas (ver {MANIFEST.name})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
