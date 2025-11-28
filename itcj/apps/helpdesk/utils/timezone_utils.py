import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from typing import Optional

# Obtener timezone de las variables de entorno
APP_TIMEZONE = os.getenv('APP_TZ', 'America/Ciudad_Juarez')

def get_local_timezone():
    """Obtiene la timezone local configurada en APP_TZ"""
    return ZoneInfo(APP_TIMEZONE)

def now_local() -> datetime:
    """Obtiene la fecha/hora actual en la timezone local"""
    return datetime.now(get_local_timezone())

def utc_to_local(dt: datetime) -> datetime:
    """Convierte una fecha UTC a timezone local (solo para migración de datos existentes)"""
    if dt is None:
        return None
    
    # Si no tiene timezone, asumimos que es UTC
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    
    return dt.astimezone(get_local_timezone())

def to_local_or_naive(dt: datetime) -> datetime:
    """
    Convierte a timezone local o retorna naive si era naive.
    Útil para compatibilidad con código existente.
    """
    if dt is None:
        return None
    
    if dt.tzinfo is None:
        # Era naive, asumir que está en hora local
        return dt.replace(tzinfo=get_local_timezone())
    
    # Ya tiene timezone, convertir a local
    return dt.astimezone(get_local_timezone())

def ensure_local_timezone(dt: datetime) -> datetime:
    """
    Asegura que la fecha tenga la timezone local.
    Si es naive, asume que está en hora local.
    """
    if dt is None:
        return None
    
    if dt.tzinfo is None:
        # Es naive, asumir que está en hora local
        return dt.replace(tzinfo=get_local_timezone())
    
    # Ya tiene timezone, convertir a local
    return dt.astimezone(get_local_timezone())

def format_local_datetime(dt: datetime, format_str: str = "%Y-%m-%d %H:%M:%S") -> str:
    """Formatea una fecha en timezone local"""
    if dt is None:
        return None
    
    local_dt = to_local_or_naive(dt)
    return local_dt.strftime(format_str)

# Para compatibilidad con código existente que usa datetime.now()
def now() -> datetime:
    """Alias para now_local() - hora actual en timezone local"""
    return now_local()

# Para usar en lugar de datetime.now() cuando queremos hora local
def localnow() -> datetime:
    """Hora actual en timezone local (mismo que now())"""
    return now_local()