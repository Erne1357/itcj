#!/usr/bin/env python3
"""
Comandos CLI core para itcj2 — sin Flask context.
Equivalente a itcj/core/commands.py.
"""
import os
from pathlib import Path

import click
from sqlalchemy import text

# Bootstraps the SQLAlchemy declarative Base (and itcj2.core.models package)
# so that service modules that import core models (e.g. themes_service) can be
# imported later without hitting the itcj2.models ↔ itcj2.core.models circular
# import chain.  This is a lightweight import: no DB connection is created.
import itcj2.models  # noqa: F401  # registra modelos antes de importar themes_service (evita import circular)

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


@click.command("init-tasks")
def init_tasks_command():
    """Inserta permisos del módulo de tareas programadas y los asigna a los roles admin y super_admin."""
    click.echo("⚙️  Inicializando permisos de Tareas Programadas...")

    tasks_dml = PROJECT_ROOT / "database" / "DML" / "core" / "tasks"
    sql_files = [
        "01_insert_permissions.sql",
        "02_insert_role_permissions.sql",
        "03_insert_task_catalog.sql",
    ]

    if not tasks_dml.exists():
        click.echo(f"❌ Directorio no encontrado: {tasks_dml}")
        raise SystemExit(1)

    try:
        for sql_file in sql_files:
            file_path = tasks_dml / sql_file
            if not file_path.exists():
                click.echo(f"⚠️  Archivo no encontrado: {sql_file}")
                continue
            click.echo(f"   🔄 Ejecutando: {sql_file}")
            execute_sql_file(str(file_path))
            click.echo(f"   ✅ Completado: {sql_file}")

        engine = _get_engine()
        with engine.connect() as connection:
            perms = connection.execute(
                text("SELECT COUNT(*) as count FROM core_permissions WHERE code LIKE 'core.tasks.%' OR code = 'core.config.admin'")
            ).fetchone()
            defs = connection.execute(
                text("SELECT COUNT(*) as count FROM core_task_definitions")
            ).fetchone()
            periodic = connection.execute(
                text("SELECT COUNT(*) as count FROM core_periodic_tasks WHERE is_active = TRUE")
            ).fetchone()
            click.echo(f"\n   📊 Permisos de tasks en DB:  {perms.count}")
            click.echo(f"   📋 Tareas en catálogo:        {defs.count}")
            click.echo(f"   🕐 Schedules activos:         {periodic.count}")

        click.echo("\n🎉 Tareas Programadas inicializadas correctamente!")

    except Exception as e:
        click.echo(f"\n💥 Error durante la inicialización: {str(e)}")
        raise


@click.command("new-theme-mundial")
def new_theme_mundial_command():
    """Crea el tema Mundial 2026 (activo), registra la tarea diaria y calienta el cache."""
    click.echo("⚽ Creando tema Mundial 2026...")

    # Todo el DML nuevo del Mundial vive en esta carpeta (01_theme.sql, 02_task.sql).
    # Se ejecutan en orden alfabético; no se toca ningún DML existente.
    mundial_dir = PROJECT_ROOT / "database" / "DML" / "core" / "themes" / "mundial"
    sql_files = sorted(mundial_dir.glob("*.sql"))

    if not sql_files:
        click.echo(f"❌ No se encontraron archivos SQL en: {mundial_dir}")
        raise SystemExit(1)

    for sql in sql_files:
        click.echo(f"📄 Ejecutando: {sql.name}")
        execute_sql_file(str(sql))

    # Invalidar cache del tema activo + activar cron + calentar cache de partidos
    from itcj2.core.services import themes_service, mundial_service

    themes_service.invalidate_active_theme_cache()

    db = _get_session()
    try:
        cron_active = mundial_service.sync_periodic_task(db)
    finally:
        db.close()

    today = mundial_service.get_today_cached(force=True) or {}

    click.echo("\n🎉 Tema Mundial 2026 listo!")
    click.echo(f"   ✓ Tema activo (manual)")
    click.echo(f"   ✓ Cron de refresco: {'activo' if cron_active else 'inactivo'}")
    click.echo(f"   ✓ Partidos hoy ({today.get('date')}): {len(today.get('matches', []))}")
    click.echo(f"   ✓ Proveedor de marcadores: {mundial_service.get_provider_name()}")


@click.command("mundial-refresh")
@click.option("--hard", is_flag=True, default=False,
              help="Además borra el historial de resultados (mundial:results) y el cache del tema activo.")
def mundial_refresh_command(hard: bool):
    """Borra el cache de partidos del Mundial en Redis y vuelve a consultar (force)."""
    from itcj2.core.services import mundial_service

    click.echo("⚽ Refrescando cache de partidos del Mundial...")
    mundial_service.clear_cache(hard=hard)
    if hard:
        click.echo("   🧹 Reset total (today + fixtures + results + active_theme)")

    # Diagnóstico de la API (por qué salen o no los marcadores)
    diag = mundial_service.api_diagnostic()
    click.echo(f"   🔎 API: provider={diag['provider']} enabled={diag['enabled']} "
               f"ok={diag['ok']} status={diag.get('status_code')} "
               f"total={diag['count']} hoy={diag['today_count']}")
    if diag.get("error"):
        click.echo(f"   ⚠️  API error: {diag['error']}")
    for s in diag.get("sample", []):
        click.echo(f"        · {s}")

    today = mundial_service.get_today_cached(force=True) or {}
    matches = today.get("matches", [])
    with_score = sum(1 for m in matches if m.get("score"))

    click.echo(f"   ✓ Proveedor: {mundial_service.get_provider_name()}")
    click.echo(f"   ✓ Partidos hoy ({today.get('date')}): {len(matches)} | con marcador: {with_score}")
    for m in matches:
        home = (m.get("home") or {}).get("name", "?")
        away = (m.get("away") or {}).get("name", "?")
        sc = m.get("score")
        detail = f"{sc['home']}-{sc['away']}" if sc else (m.get("status") or "?")
        click.echo(f"      - {home} vs {away}: {detail}")

    click.echo("\n🎉 Cache refrescado.")


@click.group("core")
def core_cli():
    """Comandos CLI del módulo core."""


core_cli.add_command(init_database_command)
core_cli.add_command(reset_database_command)
core_cli.add_command(check_database_command)
core_cli.add_command(execute_single_sql_command)
core_cli.add_command(init_themes_command)
core_cli.add_command(init_tasks_command)
core_cli.add_command(new_theme_mundial_command)
core_cli.add_command(mundial_refresh_command)
