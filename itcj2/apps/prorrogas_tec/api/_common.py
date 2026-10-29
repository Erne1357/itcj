"""Piezas compartidas por las APIs de Prórrogas."""
from fastapi.responses import JSONResponse


def error_response(status: int, code: str, message: str, **detail) -> JSONResponse:
    """Error en la raíz del JSON: ``{"error", "message", ...detalle}``."""
    return JSONResponse(status_code=status, content={"error": code, "message": message, **detail})
