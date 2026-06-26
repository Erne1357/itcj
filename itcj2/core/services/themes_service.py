"""
Servicio para gestión de temáticas del sistema.
"""
from __future__ import annotations
from typing import Optional, List

from sqlalchemy.orm import Session

from itcj2.core.models.theme import Theme


def invalidate_active_theme_cache() -> None:
    """Borra el cache del tema activo (llamar tras crear/editar/activar/desactivar)."""
    try:
        from itcj2.core.utils.redis_conn import get_redis
        get_redis().delete("core:active_theme")
    except Exception:
        pass


def _sync_mundial_cron(db: Session, theme_name: str | None) -> None:
    """Si el tema afectado es el del Mundial, sincroniza el cron con su estado activo."""
    try:
        from itcj2.core.services import mundial_service
        if theme_name == mundial_service.THEME_NAME:
            mundial_service.sync_periodic_task(db)
    except Exception:
        pass


def get_active_theme(db: Session) -> Optional[Theme]:
    """Obtiene la temática activa con mayor prioridad."""
    manual = (
        db.query(Theme)
        .filter_by(is_enabled=True, is_manually_active=True)
        .order_by(Theme.priority.asc())
        .first()
    )
    if manual:
        return manual

    all_themes = (
        db.query(Theme)
        .filter_by(is_enabled=True)
        .order_by(Theme.priority.asc())
        .all()
    )
    for theme in all_themes:
        if theme.is_date_active():
            return theme

    return None


def list_themes(db: Session) -> List[Theme]:
    return db.query(Theme).order_by(Theme.priority.asc(), Theme.name.asc()).all()


def get_theme(db: Session, theme_id: int) -> Optional[Theme]:
    return db.get(Theme, theme_id)


def get_theme_by_name(db: Session, name: str) -> Optional[Theme]:
    return db.query(Theme).filter_by(name=name).first()


def create_theme(db: Session, data: dict, created_by_id: Optional[int] = None) -> Theme:
    if get_theme_by_name(db, data.get('name', '')):
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
        created_by_id=created_by_id,
    )
    db.add(theme)
    db.commit()
    invalidate_active_theme_cache()
    _sync_mundial_cron(db, theme.name)
    return theme


def update_theme(db: Session, theme_id: int, **kwargs) -> Theme:
    theme = db.get(Theme, theme_id)
    if not theme:
        raise ValueError('Temática no encontrada')

    if 'name' in kwargs and kwargs['name'] != theme.name:
        if get_theme_by_name(db, kwargs['name']):
            raise ValueError('Ya existe una temática con ese nombre')

    allowed_fields = [
        'name', 'description', 'start_day', 'start_month', 'end_day', 'end_month',
        'is_manually_active', 'is_enabled', 'priority', 'colors', 'custom_css',
        'decorations', 'css_file', 'js_file', 'preview_image',
    ]
    for key, value in kwargs.items():
        if key in allowed_fields:
            setattr(theme, key, value)

    db.commit()
    invalidate_active_theme_cache()
    _sync_mundial_cron(db, theme.name)
    return theme


def toggle_theme_manual(db: Session, theme_id: int, active: bool) -> Theme:
    theme = db.get(Theme, theme_id)
    if not theme:
        raise ValueError('Temática no encontrada')
    theme.is_manually_active = active
    db.commit()
    invalidate_active_theme_cache()
    _sync_mundial_cron(db, theme.name)
    return theme


def toggle_theme_enabled(db: Session, theme_id: int, enabled: bool) -> Theme:
    theme = db.get(Theme, theme_id)
    if not theme:
        raise ValueError('Temática no encontrada')
    theme.is_enabled = enabled
    db.commit()
    invalidate_active_theme_cache()
    _sync_mundial_cron(db, theme.name)
    return theme


def delete_theme(db: Session, theme_id: int) -> bool:
    theme = db.get(Theme, theme_id)
    if not theme:
        raise ValueError('Temática no encontrada')
    name = theme.name
    db.delete(theme)
    db.commit()
    invalidate_active_theme_cache()
    _sync_mundial_cron(db, name)
    return True


def get_themes_count(db: Session) -> int:
    return db.query(Theme).count()


def get_active_themes_count(db: Session) -> int:
    themes = db.query(Theme).filter_by(is_enabled=True).all()
    return sum(1 for t in themes if t.is_active())
