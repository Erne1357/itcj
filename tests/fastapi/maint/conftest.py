"""
Conftest común para tests de la app maint.

- Carga eager de `itcj2.models` para resolver mappers de SQLAlchemy.
- Auto-patch de los broadcasts WS para evitar coroutines no awaited.
- Auto-patch de `_async_broadcast` para que no toque el event loop.
"""
from unittest.mock import MagicMock

import pytest

# Resolución de mappers (necesario para instanciar modelos)
import itcj2.models  # noqa: F401


_BROADCAST_FNS = (
    "broadcast_ticket_created",
    "broadcast_ticket_assigned",
    "broadcast_ticket_unassigned",
    "broadcast_ticket_status_changed",
    "broadcast_ticket_resolved",
    "broadcast_ticket_canceled",
    "broadcast_ticket_comment_added",
    "broadcast_ticket_rated",
)


@pytest.fixture(autouse=True)
def _silence_socket_broadcasts(monkeypatch):
    """Reemplaza los broadcasts WS por stubs síncronos para que no se creen
    corutinas que nadie awaite durante los tests."""
    import itcj2.sockets.maint as maint_sockets

    for fn_name in _BROADCAST_FNS:
        if hasattr(maint_sockets, fn_name):
            monkeypatch.setattr(maint_sockets, fn_name, MagicMock(return_value=None))

    # async_broadcast también se reemplaza para evitar tocar el event loop
    import itcj2.utils as itcj2_utils
    monkeypatch.setattr(itcj2_utils, "async_broadcast", MagicMock(return_value=None))

    yield
