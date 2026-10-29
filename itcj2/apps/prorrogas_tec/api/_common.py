"""Piezas compartidas por las APIs de Prórrogas."""
from fastapi.responses import JSONResponse

from itcj2.apps.prorrogas_tec.services.errors import ServiceError


def error_response(status: int, code: str, message: str, **detail) -> JSONResponse:
    """Error en la raíz del JSON: ``{"error", "message", ...detalle}``."""
    return JSONResponse(status_code=status, content={"error": code, "message": message, **detail})


def service_error_response(e: ServiceError) -> JSONResponse:
    return error_response(e.status, e.code, e.message, **e.detail)
