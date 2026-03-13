"""
Modelos para el sistema de tareas Celery.

Tablas:
    core_task_definitions  — catálogo de tareas disponibles en el sistema
    core_periodic_tasks    — schedules configurados desde la UI (Celery Beat DB-driven)
    core_task_runs         — historial de cada ejecución (result backend propio)
"""
from datetime import datetime

from sqlalchemy import (
    BigInteger, Boolean, Column, DateTime, Float,
    ForeignKey, Index, Integer, SmallInteger, String, Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func, text

from itcj2.models.base import Base


# ---------------------------------------------------------------------------
# TaskDefinition — catálogo de tareas registradas en el código
# ---------------------------------------------------------------------------

class TaskDefinition(Base):
    __tablename__ = "core_task_definitions"

    id = Column(Integer, primary_key=True)
    task_name = Column(String(255), unique=True, nullable=False)
    display_name = Column(String(200), nullable=False)
    description = Column(Text)
    app_name = Column(String(50), nullable=False, index=True)
    # "maintenance" | "notification" | "report" | "document" | "import"
    category = Column(String(50), nullable=False, default="maintenance")
    default_args = Column(JSONB, nullable=False, server_default=text("'{}'"))
    is_active = Column(Boolean, nullable=False, server_default=text("TRUE"))
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())

    periodic_tasks = relationship("PeriodicTask", back_populates="task_definition", lazy="dynamic")

    def to_dict(self):
        return {
            "id": self.id,
            "task_name": self.task_name,
            "display_name": self.display_name,
            "description": self.description,
            "app_name": self.app_name,
            "category": self.category,
            "default_args": self.default_args,
            "is_active": self.is_active,
        }


# ---------------------------------------------------------------------------
# PeriodicTask — schedules gestionados desde la UI (leídos por Celery Beat)
# ---------------------------------------------------------------------------

class PeriodicTask(Base):
    __tablename__ = "core_periodic_tasks"

    id = Column(Integer, primary_key=True)
    name = Column(String(200), unique=True, nullable=False)
    task_name = Column(String(255), ForeignKey("core_task_definitions.task_name", ondelete="CASCADE"), nullable=False)
    # Expresión cron estándar: "minuto hora día mes día_semana"
    cron_expression = Column(String(100), nullable=False)
    args_json = Column(JSONB, nullable=False, server_default=text("'[]'"))
    kwargs_json = Column(JSONB, nullable=False, server_default=text("'{}'"))
    is_active = Column(Boolean, nullable=False, server_default=text("TRUE"), index=True)
    description = Column(Text)
    last_run_at = Column(DateTime)
    next_run_at = Column(DateTime)
    created_by = Column(BigInteger, ForeignKey("core_users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())

    task_definition = relationship("TaskDefinition", back_populates="periodic_tasks")
    created_by_user = relationship("User", foreign_keys=[created_by])

    def compute_next_run(self) -> datetime | None:
        """Calcula la próxima ejecución a partir de la expresión cron.

        Devuelve None si la expresión es inválida o si croniter no está instalado.
        Usado por la API al crear/editar un PeriodicTask para guardar next_run_at.
        """
        try:
            from croniter import croniter
            from datetime import datetime
            itr = croniter(self.cron_expression, datetime.utcnow())
            return itr.get_next(datetime)
        except Exception:
            return None

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "task_name": self.task_name,
            "display_name": self.task_definition.display_name if self.task_definition else self.task_name,
            "app_name": self.task_definition.app_name if self.task_definition else None,
            "cron_expression": self.cron_expression,
            "args_json": self.args_json,
            "kwargs_json": self.kwargs_json,
            "is_active": self.is_active,
            "description": self.description,
            "last_run_at": self.last_run_at.isoformat() if self.last_run_at else None,
            "next_run_at": self.next_run_at.isoformat() if self.next_run_at else None,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# ---------------------------------------------------------------------------
# TaskRun — historial de ejecuciones (result backend propio en PostgreSQL)
# ---------------------------------------------------------------------------

class TaskRun(Base):
    __tablename__ = "core_task_runs"

    id = Column(BigInteger, primary_key=True)
    celery_task_id = Column(String(36), unique=True, nullable=True, index=True)  # UUID de Celery
    task_name = Column(String(255), nullable=False, index=True)
    display_name = Column(String(200), nullable=False)

    # "PENDING" | "RUNNING" | "SUCCESS" | "FAILURE" | "REVOKED"
    status = Column(String(20), nullable=False, default="PENDING", index=True)
    # "MANUAL" | "SCHEDULED"
    trigger = Column(String(20), nullable=False, default="MANUAL")

    triggered_by_user_id = Column(BigInteger, ForeignKey("core_users.id", ondelete="SET NULL"), nullable=True)
    periodic_task_id = Column(Integer, ForeignKey("core_periodic_tasks.id", ondelete="SET NULL"), nullable=True)

    args_json = Column(JSONB, nullable=False, server_default=text("'{}'"))
    result_json = Column(JSONB)

    progress = Column(SmallInteger, nullable=False, default=0)
    progress_message = Column(String(500))

    started_at = Column(DateTime)
    finished_at = Column(DateTime)
    duration_seconds = Column(Float)

    created_at = Column(DateTime, nullable=False, server_default=func.now(), index=True)

    triggered_by_user = relationship("User", foreign_keys=[triggered_by_user_id])
    periodic_task = relationship("PeriodicTask")

    __table_args__ = (
        Index("ix_task_runs_status_created", "status", "created_at"),
        Index("ix_task_runs_task_name_created", "task_name", "created_at"),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "celery_task_id": self.celery_task_id,
            "task_name": self.task_name,
            "display_name": self.display_name,
            "status": self.status,
            "trigger": self.trigger,
            "triggered_by_user_id": self.triggered_by_user_id,
            "triggered_by_user": (
                self.triggered_by_user.first_name + " " + self.triggered_by_user.last_name
                if self.triggered_by_user else None
            ),
            "periodic_task_id": self.periodic_task_id,
            "args_json": self.args_json,
            "result_json": self.result_json,
            "progress": self.progress,
            "progress_message": self.progress_message,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "duration_seconds": self.duration_seconds,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
