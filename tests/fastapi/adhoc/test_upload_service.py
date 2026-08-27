"""Tests del servicio de uploads de adhoc.

Escritos ANTES del service (TDD). Cubren los cuatro agujeros del legacy
documentados en ``docs/adhoc/analysis/src_api.md`` §3:

1. sin whitelist de extensiones,
2. sin límite de tamaño,
3. colisión de nombre = sobrescritura silenciosa,
4. rutas sin ``safe_join`` (traversal) y directorio plano relativo al CWD.

El service se aísla del ``Settings`` real parcheando ``upload_service._settings``
(el módulo fuente, no el consumidor) para que todo se escriba en ``tmp_path``.
"""
from io import BytesIO
from pathlib import Path

import pytest

from itcj2.apps.adhoc.services import upload_service


class _FakeSettings:
    """Settings mínimo con solo lo que lee el upload_service."""

    def __init__(self, root: Path):
        self.ADHOC_UPLOAD_PATH = str(root)
        self.ADHOC_MAX_FILE_SIZE = 1024
        self.ADHOC_ALLOWED_EXTENSIONS = "pdf,png,txt"


class _FakeUpload:
    """Duck-type de ``fastapi.UploadFile`` (filename / file / content_type)."""

    def __init__(self, filename, content: bytes = b"contenido", content_type="application/pdf"):
        self.filename = filename
        self.content_type = content_type
        self.file = BytesIO(content)


@pytest.fixture
def settings(tmp_path, monkeypatch):
    fake = _FakeSettings(tmp_path)
    monkeypatch.setattr(upload_service, "_settings", lambda: fake)
    return fake


# --------------------------------------------------------------------------
# resolve_dir
# --------------------------------------------------------------------------

def test_resolve_dir_cuelga_de_adhoc_upload_path(settings, tmp_path):
    d = upload_service.resolve_dir("documents", 7)
    assert d == tmp_path / "documents" / "7"
    assert d.is_absolute()


@pytest.mark.parametrize("kind", ["documents", "program_events", "task_comments", "indicators"])
def test_resolve_dir_acepta_los_cuatro_kinds(settings, kind):
    assert upload_service.resolve_dir(kind, 1).name == "1"


def test_resolve_dir_rechaza_kind_desconocido(settings):
    with pytest.raises(ValueError):
        upload_service.resolve_dir("../../etc", 1)


@pytest.mark.parametrize("entity_id", ["../..", "/etc", "1/../..", 0, -3, "abc"])
def test_resolve_dir_rechaza_entity_id_invalido(settings, entity_id):
    with pytest.raises(ValueError):
        upload_service.resolve_dir("documents", entity_id)


def test_resolve_dir_crea_el_directorio_solo_si_se_pide(settings):
    d = upload_service.resolve_dir("documents", 42)
    assert not d.exists()
    d2 = upload_service.resolve_dir("documents", 42, create=True)
    assert d2.is_dir()


# --------------------------------------------------------------------------
# save_upload — validaciones
# --------------------------------------------------------------------------

def test_save_upload_devuelve_ruta_relativa(settings, tmp_path):
    info = upload_service.save_upload("documents", 3, _FakeUpload("manual.pdf"))

    assert info["file_path"] == "3/manual.pdf"
    assert not Path(info["file_path"]).is_absolute()
    assert info["original_name"] == "manual.pdf"
    assert info["size_bytes"] == len(b"contenido")
    assert info["mime_type"] == "application/pdf"
    assert (tmp_path / "documents" / "3" / "manual.pdf").read_bytes() == b"contenido"


def test_save_upload_rechaza_extension_fuera_de_whitelist(settings, tmp_path):
    with pytest.raises(ValueError) as exc:
        upload_service.save_upload("documents", 3, _FakeUpload("shell.php"))

    assert "php" in str(exc.value) or "permitid" in str(exc.value).lower()
    assert not (tmp_path / "documents" / "3").exists()


def test_save_upload_rechaza_archivo_sin_extension(settings):
    with pytest.raises(ValueError):
        upload_service.save_upload("documents", 3, _FakeUpload("sinextension"))


def test_save_upload_rechaza_tamano_excedido(settings, tmp_path):
    grande = _FakeUpload("grande.pdf", content=b"x" * (settings.ADHOC_MAX_FILE_SIZE + 1))

    with pytest.raises(ValueError) as exc:
        upload_service.save_upload("documents", 3, grande)

    assert "MB" in str(exc.value) or "tama" in str(exc.value).lower()
    assert not (tmp_path / "documents" / "3" / "grande.pdf").exists()


@pytest.mark.parametrize("nombre", [
    "../evil.pdf",
    "../../../../etc/passwd.pdf",
    "..\\evil.pdf",
    "/etc/passwd.pdf",
    "C:\\Windows\\evil.pdf",
    "evil\x00.pdf",
    "sub/dir/evil.pdf",
])
def test_save_upload_rechaza_path_traversal(settings, nombre, tmp_path):
    with pytest.raises(ValueError):
        upload_service.save_upload("documents", 3, _FakeUpload(nombre))

    # Nada escrito fuera (ni dentro) de la raíz de uploads.
    escritos = [p for p in tmp_path.rglob("*") if p.is_file()]
    assert escritos == []


def test_save_upload_rechaza_nombre_vacio(settings):
    with pytest.raises(ValueError):
        upload_service.save_upload("documents", 3, _FakeUpload(""))


# --------------------------------------------------------------------------
# save_upload — colisión de nombres (bug #3 del legacy)
# --------------------------------------------------------------------------

def test_save_upload_colision_agrega_sufijo_y_no_sobrescribe(settings, tmp_path):
    primero = upload_service.save_upload("documents", 5, _FakeUpload("evidencia.pdf", content=b"uno"))
    segundo = upload_service.save_upload("documents", 5, _FakeUpload("evidencia.pdf", content=b"dos"))
    tercero = upload_service.save_upload("documents", 5, _FakeUpload("evidencia.pdf", content=b"tres"))

    assert primero["file_path"] == "5/evidencia.pdf"
    assert segundo["file_path"] != primero["file_path"]
    assert tercero["file_path"] not in (primero["file_path"], segundo["file_path"])
    assert segundo["file_path"].endswith(".pdf")

    base = tmp_path / "documents" / "5"
    assert (base / "evidencia.pdf").read_bytes() == b"uno"
    assert len([p for p in base.iterdir() if p.is_file()]) == 3
    # El nombre original se conserva aunque el del disco cambie.
    assert segundo["original_name"] == "evidencia.pdf"


def test_save_upload_indicadores_no_comparte_directorio_plano(settings, tmp_path):
    a = upload_service.save_upload("indicators", 1, _FakeUpload("evidencia.pdf", content=b"a"))
    b = upload_service.save_upload("indicators", 2, _FakeUpload("evidencia.pdf", content=b"b"))

    assert a["file_path"] == "1/evidencia.pdf"
    assert b["file_path"] == "2/evidencia.pdf"
    assert (tmp_path / "indicators" / "1" / "evidencia.pdf").read_bytes() == b"a"
    assert (tmp_path / "indicators" / "2" / "evidencia.pdf").read_bytes() == b"b"


# --------------------------------------------------------------------------
# open_download
# --------------------------------------------------------------------------

def test_open_download_devuelve_la_ruta_del_archivo(settings, tmp_path):
    info = upload_service.save_upload("task_comments", 9, _FakeUpload("nota.txt", content=b"hola"))
    nombre = info["file_path"].split("/")[-1]

    ruta = upload_service.open_download("task_comments", 9, nombre)

    assert ruta == tmp_path / "task_comments" / "9" / nombre
    assert ruta.read_bytes() == b"hola"


@pytest.mark.parametrize("nombre", [
    "../../../etc/passwd",
    "..\\..\\secreto.pdf",
    "/etc/passwd",
    "C:\\Windows\\win.ini",
    "nota\x00.txt",
])
def test_open_download_rechaza_path_traversal(settings, nombre):
    with pytest.raises(ValueError):
        upload_service.open_download("task_comments", 9, nombre)


def test_open_download_archivo_inexistente(settings):
    with pytest.raises(ValueError):
        upload_service.open_download("documents", 3, "no-existe.pdf")


def test_open_stored_resuelve_la_ruta_relativa_de_bd(settings, tmp_path):
    info = upload_service.save_upload("documents", 11, _FakeUpload("acta.pdf", content=b"z"))

    ruta = upload_service.open_stored("documents", info["file_path"])

    assert ruta.read_bytes() == b"z"


@pytest.mark.parametrize("guardado", ["../../etc/passwd", "/etc/passwd", "11/../../x.pdf"])
def test_open_stored_rechaza_valores_envenenados(settings, guardado):
    with pytest.raises(ValueError):
        upload_service.open_stored("documents", guardado)


# --------------------------------------------------------------------------
# delete_file
# --------------------------------------------------------------------------

def test_delete_file_borra_y_es_idempotente(settings, tmp_path):
    info = upload_service.save_upload("program_events", 4, _FakeUpload("plano.png", content=b"p"))

    assert upload_service.delete_file("program_events", info["file_path"]) is True
    assert not (tmp_path / "program_events" / "4" / "plano.png").exists()
    assert upload_service.delete_file("program_events", info["file_path"]) is False


def test_delete_file_no_borra_fuera_de_la_raiz(settings, tmp_path):
    externo = tmp_path.parent / "victima.txt"
    externo.write_text("no me borres")

    assert upload_service.delete_file("documents", "../../victima.txt") is False
    assert externo.exists()


# --------------------------------------------------------------------------
# download_name
# --------------------------------------------------------------------------
# Un Content-Disposition sin extension deja al usuario con un archivo que el
# sistema no sabe abrir. Paso justo con los adjuntos migrados del SGC legacy:
# `original_name` traia la etiqueta descriptiva del proveedor ('NOTIFICACION
# VR-01' para el archivo VR-01.xls), y el navegador guardaba 'NOTIFICACION
# VR-01', a secas.

def test_download_name_respeta_el_nombre_original_si_ya_trae_extension():
    ruta = Path("/app/instance/apps/adhoc/program_events/11/minuta_2016.pdf")
    assert upload_service.download_name(ruta, "Minuta de acuerdos.pdf") == "Minuta de acuerdos.pdf"


def test_download_name_pega_la_extension_del_archivo_real():
    ruta = Path("/app/instance/apps/adhoc/incidents/15/VR-01.xls")
    assert upload_service.download_name(ruta, "NOTIFICACION VR-01") == "NOTIFICACION VR-01.xls"


def test_download_name_cae_al_nombre_en_disco_si_no_hay_original():
    ruta = Path("/app/instance/apps/adhoc/documents/202/tortuga.xlsx")
    for vacio in (None, "", "   "):
        assert upload_service.download_name(ruta, vacio) == "tortuga.xlsx"


def test_download_name_no_duplica_la_extension_por_mayusculas():
    ruta = Path("/app/instance/apps/adhoc/documents/7/LISTA.DOC")
    assert upload_service.download_name(ruta, "Lista de aspirantes.doc") == "Lista de aspirantes.doc"


def test_download_name_con_archivo_sin_extension_devuelve_el_original():
    ruta = Path("/app/instance/apps/adhoc/documents/9/sin_extension")
    assert upload_service.download_name(ruta, "Informe anual") == "Informe anual"
