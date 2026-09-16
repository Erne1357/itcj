"""Franjas de cotejo: derivación, ocupación y asignación con cupo duro.

Es el **único camino de escritura** de la hora de una cita. Mientras el POST
siguiera aceptando fecha y hora libres, el límite duro sería evadible: bastaba
con no pasar por aquí.

Franjas derivadas, no materializadas
------------------------------------
``franjas(w) = [start_time + k*slot_minutes]`` mientras la franja **entera**
quepa antes de ``end_time``. No hay tabla de slots, así que no hay nada que
mantener ni que desincronizar. El precio: cambiar ``slot_minutes`` de una
ventana con citas dentro deja citas fuera de la rejilla (09:30 no cae en una
rejilla de 20 minutos). Eso la UI lo muestra en una banda «Fuera de la rejilla»
en vez de esconderlo, y se eligió a sabiendas: materializar los slots crea un
estado que sí se desincroniza en silencio.

El no-show cuenta
-----------------
``occupancy`` incluye las citas en ``no_show``. Decisión del usuario: «si no se
presentó es que ya pasó», así que la franja se consumió y su lugar no se
reabre. El registro histórico se queda donde estaba.

EXCEPCIÓN DELIBERADA a la convención de la casa (commit en el service)
----------------------------------------------------------------------
**Ningún método de esta clase hace `db.commit()`.** El commit liberaría el
``FOR UPDATE`` antes de que el INSERT llegara a la base, y el lock no serviría
de nada. El dueño de la transacción es quien llama: `AppointmentService.create`,
`.reschedule` o la ruta del reparto masivo. Lo fija un test estructural.

Por qué el lock va sobre la VENTANA
-----------------------------------
Lección de AgendaTec: ``FOR UPDATE`` sobre cero filas **no bloquea nada**, y el
caso normal aquí es insertar la primera cita de una franja vacía. Bloquear «las
citas de esta franja» no serializaría a dos encargados que llegan a la vez. La
fila de la ventana, en cambio, siempre existe.

Y como un proceso tiene **una sola** cita mientras que el lock es por ventana,
dos ventanas distintas no se serializarían entre sí: por eso además se toma un
``pg_advisory_xact_lock`` sobre el proceso. Es de **transacción** y no de
sesión, lo único compatible con PgBouncer en modo transaction.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta

from sqlalchemy import func, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from itcj2.apps.titulatec.services.appointment_errors import (
    InvalidSlot, MissingSchedule, SlotFull, SlotLockTimeout,
)

# Namespace del advisory lock que serializa las citas de un mismo proceso.
# Arbitrario pero fijo: cambiarlo deja de excluir a las transacciones que ya
# estén corriendo con el valor viejo.
_PROCESO_LOCK_NS = 0x7455  # "tU"

# Estados que NO ocupan lugar: la franja vuelve al pozo. `cancelled` (D12:
# canceló a tiempo, el lugar vuelve) y `superseded` (su ocupación la hereda la
# fila nueva del intento siguiente). `no_show` y `attended` NO están aquí a
# propósito aunque ya no sean la cita vigente: D10 dice que si no se presentó
# es que ya pasó, y D5 que una atendida con faltantes sigue "ocupando" hasta
# que la fase 2 se apruebe. Ver `occupancy` — es el punto exacto donde esto se
# puede romper otra vez confundiéndolo con `is_current`.
_ESTADOS_QUE_LIBERAN: set[str] = {"cancelled", "superseded"}

# Estados "vivos" de una cita (D4). Si la vigente está en uno de estos cuando
# `assign`/`assign_batch` abren un intento nuevo, SÍ hubo una transición real
# (reagendar/mover) y la fila vieja pasa a 'superseded'. Fuera de este set
# (no_show, attended) la fila vieja conserva su status: abrir un intento nuevo
# tras esos NO es una transición de estado (spec 2026-09-15 §2.2).
_ESTADOS_ACTIVOS: set[str] = {"scheduled", "confirmed", "in_progress"}


class SlotService:
    # ------------------------------------------------------------- derivación
    @staticmethod
    def slots(window) -> list[time]:
        """Las horas de inicio de cada franja de la ventana.

        Solo cuenta la franja si cabe ENTERA: una ventana 09:00-10:20 con
        franjas de 30 da 09:00 y 09:30, no 10:00 (que se saldría a las 10:30).
        """
        if not window or not window.start_time or not window.end_time:
            return []
        paso = timedelta(minutes=int(window.slot_minutes or 0))
        if paso <= timedelta(0):
            return []
        base = date(2000, 1, 1)
        actual = datetime.combine(base, window.start_time)
        fin = datetime.combine(base, window.end_time)
        salida = []
        while actual + paso <= fin:
            salida.append(actual.time())
            actual += paso
        return salida

    @staticmethod
    def slots_from(start, end, minutes) -> list:
        """Las mismas franjas, pero a partir de valores sueltos.

        La usa el editor de espacios para calcular la linea derivada («10 franjas
        de 2 personas, 20 citas en total») ANTES de que exista la ventana. Acepta
        `time` o "HH:MM" indistintamente, que es lo que llega de un formulario.
        """
        def _t(v):
            if isinstance(v, time):
                return v
            try:
                h, m = str(v).split(":")[:2]
                return time(int(h), int(m))
            except (ValueError, TypeError):
                return None

        ini, fin = _t(start), _t(end)
        try:
            paso = timedelta(minutes=int(minutes))
        except (TypeError, ValueError):
            return []
        if ini is None or fin is None or paso <= timedelta(0):
            return []
        base = date(2000, 1, 1)
        actual, tope = datetime.combine(base, ini), datetime.combine(base, fin)
        salida = []
        while actual + paso <= tope:
            salida.append(actual.time())
            actual += paso
        return salida

    @staticmethod
    def day_defaults(db: Session, review_day) -> dict:
        """Valores efectivos de un día: override del día, o el de la convocatoria.

        Es lo que precarga el editor de espacios. La ventana en sí guarda sus
        valores en columnas NOT NULL, así que la herencia ocurre **al crearla**,
        no al leerla: una vez creada, cambiar el default de la convocatoria no
        le mueve el horario a nadie.
        """
        from itcj2.apps.titulatec.models import Cohort
        cohort = db.get(Cohort, review_day.cohort_id)
        return {
            "start_time": review_day.start_time or (cohort.default_start_time if cohort else time(9, 0)),
            "end_time": review_day.end_time or (cohort.default_end_time if cohort else time(14, 0)),
            "slot_minutes": review_day.slot_minutes or (cohort.default_slot_minutes if cohort else 30),
            "capacity": review_day.capacity or (cohort.default_capacity if cohort else 1),
            "location": review_day.location or (cohort.default_location if cohort else None),
        }

    # -------------------------------------------------------------- ocupación
    @staticmethod
    def occupancy(db: Session, window, *, excluir_process_id: int | None = None) -> dict:
        """{hora_de_inicio: cuántas citas} de esa ventana.

        `excluir_process_id` es para MOVER: al recolocar a un alumno dentro de
        su propia ventana, su cita actual no puede contarse contra el cupo de
        la franja destino.
        """
        from itcj2.apps.titulatec.models import ReviewAppointment
        if not window or not window.id:
            return {}
        q = db.query(ReviewAppointment).filter(ReviewAppointment.window_id == window.id)
        # Filtra por ESTADO, nunca por `is_current`. Una fila `no_show` o
        # `attended` que ya no es la vigente sigue ocupando su franja (D10/D5).
        # Añadir `is_current == True` aquí parece lo natural al leer esto por
        # primera vez tras introducir el historial de intentos, y ES EL ERROR:
        # reabre el defecto de la spec 2026-09-15 §0 (reagendar liberaba la
        # franja del no-show). `is_current` es del historial, no de la
        # ocupación.
        if _ESTADOS_QUE_LIBERAN:
            q = q.filter(~ReviewAppointment.status.in_(_ESTADOS_QUE_LIBERAN))
        if excluir_process_id:
            q = q.filter(ReviewAppointment.process_id != excluir_process_id)
        salida: dict[time, int] = {}
        for a in q.all():
            if a.scheduled_at:
                hora = a.scheduled_at.time()
                salida[hora] = salida.get(hora, 0) + 1
        return salida

    @staticmethod
    def window_occupancy(db: Session, window) -> tuple[int, int]:
        """(ocupados, capacidad total) de UNA ventana."""
        franjas = SlotService.slots(window)
        ocupacion = SlotService.occupancy(db, window)
        # Solo cuentan las citas que caen en una franja real: las que quedaron
        # fuera de la rejilla tras cambiar `slot_minutes` se muestran aparte y
        # no inflan el denominador.
        ocupados = sum(n for hora, n in ocupacion.items() if hora in set(franjas))
        return ocupados, len(franjas) * int(window.capacity or 1)

    @staticmethod
    def day_occupancy(db: Session, windows) -> tuple[int, int]:
        """(ocupados, capacidad) de un conjunto de ventanas.

        UNA sola función alimenta el chip del carril de días Y la cabecera del
        tablero. Con dos numeradores distintos la misma pantalla mostraba dos
        cifras que no cuadraban, y el numerador salía acotado por carrera
        mientras el denominador no: la carrera decide qué NOMBRES se ven, nunca
        los conteos.
        """
        total_ocupados = total_capacidad = 0
        for w in windows or []:
            o, c = SlotService.window_occupancy(db, w)
            total_ocupados += o
            total_capacidad += c
        return total_ocupados, total_capacidad

    @staticmethod
    def free_slots(db: Session, window, *, excluir_process_id: int | None = None) -> list[time]:
        """Franjas con lugar libre, en orden."""
        ocupacion = SlotService.occupancy(db, window, excluir_process_id=excluir_process_id)
        cupo = int(window.capacity or 1)
        return [h for h in SlotService.slots(window) if ocupacion.get(h, 0) < cupo]

    # ------------------------------------------------------------ asignación
    @staticmethod
    def _lock_window(db: Session, window_id: int):
        """Bloquea la fila de la ventana y devuelve la ventana cargada.

        `lock_timeout` es LOCAL, no de sesión: PgBouncer está en modo
        transaccional y un `SET` de sesión se le queda pegado a otro cliente.
        """
        from itcj2.apps.titulatec.models import ReviewWindow
        try:
            db.execute(text("SET LOCAL lock_timeout = '3s'"))
            db.execute(
                text("SELECT id FROM titulatec_review_windows WHERE id = :w FOR UPDATE"),
                {"w": int(window_id)},
            ).first()
        except OperationalError as e:      # lock_timeout agotado
            raise SlotLockTimeout() from e
        window = db.get(ReviewWindow, int(window_id))
        if window is None:
            raise InvalidSlot("Ese espacio ya no existe.")
        return window

    @staticmethod
    def _lock_process(db: Session, process_id: int) -> None:
        """Serializa las citas de un mismo proceso entre ventanas distintas."""
        db.execute(text("SELECT pg_advisory_xact_lock(:ns, :pid)"),
                   {"ns": _PROCESO_LOCK_NS, "pid": int(process_id)})

    @staticmethod
    def assign(db: Session, window_id: int | None, slot_start: time | None,
               process_id: int, actor_id: int, *, location: str | None = None):
        """Sienta a un proceso en una franja. NO commitea.

        Nunca mueve una fila existente: si el proceso ya tenía una cita
        vigente, la CIERRA (a `superseded` si estaba activa —
        scheduled/confirmed/in_progress—; conserva su status si no, p. ej.
        `no_show`) e INSERTA un intento nuevo con `attempt_no+1`. Devuelve la
        `ReviewAppointment` recién creada, siempre vigente. Levanta
        `MissingSchedule`, `InvalidSlot` o `SlotFull`.
        """
        from itcj2.apps.titulatec.models import ReviewAppointment

        if not window_id or slot_start is None:
            raise MissingSchedule()

        window = SlotService._lock_window(db, window_id)
        SlotService._lock_process(db, process_id)

        if slot_start not in set(SlotService.slots(window)):
            raise InvalidSlot()

        ocupacion = SlotService.occupancy(db, window, excluir_process_id=process_id)
        if ocupacion.get(slot_start, 0) >= int(window.capacity or 1):
            raise SlotFull()

        cuando = datetime.combine(window.review_day.date, slot_start)
        lugar = location if location is not None else window.location

        vigente = (db.query(ReviewAppointment)
                   .filter_by(process_id=process_id, is_current=True)
                   .first())
        if vigente is not None:
            if vigente.status in _ESTADOS_ACTIVOS:
                vigente.status = "superseded"
            vigente.is_current = False
            # Cierra la vigente ANTES de insertar la nueva. El índice único
            # parcial (`uq_titulatec_review_appt_current`) exige que nunca
            # convivan dos `is_current=True` del mismo proceso: si el INSERT
            # de abajo llegara a la base antes que este UPDATE, Postgres
            # revienta con violación de unicidad. El orden importa.
            db.flush()

        attempt_no = (db.query(func.max(ReviewAppointment.attempt_no))
                      .filter_by(process_id=process_id).scalar() or 0) + 1

        appt = ReviewAppointment(
            process_id=process_id, window_id=window.id, scheduled_at=cuando,
            location=lugar, status="scheduled", created_by_id=actor_id,
            is_current=True, attempt_no=attempt_no,
        )
        db.add(appt)
        db.flush()
        return appt

    @staticmethod
    def assign_batch(db: Session, window_id: int, procesos: list, actor_id: int,
                     *, desde: time | None = None, location: str | None = None):
        """Reparte varios procesos en franjas consecutivas libres. NO commitea.

        Devuelve `(asignados, fuera)`, donde `asignados` es
        `[(hora, process_id), ...]` y `fuera` la lista de ids que no cupieron.

        Es **atómico** en el sentido que importa: toma UN solo lock de ventana y
        hace todos los INSERT dentro de él. Sin eso, reintentar un reparto a
        medias movía de sitio a los que ya estaban sentados.

        Límite duro: cuando se acaban los lugares **se detiene**, no desborda.

        Igual que `assign`: si un proceso ya tenía cita vigente, la CIERRA
        (superseded si estaba activa; conserva su status si no) e INSERTA un
        intento nuevo. Nunca mueve la fila existente.
        """
        from itcj2.apps.titulatec.models import ReviewAppointment

        if not procesos:
            return [], []

        window = SlotService._lock_window(db, window_id)
        cupo = int(window.capacity or 1)
        ocupacion = SlotService.occupancy(db, window)
        franjas = SlotService.slots(window)
        if desde is not None:
            franjas = [h for h in franjas if h >= desde]

        asignados, fuera = [], []
        pendientes = list(procesos)
        for hora in franjas:
            libres = cupo - ocupacion.get(hora, 0)
            while libres > 0 and pendientes:
                pid = pendientes.pop(0)
                SlotService._lock_process(db, pid)
                cuando = datetime.combine(window.review_day.date, hora)
                lugar = location if location is not None else window.location

                vigente = (db.query(ReviewAppointment)
                          .filter_by(process_id=pid, is_current=True)
                          .first())
                if vigente is not None:
                    if vigente.status in _ESTADOS_ACTIVOS:
                        vigente.status = "superseded"
                    vigente.is_current = False
                    # Mismo orden que en `assign`: cerrar antes de insertar,
                    # o el indice unico parcial revienta.
                    db.flush()

                attempt_no = (db.query(func.max(ReviewAppointment.attempt_no))
                             .filter_by(process_id=pid).scalar() or 0) + 1
                db.add(ReviewAppointment(
                    process_id=pid, window_id=window.id, scheduled_at=cuando,
                    location=lugar, status="scheduled", created_by_id=actor_id,
                    is_current=True, attempt_no=attempt_no))
                asignados.append((hora, pid))
                ocupacion[hora] = ocupacion.get(hora, 0) + 1
                libres -= 1
            if not pendientes:
                break

        fuera = pendientes
        db.flush()
        return asignados, fuera

    @staticmethod
    def propose_batch(db: Session, window, procesos: list, *, desde: time | None = None):
        """La misma repartición, pero SIN tocar la base. Es la propuesta que el
        encargado confirma o descarta; vive entera en el querystring."""
        cupo = int(window.capacity or 1)
        ocupacion = SlotService.occupancy(db, window)
        franjas = SlotService.slots(window)
        if desde is not None:
            franjas = [h for h in franjas if h >= desde]

        propuesta, pendientes = [], list(procesos)
        for hora in franjas:
            libres = cupo - ocupacion.get(hora, 0)
            while libres > 0 and pendientes:
                propuesta.append((hora, pendientes.pop(0)))
                libres -= 1
            if not pendientes:
                break
        return propuesta, pendientes

    @staticmethod
    def out_of_grid(db: Session, window) -> list:
        """Citas de la ventana cuya hora ya no cae en ninguna franja.

        Pasa al cambiar `slot_minutes` con citas dentro. Se muestran en su
        propia banda: esconderlas sería peor que enseñarlas.
        """
        from itcj2.apps.titulatec.models import ReviewAppointment
        validas = set(SlotService.slots(window))
        filas = (db.query(ReviewAppointment)
                 .filter(ReviewAppointment.window_id == window.id).all())
        return [a for a in filas
                if a.scheduled_at and a.scheduled_at.time() not in validas]

    # ------------------------------------------------------------ resolución
    @staticmethod
    def windows_for_day(db: Session, review_day_id: int, *, owner_id: int | None = None,
                        solo_abiertas: bool = True) -> list:
        """Ventanas de un día, opcionalmente solo las de un encargado."""
        from itcj2.apps.titulatec.models import ReviewWindow
        q = db.query(ReviewWindow).filter(ReviewWindow.review_day_id == review_day_id)
        if owner_id is not None:
            q = q.filter(ReviewWindow.owner_user_id == owner_id)
        if solo_abiertas:
            q = q.filter(ReviewWindow.status == "open")
        return q.order_by(ReviewWindow.start_time, ReviewWindow.id).all()

    @staticmethod
    def resolve(db: Session, cohort_id: int, day: date, hhmm: time,
                owner_id: int | None = None):
        """(ventana, franja) para una fecha y hora dadas, o (None, None).

        Puente para los caminos que todavía llegan con fecha y hora sueltas.
        Prefiere la ventana del propio encargado; si no tiene ninguna que
        contenga esa hora, acepta cualquier ventana abierta del día que sí la
        contenga, para no romper las citas heredadas.

        La hora se ajusta a la franja: 09:17 en una rejilla de 30 cae en 09:00.
        No es laxitud, es lo que permite que un `datetime` viejo siga casando
        con la rejilla nueva sin inventar una franja que no existe.
        """
        from itcj2.apps.titulatec.models import CohortReviewDay
        fila = (db.query(CohortReviewDay)
                .filter_by(cohort_id=cohort_id, date=day).first())
        if fila is None or fila.is_closed:
            return None, None

        candidatas = SlotService.windows_for_day(db, fila.id, owner_id=owner_id)
        if not candidatas:
            candidatas = SlotService.windows_for_day(db, fila.id)

        for w in candidatas:
            if not (w.start_time <= hhmm < w.end_time):
                continue
            franjas = SlotService.slots(w)
            cabe = [f for f in franjas if f <= hhmm]
            if cabe:
                return w, cabe[-1]
        return None, None
