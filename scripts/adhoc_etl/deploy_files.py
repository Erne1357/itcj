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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
