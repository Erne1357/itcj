"""
Utilidades compartidas para itcj2 (FastAPI).
"""
from werkzeug.exceptions import HTTPException as WerkzeugHTTPException
from fastapi import HTTPException


def flask_service_call(fn, *args, **kwargs):
    """Wrapper que captura abort() de Flask y lo relanza como FastAPI HTTPException.

    Los servicios de helpdesk usan ``flask.abort()`` que lanza
    ``werkzeug.exceptions.HTTPException``.  Este wrapper lo convierte
    al equivalente de FastAPI para que el middleware de errores lo maneje.
    """
    try:
        return fn(*args, **kwargs)
    except WerkzeugHTTPException as e:
        raise HTTPException(status_code=e.code, detail=e.description)
