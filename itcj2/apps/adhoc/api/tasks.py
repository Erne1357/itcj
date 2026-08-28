"""Endpoints de **tareas** y del motor de workflow — ``/api/adhoc/v2/tasks``.

El router no lleva prefijo propio: se lo pone el padre en
``itcj2/apps/adhoc/router.py`` con
``adhoc_router.include_router(tasks_router, prefix="/tasks")``.

Todo endpoint pasa por ``require_perms("adhoc", [...])``. El legacy no tenía
**ninguna** comprobación de autorización en este módulo: cualquiera con la URL
podía crear tareas, reasignarlas, aprobar documentos ajenos del SGC o
descargarse los adjuntos enumerando ids.

El endpoint de asignación del legacy (``POST /api/tasks/assign_users``) mezclaba
dos operaciones distintas detrás de un campo ``action``; si el valor no era
``assign`` ni ``notify`` respondía ``success: true`` sin haber hecho nada. Aquí
son dos rutas explícitas: ``PUT /{id}/assignees`` y
``PUT /{id}/overdue-notifications``.
"""
import logging

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile

from itcj2.apps.adhoc.schemas.tasks import (
    TaskAssigneesUpdate,
    TaskBulkCreate,
    TaskOverdueNotificationsUpdate,
    TaskUpdate,
    TaskWorkflowActionRequest,
)
from itcj2.dependencies import DbSession, is_global_admin, require_perms

router = APIRouter(tags=["adhoc-tasks"])
logger = logging.getLogger(__name__)


def _actor_context(db, user: dict) -> tuple[int, bool]:
    """``(actor_id, has_read_all)``: el contexto que decide qué ve el actor.

    Un **solo** camino para las dos preguntas que dependen de
    ``adhoc.tasks.api.read.all``: el detalle lo usa para saber si el service
    exige pertenencia (403) y los listados para emitir ``thread_readable`` en
    cada fila. Si cada uno lo calculara a su manera, la lista podría pintar un
    contador clicable sobre un hilo que el detalle contesta con 403.

    ``is_global_admin`` va primero, así que el admin global no paga la consulta
    de permisos —``require_perms`` ya lo dejó pasar por el mismo bypass—. El
    import es local a propósito: los tests parchean
    ``itcj2.core.services.authz_cache.cached_perms`` y un import de nivel de
    módulo se habría quedado con la referencia original.
    """
    from itcj2.core.services.authz_cache import cached_perms

    actor_id = int(user["sub"])
    has_read_all = is_global_admin(user) or (
        "adhoc.tasks.api.read.all" in cached_perms(db, actor_id, "adhoc")
    )
    return actor_id, has_read_all


# ==========================================================================
# Lectura
# ==========================================================================

@router.get("/mine")
def list_my_tasks(
    request: Request,
    user: dict = require_perms("adhoc", ["adhoc.tasks.api.read.own"]),
    db: DbSession = None,
):
    """Tablero de tareas del usuario autenticado.

    Misma fuente que la landing ``/adhoc/dashboard`` (que la renderiza
    server-side llamando al service directamente); este endpoint existe para
    refrescar el tablero sin recargar la página.
    """
    from itcj2.apps.adhoc.schemas.tasks import serialize_task
    from itcj2.apps.adhoc.services.task_service import AdhocTaskService

    actor_id, has_read_all = _actor_context(db, user)

    tasks = AdhocTaskService.get_dashboard_tasks(db, actor_id)
    return {
        "success": True,
        "data": [
            serialize_task(t, with_parent=True, actor_id=actor_id,
                           has_read_all=has_read_all)
            for t in tasks
        ],
        "total": len(tasks),
    }


@router.get("")
def list_tasks(
    request: Request,
    parent_type: str = Query(..., description="incident | program | document"),
    parent_id: int = Query(..., gt=0),
    user: dict = require_perms(
        "adhoc", ["adhoc.tasks.api.read.own", "adhoc.tasks.api.read.all"]
    ),
    db: DbSession = None,
):
    """Tareas colgadas de un padre concreto.

    Cada fila lleva ``thread_readable``: si este actor puede abrir el hilo de
    comentarios de **esa** tarea. La lista es el único sitio donde se puede
    responder eso por fila, y la UI lo necesita para pintar el contador de
    comentarios clicable o apagado en vez de mandar al usuario a un 403.

    Los **dos** alcances entran (``require_perms`` es OR), y eso es lo que hace
    que el flag sirva de algo. Mientras solo se admitió ``read.all``, todo el
    que lograba cargar la lista tenía alcance completo, ``thread_readable``
    salía siempre en ``True`` y el contador apagado era código que no alcanzaba
    ningún actor real — justo el rol al que estaba destinado, ``consult``
    (10 usuarios, con ``read.own`` y ``adhoc.tasks.page.list``), recibía 403 y
    veía la tabla vacía en una página que sí se le abre.

    La fila no es contenido del hilo: descripción, fechas, asignados y el
    **número** de comentarios. El hilo lo sigue guardando ``puede_leer_hilo``
    fila por fila, así que ``consult`` ve el expediente completo con la pastilla
    clicable solo donde participa.
    """
    from itcj2.apps.adhoc.schemas.tasks import serialize_task
    from itcj2.apps.adhoc.services.task_service import AdhocTaskService

    actor_id, has_read_all = _actor_context(db, user)

    tasks = AdhocTaskService.list_by_parent(db, parent_type, parent_id)
    return {
        "success": True,
        "data": [
            serialize_task(t, actor_id=actor_id, has_read_all=has_read_all)
            for t in tasks
        ],
        "total": len(tasks),
    }


@router.get("/{task_id}/workflow")
def get_task_workflow(
    task_id: int,
    request: Request,
    user: dict = require_perms(
        "adhoc", ["adhoc.tasks.api.read.own", "adhoc.tasks.api.read.all"]
    ),
    db: DbSession = None,
):
    """Detalle para el modal de workflow: tarea, padre, comentarios y aprobaciones.

    Incluye ``approvals`` —la información que el legacy destruía al modelar la
    aprobación borrando la asignación— para que la UI pueda mostrar quién ya
    validó y quién falta.

    El permiso solo dice "puede consultar detalle de ALGUNA tarea": con
    ``read.own`` (p.ej. el rol ``consult``, que no tiene ``read.all``) el
    service exige además que el actor esté asignado a la tarea o sea el
    responsable del padre — si no, 403 (D4).
    """
    from itcj2.apps.adhoc.services.task_service import AdhocTaskService

    actor_id, has_read_all = _actor_context(db, user)

    data = AdhocTaskService.get_workflow_details(
        db, task_id, actor_id=actor_id, has_read_all=has_read_all
    )
    return {"success": True, "data": data}


# ==========================================================================
# Escritura
# ==========================================================================

@router.post("")
def create_tasks(
    request: Request,
    payload: TaskBulkCreate,
    user: dict = require_perms("adhoc", ["adhoc.tasks.api.create"]),
    db: DbSession = None,
):
    """Alta masiva de tareas colgadas de un mismo padre."""
    from itcj2.apps.adhoc.schemas.tasks import serialize_task
    from itcj2.apps.adhoc.services.task_service import AdhocTaskService

    actor_id, has_read_all = _actor_context(db, user)

    created = AdhocTaskService.bulk_create(db, payload, created_by_id=actor_id)
    return {
        "success": True,
        "data": [
            serialize_task(t, actor_id=actor_id, has_read_all=has_read_all)
            for t in created
        ],
        "total": len(created),
    }


@router.patch("/{task_id}")
def update_task(
    task_id: int,
    request: Request,
    payload: TaskUpdate,
    user: dict = require_perms("adhoc", ["adhoc.tasks.api.update"]),
    db: DbSession = None,
):
    """Parche de una tarea: solo se tocan los campos presentes en el cuerpo."""
    from itcj2.apps.adhoc.schemas.tasks import serialize_task
    from itcj2.apps.adhoc.services.task_service import AdhocTaskService

    changes = payload.changes()
    if not changes:
        raise HTTPException(status_code=400, detail="No se envió ningún campo a modificar")

    actor_id, has_read_all = _actor_context(db, user)

    task = AdhocTaskService.update(db, task_id, changes, actor_id=actor_id)
    return {
        "success": True,
        "data": serialize_task(task, actor_id=actor_id, has_read_all=has_read_all),
    }


@router.delete("/{task_id}")
def delete_task(
    task_id: int,
    request: Request,
    user: dict = require_perms("adhoc", ["adhoc.tasks.api.delete"]),
    db: DbSession = None,
):
    """Elimina la tarea; sus comentarios y aprobaciones caen por cascade."""
    from itcj2.apps.adhoc.services.task_service import AdhocTaskService

    AdhocTaskService.delete(db, task_id)
    return {"success": True, "message": "Tarea eliminada correctamente."}


@router.put("/{task_id}/assignees")
def set_task_assignees(
    task_id: int,
    request: Request,
    payload: TaskAssigneesUpdate,
    user: dict = require_perms("adhoc", ["adhoc.tasks.api.assign"]),
    db: DbSession = None,
):
    """Reemplaza la lista de responsables de la tarea."""
    from itcj2.apps.adhoc.schemas.tasks import serialize_task
    from itcj2.apps.adhoc.services.task_service import AdhocTaskService

    actor_id, has_read_all = _actor_context(db, user)

    task = AdhocTaskService.set_assignees(
        db, task_id, payload.user_ids, actor_id=actor_id
    )
    return {
        "success": True,
        "data": serialize_task(task, actor_id=actor_id, has_read_all=has_read_all),
    }


@router.put("/{task_id}/overdue-notifications")
def set_task_overdue_notifications(
    task_id: int,
    request: Request,
    payload: TaskOverdueNotificationsUpdate,
    user: dict = require_perms("adhoc", ["adhoc.tasks.api.assign"]),
    db: DbSession = None,
):
    """Marca a quién avisar del vencimiento de la tarea.

    **Efecto de negocio intencional, heredado del legacy** (``api_tasks.py:219``):
    la tarea pasa a ``priority = 'Urgente'``. Marcar avisos de vencimiento es,
    en la UX del SGC, escalar la tarea — no es un accidente de implementación.
    """
    from itcj2.apps.adhoc.schemas.tasks import serialize_task
    from itcj2.apps.adhoc.services.task_service import AdhocTaskService

    actor_id, has_read_all = _actor_context(db, user)

    task = AdhocTaskService.set_overdue_notifications(
        db, task_id, payload.user_ids, actor_id=actor_id
    )
    return {
        "success": True,
        "data": serialize_task(task, actor_id=actor_id, has_read_all=has_read_all),
    }


@router.post("/{task_id}/workflow-action")
def run_task_workflow_action(
    task_id: int,
    request: Request,
    payload: TaskWorkflowActionRequest,
    user: dict = require_perms("adhoc", ["adhoc.tasks.api.workflow"]),
    db: DbSession = None,
):
    """Ejecuta ``terminar`` | ``rechazar`` | ``aprobar`` sobre la tarea.

    Además del permiso, el service exige que el actor **esté entre los
    asignados** de la tarea (403). El permiso dice "puedes operar flujos"; la
    asignación dice "puedes operar *este* flujo". El legacy no comprobaba
    ninguna de las dos cosas.
    """
    from itcj2.apps.adhoc.services.task_workflow_service import AdhocTaskWorkflowService

    result = AdhocTaskWorkflowService.workflow_action(
        db, task_id, payload.accion, actor_id=int(user["sub"])
    )
    return {"success": True, "message": result["message"]}


# ==========================================================================
# Comentarios
# ==========================================================================

@router.post("/{task_id}/comments")
def add_task_comment(
    task_id: int,
    request: Request,
    comment: str = Form(default=""),
    file: UploadFile = File(default=None),
    user: dict = require_perms("adhoc", ["adhoc.tasks.api.comment"]),
    db: DbSession = None,
):
    """Agrega un comentario a la tarea, con adjunto opcional (``multipart``).

    ``adhoc.tasks.api.comment`` dice "puedes comentar tareas"; la pertenencia
    dice "puedes comentar *esta*". El service exige además lo segundo, con el
    mismo predicado que decide el 403 del hilo: escribir en un expediente no
    puede ser más fácil que leerlo, y ``consult`` tiene este permiso.
    """
    from itcj2.apps.adhoc.schemas.tasks import serialize_comment
    from itcj2.apps.adhoc.services.task_service import AdhocTaskService

    actor_id, has_read_all = _actor_context(db, user)

    nuevo = AdhocTaskService.add_comment(
        db, task_id, actor_id, comment, upload=file, has_read_all=has_read_all
    )
    return {"success": True, "data": serialize_comment(nuevo)}


@router.get("/comments/files/{file_id}/download")
def download_task_comment_file_by_id(
    file_id: int,
    request: Request,
    user: dict = require_perms("adhoc", ["adhoc.tasks.api.comment"]),
    db: DbSession = None,
):
    """Descarga un adjunto de ``adhoc_task_comment_files`` por **id de archivo**.

    Declarada ANTES de ``/comments/{comment_id}/download``: aunque el número de
    segmentos difiere, el resto del router (``incidents``/``programs``) sigue
    esta misma convención de poner las rutas ``/files/{...}`` antes de las
    genéricas por id, así que se replica aquí para no ser la excepción que
    rompe la regla el día que alguien reordene el archivo.

    Un comentario puede tener varios adjuntos (85 del histórico migrado, uno
    con 14) — ``file_path`` en ``adhoc_task_comments`` solo admitía uno. Esta
    ruta es la única forma de bajarse los adjuntos que no entraron ahí.

    El permiso no alcanza: el service pide además pertenencia al hilo dueño del
    archivo. Son 533 filas con ids correlativos desde 1, así que sin ese gate
    bastaba enumerar para bajarse el expediente entero del SGC.
    """
    from fastapi.responses import FileResponse

    from itcj2.apps.adhoc.services import upload_service
    from itcj2.apps.adhoc.services.task_service import AdhocTaskService

    actor_id, has_read_all = _actor_context(db, user)

    file_row, path = AdhocTaskService.get_comment_file_download(
        db, file_id, actor_id=actor_id, has_read_all=has_read_all
    )
    return FileResponse(
        str(path),
        media_type=file_row.mime_type or "application/octet-stream",
        # `original_name` no siempre trae extensión — ver `download_name`.
        filename=upload_service.download_name(path, file_row.original_name),
    )


@router.get("/comments/{comment_id}/download")
def download_task_comment_file(
    comment_id: int,
    request: Request,
    user: dict = require_perms("adhoc", ["adhoc.tasks.api.comment"]),
    db: DbSession = None,
):
    """Descarga el adjunto **heredado** de un comentario (``file_path``).

    Con permiso obligatorio, pertenencia al hilo y ``safe_join`` en el service:
    el legacy servía estos archivos de forma anónima y bastaba enumerar ids
    para bajarse los adjuntos de todo el sistema de calidad.
    """
    from fastapi.responses import FileResponse

    from itcj2.apps.adhoc.services.task_service import AdhocTaskService

    actor_id, has_read_all = _actor_context(db, user)

    comment, path = AdhocTaskService.get_comment_download(
        db, comment_id, actor_id=actor_id, has_read_all=has_read_all
    )
    return FileResponse(path, filename=path.name)
