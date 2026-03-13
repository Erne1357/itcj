#!/usr/bin/env python3
"""
Comandos CLI para gestión de Celery en itcj2.

Uso:
    python -m itcj2.cli.main celery sync-tasks
    python -m itcj2.cli.main celery run cleanup-attachments
    python -m itcj2.cli.main celery run cleanup-attachments --dry-run
    python -m itcj2.cli.main celery status
"""
import json
import click


@click.group(name="celery")
def celery_cli():
    """Gestión de tareas Celery."""


@celery_cli.command("sync-tasks")
def sync_tasks():
    """Sincroniza las TaskDefinition del código con la base de datos.

    Lee los metadatos TASK_DEFINITIONS de cada módulo de tareas y los
    inserta/actualiza en la tabla core_task_definitions.
    """
    from itcj2.database import SessionLocal
    from itcj2.core.models.task_models import TaskDefinition

    # Importar módulos de tareas para acceder a sus TASK_DEFINITIONS
    task_modules = []
    try:
        from itcj2.tasks import helpdesk_tasks
        task_modules.append(helpdesk_tasks)
    except ImportError as e:
        click.echo(f"  Advertencia: no se pudo importar helpdesk_tasks: {e}", err=True)

    try:
        from itcj2.tasks import notification_tasks
        task_modules.append(notification_tasks)
    except ImportError:
        pass  # Aún no implementado en fase 1

    all_definitions = []
    for module in task_modules:
        defs = getattr(module, "TASK_DEFINITIONS", [])
        all_definitions.extend(defs)

    if not all_definitions:
        click.echo("No se encontraron definiciones de tareas.")
        return

    with SessionLocal() as db:
        created = 0
        updated = 0
        for defn in all_definitions:
            existing = db.query(TaskDefinition).filter_by(task_name=defn["task_name"]).first()
            if existing:
                for key, value in defn.items():
                    setattr(existing, key, value)
                updated += 1
            else:
                db.add(TaskDefinition(**defn))
                created += 1
        db.commit()

    click.echo(f"sync-tasks completado: {created} creadas, {updated} actualizadas.")


@celery_cli.command("run")
@click.argument("task_slug")
@click.option("--dry-run", is_flag=True, default=False, help="Simular sin modificar datos.")
@click.option("--kwargs", "extra_kwargs", default="{}", help="JSON con kwargs adicionales.")
def run_task(task_slug: str, dry_run: bool, extra_kwargs: str):
    """Ejecuta una tarea manualmente desde la línea de comandos.

    TASK_SLUG es el nombre corto de la tarea, p.ej. 'cleanup-attachments'.
    """
    import uuid
    from datetime import datetime
    from itcj2.database import SessionLocal
    from itcj2.core.models.task_models import TaskDefinition, TaskRun

    slug_map = {
        "cleanup-attachments": "itcj2.tasks.helpdesk_tasks.cleanup_attachments",
    }

    task_name = slug_map.get(task_slug)
    if not task_name:
        click.echo(f"Tarea desconocida: '{task_slug}'. Slugs disponibles: {list(slug_map.keys())}", err=True)
        raise SystemExit(1)

    try:
        extra = json.loads(extra_kwargs)
    except json.JSONDecodeError as e:
        click.echo(f"--kwargs no es JSON válido: {e}", err=True)
        raise SystemExit(1)

    celery_id = str(uuid.uuid4())

    with SessionLocal() as db:
        defn = db.query(TaskDefinition).filter_by(task_name=task_name).first()
        display_name = defn.display_name if defn else task_name

        run = TaskRun(
            celery_task_id=celery_id,
            task_name=task_name,
            display_name=display_name,
            status="PENDING",
            trigger="MANUAL",
            args_json={"dry_run": dry_run, **extra},
            created_at=datetime.utcnow(),
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        task_run_id = run.id

    click.echo(f"TaskRun creado: id={task_run_id}, celery_id={celery_id}")

    # Importar y encolar la tarea concreta
    if task_name == "itcj2.tasks.helpdesk_tasks.cleanup_attachments":
        from itcj2.tasks.helpdesk_tasks import cleanup_attachments
        cleanup_attachments.apply_async(
            task_id=celery_id,
            kwargs={"task_run_id": task_run_id, "dry_run": dry_run, **extra},
        )

    click.echo(f"Tarea '{task_name}' encolada. Monitorea el progreso en /config/system/tasks/.")


@celery_cli.command("status")
def status():
    """Muestra el estado de los workers Celery activos."""
    from itcj2.celery_app import celery_app

    inspect = celery_app.control.inspect(timeout=3.0)
    active = inspect.active()
    stats = inspect.stats()

    if not active:
        click.echo("No hay workers activos (o no responden en 3s).")
        return

    for worker_name, tasks in (active or {}).items():
        worker_stats = (stats or {}).get(worker_name, {})
        click.echo(f"\nWorker: {worker_name}")
        click.echo(f"  Total ejecutadas: {worker_stats.get('total', {})}")
        click.echo(f"  Tareas activas: {len(tasks)}")
        for t in tasks:
            click.echo(f"    - {t.get('name')} (id={t.get('id')})")
