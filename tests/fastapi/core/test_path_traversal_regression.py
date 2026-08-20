"""Regresión de contención de rutas (auditoría agosto 2026).

Tres sinks distintos servían/escribían archivos con un tramo de ruta controlado
por el usuario:

* ``GET /api/vistetec/v2/garments/image/{image_path:path}`` — ``os.path.join`` con
  el resto de la URL sin normalizar (lectura arbitraria).
* ``GET /api/help-desk/v2/attachments/custom-field/{ticket_id}/{field_key}`` — el
  único guard era ``startswith("/instance/")`` sobre un valor que el cliente
  escribe en la columna JSON ``custom_fields`` (lectura arbitraria).
* ``ImportService`` de TitulaTec — el token del CSV temporal vuelve del formulario
  (lectura y borrado de ``*.csv`` arbitrarios).

Todos se anclan ahora con ``itcj2.core.utils.safe_paths.safe_join``.
"""
import os

import pytest

from itcj2.core.utils.safe_paths import UnsafePath, is_within, safe_join


ESCAPES = [
    "../../../etc/passwd",
    "..",
    "a/../../..",
    "x/../../../../../../etc/shadow",
    "./../..",
]

ABSOLUTES = ["/etc/passwd", "/", "//etc/passwd"]


class TestSafeJoin:
    def test_normal_path_stays_inside(self, tmp_path):
        out = safe_join(tmp_path, "2026", "08", "prenda.jpg")
        assert is_within(tmp_path, out)
        assert out.name == "prenda.jpg"

    @pytest.mark.parametrize("bad", ESCAPES)
    def test_traversal_rejected(self, tmp_path, bad):
        with pytest.raises(UnsafePath):
            safe_join(tmp_path, bad)

    @pytest.mark.parametrize("bad", ABSOLUTES)
    def test_absolute_component_rejected(self, tmp_path, bad):
        """os.path.join(base, '/etc/passwd') == '/etc/passwd': la base se descarta.

        Es la trampa que hacía que el endpoint de vistetec *pareciera* anclado.
        """
        with pytest.raises(UnsafePath):
            safe_join(tmp_path, bad)

    def test_null_byte_rejected(self, tmp_path):
        with pytest.raises(UnsafePath):
            safe_join(tmp_path, "ok.jpg\x00.php")

    def test_symlink_out_of_root_rejected(self, tmp_path):
        outside = tmp_path.parent / "outside_secret"
        outside.mkdir(exist_ok=True)
        (outside / "f.txt").write_text("secreto")
        root = tmp_path / "root"
        root.mkdir()
        link = root / "escape"
        try:
            os.symlink(outside, link, target_is_directory=True)
        except (OSError, NotImplementedError, AttributeError):
            pytest.skip("symlinks no disponibles en este entorno")
        with pytest.raises(UnsafePath):
            safe_join(root, "escape", "f.txt")

    def test_dotdot_that_returns_inside_is_allowed(self, tmp_path):
        """No se prohíbe '..' per se: se prohíbe SALIR. a/../b sigue dentro."""
        out = safe_join(tmp_path, "a", "..", "b.jpg")
        assert is_within(tmp_path, out)

    def test_is_within_does_not_raise(self, tmp_path):
        assert is_within(tmp_path, tmp_path / "x")
        assert not is_within(tmp_path, tmp_path.parent / "otro")


class TestVistetecImageEndpointLogic:
    """El endpoint filtra por extensión ANTES de tocar disco."""

    def test_servable_extensions(self):
        from itcj2.apps.vistetec.api.garments import _SERVABLE_IMAGE_EXTS

        assert "jpg" in _SERVABLE_IMAGE_EXTS and "png" in _SERVABLE_IMAGE_EXTS
        for denied in ("json", "env", "py", "html", "svg", "passwd", "csv"):
            assert denied not in _SERVABLE_IMAGE_EXTS

    @pytest.mark.parametrize("url_tail", [
        "../../../../etc/passwd",
        "../../.env",
        "../../itcj/email/msal_cache.json",
        "/etc/passwd",
    ])
    def test_hostile_tails_never_resolve(self, tmp_path, url_tail):
        from itcj2.apps.vistetec.api.garments import _SERVABLE_IMAGE_EXTS

        parts = [s for s in url_tail.split("/") if s not in ("", ".")]
        ext = parts[-1].rsplit(".", 1)[-1].lower() if parts else ""
        if ext in _SERVABLE_IMAGE_EXTS:
            with pytest.raises(UnsafePath):
                safe_join(tmp_path, *parts)
        else:
            assert ext not in _SERVABLE_IMAGE_EXTS

    def test_traversal_with_image_extension_still_blocked(self, tmp_path):
        """Un atacante puede ponerle .jpg al payload; la contención debe aguantar."""
        with pytest.raises(UnsafePath):
            safe_join(tmp_path, "..", "..", "..", "secreto.jpg")


class TestHelpdeskCustomFieldPath:
    """`/instance/../../../etc/passwd` satisfacía el viejo startswith('/instance/')."""

    PREFIX = "/instance/apps/helpdesk/custom_fields/"

    @pytest.mark.parametrize("stored", [
        "/instance/../../../etc/passwd",
        "/instance/apps/helpdesk/custom_fields/../../../../../../etc/passwd",
        "/instance/apps/itcj/email/msal_cache.json",
        "/instance/apps/helpdesk/custom_fields/../../itcj/email/msal_cache.json",
    ])
    def test_stored_value_cannot_escape(self, tmp_path, stored):
        assert stored.startswith("/instance/")  # el guard viejo lo dejaba pasar
        if not stored.startswith(self.PREFIX):
            return  # el prefijo estricto ya lo corta
        with pytest.raises(UnsafePath):
            safe_join(tmp_path, stored[len(self.PREFIX):])

    def test_legitimate_value_resolves(self, tmp_path):
        stored = self.PREFIX + "TK-12_evidencia.pdf"
        out = safe_join(tmp_path, stored[len(self.PREFIX):])
        assert is_within(tmp_path, out)
        assert out.name == "TK-12_evidencia.pdf"


class TestTitulatecImportToken:
    @pytest.mark.parametrize("bad", [
        "../../../../etc/hosts", "..", "a/b", "", "ZZZZ",
        "deadbeef",              # 8 chars, el token real trae 16
        "deadbeefdeadbeef0",     # 17
        "DEADBEEFDEADBEEF",      # mayúsculas: token_hex emite minúsculas
        None, 123,
    ])
    def test_bad_tokens_yield_no_path(self, bad):
        from itcj2.apps.titulatec.services.import_service import _temp_csv_path

        assert _temp_csv_path(bad) is None

    def test_real_token_shape_accepted(self):
        import secrets

        from itcj2.apps.titulatec.services.import_service import _temp_csv_path

        tok = secrets.token_hex(8)  # exactamente lo que emite pages/admin.py
        p = _temp_csv_path(tok)
        assert p is not None and p.name == f"{tok}.csv"

    def test_read_and_delete_are_noops_for_bad_token(self):
        from itcj2.apps.titulatec.services.import_service import ImportService

        assert ImportService.read_temp("../../../../etc/passwd") is None
        ImportService.delete_temp("../../../../etc/passwd")  # no borra ni lanza
        with pytest.raises(ValueError):
            ImportService.save_temp(b"x", "../../../evil")


class TestTitulatecControlNumber:
    @pytest.mark.parametrize("bad", [
        "../../../../instance/apps/EVIL",
        "..",
        "a/b",
        "12345",
        "abc",
        "123456789",  # 9 dígitos puros: inválido por diseño
    ])
    def test_invalid_control_numbers_rejected(self, bad):
        from itcj2.apps.titulatec.services.import_service import CONTROL_NUMBER_RE

        assert not CONTROL_NUMBER_RE.fullmatch(bad)

    @pytest.mark.parametrize("good", ["12345678", "L1234567", "M123456789"])
    def test_valid_control_numbers_accepted(self, good):
        from itcj2.apps.titulatec.services.import_service import CONTROL_NUMBER_RE

        assert CONTROL_NUMBER_RE.fullmatch(good)

    def test_regex_matches_core_source_of_truth(self):
        """La copia local debe seguir igual al regex de core/api/users_admin.py."""
        from itcj2.apps.titulatec.services.import_service import CONTROL_NUMBER_RE as LOCAL
        from itcj2.core.api.users_admin import CONTROL_NUMBER_RE as CORE

        assert LOCAL.pattern == CORE.pattern


class TestHelpdeskNotificationSandbox:
    """SSTI: las plantillas de notificación viven en BD y son editables."""

    def test_environment_is_sandboxed(self):
        from jinja2.sandbox import SandboxedEnvironment

        from itcj2.apps.helpdesk.services.notification_helper import _jinja_env

        assert isinstance(_jinja_env, SandboxedEnvironment)
        assert _jinja_env.autoescape is True

    def test_dunder_access_is_blocked(self):
        from itcj2.apps.helpdesk.services.notification_helper import _safe_render

        payload = "{{ ''.__class__.__mro__[1].__subclasses__() }}"
        # _safe_render devuelve la plantilla cruda cuando el render falla
        assert _safe_render(payload, {}) == payload

    def test_normal_template_still_renders(self):
        from itcj2.apps.helpdesk.services.notification_helper import _safe_render

        out = _safe_render("Ticket {{ n }} creado", {"n": "HD-2026-001"})
        assert out == "Ticket HD-2026-001 creado"

    def test_html_is_escaped(self):
        from itcj2.apps.helpdesk.services.notification_helper import _safe_render

        out = _safe_render("{{ t }}", {"t": "<img src=x onerror=alert(1)>"})
        assert "<img" not in out


class TestCustomFieldsUploadHardening:
    def test_extension_allowlist_excludes_web_executables(self):
        from itcj2.apps.helpdesk.services.custom_fields_file_service import (
            _ALLOWED_EXTENSIONS,
        )

        for denied in ("html", "htm", "svg", "js", "php", "py", "sh", "exe"):
            assert denied not in _ALLOWED_EXTENSIONS
        assert {"pdf", "jpg", "png"} <= _ALLOWED_EXTENSIONS


class TestFileContentValidation:
    """La validación de contenido miraba solo la firma inicial: `webp` compartía
    prefijo con cualquier RIFF (avi/wav) y `docx`/`xlsx` aceptaban cualquier ZIP.
    """

    @staticmethod
    def _check(data, ext):
        import io

        from itcj2.apps.helpdesk.services.file_validation_service import (
            validate_file_magic_bytes,
        )

        return validate_file_magic_bytes(io.BytesIO(data), ext)[0]

    @staticmethod
    def _img(fmt, size=(16, 16)):
        import io

        from PIL import Image

        buf = io.BytesIO()
        Image.new("RGB", size, (10, 20, 30)).save(buf, format=fmt)
        return buf.getvalue()

    @staticmethod
    def _ooxml(kind, valid=True):
        import io
        import zipfile

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            if valid:
                z.writestr("[Content_Types].xml", "<Types/>")
                z.writestr(
                    "word/document.xml" if kind == "docx" else "xl/workbook.xml", "<x/>"
                )
            else:
                z.writestr("META-INF/MANIFEST.MF", "Main-Class: Evil")
                z.writestr("Evil.class", "payload")
        return buf.getvalue()

    # --- webp: RIFF no basta ---
    def test_real_webp_accepted(self):
        assert self._check(self._img("WEBP"), "webp")

    @pytest.mark.parametrize("riff", [
        b"RIFF\x00\x00\x00\x00AVI LIST" + b"x" * 40,
        b"RIFF\x24\x00\x00\x00WAVEfmt " + b"x" * 40,
    ])
    def test_other_riff_containers_rejected_as_webp(self, riff):
        assert not self._check(riff, "webp")

    # --- ooxml: PK no basta ---
    @pytest.mark.parametrize("kind", ["docx", "xlsx"])
    def test_real_ooxml_accepted(self, kind):
        assert self._check(self._ooxml(kind), kind)

    @pytest.mark.parametrize("kind", ["docx", "xlsx"])
    def test_plain_zip_rejected_as_ooxml(self, kind):
        assert not self._check(self._ooxml(kind, valid=False), kind)

    def test_xlsx_container_rejected_as_docx(self):
        assert not self._check(self._ooxml("xlsx"), "docx")

    # --- csv: binario fuera, cp1252 dentro ---
    @pytest.mark.parametrize("data", [
        "control,nombre\n21110001,Jose Perez\n".encode("utf-8"),
        "control,nombre\n21110001,Jos\xe9 Mu\xf1oz\n".encode("cp1252"),
        "control,nombre\n1,a\n".encode("utf-8-sig"),
    ])
    def test_text_csv_accepted(self, data):
        """cp1252 es lo que exporta Excel; el check viejo (solo UTF-8) lo tiraba."""
        assert self._check(data, "csv")

    @pytest.mark.parametrize("data", [
        b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n",
        b"MZ\x90\x00\x03\x00\x00\x00",
        b"\x7fELF\x02\x01\x01\x00",
        b"\x1f\x8b\x08\x00",
        b"a,b\n\x001,2\n",
        b"",
    ])
    def test_binary_rejected_as_csv(self, data):
        assert not self._check(data, "csv")

    def test_zip_rejected_as_csv(self):
        assert not self._check(self._ooxml("docx"), "csv")

    # --- imágenes: cabecera correcta + cuerpo corrupto ---
    @pytest.mark.parametrize("fmt,ext", [("PNG", "png"), ("JPEG", "jpg"), ("GIF", "gif")])
    def test_real_images_accepted(self, fmt, ext):
        assert self._check(self._img(fmt), ext)

    @pytest.mark.parametrize("header,ext", [
        (b"\x89PNG\r\n\x1a\n" + b"basura" * 50, "png"),
        (b"\xff\xd8\xff" + b"X" * 100, "jpg"),
    ])
    def test_valid_header_corrupt_body_rejected(self, header, ext):
        assert not self._check(header, ext)

    # --- pdf ---
    def test_pdf_accepted_and_html_rejected(self):
        assert self._check(b"%PDF-1.7\n1 0 obj\n", "pdf")
        assert not self._check(b"<html><script>alert(1)</script>", "pdf")

    # --- doc/xls: familia OLE2, no se distinguen entre sí (documentado) ---
    def test_ole2_family_accepted_plain_text_rejected(self):
        assert self._check(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 16, "doc")
        assert not self._check(b"hola mundo esto no es un doc", "doc")
