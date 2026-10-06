"""
Servicio centralizado de notificaciones para todas las aplicaciones del sistema ITCJ.

Este servicio maneja la creación, almacenamiento y difusión de notificaciones
a través de WebSockets (Socket.IO).
"""
import asyncio
import logging
from datetime import datetime
from typing import Optional, Dict, List

from sqlalchemy import and_, event, func
from sqlalchemy.orm import Session

from itcj2.core.models.notification import Notification

logger = logging.getLogger(__name__)

# Sitio de `itcj_background_tasks_total` del push (conjunto cerrado de
# `observability/spawn.py`): lo mismo salga el push de un loop o de un hilo.
_PUSH_TASK = "notify_websocket_push"

# Destino del push: el loop que corre en ESTE hilo (frente al loop principal,
# que se pasa tal cual).
_HERE = object()

# Dónde guarda cada sesión sus avisos pendientes de commit (`Session.info`).
_PENDING_KEY = "itcj2.notification_service.pending_pushes"


class _PendingPushes:
    """Los avisos que una sesión creó y que esperan al commit de su transacción
    raíz: `(transacción, user_id, payload)`.

    Viven en `session.info`, no en el módulo: se van con la sesión, y una que
    nunca commitea (CLI en seco, `get_db` que revierte y cierra) no deja nada
    para otra. `transacción` es la más interna al crear el aviso (la raíz o un
    SAVEPOINT) y sirve para saber qué descarta un rollback.
    """

    __slots__ = ("items",)

    def __init__(self):
        self.items: list = []


def _pending_for(session: Session) -> _PendingPushes:
    """Los pendientes de `session`; la primera vez engancha sus tres eventos
    (por instancia: el resto de las sesiones de la app no pagan nada)."""
    pending = session.info.get(_PENDING_KEY)
    if pending is None:
        pending = session.info[_PENDING_KEY] = _PendingPushes()
        event.listen(session, "after_commit", _emit_pending_pushes)
        event.listen(session, "after_soft_rollback", _drop_rolled_back_pushes)
        event.listen(session, "after_transaction_end", _forget_pushes_at_root_end)
    return pending


def _emit_pending_pushes(session: Session) -> None:
    """`after_commit`: empuja lo pendiente cuando commitea la transacción RAÍZ.

    SQLAlchemy lo dispara también al LIBERAR un SAVEPOINT (el `commit` de la
    transacción anidada); ahí todavía hay una anidada abierta y no es el
    commit que importa: lo del SAVEPOINT sigue pendiente de la raíz.

    Corre DENTRO de `session.commit()`, ya con el commit hecho: lo que falle
    aquí no puede salir como excepción de un commit que tuvo éxito, y no toca
    la BD (el payload se armó al crear el aviso, no ahora que el commit expiró
    los objetos). El destino se vuelve a elegir en el hilo que commitea.
    """
    pending = session.info.get(_PENDING_KEY)
    if pending is None or not pending.items or session.in_nested_transaction():
        return
    items, pending.items = pending.items, []
    for _transaction, user_id, payload in items:
        try:
            destination = NotificationService._push_destination()
            if destination is not None:
                NotificationService._emit_push(destination, user_id, payload)
        except Exception as e:
            logger.error(
                f"Error broadcasting WebSocket to user {user_id}: {e}",
                exc_info=True
            )


def _drop_rolled_back_pushes(session: Session, previous_transaction) -> None:
    """`after_soft_rollback`: descarta los avisos creados dentro de la
    transacción que se revirtió (la raíz, o un SAVEPOINT con lo que sus
    SAVEPOINT internos ya liberaron). Los de fuera de ella se conservan."""
    pending = session.info.get(_PENDING_KEY)
    if pending is None or not pending.items:
        return

    def inside_rolled_back(transaction) -> bool:
        while transaction is not None:
            if transaction is previous_transaction:
                return True
            transaction = transaction.parent
        return False

    pending.items = [
        item for item in pending.items if not inside_rolled_back(item[0])
    ]


def _forget_pushes_at_root_end(session: Session, transaction) -> None:
    """`after_transaction_end` de la raíz: lo que quede es de una transacción
    que se cerró sin commit (`close()`, un rollback) y no se empuja nunca; sin
    esto, una sesión reutilizada lo arrastraría al commit siguiente. Tras un
    commit ya no queda nada: `after_commit` corre antes."""
    if transaction.parent is None:
        pending = session.info.get(_PENDING_KEY)
        if pending is not None:
            pending.items = []


class NotificationService:
    """Servicio para manejo de notificaciones cross-app"""

    @staticmethod
    def create(
        db: Session,
        user_id: int,
        app_name: str,
        type: str,
        title: str,
        body: Optional[str] = None,
        data: Optional[Dict] = None,
        **kwargs
    ) -> Notification:
        """
        Crea una nueva notificación y la difunde a través de WebSocket.

        El push NO sale al hacer el `flush`: queda en la sesión y sale cuando
        commitea la transacción raíz (se descarta si se revierte). Ver
        `_defer_push`.

        Args:
            db: Sesión de SQLAlchemy
            user_id: ID del usuario destinatario
            app_name: Nombre de la aplicación ('agendatec', 'helpdesk', etc.)
            type: Tipo de notificación ('TICKET_CREATED', 'APPOINTMENT_CANCELED', etc.)
            title: Título de la notificación
            body: Cuerpo/descripción opcional
            data: Datos adicionales en formato dict (se almacena como JSONB)
            **kwargs: Campos opcionales (ticket_id, source_request_id, etc.)

        Returns:
            La notificación creada
        """
        try:
            notification = Notification(
                user_id=user_id,
                app_name=app_name,
                type=type,
                title=title,
                body=body,
                data=data or {},
                **{k: v for k, v in kwargs.items() if k in [
                    'ticket_id', 'source_request_id',
                    'source_appointment_id', 'program_id'
                ]}
            )

            db.add(notification)
            db.flush()  # Obtener el ID sin hacer commit

            # Difundir a través de WebSocket (Socket.IO), al commit
            NotificationService._defer_push(db, user_id, notification)

            return notification

        except Exception as e:
            logger.error(
                f"Error creating notification for user {user_id}: {e}",
                exc_info=True
            )
            raise

    @staticmethod
    def _push_destination():
        """Adónde puede salir un push desde ESTE hilo, o `None`:

        - `_HERE` con un loop corriendo en el hilo actual (endpoint `async`,
          handler de socket);
        - el loop principal de la app (`itcj2.utils.main_loop`) si no hay loop
          en este hilo (una ruta `def` en el threadpool) y ese loop corre;
        - `None` sin ninguno (CLI, Celery).
        """
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            from itcj2.utils import main_loop

            loop = main_loop()
            return loop if loop is not None and loop.is_running() else None
        return _HERE

    @staticmethod
    def _emit_push(destination, user_id: int, payload: dict) -> None:
        """Agenda el push de `payload` en `destination` (de `_push_destination`)
        sin esperar su resultado.

        `spawn` y no `loop.create_task`: guarda la tarea hasta que termina (sin
        referencia, el recolector puede destruir el push a medio vuelo) y
        loguea con el `request_id` de la petición la excepción que antes se
        perdía. Hacia el loop principal, `spawn_threadsafe`.
        """
        from itcj2.observability.spawn import discard, spawn, spawn_threadsafe
        from itcj2.sockets.notifications import push_notification

        coro = push_notification(user_id, payload)
        if destination is _HERE:
            spawn(coro, name=_PUSH_TASK)
        elif not spawn_threadsafe(coro, destination, name=_PUSH_TASK):
            # El loop se cerró entre la comprobación y la programación
            # (apagado).
            discard(coro, name=_PUSH_TASK)
            logger.warning(
                "broadcast_websocket: el loop principal ya no corre, "
                "push descartado (user_id=%s)", user_id,
            )

    @staticmethod
    def _defer_push(db: Session, user_id: int, notification: Notification) -> None:
        """Deja el push de `notification` pendiente en `db` hasta que commitee
        su transacción raíz (`_emit_pending_pushes`); nunca lanza.

        Por qué no empujar ya, al `flush`: desde un hilo el push corre en el
        loop principal EN PARALELO al hilo, que sigue trabajando y commitea
        después (o revierte). El cliente re-lee conteos y lista de la BD al
        recibir el aviso y vería datos viejos; y una transacción revertida
        dejaría un toast de algo que no existe.

        - Sin destino posible (CLI, Celery) no se arma nada: ni el payload, que
          puede consultar estilos de app, ni la espera.
        - Si `db` no es una `Session` de SQLAlchemy (dobles de pruebas) no hay
          forma de saber cuándo commitea: se empuja ya, como antes.
        - El payload (`to_dict`) se arma AQUÍ, en el hilo que posee la sesión y
          antes del commit, que expira los objetos; al hook solo llega el dict.
        """
        try:
            if not isinstance(db, Session):
                NotificationService.broadcast_websocket(user_id, notification)
                return
            if NotificationService._push_destination() is None:
                return
            transaction = db.get_nested_transaction() or db.get_transaction()
            _pending_for(db).items.append(
                (transaction, user_id, notification.to_dict())
            )
        except Exception as e:
            logger.error(
                f"Error deferring WebSocket push to user {user_id}: {e}",
                exc_info=True
            )
            # No re-lanzar: la notificación ya está en la sesión

    @staticmethod
    def broadcast_websocket(user_id: int, notification: Notification):
        """
        Difunde la notificación vía WebSocket (Socket.IO /notify namespace),
        ahora mismo. `create` no lo llama: difiere el push al commit.

        Nunca espera el resultado del push y nunca lanza: la notificación ya
        está en la sesión. Según dónde corra el llamador:

        - Con un loop corriendo en el hilo actual (endpoint `async`, handler
          de socket): `spawn` ahí.
        - Sin loop en este hilo (una ruta `def` en el threadpool) y con el loop
          principal de la app registrado y corriendo (`itcj2.utils.main_loop`):
          `spawn_threadsafe` EN ese loop, con el `request_id` del hilo.
        - Sin ninguno de los dos (CLI, Celery): no hace nada. En Celery el
          aviso en tiempo real sale por el Pub/Sub de Redis, no por aquí.

        Args:
            user_id: ID del usuario
            notification: Instancia de Notification
        """
        try:
            # Sin destino no hay nada que crear, ni que cerrar, ni que contar:
            # se decide ANTES de armar el payload.
            destination = NotificationService._push_destination()
            if destination is None:
                return

            # `to_dict()` se evalúa AQUÍ, en el hilo que posee la sesión: al
            # loop solo cruza el dict ya armado, nunca el objeto ORM.
            NotificationService._emit_push(
                destination, user_id, notification.to_dict()
            )

        except Exception as e:
            logger.error(
                f"Error broadcasting WebSocket to user {user_id}: {e}",
                exc_info=True
            )
            # No re-lanzar: la notificación ya está en DB

    @staticmethod
    def mark_read(db: Session, notification_id: int, user_id: int) -> bool:
        """
        Marca una notificación como leída.

        Returns:
            True si se marcó correctamente, False si no existe o no pertenece al usuario
        """
        notification = db.query(Notification).filter(
            and_(
                Notification.id == notification_id,
                Notification.user_id == user_id,
                Notification.is_read == False
            )
        ).first()

        if not notification:
            return False

        notification.is_read = True
        notification.read_at = datetime.now()
        db.commit()  # commit-in-service (antes dependía de que el endpoint commiteara)

        return True

    @staticmethod
    def mark_all_read(db: Session, user_id: int, app_name: Optional[str] = None) -> int:
        """
        Marca todas las notificaciones no leídas como leídas.

        Returns:
            Número de notificaciones marcadas como leídas
        """
        query = db.query(Notification).filter(
            and_(
                Notification.user_id == user_id,
                Notification.is_read == False
            )
        )

        if app_name:
            query = query.filter(Notification.app_name == app_name)

        count = query.update(
            {
                'is_read': True,
                'read_at': datetime.now()
            },
            synchronize_session=False
        )
        db.commit()  # commit-in-service

        return count

    @staticmethod
    def get_unread_count(db: Session, user_id: int, app_name: Optional[str] = None) -> int:
        """
        Obtiene el conteo de notificaciones no leídas.
        """
        query = db.query(func.count(Notification.id)).filter(
            and_(
                Notification.user_id == user_id,
                Notification.is_read == False
            )
        )

        if app_name:
            query = query.filter(Notification.app_name == app_name)

        return query.scalar() or 0

    @staticmethod
    def get_unread_counts_by_app(db: Session, user_id: int) -> Dict[str, int]:
        """
        Obtiene conteos de notificaciones no leídas agrupadas por aplicación.

        Returns:
            Dict con app_name como key y count como value
            Example: {'agendatec': 5, 'helpdesk': 2}
        """
        results = db.query(
            Notification.app_name,
            func.count(Notification.id).label('count')
        ).filter(
            and_(
                Notification.user_id == user_id,
                Notification.is_read == False
            )
        ).group_by(Notification.app_name).all()

        return {row.app_name: row.count for row in results}

    @staticmethod
    def get_notifications(
        db: Session,
        user_id: int,
        app_name: Optional[str] = None,
        unread_only: bool = False,
        limit: int = 20,
        offset: int = 0,
        before_id: Optional[int] = None
    ) -> Dict:
        """
        Obtiene notificaciones con paginación y filtros.

        Returns:
            Dict con 'items', 'total', 'unread', 'has_more'
        """
        limit = min(limit, 100)  # Límite máximo

        query = db.query(Notification).filter(
            Notification.user_id == user_id
        )

        if app_name:
            query = query.filter(Notification.app_name == app_name)

        if unread_only:
            query = query.filter(Notification.is_read == False)

        if before_id:
            query = query.filter(Notification.id < before_id)

        query = query.order_by(Notification.created_at.desc(), Notification.id.desc())

        # Obtener total y no leídas
        total_count = db.query(func.count(Notification.id)).filter(
            Notification.user_id == user_id
        )
        if app_name:
            total_count = total_count.filter(Notification.app_name == app_name)
        total_count = total_count.scalar() or 0

        unread_count = NotificationService.get_unread_count(db, user_id, app_name)

        items = query.offset(offset).limit(limit + 1).all()
        has_more = len(items) > limit
        items = items[:limit]

        # Estilos de apps UNA sola vez para toda la página (evita 1 GET Redis por
        # notificación en la serialización — antes N+1 en el hot path de lista).
        from itcj2.core.services.app_style_cache import cached_app_styles
        styles = cached_app_styles(db)

        return {
            'items': [n.to_dict(styles=styles) for n in items],
            'total': total_count,
            'unread': unread_count,
            'has_more': has_more
        }

    @staticmethod
    def delete_notification(db: Session, notification_id: int, user_id: int) -> bool:
        """
        Elimina una notificación.

        Returns:
            True si se eliminó, False si no existe o no pertenece al usuario
        """
        notification = db.query(Notification).filter(
            and_(
                Notification.id == notification_id,
                Notification.user_id == user_id
            )
        ).first()

        if not notification:
            return False

        db.delete(notification)
        db.commit()  # commit-in-service
        return True
