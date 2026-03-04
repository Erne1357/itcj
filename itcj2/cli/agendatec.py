#!/usr/bin/env python3
"""
Comandos CLI de AgendaTec para itcj2 — sin Flask context.
Equivalente a itcj/apps/agendatec/commands.py.
"""
import csv
from datetime import date, datetime
from pathlib import Path
from typing import Optional, Tuple
from zoneinfo import ZoneInfo

import click
from sqlalchemy import text

PROJECT_ROOT = Path(__file__).parent.parent.parent


def _execute_sql_scripts(db, scripts_dir: str) -> int:
    """Ejecuta todos los scripts SQL de un directorio en orden alfabético."""
    scripts_path = Path(scripts_dir)
    if not scripts_path.exists():
        click.echo(f"   ⚠️  Directorio no encontrado: {scripts_dir}")
        return 0

    sql_files = sorted(scripts_path.glob("*.sql"))
    if not sql_files:
        click.echo(f"   ℹ️  No hay scripts SQL en: {scripts_dir}")
        return 0

    executed = 0
    for sql_file in sql_files:
        try:
            click.echo(f"   📄 Ejecutando: {sql_file.name}")
            sql_content = sql_file.read_text(encoding="utf-8")
            db.execute(text(sql_content))
            executed += 1
        except Exception as e:
            click.echo(f"   ❌ Error en {sql_file.name}: {str(e)}")
            raise
    return executed


@click.command("seed-periods")
def seed_periods_command():
    """
    Crea períodos académicos iniciales y migra solicitudes existentes.

    Crea dos períodos:
    1. Ago-Dic 2025 (INACTIVE) — migra todas las solicitudes existentes
    2. Ene-Jun 2026 (ACTIVE) — período activo para nuevas solicitudes
    """
    from itcj2.apps.agendatec.models import AgendaTecPeriodConfig, PeriodEnabledDay, Request
    from itcj2.core.models import AcademicPeriod
    from itcj2.database import SessionLocal

    click.echo("🗓️  Iniciando creación de períodos académicos...\n")
    tz = ZoneInfo("America/Ciudad_Juarez")

    with SessionLocal() as db:
        existing_count = db.query(AcademicPeriod).count()
        if existing_count > 0:
            click.echo(f"⚠️  Ya existen {existing_count} período(s) en la base de datos.")
            if not click.confirm("¿Deseas continuar de todas formas?"):
                click.echo("❌ Operación cancelada.")
                return

        try:
            scripts_dir = PROJECT_ROOT / "database" / "DML" / "agendatec" / "periods"
            click.echo("🔐 Ejecutando scripts de permisos para módulo de períodos...")
            scripts_executed = _execute_sql_scripts(db, str(scripts_dir))
            click.echo(f"   ✓ {scripts_executed} script(s) ejecutado(s)\n")

            # Período 1: Ago-Dic 2025
            click.echo("📅 Creando período: Ago-Dic 2025")
            period1 = AcademicPeriod(
                code="20253",
                name="Ago-Dic 2025",
                start_date=date(2025, 8, 19),
                end_date=date(2025, 12, 13),
                status="INACTIVE",
                created_by_id=10,
            )
            db.add(period1)
            db.flush()

            config1 = AgendaTecPeriodConfig(
                period_id=period1.id,
                student_admission_start=datetime(2025, 8, 25, 16, 0, 0, tzinfo=tz),
                student_admission_deadline=datetime(2025, 8, 27, 18, 0, 0, tzinfo=tz),
                max_cancellations_per_student=2,
                allow_drop_requests=True,
                allow_appointment_requests=True,
            )
            db.add(config1)

            enabled_days_p1 = [date(2025, 8, 25), date(2025, 8, 26), date(2025, 8, 27)]
            for day in enabled_days_p1:
                db.add(PeriodEnabledDay(period_id=period1.id, day=day))

            click.echo(f"   ✓ Período creado (ID: {period1.id})")

            requests_to_migrate = db.query(Request).filter(Request.period_id == None).all()  # noqa: E711
            if requests_to_migrate:
                click.echo(f"\n📦 Migrando {len(requests_to_migrate)} solicitudes existentes...")
                for req in requests_to_migrate:
                    req.period_id = period1.id
            else:
                click.echo("   ℹ️  No hay solicitudes sin período para migrar")

            # Período 2: Ene-Jun 2026
            click.echo("\n📅 Creando período: Ene-Jun 2026")
            period2 = AcademicPeriod(
                code="20261",
                name="Ene-Jun 2026",
                start_date=date(2026, 1, 19),
                end_date=date(2026, 6, 12),
                status="ACTIVE",
                created_by_id=10,
            )
            db.add(period2)
            db.flush()

            config2 = AgendaTecPeriodConfig(
                period_id=period2.id,
                student_admission_start=datetime(2026, 1, 24, 0, 0, 0, tzinfo=tz),
                student_admission_deadline=datetime(2026, 1, 28, 18, 0, 0, tzinfo=tz),
                max_cancellations_per_student=2,
                allow_drop_requests=True,
                allow_appointment_requests=True,
            )
            db.add(config2)

            enabled_days_p2 = [date(2026, 1, 26), date(2026, 1, 27), date(2026, 1, 28)]
            for day in enabled_days_p2:
                db.add(PeriodEnabledDay(period_id=period2.id, day=day))

            click.echo(f"   ✓ Período creado (ID: {period2.id}) — ACTIVO")

            db.commit()

            click.echo("\n✅ Períodos académicos creados exitosamente")

        except Exception as e:
            db.rollback()
            click.echo(f"\n❌ Error al crear períodos: {str(e)}")
            raise


@click.command("activate-period")
@click.argument("period_id", type=int)
def activate_period_command(period_id):
    """Activa un período académico específico (desactiva el actual)."""
    from itcj2.core.services.period_service import activate_period, get_agendatec_config
    from itcj2.database import SessionLocal

    click.echo(f"🔄 Activando período ID: {period_id}...")
    with SessionLocal() as db:
        try:
            period = activate_period(db, period_id)
            if period:
                config = get_agendatec_config(db, period.id)
                click.echo(f"✅ Período \"{period.name}\" activado correctamente")
                click.echo(f"   • ID: {period.id}")
                click.echo(f"   • Rango: {period.start_date} a {period.end_date}")
                if config:
                    click.echo(f"   • Admisión hasta: {config.student_admission_deadline}")
            else:
                click.echo(f"❌ No se pudo activar el período ID: {period_id}")
        except Exception as e:
            click.echo(f"❌ Error: {str(e)}")
            raise


@click.command("list-periods")
def list_periods_command():
    """Lista todos los períodos académicos."""
    from itcj2.apps.agendatec.models import PeriodEnabledDay, Request
    from itcj2.core.models import AcademicPeriod
    from itcj2.core.services.period_service import get_agendatec_config
    from itcj2.database import SessionLocal

    click.echo("📋 Períodos Académicos:\n")
    with SessionLocal() as db:
        periods = db.query(AcademicPeriod).order_by(AcademicPeriod.start_date.desc()).all()
        if not periods:
            click.echo("   ℹ️  No hay períodos registrados")
            return

        for p in periods:
            status_emoji = {"ACTIVE": "🟢", "INACTIVE": "⚪", "ARCHIVED": "📦"}.get(p.status, "❓")
            enabled_count = db.query(PeriodEnabledDay).filter_by(period_id=p.id).count()
            req_count = db.query(Request).filter_by(period_id=p.id).count()
            config = get_agendatec_config(db, p.id)

            click.echo(f"{status_emoji} {p.name} (ID: {p.id})")
            click.echo(f"   Estado: {p.status}")
            click.echo(f"   Rango: {p.start_date} → {p.end_date}")
            if config:
                click.echo(f"   Admisión hasta: {config.student_admission_deadline}")
            click.echo(f"   Días habilitados: {enabled_count}")
            click.echo(f"   Solicitudes: {req_count}")
            click.echo()


def _normalize_str(s: Optional[str]) -> str:
    return (s or "").strip()


def _build_full_name(ap_pat, ap_mat, nombre):
    parts = [ap_pat.strip(), ap_mat.strip(), nombre.strip()]
    return " ".join(p for p in parts if p)


def _parse_student_row(row: dict) -> Tuple[dict, list]:
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
    username = control_number = None

    if no_de_control:
        first = no_de_control[0]
        if first.isalpha():
            username = no_de_control.upper()
        else:
            control_number = no_de_control.upper()
            if len(control_number) != 8:
                warnings.append(f"control_number '{control_number}' longitud != 8")

    from itcj2.core.utils.security import hash_nip

    payload = {
        "role_id": 1,
        "username": username,
        "control_number": control_number,
        "password_hash": hash_nip(nip) if nip else None,
        "full_name": full_name or None,
        "is_active": True,
    }
    return payload, warnings


def _upsert_student(db, payload: dict, dry_run: bool = False) -> Tuple[str, Optional[int]]:
    from itcj2.core.models import User

    username = payload.get("username")
    control_number = payload.get("control_number")

    existing = None
    if control_number:
        existing = db.query(User).filter_by(control_number=control_number).first()
    elif username:
        existing = db.query(User).filter_by(username=username).first()

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
            db.add(existing)
        return ("updated" if changed else "skipped", existing.id)
    else:
        user = __import__("itcj2.core.models", fromlist=["User"]).User(
            role_id=payload["role_id"],
            username=payload.get("username"),
            control_number=payload.get("control_number"),
            password_hash=payload.get("password_hash"),
            full_name=payload.get("full_name") or "SIN NOMBRE",
            is_active=payload.get("is_active", True),
        )
        if not dry_run:
            db.add(user)
        return ("created", None)


@click.command("import-students")
@click.option("--csv-path", default="database/CSV/Alumnos Activos 2026.csv")
@click.option("--dry-run", is_flag=True)
@click.option("--commit-every", type=int, default=500)
def import_students_command(csv_path: str, dry_run: bool, commit_every: int):
    """Importa/actualiza estudiantes desde un archivo CSV."""
    from itcj2.database import SessionLocal

    full_path = Path(csv_path) if Path(csv_path).is_absolute() else PROJECT_ROOT / csv_path
    click.echo(f"📚 Importando estudiantes desde: {full_path}")
    if dry_run:
        click.echo("⚠️  Modo DRY-RUN: No se realizarán cambios")

    created = updated = skipped = warnings_total = 0
    row_idx = 0
    to_commit = 0

    with SessionLocal() as db:
        try:
            with open(full_path, "r", encoding="utf-8-sig", newline="") as f:
                reader = csv.DictReader(f, delimiter=";")
                required = {"no_de_control", "apellido_paterno", "apellido_materno", "nombre_alumno", "nip"}
                missing = required - set(reader.fieldnames or [])
                if missing:
                    click.echo(f"❌ Faltan encabezados: {', '.join(sorted(missing))}")
                    return

                for row in reader:
                    row_idx += 1
                    payload, warns = _parse_student_row(row)
                    if warns:
                        warnings_total += len(warns)
                        click.echo(f"[WARN fila {row_idx}] " + " | ".join(warns))

                    if not payload.get("username") and not payload.get("control_number"):
                        skipped += 1
                        continue
                    if not payload.get("password_hash"):
                        skipped += 1
                        continue

                    status, _ = _upsert_student(db, payload, dry_run=dry_run)
                    if status == "created":
                        created += 1
                        to_commit += 1
                    elif status == "updated":
                        updated += 1
                        to_commit += 1
                    else:
                        skipped += 1

                    if not dry_run and to_commit >= commit_every:
                        db.commit()
                        to_commit = 0
                        click.echo(f"   💾 Commit parcial ({row_idx} filas)")

                if not dry_run and to_commit > 0:
                    db.commit()

            click.echo(f"\n✅ Creados: {created} | Actualizados: {updated} | Omitidos: {skipped} | Warnings: {warnings_total}")

        except FileNotFoundError:
            click.echo(f"❌ Archivo no encontrado: {full_path}")
        except Exception as e:
            db.rollback()
            click.echo(f"❌ Error: {str(e)}")
            raise


def _parse_student_row_v2(row: dict) -> Tuple[dict, list]:
    warnings = []
    no_de_control = _normalize_str(row.get("no_de_control"))
    apellido_paterno = _normalize_str(row.get("apellido_paterno"))
    apellido_materno = _normalize_str(row.get("apellido_materno"))
    nombre_alumno = _normalize_str(row.get("nombre_alumno"))
    nip = _normalize_str(row.get("nip"))

    if not nombre_alumno:
        warnings.append("Nombre vacío")
    if not apellido_paterno:
        warnings.append("Apellido paterno vacío")
    if not nip:
        warnings.append("NIP vacío")

    username = control_number = None
    if no_de_control:
        first = no_de_control[0]
        if first.isalpha():
            username = no_de_control.upper()
        else:
            control_number = no_de_control.upper()
            if len(control_number) != 8:
                warnings.append(f"control_number '{control_number}' longitud != 8")

    from itcj2.core.utils.security import hash_nip

    payload = {
        "username": username,
        "control_number": control_number,
        "password_hash": hash_nip(nip) if nip else None,
        "first_name": nombre_alumno.title() if nombre_alumno else "SIN NOMBRE",
        "last_name": apellido_paterno.title() if apellido_paterno else "SIN APELLIDO",
        "middle_name": apellido_materno.title() if apellido_materno else None,
        "is_active": True,
    }
    return payload, warnings


def _upsert_student_v2(db, payload: dict, app_id: int, role_id: int, dry_run: bool = False) -> Tuple[str, Optional[int]]:
    from itcj2.core.models import User, UserAppRole

    username = payload.get("username")
    control_number = payload.get("control_number")

    existing = None
    if control_number:
        existing = db.query(User).filter_by(control_number=control_number).first()
    elif username:
        existing = db.query(User).filter_by(username=username).first()

    user_id = None
    status = "skipped"

    if existing:
        user_id = existing.id
        changed = False
        for field in ("first_name", "last_name", "middle_name", "password_hash"):
            val = payload.get(field)
            if val is not None and getattr(existing, field, None) != val:
                setattr(existing, field, val)
                changed = True
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
                db.add(existing)
    else:
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
            db.add(user)
            db.flush()
            user_id = user.id
        status = "created"

    if user_id and not dry_run:
        existing_role = db.query(UserAppRole).filter_by(
            user_id=user_id, app_id=app_id, role_id=role_id
        ).first()
        if not existing_role:
            db.add(UserAppRole(user_id=user_id, app_id=app_id, role_id=role_id))

    return status, user_id


def _get_or_create_student_role(db) -> Tuple[Optional[int], Optional[int]]:
    from itcj2.core.models import App, Role

    app = db.query(App).filter_by(key="agendatec").first()
    if not app:
        return None, None
    role = db.query(Role).filter_by(name="student").first()
    if not role:
        role = Role(name="student")
        db.add(role)
        db.flush()
    return app.id, role.id


@click.command("sync-students-agendatec")
@click.option("--csv-path", default="database/CSV/Alumnos Activos 2026.csv")
@click.option("--dry-run", is_flag=True)
@click.option("--commit-every", type=int, default=500)
@click.option("--deactivate-missing/--no-deactivate-missing", default=True)
def sync_students_agendatec_command(csv_path, dry_run, commit_every, deactivate_missing):
    """Sincroniza estudiantes desde CSV y asigna rol 'student' para AgendaTec."""
    from itcj2.core.models import User, UserAppRole
    from itcj2.database import SessionLocal

    full_path = Path(csv_path) if Path(csv_path).is_absolute() else PROJECT_ROOT / csv_path
    click.echo("=" * 60)
    click.echo("🎓 SINCRONIZACIÓN DE ESTUDIANTES — AGENDATEC")
    click.echo("=" * 60)
    click.echo(f"📁 Archivo: {full_path}")
    if dry_run:
        click.echo("⚠️  Modo DRY-RUN")

    created = updated = skipped = warnings_total = 0
    row_idx = 0
    to_commit = 0
    processed_control_numbers: set = set()
    processed_usernames: set = set()
    deactivated = 0

    with SessionLocal() as db:
        app_id, role_id = _get_or_create_student_role(db)
        if not app_id:
            click.echo("❌ Error: No se encontró la app 'agendatec'")
            return

        click.echo(f"✓ App 'agendatec' ID: {app_id} | Rol 'student' ID: {role_id}\n")

        try:
            click.echo("📥 FASE 1: Importando estudiantes del CSV...")
            with open(full_path, "r", encoding="utf-8-sig", newline="") as f:
                reader = csv.DictReader(f, delimiter=",")
                required = {"no_de_control", "apellido_paterno", "apellido_materno", "nombre_alumno", "nip"}
                missing = required - set(reader.fieldnames or [])
                if missing:
                    click.echo(f"❌ Faltan encabezados: {', '.join(sorted(missing))}")
                    return

                for row in reader:
                    row_idx += 1
                    payload, warns = _parse_student_row_v2(row)
                    if warns:
                        warnings_total += len(warns)

                    if not payload.get("username") and not payload.get("control_number"):
                        skipped += 1
                        continue
                    if not payload.get("password_hash"):
                        skipped += 1
                        continue

                    if payload.get("control_number"):
                        processed_control_numbers.add(payload["control_number"])
                    if payload.get("username"):
                        processed_usernames.add(payload["username"])

                    status, _ = _upsert_student_v2(db, payload, app_id, role_id, dry_run=dry_run)
                    if status == "created":
                        created += 1
                        to_commit += 1
                    elif status == "updated":
                        updated += 1
                        to_commit += 1
                    else:
                        skipped += 1

                    if not dry_run and to_commit >= commit_every:
                        db.commit()
                        to_commit = 0

                if not dry_run and to_commit > 0:
                    db.commit()

            click.echo(f"   ✅ Creados: {created} | Actualizados: {updated} | Omitidos: {skipped}")

            if deactivate_missing:
                click.echo("\n🔍 FASE 2: Buscando estudiantes a desactivar...")
                students = (
                    db.query(User)
                    .join(UserAppRole, User.id == UserAppRole.user_id)
                    .filter(
                        UserAppRole.app_id == app_id,
                        UserAppRole.role_id == role_id,
                        User.is_active == True,  # noqa: E712
                    )
                    .all()
                )
                for student in students:
                    in_csv = (
                        (student.control_number and student.control_number in processed_control_numbers)
                        or (student.username and student.username in processed_usernames)
                    )
                    if not in_csv:
                        if not dry_run:
                            student.is_active = False
                            db.add(student)
                        deactivated += 1
                if not dry_run and deactivated > 0:
                    db.commit()
                click.echo(f"   🚫 Desactivados: {deactivated}")

            click.echo(f"\n✅ Sincronización completada — {row_idx} filas procesadas")

        except FileNotFoundError:
            click.echo(f"❌ Archivo no encontrado: {full_path}")
        except Exception as e:
            db.rollback()
            click.echo(f"❌ Error: {str(e)}")
            raise


@click.group("agendatec")
def agendatec_cli():
    """Comandos CLI del módulo AgendaTec."""


agendatec_cli.add_command(seed_periods_command)
agendatec_cli.add_command(activate_period_command)
agendatec_cli.add_command(list_periods_command)
agendatec_cli.add_command(import_students_command)
agendatec_cli.add_command(sync_students_agendatec_command)
