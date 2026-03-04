#!/usr/bin/env python3
"""
Comandos CLI core para itcj2 — sin Flask context.
Equivalente a itcj/core/commands.py.
"""
import os
from pathlib import Path

import click
from sqlalchemy import text

# Raíz del proyecto: itcj2/cli/ → itcj2/ → project_root/
PROJECT_ROOT = Path(__file__).parent.parent.parent


def _get_engine():
    from itcj2.database import engine
    return engine


def _get_session():
    from itcj2.database import SessionLocal
    return SessionLocal()


def execute_sql_file(file_path):
    """Ejecuta un archivo SQL específico."""
    engine = _get_engine()
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            sql_content = f.read()

        # Limpiar comentarios de línea
        cleaned_lines = []
        for line in sql_content.split("\n"):
            if "--" in line:
                comment_pos = line.find("--")
                line = line[:comment_pos].rstrip()
            if line.strip():
                cleaned_lines.append(line)

        cleaned_content = "\n".join(cleaned_lines)

        if any(
            keyword in cleaned_content.upper()
            for keyword in ["DO $$", "CREATE OR REPLACE FUNCTION", "CREATE FUNCTION"]
        ):
            with engine.connect() as connection:
                if cleaned_content.strip():
                    connection.execute(text(cleaned_content))
                    connection.commit()
        else:
            statements = [s.strip() for s in cleaned_content.split(";") if s.strip()]
            with engine.connect() as connection:
                for statement in statements:
                    if statement.strip():
                        connection.execute(text(statement))
                connection.commit()

    except Exception as e:
        raise Exception(f"Error ejecutando {file_path}: {str(e)}")


@click.command("init-db")
def init_database_command():
    """Ejecuta todos los scripts SQL de inicialización en orden."""
    click.echo("Iniciando carga de datos base...")

    sql_directories = [
        (
            "app/database/DML/core/init",
            [
                "00_insert_apps.sql",
                "01_insert_departments.sql",
                "02_insert_positions.sql",
                "03_insert_icons_deparments.sql",
                "04_insert_roles.sql",
                "05_insert_permissions.sql",
                "06_insert_role_permissions.sql",
                "07_insert_user.sql",
                "08_insert_role_positions_helpdesk.sql",
                "09_insert_user_positions.sql",
                "10_insert_user_roles.sql",
            ],
        ),
        (
            "app/database/DML/core/agendatec",
            [
                "01_insert_permissions.sql",
                "02_insert_user_app.sql",
                "03_insert_role_permission.sql",
            ],
        ),
        (
            "app/database/DML/helpdesk",
            [
                "01_insert_permissions.sql",
                "02_insert_roles.sql",
                "03_insert_role_permission.sql",
                "04_insert_categories.sql",
                "05_insert_inventory_categories.sql",
                "06_insert_enhanced_inventory_categories.sql",
                "07_insert_position_app_perm.sql",
                "08_insert_technician_user.sql",
                "09_insert_user_role_technician.sql",
                "11_insert_user_position_technician.sql",
                "12_insert_configure_moodle_custom_fields.sql",
            ],
        ),
    ]

    try:
        for directory, files in sql_directories:
            directory_path = PROJECT_ROOT / directory

            click.echo(f"\n📁 Procesando directorio: {directory}")

            if not directory_path.exists():
                alt_dir = directory.replace("app/", "")
                alt_path = PROJECT_ROOT / alt_dir
                if alt_path.exists():
                    directory_path = alt_path
                    click.echo(f"   ℹ️  Ruta alternativa: {alt_dir}")
                else:
                    click.echo(f"   ⚠️  No encontrado: {directory_path}")
                    continue
            else:
                click.echo("   ✓ Directorio encontrado")

            for sql_file in files:
                file_path = directory_path / sql_file
                if not file_path.exists():
                    click.echo(f"⚠️  Archivo no encontrado: {sql_file}")
                    continue
                try:
                    click.echo(f"   🔄 Ejecutando: {sql_file}")
                    execute_sql_file(str(file_path))
                    click.echo(f"   ✅ Completado: {sql_file}")
                except Exception as e:
                    click.echo(f"   ❌ Error en {sql_file}: {str(e)}")
                    raise

        click.echo("\n🎉 ¡Inicialización completada exitosamente!")

    except Exception as e:
        click.echo(f"\n💥 Error durante la inicialización: {str(e)}")
        raise


@click.command("reset-db")
def reset_database_command():
    """Reinicia la base de datos y ejecuta las migraciones."""
    click.echo("🔄 Reiniciando base de datos...")
    engine = _get_engine()
    try:
        from itcj2.models.base import Base
        import itcj2.core.models  # noqa
        import itcj2.apps.helpdesk.models  # noqa
        import itcj2.apps.agendatec.models  # noqa
        import itcj2.apps.vistetec.models  # noqa

        with engine.connect() as conn:
            Base.metadata.drop_all(conn)
            click.echo("✅ Tablas eliminadas")
            Base.metadata.create_all(conn)
            conn.commit()
            click.echo("✅ Tablas creadas")

        ctx = click.get_current_context()
        ctx.invoke(init_database_command)

    except Exception as e:
        click.echo(f"❌ Error durante el reset: {str(e)}")
        raise


@click.command("check-db")
def check_database_command():
    """Verifica el estado de la base de datos."""
    click.echo("🔍 Verificando estado de la base de datos...")
    engine = _get_engine()
    try:
        with engine.connect() as connection:
            tables = {
                "core_apps": "Apps registradas",
                "core_departments": "Departamentos",
                "core_positions": "Posiciones",
                "core_permissions": "Permisos",
                "core_roles": "Roles",
            }
            for table, label in tables.items():
                result = connection.execute(
                    text(f"SELECT COUNT(*) as count FROM {table}")
                ).fetchone()
                click.echo(f"  {label}: {result.count}")

        click.echo("✅ Verificación completada")

    except Exception as e:
        click.echo(f"❌ Error durante la verificación: {str(e)}")
        raise


@click.command("execute-sql")
@click.argument("sql_file")
def execute_single_sql_command(sql_file):
    """Ejecuta un archivo SQL específico."""
    click.echo(f"🔄 Ejecutando archivo: {sql_file}")

    file_path = Path(sql_file) if Path(sql_file).is_absolute() else PROJECT_ROOT / sql_file

    try:
        if not file_path.exists():
            raise FileNotFoundError(f"Archivo no encontrado: {file_path}")
        execute_sql_file(str(file_path))
        click.echo(f"✅ Archivo ejecutado exitosamente: {sql_file}")
    except Exception as e:
        click.echo(f"❌ Error ejecutando {sql_file}: {str(e)}")
        raise


@click.command("init-themes")
def init_themes_command():
    """Inicializa los permisos y datos base para el sistema de temáticas."""
    click.echo("🎨 Inicializando sistema de temáticas...")

    sql_file = PROJECT_ROOT / "database" / "DML" / "core" / "themes" / "theme.sql"

    if not sql_file.exists():
        alternatives = [
            PROJECT_ROOT / "app" / "database" / "DML" / "core" / "themes" / "theme.sql",
            PROJECT_ROOT / "database" / "DML" / "core" / "themes.sql",
        ]
        for alt in alternatives:
            if alt.exists():
                sql_file = alt
                break

    try:
        if not sql_file.exists():
            click.echo(f"⚠️  Archivo no encontrado: {sql_file}")
            return

        click.echo(f"📄 Ejecutando: {sql_file}")
        execute_sql_file(str(sql_file))

        engine = _get_engine()
        with engine.connect() as connection:
            result = connection.execute(
                text("SELECT COUNT(*) as count FROM core_permissions WHERE code LIKE 'core.themes.%'")
            ).fetchone()
            click.echo(f"   ✅ Permisos de temáticas creados: {result.count}")

            result = connection.execute(
                text("SELECT COUNT(*) as count FROM core_themes")
            ).fetchone()
            click.echo(f"   ✅ Temáticas configuradas: {result.count}")

            themes = connection.execute(
                text("SELECT name, is_enabled FROM core_themes ORDER BY priority")
            ).fetchall()
            if themes:
                click.echo("\n   📋 Temáticas disponibles:")
                for theme in themes:
                    status = "✓" if theme.is_enabled else "✗"
                    click.echo(f"      {status} {theme.name}")

        click.echo("\n🎉 Sistema de temáticas inicializado correctamente!")

    except Exception as e:
        click.echo(f"❌ Error inicializando temáticas: {str(e)}")
        raise


@click.group("core")
def core_cli():
    """Comandos CLI del módulo core."""


core_cli.add_command(init_database_command)
core_cli.add_command(reset_database_command)
core_cli.add_command(check_database_command)
core_cli.add_command(execute_single_sql_command)
core_cli.add_command(init_themes_command)
