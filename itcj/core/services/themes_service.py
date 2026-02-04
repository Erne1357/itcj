# itcj/core/services/themes_service.py
"""
Servicio para gestión de temáticas del sistema.
Maneja la lógica de negocio para crear, actualizar, eliminar y consultar temáticas.
"""
from __future__ import annotations
from typing import Optional, List
from itcj.core.extensions import db
from itcj.core.models.theme import Theme


def get_active_theme() -> Optional[Theme]:
    """
    Obtiene la temática activa con mayor prioridad.
    Prioridad de activación: manual > automática por fechas.
    """
    # Primero buscar temáticas activadas manualmente
    manual = (
        Theme.query
        .filter_by(is_enabled=True, is_manually_active=True)
        .order_by(Theme.priority.asc())
        .first()
    )

    if manual:
        return manual

    # Si no hay manual, buscar por fechas
    all_themes = (
        Theme.query
        .filter_by(is_enabled=True)
        .order_by(Theme.priority.asc())
        .all()
    )

    for theme in all_themes:
        if theme.is_date_active():
            return theme

    return None


def list_themes() -> List[Theme]:
    """Lista todas las temáticas ordenadas por prioridad y nombre."""
    return (
        Theme.query
        .order_by(Theme.priority.asc(), Theme.name.asc())
        .all()
    )


def get_theme(theme_id: int) -> Optional[Theme]:
    """Obtiene una temática por ID."""
    return Theme.query.get(theme_id)


def get_theme_by_name(name: str) -> Optional[Theme]:
    """Obtiene una temática por nombre."""
    return Theme.query.filter_by(name=name).first()


def create_theme(data: dict, created_by_id: Optional[int] = None) -> Theme:
    """
    Crea una nueva temática.

    Args:
        data: Diccionario con los datos de la temática
        created_by_id: ID del usuario que crea la temática

    Returns:
        Theme: La temática creada

    Raises:
        ValueError: Si ya existe una temática con el mismo nombre
    """
    # Verificar nombre único
    if get_theme_by_name(data.get('name', '')):
        raise ValueError('Ya existe una temática con ese nombre')

    theme = Theme(
        name=data['name'],
        description=data.get('description'),
        start_day=data.get('start_day'),
        start_month=data.get('start_month'),
        end_day=data.get('end_day'),
        end_month=data.get('end_month'),
        is_manually_active=data.get('is_manually_active', False),
        is_enabled=data.get('is_enabled', True),
        priority=data.get('priority', 100),
        colors=data.get('colors', {}),
        custom_css=data.get('custom_css', ''),
        decorations=data.get('decorations', {}),
        css_file=data.get('css_file'),
        js_file=data.get('js_file'),
        preview_image=data.get('preview_image'),
        created_by_id=created_by_id
    )

    db.session.add(theme)
    db.session.commit()

    return theme


def update_theme(theme_id: int, **kwargs) -> Theme:
    """
    Actualiza una temática existente.

    Args:
        theme_id: ID de la temática a actualizar
        **kwargs: Campos a actualizar

    Returns:
        Theme: La temática actualizada

    Raises:
        ValueError: Si la temática no existe o hay conflicto de nombre
    """
    theme = Theme.query.get(theme_id)
    if not theme:
        raise ValueError('Temática no encontrada')

    # Verificar nombre único si se está cambiando
    if 'name' in kwargs and kwargs['name'] != theme.name:
        existing = get_theme_by_name(kwargs['name'])
        if existing:
            raise ValueError('Ya existe una temática con ese nombre')

    allowed_fields = [
        'name', 'description', 'start_day', 'start_month', 'end_day', 'end_month',
        'is_manually_active', 'is_enabled', 'priority', 'colors', 'custom_css',
        'decorations', 'css_file', 'js_file', 'preview_image'
    ]

    for key, value in kwargs.items():
        if key in allowed_fields:
            setattr(theme, key, value)

    db.session.commit()

    return theme


def toggle_theme_manual(theme_id: int, active: bool) -> Theme:
    """
    Activa o desactiva manualmente una temática.

    Args:
        theme_id: ID de la temática
        active: True para activar, False para desactivar

    Returns:
        Theme: La temática actualizada

    Raises:
        ValueError: Si la temática no existe
    """
    theme = Theme.query.get(theme_id)
    if not theme:
        raise ValueError('Temática no encontrada')

    theme.is_manually_active = active
    db.session.commit()

    return theme


def toggle_theme_enabled(theme_id: int, enabled: bool) -> Theme:
    """
    Habilita o deshabilita una temática (sin eliminarla).

    Args:
        theme_id: ID de la temática
        enabled: True para habilitar, False para deshabilitar

    Returns:
        Theme: La temática actualizada

    Raises:
        ValueError: Si la temática no existe
    """
    theme = Theme.query.get(theme_id)
    if not theme:
        raise ValueError('Temática no encontrada')

    theme.is_enabled = enabled
    db.session.commit()

    return theme


def delete_theme(theme_id: int) -> bool:
    """
    Elimina una temática.

    Args:
        theme_id: ID de la temática a eliminar

    Returns:
        bool: True si se eliminó correctamente

    Raises:
        ValueError: Si la temática no existe
    """
    theme = Theme.query.get(theme_id)
    if not theme:
        raise ValueError('Temática no encontrada')

    db.session.delete(theme)
    db.session.commit()

    return True


def get_themes_count() -> int:
    """Retorna el conteo total de temáticas."""
    return Theme.query.count()


def get_active_themes_count() -> int:
    """Retorna el conteo de temáticas que están actualmente activas."""
    themes = Theme.query.filter_by(is_enabled=True).all()
    return sum(1 for t in themes if t.is_active())
