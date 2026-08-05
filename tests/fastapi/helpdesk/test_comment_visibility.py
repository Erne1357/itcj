"""Comentar un ticket exige poder VERLO.

`POST /{ticket_id}/comments` solo pedía el permiso genérico de crear comentarios
—que el rol `staff` tiene— y resolvía el ticket con `check_permissions=False`
DESPUÉS de haberlo insertado. Con eso, cualquiera podía escribir (y en maint,
adjuntar archivos) en el ticket de cualquier departamento.
"""
import pytest
from unittest.mock import MagicMock, patch

from fastapi import HTTPException

import itcj2.models  # noqa: F401


class _JsonRequest:
    """Request mínimo: solo se usan headers y json()."""

    def __init__(self, payload):
        self.headers = {"content-type": "application/json"}
        self._payload = payload

    async def json(self):
        return self._payload

    async def body(self):
        import json
        return json.dumps(self._payload).encode()


@pytest.mark.asyncio
async def test_helpdesk_comment_on_invisible_ticket_is_rejected():
    from itcj2.apps.helpdesk.api.ticket_comments import add_comment

    db = MagicMock()
    with patch("itcj2.core.services.authz_service.user_roles_in_app", return_value=["staff"]), \
         patch("itcj2.apps.helpdesk.services.ticket_service.can_user_view_ticket",
               return_value=False), \
         patch("itcj2.apps.helpdesk.services.ticket_service.add_comment") as mock_add:
        with pytest.raises(HTTPException) as exc:
            await add_comment(
                ticket_id=42,
                request=_JsonRequest({"content": "hola", "is_internal": False}),
                user={"sub": "999", "role": "user"},
                db=db,
            )

    assert exc.value.status_code == 403
    mock_add.assert_not_called()  # el comentario NO llegó a insertarse


@pytest.mark.asyncio
async def test_maint_comment_on_invisible_ticket_is_rejected():
    from itcj2.apps.maint.api.comments import add_comment

    db = MagicMock()
    with patch("itcj2.apps.maint.services.ticket_service.can_user_view_ticket",
               return_value=False), \
         patch("itcj2.apps.maint.services.ticket_service.add_comment") as mock_add:
        with pytest.raises(HTTPException) as exc:
            await add_comment(
                ticket_id=42,
                request=_JsonRequest({"content": "hola", "is_internal": False}),
                user={"sub": "999", "role": "user"},
                db=db,
            )

    assert exc.value.status_code == 403
    mock_add.assert_not_called()
