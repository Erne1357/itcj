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
    """Ejecuta todos los scripts SQL de un directorio en orden alfabético.

    Invalida el caché de authz al final, incondicionalmente. Este helper es
    compartido por todos los comandos de agendatec que cargan DML por
    directorio (`seed-periods`, `load-help`, `load-split-scope-2026-08`, y
    cualquiera futuro): varios de esos directorios SÍ tocan permisos/roles
    (p.ej. `database/DML/agendatec/periods/`, `.../help/`), y dejarlo a
    criterio de cada comando es exactamente el tipo de decisión que alguien
    olvida. El costo de invalidar de más en un comando que solo corre en
    deploy (un refill de caché) es aceptable frente al de dejar un permiso
    revocado autorizando hasta AUTHZ_CACHE_TTL (300s).

    Este `db` es del CALLER y no se commitea aquí, así que esta invalidación
    corre ANTES de ese commit. Cada llamador debe invalidar OTRA VEZ después
    de su propio `db.commit()` (ver el comentario en `load_help_command`) —
    sin eso, un lector que caiga en la ventana pre-commit repuebla el caché
    con el estado viejo aún no commiteado y esa entrada sobrevive el TTL
    completo, el mismo patrón que `bump_version`/`forget_cached_version`
    (Tareas 5/6) tuvieron que cerrar para la época de sesión.
    """
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

    try:
        from itcj2.core.services.authz_cache import invalidate_all
        invalidate_all()
        click.echo("   🧹 Caché de authz invalidado.")
    except Exception as e:
        click.echo(f"   ⚠️  No se pudo invalidar el caché de authz ({e}). "
                   "Aplicará en ≤5 min por TTL.")

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
            # Segunda invalidación, ya con el commit hecho: ver el comentario en
            # load_help_command para el porqué (no es redundante con la de
            # _execute_sql_scripts).
            from itcj2.core.services.authz_cache import invalidate_all
            invalidate_all()

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
    if not nip:
        warnings.append("NIP vacío")

    # Alumnos de un solo apellido llegan con el paterno vacío. Se recorre el materno a
    # ``last_name`` para que el nombre completo quede "Parra Diego Andrés" y no
    # "SIN APELLIDO Parra Diego Andrés".
    if not apellido_paterno:
        if apellido_materno:
            apellido_paterno, apellido_materno = apellido_materno, ""
            warnings.append("Apellido paterno vacío (se usa el materno)")
        else:
            warnings.append("Apellido paterno vacío")

    # El no. de control institucional es SIEMPRE el identificador del alumno y va en
    # ``control_number``, incluidos los alfanuméricos de reingreso/posgrado
    # (B*/C*/D*/M*). Es el campo por el que se autentica el alumno y el que ya usan
    # las filas existentes en BD; ``username`` queda reservado para cuentas de staff.
    control_number = no_de_control.upper() if no_de_control else None
    if control_number and len(control_number) not in (8, 9):
        warnings.append(
            f"control_number '{control_number}' longitud inesperada ({len(control_number)})"
        )

    from itcj2.core.utils.security import hash_nip

    payload = {
        "username": None,
        "control_number": control_number,
        "password_hash": hash_nip(nip) if nip else None,
        "first_name": nombre_alumno.title() if nombre_alumno else "SIN NOMBRE",
        "last_name": apellido_paterno.title() if apellido_paterno else "SIN APELLIDO",
        "middle_name": apellido_materno.title() if apellido_materno else None,
        "is_active": True,
    }
    return payload, warnings


def _flush_grant_invalidations(granted_ids: list) -> None:
    """Reinvalida el caché de authz de los alumnos cuyo rol ACABA de commitearse.

    `_upsert_student_v2` ya invalida junto al `db.add(UserAppRole(...))`, pero
    ese add no se commitea hasta `commit_every` filas después (500 por defecto)
    o al final del CSV. Un lector que golpee un guard de agendatec en esa
    ventana repuebla el caché leyendo Postgres —que TODAVÍA no tiene el rol— y
    esa entrada `has: False` le sobrevive el TTL completo (300s) PASADO el
    commit. Misma Carrera A6 que cierran con una segunda invalidación
    post-commit los otros cuatro call sites de este fix; aquí la dirección es
    stale-DENY (403 al alumno recién importado, no acceso indebido), pero el
    invariante es el mismo y dejarlo a medias es lo que se copia después.

    Vacía la lista: hay que llamarla tras CADA commit parcial, no solo al final.
    """
    if not granted_ids:
        return
    from itcj2.core.services.authz_cache import invalidate_user_app
    for uid in granted_ids:
        invalidate_user_app(uid, "agendatec")
    granted_ids.clear()


def _upsert_student_v2(
    db,
    payload: dict,
    app_id: int,
    role_id: int,
    dry_run: bool = False,
    granted_ids: Optional[list] = None,
) -> Tuple[str, Optional[int]]:
    """Crea/actualiza un alumno y le asegura el rol `student` de agendatec.

    `granted_ids`: lista de salida. Se le anexa el id de cada alumno al que se
    le CREÓ el UserAppRole, para que el caller pueda reinvalidar su caché
    después del commit (ver `_flush_grant_invalidations`).
    """
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
        for field in ("first_name", "last_name", "password_hash"):
            val = payload.get(field)
            if val is not None and getattr(existing, field, None) != val:
                setattr(existing, field, val)
                changed = True
        # middle_name sí se limpia cuando el CSV no trae apellido materno: el padrón
        # es la fuente de verdad y si no, un materno viejo quedaría pegado al nombre.
        if existing.middle_name != payload.get("middle_name"):
            existing.middle_name = payload.get("middle_name")
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
            # role_id es el rol global de la cuenta; sin él la fila queda con NULL y
            # difiere del resto del padrón. La autorización real vive en
            # core_user_app_roles, pero se mantiene consistente.
            role_id=role_id,
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
            # El caché es read-through: si el alumno ya golpeó un guard de agendatec
            # antes (periodo anterior), su entrada `has` dice False y le daría 403
            # hasta que expire el TTL.
            from itcj2.core.services.authz_cache import invalidate_user_app
            invalidate_user_app(user_id, "agendatec")
            # Pero esta invalidación es PRE-commit y por tanto insuficiente por
            # sí sola: el caller debe reinvalidar tras el commit que incluya
            # este add. Ver `_flush_grant_invalidations`.
            if granted_ids is not None:
                granted_ids.append(user_id)

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


#: CSVs del semestre en curso. Se procesan TODOS en la misma corrida para que la
#: fase de desactivación evalúe contra la unión (activos + aspirantes) y no dé de
#: baja a los alumnos del primer archivo al cargar el segundo.
DEFAULT_STUDENT_CSVS = (
    "database/CSV/Alumnos_Activos_20263.csv",
    "database/CSV/Alumnos_Aspirantes_20263.csv",
)

REQUIRED_STUDENT_CSV_HEADERS = {
    "no_de_control",
    "apellido_paterno",
    "apellido_materno",
    "nombre_alumno",
    "nip",
}


@click.command("sync-students-agendatec")
@click.option(
    "--csv-path",
    "csv_paths",
    multiple=True,
    default=DEFAULT_STUDENT_CSVS,
    show_default=True,
    help=(
        "CSV de alumnos. Repite la opción para procesar varios archivos en la MISMA "
        "corrida: la desactivación se evalúa contra la unión de todos ellos."
    ),
)
@click.option("--dry-run", is_flag=True)
@click.option("--commit-every", type=int, default=500)
@click.option("--deactivate-missing/--no-deactivate-missing", default=True)
def sync_students_agendatec_command(csv_paths, dry_run, commit_every, deactivate_missing):
    """Sincroniza estudiantes desde uno o varios CSV y asigna rol 'student' para AgendaTec."""
    from itcj2.core.models import User, UserAppRole
    from itcj2.database import SessionLocal

    full_paths = [
        Path(p) if Path(p).is_absolute() else PROJECT_ROOT / p
        for p in csv_paths
    ]

    click.echo("=" * 60)
    click.echo("🎓 SINCRONIZACIÓN DE ESTUDIANTES — AGENDATEC")
    click.echo("=" * 60)
    for p in full_paths:
        click.echo(f"📁 Archivo: {p}")
    if dry_run:
        click.echo("⚠️  Modo DRY-RUN")

    # Validación previa de TODOS los archivos (existencia + encabezados) antes de
    # tocar la BD: una sincronización a medias dejaría la fase de desactivación
    # evaluando contra un padrón incompleto y daría de baja a quien no toca.
    problemas = []
    for p in full_paths:
        if not p.is_file():
            problemas.append(f"{p}: no encontrado")
            continue
        with open(p, "r", encoding="utf-8-sig", newline="") as f:
            cabeceras = set(csv.DictReader(f, delimiter=",").fieldnames or [])
        faltan = REQUIRED_STUDENT_CSV_HEADERS - cabeceras
        if faltan:
            problemas.append(f"{p.name}: faltan encabezados {', '.join(sorted(faltan))}")
    if problemas:
        for msg in problemas:
            click.echo(f"❌ {msg}")
        raise SystemExit(1)

    created = updated = skipped = warnings_total = 0
    row_idx = 0
    to_commit = 0
    processed_control_numbers: set = set()
    processed_usernames: set = set()
    duplicados = 0
    deactivated = 0
    # Alumnos con rol recién concedido y todavía sin commitear. Se vacía tras
    # CADA commit (parcial y final), no solo al terminar: con lotes de 500 el
    # "solo al final" deja la ventana de caché stale abierta casi todo el import.
    pending_grants: list = []

    with SessionLocal() as db:
        app_id, role_id = _get_or_create_student_role(db)
        if not app_id:
            click.echo("❌ Error: No se encontró la app 'agendatec'")
            return

        click.echo(f"✓ App 'agendatec' ID: {app_id} | Rol 'student' ID: {role_id}\n")

        try:
            click.echo("📥 FASE 1: Importando estudiantes del CSV...")
            for full_path in full_paths:
                f_rows = f_created = f_updated = f_skipped = 0
                with open(full_path, "r", encoding="utf-8-sig", newline="") as f:
                    reader = csv.DictReader(f, delimiter=",")

                    for row in reader:
                        row_idx += 1
                        f_rows += 1
                        payload, warns = _parse_student_row_v2(row)
                        if warns:
                            warnings_total += len(warns)

                        if not payload.get("username") and not payload.get("control_number"):
                            skipped += 1
                            f_skipped += 1
                            continue
                        if not payload.get("password_hash"):
                            skipped += 1
                            f_skipped += 1
                            continue

                        # Un mismo alumno repetido entre archivos se procesa una sola vez.
                        clave = payload.get("control_number") or payload.get("username")
                        if clave in processed_control_numbers or clave in processed_usernames:
                            duplicados += 1
                            skipped += 1
                            f_skipped += 1
                            continue

                        if payload.get("control_number"):
                            processed_control_numbers.add(payload["control_number"])
                        if payload.get("username"):
                            processed_usernames.add(payload["username"])

                        status, _ = _upsert_student_v2(
                            db, payload, app_id, role_id, dry_run=dry_run,
                            granted_ids=pending_grants,
                        )
                        if status == "created":
                            created += 1
                            f_created += 1
                            to_commit += 1
                        elif status == "updated":
                            updated += 1
                            f_updated += 1
                            to_commit += 1
                        else:
                            skipped += 1
                            f_skipped += 1

                        if not dry_run and to_commit >= commit_every:
                            db.commit()
                            to_commit = 0
                            _flush_grant_invalidations(pending_grants)

                    if not dry_run and to_commit > 0:
                        db.commit()
                        to_commit = 0
                    # También fuera del `if`: en dry-run la lista está vacía y esto
                    # es un no-op, pero deja el invariante “ninguna concesión
                    # sobrevive a su archivo sin reinvalidar” sin excepciones.
                    _flush_grant_invalidations(pending_grants)

                click.echo(
                    f"   • {full_path.name}: {f_rows} filas — "
                    f"creados {f_created} | actualizados {f_updated} | omitidos {f_skipped}"
                )

            click.echo(f"   ✅ Creados: {created} | Actualizados: {updated} | Omitidos: {skipped}")
            if duplicados:
                click.echo(f"   ♻️  Repetidos entre archivos (ignorados): {duplicados}")
            if warnings_total:
                click.echo(f"   ⚠️  Advertencias de parseo: {warnings_total}")

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
                # Ids con algún rol distinto de agendatec/student: la baja apaga la
                # cuenta completa, así que esos pierden también su acceso de staff.
                # Se listan explícitamente para que quede constancia en la corrida.
                ids_con_otros_roles = {
                    uid
                    for (uid,) in db.query(UserAppRole.user_id)
                    .filter(
                        ~((UserAppRole.app_id == app_id) & (UserAppRole.role_id == role_id))
                    )
                    .distinct()
                }
                con_otros_roles = []
                revoked_ids = []
                failed_revocations = 0
                for student in students:
                    in_csv = (
                        (student.control_number and student.control_number in processed_control_numbers)
                        or (student.username and student.username in processed_usernames)
                    )
                    if in_csv:
                        continue
                    if not dry_run:
                        # bump_version(db=db) es atómico con is_active=False (misma
                        # transacción): sin esto, desactivar sin revocar deja la
                        # sesión del alumno viva hasta 12h. Es un import batch de
                        # muchos alumnos, no una acción admin de uno solo, así que
                        # un fallo de revocación NO aborta todo el batch (a
                        # diferencia de users_admin.toggle_user_status) — pero
                        # tampoco se desactiva en silencio sin haber revocado:
                        # ese es justo el modo de falla que este plan busca
                        # eliminar. Se omite ese alumno (sigue activo) y se
                        # reporta al final.
                        from itcj2.core.services.session_service import bump_version
                        if bump_version(student.id, db=db) is None:
                            failed_revocations += 1
                            click.echo(
                                f"   ⚠️  No se pudo revocar la sesión de {student.id}; "
                                "se deja activo (no se desactiva sin revocar)."
                            )
                            continue
                        student.is_active = False
                        db.add(student)
                        revoked_ids.append(student.id)
                    # Se anota DESPUÉS de la revocación: el reporte enumera a los
                    # que de verdad se dieron de baja, no a los omitidos por
                    # fallo de revocación.
                    if student.id in ids_con_otros_roles:
                        con_otros_roles.append(student.control_number or student.username)
                    deactivated += 1
                if not dry_run and deactivated > 0:
                    db.commit()
                    # bump_version(db=db) ya borró la caché de cada época antes de
                    # este commit; ese borrado puede perder la carrera contra un
                    # lector que repueble con la época vieja aún no commiteada
                    # (Carrera A6, Tarea 5/6). Este segundo borrado, YA con el
                    # commit hecho, cierra esa ventana.
                    from itcj2.core.services.session_service import forget_cached_version
                    for uid in revoked_ids:
                        forget_cached_version(uid)
                click.echo(f"   🚫 Desactivados: {deactivated}")
                if failed_revocations:
                    click.echo(f"   ⚠️  Omitidos por fallo de revocación (siguen activos): {failed_revocations}")
                if con_otros_roles:
                    click.echo(
                        f"   ⚠️  {len(con_otros_roles)} de ellos tenían roles adicionales "
                        f"(pierden también ese acceso): {', '.join(con_otros_roles)}"
                    )

            click.echo(f"\n✅ Sincronización completada — {row_idx} filas procesadas")

        except SystemExit:
            db.rollback()
            raise
        except Exception as e:
            db.rollback()
            click.echo(f"❌ Error: {str(e)}")
            raise


@click.command("load-help")
def load_help_command():
    """Carga permisos y asignaciones de la pestaña de Ayuda de AgendaTec.

    Ejecuta en orden alfabético los scripts de ``database/DML/agendatec/help/``:
      - 01_insert_help_permissions.sql
      - 02_insert_help_role_permissions.sql

    Idempotente (los INSERT usan ON CONFLICT DO NOTHING).
    """
    from itcj2.database import SessionLocal

    click.echo("=" * 60)
    click.echo("📖 AGENDATEC — Cargando permisos de Ayuda")
    click.echo("=" * 60)

    scripts_dir = PROJECT_ROOT / "database" / "DML" / "agendatec" / "help"

    with SessionLocal() as db:
        try:
            executed = _execute_sql_scripts(db, str(scripts_dir))
            db.commit()
            # `_execute_sql_scripts` ya invalidó una vez, pero ANTES de este
            # commit (recibe un `db` que no le pertenece y no lo commitea). Un
            # lector que caiga justo en esa ventana repuebla el caché leyendo
            # Postgres todavía sin el DML aplicado, y esa entrada le sobrevive
            # el TTL completo (300s) — Race A6 una vez más, ahora en el caché
            # de authz en vez de en la época de sesión. Esta segunda llamada,
            # YA con el commit hecho, cierra esa ventana. NO es redundante con
            # la de _execute_sql_scripts: quitar cualquiera de las dos reabre
            # una ventana distinta.
            from itcj2.core.services.authz_cache import invalidate_all
            invalidate_all()
            click.echo(f"\n✅ {executed} script(s) ejecutado(s) correctamente")
        except Exception as e:
            db.rollback()
            click.echo(f"\n❌ Error: {str(e)}")
            raise


@click.command("load-split-scope-2026-08")
@click.option("--dry-run", is_flag=True, help="Lista los scripts sin ejecutarlos.")
def load_split_scope_command(dry_run):
    """Carga el DML del feature split + scope por carrera (agosto 2026).

    Corre SOLO database/DML/agendatec/split_scope_2026-08/, sin re-ejecutar
    ningún DML ya aplicado en producción.

    Idempotente: todo el SQL usa ON CONFLICT DO NOTHING.
    """
    from itcj2.database import SessionLocal

    scripts_dir = PROJECT_ROOT / "database" / "DML" / "agendatec" / "split_scope_2026-08"

    if not scripts_dir.exists():
        click.echo(f"❌ No existe {scripts_dir}")
        click.echo("   database/ está gitignored: súbelo al servidor por scp.")
        raise SystemExit(1)

    sql_files = sorted(scripts_dir.glob("*.sql"))
    if not sql_files:
        click.echo(f"ℹ️  No hay scripts SQL en {scripts_dir}")
        return

    if dry_run:
        click.echo(f"🔍 {len(sql_files)} script(s) en {scripts_dir.name}:")
        for f in sql_files:
            click.echo(f"   📄 {f.name}")
        click.echo("\n(dry-run: no se ejecutó nada)")
        return

    click.echo("🔐 Cargando DML de split + scope...")
    with SessionLocal() as db:
        try:
            executed = _execute_sql_scripts(db, str(scripts_dir))
            db.commit()
            # Segunda invalidación post-commit: ver el comentario en
            # load_help_command para el porqué (no es redundante).
            from itcj2.core.services.authz_cache import invalidate_all
            invalidate_all()
            click.echo(f"\n✅ {executed} script(s) ejecutado(s) correctamente")
        except Exception as e:
            db.rollback()
            click.echo(f"\n❌ Error: {str(e)}")
            raise


@click.group("agendatec")
def agendatec_cli():
    """Comandos CLI del módulo AgendaTec."""


agendatec_cli.add_command(seed_periods_command)
agendatec_cli.add_command(activate_period_command)
agendatec_cli.add_command(list_periods_command)
agendatec_cli.add_command(import_students_command)
agendatec_cli.add_command(sync_students_agendatec_command)
agendatec_cli.add_command(load_help_command)
agendatec_cli.add_command(load_split_scope_command)
