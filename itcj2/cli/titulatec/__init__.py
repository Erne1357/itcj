"""Comandos CLI de TitulaTec (`python -m itcj2.cli.main titulatec ...`).

Paquete con un módulo por contexto (spec 2026-10-14-titulatec-cli-paquete §3).
La lista de comandos con sus opciones está en el docstring de `_common.py`.

    _common         grupo `titulatec_cli`, rutas (`PROJECT_ROOT`, `DML_TITULATEC`),
                    `SEED_FILES`, bitácora de comandos y helpers compartidos
    verificaciones  verificaciones de init-titulatec (encuesta 2026-09,
                    Titulación, Centro de Cómputo) y sus constantes
    seed            init-titulatec
    deltas          init-email-tasks, init-outbox-admin, init-bitacora,
                    init-reportes, init-especialidades, init-ajustes-2026-10
    posgrado        init-posgrado
    biblioteca      init-biblioteca-caja, activar-biblioteca-caja
    liberaciones    import-prior-clearances, emitir-folios-previos
    encuesta        load-survey-2026-09, import-survey-xlsx
    sii             sii-ping, sii-rules-validate, sii-check, sii-sweep
    bitacora        audit-purge, audit-backfill-solicitudes
    mantenimiento   fix-missing-credentials, rename-documents, fix-control-l
    nips            exportar-sin-cuenta, cargar-nips, purgar-nips
    promedios       exportar-controles, cargar-promedios
    documentos      init-reemplazo-docs
    fase2           init-titulatec-fase-2 (DML de la fase 2 del desarrollo, fases 3-8;
                    tras init-titulatec o init-ajustes-2026-10 hay que re-correrlo)

Cada submódulo registra sus comandos en `titulatec_cli` al importarse: por eso
este archivo los importa TODOS. Los submódulos de comandos solo dependen de
`_common` y `verificaciones`, nunca entre sí. Para parchear un helper en un
test, apunta al submódulo donde lo BUSCA la función que lo llama (p. ej.
`itcj2.cli.titulatec.deltas._run_sql_files`), no a este paquete: un parche
aquí no intercepta nada.
"""
from itcj2.cli.titulatec._common import (
    DML_TITULATEC,
    PROJECT_ROOT,
    SEED_FILES,
    titulatec_cli,
)

# Registran sus comandos en `titulatec_cli` al importarse: primero `_common`
# (arriba), luego `verificaciones` y el resto.
# isort: off
from itcj2.cli.titulatec import (  # noqa: F401
    verificaciones,
    seed,
    deltas,
    posgrado,
    biblioteca,
    liberaciones,
    encuesta,
    sii,
    bitacora,
    mantenimiento,
    nips,
    promedios,
    documentos,
    fase2,
)
# isort: on

__all__ = ["DML_TITULATEC", "PROJECT_ROOT", "SEED_FILES", "titulatec_cli"]
