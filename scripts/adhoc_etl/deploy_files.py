"""Copia el acervo del legacy a `instance/apps/adhoc/`.

Lee `build/adhoc_legacy/_file_plan.json` (lo genera `run.py`) y deja cada
archivo donde la app lo va a buscar:

    instance/apps/adhoc/{kind}/{entity_id}/{nombre_saneado}

Esa forma no es invento: es el contrato que documenta `upload_service.py`
(`save_upload` devuelve `"{entity_id}/{filename}"` relativo al kind, y
`open_stored` rechaza cualquier otra forma), y es exactamente lo que las
columnas `file_url` / `file_path` del import traen escrito.

## Por qué copia directo y no pasa por `save_upload`

`save_upload` valida tamaño (10 MB) y whitelist de extensión, y añade sufijo
anti-colisión. Cuatro documentos del legacy pesan ~14 MB, así que pasarían por
un `ValueError`, y el sufijo cambiaría el nombre respecto al que ya quedó
escrito en la BD. El ETL no es una subida HTTP: escribe el archivo tal cual y
la app lo lee con `open_stored`, que solo exige dos tramos y que exista.

Uso:
    python scripts/adhoc_etl/deploy_files.py [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import shutil
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PLAN = ROOT / "build" / "adhoc_legacy" / "_file_plan.json"
DEST_ROOT = ROOT / "instance" / "apps" / "adhoc"

#: Los cuatro almacenes de `utils/constants.py::UPLOAD_KINDS`, más el de
#: incidencias, que es nuevo con `adhoc_incident_files`.
VALID_KINDS = {"documents", "program_events", "task_comments", "indicators", "incidents"}


def prune(plan: list[dict], *, apply: bool) -> int:
    """Borra los archivos que el plan actual ya no referencia.

    Hace falta porque el destino es `{kind}/{id_NUEVO}/`: si el ETL vuelve a
    correr y una entidad cambia de id, la copia anterior queda huérfana. Pasó
    de verdad — al mover los placeholder de incidencia y programa a los ids
    bajos, los 347 adjuntos de incidencia y los 2 de evento se duplicaron.

    Solo mira las carpetas de los kinds que el plan toca, y solo borra lo que
    NO está en el plan. Un archivo subido por la web que el plan desconoce
    también entra en ese saco, así que por defecto solo informa.
    """
    expected: set[Path] = {
        DEST_ROOT / item["kind"] / str(item["entity_id"]) / item["name"] for item in plan
    }
    kinds = {item["kind"] for item in plan}

    orphans: list[Path] = []
    for kind in sorted(kinds):
        root = DEST_ROOT / kind
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.is_file() and path not in expected:
                orphans.append(path)

    if not orphans:
        print("\nSin archivos huerfanos.")
        return 0

    wasted = sum(p.stat().st_size for p in orphans)
    print(f"\n{len(orphans)} archivos huerfanos ({wasted/1048576:.1f} MB):")
    by_kind: Counter = Counter(p.relative_to(DEST_ROOT).parts[0] for p in orphans)
    for kind, count in sorted(by_kind.items()):
        print(f"  {kind:<16} {count:>5}")
    for path in orphans[:5]:
        print(f"    ej. {path.relative_to(DEST_ROOT)}")

    if not apply:
        print("\n(solo informe — usa --prune para borrarlos)")
        return 0

    for path in orphans:
        path.unlink()
    for kind in sorted(kinds):
        for folder in sorted((DEST_ROOT / kind).glob("*"), reverse=True):
            if folder.is_dir() and not any(folder.iterdir()):
                folder.rmdir()
    print(f"\n{len(orphans)} archivos borrados.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--prune", action="store_true",
                        help="borra los archivos que el plan ya no referencia")
    args = parser.parse_args()

    if not PLAN.exists():
        print(f"No existe {PLAN}. Corre antes: python scripts/adhoc_etl/run.py")
        return 1

    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    by_kind: Counter = Counter()
    copied = missing = 0
    total_bytes = 0

    for item in plan:
        kind = item["kind"]
        if kind not in VALID_KINDS:
            print(f"  kind desconocido: {kind}")
            return 1
        source = Path(item["src"])
        if not source.exists():
            missing += 1
            print(f"  FALTA  {source}")
            continue
        target = DEST_ROOT / kind / str(item["entity_id"]) / item["name"]
        if not args.dry_run:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        by_kind[kind] += 1
        copied += 1
        total_bytes += source.stat().st_size

    verb = "se copiarian" if args.dry_run else "copiados"
    print(f"\n{copied} archivos {verb} · {total_bytes/1048576:.1f} MB")
    for kind, count in sorted(by_kind.items()):
        print(f"  {kind:<16} {count:>5}")
    if missing:
        print(f"\n{missing} archivos del plan no estan en el staging")
    print(f"\nDestino: {DEST_ROOT}")

    if not args.dry_run:
        prune(plan, apply=args.prune)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
