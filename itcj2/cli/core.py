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


@click.command("seed-reference-data")
def seed_reference_data_command():
    """Carga TODO el catálogo de referencia (apps, roles, permisos, posiciones,
    categorías, temas...) sobre un esquema recién creado (create_all / fresh DB).

    SOLO para bootstrap local o de staging — requiere `database/DML/` en disco
    (gitignored a propósito: trae PII real y no se distribuye por git; los
    archivos viven en el servidor y se transfieren por scp). El gate de CI NO
    usa este comando ni tiene acceso a `database/DML/`: siembra su propio set
    mínimo, sin PII, vía fixture de pytest (`tests/fastapi/conftest.py`).

    A diferencia de `init-db` (subset legacy: solo core + agendatec + helpdesk),
    este comando recorre TODOS los DML de `database/DML/` que son reproducibles
    en un ambiente nuevo, en el orden de dependencias correcto.

    Deliberadamente EXCLUIDO (no reproducible desde DML solo):
    - `core/init/09_insert_user_positions.sql` y
      `helpdesk/11_insert_user_position_technician.sql`: asignan puestos a
      usuarios que el propio script marca como "EXISTING USER - UPDATE"
      (preexistían en la BD real antes de que este DML se escribiera; en una
      BD nueva el UPDATE no toca ninguna fila y el INSERT subsiguiente falla
      con user_id NULL). Repararlos implicaría inventar datos de personas
      reales que no están en ningún DML — fuera de alcance de un seed.
    - `database/DML/agendatec/{11..15}.sql`, `agendatec/help/*`,
      `agendatec/periods/*`: preceden el rename de tablas legacy→core_* y
      referencian tablas que ya no existen (`roles`, `programs`, `users`).
      Datos reales de agendatec vinieron de la restauración del dump, no de
      re-ejecutar estos scripts.
    - `database/DML/dump/*`, `database/DML/maint/{11,12}_*`,
      `helpdesk/inventory_by_department_report.sql`,
      `helpdesk/10_verify_notification_setup.sql`,
      `vistetec/04_verify_permissions.sql`,
      `database/DML/org_scope_2026_07/*` (duplicado obsoleto de
      `core/config_2026_07/subtree/*`): dumps de prod, altas de personal real
      con contraseña compartida, reportes/verificaciones de solo lectura, o
      duplicados — ninguno es catálogo de referencia reproducible.
    """
    click.echo("🌱 Cargando catálogo de referencia completo...")

    files = [
        "core/init/00_insert_apps.sql",
        "core/init/01_insert_departments.sql",
        "core/init/02_insert_positions.sql",
        "core/init/03_insert_icons_deparments.sql",
        "core/init/04_insert_roles.sql",
        # Roles cross-app (student/coordinator/admin/social_service) deben
        # existir ANTES de que 05/06 y core/agendatec/03 les asignen permisos.
        "agendatec/10_insert_roles.sql",
        "core/init/05_insert_permissions.sql",
        "core/init/06_insert_role_permissions.sql",
        "core/init/07_insert_user.sql",
        "core/init/08_insert_role_positions_helpdesk.sql",
        "core/init/10_insert_user_roles.sql",
        "core/agendatec/01_insert_permissions.sql",
        "core/agendatec/02_insert_user_app.sql",
        "core/agendatec/03_insert_role_permission.sql",
        "helpdesk/01_insert_permissions.sql",
        "helpdesk/02_insert_roles.sql",
        "helpdesk/03_insert_role_permission.sql",
        "helpdesk/04_insert_categories.sql",
        "helpdesk/05_insert_inventory_categories.sql",
        "helpdesk/06_insert_enhanced_inventory_categories.sql",
        "helpdesk/07_insert_position_app_perm.sql",
        "helpdesk/07_insert_peripherals_categories.sql",
        "helpdesk/08_insert_technician_user.sql",
        "helpdesk/09_insert_user_role_technician.sql",
        "helpdesk/12_insert_configure_moodle_custom_fields.sql",
        "helpdesk/13_update_monitor_resolutions.sql",
        "helpdesk/config/01_insert_permissions.sql",
        "helpdesk/config/02_seed_priorities.sql",
        "helpdesk/config/03_seed_statuses.sql",
        "helpdesk/config/04_seed_status_transitions.sql",
        "helpdesk/config/05_seed_areas.sql",
        "helpdesk/config/06_seed_notification_templates.sql",
        "helpdesk/inventory/01_add_verification_permissions.sql",
        "helpdesk/inventory/02_assign_verification_permissions.sql",
        "helpdesk/inventory/04_add_retirement_request_permissions.sql",
        "helpdesk/inventory/05_assign_retirement_permissions_to_roles.sql",
        "helpdesk/inventory/06_add_retirement_sign_permissions.sql",
        "helpdesk/inventory/07_add_retirement_comp_center_sign_permission.sql",
        "helpdesk/inventory/assign/01_add_assign_all_permission.sql",
        "helpdesk/inventory/assign/02_assign_assign_all_to_roles_and_positions.sql",
        "helpdesk/inventory_campaign/01_add_campaign_permissions.sql",
        "helpdesk/inventory_campaign/02_assign_campaign_permissions.sql",
        "helpdesk/14_fix_retirement_signer_subdirector.sql",
        "helpdesk/quickfixes_2026_06/01_reset_secretary_password_perm.sql",
        "vistetec/00_insert_app.sql",
        "vistetec/01_insert_roles.sql",
        "vistetec/02_insert_permissions.sql",
        "vistetec/03_insert_role_permissions.sql",
        # warehouse app row antes de maint (maint/08-09 la requieren), pero los
        # roles maint (dispatcher/tech_maint/coordinadores) deben existir ANTES
        # de warehouse/03 — por eso maint/00-02 se intercalan aquí.
        "warehouse/00_insert_app.sql",
        "maint/00_insert_app.sql",
        "maint/01_add_maint_permissions.sql",
        "maint/02_assign_maint_permissions_to_roles.sql",
        "warehouse/01_add_warehouse_permissions.sql",
        "warehouse/02_assign_warehouse_permissions_to_helpdesk_roles.sql",
        "warehouse/03_assign_warehouse_permissions_to_maint_roles.sql",
        "warehouse/04_assign_warehouse_to_tech_desarrollo.sql",
        "maint/03_seed_maint_categories.sql",
        "maint/05_add_stats_permissions.sql",
        "maint/06_help_permissions.sql",
        "maint/08_insert_position_app_perm.sql",
        "maint/09_assign_warehouse_user_roles.sql",
        "maint/10_add_coordinator_roles_permissions.sql",
        "maint/config/01_insert_permissions.sql",
        "maint/config/02_seed_priorities.sql",
        "maint/config/03_seed_maint_types.sql",
        "maint/config/04_seed_service_origins.sql",
        "maint/config/05_seed_areas.sql",
        "maint/config/06_seed_notification_templates.sql",
        "titulatec/00_insert_app.sql",
        "titulatec/04_insert_vinculacion_positions.sql",
        "titulatec/06_seed_catalogs.sql",
        "titulatec/07_insert_cotejo_reqs_perm.sql",
        "directory/00_insert_app.sql",
        "directory/01_insert_permissions.sql",
        "directory/02_insert_role_permission.sql",
        "directory/03_grant_directory_access.sql",
        "core/config_2026_07/subtree/01_insert_subtree_perms.sql",
        "core/config_2026_07/subtree/02_assign_subtree_perms.sql",
        "core/config_2026_07/subtree/03_fix_subdirector_head_codes.sql",
        "core/config_2026_07/01_app_colors.sql",
        "core/tasks/01_insert_permissions.sql",
        "core/tasks/02_insert_role_permissions.sql",
        "core/tasks/03_insert_task_catalog.sql",
        "core/themes/theme.sql",
        "core/themes/mundial/01_theme.sql",
        "core/themes/mundial/02_task.sql",
    ]

    base = PROJECT_ROOT / "database" / "DML"
    try:
        for rel in files:
            file_path = base / rel
            if not file_path.exists():
                click.echo(f"   ⚠️  Archivo no encontrado, se omite: {rel}")
                continue
            click.echo(f"   🔄 {rel}")
            execute_sql_file(str(file_path))
        click.echo("\n🎉 Catálogo de referencia cargado correctamente.")
    except Exception as e:
        click.echo(f"\n💥 Error cargando catálogo de referencia: {str(e)}")
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


@click.command("init-config-2026-07")
def init_config_2026_07_command():
    """Carga el revamp de configuración 2026-07 (database/DML/core/config_2026_07).

    Ejecuta en orden:
      01_app_colors.sql                          → color + icon_class canónicos por app (badges DB)
      subtree/01_insert_subtree_perms.sql        → permisos *.api.read.subtree (scope por subárbol)
      subtree/02_assign_subtree_perms.sql        → asigna esos permisos a los roles correspondientes
      subtree/03_fix_subdirector_head_codes.sql  → normaliza codes de subdirector/jefe

    Prerequisito: `alembic upgrade head` (la migración o1s2c3p4e004_app_style_columns
    agrega core_apps.color / icon_class; sin ella 01_app_colors falla).
    Todo el DML es idempotente (COALESCE / ON CONFLICT DO NOTHING).

    Nota: subtree/01 y subtree/02 son idénticos a database/DML/org_scope_2026_07/*
    (mismos permisos), así que este comando ya cubre esa carga.
    """
    click.echo("🎨 Cargando config revamp 2026-07...")

    base = PROJECT_ROOT / "database" / "DML" / "core" / "config_2026_07"
    files = [
        base / "01_app_colors.sql",
        base / "subtree" / "01_insert_subtree_perms.sql",
        base / "subtree" / "02_assign_subtree_perms.sql",
        base / "subtree" / "03_fix_subdirector_head_codes.sql",
    ]

    engine = _get_engine()

    # Guard: 01_app_colors hace UPDATE core_apps SET color/icon_class. Si la
    # migración app_style_columns (o1s2c3p4e004) no corrió, la columna no existe
    # y el script falla de forma poco clara. Abortamos con mensaje accionable.
    with engine.connect() as connection:
        has_color = connection.execute(
            text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name = 'core_apps' AND column_name = 'color'"
            )
        ).fetchone()
    if not has_color:
        click.echo(
            "❌ core_apps.color no existe. Corre primero `alembic upgrade head` "
            "(migración o1s2c3p4e004_app_style_columns) y reintenta."
        )
        raise SystemExit(1)

    try:
        for file_path in files:
            if not file_path.exists():
                click.echo(f"   ⚠️  Archivo no encontrado: {file_path.relative_to(base)}")
                continue
            click.echo(f"   🔄 Ejecutando: {file_path.relative_to(base)}")
            execute_sql_file(str(file_path))
            click.echo(f"   ✅ Completado: {file_path.name}")

        with engine.connect() as connection:
            colored = connection.execute(
                text("SELECT COUNT(*) AS count FROM core_apps WHERE color IS NOT NULL")
            ).fetchone()
            subtree = connection.execute(
                text("SELECT COUNT(*) AS count FROM core_permissions WHERE code LIKE '%.subtree'")
            ).fetchone()
        click.echo(f"\n   🎨 Apps con color asignado:   {colored.count}")
        click.echo(f"   🔐 Permisos .subtree en DB:   {subtree.count}")

        click.echo("\n🎉 Config revamp 2026-07 cargado correctamente!")

    except Exception as e:
        click.echo(f"\n💥 Error durante init-config-2026-07: {str(e)}")
        raise


@click.command("fix-org-scope-2026-08")
@click.option("--dry-run", is_flag=True, default=False,
              help="Solo muestra el estado actual; no escribe nada.")
def fix_org_scope_2026_08_command(dry_run: bool):
    """Aplica el delta de coherencia del scope organizacional (agosto 2026).

    Ejecuta database/DML/helpdesk/org_scope_fix_2026_08/, que:
      - revoca `helpdesk.tickets.api.read.all` al rol `department_head` (el jefe
        lee su departamento y su subárbol, no todo el instituto; resolve_read_scope
        da precedencia a .read.all sobre .subtree);
      - reafirma los permisos `.subtree` del rol.

    Es un DELTA a propósito: `helpdesk/03_insert_role_permission.sql` empieza
    borrando todos los permisos de helpdesk de los roles que toca, así que
    re-ejecutarlo en producción no es seguro. Idempotente: correrlo dos veces no
    hace daño.
    """
    base = PROJECT_ROOT / "database" / "DML" / "helpdesk" / "org_scope_fix_2026_08"
    files = [base / "01_department_head_scope.sql"]

    engine = _get_engine()

    def _report(label: str):
        with engine.connect() as connection:
            rows = connection.execute(text("""
                SELECT p.code
                FROM core_role_permissions rp
                JOIN core_permissions p ON p.id = rp.perm_id
                JOIN core_roles r       ON r.id = rp.role_id
                JOIN core_apps a        ON a.id = p.app_id
                WHERE r.name = 'department_head' AND a.key = 'helpdesk'
                  AND (p.code LIKE '%.subtree' OR p.code = 'helpdesk.tickets.api.read.all')
                ORDER BY p.code
            """)).fetchall()
        click.echo(f"\n   {label} department_head en helpdesk:")
        if not rows:
            click.echo("      (ninguno de los permisos relevantes)")
        for row in rows:
            click.echo(f"      - {row.code}")

    _report("ANTES —")
    if dry_run:
        click.echo("\n   (dry-run: no se escribió nada)")
        return

    try:
        for file_path in files:
            if not file_path.exists():
                click.echo(f"   ⚠️  Archivo no encontrado: {file_path}")
                continue
            click.echo(f"\n   🔄 Ejecutando: {file_path.name}")
            execute_sql_file(str(file_path))
            click.echo(f"   ✅ Completado: {file_path.name}")

        _report("DESPUÉS —")
        click.echo("\n🎉 Delta de scope organizacional aplicado.")
    except Exception as e:
        click.echo(f"\n💥 Error durante fix-org-scope-2026-08: {str(e)}")
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
core_cli.add_command(seed_reference_data_command)
core_cli.add_command(reset_database_command)
core_cli.add_command(check_database_command)
core_cli.add_command(execute_single_sql_command)
core_cli.add_command(init_themes_command)
core_cli.add_command(init_tasks_command)
core_cli.add_command(init_config_2026_07_command)
core_cli.add_command(fix_org_scope_2026_08_command)
core_cli.add_command(new_theme_mundial_command)
core_cli.add_command(mundial_refresh_command)
