"""
Tareas Celery del módulo Core — Notificaciones masivas.

Tareas disponibles:
    send_mass_notification — crea registros Notification para un conjunto de usuarios
                             y los empuja por Socket.IO vía Redis Pub/Sub
"""
import json
import logging
from typing import Any

from itcj2.celery_app import celery_app
from itcj2.tasks.base import LoggedTask

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Metadata de registro (se usa en CLI sync-tasks para poblar TaskDefinition)
# ---------------------------------------------------------------------------

TASK_DEFINITIONS = [
    {
        "task_name": "itcj2.tasks.notification_tasks.send_mass_notification",
        "display_name": "Notificación Masiva",
        "description": (
            "Envía una notificación a múltiples usuarios según el criterio indicado "
            "en el campo 'target' (all, role:<app>.<rol>, app:<clave>, users:[id,...])."
        ),
        "app_name": "core",
        "category": "notification",
        "default_args": {
            "title": "",
            "message": "",
            "target": "all",
            "app_name": "core",
            "link": None,
        },
    },
]


# ---------------------------------------------------------------------------
# Helpers privados
# ---------------------------------------------------------------------------

def _resolve_target_user_ids(db, target: str) -> list[int]:
    """Resuelve el criterio 'target' a una lista de user_ids activos.

    Formatos soportados:
        "all"                      → todos los usuarios activos
        "role:<app_key>.<name>"    → usuarios con ese rol en esa app (UserAppRole)
        "role:<name>"              → usuarios con ese rol global (User.role)
        "app:<app_key>"            → usuarios con cualquier rol en esa app
        "users:[1,2,3]"            → IDs explícitos (lista JSON)
    """
    from itcj2.core.models.user import User

    if target == "all":
        rows = db.query(User.id).filter(User.is_active.is_(True)).all()
        return [r.id for r in rows]

    if target.startswith("role:"):
        role_spec = target[5:]

        if "." in role_spec:
            # Rol en app específica: "helpdesk.tecnico"
            app_key, role_name = role_spec.split(".", 1)
            return _users_by_app_role(db, app_key, role_name)

        # Rol global
        from itcj2.core.models.role import Role
        rows = (
            db.query(User.id)
            .join(User.role)
            .filter(User.is_active.is_(True), Role.name == role_spec)
            .all()
        )
        return [r.id for r in rows]

    if target.startswith("app:"):
        app_key = target[4:]
        return _users_by_app_role(db, app_key, role_name=None)

    if target.startswith("users:"):
        raw = target[6:]
        try:
            ids = json.loads(raw)
            if not isinstance(ids, list):
                raise ValueError("Se esperaba una lista JSON")
            return [int(i) for i in ids]
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"[send_mass_notification] target inválido '{target}': {e}")
            return []

    logger.warning(f"[send_mass_notification] target desconocido: '{target}'")
    return []


def _users_by_app_role(db, app_key: str, role_name: str | None) -> list[int]:
    """Usuarios que tienen un rol (o cualquier rol) en una app concreta."""
    from itcj2.core.models.user import User
    from itcj2.core.models.user_app_role import UserAppRole
    from itcj2.core.models.app import App
    from itcj2.core.models.role import Role

    query = (
        db.query(User.id)
        .join(UserAppRole, UserAppRole.user_id == User.id)
        .join(App, App.id == UserAppRole.app_id)
        .filter(User.is_active.is_(True), App.key == app_key)
    )

    if role_name is not None:
        query = query.join(Role, Role.id == UserAppRole.role_id).filter(
            Role.name == role_name
        )

    rows = query.distinct().all()
    return [r.id for r in rows]


def _create_notifications_batch(
    db,
    user_ids: list[int],
    title: str,
    body: str,
    app_name: str,
    link: str | None,
) -> list[dict]:
    """Inserta Notification records en bloque y devuelve sus dicts serializados."""
    from itcj2.core.models.notification import Notification

    notifications = [
        Notification(
            user_id=uid,
            app_name=app_name,
            type="SYSTEM",
            title=title,
            body=body,
            data={"url": link} if link else {},
        )
        for uid in user_ids
    ]
    db.add_all(notifications)
    db.flush()  # Obtiene IDs sin cerrar la transacción
    notif_dicts = [n.to_dict() for n in notifications]
    db.commit()
    return notif_dicts


def _push_user_notifications(notif_dicts: list[dict]) -> None:
    """Publica en Redis un evento 'user_notification' por cada notificación
    para que Uvicorn la retransmita por Socket.IO en tiempo real.
    """
    try:
        import redis
        from itcj2.config import get_settings

        r = redis.from_url(get_settings().REDIS_URL)
        for notif in notif_dicts:
            r.publish("task_events", json.dumps({
                "type": "user_notification",
                "user_id": notif["user_id"] if "user_id" in notif else None,
                "notification": notif,
            }))
    except Exception as e:
        logger.error(f"[send_mass_notification] Error publicando en Redis: {e}")


# ---------------------------------------------------------------------------
# send_mass_notification
# ---------------------------------------------------------------------------

_BATCH_SIZE = 100


@celery_app.task(
    bind=True,
    base=LoggedTask,
    name="itcj2.tasks.notification_tasks.send_mass_notification",
    max_retries=1,
    default_retry_delay=30,
    soft_time_limit=120,
    time_limit=150,
    queue="notifications",
)
def send_mass_notification(
    self,
    task_run_id: int,
    title: str,
    message: str,
    target: str,
    app_name: str = "core",
    link: str | None = None,
) -> dict[str, Any]:
    """
    Crea registros Notification para un conjunto de usuarios y los empuja
    por Socket.IO vía Redis Pub/Sub.

    Args:
        task_run_id:  ID del TaskRun creado por la API antes de encolar esta tarea.
        title:        Título visible en la notificación.
        message:      Cuerpo del mensaje.
        target:       Criterio de destinatarios (ver _resolve_target_user_ids).
        app_name:     App origen de la notificación.
        link:         URL opcional a la que redirige la notificación.

    Returns:
        dict con claves: sent_to, failed, target
    """
    from itcj2.database import SessionLocal

    logger.info(
        f"[send_mass_notification] Iniciando — target='{target}', "
        f"title='{title}', task_run_id={task_run_id}"
    )

    # ── Paso 1: resolver destinatarios ─────────────────────────────────
    self.update_progress(task_run_id, current=0, total=3, message="Resolviendo destinatarios...")

    with SessionLocal() as db:
        user_ids = _resolve_target_user_ids(db, target)

    total_users = len(user_ids)
    logger.info(f"[send_mass_notification] {total_users} destinatarios resueltos")

    if total_users == 0:
        return {"sent_to": 0, "failed": 0, "target": target}

    # ── Paso 2: crear notificaciones en lotes ──────────────────────────
    self.update_progress(
        task_run_id, current=1, total=3,
        message=f"Creando notificaciones para {total_users} usuarios...",
    )

    sent = 0
    failed = 0

    for batch_start in range(0, total_users, _BATCH_SIZE):
        batch_ids = user_ids[batch_start: batch_start + _BATCH_SIZE]
        try:
            with SessionLocal() as db:
                notif_dicts = _create_notifications_batch(
                    db, batch_ids, title, message, app_name, link
                )
            _push_user_notifications(notif_dicts)
            sent += len(batch_ids)
        except Exception as exc:
            failed += len(batch_ids)
            logger.error(
                f"[send_mass_notification] Error en lote {batch_start}–"
                f"{batch_start + len(batch_ids)}: {exc}"
            )

        # Actualizar progreso proporcional al porcentaje de lotes procesados
        progress_pct = int(10 + (sent / total_users) * 85)
        self.update_progress(
            task_run_id, current=progress_pct, total=100,
            message=f"Enviadas {sent}/{total_users}...",
        )

    # ── Paso 3: finalizar ─────────────────────────────────────────────
    self.update_progress(task_run_id, current=3, total=3, message="Completado")

    result = {"sent_to": sent, "failed": failed, "target": target}
    logger.info(f"[send_mass_notification] Completado: {result}")
    return result
