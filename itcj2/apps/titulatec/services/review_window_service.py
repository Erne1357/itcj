"""Espacios de cotejo: el horario propio de cada encargado dentro de un día.

Lo que aquí se valida son las dos formas de perder citas en silencio:

* **encoger un espacio** que ya tiene gente dentro (bajar la capacidad, recortar
  el horario, cambiar la duración de las franjas o cambiarle el MODO: un sin
  horario, ``walkin``, es una sola franja con el cupo total, spec 2026-09-29
  §3.1, así que `update` valida contra el modo DESTINO);
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
    DuplicateWindowStart, InvalidSlot, PlacesOutOfRange, WalkinStartLocked,
    WindowInUse, WindowModeConflict, WindowOverlap, WindowShrinkConflict,
)
from itcj2.apps.titulatec.services.slot_service import SlotService

# «Abrir más lugares» (D6): de 1 a 50 por vez, nunca más de 500 en total. El
# tope total es el MISMO `max` del campo «Personas en total» del editor: si
# abrir lugares lo rebasara, el formulario ya no dejaría volver a guardar el
# espacio. El texto de `PlacesOutOfRange` repite los dos números.
_LUGARES_POR_VEZ = 50
_LUGARES_TOPE = 500


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
    def _se_encima(db: Session, review_day_id: int, owner_id: int, inicio, fin,
                   *, excluir_id=None) -> bool:
        """True si `[inicio, fin)` se encima con OTRO espacio del mismo dueño
        ese día.

        Es el predicado puro, sin la excepción: `assert_no_overlap` lo usa tal
        cual para crear/editar UN espacio, y `create_many`/`copy_to_days` (D9)
        lo usan para decidir a cuál de varios días saltarse, uno por uno, sin
        levantar nada.
        """
        from itcj2.apps.titulatec.models import ReviewWindow
        q = (db.query(ReviewWindow)
             .filter(ReviewWindow.review_day_id == review_day_id,
                     ReviewWindow.owner_user_id == owner_id))
        if excluir_id:
            q = q.filter(ReviewWindow.id != excluir_id)
        return any(inicio < otra.end_time and otra.start_time < fin for otra in q.all())

    @staticmethod
    def assert_no_overlap(db: Session, review_day_id: int, owner_id: int,
                          inicio, fin, *, excluir_id=None) -> None:
        if ReviewWindowService._se_encima(db, review_day_id, owner_id, inicio, fin,
                                          excluir_id=excluir_id):
            raise WindowOverlap()

    @staticmethod
    def _assert_cabe_lo_agendado(db: Session, window, inicio, fin, minutos, cupo,
                                 *, walkin: bool) -> None:
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

        Se mide contra el modo DESTINO (`walkin`), que es lo que va a quedar
        escrito; el de origen es el que la ventana tiene todavía:

        * sin horario -> sin horario, con citas vivas y otra apertura:
          `WalkinStartLocked`. Los apartados guardan día + apertura;
        * -> sin horario: ninguna viva puede quedar, por su hora real, fuera
          del horario nuevo ``[inicio, fin)`` (una sentada a las 13:30 no cabe
          en un 09:00-12:00 aunque sobre cupo, y se le seguiría anunciando su
          hora); y como es una sola franja, todas cuentan juntas contra el
          cupo TOTAL. Las dos, `WindowShrinkConflict`;
        * sin horario -> con franjas: cada cita vuelve a su hora real y tiene
          que caber en la rejilla y en el cupo por franja nuevos
          (`WindowModeConflict`, con cuántas no caben);
        * con franjas -> con franjas: la rejilla y el cupo de siempre.

        Ruling 2026-09-29 (revisión de T2, arrastrada a la Tarea 4 — spec
        §3.2): dentro de las dos que van HACIA sin horario, el cupo total que
        no alcanza es dos cosas distintas según de dónde se venga. Si YA era
        sin horario y se baja el cupo por debajo de lo apartado, el horario no
        se tocó — sigue siendo el encogimiento de siempre
        (`WindowShrinkConflict`). Si se viene de franjas, el horario tampoco
        cambia de sitio: es el CUPO TOTAL del modo nuevo el que no las
        aguanta, y eso es `WindowModeConflict`, no un horario que se quedó
        chico. Antes las dos disparaban `WindowShrinkConflict`, y su frase
        («fuera del horario nuevo») no describía lo que pasó en el segundo
        caso: el horario no cambió, el modo sí.
        """
        cupo = int(cupo)
        desde_walkin = window.visibility == "walkin"

        if walkin:
            # UNA sola consulta, agrupada por hora REAL: sirve para «vivas»
            # (la suma, que da igual cómo se agrupe) y para «fuera» (qué horas
            # caen fuera del horario nuevo). Antes se pedía `occupancy` DOS
            # veces —una agrupada por apertura, solo para sumarla después— y
            # las dos cuentan exactamente las mismas filas.
            reales = SlotService.occupancy(db, window, walkin=False)
            if not reales:
                return
            vivas = sum(reales.values())
            if desde_walkin and inicio != window.start_time:
                raise WalkinStartLocked(vivas)
            fuera = sum(n for hora, n in reales.items() if not inicio <= hora < fin)
            if fuera:
                raise WindowShrinkConflict(fuera)
            if vivas > cupo:
                if desde_walkin:
                    raise WindowShrinkConflict(vivas - cupo)
                raise WindowModeConflict(vivas - cupo)
            return

        ocupacion = SlotService.occupancy(db, window, walkin=False)
        if not ocupacion:
            return
        rejilla = set(SlotService.slots_from(inicio, fin, minutos))
        fuera = sum(n for hora, n in ocupacion.items() if hora not in rejilla)
        if desde_walkin:
            sobran = sum(n - cupo for hora, n in ocupacion.items()
                         if hora in rejilla and n > cupo)
            if fuera or sobran:
                raise WindowModeConflict(fuera + sobran)
            return

        if fuera:
            raise WindowShrinkConflict(fuera)

        excedidas = sum(1 for n in ocupacion.values() if n > cupo)
        if excedidas:
            raise WindowShrinkConflict(excedidas)

    @staticmethod
    def create(db: Session, review_day_id: int, owner_id: int, *, start_time,
               end_time, slot_minutes, capacity, location=None,
               position_id=None, actor_id=None, visibility="private"):
        """`visibility` nace `private` (D1): publicar es un acto deliberado.

        El default del parámetro repite el `server_default` de la columna a
        propósito — así un llamador que no lo pase (el alta desde otro punto de
        la app) no publica un espacio sin querer.
        """
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
            visibility=visibility or "private",
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
               capacity, location=None, visibility=None):
        """`visibility=None` CONSERVA el modo actual, no lo devuelve a privado.

        La distinción importa: los llamadores que no saben del modo (o que solo
        tocan el horario) no pueden despublicar un espacio por omisión. Por lo
        mismo, lo agendado se valida contra el modo que va a quedar: el nuevo,
        o el de siempre si no se pasó ninguno.
        """
        inicio, fin = _t(start_time), _t(end_time)
        if inicio is None or fin is None or fin <= inicio:
            raise InvalidSlot("La hora de fin tiene que ser posterior a la de inicio.")

        # Bajo el mismo lock que usa el cupo, para que nadie agende justo
        # mientras se encoge el espacio. `_lock_window` relee `window` (es el
        # mismo objeto del mapa de identidad): lo de abajo valida contra la
        # fila de ahora, no contra la que se cargó antes de esperar.
        SlotService._lock_window(db, window.id)
        ReviewWindowService.assert_no_overlap(db, window.review_day_id,
                                              window.owner_user_id, inicio, fin,
                                              excluir_id=window.id)
        destino = visibility if visibility is not None else window.visibility
        ReviewWindowService._assert_cabe_lo_agendado(
            db, window, inicio, fin, int(slot_minutes or 30), int(capacity or 1),
            walkin=destino == "walkin")

        window.start_time = inicio
        window.end_time = fin
        window.slot_minutes = int(slot_minutes or 30)
        window.capacity = int(capacity or 1)
        window.location = location or None
        if visibility is not None:
            window.visibility = visibility
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            raise DuplicateWindowStart()
        return window

    @staticmethod
    def add_places(db: Session, window, n: int):
        """«Abrir más lugares» (D6): `capacity += n` bajo el lock de la ventana.

        Solo en sin horario (`InvalidSlot` si no): con franjas `capacity` es
        POR FRANJA, que el editor topa en 20, y se edita ahí.

        `n` va de 1 a 50 y el total no pasa de 500 (`PlacesOutOfRange`). El
        rango de `n` es entrada del usuario y se revisa antes del lock; el
        modo y el tope total, después, contra la fila que `_lock_window` RELEE
        bajo el lock (esa es la única relectura; aquí no se repite). Si
        mientras se esperaba otro encargado abrió lugares, sumarle al valor
        viejo borraría los suyos; si pasó el espacio a «Agendable», se sumaría
        a un cupo por franja.
        """
        try:
            n = int(n)
        except (TypeError, ValueError):
            raise PlacesOutOfRange() from None
        if not 1 <= n <= _LUGARES_POR_VEZ:
            raise PlacesOutOfRange()

        w = SlotService._lock_window(db, window.id)
        if w.visibility != "walkin":
            raise InvalidSlot("Solo los espacios sin horario abren lugares.")
        total = int(w.capacity or 1) + n
        if total > _LUGARES_TOPE:
            raise PlacesOutOfRange()
        w.capacity = total
        db.flush()
        return w

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
    def create_many(db: Session, day_ids, owner_id: int, *,
                    position_id=None, actor_id=None, **campos) -> tuple[list, list]:
        """Crea el MISMO espacio en varios días a la vez (D9). (creados, saltados).

        `saltados` son FECHAS (`date`), no ids de día: es lo que necesita el
        aviso («se saltaron 2: mar 07, jue 09»). Se salta un día cuando el
        horario nuevo se ENCIMA con otro espacio del mismo dueño ese día — el
        mismo predicado que usa `assert_no_overlap` al crear uno solo, sin la
        excepción.

        El encimado se resuelve para TODOS los días ANTES de crear el primero.
        `create()` solo atrapa la UNIQUE del arranque (`DuplicateWindowStart`
        vía `IntegrityError`), no el solape; un `IntegrityError` a mitad del
        lote se llevaría el `db.rollback()` por delante de lo YA creado en
        esta misma llamada (todavía sin commit: el dueño de la transacción es
        la ruta). Decidir el reparto completo de una sola pasada evita ese
        riesgo salvo carrera real entre dos peticiones — y entonces sí falla
        el lote entero, que es aceptable (spec §5).
        """
        from itcj2.apps.titulatec.models import CohortReviewDay

        inicio, fin = _t(campos.get("start_time")), _t(campos.get("end_time"))
        if inicio is None or fin is None or fin <= inicio:
            raise InvalidSlot("La hora de fin tiene que ser posterior a la de inicio.")

        filas = (db.query(CohortReviewDay)
                 .filter(CohortReviewDay.id.in_(day_ids)).all())
        por_id = {f.id: f for f in filas}

        a_crear, saltados = [], []
        for did in day_ids:
            fila = por_id.get(did)
            if fila is None:            # id que ya no existe: se ignora, no truena
                continue
            if ReviewWindowService._se_encima(db, fila.id, owner_id, inicio, fin):
                saltados.append(fila.date)
            else:
                a_crear.append(fila)

        creados = [ReviewWindowService.create(
            db, fila.id, owner_id, position_id=position_id, actor_id=actor_id,
            **campos) for fila in a_crear]
        return creados, saltados

    @staticmethod
    def copy_to_days(db: Session, window, review_day_ids) -> tuple[list, list]:
        """Replica el horario en los DÍAS ELEGIDOS. Devuelve (creados, saltados).

        D9 (spec §0.2, el bug de origen): antes copiaba a TODOS los días de la
        convocatoria y saltaba cualquiera donde el dueño YA tuviera un espacio,
        aunque fuera a otra hora — «copiar a los demás días» pisaba en silencio
        la elección de dejar un hueco. Ahora copia solo a los días que se le
        pasan, y salta nada más el que de verdad se ENCIMA con el horario que
        se está copiando (mismo predicado que `create_many`, y `saltados` es
        igual de fechas: las dos alimentan el mismo aviso).

        **Copia también el MODO** (`visibility`). Sin eso, el encargado publica
        el lunes como «Agendable», copia a los demás días y el martes nace
        privado: espacios gemelos con visibilidad distinta y nada que se lo
        diga. El horario y el modo son la misma decisión.
        """
        from itcj2.apps.titulatec.models import CohortReviewDay
        filas = (db.query(CohortReviewDay)
                 .filter(CohortReviewDay.id.in_(review_day_ids)).all())
        por_id = {f.id: f for f in filas}

        creados, saltados = [], []
        for did in review_day_ids:
            fila = por_id.get(did)
            if fila is None or fila.id == window.review_day_id:
                continue
            if ReviewWindowService._se_encima(db, fila.id, window.owner_user_id,
                                              window.start_time, window.end_time):
                saltados.append(fila.date)
                continue
            creados.append(ReviewWindowService.create(
                db, fila.id, window.owner_user_id,
                start_time=window.start_time, end_time=window.end_time,
                slot_minutes=window.slot_minutes, capacity=window.capacity,
                location=window.location, position_id=window.owner_position_id,
                actor_id=window.created_by_id, visibility=window.visibility))
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
