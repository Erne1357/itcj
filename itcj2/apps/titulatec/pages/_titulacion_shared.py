"""Piezas compartidas por las vistas de la pestaña Titulación (Formato B y Anexo III).

`titulacion_admin.py` y `titulacion_anexo.py` importan de aquí lo que no depende
de la vista: nombres, selector de carreras, la vista (`tab/q/carrera/page`) con
que se actúa, el siguiente de la cola FIFO que nadie más tiene abierto y la
pestaña de un `?selected=`. Lo que cambia por vista (servicio de bandeja, tipo de
presencia, estado→pestaña) entra por parámetro.
"""
from __future__ import annotations

from typing import Callable

# Al elegir el siguiente de la cola tras dictaminar se saltan, a lo más, estos
# procesos abiertos por otra persona (el Depto. son dos o tres revisores).
NEXT_TRIES = 10


def to_int(raw):
    try:
        return int(raw) if raw not in (None, "") else None
    except (TypeError, ValueError):
        return None


def nombre(user) -> str:
    return " ".join(p for p in (user.first_name, user.last_name) if p) if user else ""


def viewer_name(db, user_id: int) -> str:
    """Nombre con que el revisor aparece en la insignia de los demás."""
    from itcj2.core.models.user import User
    return nombre(db.get(User, user_id)) or "Otra persona"


def vista(form) -> dict:
    """La pestaña, búsqueda, carrera y página desde las que se actuó: la acción
    re-pinta la MISMA vista (regla 3 de la paginación, CLAUDE.md §18)."""
    return {"tab": form.get("tab") or "pending", "q": form.get("q") or "",
            "carrera": form.get("carrera") or "", "page": form.get("page") or ""}


def programs(db, user_id: int) -> list[dict]:
    """Carreras del filtro: las del alcance del usuario (todas con «ALL»)."""
    from itcj2.apps.titulatec.services.scope_service import officer_programs
    from itcj2.core.models.program import Program

    scope = officer_programs(db, user_id)
    if scope != "ALL" and not scope:
        return []
    query = db.query(Program.id, Program.name).order_by(Program.name, Program.id)
    if scope != "ALL":
        query = query.filter(Program.id.in_(scope))
    return [{"id": p.id, "name": p.name} for p in query.all()]


def next_free(db, user_id: int, done_id: int, vista_: dict | None, *, inbox, kind: str):
    """El siguiente «Por revisar» de la cola FIFO que nadie más tenga abierto.

    Salta el recién dictaminado y, uno por uno, los que otra persona tiene
    abiertos; con Redis caído `viewers` devuelve vacío y gana la cabeza de la
    cola. Respeta la búsqueda y la carrera de la vista. None si no queda ninguno
    libre. `inbox` es el servicio de bandeja (`next_pending`) y `kind` el tipo
    de `ReviewPresence`.
    """
    from itcj2.apps.titulatec.services.review_presence import ReviewPresence

    vista_ = vista_ or {}
    q, carrera = vista_.get("q") or "", to_int(vista_.get("carrera"))
    excluir = {done_id}
    for _ in range(NEXT_TRIES):
        pid = inbox.next_pending(db, user_id, exclude_ids=excluir, q=q, program_id=carrera)
        if pid is None:
            return None
        if not ReviewPresence.viewers(kind, [pid], exclude_user_id=user_id):
            return pid
        excluir.add(pid)
    return None


def infer_tab(db, user_id: int, process_id: int, *, status_of: Callable,
              tab_by_status: dict, fallback: str = "unsent") -> str:
    """Pestaña de un `?selected=` que llega sin ella. Solo mira procesos en
    alcance: la pestaña marcada no debe delatar el estado de uno ajeno.
    `status_of(db, process_id)` da el estado propio de la vista."""
    from itcj2.apps.titulatec.services.scope_service import process_in_scope

    if process_in_scope(db, user_id, process_id) is None:
        return "pending"
    return tab_by_status.get(status_of(db, process_id), fallback)
