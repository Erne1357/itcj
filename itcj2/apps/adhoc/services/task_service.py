"""Lógica de negocio de las **tareas** del SGC.

Cubre el CRUD, la asignación de responsables, los comentarios con adjunto y el
tablero del dashboard. El motor de aprobación vive aparte, en
``task_workflow_service`` — aquí no hay ninguna transición de estado de
documento.

Convenciones del repo que aplican a todo el módulo: métodos ``@staticmethod``,
``db: Session`` como primer parámetro, **el ``commit()`` va en el service**,
``db.get(Model, id)`` para PK y ``selectinload`` para matar los N+1 (el legacy
disparaba una query por tarea, otra por comentario y otra por autor de
comentario en cada render del tablero).

Notificaciones: se disparan **después** del commit de negocio y son
*fail-soft* — un fallo de Redis, de Socket.IO o del buzón de Graph nunca puede
tumbar una operación del SGC. Es la única propiedad del legacy que valía la
pena conservar tal cual.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Iterable, Optional

from fastapi import HTTPException
from sqlalchemy import and_, nulls_last, or_, select, update
from sqlalchemy.orm import Session, selectinload

logger = logging.getLogger(__name__)

__all__ = ["AdhocTaskService"]


# ==========================================================================
# Internos
# ==========================================================================

#: ``parent_type`` → (modelo del padre, nombre de la FK en ``adhoc_tasks``).
#: Las tres FK son mutuamente excluyentes por ``ck_adhoc_tasks_single_parent``.
_PARENTS: dict[str, tuple[str, str]] = {
    "incident": ("AdhocIncident", "incident_id"),
    "program": ("AdhocProgramEvent", "program_id"),
    "document": ("AdhocDocument", "document_id"),
}


def _parent_model(parent_type: str):
    from itcj2.apps.adhoc import models as adhoc_models

    try:
        class_name, column = _PARENTS[parent_type]
    except KeyError:
        raise HTTPException(
            status_code=400,
            detail=f"Tipo de padre inválido: {parent_type}",
        )
    return getattr(adhoc_models, class_name), column


def _load_task(db: Session, task_id: int, *, eager: bool = False):
    """``db.get`` con 404 legible. ``eager`` para las rutas que serializan."""
    from itcj2.apps.adhoc.models import (
        AdhocDocument,
        AdhocIncident,
        AdhocProgramEvent,
        AdhocTask,
        AdhocTaskApproval,
        AdhocTaskComment,
    )

    if eager:
        task = (
            db.query(AdhocTask)
            .options(
                selectinload(AdhocTask.assignees),
                selectinload(AdhocTask.comments).selectinload(AdhocTaskComment.user),
                selectinload(AdhocTask.comments).selectinload(AdhocTaskComment.files),
                selectinload(AdhocTask.approvals).selectinload(AdhocTaskApproval.user),
                selectinload(AdhocTask.document).selectinload(AdhocDocument.author),
                selectinload(AdhocTask.document).selectinload(AdhocDocument.current_step),
                selectinload(AdhocTask.incident).selectinload(AdhocIncident.area),
                selectinload(AdhocTask.incident).selectinload(AdhocIncident.process),
                selectinload(AdhocTask.incident).selectinload(AdhocIncident.responsible),
                selectinload(AdhocTask.program).selectinload(AdhocProgramEvent.area),
                selectinload(AdhocTask.program).selectinload(AdhocProgramEvent.process),
                selectinload(AdhocTask.program).selectinload(AdhocProgramEvent.responsible),
                selectinload(AdhocTask.flow_step),
            )
            .filter(AdhocTask.id == task_id)
            .first()
        )
    else:
        task = db.get(AdhocTask, task_id)

    if task is None:
        raise HTTPException(status_code=404, detail="Tarea no encontrada")
    return task


def _resolve_users(db: Session, user_ids: Iterable[int]) -> list:
    """Carga los ``User`` de una lista de ids en **una** query.

    Los ids inexistentes se ignoran en silencio (el legacy hacía
    ``User.query.get(uid)`` dentro del bucle: N+1 y, si el id era basura,
    reventaba el lote entero).
    """
    from itcj2.core.models.user import User

    ids = [int(uid) for uid in user_ids or []]
    if not ids:
        return []
    found = db.query(User).filter(User.id.in_(ids)).all()
    by_id = {u.id: u for u in found}
    return [by_id[i] for i in dict.fromkeys(ids) if i in by_id]


def _notify(db: Session, fn, *args, **kwargs) -> None:
    """Crea notificaciones in-app y las commitea. Nunca lanza.

    ``NotificationService.create`` hace ``add()`` + ``flush()`` sin commit (plan
    §7), así que la transacción es responsabilidad de quien llama: aquí.
    """
    try:
        fn(db, *args, **kwargs)
        db.commit()
    except Exception:
        logger.exception("[adhoc] Fallo notificando (%s); se continúa", getattr(fn, "__name__", fn))
        try:
            db.rollback()
        except Exception:
            pass


def _email(fn, *args, **kwargs) -> None:
    """Dispara un correo transaccional. Nunca lanza (el helper ya devuelve bool)."""
    try:
        fn(*args, **kwargs)
    except Exception:
        logger.exception("[adhoc] Fallo enviando correo (%s); se continúa",
                         getattr(fn, "__name__", fn))


#: Mensaje único del 403 de las cuatro puertas del hilo. Uno solo porque el
#: motivo es uno solo: no participas en esta tarea. Cuatro textos distintos
#: para el mismo veredicto solo le dirían al de fuera por qué puerta entró.
_SIN_ACCESO_AL_HILO = "No tienes acceso al historial de esta tarea"


def _exigir_acceso_al_hilo(task, *, actor_id: Optional[int], has_read_all: bool) -> None:
    """403 si el actor no alcanza el hilo de ``task``. **Único gate del hilo.**

    El hilo de una tarea tiene CUATRO puertas y todas pasan por aquí:

    * ``GET /tasks/{id}/workflow`` — el hilo entero;
    * ``GET /tasks/comments/{id}/download`` — el adjunto heredado;
    * ``GET /tasks/comments/files/{id}/download`` — los adjuntos 0..N;
    * ``POST /tasks/{id}/comments`` — escribir en él.

    Hasta la auditoría de B3 solo la primera preguntaba por la pertenencia: las
    otras tres se conformaban con ``adhoc.tasks.api.comment``, que el rol
    ``consult`` tiene, así que el mismo actor recibía **403** en el hilo y
    **200** en su contenido. Con 533 adjuntos de ids correlativos desde 1,
    enumerar bajaba el expediente entero del SGC.

    La regla no se escribe aquí: es
    :func:`~itcj2.apps.adhoc.schemas.tasks.puede_leer_hilo`, la misma con la que
    ``serialize_task`` emite ``thread_readable``. Una función pura, un veredicto,
    cuatro puertas — o vuelven a divergir.

    Escribir es *participar*, así que el gate de ``add_comment`` no puede ser
    más ancho que el de leer; que sea exactamente el mismo es deliberado: quien
    tiene ``read.all`` (supervisores y admin) comenta hoy sobre cualquier tarea
    del SGC y estrecharlo sería un cambio de producto, no un arreglo.
    """
    from itcj2.apps.adhoc.schemas.tasks import puede_leer_hilo

    if not puede_leer_hilo(task, actor_id=actor_id, has_read_all=has_read_all):
        raise HTTPException(status_code=403, detail=_SIN_ACCESO_AL_HILO)


def _assignee_flags(db: Session, task_id: int) -> dict[int, bool]:
    """``{user_id: notified_overdue}`` de la tabla de asociación."""
    from itcj2.apps.adhoc.models import adhoc_task_assignees

    rows = db.execute(
        select(
            adhoc_task_assignees.c.user_id,
            adhoc_task_assignees.c.notified_overdue,
        ).where(adhoc_task_assignees.c.task_id == task_id)
    ).all()
    return {int(uid): bool(flag) for uid, flag in rows}


# ==========================================================================
# Service
# ==========================================================================

class AdhocTaskService:
    """Tareas colgadas de una incidencia, un evento de programa o un documento."""

    # ---------------------------------------------------------------- lectura

    @staticmethod
    def list_by_parent(db: Session, parent_type: str, parent_id: int) -> list:
        """Tareas de un padre concreto, con asignados y comentarios precargados.

        ``incident`` y ``program`` entran en el *eager loading* porque el
        serializador evalúa
        :func:`~itcj2.apps.adhoc.schemas.tasks.puede_leer_hilo` sobre cada fila
        y el predicado los toca. Medido contra la base real (la incidencia con
        más tareas, 12 filas) el coste sin ellos ya era **una** query y no una
        por fila: son *many-to-one*, así que SQLAlchemy las resuelve por el
        identity map después de la primera. Es decir, esto no arregla un N+1
        —cuesta lo mismo, una query—, sino que deja de depender de esa
        optimización para que el N+1 siga sin existir el día que alguien
        cambie el predicado.
        """
        from itcj2.apps.adhoc.models import AdhocTask

        model, column = _parent_model(parent_type)
        if db.get(model, parent_id) is None:
            raise HTTPException(status_code=404, detail="El registro padre no existe")

        return (
            db.query(AdhocTask)
            .options(
                selectinload(AdhocTask.assignees),
                selectinload(AdhocTask.comments),
                selectinload(AdhocTask.incident),
                selectinload(AdhocTask.program),
                selectinload(AdhocTask.flow_step),
            )
            .filter(getattr(AdhocTask, column) == parent_id)
            .order_by(nulls_last(AdhocTask.due_date.asc()), AdhocTask.id.asc())
            .all()
        )

    @staticmethod
    def get_dashboard_tasks(db: Session, user_id: int) -> list:
        """Tablero de tareas del usuario — los 4 predicados del plan §3.b.

        1. **Ejecutor**: asignado y la tarea sigue abierta
           (``Pendiente`` / ``Rechazada`` / ``En Proceso``).
        2. **Revisor de incidencia**: responsable de la incidencia padre y la
           tarea está ``En Revisión``.
        3. **Revisor de evento de programa**: idem con el evento.
        4. **Validador documental**: asignado a una tarea de documento
           ``En Revisión`` o ``En Espera``.

        Una sola query con ``or_()`` de los cuatro (el legacy concatenaba cuatro
        listas en Python) y ``.distinct()`` porque una tarea documental asignada
        al propio usuario cae en las ramas 1 y 4 a la vez.
        """
        from itcj2.apps.adhoc.models import AdhocIncident, AdhocProgramEvent, AdhocTask
        from itcj2.apps.adhoc.utils.constants import (
            TASK_OPEN_STATUSES,
            TASK_STATUS_IN_REVIEW,
            TASK_STATUS_WAITING,
        )
        from itcj2.core.models.user import User

        uid = int(user_id)
        soy_asignado = AdhocTask.assignees.any(User.id == uid)

        ejecutor = and_(soy_asignado, AdhocTask.status.in_(TASK_OPEN_STATUSES))
        revisor_incidencia = and_(
            AdhocTask.status == TASK_STATUS_IN_REVIEW,
            AdhocTask.incident.has(AdhocIncident.responsible_id == uid),
        )
        revisor_programa = and_(
            AdhocTask.status == TASK_STATUS_IN_REVIEW,
            AdhocTask.program.has(AdhocProgramEvent.responsible_id == uid),
        )
        validador_documental = and_(
            soy_asignado,
            AdhocTask.document_id.isnot(None),
            AdhocTask.status.in_((TASK_STATUS_IN_REVIEW, TASK_STATUS_WAITING)),
        )

        return (
            db.query(AdhocTask)
            .options(
                selectinload(AdhocTask.assignees),
                selectinload(AdhocTask.comments),
                selectinload(AdhocTask.document),
                selectinload(AdhocTask.incident),
                selectinload(AdhocTask.program),
                selectinload(AdhocTask.flow_step),
            )
            .filter(or_(ejecutor, revisor_incidencia, revisor_programa, validador_documental))
            .distinct()
            .order_by(nulls_last(AdhocTask.due_date.asc()), AdhocTask.id.asc())
            .all()
        )

    @staticmethod
    def get_workflow_details(db: Session, task_id: int, *, actor_id: int,
                             has_read_all: bool) -> dict:
        """Payload del modal de workflow: tarea + padre + comentarios + aprobaciones.

        Sin ``adhoc.tasks.api.read.all`` (``has_read_all=False``) el actor tiene
        que estar asignado a la tarea o ser el responsable del padre —el mismo
        predicado "asignado o responsable" que decide si la tarea aparece en su
        tablero (ver :meth:`get_dashboard_tasks`)— o **403** (D4). Antes de este
        fix, tener solo ``adhoc.tasks.api.read.own`` (p.ej. el rol ``consult``)
        alcanzaba para leer el detalle completo de cualquier tarea del sistema:
        comentarios, aprobaciones, todo.

        La regla no se escribe aquí: es
        :func:`~itcj2.apps.adhoc.schemas.tasks.puede_leer_hilo`, la **misma**
        función con la que ``serialize_task`` emite ``thread_readable``. Este
        403 y el flag con el que la lista de tareas decide si el contador de
        comentarios es clicable tienen que ser la misma frase, o la UI termina
        ofreciendo un botón que el servidor contesta con 403.

        Se aplica por :func:`_exigir_acceso_al_hilo`, que es también el gate de
        las otras tres puertas del hilo (los dos adjuntos y el alta de
        comentario).
        """
        from itcj2.apps.adhoc.schemas.tasks import serialize_workflow_details

        task = _load_task(db, task_id, eager=True)
        _exigir_acceso_al_hilo(task, actor_id=actor_id, has_read_all=has_read_all)

        return serialize_workflow_details(task)

    # ------------------------------------------------------------- escritura

    @staticmethod
    def bulk_create(db: Session, payload, created_by_id: Optional[int]) -> list:
        """Alta masiva de tareas colgadas de un mismo padre.

        Valida que el padre exista (**404**) antes de insertar nada: el legacy
        creaba tareas huérfanas cuando ``parent_id`` no era un dígito, algo que
        hoy además rechazaría ``ck_adhoc_tasks_single_parent``.
        """
        from itcj2.apps.adhoc.models import AdhocTask
        from itcj2.apps.adhoc.services import notify
        from itcj2.apps.adhoc.services.email_helper import AdhocEmailHelper

        model, column = _parent_model(payload.parent_type)
        if db.get(model, payload.parent_id) is None:
            raise HTTPException(status_code=404, detail="El registro padre no existe")

        # Una sola query para TODOS los asignados del lote (el legacy: una por fila).
        todos_los_ids = {uid for item in payload.tasks for uid in item.assignee_ids}
        usuarios = {u.id: u for u in _resolve_users(db, todos_los_ids)}

        creadas = []
        for item in payload.tasks:
            task = AdhocTask(
                description=item.description,
                status=item.status,
                priority=item.priority,
                start_date=item.start_date,
                due_date=item.due_date,
                created_by_id=created_by_id,
            )
            setattr(task, column, payload.parent_id)
            for uid in item.assignee_ids:
                if uid in usuarios:
                    task.assignees.append(usuarios[uid])
            db.add(task)
            creadas.append(task)

        db.commit()
        for task in creadas:
            db.refresh(task)

        for task in creadas:
            if task.assignees:
                _notify(db, notify.notify_task_created, task, list(task.assignees))
                _email(AdhocEmailHelper.send_task_assigned, db, task, list(task.assignees))

        return creadas

    @staticmethod
    def update(db: Session, task_id: int, changes: dict, actor_id: Optional[int]):
        """Parche de una tarea. Solo toca los campos presentes en ``changes``.

        Regla ``completed_at`` ↔ ``Completada`` (heredada del legacy): al pasar a
        ``Completada`` se sella la fecha si no la tenía. La limpieza es más
        angosta que en el legacy (D1): solo se borra cuando el ``status``
        **cambia en esta misma edición** y el nuevo valor es de trabajo abierto
        (:data:`TASK_OPEN_STATUSES`). Sin esa condición, cualquier PATCH que no
        tocara el status —aunque fuera solo la prioridad— le borraba la fecha a
        una tarea que ``task_workflow_service._generic_task`` había dejado en
        ``'En Revisión'`` con ``completed_at`` ya sellado, que es la fuente del
        dashboard.
        """
        from itcj2.apps.adhoc.services import notify
        from itcj2.apps.adhoc.services.email_helper import AdhocEmailHelper
        from itcj2.apps.adhoc.utils.constants import TASK_OPEN_STATUSES, TASK_STATUS_COMPLETED

        task = _load_task(db, task_id)

        if "description" in changes and not (changes["description"] or "").strip():
            raise HTTPException(status_code=400, detail="La descripción no puede estar vacía")

        descripcion_previa, estatus_previo = task.description, task.status

        for campo in ("description", "status", "priority", "start_date", "due_date"):
            if campo in changes:
                valor = changes[campo]
                if valor is None and campo in ("status", "priority"):
                    continue  # NOT NULL con CheckConstraint: un None no borra nada
                setattr(task, campo, valor)

        estatus_cambio = "status" in changes and task.status != estatus_previo

        if task.status == TASK_STATUS_COMPLETED:
            if not task.completed_at:
                task.completed_at = datetime.now()
        elif estatus_cambio and task.status in TASK_OPEN_STATUSES:
            task.completed_at = None

        db.commit()
        db.refresh(task)

        if descripcion_previa != task.description or estatus_previo != task.status:
            destinatarios = list(task.assignees)
            if destinatarios:
                _notify(db, notify.notify_task_updated, task, destinatarios,
                        action_label="Tarea actualizada", actor_id=actor_id)
                _email(AdhocEmailHelper.send_task_updated, db, task, destinatarios,
                       action_label="Tarea actualizada")

        return task

    @staticmethod
    def delete(db: Session, task_id: int) -> None:
        """Borra la tarea. Sus comentarios y aprobaciones caen por cascade."""
        task = _load_task(db, task_id)
        db.delete(task)
        db.commit()

    @staticmethod
    def set_assignees(db: Session, task_id: int, user_ids: list[int], actor_id: Optional[int]):
        """Reemplaza la lista de asignados por la recibida.

        **Preserva ``notified_overdue``** de quien sigue asignado: el legacy
        hacía ``task.assigned_users = []`` y volvía a añadir, borrando la
        bandera de aviso de vencimiento de todo el mundo sin decir nada.
        Solo se notifica a los **nuevos**: reasignar a quien ya estaba no es un
        evento.
        """
        from itcj2.apps.adhoc.models import adhoc_task_assignees
        from itcj2.apps.adhoc.services import notify
        from itcj2.apps.adhoc.services.email_helper import AdhocEmailHelper

        task = _load_task(db, task_id)

        flags_previas = _assignee_flags(db, task.id)
        previos = set(flags_previas)

        usuarios = _resolve_users(db, user_ids)
        task.assignees = usuarios
        db.flush()

        conservan_bandera = [u.id for u in usuarios if flags_previas.get(u.id)]
        if conservan_bandera:
            db.execute(
                update(adhoc_task_assignees)
                .where(
                    adhoc_task_assignees.c.task_id == task.id,
                    adhoc_task_assignees.c.user_id.in_(conservan_bandera),
                )
                .values(notified_overdue=True)
            )

        db.commit()
        db.refresh(task)

        nuevos = [u for u in usuarios if u.id not in previos]
        if nuevos:
            _notify(db, notify.notify_task_assignees_changed, task, nuevos)
            _email(AdhocEmailHelper.send_task_assigned, db, task, nuevos)

        return task

    @staticmethod
    def set_overdue_notifications(db: Session, task_id: int, user_ids: list[int],
                                  actor_id: Optional[int]):
        """Marca quién recibe el aviso de vencimiento de la tarea.

        **Efecto de negocio conservado del legacy** (``api_tasks.py:219``): la
        tarea pasa a ``priority = 'Urgente'``. No es un accidente: marcar avisos
        de vencimiento es, en la UX del SGC, escalar la tarea, y la lista del
        dashboard la pinta en rojo por esa prioridad. D3 manda "misma UX".

        Quien esté en ``user_ids`` y no estuviera asignado **se agrega** a los
        asignados (no se puede avisar de un vencimiento a quien no es
        responsable); los ausentes de la lista quedan desmarcados pero siguen
        asignados.
        """
        from itcj2.apps.adhoc.models import adhoc_task_assignees

        task = _load_task(db, task_id)

        db.execute(
            update(adhoc_task_assignees)
            .where(adhoc_task_assignees.c.task_id == task.id)
            .values(notified_overdue=False)
        )

        ya_asignados = {u.id for u in task.assignees}
        for user in _resolve_users(db, user_ids):
            if user.id not in ya_asignados:
                task.assignees.append(user)
        db.flush()

        marcados = [uid for uid in user_ids if uid in {u.id for u in task.assignees}]
        if marcados:
            db.execute(
                update(adhoc_task_assignees)
                .where(
                    adhoc_task_assignees.c.task_id == task.id,
                    adhoc_task_assignees.c.user_id.in_(marcados),
                )
                .values(notified_overdue=True)
            )
            task.priority = "Urgente"

        db.commit()
        db.refresh(task)
        return task

    # ------------------------------------------------------------ comentarios

    @staticmethod
    def add_comment(db: Session, task_id: int, user_id: Optional[int],
                    comment: Optional[str], upload: Any = None, *,
                    has_read_all: bool):
        """Agrega un comentario, con adjunto opcional.

        ``comment`` y ``user_id`` son NOT NULL en ``adhoc_task_comments``: el
        legacy no validaba ninguno de los dos y el ``IntegrityError`` salía como
        500. Aquí son **400** con mensaje.

        ``has_read_all`` es obligatorio y sin defecto a propósito: es la mitad
        del contexto del actor que este service no puede deducir, y un defecto
        —cualquiera de los dos— convertiría un olvido en el call site en una
        puerta abierta o en un 403 falso. Con él, :func:`_exigir_acceso_al_hilo`
        aplica el mismo veredicto que el resto del hilo: escribir en un
        expediente ajeno no puede ser más fácil que leerlo.
        """
        from itcj2.apps.adhoc.models import AdhocTaskComment
        from itcj2.apps.adhoc.services import notify
        from itcj2.apps.adhoc.services.email_helper import AdhocEmailHelper
        from itcj2.apps.adhoc.services.upload_service import save_upload

        task = _load_task(db, task_id)

        # Identificar al actor → autorizarlo → validar lo que manda, en ese
        # orden. Es el mismo que sigue `task_workflow_service`: la pertenencia
        # se comprueba antes que la validez del cuerpo para no contarle nada
        # del expediente a quien no participa en él.
        if not user_id:
            raise HTTPException(status_code=400, detail="No se pudo identificar al autor del comentario")

        _exigir_acceso_al_hilo(task, actor_id=user_id, has_read_all=has_read_all)

        texto = (comment or "").strip()
        if not texto:
            raise HTTPException(status_code=400, detail="El comentario no puede estar vacío")

        nuevo = AdhocTaskComment(task_id=task.id, user_id=int(user_id), comment=texto)

        if upload is not None and getattr(upload, "filename", None):
            try:
                meta = save_upload("task_comments", task.id, upload)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            nuevo.file_path = meta["file_path"]

        db.add(nuevo)
        db.commit()
        db.refresh(nuevo)

        destinatarios = [u for u in task.assignees if u.id != int(user_id)]
        if destinatarios:
            _notify(db, notify.notify_task_commented, task, nuevo, destinatarios,
                    actor_id=int(user_id))
            _email(AdhocEmailHelper.send_task_updated, db, task, destinatarios,
                   action_label="Nuevo comentario en tarea")

        return nuevo

    @staticmethod
    def get_comment_download(db: Session, comment_id: int, *, actor_id: Optional[int],
                             has_read_all: bool):
        """``(comentario, ruta absoluta verificada)`` para el endpoint de descarga.

        ``open_stored`` aplica ``safe_join``: una fila envenenada con
        ``../../etc/passwd`` da **404**, no una lectura fuera de la raíz. El
        legacy servía estos adjuntos **sin autenticación** (IDOR).

        Tener ``adhoc.tasks.api.comment`` no basta —lo tiene el rol
        ``consult``—: el adjunto pertenece al hilo de su tarea y se sirve con el
        mismo veredicto que el hilo (:func:`_exigir_acceso_al_hilo`). El orden
        es resolver la fila (**404**), autorizar (**403**) y solo entonces mirar
        si hay binario (**404**): al revés, el 404 de "no tiene adjunto" le
        contaría a un extraño qué comentarios llevan archivo.
        """
        from itcj2.apps.adhoc.models import AdhocTaskComment
        from itcj2.apps.adhoc.services.upload_service import open_stored

        comment = db.get(AdhocTaskComment, comment_id)
        if comment is None:
            raise HTTPException(status_code=404, detail="Comentario no encontrado")

        _exigir_acceso_al_hilo(comment.task, actor_id=actor_id, has_read_all=has_read_all)

        if not comment.file_path:
            raise HTTPException(status_code=404, detail="El comentario no tiene archivo adjunto")

        try:
            path = open_stored("task_comments", comment.file_path)
        except ValueError as exc:
            logger.warning("[adhoc] Descarga de comentario %s rechazada: %s", comment_id, exc)
            raise HTTPException(status_code=404, detail="El archivo no está disponible") from exc

        return comment, path

    @staticmethod
    def get_comment_file_download(db: Session, file_id: int, *, actor_id: Optional[int],
                                  has_read_all: bool):
        """``(archivo, ruta absoluta verificada)`` para el archivo de un comentario.

        Espejo de :meth:`get_comment_download`, pero sobre
        ``adhoc_task_comment_files``: un comentario puede tener más de un
        adjunto (85 comentarios del histórico migrado, uno con 14), algo que
        ``AdhocTaskComment.file_path`` nunca pudo representar.

        Mismo gate y mismo orden que su espejo. Aquí importaba todavía más: son
        533 filas con ids correlativos desde 1, así que servirlas solo contra el
        permiso ``adhoc.tasks.api.comment`` dejaba bajar el expediente completo
        del SGC enumerando.

        ``file_path`` es NULLABLE en esta tabla — hay adjuntos migrados cuyo
        binario ya no está en el servidor del proveedor. Ese caso también da
        **404** legible, igual que uno con ``open_stored`` fallido.
        """
        from itcj2.apps.adhoc.models import AdhocTaskCommentFile
        from itcj2.apps.adhoc.services.upload_service import open_stored

        file_row = db.get(AdhocTaskCommentFile, file_id)
        if file_row is None:
            raise HTTPException(status_code=404, detail="Archivo no encontrado")

        _exigir_acceso_al_hilo(file_row.comment.task, actor_id=actor_id,
                               has_read_all=has_read_all)

        if not file_row.file_path:
            raise HTTPException(
                status_code=404,
                detail="El archivo no tiene un binario disponible "
                       "(adjunto migrado sin archivo en el servidor de origen)",
            )

        try:
            path = open_stored("task_comments", file_row.file_path)
        except ValueError as exc:
            logger.warning(
                "[adhoc] Descarga de adjunto de comentario (file_id=%s) rechazada: %s",
                file_id, exc,
            )
            raise HTTPException(status_code=404, detail="El archivo no está disponible") from exc

        return file_row, path
