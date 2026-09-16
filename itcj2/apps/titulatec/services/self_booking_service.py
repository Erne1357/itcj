"""Reglas del EGRESADO para su cita de cotejo (spec 2026-09-15 §3 y §4.1).

D13 parte las guardas en dos capas, y esa partición decide dónde vive cada regla:

* **Duras**, en `AppointmentService` / `SlotService`, para TODOS (encargado
  incluido): una sola cita vigente por proceso, encuesta enviada, día
  habilitado, franja real de la rejilla, cupo libre, lock de ventana y
  advisory lock del proceso.
* **Del alumno**, aquí: fase 2 aprobada, tope de cancelaciones propias,
  anticipación mínima, y que la ventana esté publicada y sea de su carrera.

Por eso `cancel` **envuelve** a `AppointmentService.cancel` en vez de
duplicarla, y `book` delega en `AppointmentService.create`: si la ventana de
2 h se colara a la capa compartida se le aplicaría también al encargado, que
no tiene ventana de tiempo, y reimplementar aquí las guardas duras es
exactamente como se abren los agujeros. Si acabas escribiendo dos veces la
misma regla, la partición está mal hecha.

`eligibility` es la ÚNICA fuente de la verdad de «¿puede agendar solo?»
-------------------------------------------------------------------------
La consumen la pantalla del alumno (sus cuatro caras) y el cubo «Requieren que
les agendes» de la cola del encargado (D10). Con dos implementaciones, el cubo
diría una cosa y el alumno vería otra — y el alumno tendría razón la mitad de
las veces.

El reloj es `db_now()`
----------------------
Hora local naive, idéntica a la que produce `NOW()` en Postgres, porque TODAS
las columnas de fecha de esta app son naive. Nunca `utcnow()`: restaría seis
horas y la ventana de D8 se abriría o cerraría sola. Se importa a nivel de
módulo a propósito, para que un test pueda fijarlo con
`monkeypatch.setattr(mod, "db_now", ...)`.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from itcj2.apps.titulatec.services.appointment_errors import (
    CancelTooLate, NotYours, SelfBookingNotAllowed, SlotTooSoon,
)
from itcj2.core.utils.timezone import db_now

# Los dos modos PUBLICADOS de un espacio (D1). `private` es el default y
# significa «el egresado no lo ve»: no entra ni a la oferta ni a la
# revalidación de `book`, así que publicar sigue siendo un acto deliberado.
_VISIBLES: tuple[str, ...] = ("bookable", "walkin")


def _nombre(user) -> str:
    """Nombre del encargado para el anuncio del espacio.

    `full_name` es la propiedad que ya usa el resto de la app (`_proc_rows`).
    El respaldo evita que una fila de usuario perdida deje un anuncio mudo.
    """
    return (getattr(user, "full_name", None) or "").strip() or "Servicios Escolares"


class SelfBookingService:
    """Todas las reglas del auto-agendado del egresado."""

    # §3, columna «Mensaje al alumno», literal. Vive aquí y no en la plantilla
    # porque la consumen dos sitios: la cara 4 de la pantalla del alumno («una
    # frase que dice por qué», nunca un botón deshabilitado y mudo) y el error
    # que levanta `book`. Con el texto en la plantilla, el error diría otra cosa.
    MENSAJES: dict[str, str] = {
        "proceso_inactivo": "Tu proceso no está activo.",
        "fase_aprobada": "Tu cotejo ya quedó aprobado. No necesitas otra cita.",
        "sin_encuesta": "Primero envía la encuesta de egresados.",
        "tiene_cita": "Ya tienes una cita. Cancélala si necesitas otra.",
        "bloqueado_por_cancelaciones": ("Cancelaste {n} veces. Pídele la cita a tu "
                                        "encargado de carrera."),
    }

    # ------------------------------------------------------------- utilería
    @staticmethod
    def _settings():
        """`get_settings()` está cacheado; el import va local (gotcha 2)."""
        from itcj2.config import get_settings
        return get_settings()

    @staticmethod
    def message_for(reason: str | None, *, cancellations: int | None = None) -> str | None:
        """La frase que ve el alumno para ese `reason`, o None si puede agendar.

        El conteo entra por parámetro para que el mensaje diga las veces REALES
        que canceló y no el tope configurado (son iguales en el caso normal, y
        dejan de serlo en cuanto alguien baje el tope con gente ya bloqueada).
        """
        if not reason:
            return None
        plantilla = SelfBookingService.MENSAJES.get(reason)
        if plantilla is None:
            return None
        if "{n}" in plantilla:
            n = (cancellations if cancellations is not None
                 else SelfBookingService._settings().TITULATEC_SELF_CANCEL_MAX)
            return plantilla.format(n=n)
        return plantilla

    # -------------------------------------------------------- D9: el contador
    @staticmethod
    def cancellations(db: Session, proc) -> int:
        """Cuántas veces canceló ÉL su propia cita.

        Derivado, sin columna denormalizada: `status='cancelled'` **y**
        `cancelled_by_id == process.student_id`. Si cancela el encargado no le
        consume cupo — si no, el encargado podría dejarlo bloqueado sin querer.

        `student_id` y `cancelled_by_id` son las dos `BigInteger` con FK a
        `core_users.id`, así que la comparación es directa y no pasa por
        ninguna otra tabla.
        """
        from itcj2.apps.titulatec.models import ReviewAppointment
        if proc is None:
            return 0
        return (db.query(ReviewAppointment)
                .filter(ReviewAppointment.process_id == proc.id,
                        ReviewAppointment.status == "cancelled",
                        ReviewAppointment.cancelled_by_id == proc.student_id)
                .count())

    @staticmethod
    def is_blocked_by_cancellations(db: Session, proc) -> bool:
        """El predicado de D9, aislado.

        Lo comparten la regla 5 de `eligibility` y el cubo de D10
        (`AppointmentService.list_self_blocked_processes`), que así no puede
        discrepar de lo que ve el alumno en su pantalla.
        """
        return (SelfBookingService.cancellations(db, proc)
                >= SelfBookingService._settings().TITULATEC_SELF_CANCEL_MAX)

    # ------------------------------------------------------------ §3: la puerta
    @staticmethod
    def _fase_cotejo_aprobada(db: Session, proc) -> bool:
        """Regla 2: se lee de `ProcessPhase` de la fase 2, NUNCA de `appt.status`.

        D5: el corte real es la FASE aprobada. Una cita `attended` a la que le
        faltaron papeles deja la fase abierta, y ese alumno **sí** puede
        agendar otra — que es literalmente lo que esta feature viene a
        habilitar. `PhaseService.PHASE_COTEJO` y no un `2` literal, para que
        grep lo encuentre desde el otro lado.
        """
        from itcj2.apps.titulatec.models import ProcessPhase
        from itcj2.apps.titulatec.services.phase_service import PhaseService

        fila = (db.query(ProcessPhase)
                .filter_by(process_id=proc.id,
                           phase_number=PhaseService.PHASE_COTEJO)
                .first())
        return fila is not None and fila.status == "approved"

    @staticmethod
    def eligibility(db: Session, process_id: int) -> dict:
        """¿Puede agendar solo, y si no, por qué? (spec §3)

        Devuelve `{can_book, can_walkin, reason, cancellations,
        blocked_by_cancellations, current}`.

        **El ORDEN de evaluación es parte del contrato**: la primera regla que
        falla es la que se reporta, así que un proceso inactivo **y** sin
        encuesta dice `proceso_inactivo`, no `sin_encuesta`. Reordenar la
        cadena le cambia el mensaje al alumno aunque las seis sigan estando.

        `can_walkin` **no es** `can_book`: pasa con las reglas 1 a 4 y la 5 NO
        lo apaga. El bloqueado por D9 perdió el derecho a *reservar un lugar*,
        no el de *presentarse* a una atención que el encargado anunció abierta
        a todos. Colgarlo de `can_book` le fabricaría un callejón sin salida —
        una pantalla que solo dice «pídele la cita a tu encargado» el mismo día
        en que su encargado atiende sin cita.

        `current` es la cita VIGENTE (`get_for_process`), que puede venir en
        `attended`, `no_show` o ninguna: solo los estados VIVOS disparan la
        regla 4.
        """
        from itcj2.apps.titulatec.models import TitulationProcess
        from itcj2.apps.titulatec.services.appointment_service import (
            _ESTADOS_ACTIVOS, AppointmentService,
        )
        from itcj2.apps.titulatec.services.survey_review_service import SurveyReviewService

        proc = db.get(TitulationProcess, int(process_id))
        if proc is None:
            # Fail-closed. No es una fila de la tabla de §3 porque no debería
            # pasar; se reporta como proceso inactivo en vez de reventar.
            return {"can_book": False, "can_walkin": False,
                    "reason": "proceso_inactivo", "cancellations": 0,
                    "blocked_by_cancellations": False, "current": None}

        current = AppointmentService.get_for_process(db, proc.id)
        cancelaciones = SelfBookingService.cancellations(db, proc)
        bloqueado = SelfBookingService.is_blocked_by_cancellations(db, proc)

        # Las 6 reglas de §3, EN ORDEN.
        reason = None
        if proc.status != "active":
            reason = "proceso_inactivo"
        elif SelfBookingService._fase_cotejo_aprobada(db, proc):
            reason = "fase_aprobada"
        elif SurveyReviewService.get_for_process(db, proc.id) is None:
            reason = "sin_encuesta"
        elif current is not None and current.status in _ESTADOS_ACTIVOS:
            reason = "tiene_cita"
        elif bloqueado:
            reason = "bloqueado_por_cancelaciones"

        return {
            "can_book": reason is None,
            # Reglas 1 a 4 sí lo apagan; la 5 no. Escrito como una sola
            # expresión para que no pueda divergir de `reason`.
            "can_walkin": reason in (None, "bloqueado_por_cancelaciones"),
            "reason": reason,
            "cancellations": cancelaciones,
            "blocked_by_cancellations": bloqueado,
            "current": current,
        }

    # ------------------------------------------------------------ §4.1: oferta
    @staticmethod
    def _owners_serving(db: Session, owner_ids: set, program_id: int | None) -> set:
        """De esos dueños, los que ATIENDEN esa carrera (D3).

        Es el predicado de alcance de `scope_service._program_ids_for_user`
        recorrido al revés (carrera -> encargados), y se resuelve **llamando a
        la función que ya existe** para cada dueño candidato, no reescribiendo
        su join (`ProgramPosition` ⋈ `Position` ⋈ `PositionAppRole` /
        `PositionAppPerm` ⋈ `UserPosition` con `_active_position_filter()`).
        Una segunda implementación de ese join diverge en tres meses y nadie se
        entera: el día que alguien añada una vía de asignación, el alcance del
        encargado la respetaría y la oferta del alumno no.

        El conjunto candidato es pequeño —solo los dueños de ventanas
        PUBLICADAS de esos días—, así que preguntar uno por uno sale barato.
        """
        from itcj2.apps.titulatec.services.scope_service import _program_ids_for_user

        if not owner_ids or not program_id:
            return set()
        return {uid for uid in owner_ids
                if program_id in _program_ids_for_user(db, uid)}

    @staticmethod
    def _offerable_windows(db: Session, proc, *, ahora: datetime) -> list:
        """`[(día, ventana)]` publicadas, vigentes y de la carrera del proceso.

        UN solo predicado para los dos consumidores: `offer`, que las pinta, y
        `_window_in_offer`, que revalida lo que llega del formulario. Si la
        oferta y la escritura usaran consultas distintas, un día divergen y el
        agujero se abre justo por el lado que nadie mira.

        **No filtra por franjas libres a propósito.** Una ventana llena sigue
        siendo «suya», y agendar en ella tiene que responder «esa franja se
        llenó hace un momento» (`SlotFull`, que refresca el tablero), no un 404
        de recurso ajeno.
        """
        from itcj2.apps.titulatec.models import CohortReviewDay, ReviewWindow

        if proc is None or proc.program_id is None:
            # Fail-closed, igual que el alcance del encargado: un proceso sin
            # carrera no cae en el conjunto de nadie (ver `scope_service`).
            return []
        dias = (db.query(CohortReviewDay)
                .filter(CohortReviewDay.cohort_id == proc.cohort_id,
                        CohortReviewDay.is_closed.is_(False),
                        CohortReviewDay.date >= ahora.date())
                .order_by(CohortReviewDay.date).all())
        if not dias:
            return []
        por_id = {d.id: d for d in dias}
        ventanas = (db.query(ReviewWindow)
                    .filter(ReviewWindow.review_day_id.in_(list(por_id)),
                            ReviewWindow.status == "open",
                            ReviewWindow.visibility.in_(_VISIBLES))
                    .order_by(ReviewWindow.start_time, ReviewWindow.id).all())
        if not ventanas:
            return []
        atienden = SelfBookingService._owners_serving(
            db, {w.owner_user_id for w in ventanas}, proc.program_id)
        return [(por_id[w.review_day_id], w) for w in ventanas
                if w.owner_user_id in atienden]

    @staticmethod
    def _min_bookable_at(ahora: datetime | None = None) -> datetime:
        """El primer instante reservable: `db_now() + MIN_LEAD` (D8)."""
        ahora = ahora or db_now()
        return ahora + timedelta(
            minutes=SelfBookingService._settings().TITULATEC_SELF_BOOK_MIN_LEAD_MINUTES)

    @staticmethod
    def _offerable_slots(db: Session, window, *, ahora: datetime | None = None) -> list:
        """Franjas LIBRES de una ventana `bookable` que todavía admiten reserva.

        Mismo corte que usa `book`, a propósito: si la oferta pintara una
        franja que la escritura va a rechazar, el egresado pulsaría un botón
        que siempre falla y no sabría por qué.
        """
        from itcj2.apps.titulatec.services.slot_service import SlotService

        ahora = ahora or db_now()
        minimo = SelfBookingService._min_bookable_at(ahora)
        dia = window.review_day.date
        return [h for h in SlotService.free_slots(db, window)
                if datetime.combine(dia, h) >= minimo]

    @staticmethod
    def offer(db: Session, process_id: int) -> list[dict]:
        """Los días y espacios ofrecibles, por día y dentro del día por encargado.

        Forma::

            [{"date": date,
              "owners": [{"owner_id": int, "owner_name": str,
                          "windows": [{"window_id", "visibility",
                                       "start_time", "end_time",
                                       "location", "slots": [time, ...]}]}]}]

        Es el CATÁLOGO, no la puerta: quién puede reservar lo decide
        `eligibility`, y los dos se consumen juntos en la pantalla del alumno.
        Por eso la oferta incluye los `walkin` aunque el alumno esté bloqueado
        por D9: puede presentarse aunque no pueda reservar.

        Las `walkin` viajan **sin franjas**, como anuncio (D2: no crean ningún
        registro; el alumno llega y el encargado lo atiende desde su cola). Una
        `bookable` sin franjas ofrecibles se omite: no es oferta, es ruido.
        """
        from itcj2.apps.titulatec.models import TitulationProcess
        from itcj2.core.models.user import User

        proc = db.get(TitulationProcess, int(process_id))
        ahora = db_now()
        pares = SelfBookingService._offerable_windows(db, proc, ahora=ahora)
        if not pares:
            return []

        duenos = {w.owner_user_id for _, w in pares}
        nombres = {u.id: u for u in
                   db.query(User).filter(User.id.in_(duenos)).all()}

        por_dia: dict = {}
        for dia, w in pares:
            item = {"window_id": w.id, "visibility": w.visibility,
                    "start_time": w.start_time, "end_time": w.end_time,
                    "location": w.location, "slots": []}
            if w.visibility == "bookable":
                item["slots"] = SelfBookingService._offerable_slots(db, w, ahora=ahora)
                if not item["slots"]:
                    continue
            por_dia.setdefault(dia.date, {}).setdefault(w.owner_user_id, []).append(item)

        salida = []
        for fecha in sorted(por_dia):
            grupos = por_dia[fecha]
            orden = sorted(grupos, key=lambda uid: _nombre(nombres.get(uid)))
            salida.append({
                "date": fecha,
                "owners": [{"owner_id": uid,
                            "owner_name": _nombre(nombres.get(uid)),
                            "windows": grupos[uid]} for uid in orden],
            })
        return salida

    # ------------------------------------------------------------ §4.1: agendar
    @staticmethod
    def _window_in_offer(db: Session, process_id: int, window_id):
        """La ventana **agendable** de la oferta de ESE proceso, o None.

        **Control de seguridad crítico de la spec.** `window_id` llega en el
        cuerpo del formulario, no en la ruta, así que el regresor estructural
        `test_scope_guard.py` —que barre las rutas con `{process_id}`— no lo
        ve. Sin esta revalidación, un egresado se sienta en la ventana de
        cualquier encargado de cualquier carrera cambiando un número; es la
        misma clase de agujero que dejó abierto el reparto masivo.

        Se revalida contra el proceso del usuario autenticado, jamás contra un
        id que venga del formulario, y `walkin` queda fuera: es un anuncio, no
        una agenda (D2).
        """
        from itcj2.apps.titulatec.models import TitulationProcess

        if not window_id:
            return None
        proc = db.get(TitulationProcess, int(process_id))
        wid = int(window_id)
        for _dia, w in SelfBookingService._offerable_windows(db, proc, ahora=db_now()):
            if w.id == wid and w.visibility == "bookable":
                return w
        return None

    @staticmethod
    def book(db: Session, process_id: int, window_id, slot_start, actor_id: int):
        """El egresado toma una franja. Dueña de la transacción.

        El orden importa (§4.1):

        1. `eligibility` se re-verifica **aquí dentro**, no antes: lo que pintó
           la UI es informativo y pudo quedarse rancio.
        2. La ventana tiene que existir, estar `open`, ser `bookable` y
           pertenecer a la oferta de ESTE proceso (`_window_in_offer`).
        3. La anticipación mínima se mide contra `db_now()` (D8).
        4. Se delega en `AppointmentService.create(..., booked_by='student')`,
           que aporta las guardas duras —encuesta enviada, día habilitado,
           franja real, cupo, lock de ventana y advisory lock del proceso, con
           la re-comprobación de D4 DENTRO del lock que cierra el TOCTOU del
           doble clic—. **No se reimplementan aquí.**
        5. No notifica a nadie: al alumno porque acaba de pulsar el botón
           (`create` lo calla cuando el actor es el propio alumno) y al
           encargado porque D11 dice que se entera por su tablero.
        """
        from itcj2.apps.titulatec.services.appointment_errors import MissingSchedule
        from itcj2.apps.titulatec.services.appointment_service import AppointmentService

        elig = SelfBookingService.eligibility(db, process_id)
        if not elig["can_book"]:
            raise SelfBookingNotAllowed(
                elig["reason"],
                SelfBookingService.message_for(elig["reason"],
                                               cancellations=elig["cancellations"]))

        ventana = SelfBookingService._window_in_offer(db, process_id, window_id)
        if ventana is None:
            raise NotYours("Ese espacio ya no está disponible para agendar.")

        if slot_start is None:
            raise MissingSchedule()

        minutos = SelfBookingService._settings().TITULATEC_SELF_BOOK_MIN_LEAD_MINUTES
        cuando = datetime.combine(ventana.review_day.date, slot_start)
        if cuando < SelfBookingService._min_bookable_at():
            raise SlotTooSoon(minutos)

        return AppointmentService.create(
            db, process_id, window_id=ventana.id, slot_start=slot_start,
            created_by_id=actor_id, booked_by="student")

    # ----------------------------------------------------------- §4.1: cancelar
    @staticmethod
    def cancel(db: Session, appt, actor_id: int, reason: str | None = None):
        """El egresado cancela su propia cita. Dueña de la transacción.

        **Envuelve** a `AppointmentService.cancel`, no la duplica (D13). Lo
        único propio de esta capa son dos cosas:

        * que la cita sea SUYA (defensa en profundidad: la ruta ya resuelve el
          proceso del usuario autenticado, pero el service no confía en eso);
        * la ventana de 2 h de D8.

        Todo lo demás —que el estado admita la cancelación, el sellado de
        `cancelled_at` / `cancelled_by_id` / `cancel_reason`, el
        `ProcessEvent`, dejar la fila fuera de vigencia y devolver la franja al
        pozo (D12)— es de la capa compartida, que también usa el encargado. El
        encargado no pasa por aquí y por eso no tiene ventana de tiempo.

        Tampoco notifica: `AppointmentService.cancel` avisa al alumno salvo que
        el actor sea él mismo, y aquí el actor es siempre él.
        """
        from itcj2.apps.titulatec.models import TitulationProcess
        from itcj2.apps.titulatec.services.appointment_service import AppointmentService

        proc = db.get(TitulationProcess, appt.process_id)
        if proc is None or int(actor_id) != int(proc.student_id):
            raise NotYours("Esa cita no es tuya.")

        minutos = SelfBookingService._settings().TITULATEC_SELF_CANCEL_MIN_LEAD_MINUTES
        # Spec, literal: puede cancelar mientras
        # `db_now() <= scheduled_at - MIN_LEAD`.
        if db_now() > appt.scheduled_at - timedelta(minutes=minutos):
            raise CancelTooLate(minutos)

        return AppointmentService.cancel(db, appt, actor_id, reason)
