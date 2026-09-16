"""Espacios de cotejo: el horario propio de cada encargado dentro de un día.

Lo que aquí se valida son las dos formas de perder citas en silencio:

* **encoger un espacio** que ya tiene gente dentro (bajar la capacidad, recortar
  el horario o cambiar la duración de las franjas);
* **borrarlo**. Lo impide ``ON DELETE RESTRICT`` a nivel de base; este service
  solo traduce el error a una frase que se pueda leer en ventanilla.

Y una que la UNIQUE no cubre: dos espacios del mismo dueño el mismo día que se
**encimen** (09:00-12:00 junto a 10:00-14:00). La UNIQUE es
``(día, dueño, hora de inicio)``, así que 09:00 y 10:00 son distintas y pasa.
La alternativa de base (``EXCLUDE USING gist``) exige `btree_gist`, que no está
instalado, así que se valida aquí bajo el mismo lock.

Igual que `SlotService`, **no commitea**: el dueño de la transacción es la ruta.
"""
from __future__ import annotations

from datetime import time

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from itcj2.apps.titulatec.services.appointment_errors import (
    DuplicateWindowStart, InvalidSlot, WindowInUse, WindowOverlap,
    WindowShrinkConflict,
)
from itcj2.apps.titulatec.services.slot_service import SlotService


def _t(v):
    """'09:30' | time(9,30) -> time(9,30), o None."""
    if isinstance(v, time):
        return v
    try:
        h, m = str(v).split(":")[:2]
        return time(int(h), int(m))
    except (ValueError, TypeError, AttributeError):
        return None


class ReviewWindowService:
    # ---------------------------------------------------------------- lectura
    @staticmethod
    def get(db: Session, window_id: int):
        from itcj2.apps.titulatec.models import ReviewWindow
        return db.get(ReviewWindow, int(window_id))

    @staticmethod
    def puede_editar(window, user_id: int, *, manage_all: bool) -> bool:
        """Cada encargado edita los SUYOS; la jefatura, los de cualquiera.

        Es una comprobación de propiedad, no de permiso: el permiso ya lo
        resolvió `require_page_app`.
        """
        return bool(window) and (manage_all or window.owner_user_id == user_id)

    # -------------------------------------------------------------- escritura
    @staticmethod
    def assert_no_overlap(db: Session, review_day_id: int, owner_id: int,
                          inicio, fin, *, excluir_id=None) -> None:
        from itcj2.apps.titulatec.models import ReviewWindow
        q = (db.query(ReviewWindow)
             .filter(ReviewWindow.review_day_id == review_day_id,
                     ReviewWindow.owner_user_id == owner_id))
        if excluir_id:
            q = q.filter(ReviewWindow.id != excluir_id)
        for otra in q.all():
            if inicio < otra.end_time and otra.start_time < fin:
                raise WindowOverlap()

    @staticmethod
    def _assert_cabe_lo_agendado(db: Session, window, inicio, fin, minutos, cupo) -> None:
        """Ninguna cita VIVA puede quedar fuera del horario nuevo, ni sobrar del cupo.

        Se comprueba ANTES de escribir: reducir un espacio con gente dentro no
        puede dejarlas huérfanas en silencio.

        Cuenta con `SlotService.occupancy`, que es el MISMO predicado que decide
        el cupo al agendar: filtra por ESTADO —una `cancelled` o una
        `superseded` ya devolvieron su lugar; un `no_show` NO, D10— y **nunca**
        por `is_current`. Contar filas crudas, que es lo que hacía antes,
        rompía un caso perfectamente alcanzable con el historial de intentos:
        el alumno cancela su 09:00 y se re-agenda en la misma 09:00 (legítimo,
        D12 liberó el lugar), quedaban 2 filas en esa hora contra un cupo de 1
        y CUALQUIER edición del espacio —hasta cambiarle solo la ubicación—
        moría con un `WindowShrinkConflict` cuyo número, además, mentía.
        """
        ocupacion = SlotService.occupancy(db, window)
        if not ocupacion:
            return

        rejilla = set(SlotService.slots_from(inicio, fin, minutos))
        fuera = sum(n for hora, n in ocupacion.items() if hora not in rejilla)
        if fuera:
            raise WindowShrinkConflict(fuera)

        excedidas = sum(1 for n in ocupacion.values() if n > int(cupo))
        if excedidas:
            raise WindowShrinkConflict(excedidas)

    @staticmethod
    def create(db: Session, review_day_id: int, owner_id: int, *, start_time,
               end_time, slot_minutes, capacity, location=None,
               position_id=None, actor_id=None):
        from itcj2.apps.titulatec.models import ReviewWindow

        inicio, fin = _t(start_time), _t(end_time)
        if inicio is None or fin is None or fin <= inicio:
            raise InvalidSlot("La hora de fin tiene que ser posterior a la de inicio.")
        ReviewWindowService.assert_no_overlap(db, review_day_id, owner_id, inicio, fin)

        w = ReviewWindow(
            review_day_id=review_day_id, owner_user_id=owner_id,
            owner_position_id=position_id, start_time=inicio, end_time=fin,
            slot_minutes=int(slot_minutes or 30), capacity=int(capacity or 1),
            location=(location or None), status="open",
            created_by_id=actor_id or owner_id,
        )
        db.add(w)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            raise DuplicateWindowStart()
        return w

    @staticmethod
    def update(db: Session, window, *, start_time, end_time, slot_minutes,
               capacity, location=None):
        inicio, fin = _t(start_time), _t(end_time)
        if inicio is None or fin is None or fin <= inicio:
            raise InvalidSlot("La hora de fin tiene que ser posterior a la de inicio.")

        # Bajo el mismo lock que usa el cupo, para que nadie agende justo
        # mientras se encoge el espacio.
        SlotService._lock_window(db, window.id)
        ReviewWindowService.assert_no_overlap(db, window.review_day_id,
                                              window.owner_user_id, inicio, fin,
                                              excluir_id=window.id)
        ReviewWindowService._assert_cabe_lo_agendado(
            db, window, inicio, fin, int(slot_minutes or 30), int(capacity or 1))

        window.start_time = inicio
        window.end_time = fin
        window.slot_minutes = int(slot_minutes or 30)
        window.capacity = int(capacity or 1)
        window.location = location or None
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            raise DuplicateWindowStart()
        return window

    @staticmethod
    def toggle_pause(db: Session, window):
        """En pausa: deja de ofrecer franjas, pero conserva sus citas."""
        window.status = "open" if window.status == "paused" else "paused"
        db.flush()
        return window

    @staticmethod
    def delete(db: Session, window) -> None:
        """Borra el espacio, si de verdad no queda nada que perder.

        Dos motivos distintos para negarse, con mensajes distintos (ver
        `WindowInUse`), porque la acción que le toca al encargado no es la
        misma:

        * **citas vivas** → puede moverlas y volver a intentarlo. El conteo
          sale de `SlotService.occupancy`, el mismo predicado del cupo, así que
          coincide con lo que ve en el tablero. Antes contaba filas crudas y le
          decía «muévelas» por citas canceladas o superadas que ya no están
          ahí;
        * **solo historial muerto** → no hay nada que mover, y la FK
          `fk_titulatec_review_appointments_window` (`ON DELETE RESTRICT`,
          verificado en BD) rechazaría el DELETE igual. Sin este segundo
          chequeo el service daría el visto bueno y Postgres devolvería un
          `IntegrityError` crudo: un 500 en vez de una frase.
        """
        from itcj2.apps.titulatec.models import ReviewAppointment
        vivas = sum(SlotService.occupancy(db, window).values())
        if vivas:
            raise WindowInUse(vivas)
        historicas = (db.query(ReviewAppointment)
                      .filter(ReviewAppointment.window_id == window.id).count())
        if historicas:
            raise WindowInUse(historicas, solo_historial=True)
        db.delete(window)
        db.flush()

    @staticmethod
    def copy_to_days(db: Session, window, review_day_ids) -> tuple[list, list]:
        """Replica el horario en otros días. Devuelve (creados, saltados).

        Los días donde el dueño YA tiene un espacio no se tocan: copiar no puede
        pisar una configuración que alguien hizo a mano.
        """
        from itcj2.apps.titulatec.models import ReviewWindow
        creados, saltados = [], []
        for did in review_day_ids:
            if did == window.review_day_id:
                continue
            existe = (db.query(ReviewWindow)
                      .filter(ReviewWindow.review_day_id == did,
                              ReviewWindow.owner_user_id == window.owner_user_id)
                      .first())
            if existe is not None:
                saltados.append(did)
                continue
            creados.append(ReviewWindowService.create(
                db, did, window.owner_user_id,
                start_time=window.start_time, end_time=window.end_time,
                slot_minutes=window.slot_minutes, capacity=window.capacity,
                location=window.location, position_id=window.owner_position_id,
                actor_id=window.created_by_id))
        return creados, saltados

    @staticmethod
    def pause_future_for_owner(db: Session, owner_id: int, desde) -> int:
        """Pausa los espacios FUTUROS de un encargado que se da de baja.

        Sin esto la ventana queda huérfana y sigue aceptando citas de alguien que
        ya no está. No se borran: sus citas pasadas son historia.
        """
        from itcj2.apps.titulatec.models import CohortReviewDay, ReviewWindow
        filas = (db.query(ReviewWindow)
                 .join(CohortReviewDay, CohortReviewDay.id == ReviewWindow.review_day_id)
                 .filter(ReviewWindow.owner_user_id == owner_id,
                         ReviewWindow.status == "open",
                         CohortReviewDay.date >= desde).all())
        for w in filas:
            w.status = "paused"
        db.flush()
        return len(filas)
