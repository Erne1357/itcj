"""Invariantes de los workflows de CI/CD (`.github/workflows/`).

Cada una cierra un hueco que convierte un rojo en verde o se traga un deploy
sin avisar. Leen archivos del repo: corren igual en CI y en dev.

No se usa PyYAML a propósito (no está en requirements.txt; ver
test_compose_prod_invariants.py): se corta el bloque de cada job por
indentación y se buscan las claves como texto.
"""
from pathlib import Path

WORKFLOWS = Path(__file__).resolve().parents[3] / ".github" / "workflows"


def _job(workflow: str, job: str) -> str:
    """Texto del job ``job`` (clave con indentación de 2 espacios) del workflow."""
    block: list[str] = []
    inside = False
    for line in (WORKFLOWS / workflow).read_text(encoding="utf-8").splitlines():
        is_key = (
            line.startswith("  ")
            and not line.startswith("   ")
            and not line.lstrip().startswith("#")
            and line.rstrip().endswith(":")
        )
        if is_key:
            inside = line.strip() == f"{job}:"
            continue
        if inside:
            if line and not line.startswith(" "):
                break
            block.append(line)
    assert block, f"{workflow} no define el job '{job}'"
    return "\n".join(block)


def test_todos_los_shards_de_un_run_leen_las_mismas_duraciones():
    """pytest-split corta en tramos contiguos según las duraciones.

    Si cada shard restaurara «el caché más reciente» por su cuenta, un re-run
    del shard rojo después de que la nocturna guardó duraciones nuevas correría
    otro tramo: el test rojo caería en uno que ya pasó y nadie lo volvería a
    correr. La key se resuelve una vez por run y los shards la piden exacta.
    """
    durations = _job("_tests.yml", "durations")
    assert "lookup-only: true" in durations

    shard = _job("_tests.yml", "shard")
    assert "needs: durations" in shard
    assert "key: ${{ needs.durations.outputs.key }}" in shard
    assert "fail-on-cache-miss: true" in shard
    assert "restore-keys" not in shard


def test_un_run_superado_no_entra_a_la_cola_del_deploy():
    """La cola de `production-deploy` cancela al deploy PENDIENTE cuando llega
    otro, sin mirar qué commit es más nuevo: un run viejo que termina sus tests
    tarde desplazaría a un hotfix que esperaba turno. Si main ya avanzó, el run
    del carril full no despliega (el más nuevo lo hará e incluye este commit).
    """
    gate = _job("deploy.yml", "gate")
    assert "compare/$SHA...main" in gate
    assert "superseded" in gate

    deploy = _job("deploy.yml", "deploy")
    assert "gate" in deploy.split("if:")[0], "deploy debe depender de gate"
    assert "needs.gate.outputs.superseded != 'true'" in deploy


def test_un_hotfix_cuyo_deploy_se_cancela_deja_el_run_en_rojo():
    """Un job cancelado no pone el run en rojo ni manda correo: sin esta
    alerta, un hotfix desplazado de la cola nunca llegaría a prod en silencio.
    """
    alert = _job("deploy.yml", "deploy-cancel-alert")
    assert "needs.plan.outputs.lane == 'hotfix'" in alert
    assert "needs.deploy.result == 'cancelled'" in alert
    assert "::error::" in alert
    assert "exit 1" in alert


def test_el_paso_de_apt_no_se_puede_colgar():
    """2026-10-07 (run 37679631400): un runner no alcanzó el mirror de Azure
    (`Ign:` en cada índice) y `apt-get update` esperó el timeout de cada archivo:
    >10 min en un paso de ~10 s, con el job sin límite propio (6 h por omisión).
    Con 8 shards la probabilidad de tocar un runner así se multiplica: el paso
    lleva límite y apt timeouts cortos con reintentos, para fallar rápido y que
    «Re-run failed jobs» relance solo ese shard."""
    shard = _job("_tests.yml", "shard")
    paso = shard[shard.index("Dependencias de sistema para WeasyPrint"):]
    paso = paso[:paso.index("- name:", 1)] if "- name:" in paso[1:] else paso
    assert "timeout-minutes:" in paso
    assert "Acquire::Retries=" in paso
    assert "Acquire::http::Timeout=" in paso
