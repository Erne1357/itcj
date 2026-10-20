"""La descarga de un adjunto se sirve `inline`: la miniatura del detalle abre la
imagen (o el PDF) en otra pestaña en vez de bajarla como archivo."""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from itcj2.apps.maint.api.attachments import download_attachment


def test_download_is_inline(tmp_path):
    img = tmp_path / "86_20260924102834_abc.jpeg"
    img.write_bytes(b"\xff\xd8\xff\xe0fake-jpeg")
    att = SimpleNamespace(
        id=14, ticket_id=86, is_purged=False, purged_at=None,
        filepath=str(img), filename=img.name,
        original_filename="foto del salon.jpeg", mime_type="image/jpeg",
    )
    db = MagicMock()
    db.get.return_value = att

    with patch("itcj2.apps.maint.services.ticket_service.get_ticket_by_id"):
        resp = download_attachment(attachment_id=14, user={"sub": "10"}, db=db)

    disposition = resp.headers["content-disposition"]
    assert disposition.startswith("inline")
    assert "foto%20del%20salon.jpeg" in disposition or "foto del salon.jpeg" in disposition
    assert resp.media_type == "image/jpeg"


def _serve(tmp_path, *, name, mime):
    f = tmp_path / name
    f.write_bytes(b"%PDF-1.4 fake")
    att = SimpleNamespace(
        id=15, ticket_id=86, is_purged=False, purged_at=None,
        filepath=str(f), filename=name, original_filename=name, mime_type=mime,
    )
    db = MagicMock()
    db.get.return_value = att
    with patch("itcj2.apps.maint.services.ticket_service.get_ticket_by_id"):
        return download_attachment(attachment_id=15, user={"sub": "10"}, db=db)


def test_declared_mime_cannot_turn_inline_into_html(tmp_path):
    """El mime_type de un documento es el `content_type` que mandó el navegador:
    un PDF declarado `text/html` no debe renderizarse como HTML en el dominio."""
    resp = _serve(tmp_path, name="oficio.pdf", mime="text/html")
    assert resp.media_type == "application/pdf"
    assert resp.headers["content-disposition"].startswith("inline")
    assert resp.headers["x-content-type-options"] == "nosniff"


def test_unknown_type_is_downloaded_not_rendered(tmp_path):
    resp = _serve(tmp_path, name="algo.html", mime="text/html")
    assert resp.media_type == "application/octet-stream"
    assert resp.headers["content-disposition"].startswith("attachment")
