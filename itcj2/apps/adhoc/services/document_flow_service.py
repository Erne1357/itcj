"""Flujos de aprobación de documentos: pasos, validadores y arranque del flujo.

Es la pieza más delicada de la migración. Todo lo de aquí sale de
``api_docs.py`` (`save_flow_steps`, `assign_step_users`, `notify_step_users`,
`iniciar_flujo_doc`), reescrito según el plan §7 y §10.b. Los cinco arreglos
que justifican el módulo:

1. **Upsert por ``step_order``, no delete-all** (:meth:`upsert_flow_steps`).
   El legacy borraba *todos* los ``FlowStep`` del flujo y los recreaba con ids
   nuevos. Como ``adhoc_tasks.flow_step_id`` y
   ``adhoc_documents.current_step_id`` son FK **sin ``ondelete``** (RESTRICT),
   editar un flujo con documentos en curso corrompía el workflow. Ahora el
   ``step_order`` es la clave: el mismo paso conserva su id, y la operación se
   rechaza con 409 si hay documentos activos o si el paso que tocaría borrar
   está referenciado.

2. **``delete_flow`` con el mismo guard.** Los pasos sí caen en cascada, pero
   los documentos y las tareas que los apuntan no: sin el guard, el DELETE
   revienta con ``IntegrityError`` → 500.

3. **``set_step_validators`` preserva ``notify_on_overdue``.** El legacy hacía
   ``step.assigned_users = []`` y volvía a añadir: la tabla de asociación se
   reescribía entera y el flag de "avísame si se atrasa" desaparecía de todos
   sin decir nada. Aquí se hace un diff sobre la tabla de asociación y solo se
   tocan las filas que entran o salen.

4. **``start_flow`` valida que el flujo exista.** El legacy asignaba
   ``doc.flow_id = flow_id`` con el valor crudo del JSON y solo se enteraba de
   que no existía porque la consulta de pasos salía vacía (mensaje engañoso:
   "el flujo no tiene pasos configurados").

5. **`start_flow` mira las tareas DE FLUJO, no el `status`.** El guard de "ya
   iniciado" preguntaba `status == 'En Revisión' and flow_id`, y el documento 202
   llegó de la migración en `'Borrador'` con `flow_id` y dos tareas vivas: no
   disparaba, y volver a sellar duplicaba el juego completo de tareas. Ahora lo
   decide :meth:`AdhocDocumentFlowService._assert_sin_flujo_vivo`, que busca
   tareas de ESTE documento con `flow_step_id IS NOT NULL` —la marca que solo
   pone `start_flow`— en `'En Revisión'` o `'En Espera'`, y el conflicto es un
   409, no un 400. El seguimiento manual del documento no cuenta: es trabajo,
   no flujo.

Contrato de errores idéntico al de ``document_service``: ``LookupError`` → 404,
:class:`AdhocConflict` → 409, ``ValueError`` → 400. Ningún método lanza
``HTTPException``.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional, Sequence

from sqlalchemy.orm import Session, selectinload

from itcj2.apps.adhoc.models import (
    AdhocApprovalFlow,
    AdhocApprovalFlowStep,
    AdhocDocument,
    AdhocTask,
    adhoc_flow_step_assignees as STEP_USERS,
)
from itcj2.apps.adhoc.schemas.documents import FlowCreate, FlowStepIn, FlowUpdate
from itcj2.apps.adhoc.services import notify
from itcj2.apps.adhoc.services.document_service import AdhocConflict
from itcj2.apps.adhoc.utils.constants import (
    DOCUMENT_STATUS_APPROVED,
    DOCUMENT_STATUS_IN_REVIEW,
    DOCUMENT_STATUSES_STARTABLE,
    PRIORITY_HIGH,
    TASK_STATUS_IN_REVIEW,
    TASK_STATUS_WAITING,
)
from itcj2.core.models.user import User

logger = logging.getLogger(__name__)

__all__ = ["AdhocDocumentFlowService"]

#: ``adhoc_tasks.description`` es ``String(255)``; el título del documento puede
#: llegar a 200 y el prefijo se lo come. Se trunca en vez de reventar el INSERT.
_DESCRIPTION_MAX = 255


def _clip(text: str) -> str:
    return text if len(text) <= _DESCRIPTION_MAX else text[: _DESCRIPTION_MAX - 1] + "…"


class AdhocDocumentFlowService:
    """Flujos, pasos, validadores y máquina de arranque del workflow."""

    # ==================================================================
    # Flujos
    # ==================================================================
    @staticmethod
    def list_flows(db: Session) -> list[AdhocApprovalFlow]:
        """Todos los flujos con sus pasos precargados (sin N+1 al contarlos)."""
        return (
            db.query(AdhocApprovalFlow)
            .options(selectinload(AdhocApprovalFlow.steps))
            .order_by(AdhocApprovalFlow.name.asc())
            .all()
        )

    @staticmethod
    def get_flow(db: Session, flow_id: int) -> AdhocApprovalFlow:
        flow = (
            db.query(AdhocApprovalFlow)
            .options(selectinload(AdhocApprovalFlow.steps))
            .filter(AdhocApprovalFlow.id == flow_id)
            .first()
        )
        if flow is None:
            raise LookupError("Flujo de aprobación no encontrado")
        return flow

    @staticmethod
    def create_flow(db: Session, data: FlowCreate) -> AdhocApprovalFlow:
        flow = AdhocApprovalFlow(name=data.name, description=data.description)
        db.add(flow)
        db.commit()
        db.refresh(flow)
        return flow

    @staticmethod
    def update_flow(db: Session, flow_id: int, data: FlowUpdate) -> AdhocApprovalFlow:
        flow = db.get(AdhocApprovalFlow, flow_id)
        if flow is None:
            raise LookupError("Flujo de aprobación no encontrado")

        changes = data.model_dump(exclude_unset=True)
        if "name" in changes:
            if not (changes["name"] or "").strip():
                raise ValueError("El nombre del flujo no puede quedar vacío")
            changes["name"] = changes["name"].strip()

        for field, value in changes.items():
            setattr(flow, field, value)
        db.commit()
        db.refresh(flow)
        return flow

    @staticmethod
    def delete_flow(db: Session, flow_id: int) -> None:
        """Borra el flujo y sus pasos. 409 si algún documento o tarea los usa.

        ``adhoc_approval_flow_steps.flow_id`` es ``ondelete CASCADE``, pero
        ``adhoc_documents.flow_id``, ``adhoc_documents.current_step_id`` y
        ``adhoc_tasks.flow_step_id`` son RESTRICT: sin este guard el DELETE
        sería un ``IntegrityError`` → 500.
        """
        flow = AdhocDocumentFlowService.get_flow(db, flow_id)
        step_ids = [s.id for s in flow.steps]

        en_uso = (
            db.query(AdhocDocument.id)
            .filter(AdhocDocument.flow_id == flow.id)
            .count()
        )
        if en_uso:
            raise AdhocConflict(
                f"No se puede eliminar el flujo: {en_uso} documento(s) lo están usando"
            )
        AdhocDocumentFlowService._assert_steps_unreferenced(db, step_ids)

        for step_id in step_ids:
            db.execute(STEP_USERS.delete().where(STEP_USERS.c.step_id == step_id))
        db.delete(flow)
        db.commit()

    # ==================================================================
    # Pasos
    # ==================================================================
    @staticmethod
    def list_steps(db: Session, flow_id: int) -> list[AdhocApprovalFlowStep]:
        AdhocDocumentFlowService.get_flow(db, flow_id)   # 404 si el flujo no existe
        return (
            db.query(AdhocApprovalFlowStep)
            .filter(AdhocApprovalFlowStep.flow_id == flow_id)
            .order_by(AdhocApprovalFlowStep.step_order.asc())
            .all()
        )

    @staticmethod
    def upsert_flow_steps(
        db: Session,
        flow_id: int,
        steps: Sequence[FlowStepIn],
    ) -> list[AdhocApprovalFlowStep]:
        """Sincroniza los pasos del flujo **por ``step_order``**.

        * ``step_order`` ya existente → se actualiza ``name``/``days_limit``
          conservando el **id** (y con él las tareas y el ``current_step_id``
          que lo apuntan).
        * ``step_order`` nuevo → se inserta.
        * ``step_order`` ausente del payload → se borra, pero solo si nadie lo
          referencia.

        Raises:
            LookupError: el flujo no existe.
            ValueError: lista vacía o ``step_order`` duplicado/inválido.
            AdhocConflict: hay documentos en revisión en este flujo, o el paso
                a borrar tiene tareas/documentos apuntándolo.
        """
        flow = AdhocDocumentFlowService.get_flow(db, flow_id)

        if not steps:
            raise ValueError("Debe enviar al menos un paso para el flujo")

        orders: list[int] = []
        for index, payload in enumerate(steps, start=1):
            order = payload.step_order or index
            if order < 1:
                raise ValueError(f"step_order inválido: {order}")
            orders.append(order)
        if len(set(orders)) != len(orders):
            raise ValueError("Hay pasos con el mismo step_order")

        activos = (
            db.query(AdhocDocument.id)
            .filter(
                AdhocDocument.flow_id == flow.id,
                AdhocDocument.status == DOCUMENT_STATUS_IN_REVIEW,
            )
            .count()
        )
        if activos:
            raise AdhocConflict(
                f"No se pueden modificar los pasos: {activos} documento(s) están "
                "en revisión con este flujo. Espera a que terminen o crea un flujo nuevo."
            )

        existing = {
            s.step_order: s
            for s in db.query(AdhocApprovalFlowStep)
            .filter(AdhocApprovalFlowStep.flow_id == flow.id)
            .all()
        }
        incoming = dict(zip(orders, steps))

        to_delete = [s for order, s in existing.items() if order not in incoming]
        AdhocDocumentFlowService._assert_steps_unreferenced(db, [s.id for s in to_delete])

        for order, payload in incoming.items():
            step = existing.get(order)
            if step is not None:
                step.name = payload.name
                step.days_limit = payload.days_limit
            else:
                db.add(AdhocApprovalFlowStep(
                    flow_id=flow.id,
                    name=payload.name,
                    days_limit=payload.days_limit,
                    step_order=order,
                ))

        for step in to_delete:
            db.execute(STEP_USERS.delete().where(STEP_USERS.c.step_id == step.id))
            db.delete(step)

        db.commit()
        return AdhocDocumentFlowService.list_steps(db, flow.id)

    @staticmethod
    def get_step(db: Session, step_id: int) -> AdhocApprovalFlowStep:
        step = db.get(AdhocApprovalFlowStep, step_id)
        if step is None:
            raise LookupError("Paso de flujo no encontrado")
        return step

    @staticmethod
    def get_step_details(db: Session, step_id: int) -> tuple[AdhocApprovalFlowStep, list[User], set[int]]:
        """``(paso, validadores, ids_que_reciben_alerta_de_atraso)``.

        Se lee la tabla de asociación directamente en vez de la relación ORM:
        el flag ``notify_on_overdue`` vive en la asociación y la relación no lo
        expone.
        """
        step = AdhocDocumentFlowService.get_step(db, step_id)
        rows = db.execute(
            STEP_USERS.select().where(STEP_USERS.c.step_id == step.id)
        ).fetchall()

        notify_ids = {r.user_id for r in rows if r.notify_on_overdue}
        user_ids = [r.user_id for r in rows]
        users = (
            db.query(User)
            .filter(User.id.in_(user_ids))
            .order_by(User.last_name.asc(), User.first_name.asc())
            .all()
            if user_ids else []
        )
        return step, users, notify_ids

    @staticmethod
    def set_step_validators(
        db: Session,
        step_id: int,
        user_ids: Sequence[int],
    ) -> AdhocApprovalFlowStep:
        """Reemplaza los validadores del paso **preservando ``notify_on_overdue``**.

        Diff sobre la tabla de asociación: solo se borran los que salen y solo
        se insertan los que entran. Los que siguen conservan su fila —y con
        ella su flag—, que es justamente lo que el legacy destruía.
        """
        step = AdhocDocumentFlowService.get_step(db, step_id)
        wanted = AdhocDocumentFlowService._validated_user_ids(db, user_ids)

        current = {
            r.user_id
            for r in db.execute(
                STEP_USERS.select().where(STEP_USERS.c.step_id == step.id)
            ).fetchall()
        }

        to_remove = current - wanted
        if to_remove:
            db.execute(
                STEP_USERS.delete().where(
                    STEP_USERS.c.step_id == step.id,
                    STEP_USERS.c.user_id.in_(to_remove),
                )
            )
        to_add = wanted - current
        if to_add:
            db.execute(STEP_USERS.insert(), [
                {"step_id": step.id, "user_id": uid, "notify_on_overdue": False}
                for uid in sorted(to_add)
            ])

        db.commit()
        db.expire(step)
        return step

    @staticmethod
    def set_step_overdue_notifications(
        db: Session,
        step_id: int,
        user_ids: Sequence[int],
    ) -> AdhocApprovalFlowStep:
        """Marca quién recibe la alerta de atraso de este paso.

        Conserva el efecto del legacy: marcar a alguien que aún no era
        validador **lo asigna** al paso. Los que no vienen en la lista quedan
        con el flag en ``false`` (siguen asignados).
        """
        step = AdhocDocumentFlowService.get_step(db, step_id)
        wanted = AdhocDocumentFlowService._validated_user_ids(db, user_ids)

        db.execute(
            STEP_USERS.update()
            .where(STEP_USERS.c.step_id == step.id)
            .values(notify_on_overdue=False)
        )

        current = {
            r.user_id
            for r in db.execute(
                STEP_USERS.select().where(STEP_USERS.c.step_id == step.id)
            ).fetchall()
        }

        to_add = wanted - current
        if to_add:
            db.execute(STEP_USERS.insert(), [
                {"step_id": step.id, "user_id": uid, "notify_on_overdue": True}
                for uid in sorted(to_add)
            ])
        to_flag = wanted & current
        if to_flag:
            db.execute(
                STEP_USERS.update()
                .where(
                    STEP_USERS.c.step_id == step.id,
                    STEP_USERS.c.user_id.in_(to_flag),
                )
                .values(notify_on_overdue=True)
            )

        db.commit()
        db.expire(step)
        return step

    # ==================================================================
    # Arranque y avance del flujo (plan §10.b)
    # ==================================================================
    @staticmethod
    def _assert_sin_flujo_vivo(db: Session, doc: AdhocDocument) -> None:
        """409 si el documento ya tiene un flujo de aprobación a medias.

        Lo que impide sellar un documento no es lo que diga ``status`` —el guard
        anterior preguntaba ``status == 'En Revisión' and flow_id``, y por eso
        no protegía nada:

        * hacia arriba era redundante, porque ``'En Revisión'`` ya no está en
          ``DOCUMENT_STATUSES_STARTABLE`` y el gate de justo debajo lo rechaza
          igual (con 409 en vez de 400);
        * hacia abajo no cubría el caso real: el documento 202 llegó de la
          migración del SGC en ``status='Borrador'`` con ``flow_id=5``,
          ``current_step_id=NULL`` y **dos tareas de flujo vivas**. La condición
          no disparaba, el panel pintaba el botón del sello (``'Borrador'`` sí es
          startable) y volver a pulsarlo duplicaba el juego completo de tareas,
          con dos *"Aprobar Documento: …"* por paso en el tablero de cada
          validador.

        Son las **tareas de flujo** vivas. Y solo esas: el predicado exige
        ``flow_step_id IS NOT NULL``, que es la marca que ``start_flow`` —y nadie
        más— pone al crearlas.

        Por qué no se reutiliza :meth:`AdhocDocumentService._assert_sin_flujo_vivo`,
        que responde a una pregunta parecida: esa mira **cualquier** tarea de la
        cadena de versiones, y hace bien, porque lo que va a marcar ``'Obsoleto'``
        es la cadena entera. Aquí ese alcance es dañino en las dos direcciones:

        * cuenta el seguimiento manual. Un documento puede tener tareas propias
          que no son de flujo —la pantalla ``/adhoc/documentos/{id}/tareas`` deja
          crearlas y su ``<select>`` ofrece ``'En Revisión'`` y ``'En Espera'``
          entre los seis estados—, y con ellas el sellado contestaba un 409 que
          nombraba un flujo inexistente y pedía terminar o rechazar una tarea de
          trabajo legítima. Comprobado sobre el documento 2 (``'Borrador'``,
          ``flow_id`` nulo, cero tareas): una sola tarea manual en cualquiera de
          esos dos estados lo dejaba imposible de sellar;
        * y el alcance de cadena no aporta nada: una versión solo se anexa si la
          cadena no tiene flujo vivo (``_supersede_chain``), y medido sobre la
          base real hay 0 documentos startables cuya cadena tenga tareas de flujo
          vivas en otra versión.
        """
        viva = (
            db.query(AdhocTask.id)
            .filter(
                AdhocTask.document_id == doc.id,
                AdhocTask.flow_step_id.isnot(None),
                AdhocTask.status.in_((TASK_STATUS_IN_REVIEW, TASK_STATUS_WAITING)),
            )
            .first()
        )
        if viva is not None:
            raise AdhocConflict(
                "El documento ya tiene un flujo de aprobación en curso. Termine o "
                "rechace las tareas del flujo pendientes antes de iniciar otro."
            )

    @staticmethod
    def start_flow(
        db: Session,
        document_id: int,
        flow_id: Optional[int],
        actor_id: Optional[int] = None,
    ) -> dict:
        """Arranca el flujo de aprobación de un documento.

        Los 9 pasos del plan §10.b. Crea **una tarea por paso** con un
        *snapshot* deliberado de los validadores del paso (reasignar el paso
        después no altera las tareas ya creadas: comportamiento del legacy que
        se conserva), pone la primera en ``En Revisión`` y el resto en
        ``En Espera``, y notifica a los validadores del primer paso.

        Returns:
            ``{"document", "flow", "first_step", "tasks", "email_sent", "message"}``.

        Raises:
            ValueError: sin ``flow_id``, o flujo sin pasos.
            LookupError: documento o flujo inexistentes.
            AdhocConflict: el documento ya tiene un flujo vivo —tareas **de
                flujo** en ``'En Revisión'`` o ``'En Espera'``, se comprueba con
                :meth:`_assert_sin_flujo_vivo`—, o su estado no admite arrancar
                uno (``DOCUMENT_STATUSES_STARTABLE``): una versión superada está
                en ``'Obsoleto'``, que es terminal.
        """
        if not flow_id:
            raise ValueError("Debe enviar flow_id.")

        doc = db.get(AdhocDocument, document_id)
        if doc is None:
            raise LookupError("Documento no encontrado")

        AdhocDocumentFlowService._assert_sin_flujo_vivo(db, doc)

        # `DOCUMENT_STATUSES_STARTABLE` existía desde la migración y hasta ahora
        # solo lo respetaba el navegador (`documents-panel.js` esconde el botón
        # del sello salvo en 'Borrador' y 'Rechazado'). El servidor no lo miraba,
        # así que un POST a mano —o el mismo botón sobre una fila desactualizada—
        # arrancaba un flujo sobre un documento OBSOLETO: la versión superada
        # volvía a 'En Revisión' con tareas nuevas para sus validadores, invisible
        # en las dos listas porque `is_current` seguía en false. 'Obsoleto' es
        # terminal por definición: de ahí no se sale arrancando otro flujo, se
        # sale anexando una versión nueva.
        if doc.status not in DOCUMENT_STATUSES_STARTABLE:
            raise AdhocConflict(
                f"No se puede iniciar un flujo de aprobación sobre un documento en "
                f"estado '{doc.status}'. Solo se puede desde: "
                f"{', '.join(DOCUMENT_STATUSES_STARTABLE)}."
            )

        flow = db.get(AdhocApprovalFlow, int(flow_id))
        if flow is None:
            raise LookupError("Flujo de aprobación no encontrado")

        steps = (
            db.query(AdhocApprovalFlowStep)
            .filter(AdhocApprovalFlowStep.flow_id == flow.id)
            .order_by(AdhocApprovalFlowStep.step_order.asc())
            .all()
        )
        if not steps:
            raise ValueError("El flujo seleccionado no tiene pasos configurados.")

        doc.flow_id = flow.id
        doc.current_step_id = steps[0].id
        doc.status = DOCUMENT_STATUS_IN_REVIEW

        tasks: list[AdhocTask] = []
        for index, step in enumerate(steps):
            task = AdhocTask(
                description=_clip(f"Aprobar Documento: {doc.title} (Paso: {step.name})"),
                status=TASK_STATUS_IN_REVIEW if index == 0 else TASK_STATUS_WAITING,
                priority=PRIORITY_HIGH,
                document_id=doc.id,
                flow_step_id=step.id,
                created_by_id=doc.author_id,
            )
            for user in AdhocDocumentFlowService._step_users(db, step.id):
                task.assignees.append(user)
            db.add(task)
            tasks.append(task)

        db.commit()

        first_step = steps[0]
        recipients = AdhocDocumentFlowService._step_users(db, first_step.id)

        # Notificación in-app: best-effort, y el commit es nuestro
        # (NotificationService.create hace flush, no commit).
        try:
            notify.notify_flow_started(db, doc, first_step, recipients)
            db.commit()
        except Exception:
            db.rollback()
            logger.exception(
                "[adhoc] No se pudo notificar el arranque del flujo del documento %s", doc.id
            )

        email_sent = False
        try:
            from itcj2.apps.adhoc.services.email_helper import AdhocEmailHelper

            email_sent = AdhocEmailHelper.send_flow_started(db, doc, first_step, recipients)
        except Exception:      # pragma: no cover - el helper ya es fail-soft
            logger.exception(
                "[adhoc] Error enviando correo de arranque de flujo del documento %s", doc.id
            )

        message = "Flujo iniciado correctamente."
        message += (
            " Se enviaron notificaciones por correo al primer paso."
            if email_sent else
            " El correo no se envió o está desactivado, pero el flujo quedó iniciado."
        )

        db.refresh(doc)
        return {
            "document": doc,
            "flow": flow,
            "first_step": first_step,
            "tasks": tasks,
            "email_sent": email_sent,
            "message": message,
        }

    @staticmethod
    def advance_to_next_step(
        db: Session,
        document: AdhocDocument,
    ) -> Optional[AdhocApprovalFlowStep]:
        """Mueve el documento al paso siguiente, o lo aprueba si ya no hay.

        **No commitea**: la llama ``task_workflow_service`` dentro de su propia
        transacción, junto con el cambio de estatus de la tarea.

        Returns:
            El paso siguiente, o ``None`` si el documento quedó ``Aprobado``.

        Raises:
            AdhocConflict: el documento no tiene paso actual (el legacy
                reventaba aquí con ``AttributeError`` → 500).
        """
        if not document.current_step_id:
            raise AdhocConflict("El documento no tiene un paso de flujo activo")

        current = db.get(AdhocApprovalFlowStep, document.current_step_id)
        if current is None:
            raise AdhocConflict("El paso actual del documento ya no existe")

        nxt = (
            db.query(AdhocApprovalFlowStep)
            .filter(
                AdhocApprovalFlowStep.flow_id == current.flow_id,
                AdhocApprovalFlowStep.step_order > current.step_order,
            )
            .order_by(AdhocApprovalFlowStep.step_order.asc())
            .first()
        )

        if nxt is not None:
            document.current_step_id = nxt.id
            return nxt

        document.status = DOCUMENT_STATUS_APPROVED
        document.approval_date = datetime.now()
        return None

    # ==================================================================
    # Internos
    # ==================================================================
    @staticmethod
    def _step_users(db: Session, step_id: int) -> list[User]:
        rows = db.execute(
            STEP_USERS.select().where(STEP_USERS.c.step_id == step_id)
        ).fetchall()
        ids = [r.user_id for r in rows]
        if not ids:
            return []
        return db.query(User).filter(User.id.in_(ids)).all()

    @staticmethod
    def _validated_user_ids(db: Session, user_ids: Sequence[Any]) -> set[int]:
        """Ids únicos, enteros y **existentes** en ``core_users``.

        El legacy hacía ``User.query.get(uid)`` y saltaba en silencio los que no
        existían: el usuario creía haber asignado 5 validadores y quedaban 2.
        """
        try:
            wanted = {int(uid) for uid in (user_ids or [])}
        except (TypeError, ValueError) as exc:
            raise ValueError("user_ids inválidos") from exc

        if not wanted:
            return set()

        found = {row[0] for row in db.query(User.id).filter(User.id.in_(wanted)).all()}
        missing = sorted(wanted - found)
        if missing:
            raise ValueError(
                f"No existen los usuarios: {', '.join(str(m) for m in missing)}"
            )
        return wanted

    @staticmethod
    def _assert_steps_unreferenced(db: Session, step_ids: Sequence[int]) -> None:
        """409 si algún documento o tarea apunta a los pasos que se van a borrar."""
        if not step_ids:
            return

        docs = (
            db.query(AdhocDocument.id)
            .filter(AdhocDocument.current_step_id.in_(step_ids))
            .count()
        )
        if docs:
            raise AdhocConflict(
                f"No se pueden eliminar los pasos: {docs} documento(s) están "
                "posicionados en ellos"
            )

        tareas = (
            db.query(AdhocTask.id)
            .filter(AdhocTask.flow_step_id.in_(step_ids))
            .count()
        )
        if tareas:
            raise AdhocConflict(
                f"No se pueden eliminar los pasos: {tareas} tarea(s) los referencian"
            )
