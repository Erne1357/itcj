"""Reloj único para timestamps que se guardan en base de datos.

Postgres corre con `timezone = America/Ciudad_Juarez`, así que todos los
`server_default=func.now()` / `text("NOW()")` de los modelos escriben hora
LOCAL. `datetime.utcnow()` escribe UTC: seis horas adelantado. Como ambos son
naive, mezclarlos no lanza ningún error — simplemente produce timestamps
corridos y ventanas de consulta desplazadas, en silencio.

`db_now()` devuelve exactamente lo que escribiría la base: hora local **naive**.
Es el reemplazo directo de `utcnow()` en cualquier valor que se persista o que
se compare contra una columna de fecha.

Las apps helpdesk y maint ya tienen su propio `timezone_utils.now_local()`, que
devuelve un datetime *aware*; sirve para presentación. Este vive en core para
que `tasks/`, `cli/`, `core/` y las apps sin util propio no tengan que importar
de otra app.
"""
import os
from datetime import datetime
from zoneinfo import ZoneInfo

APP_TIMEZONE = os.getenv("APP_TZ", "America/Ciudad_Juarez")


def db_now() -> datetime:
    """Hora local naive, idéntica a la que produce `NOW()` en Postgres."""
    return datetime.now(ZoneInfo(APP_TIMEZONE)).replace(tzinfo=None)
