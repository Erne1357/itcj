"""Factories del dominio de tareas de Adhoc.

Funciones planas (no fixtures de pytest) para no tener que tocar el
``conftest.py`` compartido de ``tests/fastapi/adhoc/``, que otros dominios de la
migración están escribiendo en paralelo. Cada factory recibe la sesión
``db_session`` (transaccional, con rollback al final del test) y hace
``flush()``, nunca ``commit()``.

Por qué BD real y no ``MagicMock`` (desviación consciente del plan §9.1): el
motor de workflow decide en función de **invariantes relacionales** — cuántas
filas de ``adhoc_task_approvals`` hay contra cuántos asignados tiene la tarea,
qué paso del flujo sigue al actual, qué tareas del documento están ``En Espera``.
Un ``MagicMock`` no puede expresar eso sin convertirse en una reimplementación
del propio service, y el test dejaría de probar nada. Los tests puramente
lógicos (validación de schemas, serializadores) sí van sin BD.
"""
from __future__ import annotations

from datetime import date
from typing import Optional, Sequence


def make_role(db, name: str = "staff"):
    from itcj2.core.models.role import Role

    role = db.query(Role).filter_by(name=name).first()
    if role is None:
        role = Role(name=name)
        db.add(role)
        db.flush()
    return role


def make_user(db, first_name: str = "TEST", last_name: str = "USER", email: Optional[str] = None):
    from itcj2.core.models.user import User

    role = make_role(db)
    u = User(
        first_name=first_name,
        last_name=last_name,
        email=email,
        is_active=True,
        role_id=role.id,
    )
    db.add(u)
    db.flush()
    return u


def make_incident(db, title: str = "Incidencia de prueba", responsible=None, status: str = "No Iniciada"):
    from itcj2.apps.adhoc.models import AdhocIncident

    inc = AdhocIncident(
        title=title,
        folio=f"INC-{title[:8]}",
        status=status,
        priority="Media",
        responsible_id=getattr(responsible, "id", None),
        commitment_date=date(2026, 12, 31),
    )
    db.add(inc)
    db.flush()
    return inc


def make_program_event(db, title: str = "Evento de prueba", responsible=None, status: str = "Planeado"):
    from itcj2.apps.adhoc.models import AdhocProgramEvent

    ev = AdhocProgramEvent(
        title=title,
        folio=f"PRG-{title[:8]}",
        status=status,
        priority="Media",
        responsible_id=getattr(responsible, "id", None),
        commitment_date=date(2026, 12, 31),
    )
    db.add(ev)
    db.flush()
    return ev


def make_flow(db, name: str = "Flujo de prueba", steps: Sequence[str] = ("Revisión", "Autorización")):
    """Devuelve ``(flow, [step, ...])`` con ``step_order`` 1..N."""
    from itcj2.apps.adhoc.models import AdhocApprovalFlow, AdhocApprovalFlowStep

    flow = AdhocApprovalFlow(name=name)
    db.add(flow)
    db.flush()

    created = []
    for i, step_name in enumerate(steps, start=1):
        step = AdhocApprovalFlowStep(flow_id=flow.id, name=step_name, step_order=i, days_limit=3)
        db.add(step)
        created.append(step)
    db.flush()
    return flow, created


def make_document(db, title: str = "Documento de prueba", author=None, flow=None,
                  current_step=None, status: str = "En Revisión", file_url: Optional[str] = None):
    from itcj2.apps.adhoc.models import AdhocDocument

    doc = AdhocDocument(
        title=title,
        code=f"DOC-{title[:8]}",
        version="1.0",
        status=status,
        author_id=getattr(author, "id", None),
        flow_id=getattr(flow, "id", None),
        current_step_id=getattr(current_step, "id", None),
        file_url=file_url,
    )
    db.add(doc)
    db.flush()
    return doc


def make_task(db, *, incident=None, program=None, document=None, flow_step=None,
              description: str = "Tarea de prueba", status: str = "Pendiente",
              priority: str = "Media", assignees: Sequence = (), created_by=None):
    from itcj2.apps.adhoc.models import AdhocTask

    task = AdhocTask(
        description=description,
        status=status,
        priority=priority,
        incident_id=getattr(incident, "id", None),
        program_id=getattr(program, "id", None),
        document_id=getattr(document, "id", None),
        flow_step_id=getattr(flow_step, "id", None),
        created_by_id=getattr(created_by, "id", None),
    )
    for u in assignees:
        task.assignees.append(u)
    db.add(task)
    db.flush()
    return task


def add_comment(db, task, user, text: str = "Comentario de prueba", file_path: Optional[str] = None):
    from itcj2.apps.adhoc.models import AdhocTaskComment

    c = AdhocTaskComment(task_id=task.id, user_id=user.id, comment=text, file_path=file_path)
    db.add(c)
    db.flush()
    return c


def add_comment_file(db, comment, *, original_name: str = "evidencia.pdf",
                     file_path: Optional[str] = None, mime_type: Optional[str] = "application/pdf",
                     size_bytes: Optional[int] = None, uploaded_by=None):
    """Fila de ``adhoc_task_comment_files``. ``file_path=None`` simula un
    adjunto migrado cuyo binario ya no está en el servidor de origen."""
    from itcj2.apps.adhoc.models import AdhocTaskCommentFile

    f = AdhocTaskCommentFile(
        task_comment_id=comment.id,
        file_path=file_path,
        original_name=original_name,
        mime_type=mime_type,
        size_bytes=size_bytes,
        uploaded_by_id=getattr(uploaded_by, "id", None),
    )
    db.add(f)
    db.flush()
    return f


def assignee_flag(db, task_id: int, user_id: int) -> bool:
    """Lee ``notified_overdue`` de la fila de asociación (no hay relationship)."""
    from sqlalchemy import select

    from itcj2.apps.adhoc.models import adhoc_task_assignees

    row = db.execute(
        select(adhoc_task_assignees.c.notified_overdue).where(
            adhoc_task_assignees.c.task_id == task_id,
            adhoc_task_assignees.c.user_id == user_id,
        )
    ).scalar_one_or_none()
    return bool(row)
