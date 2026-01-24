#!/usr/bin/env python3
"""
Comandos Flask para AgendaTec - Inicialización de períodos académicos e importación de datos
"""
import csv
import os
from datetime import date, datetime
from pathlib import Path
from typing import Optional, Tuple
from zoneinfo import ZoneInfo

import click
from flask import current_app
from flask.cli import with_appcontext
from sqlalchemy import text

from itcj.apps.agendatec.models.agendatec_period_config import AgendaTecPeriodConfig
from itcj.apps.agendatec.models.period_enabled_day import PeriodEnabledDay
from itcj.apps.agendatec.models.request import Request
from itcj.core.extensions import db
from itcj.core.models.academic_period import AcademicPeriod
from itcj.core.models.app import App
from itcj.core.models.role import Role
from itcj.core.models.user import User
from itcj.core.models.user_app_role import UserAppRole
from itcj.core.services import period_service
from itcj.core.utils.security import hash_nip


def _execute_sql_scripts(scripts_dir: str) -> int:
    """
    Ejecuta todos los scripts SQL de un directorio en orden alfabético.
    
    Args:
        scripts_dir: Ruta al directorio con los scripts SQL.
        
    Returns:
        Número de scripts ejecutados.
    """
    scripts_path = Path(scripts_dir)
    
    if not scripts_path.exists():
        click.echo(f'   ⚠️  Directorio no encontrado: {scripts_dir}')
        return 0
    
    # Obtener scripts SQL ordenados
    sql_files = sorted(scripts_path.glob('*.sql'))
    
    if not sql_files:
        click.echo(f'   ℹ️  No hay scripts SQL en: {scripts_dir}')
        return 0
    
    executed = 0
    for sql_file in sql_files:
        try:
            click.echo(f'   📄 Ejecutando: {sql_file.name}')
            sql_content = sql_file.read_text(encoding='utf-8')
            db.session.execute(text(sql_content))
            executed += 1
        except Exception as e:
            click.echo(f'   ❌ Error en {sql_file.name}: {str(e)}')
            raise
    
    return executed


@click.command('seed-periods')
@with_appcontext
def seed_periods_command():
    """
    Crea períodos académicos iniciales y migra solicitudes existentes.

    Crea dos períodos:
    1. Ago-Dic 2025 (INACTIVE) - migra todas las solicitudes existentes aquí
    2. Ene-Jun 2026 (ACTIVE) - período activo para nuevas solicitudes

    Configura días habilitados: 25, 26, 27 de agosto para el primer período.
    """
    click.echo('🗓️  Iniciando creación de períodos académicos...\n')

    tz = ZoneInfo("America/Ciudad_Juarez")

    # Verificar si ya existen períodos
    existing_count = db.session.query(AcademicPeriod).count()
    if existing_count > 0:
        click.echo(f'⚠️  Ya existen {existing_count} período(s) en la base de datos.')
        if not click.confirm('¿Deseas continuar de todas formas?'):
            click.echo('❌ Operación cancelada.')
            return

    try:
        # ==================== EJECUTAR SCRIPTS SQL DE PERMISOS ====================
        click.echo('🔐 Ejecutando scripts de permisos para módulo de períodos...')
        
        # Determinar la ruta base del proyecto
        base_path = Path(current_app.root_path).parent  # itcj/ -> raíz del proyecto
        scripts_dir = base_path / 'database' / 'DML' / 'agendatec' / 'periods'
        
        scripts_executed = _execute_sql_scripts(str(scripts_dir))
        click.echo(f'   ✓ {scripts_executed} script(s) ejecutado(s)\n')

        # ==================== PERÍODO 1: Ago-Dic 2025 ====================
        click.echo('📅 Creando período: Ago-Dic 2025')

        period1 = AcademicPeriod(
            code="20253",
            name="Ago-Dic 2025",
            start_date=date(2025, 8, 19),
            end_date=date(2025, 12, 13),
            status="INACTIVE",
            created_by_id=10
        )
        db.session.add(period1)
        db.session.flush()  # Para obtener el ID

        # Crear configuración de AgendaTec para este período
        config1 = AgendaTecPeriodConfig(
            period_id=period1.id,
            student_admission_start=datetime(2025, 8, 25, 16, 0, 0, tzinfo=tz),
            student_admission_deadline=datetime(2025, 8, 27, 18, 0, 0, tzinfo=tz),
            max_cancellations_per_student=2,
            allow_drop_requests=True,
            allow_appointment_requests=True
        )
        db.session.add(config1)

        # Configurar días habilitados para Ago-Dic 2025
        enabled_days_p1 = [
            date(2025, 8, 25),
            date(2025, 8, 26),
            date(2025, 8, 27)
        ]

        for day in enabled_days_p1:
            enabled_day = PeriodEnabledDay(period_id=period1.id, day=day)
            db.session.add(enabled_day)

        click.echo(f'   ✓ Período creado (ID: {period1.id})')
        click.echo(f'   ✓ Días habilitados: {", ".join(d.strftime("%d-%b") for d in enabled_days_p1)}')

        # Migrar solicitudes existentes a este período
        requests_to_migrate = db.session.query(Request).filter(Request.period_id == None).all()

        if requests_to_migrate:
            click.echo(f'\n📦 Migrando {len(requests_to_migrate)} solicitudes existentes...')
            for req in requests_to_migrate:
                req.period_id = period1.id
            click.echo(f'   ✓ Solicitudes migradas al período "Ago-Dic 2025"')
        else:
            click.echo('   ℹ️  No hay solicitudes sin período para migrar')

        # ==================== PERÍODO 2: Ene-Jun 2026 ====================
        click.echo('\n📅 Creando período: Ene-Jun 2026')

        period2 = AcademicPeriod(
            code="20261",
            name="Ene-Jun 2026",
            start_date=date(2026, 1, 19),
            end_date=date(2026, 6, 12),
            status="ACTIVE",
            created_by_id=10
        )
        db.session.add(period2)
        db.session.flush()

        # Crear configuración de AgendaTec para este período
        config2 = AgendaTecPeriodConfig(
            period_id=period2.id,
            student_admission_start=datetime(2026, 1, 24, 0, 0, 0, tzinfo=tz),
            student_admission_deadline=datetime(2026, 1, 28, 18, 0, 0, tzinfo=tz),
            max_cancellations_per_student=2,
            allow_drop_requests=True,
            allow_appointment_requests=True
        )
        db.session.add(config2)

        # Configurar días habilitados para Ene-Jun 2026 (ejemplo: 26, 27, 28 de enero)
        enabled_days_p2 = [
            date(2026, 1, 26),
            date(2026, 1, 27),
            date(2026, 1, 28)
        ]

        for day in enabled_days_p2:
            enabled_day = PeriodEnabledDay(period_id=period2.id, day=day)
            db.session.add(enabled_day)

        click.echo(f'   ✓ Período creado (ID: {period2.id}) - ACTIVO')
        click.echo(f'   ✓ Días habilitados: {", ".join(d.strftime("%d-%b") for d in enabled_days_p2)}')

        # Commit de todos los cambios
        db.session.commit()

        click.echo('\n' + '='*60)
        click.echo('✅ Períodos académicos creados exitosamente')
        click.echo('='*60)
        click.echo(f'\n📊 Resumen:')
        click.echo(f'   • Período INACTIVO: "Ago-Dic 2025" (ID: {period1.id})')
        click.echo(f'     - Solicitudes migradas: {len(requests_to_migrate)}')
        click.echo(f'     - Días habilitados: {len(enabled_days_p1)}')
        click.echo(f'   • Período ACTIVO: "Ene-Jun 2026" (ID: {period2.id})')
        click.echo(f'     - Días habilitados: {len(enabled_days_p2)}')
        click.echo('\n💡 Notas importantes:')
        click.echo('   1. El período "Ene-Jun 2026" está ACTIVO para nuevas solicitudes')
        click.echo('   2. Todas las solicitudes antiguas se asignaron a "Ago-Dic 2025"')
        click.echo('   3. Puedes modificar los días habilitados desde la interfaz admin')
        click.echo('   4. Solo puede haber UN período ACTIVO a la vez')

    except Exception as e:
        db.session.rollback()
        click.echo(f'\n❌ Error al crear períodos: {str(e)}')
        raise


@click.command('activate-period')
@click.argument('period_id', type=int)
@with_appcontext
def activate_period_command(period_id):
    """
    Activa un período académico específico (desactiva el actual).

    Uso: flask activate-period <period_id>
    """
    from itcj.core.services.period_service import activate_period as activate_service

    click.echo(f'🔄 Activando período ID: {period_id}...')

    try:
        # Usar el servicio de activación
        period = activate_service(period_id)

        if period:
            config = period_service.get_agendatec_config(period.id)
            click.echo(f'✅ Período "{period.name}" activado correctamente')
            click.echo(f'   • ID: {period.id}')
            click.echo(f'   • Rango: {period.start_date} a {period.end_date}')
            if config:
                click.echo(f'   • Admisión hasta: {config.student_admission_deadline}')
        else:
            click.echo(f'❌ No se pudo activar el período ID: {period_id}')

    except Exception as e:
        click.echo(f'❌ Error: {str(e)}')
        raise


@click.command('list-periods')
@with_appcontext
def list_periods_command():
    """Lista todos los períodos académicos."""
    click.echo('📋 Períodos Académicos:\n')

    periods = db.session.query(AcademicPeriod).order_by(AcademicPeriod.start_date.desc()).all()

    if not periods:
        click.echo('   ℹ️  No hay períodos registrados')
        click.echo('   💡 Ejecuta: flask seed-periods')
        return

    for p in periods:
        status_emoji = {
            'ACTIVE': '🟢',
            'INACTIVE': '⚪',
            'ARCHIVED': '📦'
        }.get(p.status, '❓')

        enabled_days_count = db.session.query(PeriodEnabledDay).filter_by(period_id=p.id).count()
        requests_count = db.session.query(Request).filter_by(period_id=p.id).count()
        config = period_service.get_agendatec_config(p.id)

        click.echo(f'{status_emoji} {p.name} (ID: {p.id})')
        click.echo(f'   Estado: {p.status}')
        click.echo(f'   Rango: {p.start_date} → {p.end_date}')
        if config:
            click.echo(f'   Admisión hasta: {config.student_admission_deadline}')
        click.echo(f'   Días habilitados: {enabled_days_count}')
        click.echo(f'   Solicitudes: {requests_count}')
        click.echo()


def register_agendatec_commands(app):
    """Registra todos los comandos de AgendaTec en la aplicación Flask."""
    app.cli.add_command(seed_periods_command)
    app.cli.add_command(activate_period_command)
    app.cli.add_command(list_periods_command)
    app.cli.add_command(import_students_command)
    app.cli.add_command(sync_students_agendatec_command)


# ═══════════════════════════════════════════════════════════════════════════════
# IMPORTACIÓN DE ESTUDIANTES
# ═══════════════════════════════════════════════════════════════════════════════


def _build_full_name(ap_pat: str, ap_mat: str, nombre: str) -> str:
    """Construye el nombre completo desde las partes."""
    parts = [ap_pat.strip(), ap_mat.strip(), nombre.strip()]
    return " ".join(p for p in parts if p)


def _normalize_str(s: Optional[str]) -> str:
    """Normaliza una cadena eliminando espacios."""
    return (s or "").strip()


def _parse_student_row(row: dict) -> Tuple[dict, list]:
    """
    Parsea una fila del CSV de estudiantes.
    
    Args:
        row: Diccionario con los datos de la fila.
        
    Returns:
        Tupla con (payload para User, lista de warnings).
    """
    warnings = []

    no_de_control = _normalize_str(row.get("no_de_control"))
    apellido_paterno = _normalize_str(row.get("apellido_paterno"))
    apellido_materno = _normalize_str(row.get("apellido_materno"))
    nombre_alumno = _normalize_str(row.get("nombre_alumno"))
    nip = _normalize_str(row.get("nip"))

    if not nombre_alumno and not (apellido_paterno or apellido_materno):
        warnings.append("Nombre vacío")
    if not nip:
        warnings.append("NIP vacío")

    full_name = _build_full_name(apellido_paterno, apellido_materno, nombre_alumno)

    username: Optional[str] = None
    control_number: Optional[str] = None

    if no_de_control:
        first = no_de_control[0]
        if first.isalpha():
            username = no_de_control.upper()
        else:
            control_number = no_de_control.upper()
            if len(control_number) != 8:
                warnings.append(f"control_number '{control_number}' con longitud != 8")

    payload = {
        "role_id": 1,  # estudiantes
        "username": username or None,
        "control_number": control_number or None,
        "password_hash": hash_nip(nip) if nip else None,
        "full_name": full_name or None,
        "is_active": True,
    }
    return payload, warnings


def _upsert_student(payload: dict, dry_run: bool = False) -> Tuple[str, Optional[int]]:
    """
    Inserta o actualiza un estudiante.
    
    Args:
        payload: Datos del estudiante.
        dry_run: Si es True, no realiza cambios en la base de datos.
        
    Returns:
        Tupla con (status: 'created'|'updated'|'skipped', user_id).
    """
    username = payload.get("username")
    control_number = payload.get("control_number")

    existing = None
    if control_number:
        existing = User.query.filter_by(control_number=control_number).first()
    elif username:
        existing = User.query.filter_by(username=username).first()

    if existing:
        changed = False
        for field in ("full_name", "password_hash", "role_id", "is_active"):
            val = payload.get(field)
            if val is not None and getattr(existing, field) != val:
                setattr(existing, field, val)
                changed = True

        if username and existing.username != username:
            existing.username = username
            changed = True
        if control_number and existing.control_number != control_number:
            existing.control_number = control_number
            changed = True

        if changed and not dry_run:
            db.session.add(existing)
        return ("updated" if changed else "skipped", existing.id)
    else:
        user = User(
            role_id=payload["role_id"],
            username=payload.get("username"),
            control_number=payload.get("control_number"),
            password_hash=payload.get("password_hash"),
            full_name=payload.get("full_name") or "SIN NOMBRE",
            is_active=payload.get("is_active", True),
        )
        if not dry_run:
            db.session.add(user)
        return ("created", None)


@click.command("import-students")
@click.option(
    "--csv-path",
    default="database/CSV/Alumnos Activos 2026.csv",
    help="Ruta al archivo CSV (default: database/CSV/Alumnos Activos 2026.csv)",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Simular sin escribir cambios a la base de datos",
)
@click.option(
    "--commit-every",
    type=int,
    default=500,
    help="Confirma cada N operaciones (default: 500)",
)
@with_appcontext
def import_students_command(csv_path: str, dry_run: bool, commit_every: int):
    """
    Importa/actualiza estudiantes desde un archivo CSV.

    El CSV debe tener los siguientes encabezados (separados por punto y coma):
    - no_de_control: Número de control o username
    - apellido_paterno: Apellido paterno
    - apellido_materno: Apellido materno
    - nombre_alumno: Nombre(s)
    - nip: Contraseña (NIP)

    Otros campos opcionales: nombre_carrera, carrera, reticula, estatus_alumno

    Ejemplos:
        flask import-students
        flask import-students --csv-path mi_archivo.csv
        flask import-students --dry-run
    """
    click.echo(f"📚 Importando estudiantes desde: {csv_path}")
    if dry_run:
        click.echo("⚠️  Modo DRY-RUN: No se realizarán cambios")
    click.echo()

    created = updated = skipped = warnings_total = 0
    row_idx = 0
    to_commit = 0

    try:
        with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f, delimiter=";")
            
            # Validar encabezados requeridos
            required_headers = {
                "no_de_control",
                "apellido_paterno",
                "apellido_materno",
                "nombre_alumno",
                "nip",
            }
            actual_headers = set(reader.fieldnames or [])
            missing_headers = required_headers - actual_headers
            
            if missing_headers:
                click.echo(f"❌ El CSV no tiene los encabezados esperados.")
                click.echo(f"   Faltan: {', '.join(sorted(missing_headers))}")
                return

            for row in reader:
                row_idx += 1
                payload, warns = _parse_student_row(row)
                
                if warns:
                    warnings_total += len(warns)
                    click.echo(f"[WARN fila {row_idx}] " + " | ".join(warns))

                # Validar datos mínimos
                if not payload.get("username") and not payload.get("control_number"):
                    click.echo(f"[SKIP fila {row_idx}] Sin username/control_number")
                    skipped += 1
                    continue
                if not payload.get("password_hash"):
                    click.echo(f"[SKIP fila {row_idx}] Sin NIP")
                    skipped += 1
                    continue

                status, _ = _upsert_student(payload, dry_run=dry_run)
                if status == "created":
                    created += 1
                    to_commit += 1
                elif status == "updated":
                    updated += 1
                    to_commit += 1
                else:
                    skipped += 1

                if not dry_run and to_commit >= commit_every:
                    db.session.commit()
                    to_commit = 0
                    click.echo(f"   💾 Commit parcial ({row_idx} filas procesadas)")

            if not dry_run and to_commit > 0:
                db.session.commit()

        # Resumen
        click.echo()
        click.echo("=" * 50)
        click.echo("📊 RESUMEN DE IMPORTACIÓN")
        click.echo("=" * 50)
        click.echo(f"   Archivo: {csv_path}")
        click.echo(f"   Filas procesadas: {row_idx}")
        click.echo(f"   ✅ Creados: {created}")
        click.echo(f"   🔄 Actualizados: {updated}")
        click.echo(f"   ⏭️  Omitidos: {skipped}")
        click.echo(f"   ⚠️  Warnings: {warnings_total}")
        
        if dry_run:
            click.echo()
            click.echo("💡 DRY-RUN: No se realizaron cambios en la base de datos")
        else:
            click.echo()
            click.echo("✅ Importación completada exitosamente")

    except FileNotFoundError:
        click.echo(f"❌ Error: No se encontró el archivo '{csv_path}'")
    except Exception as e:
        db.session.rollback()
        click.echo(f"❌ Error durante la importación: {str(e)}")
        raise


# ═══════════════════════════════════════════════════════════════════════════════
# SINCRONIZACIÓN DE ESTUDIANTES AGENDATEC
# ═══════════════════════════════════════════════════════════════════════════════

def _get_or_create_student_role() -> Tuple[Optional[int], Optional[int]]:
    """
    Obtiene los IDs de la app 'agendatec' y el rol 'student'.
    Si el rol 'student' no existe, lo crea.
    
    Returns:
        Tupla (app_id, role_id) o (None, None) si la app no existe.
    """
    # Buscar la app agendatec
    app = App.query.filter_by(key='agendatec').first()
    if not app:
        return None, None
    
    # Buscar o crear el rol student
    role = Role.query.filter_by(name='student').first()
    if not role:
        role = Role(name='student')
        db.session.add(role)
        db.session.flush()
    
    return app.id, role.id


def _parse_student_row_v2(row: dict) -> Tuple[dict, list]:
    """
    Parsea una fila del CSV de estudiantes (versión 2 con nombres divididos).
    
    Args:
        row: Diccionario con los datos de la fila.
        
    Returns:
        Tupla con (payload para User, lista de warnings).
    """
    warnings = []

    no_de_control = _normalize_str(row.get("no_de_control"))
    apellido_paterno = _normalize_str(row.get("apellido_paterno"))
    apellido_materno = _normalize_str(row.get("apellido_materno"))
    nombre_alumno = _normalize_str(row.get("nombre_alumno"))
    nip = _normalize_str(row.get("nip"))
    curp = _normalize_str(row.get("curp_alumno"))

    if not nombre_alumno:
        warnings.append("Nombre vacío")
    if not apellido_paterno:
        warnings.append("Apellido paterno vacío")
    if not nip:
        warnings.append("NIP vacío")

    # Construir identificadores
    username: Optional[str] = None
    control_number: Optional[str] = None

    if no_de_control:
        first = no_de_control[0]
        if first.isalpha():
            username = no_de_control.upper()
        else:
            control_number = no_de_control.upper()
            if len(control_number) != 8:
                warnings.append(f"control_number '{control_number}' con longitud != 8")

    payload = {
        "username": username or None,
        "control_number": control_number or None,
        "password_hash": hash_nip(nip) if nip else None,
        "first_name": nombre_alumno.title() if nombre_alumno else "SIN NOMBRE",
        "last_name": apellido_paterno.title() if apellido_paterno else "SIN APELLIDO",
        "middle_name": apellido_materno.title() if apellido_materno else None,
        "is_active": True,
    }
    return payload, warnings


def _upsert_student_v2(payload: dict, app_id: int, role_id: int, dry_run: bool = False) -> Tuple[str, Optional[int]]:
    """
    Inserta o actualiza un estudiante y asigna rol en agendatec.
    
    Args:
        payload: Datos del estudiante.
        app_id: ID de la app agendatec.
        role_id: ID del rol student.
        dry_run: Si es True, no realiza cambios en la base de datos.
        
    Returns:
        Tupla con (status: 'created'|'updated'|'skipped', user_id).
    """
    username = payload.get("username")
    control_number = payload.get("control_number")

    existing = None
    if control_number:
        existing = User.query.filter_by(control_number=control_number).first()
    elif username:
        existing = User.query.filter_by(username=username).first()

    user_id = None
    status = "skipped"

    if existing:
        user_id = existing.id
        changed = False
        
        # Actualizar campos si cambiaron
        for field in ("first_name", "last_name", "middle_name", "password_hash"):
            val = payload.get(field)
            if val is not None and getattr(existing, field, None) != val:
                setattr(existing, field, val)
                changed = True
        
        # Asegurar que esté activo
        if not existing.is_active:
            existing.is_active = True
            changed = True

        if username and existing.username != username:
            existing.username = username
            changed = True
        if control_number and existing.control_number != control_number:
            existing.control_number = control_number
            changed = True

        if changed:
            status = "updated"
            if not dry_run:
                db.session.add(existing)
    else:
        # Crear nuevo usuario
        user = User(
            username=payload.get("username"),
            control_number=payload.get("control_number"),
            password_hash=payload.get("password_hash"),
            first_name=payload.get("first_name") or "SIN NOMBRE",
            last_name=payload.get("last_name") or "SIN APELLIDO",
            middle_name=payload.get("middle_name"),
            is_active=True,
        )
        if not dry_run:
            db.session.add(user)
            db.session.flush()  # Para obtener el ID
            user_id = user.id
        status = "created"
    
    # Asignar rol de student para agendatec si no lo tiene
    if user_id and not dry_run:
        existing_role = UserAppRole.query.filter_by(
            user_id=user_id,
            app_id=app_id,
            role_id=role_id
        ).first()
        
        if not existing_role:
            user_app_role = UserAppRole(
                user_id=user_id,
                app_id=app_id,
                role_id=role_id
            )
            db.session.add(user_app_role)
    
    return status, user_id


@click.command("sync-students-agendatec")
@click.option(
    "--csv-path",
    default="database/CSV/Alumnos Activos 2026.csv",
    help="Ruta al archivo CSV (default: database/CSV/Alumnos Activos 2026.csv)",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Simular sin escribir cambios a la base de datos",
)
@click.option(
    "--commit-every",
    type=int,
    default=500,
    help="Confirma cada N operaciones (default: 500)",
)
@click.option(
    "--deactivate-missing/--no-deactivate-missing",
    default=True,
    help="Desactivar usuarios no encontrados en el CSV (default: True)",
)
@with_appcontext
def sync_students_agendatec_command(csv_path: str, dry_run: bool, commit_every: int, deactivate_missing: bool):
    """
    Sincroniza estudiantes desde CSV y asigna rol 'student' para AgendaTec.

    Este comando:
    1. Importa/actualiza estudiantes desde el CSV
    2. Asigna el rol 'student' para la app 'agendatec' a cada estudiante
    3. Desactiva estudiantes que tienen rol en agendatec pero NO están en el CSV

    El CSV debe tener los siguientes encabezados (separados por coma):
    - no_de_control: Número de control
    - apellido_paterno: Apellido paterno
    - apellido_materno: Apellido materno
    - nombre_alumno: Nombre(s)
    - nip: Contraseña (NIP)

    Ejemplos:
        flask sync-students-agendatec
        flask sync-students-agendatec --dry-run
        flask sync-students-agendatec --no-deactivate-missing
    """
    click.echo("=" * 60)
    click.echo("🎓 SINCRONIZACIÓN DE ESTUDIANTES - AGENDATEC")
    click.echo("=" * 60)
    click.echo(f"📁 Archivo: {csv_path}")
    if dry_run:
        click.echo("⚠️  Modo DRY-RUN: No se realizarán cambios")
    click.echo()

    # Obtener IDs de app y rol
    app_id, role_id = _get_or_create_student_role()
    if not app_id:
        click.echo("❌ Error: No se encontró la app 'agendatec' en la base de datos")
        return
    
    click.echo(f"✓ App 'agendatec' ID: {app_id}")
    click.echo(f"✓ Rol 'student' ID: {role_id}")
    click.echo()

    created = updated = skipped = warnings_total = 0
    row_idx = 0
    to_commit = 0
    processed_control_numbers = set()
    processed_usernames = set()

    try:
        # ==================== FASE 1: IMPORTAR ESTUDIANTES ====================
        click.echo("📥 FASE 1: Importando estudiantes del CSV...")
        click.echo("-" * 40)
        
        with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f, delimiter=",")
            
            # Validar encabezados requeridos
            required_headers = {
                "no_de_control",
                "apellido_paterno",
                "apellido_materno",
                "nombre_alumno",
                "nip",
            }
            actual_headers = set(reader.fieldnames or [])
            missing_headers = required_headers - actual_headers
            
            if missing_headers:
                click.echo(f"❌ El CSV no tiene los encabezados esperados.")
                click.echo(f"   Faltan: {', '.join(sorted(missing_headers))}")
                click.echo(f"   Encontrados: {', '.join(sorted(actual_headers))}")
                return

            for row in reader:
                row_idx += 1
                payload, warns = _parse_student_row_v2(row)
                
                if warns:
                    warnings_total += len(warns)
                    if row_idx <= 10:  # Solo mostrar primeros warnings
                        click.echo(f"   [WARN fila {row_idx}] " + " | ".join(warns))

                # Validar datos mínimos
                if not payload.get("username") and not payload.get("control_number"):
                    if row_idx <= 10:
                        click.echo(f"   [SKIP fila {row_idx}] Sin username/control_number")
                    skipped += 1
                    continue
                if not payload.get("password_hash"):
                    if row_idx <= 10:
                        click.echo(f"   [SKIP fila {row_idx}] Sin NIP")
                    skipped += 1
                    continue

                # Registrar para la fase de desactivación
                if payload.get("control_number"):
                    processed_control_numbers.add(payload["control_number"])
                if payload.get("username"):
                    processed_usernames.add(payload["username"])

                status, _ = _upsert_student_v2(payload, app_id, role_id, dry_run=dry_run)
                if status == "created":
                    created += 1
                    to_commit += 1
                elif status == "updated":
                    updated += 1
                    to_commit += 1
                else:
                    skipped += 1

                if not dry_run and to_commit >= commit_every:
                    db.session.commit()
                    to_commit = 0
                    click.echo(f"   💾 Commit parcial ({row_idx} filas procesadas)")

            if not dry_run and to_commit > 0:
                db.session.commit()

        click.echo()
        click.echo(f"   ✅ Filas procesadas: {row_idx}")
        click.echo(f"   ✅ Creados: {created}")
        click.echo(f"   🔄 Actualizados: {updated}")
        click.echo(f"   ⏭️  Omitidos: {skipped}")
        
        # ==================== FASE 2: DESACTIVAR AUSENTES ====================
        if deactivate_missing:
            click.echo()
            click.echo("🔍 FASE 2: Buscando estudiantes a desactivar...")
            click.echo("-" * 40)
            
            # Buscar todos los usuarios con rol student en agendatec
            students_in_agendatec = db.session.query(User).join(
                UserAppRole, User.id == UserAppRole.user_id
            ).filter(
                UserAppRole.app_id == app_id,
                UserAppRole.role_id == role_id,
                User.is_active == True
            ).all()
            
            deactivated = 0
            for student in students_in_agendatec:
                # Verificar si está en el CSV
                in_csv = False
                if student.control_number and student.control_number in processed_control_numbers:
                    in_csv = True
                elif student.username and student.username in processed_usernames:
                    in_csv = True
                
                if not in_csv:
                    if not dry_run:
                        student.is_active = False
                        db.session.add(student)
                    deactivated += 1
                    if deactivated <= 20:  # Mostrar primeros 20
                        identifier = student.control_number or student.username
                        click.echo(f"   ❌ Desactivando: {identifier} - {student.full_name}")
            
            if not dry_run and deactivated > 0:
                db.session.commit()
            
            if deactivated > 20:
                click.echo(f"   ... y {deactivated - 20} más")
            
            click.echo()
            click.echo(f"   📊 Estudiantes activos en AgendaTec: {len(students_in_agendatec)}")
            click.echo(f"   🚫 Desactivados (no en CSV): {deactivated}")
        
        # ==================== RESUMEN FINAL ====================
        click.echo()
        click.echo("=" * 60)
        click.echo("📊 RESUMEN FINAL")
        click.echo("=" * 60)
        click.echo(f"   Archivo procesado: {csv_path}")
        click.echo(f"   Total filas CSV: {row_idx}")
        click.echo(f"   ✅ Estudiantes creados: {created}")
        click.echo(f"   🔄 Estudiantes actualizados: {updated}")
        click.echo(f"   ⏭️  Filas omitidas: {skipped}")
        click.echo(f"   ⚠️  Warnings totales: {warnings_total}")
        if deactivate_missing:
            click.echo(f"   🚫 Estudiantes desactivados: {deactivated}")
        
        if dry_run:
            click.echo()
            click.echo("💡 DRY-RUN: No se realizaron cambios en la base de datos")
        else:
            click.echo()
            click.echo("✅ Sincronización completada exitosamente")

    except FileNotFoundError:
        click.echo(f"❌ Error: No se encontró el archivo '{csv_path}'")
    except Exception as e:
        db.session.rollback()
        click.echo(f"❌ Error durante la sincronización: {str(e)}")
        raise

