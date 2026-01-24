"""
Helpers de respuesta para APIs de AgendaTec.

Este módulo proporciona funciones estandarizadas para generar respuestas
JSON consistentes en todos los endpoints de la API.
"""
from typing import Any, Optional
from flask import jsonify


def api_error(
    code: str,
    message: Optional[str] = None,
    status: int = 400,
    **extra: Any
) -> tuple:
    """
    Genera una respuesta de error estandarizada para la API.

    Args:
        code: Código de error identificador (ej: "not_found", "validation_error")
        message: Mensaje descriptivo del error (opcional, para mostrar al usuario)
        status: Código HTTP de respuesta (default: 400)
        **extra: Campos adicionales a incluir en la respuesta

    Returns:
        Tupla (Response, status_code) lista para retornar desde un endpoint Flask

    Examples:
        >>> return api_error("not_found", "Usuario no encontrado", 404)
        >>> return api_error("validation_error", "Campos inválidos", 400, fields=["email", "name"])
        >>> return api_error("slot_unavailable", status=409)
    """
    payload = {
        "error": code,
        "status": status,
    }
    if message:
        payload["message"] = message
    payload.update(extra)
    return jsonify(payload), status


def api_success(
    data: Optional[dict] = None,
    message: Optional[str] = None,
    status: int = 200,
    **extra: Any
) -> tuple:
    """
    Genera una respuesta de éxito estandarizada para la API.

    Args:
        data: Diccionario con los datos de respuesta (opcional)
        message: Mensaje de éxito (opcional)
        status: Código HTTP de respuesta (default: 200)
        **extra: Campos adicionales a incluir en la respuesta

    Returns:
        Tupla (Response, status_code) lista para retornar desde un endpoint Flask

    Examples:
        >>> return api_success({"user_id": 123}, "Usuario creado", 201)
        >>> return api_success(data={"items": [...]})
    """
    payload = {"ok": True}
    if message:
        payload["message"] = message
    if data:
        payload.update(data)
    payload.update(extra)
    return jsonify(payload), status


def api_created(data: Optional[dict] = None, message: Optional[str] = None, **extra: Any) -> tuple:
    """
    Respuesta para recursos creados exitosamente (HTTP 201).

    Args:
        data: Datos del recurso creado
        message: Mensaje descriptivo
        **extra: Campos adicionales

    Returns:
        Tupla (Response, 201)
    """
    return api_success(data=data, message=message, status=201, **extra)


def api_deleted(message: str = "Recurso eliminado", **extra: Any) -> tuple:
    """
    Respuesta para recursos eliminados exitosamente (HTTP 200).

    Args:
        message: Mensaje de confirmación
        **extra: Campos adicionales

    Returns:
        Tupla (Response, 200)
    """
    return api_success(message=message, **extra)


def api_not_found(resource: str = "Recurso", message: Optional[str] = None) -> tuple:
    """
    Respuesta para recursos no encontrados (HTTP 404).

    Args:
        resource: Nombre del recurso no encontrado
        message: Mensaje personalizado (si no se proporciona, se genera uno)

    Returns:
        Tupla (Response, 404)
    """
    msg = message or f"{resource} no encontrado"
    return api_error("not_found", msg, 404)


def api_forbidden(message: str = "No tienes permisos para realizar esta acción") -> tuple:
    """
    Respuesta para acciones no permitidas (HTTP 403).

    Args:
        message: Mensaje descriptivo del error de permisos

    Returns:
        Tupla (Response, 403)
    """
    return api_error("forbidden", message, 403)


def api_conflict(code: str = "conflict", message: Optional[str] = None, **extra: Any) -> tuple:
    """
    Respuesta para conflictos de recursos (HTTP 409).

    Args:
        code: Código específico del conflicto
        message: Descripción del conflicto
        **extra: Campos adicionales (ej: existing_id)

    Returns:
        Tupla (Response, 409)
    """
    return api_error(code, message, 409, **extra)


def api_validation_error(
    message: str = "Error de validación",
    fields: Optional[list] = None,
    **extra: Any
) -> tuple:
    """
    Respuesta para errores de validación (HTTP 400).

    Args:
        message: Descripción general del error
        fields: Lista de campos con errores
        **extra: Campos adicionales

    Returns:
        Tupla (Response, 400)
    """
    kwargs = extra
    if fields:
        kwargs["fields"] = fields
    return api_error("validation_error", message, 400, **kwargs)


def api_service_unavailable(message: str = "Servicio no disponible") -> tuple:
    """
    Respuesta para servicios no disponibles (HTTP 503).

    Útil cuando dependencias externas no están disponibles
    (ej: no hay período activo, servicio externo caído).

    Args:
        message: Descripción del problema

    Returns:
        Tupla (Response, 503)
    """
    return api_error("service_unavailable", message, 503)


# Alias comunes para errores frecuentes
def api_invalid_payload(message: str = "Payload inválido") -> tuple:
    """Respuesta para payloads malformados (HTTP 400)."""
    return api_error("invalid_payload", message, 400)


def api_missing_fields(fields: list, message: str = "Campos requeridos faltantes") -> tuple:
    """Respuesta para campos faltantes (HTTP 400)."""
    return api_error("missing_fields", message, 400, required=fields)


def api_invalid_status(
    current: Optional[str] = None,
    allowed: Optional[list] = None
) -> tuple:
    """Respuesta para transiciones de estado inválidas (HTTP 400)."""
    extra = {}
    if current:
        extra["current_status"] = current
    if allowed:
        extra["allowed_statuses"] = allowed
    return api_error("invalid_status", "Estado inválido", 400, **extra)


def api_period_required(message: str = "No hay un período académico activo") -> tuple:
    """Respuesta cuando se requiere un período activo (HTTP 503)."""
    return api_error("no_active_period", message, 503)
