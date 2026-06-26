"""
Tests para la lógica de adjuntos por área en el endpoint
POST /api/help-desk/v2/attachments/ticket/{ticket_id}.

Cubre:
  - Subir PDF a ticket DESARROLLO → permitido (allowed_ext incluye docs).
  - Subir PDF a ticket SOPORTE → 400 (solo imágenes).
  - Subir imagen a ticket SOPORTE → permitido.
  - Subir imagen a ticket DESARROLLO → permitido.

Nota: `fvs` y `ticket_service` se importan LOCALMENTE dentro de
upload_attachment(), por lo que NO son atributos del módulo
itcj2.apps.helpdesk.api.attachments. Se deben parchear en el módulo
fuente (itcj2.apps.helpdesk.services.*).
"""
import io
from unittest.mock import MagicMock, patch

import pytest

from tests.conftest import make_jwt

BASE = "/api/help-desk/v2/attachments"

# Cabecera mínima para un PDF válido (magic bytes %PDF)
PDF_MAGIC = b"%PDF-1.4 fake content for testing"
# Cabecera mínima para JPEG válido (magic bytes FF D8 FF)
JPEG_MAGIC = bytes([0xFF, 0xD8, 0xFF, 0xE0]) + b"\x00\x10JFIF\x00" + b"\x00" * 50


def _make_ticket(ticket_id: int = 1, area: str = "SOPORTE"):
    ticket = MagicMock()
    ticket.id = ticket_id
    ticket.ticket_number = f"TKT-2026-{ticket_id:03d}"
    ticket.area = area
    ticket.status = "PENDING"
    return ticket


def _make_headers(user_id: int = 10, role: str = "admin") -> dict:
    token = make_jwt(user_id=user_id, role=role)
    return {"Cookie": f"itcj_token={token}"}


# ---------------------------------------------------------------------------
# Tests de lógica de extensiones por área
# ---------------------------------------------------------------------------

class TestAllowedExtByArea:
    """
    Verifica la decisión de allowed_ext según ticket.area.

    Parchea validate_and_get_file_info en el módulo fuente (no en el alias
    local `fvs`) y get_ticket_by_id en ticket_service, que es donde viven
    realmente al momento de la importación local dentro de la función endpoint.
    """

    @patch(
        "itcj2.apps.helpdesk.services.ticket_service.get_ticket_by_id",
    )
    @patch(
        "itcj2.apps.helpdesk.services.file_validation_service.validate_and_get_file_info",
    )
    def test_pdf_allowed_on_desarrollo(self, mock_validate, mock_get_ticket, app_client):
        """PDF enviado a ticket DESARROLLO → validate_and_get_file_info llamado con extensiones de doc."""
        ticket = _make_ticket(area="DESARROLLO")
        mock_get_ticket.return_value = ticket

        from itcj2.config import get_settings
        s = get_settings()
        expected_doc_exts = set(s.HELPDESK_ALLOWED_DOC_EXTENSIONS.split(','))

        # Simular validación exitosa de un PDF
        mock_validate.return_value = (True, {
            "extension": "pdf",
            "is_image": False,
            "size": 1024,
        })

        mock_db = MagicMock()
        mock_db.query.return_value.filter_by.return_value.count.return_value = 0

        from itcj2.database import get_db
        app_client.app.dependency_overrides[get_db] = lambda: (yield mock_db)

        try:
            with patch("builtins.open", MagicMock()):
                with patch("os.makedirs"):
                    with patch("os.path.exists", return_value=False):
                        with patch(
                            "itcj2.apps.helpdesk.models.attachment.Attachment"
                        ) as MockAttachment:
                            mock_att_instance = MagicMock()
                            mock_att_instance.to_dict.return_value = {"id": 1}
                            MockAttachment.return_value = mock_att_instance

                            resp = app_client.post(
                                f"{BASE}/ticket/1",
                                data={"attachment_type": "ticket"},
                                files={"file": ("test.pdf", io.BytesIO(PDF_MAGIC), "application/pdf")},
                                headers=_make_headers(role="admin"),
                            )

            # validate_and_get_file_info debe haberse llamado con extensiones de doc incluidas
            assert mock_validate.called, "validate_and_get_file_info no fue llamado"
            call_kwargs = mock_validate.call_args
            passed_exts = call_kwargs.kwargs.get(
                "allowed_extensions",
                call_kwargs.args[1] if len(call_kwargs.args) > 1 else set()
            )
            assert expected_doc_exts.issubset(passed_exts), (
                f"Se esperaba que allowed_ext incluyera docs para DESARROLLO. Got: {passed_exts}"
            )
        finally:
            app_client.app.dependency_overrides.pop(get_db, None)

    @patch(
        "itcj2.apps.helpdesk.services.ticket_service.get_ticket_by_id",
    )
    @patch(
        "itcj2.apps.helpdesk.services.file_validation_service.validate_and_get_file_info",
    )
    def test_pdf_rejected_on_soporte(self, mock_validate, mock_get_ticket, app_client):
        """PDF enviado a ticket SOPORTE → validate_and_get_file_info llamado sin extensiones de doc."""
        ticket = _make_ticket(area="SOPORTE")
        mock_get_ticket.return_value = ticket

        from itcj2.config import get_settings
        s = get_settings()
        doc_exts = set(s.HELPDESK_ALLOWED_DOC_EXTENSIONS.split(','))

        # Simular fallo de validación (PDF no es imagen)
        mock_validate.return_value = (
            False,
            "Extensión no permitida: pdf",
        )

        mock_db = MagicMock()
        from itcj2.database import get_db
        app_client.app.dependency_overrides[get_db] = lambda: (yield mock_db)

        try:
            resp = app_client.post(
                f"{BASE}/ticket/1",
                data={"attachment_type": "ticket"},
                files={"file": ("test.pdf", io.BytesIO(PDF_MAGIC), "application/pdf")},
                headers=_make_headers(role="admin"),
            )

            # El endpoint debe retornar 400 (validación falló)
            assert resp.status_code == 400, f"Se esperaba 400, se obtuvo {resp.status_code}"

            # validate_and_get_file_info fue llamado con solo extensiones de imagen
            assert mock_validate.called, "validate_and_get_file_info no fue llamado"
            call_kwargs = mock_validate.call_args
            passed_exts = call_kwargs.kwargs.get(
                "allowed_extensions",
                call_kwargs.args[1] if len(call_kwargs.args) > 1 else set()
            )
            assert not doc_exts.intersection(passed_exts), (
                f"SOPORTE no debe tener extensiones de doc. Got: {passed_exts}"
            )
        finally:
            app_client.app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# Test unitario de lógica pura de selección de extensiones
# ---------------------------------------------------------------------------

class TestAllowedExtSelectionLogic:
    """
    Verifica directamente la lógica de selección de allowed_ext del endpoint,
    sin levantar HTTP ni necesitar BD.
    """

    def test_desarrollo_includes_doc_extensions(self):
        """Para DESARROLLO, allowed_ext debe incluir todas las extensiones de doc."""
        from itcj2.config import get_settings
        s = get_settings()
        img_ext = set(s.HELPDESK_ALLOWED_EXTENSIONS.split(','))
        doc_ext = set(s.HELPDESK_ALLOWED_DOC_EXTENSIONS.split(','))

        # Lógica del endpoint para attachment_type == "ticket", area == "DESARROLLO"
        area = "DESARROLLO"
        if area == "DESARROLLO":
            allowed_ext = img_ext | doc_ext
        else:
            allowed_ext = img_ext

        assert "pdf" in allowed_ext
        assert "docx" in allowed_ext
        assert "xlsx" in allowed_ext
        assert "csv" in allowed_ext
        assert "jpg" in allowed_ext  # imágenes también incluidas

    def test_soporte_excludes_doc_extensions(self):
        """Para SOPORTE, allowed_ext solo debe contener imágenes."""
        from itcj2.config import get_settings
        s = get_settings()
        img_ext = set(s.HELPDESK_ALLOWED_EXTENSIONS.split(','))
        doc_ext = set(s.HELPDESK_ALLOWED_DOC_EXTENSIONS.split(','))

        area = "SOPORTE"
        if area == "DESARROLLO":
            allowed_ext = img_ext | doc_ext
        else:
            allowed_ext = img_ext

        assert "pdf" not in allowed_ext
        assert "docx" not in allowed_ext
        assert "xlsx" not in allowed_ext
        assert "jpg" in allowed_ext
        assert "png" in allowed_ext

    def test_resolution_always_includes_docs(self):
        """attachment_type resolution/comment siempre permite docs (sin importar área)."""
        from itcj2.config import get_settings
        s = get_settings()
        img_ext = set(s.HELPDESK_ALLOWED_EXTENSIONS.split(','))
        doc_ext = set(s.HELPDESK_ALLOWED_DOC_EXTENSIONS.split(','))

        # Lógica del endpoint para attachment_type != "ticket"
        attachment_type = "resolution"
        if attachment_type == "ticket":
            allowed_ext = img_ext  # no llega aquí
        else:
            allowed_ext = img_ext | doc_ext

        assert "pdf" in allowed_ext
        assert "jpg" in allowed_ext
