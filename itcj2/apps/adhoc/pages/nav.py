"""Navegación data-driven de Adhoc (Calidad), filtrada por permisos.

Patrón 2 de `docs/adhoc/analysis/tgt_convenciones-app.md` §Nav — el mismo de
`itcj2/apps/titulatec/pages/nav.py`: una tabla de tuplas
``(label, icon_bi, url, {permisos any-of})`` y un filtro contra
``get_user_permissions_for_app``. URLs literales (`/adhoc/...`), sin ENDPOINT_MAP.

Regla de fail-soft (importante mientras el DML de F2 no exista): si el cálculo de
permisos revienta o el usuario no tiene ninguno, se devuelve una lista **vacía**.
Devolver el menú sin filtrar sería un fallo abierto: enseñaría enlaces a páginas
que después responden 403. La única excepción es el admin global del JWT
(``user["role"] == "admin"``), que ya bypasea ``require_perms``.
"""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


# (label, icono Bootstrap, url, permisos que lo habilitan — any-of)
NAV_SECTIONS: list[tuple[str, str, str, set[str]]] = [
    (
        "Tareas",
        "bi-list-task",
        "/adhoc/dashboard",
        {"adhoc.dashboard.page.view"},
    ),
    (
        "Documentos",
        "bi-file-earmark-text",
        "/adhoc/documentos",
        {"adhoc.documents.page.list"},
    ),
    (
        "Indicadores",
        "bi-graph-up-arrow",
        "/adhoc/indicadores/?mode=tracking",
        {"adhoc.indicators.page.list", "adhoc.indicators.page.tracking"},
    ),
    (
        "Panel de Control",
        "bi-sliders",
        "/adhoc/panel",
        {"adhoc.panel.page.view"},
    ),
]


def _all_items() -> list[dict]:
    return [{"label": label, "icon": icon, "url": url} for label, icon, url, _ in NAV_SECTIONS]


def nav_items(db: Session, user_id: int, *, is_admin: bool = False) -> list[dict]:
    """Secciones visibles para *user_id* en la app ``adhoc``.

    ``is_admin`` es el admin GLOBAL del JWT (``user["role"] == "admin"``), que ve
    todo sin consultar permisos. Para cualquier otro usuario, un error al calcular
    permisos devuelve ``[]`` (fail-closed), nunca el menú completo.
    """
    if is_admin:
        return _all_items()

    from itcj2.core.services.authz_service import get_user_permissions_for_app

    try:
        perms = get_user_permissions_for_app(db, int(user_id), "adhoc")
    except Exception as exc:
        # Típico en F0/F1: los permisos adhoc.* aún no existen en BD.
        logger.warning("adhoc nav: no se pudieron calcular permisos para user %s: %s", user_id, exc)
        return []

    out: list[dict] = []
    for label, icon, url, need in NAV_SECTIONS:
        if perms & need:
            out.append({"label": label, "icon": icon, "url": url})
    return out


def nav_for_user(db: Session, user: dict | None) -> list[dict]:
    """Azúcar para las páginas: acepta el dict del JWT y resuelve el admin global."""
    if not user:
        return []
    try:
        return nav_items(db, int(user["sub"]), is_admin=user.get("role") == "admin")
    except Exception as exc:
        logger.warning("adhoc nav: usuario inválido en el contexto (%s)", exc)
        return []
