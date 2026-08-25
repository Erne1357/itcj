"""Tests de ``document_service`` (Adhoc / Calidad). Escritos ANTES del service.

Lo que se está probando no es "CRUD funciona", sino los arreglos concretos que
el plan pide sobre ``api_docs.save_documents`` y compañía:

* el alta masiva ya **no traga excepciones y redirige "exitosa"**: una FK
  inventada es un 400 y **nada** se persiste;
* el archivo se guarda por ``upload_service`` (whitelist, límite, sin
  sobrescritura) y la columna guarda la ruta **relativa** ``{id}/{nombre}``;
* borrar un documento borra también su archivo (el legacy dejaba huérfanos);
* la descarga de un documento sin adjunto es un **404 JSON**, no el texto plano
  ``"El documento no tiene archivo adjunto."`` que devolvía el legacy.

``db_session`` es la sesión transaccional de ``tests/fastapi/conftest.py``.
"""
import uuid
from io import BytesIO
from pathlib import Path

import pytest

from itcj2.apps.adhoc.models import (
    AdhocArea,
    AdhocDocument,
    AdhocDocumentCategory,
)
from itcj2.apps.adhoc.schemas.documents import (
    DocumentCreate,
    DocumentFilters,
    DocumentUpdate,
)
from itcj2.apps.adhoc.services import upload_service
from itcj2.apps.adhoc.services.document_service import AdhocDocumentService as SVC
from itcj2.core.models.user import User


# --------------------------------------------------------------------------
# Fixtures y factories locales
# --------------------------------------------------------------------------

class _FakeSettings:
    def __init__(self, root: Path):
        self.ADHOC_UPLOAD_PATH = str(root)
        self.ADHOC_MAX_FILE_SIZE = 1024 * 1024
        self.ADHOC_ALLOWED_EXTENSIONS = "pdf,png,txt"


class _FakeUpload:
    """Duck-type de ``fastapi.UploadFile``."""

    def __init__(self, filename, content=b"contenido", content_type="application/pdf"):
        self.filename = filename
        self.content_type = content_type
        self.file = BytesIO(content)


@pytest.fixture
def uploads_root(tmp_path, monkeypatch):
    monkeypatch.setattr(upload_service, "_settings", lambda: _FakeSettings(tmp_path))
    return tmp_path


def make_user(db, label="autor"):
    tag = uuid.uuid4().hex[:10]
    u = User(
        first_name=label.upper(), last_name="ADHOC",
        username=f"e2e_adhoc_{label}_{tag}",
        email=f"e2e_adhoc_{label}_{tag}@test.local",
    )
    db.add(u)
    db.flush()
    return u


def make_area(db):
    a = AdhocArea(name=f"e2e_area_{uuid.uuid4().hex[:8]}")
    db.add(a)
    db.flush()
    return a


def make_category(db):
    c = AdhocDocumentCategory(name=f"e2e_cat_{uuid.uuid4().hex[:8]}")
    db.add(c)
    db.flush()
    return c


def item(**kw):
    kw.setdefault("title", f"e2e_doc_{uuid.uuid4().hex[:8]}")
    return DocumentCreate(**kw)


# ==========================================================================
# bulk_create
# ==========================================================================

def test_bulk_create_persiste_los_documentos_con_defaults(db_session):
    autor = make_user(db_session)
    docs = SVC.bulk_create(
        db_session,
        [item(code="MC-01", title="Manual"), item(code="PR-02", title="Procedimiento")],
        author_id=autor.id,
    )
    assert len(docs) == 2
    assert all(d.id is not None for d in docs)
    assert all(d.status == "Borrador" for d in docs)
    assert all(d.version == "1.0" for d in docs)
    assert all(d.author_id == autor.id for d in docs)


def test_bulk_create_rechaza_lista_vacia(db_session):
    with pytest.raises(ValueError):
        SVC.bulk_create(db_session, [], author_id=None)


def test_bulk_create_rechaza_fk_inexistente_y_no_persiste_nada(db_session):
    antes = db_session.query(AdhocDocument).count()
    with pytest.raises(ValueError):
        SVC.bulk_create(db_session, [item(area_id=99_999_999)], author_id=None)
    db_session.rollback()
    assert db_session.query(AdhocDocument).count() == antes


def test_bulk_create_acepta_las_fk_validas(db_session):
    area, cat = make_area(db_session), make_category(db_session)
    docs = SVC.bulk_create(
        db_session, [item(area_id=area.id, category_id=cat.id)], author_id=None,
    )
    assert docs[0].area_id == area.id
    assert docs[0].category_id == cat.id


def test_bulk_create_ignora_un_autor_que_no_existe_en_core_users(db_session):
    """El legacy logueaba y guardaba como Sistema; se conserva el comportamiento."""
    docs = SVC.bulk_create(db_session, [item()], author_id=99_999_999)
    assert docs[0].author_id is None


def test_bulk_create_guarda_el_archivo_con_ruta_relativa(db_session, uploads_root):
    docs = SVC.bulk_create(
        db_session, [item(title="Con archivo")], author_id=None,
        uploads=[_FakeUpload("evidencia.pdf")],
    )
    doc = docs[0]
    assert doc.file_url == f"{doc.id}/evidencia.pdf"
    assert (uploads_root / "documents" / str(doc.id) / "evidencia.pdf").is_file()


def test_bulk_create_rechaza_extension_fuera_de_la_whitelist(db_session, uploads_root):
    with pytest.raises(ValueError):
        SVC.bulk_create(
            db_session, [item()], author_id=None,
            uploads=[_FakeUpload("shell.php", content_type="application/x-php")],
        )


def test_bulk_create_ignora_los_slots_de_archivo_vacios(db_session, uploads_root):
    """Un ``<input type=file>`` sin elegir manda una parte con filename vacío."""
    docs = SVC.bulk_create(
        db_session,
        [item(title="Sin archivo"), item(title="Con archivo")],
        author_id=None,
        uploads=[_FakeUpload(""), _FakeUpload("ok.pdf")],
    )
    assert docs[0].file_url is None
    assert docs[1].file_url == f"{docs[1].id}/ok.pdf"


# ==========================================================================
# Listado y filtros
# ==========================================================================

def test_list_documents_filtra_por_status_y_area(db_session):
    area = make_area(db_session)
    SVC.bulk_create(db_session, [
        item(title="e2e_uno", area_id=area.id),
        item(title="e2e_dos"),
    ], author_id=None)
    otro = db_session.query(AdhocDocument).filter_by(title="e2e_uno").one()
    otro.status = "Aprobado"
    db_session.flush()

    page = SVC.list_documents(
        db_session, DocumentFilters(area_id=area.id, status="Aprobado"),
        page=1, per_page=20,
    )
    assert page.total == 1
    assert page.items[0].id == otro.id


def test_list_documents_busca_por_codigo_y_titulo(db_session):
    SVC.bulk_create(db_session, [
        item(code="ZZQ-777", title="Instructivo de prueba"),
    ], author_id=None)
    por_codigo = SVC.list_documents(db_session, DocumentFilters(q="zzq-77"), page=1, per_page=20)
    por_titulo = SVC.list_documents(
        db_session, DocumentFilters(q="Instructivo de prueba"), page=1, per_page=20,
    )
    assert por_codigo.total == 1
    assert por_titulo.total >= 1


def test_list_documents_pagina(db_session):
    SVC.bulk_create(db_session, [item() for _ in range(5)], author_id=None)
    page = SVC.list_documents(db_session, DocumentFilters(), page=1, per_page=2)
    assert len(page.items) == 2
    assert page.pages >= 3


# ==========================================================================
# get / update / delete
# ==========================================================================

def test_get_documento_inexistente_es_404(db_session):
    with pytest.raises(LookupError):
        SVC.get(db_session, 99_999_999)


def test_update_aplica_solo_los_campos_enviados(db_session):
    doc = SVC.bulk_create(db_session, [item(code="A-1", title="Original")], author_id=None)[0]
    SVC.update(db_session, doc.id, DocumentUpdate(title="Editado"))
    db_session.refresh(doc)
    assert doc.title == "Editado"
    assert doc.code == "A-1"


def test_update_rechaza_titulo_vacio(db_session):
    doc = SVC.bulk_create(db_session, [item(title="Original")], author_id=None)[0]
    with pytest.raises(ValueError):
        SVC.update(db_session, doc.id, DocumentUpdate(title="   "))


def test_update_rechaza_fk_inexistente(db_session):
    doc = SVC.bulk_create(db_session, [item()], author_id=None)[0]
    with pytest.raises(ValueError):
        SVC.update(db_session, doc.id, DocumentUpdate(process_id=99_999_999))


def test_update_reemplaza_el_archivo_y_borra_el_anterior(db_session, uploads_root):
    doc = SVC.bulk_create(
        db_session, [item()], author_id=None, uploads=[_FakeUpload("viejo.pdf")],
    )[0]
    viejo = uploads_root / "documents" / str(doc.id) / "viejo.pdf"
    assert viejo.is_file()

    SVC.update(db_session, doc.id, DocumentUpdate(), upload=_FakeUpload("nuevo.pdf"))
    db_session.refresh(doc)
    assert doc.file_url == f"{doc.id}/nuevo.pdf"
    assert not viejo.exists()


def test_delete_borra_el_documento_y_su_archivo(db_session, uploads_root):
    doc = SVC.bulk_create(
        db_session, [item()], author_id=None, uploads=[_FakeUpload("adj.pdf")],
    )[0]
    doc_id = doc.id
    ruta = uploads_root / "documents" / str(doc_id) / "adj.pdf"
    SVC.delete(db_session, doc_id)
    assert db_session.get(AdhocDocument, doc_id) is None
    assert not ruta.exists()


def test_delete_inexistente_es_404(db_session):
    with pytest.raises(LookupError):
        SVC.delete(db_session, 99_999_999)


# ==========================================================================
# Descarga
# ==========================================================================

def test_resolve_download_devuelve_ruta_y_nombre(db_session, uploads_root):
    doc = SVC.bulk_create(
        db_session, [item()], author_id=None, uploads=[_FakeUpload("informe.pdf")],
    )[0]
    path, name = SVC.resolve_download(db_session, doc.id)
    assert path.is_file()
    assert name == "informe.pdf"


def test_resolve_download_sin_adjunto_es_404(db_session, uploads_root):
    doc = SVC.bulk_create(db_session, [item()], author_id=None)[0]
    with pytest.raises(LookupError):
        SVC.resolve_download(db_session, doc.id)
