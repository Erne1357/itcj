"""Registro de apps del escritorio (fuente única, lado servidor).

Lo consumen la plantilla del dashboard (JSON en `#desktop-apps-data`) y el JS del
escritorio. No depende de la BD ni filtra por acceso (decisión de diseño).
"""
from sqlalchemy.orm import Session, joinedload

# Orden = orden del escritorio, de la barra y del menú inicio.
# `prefixes` sin barra final: sirven para saber a qué app pertenece una URL.
# Ningún prefijo es prefijo de otro (lo valida el test); si algún día ocurre,
# el resolver del cliente debe preferir el más largo.
DESKTOP_APPS: list[dict] = [
    {"key": "agendatec", "name": "AgendaTec", "url": "/agendatec/", "prefixes": ["/agendatec"],
     "icon": "calendar", "image": "core/images/app-icons/agendatec.webp",
     "pinned": True, "on_desktop": True, "badge_key": "agendatec", "system": False},
    {"key": "helpdesk", "name": "Help Desk", "url": "/help-desk/", "prefixes": ["/help-desk"],
     "icon": "ticket", "image": "core/images/app-icons/helpdesk.webp",
     "pinned": True, "on_desktop": True, "badge_key": "helpdesk", "system": False},
    {"key": "maint", "name": "Mantenimiento", "url": "/maint/", "prefixes": ["/maint"],
     "icon": "wrench", "image": "core/images/app-icons/maint.webp",
     "pinned": True, "on_desktop": True, "badge_key": "maint", "system": False},
    {"key": "directory", "name": "Extensiones", "url": "/directory/", "prefixes": ["/directory"],
     "icon": "book", "image": "core/images/app-icons/directory.webp",
     "pinned": True, "on_desktop": True, "badge_key": "directory", "system": False},
    {"key": "titulatec", "name": "TitulaTec", "url": "/titulatec/", "prefixes": ["/titulatec"],
     "icon": "graduation", "image": "core/images/app-icons/titulatec.webp",
     "pinned": True, "on_desktop": True, "badge_key": "titulatec", "system": False},
    {"key": "prorrogas_tec", "name": "Prórrogas", "url": "/prorrogas/", "prefixes": ["/prorrogas"],
     "icon": "briefcase", "image": "core/images/app-icons/prorrogas_tec.webp",
     "pinned": True, "on_desktop": True, "badge_key": "prorrogas_tec", "system": False},
    # Apps del sistema: sin imagen, ni en el escritorio ni ancladas.
    {"key": "profile", "name": "Perfil", "url": "/itcj/profile", "prefixes": ["/itcj/profile"],
     "icon": "user", "image": None,
     "pinned": False, "on_desktop": False, "badge_key": None, "system": True},
    {"key": "settings", "name": "Configuración", "url": "/itcj/config", "prefixes": ["/itcj/config"],
     "icon": "settings", "image": None,
     "pinned": False, "on_desktop": False, "badge_key": None, "system": True},
]

# Fondo del escritorio: LQIP (32x21 WebP q=40) inline + color promedio de respaldo.
DESKTOP_BACKGROUND: dict = {
    "url_path": "core/images/windows.webp",
    "lqip": "data:image/webp;base64,UklGRsAAAABXRUJQVlA4ILQAAABQBQCdASogABUAPu1mqk2ppaQiMAgBMB2JZgCdMzlC+NvXb0Ced2WgM9ZXMkIIT6t8orAA/nGalTyaE7sfqM7+X0OgN+5ph5MxJ3tzVlb72T+l+LpPVM6dcKtH9FjG6PeMKiHHyvFxbbgKnNg0ztFCnuA0bb8ERnrdUXyBg1ojgJ82s9ae9lQgcblFXld6nibGAy5yfOV8GH5KLOSKr9R8+w8pQUIzK6jDS3cWVB9Sc7SQAAA=",
    "color": "#61697a",
}


def build_apps_payload() -> list[dict]:
    """Copia de `DESKTOP_APPS` con `image` resuelta a URL estática versionada."""
    from itcj2.templates import sv

    out = []
    for app in DESKTOP_APPS:
        item = {**app, "prefixes": list(app["prefixes"])}
        if app["image"]:
            rel = app["image"].removeprefix("core/")
            item["image"] = f"/static/{app['image']}?v={sv('core', rel)}"
        out.append(item)
    return out


def _initials(name: str) -> str:
    parts = [p for p in (name or "").split() if p]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][0].upper()
    return (parts[0][0] + parts[1][0]).upper()


def get_user_card(db: Session, user: dict) -> dict:
    """Datos de la tarjeta del menú inicio: nombre, iniciales, puesto y departamento."""
    from itcj2.core.models.position import Position, UserPosition
    from itcj2.core.models.user import User

    uid = int(user["sub"])
    u = db.get(User, uid)
    full_name = u.full_name if u else (user.get("name") or "")

    up = (
        db.query(UserPosition)
        .options(joinedload(UserPosition.position).joinedload(Position.department))
        .filter(UserPosition.user_id == uid, UserPosition.is_active.is_(True))
        .order_by(UserPosition.id)
        .first()
    )
    position = up.position if up else None
    dept = position.department if position else None
    return {
        "full_name": full_name,
        "initials": _initials(full_name),
        "position": position.title if position else "",
        "department": dept.name if dept else "",
    }
