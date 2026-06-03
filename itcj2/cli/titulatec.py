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

# Orden de ejecución de los seeders. Todos idempotentes (ON CONFLICT DO NOTHING).
_SEED_FILES = [
    "00_insert_app.sql",                  # Registra la app en core_apps
    "01_insert_roles.sql",                # 4 roles nuevos (alumno recicla 'student' global)
    "02_insert_permissions.sql",          # 61 permisos titulatec.*
    "03_insert_role_permissions.sql",     # Asignación rol→permisos (incl. 'student')
    "04_insert_vinculacion_positions.sql",# Puestos nuevos coord_vinculacion_* por depto
    "05_insert_position_app_roles.sql",   # Mapeo puestos→roles (escolares, titulaciones, vinculación)
    "06_seed_catalogs.sql",               # Modalidades, fases (0-8) y tipos de documento
]


def _run_sql_files(files: list[str]) -> None:
    """Ejecuta una lista de archivos SQL (relativos a DML_TITULATEC) vía el helper de core."""
    from itcj2.cli.core import execute_sql_file

    for filename in files:
        file_path = DML_TITULATEC / filename
        if not file_path.exists():
            click.echo(f"   ⚠️  Archivo no encontrado: {filename}")
            continue
        click.echo(f"   🔄 Ejecutando: {filename}")
        execute_sql_file(str(file_path))
        click.echo(f"   ✅ Completado: {filename}")


@click.group("titulatec")
def titulatec_cli():
    """Comandos de inicialización de la app de TitulaTec."""


@titulatec_cli.command("init-titulatec")
def init_titulatec_command():
    """Inicializa la app de TitulaTec completamente.

    Ejecuta en orden todos los seeders de database/DML/titulatec/:
      00_insert_app.sql                   → Registra 'titulatec' en core_apps
      01_insert_roles.sql                 → 4 roles nuevos (el alumno recicla 'student')
      02_insert_permissions.sql           → 61 permisos titulatec.*
      03_insert_role_permissions.sql      → Asignación rol→permisos (incl. 'student')
      04_insert_vinculacion_positions.sql → Puestos coord_vinculacion_* por depto académico
      05_insert_position_app_roles.sql    → Mapeo puestos→roles
      06_seed_catalogs.sql                → Modalidades, fases (0-8), tipos de documento

    Todos los DML son idempotentes (ON CONFLICT DO NOTHING).

    Prerequisito:
      - Tablas titulatec_* existen (alembic upgrade head).
    """
    click.echo("🎓 Inicializando app de TitulaTec...")
    click.echo()
    try:
        _run_sql_files(_SEED_FILES)
        click.echo()
        click.echo("🎉 init-titulatec completado.")
    except Exception as e:
        click.echo(f"\n💥 Error durante init-titulatec: {e}")
        raise
