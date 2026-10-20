"""Helpers compartidos por los tests de sitios instrumentados (Fase 4b, Task 2).

Mismo patrón de delta que `test_work_metrics.py` (Task 1): los histogramas son
de MÓDULO y acumulan entre tests, así que todo se mide como delta con
`REGISTRY.get_sample_value`, que exige el juego de etiquetas EXACTO.
"""
from prometheus_client import REGISTRY

RENDER = "itcj_document_render_seconds"
OUTBOUND = "itcj_outbound_request_seconds"
OUTCOMES = ("ok", "error", "timeout")


def counts(labels: dict, name: str = RENDER) -> dict:
    return {
        outcome: REGISTRY.get_sample_value(
            f"{name}_count", {**labels, "outcome": outcome}
        ) or 0.0
        for outcome in OUTCOMES
    }


def delta(before: dict, after: dict) -> dict:
    return {outcome: after[outcome] - before[outcome] for outcome in OUTCOMES}


def only(outcome: str) -> dict:
    return {o: (1.0 if o == outcome else 0.0) for o in OUTCOMES}
