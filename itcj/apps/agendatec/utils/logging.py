# utils/logging.py
"""
Módulo de logging estructurado para AgendaTec.

Proporciona un logger con contexto enriquecido para operaciones críticas,
usando el sistema de logging estándar de Python con formateo estructurado.
"""
from __future__ import annotations

import logging
import json
from contextvars import ContextVar
from datetime import datetime
from functools import wraps
from typing import Any, Callable, Optional

# Context variables para datos de contexto
_request_id_var: ContextVar[Optional[str]] = ContextVar("request_id", default=None)
_user_id_var: ContextVar[Optional[int]] = ContextVar("user_id", default=None)
_operation_var: ContextVar[Optional[str]] = ContextVar("operation", default=None)


class StructuredFormatter(logging.Formatter):
    """
    Formatter que produce logs en formato JSON estructurado.
    
    Incluye automáticamente:
    - timestamp: Marca de tiempo ISO
    - level: Nivel del log
    - message: Mensaje principal
    - logger: Nombre del logger
    - Contexto adicional (request_id, user_id, operation)
    """

    def format(self, record: logging.LogRecord) -> str:
        """Formatea el registro como JSON estructurado."""
        log_entry = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Añadir contexto de context vars
        request_id = _request_id_var.get()
        user_id = _user_id_var.get()
        operation = _operation_var.get()

        if request_id:
            log_entry["request_id"] = request_id
        if user_id:
            log_entry["user_id"] = user_id
        if operation:
            log_entry["operation"] = operation

        # Añadir campos extra del record
        if hasattr(record, "extra_data") and record.extra_data:
            log_entry["data"] = record.extra_data

        # Añadir información de excepción si existe
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)

        # Añadir ubicación del código
        log_entry["location"] = f"{record.filename}:{record.lineno}"

        return json.dumps(log_entry, ensure_ascii=False, default=str)


class ContextLogger:
    """
    Logger con soporte para contexto estructurado.
    
    Envuelve el logger estándar añadiendo métodos para incluir
    datos adicionales en los logs de forma estructurada.
    """

    def __init__(self, name: str):
        """
        Inicializa el logger.
        
        Args:
            name: Nombre del logger (típicamente __name__).
        """
        self._logger = logging.getLogger(name)

    def _log(
        self,
        level: int,
        msg: str,
        *args,
        extra_data: Optional[dict] = None,
        **kwargs,
    ) -> None:
        """Log interno con datos extra."""
        extra = kwargs.pop("extra", {})
        extra["extra_data"] = extra_data
        self._logger.log(level, msg, *args, extra=extra, **kwargs)

    def debug(self, msg: str, *args, **kwargs) -> None:
        """Log a nivel DEBUG."""
        self._log(logging.DEBUG, msg, *args, **kwargs)

    def info(self, msg: str, *args, **kwargs) -> None:
        """Log a nivel INFO."""
        self._log(logging.INFO, msg, *args, **kwargs)

    def warning(self, msg: str, *args, **kwargs) -> None:
        """Log a nivel WARNING."""
        self._log(logging.WARNING, msg, *args, **kwargs)

    def error(self, msg: str, *args, **kwargs) -> None:
        """Log a nivel ERROR."""
        self._log(logging.ERROR, msg, *args, **kwargs)

    def exception(self, msg: str, *args, **kwargs) -> None:
        """Log a nivel ERROR con información de excepción."""
        kwargs["exc_info"] = True
        self._log(logging.ERROR, msg, *args, **kwargs)

    def bind(self, **context) -> "BoundLogger":
        """
        Crea un logger con contexto adicional vinculado.
        
        Args:
            **context: Pares clave-valor para añadir al contexto.
            
        Returns:
            BoundLogger con el contexto vinculado.
        """
        return BoundLogger(self, context)


class BoundLogger:
    """Logger con contexto predefinido."""

    def __init__(self, parent: ContextLogger, context: dict):
        """
        Inicializa el bound logger.
        
        Args:
            parent: Logger padre.
            context: Diccionario de contexto a incluir en todos los logs.
        """
        self._parent = parent
        self._context = context

    def _merge_context(self, extra_data: Optional[dict]) -> dict:
        """Combina el contexto vinculado con datos adicionales."""
        merged = dict(self._context)
        if extra_data:
            merged.update(extra_data)
        return merged

    def debug(self, msg: str, *args, extra_data: Optional[dict] = None, **kwargs) -> None:
        """Log a nivel DEBUG con contexto."""
        self._parent.debug(msg, *args, extra_data=self._merge_context(extra_data), **kwargs)

    def info(self, msg: str, *args, extra_data: Optional[dict] = None, **kwargs) -> None:
        """Log a nivel INFO con contexto."""
        self._parent.info(msg, *args, extra_data=self._merge_context(extra_data), **kwargs)

    def warning(self, msg: str, *args, extra_data: Optional[dict] = None, **kwargs) -> None:
        """Log a nivel WARNING con contexto."""
        self._parent.warning(msg, *args, extra_data=self._merge_context(extra_data), **kwargs)

    def error(self, msg: str, *args, extra_data: Optional[dict] = None, **kwargs) -> None:
        """Log a nivel ERROR con contexto."""
        self._parent.error(msg, *args, extra_data=self._merge_context(extra_data), **kwargs)

    def exception(self, msg: str, *args, extra_data: Optional[dict] = None, **kwargs) -> None:
        """Log a nivel ERROR con información de excepción."""
        self._parent.exception(msg, *args, extra_data=self._merge_context(extra_data), **kwargs)

    def bind(self, **context) -> "BoundLogger":
        """
        Crea un nuevo BoundLogger con contexto adicional.
        
        Args:
            **context: Pares clave-valor para añadir al contexto existente.
            
        Returns:
            Nuevo BoundLogger con el contexto combinado.
        """
        merged_context = dict(self._context)
        merged_context.update(context)
        return BoundLogger(self._parent, merged_context)


# ═══════════════════════════════════════════════════════════════════════════════
# FUNCIONES DE CONTEXTO
# ═══════════════════════════════════════════════════════════════════════════════


def set_request_context(request_id: Optional[str] = None, user_id: Optional[int] = None) -> None:
    """
    Establece el contexto de la solicitud actual.
    
    Args:
        request_id: ID único de la solicitud HTTP.
        user_id: ID del usuario autenticado.
    """
    if request_id:
        _request_id_var.set(request_id)
    if user_id:
        _user_id_var.set(user_id)


def set_operation_context(operation: str) -> None:
    """
    Establece el contexto de la operación actual.
    
    Args:
        operation: Nombre de la operación (ej: "create_request", "cancel_appointment").
    """
    _operation_var.set(operation)


def clear_context() -> None:
    """Limpia todo el contexto de logging."""
    _request_id_var.set(None)
    _user_id_var.set(None)
    _operation_var.set(None)


def with_logging_context(**context):
    """
    Decorador para establecer contexto de logging en una función.
    
    Args:
        **context: Contexto a establecer (operation, etc.).
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            if "operation" in context:
                set_operation_context(context["operation"])
            try:
                return func(*args, **kwargs)
            finally:
                if "operation" in context:
                    _operation_var.set(None)
        return wrapper
    return decorator


# ═══════════════════════════════════════════════════════════════════════════════
# FACTORY FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════


def get_logger(name: str) -> ContextLogger:
    """
    Obtiene un logger estructurado.
    
    Args:
        name: Nombre del logger (usar __name__).
        
    Returns:
        ContextLogger configurado.
    """
    return ContextLogger(name)


def configure_structured_logging(app_logger: logging.Logger, level: int = logging.INFO) -> None:
    """
    Configura el logging estructurado para la aplicación.
    
    Args:
        app_logger: Logger de la aplicación Flask.
        level: Nivel de logging.
    """
    handler = logging.StreamHandler()
    handler.setFormatter(StructuredFormatter())
    handler.setLevel(level)

    # Limpiar handlers existentes y añadir el nuevo
    app_logger.handlers.clear()
    app_logger.addHandler(handler)
    app_logger.setLevel(level)


# ═══════════════════════════════════════════════════════════════════════════════
# LOGGER PRE-CONFIGURADO PARA AGENDATEC
# ═══════════════════════════════════════════════════════════════════════════════

# Logger principal para el módulo AgendaTec
logger = get_logger("agendatec")
