"""
Servicio centralizado de notificaciones para todas las aplicaciones del sistema ITCJ.

Este servicio maneja la creación, almacenamiento y difusión de notificaciones
a través de SSE (Server-Sent Events) y WebSockets.
"""
import json
from datetime import datetime
from typing import Optional, Dict, List
from flask import current_app
from sqlalchemy import func, and_
from itcj.core.extensions import db
from itcj.core.models.notification import Notification
from itcj.core.utils.redis_conn import get_redis


class NotificationService:
    """Servicio para manejo de notificaciones cross-app"""

    @staticmethod
    def create(
        user_id: int,
        app_name: str,
        type: str,
        title: str,
        body: Optional[str] = None,
        data: Optional[Dict] = None,
        **kwargs
    ) -> Notification:
        """
        Crea una nueva notificación y la difunde a través de SSE y WebSocket.

        Args:
            user_id: ID del usuario destinatario
            app_name: Nombre de la aplicación ('agendatec', 'helpdesk', etc.)
            type: Tipo de notificación ('TICKET_CREATED', 'APPOINTMENT_CANCELED', etc.)
            title: Título de la notificación
            body: Cuerpo/descripción opcional
            data: Datos adicionales en formato dict (se almacena como JSONB)
            **kwargs: Campos opcionales (ticket_id, source_request_id, etc.)

        Returns:
            La notificación creada

        Example:
            >>> NotificationService.create(
            ...     user_id=123,
            ...     app_name='helpdesk',
            ...     type='TICKET_ASSIGNED',
            ...     title='Ticket asignado',
            ...     body='Se te ha asignado el ticket #1234',
            ...     data={'ticket_id': 1234, 'url': '/help-desk/tickets/1234'},
            ...     ticket_id=1234
            ... )
        """
        try:
            # Crear notificación en la base de datos
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

            db.session.add(notification)
            db.session.flush()  # Obtener el ID sin hacer commit

            # Difundir a través de SSE (Redis pub/sub)
            NotificationService.broadcast_sse(user_id, notification)

            # Difundir a través de WebSocket (backwards compatibility)
            NotificationService.broadcast_websocket(user_id, notification)

            return notification

        except Exception as e:
            current_app.logger.error(
                f"Error creating notification for user {user_id}: {e}",
                exc_info=True
            )
            raise

    @staticmethod
    def broadcast_sse(user_id: int, notification: Notification):
        """
        Publica la notificación al canal Redis para SSE.

        Args:
            user_id: ID del usuario
            notification: Instancia de Notification
        """
        try:
            redis_client = get_redis()
            channel = f"notify:user:{user_id}"

            payload = notification.to_dict()
            message = json.dumps(payload)

            redis_client.publish(channel, message)

        except Exception as e:
            current_app.logger.error(
                f"Error broadcasting SSE to user {user_id}: {e}",
                exc_info=True
            )
            # No re-lanzar: la notificación ya está en DB

    @staticmethod
    def broadcast_websocket(user_id: int, notification: Notification):
        """
        Difunde la notificación vía WebSocket (backwards compatibility).

        Args:
            user_id: ID del usuario
            notification: Instancia de Notification
        """
        try:
            # Import here to avoid circular dependency
            from itcj.core.extensions import socketio
            from itcj.core.sockets.notifications import push_notification

            if socketio:
                push_notification(socketio, user_id, notification.to_dict())

        except Exception as e:
            current_app.logger.error(
                f"Error broadcasting WebSocket to user {user_id}: {e}",
                exc_info=True
            )
            # No re-lanzar: la notificación ya está en DB

    @staticmethod
    def mark_read(notification_id: int, user_id: int) -> bool:
        """
        Marca una notificación como leída.

        Args:
            notification_id: ID de la notificación
            user_id: ID del usuario (para verificar ownership)

        Returns:
            True si se marcó correctamente, False si no existe o no pertenece al usuario
        """
        notification = db.session.query(Notification).filter(
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

        return True

    @staticmethod
    def mark_all_read(user_id: int, app_name: Optional[str] = None) -> int:
        """
        Marca todas las notificaciones no leídas como leídas.

        Args:
            user_id: ID del usuario
            app_name: Opcional, filtrar por aplicación específica

        Returns:
            Número de notificaciones marcadas como leídas
        """
        query = db.session.query(Notification).filter(
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

        return count

    @staticmethod
    def get_unread_count(user_id: int, app_name: Optional[str] = None) -> int:
        """
        Obtiene el conteo de notificaciones no leídas.

        Args:
            user_id: ID del usuario
            app_name: Opcional, filtrar por aplicación específica

        Returns:
            Número de notificaciones no leídas
        """
        query = db.session.query(func.count(Notification.id)).filter(
            and_(
                Notification.user_id == user_id,
                Notification.is_read == False
            )
        )

        if app_name:
            query = query.filter(Notification.app_name == app_name)

        return query.scalar() or 0

    @staticmethod
    def get_unread_counts_by_app(user_id: int) -> Dict[str, int]:
        """
        Obtiene conteos de notificaciones no leídas agrupadas por aplicación.

        Args:
            user_id: ID del usuario

        Returns:
            Dict con app_name como key y count como value
            Example: {'agendatec': 5, 'helpdesk': 2}
        """
        results = db.session.query(
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
        user_id: int,
        app_name: Optional[str] = None,
        unread_only: bool = False,
        limit: int = 20,
        offset: int = 0,
        before_id: Optional[int] = None
    ) -> Dict:
        """
        Obtiene notificaciones con paginación y filtros.

        Args:
            user_id: ID del usuario
            app_name: Filtrar por aplicación
            unread_only: Solo notificaciones no leídas
            limit: Número máximo de resultados (máx 100)
            offset: Offset para paginación
            before_id: Cursor-based pagination (ID de notificación)

        Returns:
            Dict con 'items', 'total', 'unread', 'has_more'
        """
        limit = min(limit, 100)  # Límite máximo

        # Query base
        query = db.session.query(Notification).filter(
            Notification.user_id == user_id
        )

        # Filtros
        if app_name:
            query = query.filter(Notification.app_name == app_name)

        if unread_only:
            query = query.filter(Notification.is_read == False)

        if before_id:
            query = query.filter(Notification.id < before_id)

        # Ordenar por más reciente primero
        query = query.order_by(Notification.created_at.desc(), Notification.id.desc())

        # Obtener total y no leídas
        total_count = db.session.query(func.count(Notification.id)).filter(
            Notification.user_id == user_id
        )
        if app_name:
            total_count = total_count.filter(Notification.app_name == app_name)
        total_count = total_count.scalar() or 0

        unread_count = NotificationService.get_unread_count(user_id, app_name)

        # Paginación
        items = query.offset(offset).limit(limit + 1).all()
        has_more = len(items) > limit
        items = items[:limit]

        return {
            'items': [n.to_dict() for n in items],
            'total': total_count,
            'unread': unread_count,
            'has_more': has_more
        }

    @staticmethod
    def delete_notification(notification_id: int, user_id: int) -> bool:
        """
        Elimina una notificación (soft delete podría implementarse después).

        Args:
            notification_id: ID de la notificación
            user_id: ID del usuario (para verificar ownership)

        Returns:
            True si se eliminó, False si no existe o no pertenece al usuario
        """
        notification = db.session.query(Notification).filter(
            and_(
                Notification.id == notification_id,
                Notification.user_id == user_id
            )
        ).first()

        if not notification:
            return False

        db.session.delete(notification)
        return True
