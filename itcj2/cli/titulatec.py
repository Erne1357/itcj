#!/usr/bin/env python3
"""
Comandos CLI de TitulaTec para itcj2.

Comandos:
    titulatec init-titulatec    Registra la app, roles, permisos, puestos y catálogos base.
"""
from pathlib import Path

import click

PROJECT_ROOT = Path(__file__).parent.parent.parent
DML_TITULATEC = PROJECT_ROOT / "database" / "DML" / "titulatec"

# Orden de ejecución de los seeders. FUENTE ÚNICA: `itcj2/cli/core.py`
# (`seed-reference-data`) importa esta misma lista, para que no vuelvan a divergir
# como divergieron hasta 2026-09 (core corría 00/04/06/07, este comando 00-06;
# ninguno de los dos cargaba el set completo).
#
# Todos son idempotentes, pero OJO con el 03: además de los INSERT ... ON CONFLICT
# lleva dos DELETE que revocan `cohort.*` al rol `titulatec_titulaciones` (las
# convocatorias son de Servicios Escolares). Eso se aplica EN CADA CORRIDA: una
# concesión manual posterior de esos permisos se pierde al re-sembrar. Es la
# política declarada, no un accidente.
SEED_FILES = [
    "00_insert_app.sql",                  # Registra la app en core_apps
    "01_insert_roles.sql",                # 5 roles nuevos (alumno recicla 'student' global)
    "02_insert_permissions.sql",          # Permisos titulatec.*
    "03_insert_role_permissions.sql",     # Asignación rol→permisos (incl. 'student') + revocaciones
    "04_insert_vinculacion_positions.sql",# Puestos nuevos coord_vinculacion_* por depto
    "05_insert_position_app_roles.sql",   # Mapeo puestos→roles (escolares, titulaciones, vinculación)
    "06_seed_catalogs.sql",               # Modalidades, fases (0-8) y tipos de documento
    "07_insert_cotejo_reqs_perm.sql",     # Permiso de requisitos de cotejo (rol head)
]


def _run_sql_files(files: list[str]) -> None:
    """Ejecuta una lista de archivos SQL (relativos a DML_TITULATEC) vía el helper de core.

    Aborta si falta un archivo. Antes hacía `continue` con un warning y luego
    imprimía "init-titulatec completado" con exit 0: una app a medio sembrar
    (sin roles ni permisos) es indistinguible de una app sembrada, y todas sus
    páginas responden 404 sin que nada lo señale.
    """
    from itcj2.cli.core import execute_sql_file

    missing = [f for f in files if not (DML_TITULATEC / f).exists()]
    if missing:
        raise click.ClickException(
            "Faltan seeders en {}: {}.\n"
            "database/ está fuera del repo (gitignored): recupéralos del respaldo "
            "o de `git show db64df9^:database/DML/titulatec/<archivo>`. "
            "Sembrar a medias deja la app en 404 permanente.".format(
                DML_TITULATEC, ", ".join(missing)
            )
        )

    for filename in files:
        file_path = DML_TITULATEC / filename
        click.echo(f"   🔄 Ejecutando: {filename}")
        execute_sql_file(str(file_path))
        click.echo(f"   ✅ Completado: {filename}")


@click.group("titulatec")
def titulatec_cli():
    """Comandos de inicialización de la app de TitulaTec."""


@titulatec_cli.command("init-titulatec")
def init_titulatec_command():
    """Inicializa la app de TitulaTec completamente.

    Ejecuta en orden los 8 seeders de database/DML/titulatec/ (ver SEED_FILES).
    Idempotentes, pero el 03 revoca `cohort.*` a `titulatec_titulaciones` en cada
    corrida (política: las convocatorias son de Servicios Escolares).

    Aborta si falta cualquier archivo: sembrar a medias deja la app en 404.

    Prerequisitos:
      - Tablas titulatec_* existen (alembic upgrade head).
      - 04 antes que 05: el mapeo puesto→rol necesita los puestos ya creados.
    """
    click.echo("🎓 Inicializando app de TitulaTec...")
    click.echo()
    try:
        _run_sql_files(SEED_FILES)
        click.echo()
        click.echo("🎉 init-titulatec completado.")
    except Exception as e:
        click.echo(f"\n💥 Error durante init-titulatec: {e}")
        raise
