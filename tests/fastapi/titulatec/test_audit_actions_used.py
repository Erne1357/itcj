"""Contrato de la bitácora, parte (b): todo código registrado se usa (spec 2026-10-07 §8).

Complemento de `test_audit_actions_contract.py` (que cubre (a), (c) y (d)): un
vocabulario cerrado no puede acumular códigos muertos. Cada clave de
`AUDIT_ACTIONS` debe aparecer como LITERAL en el código de acción de alguna
llamada `AuditService.record(` de `itcj2/apps/titulatec/**`,
`itcj2/cli/titulatec.py` o `itcj2/tasks/titulatec_tasks.py`.

Reusa el barrido AST del test de contrato (mismas formas de literal y mismos
archivos), así que si cambia allá, cambia aquí. Sin BD.
"""
from __future__ import annotations

from tests.fastapi.titulatec import test_audit_actions_contract as contrato


def _codigos_usados() -> set[str]:
    usados: set[str] = set()
    for ruta in contrato._fuentes_instrumentadas():
        codigos, _, _ = contrato._barrer_llamadas(
            ruta.read_text(encoding="utf-8"), ruta.relative_to(contrato._REPO).as_posix())
        usados.update(c for _, c in codigos)
    return usados


def test_todo_codigo_registrado_se_usa_en_alguna_llamada_a_record():
    registrados = set(contrato._vocab().AUDIT_ACTIONS)
    muertos = sorted(registrados - _codigos_usados())
    assert not muertos, (
        "estos códigos están en `AUDIT_ACTIONS` pero ninguna llamada "
        "`AuditService.record(db, '<código>', ...)` los emite (instrumenta la "
        "mutación que les corresponde o quita el código del vocabulario):\n  "
        + "\n  ".join(muertos)
    )
