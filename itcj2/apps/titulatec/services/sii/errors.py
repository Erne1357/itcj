"""Errores del conector y del motor de reglas del SII.

Regla de oro (spec 2026-09-25 §3.1 y §5): el MENSAJE de estas excepciones
puede terminar en un log, en `titulatec_eligibility_checks.error` y en la
bandeja de Servicios Escolares. Por eso nunca lleva la cadena de conexión
(`PWD=…`), ni el NIP, ni filas crudas del SII: quien las lanza arma un texto
ya saneado y las re-lanza `from None` para que el traceback no arrastre la
excepción original del driver.
"""


class SiiError(Exception):
    """Base de todo lo que puede salir mal al hablar con el SII."""


class SiiUnavailable(SiiError):
    """El SII no se pudo consultar: deshabilitado, sin driver, sin conexión o
    timeout. Es REINTENTABLE (la tarea de celery reintenta con backoff)."""


class SiiQueryError(SiiError):
    """El SII respondió, pero la consulta es inválida (SQL roto, tabla o
    columna inexistente del lado del SII). Reintentar no lo arregla."""


class SiiRulesError(SiiError):
    """`rules.toml` o sus `.sql` no se pueden cargar o no son válidos."""
