"""
Helper de Notificaciones para VisteTec

Proporciona métodos para crear notificaciones en los diferentes eventos
del ciclo de vida de citas, donaciones y campañas.
"""
from flask import current_app
from itcj.core.extensions import db
from itcj.core.services.notification_service import NotificationService
from itcj.core.services.authz_service import _get_users_with_roles_in_app
from itcj.apps.vistetec.models.slot_volunteer import SlotVolunteer


class VisteTecNotificationHelper:
    """Helper para crear notificaciones de eventos de VisteTec"""

    # ==================== CITAS ====================

    @staticmethod
    def notify_appointment_scheduled(appointment):
        """
        Notifica a voluntarios del slot cuando un estudiante agenda una cita.

        Args:
            appointment: Instancia de Appointment recién creada (con relaciones cargadas)
        """
        try:
            # Obtener voluntarios inscritos en el slot
            slot_volunteers = SlotVolunteer.query.filter_by(
                slot_id=appointment.slot_id
            ).all()

            student_name = appointment.student.full_name if appointment.student else 'Estudiante'
            garment_name = appointment.garment.name if appointment.garment else 'Prenda'
            slot = appointment.slot
            slot_info = ''
            if slot:
                slot_date = slot.date.strftime('%d/%m/%Y') if slot.date else ''
                slot_time = slot.start_time.strftime('%H:%M') if slot.start_time else ''
                slot_info = f'{slot_date} a las {slot_time}'

            for sv in slot_volunteers:
                NotificationService.create(
                    user_id=sv.volunteer_id,
                    app_name='vistetec',
                    type='APPOINTMENT_SCHEDULED',
                    title=f'Nueva cita {appointment.code}',
                    body=f'{student_name} agendó cita para "{garment_name}" el {slot_info}',
                    data={
                        'appointment_id': appointment.id,
                        'url': '/vistetec/volunteer/appointments',
                    }
                )

            db.session.commit()

            current_app.logger.info(
                f"Notificación APPOINTMENT_SCHEDULED enviada a {len(slot_volunteers)} voluntarios para cita {appointment.code}"
            )

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(
                f"Error enviando notificación APPOINTMENT_SCHEDULED para cita {appointment.code}: {e}",
                exc_info=True
            )

    @staticmethod
    def notify_appointment_cancelled(appointment, cancelled_by_volunteer=False):
        """
        Notifica cuando se cancela una cita.
        - Si cancela el estudiante → notifica a voluntarios del slot
        - Si cancela un voluntario → notifica al estudiante

        Args:
            appointment: Instancia de Appointment
            cancelled_by_volunteer: True si fue cancelada por un voluntario
        """
        try:
            garment_name = appointment.garment.name if appointment.garment else 'Prenda'

            if cancelled_by_volunteer:
                # Notificar al estudiante
                NotificationService.create(
                    user_id=appointment.student_id,
                    app_name='vistetec',
                    type='APPOINTMENT_CANCELLED',
                    title=f'Cita {appointment.code} cancelada',
                    body=f'Tu cita para "{garment_name}" fue cancelada por un voluntario',
                    data={
                        'appointment_id': appointment.id,
                        'url': '/vistetec/student/my-appointments',
                    }
                )
            else:
                # Notificar a voluntarios del slot
                slot_volunteers = SlotVolunteer.query.filter_by(
                    slot_id=appointment.slot_id
                ).all()

                student_name = appointment.student.full_name if appointment.student else 'Estudiante'

                for sv in slot_volunteers:
                    NotificationService.create(
                        user_id=sv.volunteer_id,
                        app_name='vistetec',
                        type='APPOINTMENT_CANCELLED',
                        title=f'Cita {appointment.code} cancelada',
                        body=f'{student_name} canceló su cita para "{garment_name}"',
                        data={
                            'appointment_id': appointment.id,
                            'url': '/vistetec/volunteer/appointments',
                        }
                    )

            db.session.commit()

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(
                f"Error enviando notificación APPOINTMENT_CANCELLED para cita {appointment.code}: {e}",
                exc_info=True
            )

    @staticmethod
    def notify_attendance_marked(appointment, attended):
        """
        Notifica al estudiante cuando se marca su asistencia.

        Args:
            appointment: Instancia de Appointment
            attended: True si asistió, False si no
        """
        try:
            garment_name = appointment.garment.name if appointment.garment else 'Prenda'
            status_text = 'registrada' if attended else 'marcada como inasistencia'

            NotificationService.create(
                user_id=appointment.student_id,
                app_name='vistetec',
                type='APPOINTMENT_ATTENDANCE',
                title=f'Asistencia {status_text}',
                body=f'Tu cita {appointment.code} para "{garment_name}" fue {status_text}',
                data={
                    'appointment_id': appointment.id,
                    'url': '/vistetec/student/my-appointments',
                }
            )

            db.session.commit()

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(
                f"Error enviando notificación APPOINTMENT_ATTENDANCE para cita {appointment.code}: {e}",
                exc_info=True
            )

    @staticmethod
    def notify_appointment_completed(appointment):
        """
        Notifica al estudiante cuando se completa su cita con el resultado.

        Args:
            appointment: Instancia de Appointment con outcome (taken/not_fit/declined)
        """
        try:
            garment_name = appointment.garment.name if appointment.garment else 'Prenda'
            outcome_text = {
                'taken': 'Prenda entregada',
                'not_fit': 'La prenda no fue de tu talla',
                'declined': 'Decidiste no llevar la prenda',
            }.get(appointment.outcome, 'Completada')

            NotificationService.create(
                user_id=appointment.student_id,
                app_name='vistetec',
                type='APPOINTMENT_COMPLETED',
                title=f'Cita {appointment.code} completada',
                body=f'{outcome_text}: "{garment_name}"',
                data={
                    'appointment_id': appointment.id,
                    'outcome': appointment.outcome,
                    'url': '/vistetec/student/my-appointments',
                }
            )

            db.session.commit()

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(
                f"Error enviando notificación APPOINTMENT_COMPLETED para cita {appointment.code}: {e}",
                exc_info=True
            )

    # ==================== DONACIONES ====================

    @staticmethod
    def notify_garment_donation(donation):
        """
        Notifica cuando se registra una donación de prenda.
        - Si tiene donor_id → notifica al donador
        - Notifica a admins de vistetec

        Args:
            donation: Instancia de Donation con donation_type='garment'
        """
        try:
            garment_name = donation.garment.name if donation.garment else 'Prenda'
            donor_display = donation.donor.full_name if donation.donor else (donation.donor_name or 'Anónimo')

            # Notificar al donador si es usuario registrado
            if donation.donor_id:
                NotificationService.create(
                    user_id=donation.donor_id,
                    app_name='vistetec',
                    type='GARMENT_DONATION_REGISTERED',
                    title=f'Donación registrada: {donation.code}',
                    body=f'Tu donación de "{garment_name}" fue registrada exitosamente',
                    data={
                        'donation_id': donation.id,
                        'url': '/vistetec/student/my-donations',
                    }
                )

            # Notificar a admins de vistetec
            admins = _get_users_with_roles_in_app('vistetec', ['admin']) or []
            for admin in admins:
                admin_id = getattr(admin, 'id', None)
                if admin_id and admin_id != donation.registered_by_id and admin_id != donation.donor_id:
                    NotificationService.create(
                        user_id=admin_id,
                        app_name='vistetec',
                        type='GARMENT_DONATION_REGISTERED',
                        title=f'Nueva donación de prenda: {donation.code}',
                        body=f'{donor_display} donó "{garment_name}"',
                        data={
                            'donation_id': donation.id,
                            'url': '/vistetec/admin/dashboard',
                        }
                    )

            db.session.commit()

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(
                f"Error enviando notificación GARMENT_DONATION para donación {donation.code}: {e}",
                exc_info=True
            )

    @staticmethod
    def notify_pantry_donation(donation):
        """
        Notifica cuando se registra una donación de despensa.

        Args:
            donation: Instancia de Donation con donation_type='pantry'
        """
        try:
            item_name = donation.pantry_item.name if donation.pantry_item else 'Producto'
            quantity = donation.quantity or 1
            donor_display = donation.donor.full_name if donation.donor else (donation.donor_name or 'Anónimo')
            campaign_text = ''
            if donation.campaign:
                campaign_text = f' para la campaña "{donation.campaign.name}"'

            # Notificar al donador si es usuario registrado
            if donation.donor_id:
                NotificationService.create(
                    user_id=donation.donor_id,
                    app_name='vistetec',
                    type='PANTRY_DONATION_REGISTERED',
                    title=f'Donación registrada: {donation.code}',
                    body=f'Tu donación de {quantity} {item_name}{campaign_text} fue registrada',
                    data={
                        'donation_id': donation.id,
                        'url': '/vistetec/student/my-donations',
                    }
                )

            # Notificar a admins de vistetec
            admins = _get_users_with_roles_in_app('vistetec', ['admin']) or []
            for admin in admins:
                admin_id = getattr(admin, 'id', None)
                if admin_id and admin_id != donation.registered_by_id and admin_id != donation.donor_id:
                    NotificationService.create(
                        user_id=admin_id,
                        app_name='vistetec',
                        type='PANTRY_DONATION_REGISTERED',
                        title=f'Nueva donación de despensa: {donation.code}',
                        body=f'{donor_display} donó {quantity} {item_name}{campaign_text}',
                        data={
                            'donation_id': donation.id,
                            'url': '/vistetec/admin/dashboard',
                        }
                    )

            db.session.commit()

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(
                f"Error enviando notificación PANTRY_DONATION para donación {donation.code}: {e}",
                exc_info=True
            )

    # ==================== CAMPAÑAS ====================

    @staticmethod
    def notify_campaign_launched(campaign):
        """
        Notifica a voluntarios y admins cuando se lanza una nueva campaña.

        Args:
            campaign: Instancia de PantryCampaign recién creada
        """
        try:
            item_name = campaign.requested_item.name if campaign.requested_item else 'Producto'
            goal_text = f'Meta: {campaign.goal_quantity} {item_name}' if campaign.goal_quantity else item_name

            # Obtener voluntarios y admins de vistetec
            recipients = set()
            for role in ['admin', 'volunteer']:
                users = _get_users_with_roles_in_app('vistetec', [role]) or []
                for u in users:
                    uid = getattr(u, 'id', None)
                    if uid:
                        recipients.add(uid)

            for user_id in recipients:
                NotificationService.create(
                    user_id=user_id,
                    app_name='vistetec',
                    type='CAMPAIGN_LAUNCHED',
                    title=f'Nueva campaña: {campaign.name}',
                    body=f'{campaign.description[:100] if campaign.description else goal_text}',
                    data={
                        'campaign_id': campaign.id,
                        'url': '/vistetec/admin/campaigns',
                    }
                )

            db.session.commit()

            current_app.logger.info(
                f"Notificación CAMPAIGN_LAUNCHED enviada a {len(recipients)} usuarios para campaña '{campaign.name}'"
            )

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(
                f"Error enviando notificación CAMPAIGN_LAUNCHED para campaña '{campaign.name}': {e}",
                exc_info=True
            )

    @staticmethod
    def notify_campaign_ended(campaign):
        """
        Notifica a voluntarios y admins cuando finaliza una campaña.

        Args:
            campaign: Instancia de PantryCampaign desactivada
        """
        try:
            collected = campaign.collected_quantity or 0
            goal = campaign.goal_quantity or 0
            progress_text = f'Se recolectaron {collected}/{goal} unidades' if goal else f'Se recolectaron {collected} unidades'

            # Obtener voluntarios y admins de vistetec
            recipients = set()
            for role in ['admin', 'volunteer']:
                users = _get_users_with_roles_in_app('vistetec', [role]) or []
                for u in users:
                    uid = getattr(u, 'id', None)
                    if uid:
                        recipients.add(uid)

            for user_id in recipients:
                NotificationService.create(
                    user_id=user_id,
                    app_name='vistetec',
                    type='CAMPAIGN_ENDED',
                    title=f'Campaña finalizada: {campaign.name}',
                    body=progress_text,
                    data={
                        'campaign_id': campaign.id,
                        'url': '/vistetec/admin/campaigns',
                    }
                )

            db.session.commit()

            current_app.logger.info(
                f"Notificación CAMPAIGN_ENDED enviada a {len(recipients)} usuarios para campaña '{campaign.name}'"
            )

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(
                f"Error enviando notificación CAMPAIGN_ENDED para campaña '{campaign.name}': {e}",
                exc_info=True
            )
