"""Orquesta el transform: genera los `.sql` del import y el plan de archivos.

    python scripts/adhoc_etl/run.py

Escribe `database/DML/adhoc/legacy_import/*.sql` y
`build/adhoc_legacy/_file_plan.json`, que consume `deploy_files.py` para copiar
los 1083 archivos a `instance/apps/adhoc/{kind}/{entity_id}/`.

El orden de los pasos no es estético: es el de las dependencias de FK reales.
`adhoc_indicators.process_id` es NOT NULL, así que estructura va antes que
indicadores; y `adhoc_task_approvals.comment_id` es FK a los comentarios, así
que las aprobaciones van al final.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from builders import step_catalogs, step_flows, step_structure, step_truncate, step_users
from builders_content import (
    step_acknowledgements, step_documents, step_incidents, step_indicators, step_program,
)
from builders_tasks import (
    step_approvals, step_comments_and_files, step_tasks, step_verify,
)
from transform import DATA, OUT, Ctx


def main() -> int:
    ctx = Ctx()
    file_plan: list[dict] = []
    files = []

    files.append(step_truncate(ctx))
    files.extend(step_users(ctx))
    files.append(step_catalogs(ctx))
    files.append(step_structure(ctx))
    files.append(step_flows(ctx))
    files.append(step_documents(ctx, file_plan))
    files.append(step_acknowledgements(ctx))
    files.append(step_incidents(ctx))
    files.append(step_program(ctx))
    files.append(step_indicators(ctx))
    files.append(step_tasks(ctx))
    files.append(step_comments_and_files(ctx, file_plan))
    files.append(step_approvals(ctx))
    files.append(step_verify(ctx))

    # Se escribe al final para que 99_verify tenga todos los conteos.
    for existing in OUT.glob("*.sql") if OUT.exists() else []:
        existing.unlink()
    total = 0
    for f in files:
        size = f.write()
        total += size
        print(f"  {f.name:<28} {size/1024:>8.1f} KB")

    (DATA / "_file_plan.json").write_text(
        json.dumps(file_plan, ensure_ascii=False, indent=1), encoding="utf-8"
    )

    print(f"\n{len(files)} archivos · {total/1048576:.2f} MB -> {OUT}")
    print(f"{len(file_plan)} archivos por copiar -> build/adhoc_legacy/_file_plan.json\n")
    print("Volumen calculado:")
    for table, count in sorted(ctx.stats.items()):
        print(f"  {table:<38} {count:>7,}")
    print(f"  {'TOTAL':<38} {sum(ctx.stats.values()):>7,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
