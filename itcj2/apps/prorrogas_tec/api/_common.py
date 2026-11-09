"""Piezas compartidas por las APIs de Prórrogas."""
from fastapi.responses import JSONResponse, Response

from itcj2.apps.prorrogas_tec.services.errors import ServiceError


def error_response(status: int, code: str, message: str, **detail) -> JSONResponse:
    """Error en la raíz del JSON: ``{"error", "message", ...detalle}``."""
    return JSONResponse(status_code=status, content={"error": code, "message": message, **detail})


def service_error_response(e: ServiceError) -> JSONResponse:
    return error_response(e.status, e.code, e.message, **e.detail)


def recibo_pdf_response(db, req, numero: int) -> Response:
    """PDF del recibo escaneado de una parcialidad; `req` ya viene filtrada por dueño (o es None)."""
    from itcj2.apps.prorrogas_tec.services.receipt_scan_service import ReceiptScanService
    try:
        if req is None:
            raise ServiceError("no_encontrada", "No se encontró el recibo.", status=404)
        data = ReceiptScanService.read(db, req, numero)
    except ServiceError:
        return error_response(404, "no_encontrada", "No se encontró el recibo.")
    return Response(data, media_type="application/pdf",
                    headers={"Content-Disposition": 'inline; filename="recibo.pdf"'})
