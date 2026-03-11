#!/usr/bin/env python3
"""
Comandos CLI de Warehouse para itcj2.

Comandos:
    warehouse init-warehouse       Registra la app y carga los permisos base.
    warehouse warehouse-helpdesk   Asigna permisos a roles de Helpdesk.
    warehouse warehouse-maint      Asigna permisos a roles de Mantenimiento.
"""
from pathlib import Path

import click

PROJECT_ROOT = Path(__file__).parent.parent.parent
DML_WAREHOUSE = PROJECT_ROOT / "database" / "DML" / "warehouse"


def _run_sql_files(files: list[str]) -> None:
    """Ejecuta una lista de archivos SQL usando el helper de core."""
    from itcj2.cli.core import execute_sql_file

    for filename in files:
        file_path = DML_WAREHOUSE / filename
        if not file_path.exists():
            click.echo(f"   ⚠️  Archivo no encontrado: {filename}")
            continue
        click.echo(f"   🔄 Ejecutando: {filename}")
        execute_sql_file(str(file_path))
        click.echo(f"   ✅ Completado: {filename}")


@click.group("warehouse")
def warehouse_cli():
    """Comandos de inicialización del módulo Warehouse."""


@warehouse_cli.command("init-warehouse")
def init_warehouse_command():
    """Registra la app warehouse y carga sus permisos base.

    Ejecuta:
      00_insert_app.sql
      01_add_warehouse_permissions.sql
    """
    click.echo("🏗️  Inicializando Warehouse...")
    try:
        _run_sql_files([
            "00_insert_app.sql",
            "01_add_warehouse_permissions.sql",
        ])
        click.echo("\n🎉 ¡Warehouse inicializado exitosamente!")
    except Exception as e:
        click.echo(f"\n💥 Error durante la inicialización: {e}")
        raise


@warehouse_cli.command("warehouse-helpdesk")
def warehouse_helpdesk_command():
    """Asigna los permisos de Warehouse a los roles de Helpdesk.

    Ejecuta:
      02_assign_warehouse_permissions_to_helpdesk_roles.sql
      04_assign_warehouse_to_tech_desarrollo.sql
    """
    click.echo("🔗 Asignando permisos Warehouse → roles Helpdesk...")
    try:
        _run_sql_files([
            "02_assign_warehouse_permissions_to_helpdesk_roles.sql",
            "04_assign_warehouse_to_tech_desarrollo.sql",
        ])
        click.echo("\n🎉 ¡Permisos Helpdesk asignados exitosamente!")
    except Exception as e:
        click.echo(f"\n💥 Error durante la asignación: {e}")
        raise


@warehouse_cli.command("warehouse-maint")
def warehouse_maint_command():
    """Asigna los permisos de Warehouse a los roles de Mantenimiento.

    Ejecuta:
      03_assign_warehouse_permissions_to_maint_roles.sql
    """
    click.echo("🔧 Asignando permisos Warehouse → roles Mantenimiento...")
    try:
        _run_sql_files([
            "03_assign_warehouse_permissions_to_maint_roles.sql",
        ])
        click.echo("\n🎉 ¡Permisos Mantenimiento asignados exitosamente!")
    except Exception as e:
        click.echo(f"\n💥 Error durante la asignación: {e}")
        raise
