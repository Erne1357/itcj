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
    """Lo garantiza `ON DELETE RESTRICT`; aquí solo se traduce a español."""

    def __init__(self, n: int):
        plural = "s" if n != 1 else ""
        super().__init__(
            f"Este espacio tiene {n} cita{plural}. Muévelas o cámbialo a «En pausa».")


class DuplicateWindowStart(AppointmentError):
    def __init__(self, msg="Ya tienes un espacio que empieza a esa hora ese día."):
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
