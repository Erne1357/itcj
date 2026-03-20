"""
Tasks API v2 — Gestión de tareas Celery desde la UI de administración.

Todos los endpoints requieren el permiso core.config.admin (solo super-admin).
Prefijo: /api/core/v2/tasks

Recursos:
    TaskDefinition  — catálogo de tareas registradas en el código
    PeriodicTask    — schedules configurados desde la UI
    TaskRun         — historial de ejecuciones
"""
import logging
import uuid
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, field_validator

from itcj2.dependencies import DbSession, require_perms

router = APIRouter(tags=["core-tasks"])
logger = logging.getLogger(__name__)

_ADMIN_PERM = require_perms("itcj", ["core.config.admin"])


# ---------------------------------------------------------------------------
# Schemas Pydantic
# ---------------------------------------------------------------------------

class PeriodicTaskCreate(BaseModel):
    name: str
    task_name: str
    cron_expression: str
    args_json: list = []
    kwargs_json: dict = {}
    is_active: bool = True
    description: str | None = None

    @field_validator("cron_expression")
    @classmethod
    def validate_cron(cls, v: str) -> str:
        parts = v.strip().split()
        if len(parts) != 5:
            raise ValueError("La expresión cron debe tener exactamente 5 campos")
        return v.strip()

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("El nombre no puede estar vacío")
        return v


class PeriodicTaskUpdate(BaseModel):
    name: str | None = None
    cron_expression: str | None = None
    args_json: list | None = None
    kwargs_json: dict | None = None
    description: str | None = None

    @field_validator("cron_expression")
    @classmethod
    def validate_cron(cls, v: str | None) -> str | None:
        if v is None:
            return v
        parts = v.strip().split()
        if len(parts) != 5:
            raise ValueError("La expresión cron debe tener exactamente 5 campos")
        return v.strip()


class TaskDispatchBody(BaseModel):
    task_name: str
    kwargs: dict[str, Any] = {}


# ---------------------------------------------------------------------------
# TaskDefinitions
# ---------------------------------------------------------------------------

@router.get("/definitions")
def list_definitions(
    user: dict = _ADMIN_PERM,
    db: DbSession = None,
):
    """Lista todas las TaskDefinition registradas en el sistema."""
    from itcj2.core.models.task_models import TaskDefinition

    rows = (
        db.query(TaskDefinition)
        .order_by(TaskDefinition.app_name, TaskDefinition.display_name)
        .all()
    )
    return {"status": "ok", "data": [r.to_dict() for r in rows]}


@router.post("/definitions/sync", status_code=201)
def sync_definitions(
    user: dict = _ADMIN_PERM,
    db: DbSession = None,
):
    """Sincroniza las TaskDefinition en la DB con las registradas en el código.

    Importa TASK_DEFINITIONS de todos los módulos de tareas conocidos e
    inserta/actualiza los registros correspondientes.
    """
    from itcj2.core.models.task_models import TaskDefinition
    from itcj2.tasks.helpdesk_tasks import TASK_DEFINITIONS as hd_defs
    from itcj2.tasks.notification_tasks import TASK_DEFINITIONS as notif_defs

    all_defs = hd_defs + notif_defs
    created = 0
    updated = 0

    for defn in all_defs:
        existing = db.query(TaskDefinition).filter_by(
            task_name=defn["task_name"]
        ).first()

        if existing:
            for key, value in defn.items():
                setattr(existing, key, value)
            updated += 1
        else:
            db.add(TaskDefinition(**defn))
            created += 1

    db.commit()
    logger.info(
        "sync_definitions: %d creadas, %d actualizadas — usuario %s",
        created, updated, user["sub"],
    )
    return {"status": "ok", "data": {"created": created, "updated": updated}}


# ---------------------------------------------------------------------------
# PeriodicTasks
# ---------------------------------------------------------------------------

@router.get("/periodic")
def list_periodic(
    user: dict = _ADMIN_PERM,
    db: DbSession = None,
):
    """Lista todas las tareas programadas."""
    from itcj2.core.models.task_models import PeriodicTask

    rows = (
        db.query(PeriodicTask)
        .order_by(PeriodicTask.name)
        .all()
    )
    return {"status": "ok", "data": [r.to_dict() for r in rows]}


@router.post("/periodic", status_code=201)
def create_periodic(
    body: PeriodicTaskCreate,
    user: dict = _ADMIN_PERM,
    db: DbSession = None,
):
    """Crea una nueva tarea programada."""
    from itcj2.core.models.task_models import PeriodicTask, TaskDefinition

    if db.query(PeriodicTask).filter_by(name=body.name).first():
        raise HTTPException(
            409, detail={"status": "error", "error": "name_already_exists"}
        )

    if not db.query(TaskDefinition).filter_by(task_name=body.task_name).first():
        raise HTTPException(
            404, detail={"status": "error", "error": "task_definition_not_found"}
        )

    pt = PeriodicTask(
        name=body.name,
        task_name=body.task_name,
        cron_expression=body.cron_expression,
        args_json=body.args_json,
        kwargs_json=body.kwargs_json,
        is_active=body.is_active,
        description=body.description,
        created_by=int(user["sub"]),
    )
    pt.next_run_at = pt.compute_next_run()

    db.add(pt)
    db.commit()
    db.refresh(pt)

    logger.info("PeriodicTask '%s' creada por usuario %s", pt.name, user["sub"])
    return {"status": "ok", "data": pt.to_dict()}


@router.patch("/periodic/{task_id}")
def update_periodic(
    task_id: int,
    body: PeriodicTaskUpdate,
    user: dict = _ADMIN_PERM,
    db: DbSession = None,
):
    """Edita nombre, cron, args o descripción de una tarea programada."""
    from itcj2.core.models.task_models import PeriodicTask

    pt = db.get(PeriodicTask, task_id)
    if not pt:
        raise HTTPException(
            404, detail={"status": "error", "error": "not_found"}
        )

    if body.name is not None:
        name = body.name.strip()
        if name != pt.name and db.query(PeriodicTask).filter_by(name=name).first():
            raise HTTPException(
                409, detail={"status": "error", "error": "name_already_exists"}
            )
        pt.name = name

    if body.cron_expression is not None:
        pt.cron_expression = body.cron_expression
        pt.next_run_at = pt.compute_next_run()

    if body.args_json is not None:
        pt.args_json = body.args_json

    if body.kwargs_json is not None:
        pt.kwargs_json = body.kwargs_json

    if body.description is not None:
        pt.description = body.description

    db.commit()
    db.refresh(pt)

    logger.info("PeriodicTask %d actualizada por usuario %s", task_id, user["sub"])
    return {"status": "ok", "data": pt.to_dict()}


@router.patch("/periodic/{task_id}/toggle")
def toggle_periodic(
    task_id: int,
    user: dict = _ADMIN_PERM,
    db: DbSession = None,
):
    """Activa o pausa una tarea programada sin modificar el resto de su configuración."""
    from itcj2.core.models.task_models import PeriodicTask

    pt = db.get(PeriodicTask, task_id)
    if not pt:
        raise HTTPException(
            404, detail={"status": "error", "error": "not_found"}
        )

    pt.is_active = not pt.is_active
    db.commit()

    action = "activada" if pt.is_active else "pausada"
    logger.info(
        "PeriodicTask %d %s por usuario %s", task_id, action, user["sub"]
    )
    return {"status": "ok", "data": {"is_active": pt.is_active}}


@router.delete("/periodic/{task_id}", status_code=204)
def delete_periodic(
    task_id: int,
    user: dict = _ADMIN_PERM,
    db: DbSession = None,
):
    """Elimina una tarea programada."""
    from itcj2.core.models.task_models import PeriodicTask

    pt = db.get(PeriodicTask, task_id)
    if not pt:
        raise HTTPException(
            404, detail={"status": "error", "error": "not_found"}
        )

    db.delete(pt)
    db.commit()
    logger.info("PeriodicTask %d eliminada por usuario %s", task_id, user["sub"])


# ---------------------------------------------------------------------------
# TaskRuns
# ---------------------------------------------------------------------------

@router.get("/runs")
def list_runs(
    status: str | None = Query(None, description="PENDING|RUNNING|SUCCESS|FAILURE|REVOKED"),
    task_name: str | None = Query(None),
    app_name: str | None = Query(None),
    days: int = Query(7, ge=1, le=365, description="Rango de días hacia atrás"),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    user: dict = _ADMIN_PERM,
    db: DbSession = None,
):
    """Lista el historial de ejecuciones con filtros y paginación."""
    from sqlalchemy import desc
    from itcj2.core.models.task_models import TaskRun, TaskDefinition

    query = db.query(TaskRun)

    if status:
        query = query.filter(TaskRun.status == status.upper())

    if task_name:
        query = query.filter(TaskRun.task_name == task_name)

    if app_name:
        query = (
            query
            .join(
                TaskDefinition,
                TaskDefinition.task_name == TaskRun.task_name,
                isouter=True,
            )
            .filter(TaskDefinition.app_name == app_name)
        )

    since = datetime.now() - timedelta(days=days)
    query = query.filter(TaskRun.created_at >= since)

    total = query.count()
    runs = (
        query
        .order_by(desc(TaskRun.created_at))
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )

    return {
        "status": "ok",
        "data": [r.to_dict() for r in runs],
        "meta": {
            "total": total,
            "page": page,
            "per_page": per_page,
            "total_pages": (total + per_page - 1) // per_page,
        },
    }


@router.get("/runs/{run_id}")
def get_run(
    run_id: int,
    user: dict = _ADMIN_PERM,
    db: DbSession = None,
):
    """Devuelve el detalle completo de una ejecución, incluyendo result_json."""
    from itcj2.core.models.task_models import TaskRun

    run = db.get(TaskRun, run_id)
    if not run:
        raise HTTPException(
            404, detail={"status": "error", "error": "not_found"}
        )

    return {"status": "ok", "data": run.to_dict()}


@router.post("/runs", status_code=201)
def dispatch_task(
    body: TaskDispatchBody,
    user: dict = _ADMIN_PERM,
    db: DbSession = None,
):
    """Dispara una tarea manualmente.

    Crea un TaskRun con status=PENDING y lo encola en Celery.
    """
    from itcj2.core.models.task_models import TaskDefinition, TaskRun
    from itcj2.celery_app import celery_app

    defn = db.query(TaskDefinition).filter_by(task_name=body.task_name).first()
    if not defn:
        raise HTTPException(
            404, detail={"status": "error", "error": "task_definition_not_found"}
        )

    if not defn.is_active:
        raise HTTPException(
            409, detail={"status": "error", "error": "task_is_inactive"}
        )

    celery_id = str(uuid.uuid4())
    user_id = int(user["sub"])

    run = TaskRun(
        celery_task_id=celery_id,
        task_name=body.task_name,
        display_name=defn.display_name,
        status="PENDING",
        trigger="MANUAL",
        triggered_by_user_id=user_id,
        args_json=body.kwargs,
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    # Encolar en Celery — task_run_id se inyecta en kwargs para LoggedTask
    celery_app.send_task(
        body.task_name,
        kwargs={**body.kwargs, "task_run_id": run.id},
        task_id=celery_id,
    )

    logger.info(
        "Tarea '%s' despachada manualmente por usuario %s (run_id=%d, celery_id=%s)",
        body.task_name, user_id, run.id, celery_id,
    )
    return {"status": "ok", "data": run.to_dict()}


@router.delete("/runs/{run_id}/revoke")
def revoke_run(
    run_id: int,
    user: dict = _ADMIN_PERM,
    db: DbSession = None,
):
    """Cancela una tarea PENDING o RUNNING (Celery revoke + terminate)."""
    from itcj2.core.models.task_models import TaskRun
    from itcj2.celery_app import celery_app

    run = db.get(TaskRun, run_id)
    if not run:
        raise HTTPException(
            404, detail={"status": "error", "error": "not_found"}
        )

    if run.status not in ("PENDING", "RUNNING"):
        raise HTTPException(
            409,
            detail={
                "status": "error",
                "error": "cannot_revoke",
                "detail": f"La tarea está en estado {run.status}",
            },
        )

    if run.celery_task_id:
        celery_app.control.revoke(run.celery_task_id, terminate=True)

    run.status = "REVOKED"
    run.finished_at = datetime.now()
    if run.started_at:
        run.duration_seconds = round(
            (run.finished_at - run.started_at).total_seconds(), 3
        )

    db.commit()

    logger.info(
        "TaskRun %d revocada por usuario %s (celery_id=%s)",
        run_id, user["sub"], run.celery_task_id,
    )
    return {"status": "ok", "data": run.to_dict()}
