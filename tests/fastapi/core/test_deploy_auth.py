"""Phase 8: /static-update es fail-closed (DEPLOY_SECRET sin configurar → 403)."""
import asyncio

import pytest
from fastapi import HTTPException

from itcj2.core.api.deploy import notify_static_update, StaticUpdateBody


def test_deploy_rejects_when_secret_unset():
    # DEPLOY_SECRET default = "" → debe rechazar (antes: guard nunca disparaba).
    with pytest.raises(HTTPException) as ei:
        asyncio.run(notify_static_update(StaticUpdateBody(changed=["a.css"], deploy_key=None)))
    assert ei.value.status_code == 403


def test_deploy_rejects_wrong_key(monkeypatch):
    from itcj2.config import get_settings
    s = get_settings()
    monkeypatch.setattr(s, "DEPLOY_SECRET", "super-secret", raising=False)
    with pytest.raises(HTTPException) as ei:
        asyncio.run(notify_static_update(StaticUpdateBody(changed=["a.css"], deploy_key="wrong")))
    assert ei.value.status_code == 403
