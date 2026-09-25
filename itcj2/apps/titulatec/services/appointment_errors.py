"""Errores de dominio de la agenda de cotejo.

``str(e)`` es **el mensaje que ve el usuario**: viaja tal cual en el header
``X-Tt-Error`` y de ahí al toast. Escríbelos en español de ventanilla, sin em
dashes, diciendo qué hacer.

Error de entrada contra colisión de estado
------------------------------------------
htmx **no swappea en 4xx**. Si un cupo lleno respondiera 409, el encargado se
quedaría mirando un tablero rancio que sigue pintando libre el asiento que otro
acaba de ocupar: el error se ve, pero la pantalla miente.

Por eso hay dos familias:

* **Entrada del usuario** (falta la fecha, el día no está habilitado, la hora no
  cae en la rejilla) → 400 + ``X-Tt-Error``. No hay nada que refrescar: lo que
  hay en pantalla sigue siendo verdad.
* **Colisión de estado** (otro encargado ganó la franja, la cita ya cambió de
  estado) → **200 con el cuerpo re-renderizado**, que ya trae la realidad nueva,
  más el mensaje aparte. Lo marca ``refresca_la_vista = True``.
"""


class AppointmentError(Exception):
    """Base. `refresca_la_vista` decide 200-con-cuerpo-fresco contra 400."""

    refresca_la_vista = False


# --------------------------------------------------------------------------
# Entrada del usuario: 400 + X-Tt-Error
# --------------------------------------------------------------------------
class MissingSchedule(AppointmentError):
    """Falta la ventana o la franja.

    Antes esto era un `if dt:` que devolvía 200 con el cuerpo re-renderizado y
    **no creaba nada**: el encargado pulsaba «Agendar», la pantalla parpadeaba y
    no pasaba nada, sin un solo mensaje. Reproducido el 2026-09-03: HTTP 200,
    sin `X-Tt-Error`, cero filas.
    """

    def __init__(self, msg="Falta la fecha o la franja de la cita."):
        super().__init__(msg)


class DayNotAllowed(AppointmentError):
    def __init__(self, msg="Esa fecha no está habilitada para cotejo."):
        super().__init__(msg)


class InvalidSlot(AppointmentError):
    def __init__(self, msg="Esa hora no es una franja de ese espacio."):
        super().__init__(msg)


class WindowShrinkConflict(AppointmentError):
    """Reducir un espacio no puede dejar citas fuera en silencio."""

    def __init__(self, n: int):
        plural = "s" if n != 1 else ""
        verbo = "n" if n != 1 else ""
        super().__init__(
            f"{n} cita{plural} quedaría{verbo} fuera del horario nuevo. "
            f"Muévelas antes de reducirlo.")


class WindowOverlap(AppointmentError):
    def __init__(self, msg="Ya tienes un espacio que se encima con ese horario ese día."):
        super().__init__(msg)


class WindowInUse(AppointmentError):
    """Lo garantiza `ON DELETE RESTRICT`; aquí solo se traduce a español.

    Dos mensajes, porque son dos situaciones distintas y al encargado no le
    toca lo mismo en cada una. Con citas VIVAS puede moverlas y entonces sí
    borrar el espacio. Con solo historial muerto (canceladas o superadas) no
    hay nada que mover, y la FK `fk_titulatec_review_appointments_window` es
    `ON DELETE RESTRICT`, así que Postgres va a seguir rechazando el DELETE
    pase lo que pase: la única salida real es pausarlo. Darle el mensaje de
    «muévelas» lo manda a buscar en el tablero citas que ya no están ahí.
    """

    def __init__(self, n: int, *, solo_historial: bool = False):
        if solo_historial:
            super().__init__(
                "Este espacio ya no tiene citas activas, pero conserva el "
                "historial de intentos anteriores. Cámbialo a «En pausa»: "
                "borrarlo perdería ese registro.")
            return
        plural = "s" if n != 1 else ""
        super().__init__(
            f"Este espacio tiene {n} cita{plural}. Muévelas o cámbialo a «En pausa».")


class DuplicateWindowStart(AppointmentError):
    def __init__(self, msg="Ya tienes un espacio que empieza a esa hora ese día."):
        super().__init__(msg)


class SurveyNotSubmitted(AppointmentError):
    """El alumno no ha enviado la encuesta de egresados (D2).

    Guarda dura de `AppointmentService.create`, ANTES que cualquier otra
    validación: hace falta la solicitud (`SurveyReview`), no que GTV ya la
    haya liberado. Servicios Escolares puede agendar mientras GTV sigue
    revisando en paralelo; lo único que bloquea es no haberla enviado.
    """

    def __init__(self, msg="El alumno todavía no envía la encuesta de egresados. "
                           "Sin ella no se puede agendar."):
        super().__init__(msg)


def _lapso(minutos: int) -> str:
    """'1 hora' / '2 horas' / '45 minutos'. Las ventanas de D8 son
    configurables, así que el mensaje no puede llevar el número a mano."""
    if minutos % 60 == 0:
        horas = minutos // 60
        return "1 hora" if horas == 1 else f"{horas} horas"
    return f"{minutos} minutos"


class SelfBookingNotAllowed(AppointmentError):
    """El egresado no cumple una de las 6 reglas de elegibilidad (spec §3).

    Lleva `reason` —el mismo código que devuelve
    `SelfBookingService.eligibility`— para que la ruta pueda distinguirlas sin
    leer el texto. El mensaje lo pone quien la levanta, desde la tabla de §3
    (`SelfBookingService.message_for`): la copia vive con las reglas, no aquí,
    o habría dos sitios que decirle al alumno por qué no puede.

    `tiene_cita` es la única que refresca la vista: es lo que produce un doble
    clic en «Agendar», y ahí la pantalla ESTÁ rancia — ya existe una cita que
    el alumno no está viendo. Las demás son estados estables: lo que hay en
    pantalla sigue siendo verdad y solo falta el mensaje.
    """

    def __init__(self, reason: str, msg: str | None = None):
        super().__init__(msg or "Ahora mismo no puedes agendar tu cita de cotejo.")
        self.reason = reason
        self.refresca_la_vista = reason == "tiene_cita"


class SlotTooSoon(AppointmentError):
    """D8: el egresado agenda hasta `TITULATEC_SELF_BOOK_MIN_LEAD_MINUTES` antes."""

    def __init__(self, minutos: int = 60):
        super().__init__(f"Esa franja empieza en menos de {_lapso(minutos)}. "
                         f"Elige una más adelante.")


class CancelTooLate(AppointmentError):
    """D8: el egresado cancela hasta `TITULATEC_SELF_CANCEL_MIN_LEAD_MINUTES` antes.

    El encargado NO pasa por aquí: su `cancel` no tiene ventana de tiempo.
    """

    def __init__(self, minutos: int = 120):
        super().__init__(f"Ya faltan menos de {_lapso(minutos)} para tu cita, así que "
                         f"ya no puedes cancelarla. Avisa a tu encargado de carrera.")


class NotYours(AppointmentError):
    """El recurso no es de este egresado: ventana fuera de su oferta, o cita
    de otro proceso.

    **La ruta responde 404 limpio, SIN `X-Tt-Error`**, por la misma razón que
    `scope_service.assert_process_in_scope`: los ids son enteros secuenciales
    y un 403 (o un mensaje distintivo) confirmaría que el id existe. Por eso
    `str(e)` de esta familia casi nunca se enseña — está para el log.
    """

    def __init__(self, msg="Eso ya no está disponible."):
        super().__init__(msg)


# --------------------------------------------------------------------------
# Colisión de estado: 200 con el cuerpo fresco
# --------------------------------------------------------------------------
class SlotFull(AppointmentError):
    refresca_la_vista = True

    def __init__(self, msg="Esa franja se llenó hace un momento. Elige otro lugar."):
        super().__init__(msg)


class InvalidTransition(AppointmentError):
    refresca_la_vista = True

    def __init__(self, desde=None, hacia=None, msg=None):
        super().__init__(msg or _texto_transicion(desde, hacia))
        self.desde = desde
        self.hacia = hacia


class AppointmentConflict(AppointmentError):
    """El proceso ya tiene una cita ACTIVA y se intento abrir otra (D4).

    No es una `InvalidTransition`: con el historial de intentos, agendar sobre
    una cita que ya no esta viva (`attended` con faltantes -D5-, `no_show`
    -D7-, `cancelled` -D6-) es legitimo y crea una fila nueva. Lo unico que se
    rechaza es duplicar una cita VIVA, y eso no es un salto de estado invalido
    sino un choque: por eso tiene error propio y mensaje propio.
    """

    refresca_la_vista = True

    def __init__(self, msg="Ese alumno ya tiene una cita activa. "
                           "Muévela o cancélala antes de agendar otra."):
        super().__init__(msg)


class EnrollmentRevoked(AppointmentError):
    """El proceso quedó `cancelled` (`ProcessService.cancel`): no se le agenda.

    Colisión de estado, no error de entrada: el caso real es un tablero abierto
    desde antes de la revocación que todavía pinta al alumno. Re-renderizar
    le quita la fila de la vista.
    """

    refresca_la_vista = True

    def __init__(self, msg="La inscripción de este alumno fue revocada: ya no se le agenda cita."):
        super().__init__(msg)


class SlotLockTimeout(AppointmentError):
    refresca_la_vista = True

    def __init__(self, msg="Otro encargado está agendando en ese espacio. Vuelve a intentar."):
        super().__init__(msg)


def _texto_transicion(desde, hacia) -> str:
    if desde == "attended":
        return "Esa cita ya está marcada como asistió; no se puede cambiar."
    if desde == "no_show" and hacia == "attended":
        return ("Esa cita quedó como «no se presentó». Usa «Deshacer no se presentó» "
                "antes de atenderla.")
    return "Esa cita ya cambió de estado. Revisa cómo quedó."
