#!/usr/bin/env python3
"""
Comandos CLI de Mantenimiento para itcj2.

Comandos:
    maint init-maint    Registra la app, permisos, roles y categorías base.
"""
from pathlib import Path

import click

PROJECT_ROOT = Path(__file__).parent.parent.parent
DML_MAINT = PROJECT_ROOT / "database" / "DML" / "maint"


def _run_sql_files(files: list[str]) -> None:
    """Ejecuta una lista de archivos SQL usando el helper de core."""
    from itcj2.cli.core import execute_sql_file

    for filename in files:
        file_path = DML_MAINT / filename
        if not file_path.exists():
            click.echo(f"   ⚠️  Archivo no encontrado: {filename}")
            continue
        click.echo(f"   🔄 Ejecutando: {filename}")
        execute_sql_file(str(file_path))
        click.echo(f"   ✅ Completado: {filename}")


@click.group("maint")
def maint_cli():
    """Comandos de inicialización de la app de Mantenimiento."""


@maint_cli.command("init-maint")
def init_maint_command():
    """Inicializa la app de Mantenimiento completamente.

    Ejecuta en orden:
      00_insert_app.sql                         → Registra la app en core_apps
      01_add_maint_permissions.sql              → 20 permisos maint.*
      02_assign_maint_permissions_to_roles.sql  → Roles + asignación + posiciones
      03_seed_maint_categories.sql              → 6 categorías base
      05_add_stats_permissions.sql              → 4 permisos stats/analysis
      06_help_permissions.sql                   → Permisos de páginas de ayuda
      08_insert_position_app_perm.sql           → Extras al puesto secretary_equipment_maint
                                                  (asignaciones, admin, stats, warehouse vía dispatcher)
      09_assign_warehouse_user_roles.sql        → Propaga UserAppRole maint → warehouse
                                                  (admin/dispatcher/tech_maint)

    Todos los DML son idempotentes (ON CONFLICT DO NOTHING).

    Prerequisitos:
      - Tablas maint_* existen (alembic upgrade head)
      - `warehouse init-warehouse` ejecutado (app warehouse + perms warehouse.*)

    Post-requisito:
      - Ejecutar `warehouse warehouse-maint` DESPUÉS de este comando para
        asignar los perms warehouse a los roles dispatcher/tech_maint que
        crea el paso 02.
    """
    click.echo("🔧 Inicializando app de Mantenimiento...")
    click.echo()
    try:
        _run_sql_files([
            "00_insert_app.sql",
            "01_add_maint_permissions.sql",
            "02_assign_maint_permissions_to_roles.sql",
            "03_seed_maint_categories.sql",
            "05_add_stats_permissions.sql",
            "06_help_permissions.sql",
            "08_insert_position_app_perm.sql",
            "09_assign_warehouse_user_roles.sql",
        ])
        click.echo()
        click.echo("🎉 ¡App de Mantenimiento inicializada exitosamente!")
        click.echo()
        click.echo("   Roles creados: admin, dispatcher, tech_maint,")
        click.echo("                  department_head, secretary, staff")
        click.echo("   Categorías:    TRANSPORT, GENERAL, ELECTRICAL,")
        click.echo("                  CARPENTRY, AC, GARDENING")
        click.echo("   Almacén:       admin/dispatcher/tech_maint con UserAppRole")
        click.echo("                  cruzada a la app warehouse (paso 09)")
        click.echo()
        click.echo("   ⚠️  Siguiente paso obligatorio (asigna perms warehouse a estos roles):")
        click.echo("   → python -m itcj2.cli.main warehouse warehouse-maint")
    except Exception as e:
        click.echo(f"\n💥 Error durante la inicialización: {e}")
        raise
