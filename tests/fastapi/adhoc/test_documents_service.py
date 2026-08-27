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

Los dos bloques del final cubren lo que trajo el control documental (B1) sobre
los 202 documentos reales: la **cadena de versiones** (``only_current``,
``list_versions``, el anexado que supera la cadena entera) y los **tres cubos de
vigencia**, que tienen que ser disjuntos y exhaustivos y coincidir bit a bit con
el ``expiry_state`` que pinta el badge —el filtro SQL y la aritmética de
``schemas.documents._expiry`` son dos implementaciones del mismo criterio, y una
auditoría ISO 9001 no perdona que discrepen.

``db_session`` es la sesión transaccional de ``tests/fastapi/conftest.py``.
"""
import uuid
from datetime import date, timedelta
from io import BytesIO
from pathlib import Path

import pytest

from itcj2.apps.adhoc.models import (
    AdhocArea,
    AdhocDocument,
    AdhocDocumentCategory,
    AdhocTask,
)
from itcj2.apps.adhoc.schemas.documents import (
    DocumentCreate,
    DocumentFilters,
    DocumentUpdate,
    document_out,
)
from itcj2.apps.adhoc.services import upload_service
from itcj2.apps.adhoc.services.document_service import (
    AdhocConflict,
    AdhocDocumentService as SVC,
)
from itcj2.apps.adhoc.utils.constants import DOCUMENT_EXPIRY_SOON_DAYS
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


# ==========================================================================
# Cadena de versiones — only_current, list_versions y el anexado
# ==========================================================================
#
# La forma real de los datos (verificada en la BD): estructura **plana** de
# profundidad 1 —``parent_id`` apunta siempre a la raíz, cero filas con un
# padre que a su vez tenga padre—, 144 cadenas y **exactamente una** fila
# ``is_current`` en cada una. Todo lo de aquí abajo defiende esa invariante:
# es lo único que permite que las dos listas oculten las 58 versiones
# superadas sin esconder por accidente la vigente.

def anexar(db, base, **kw):
    """Anexa una versión nueva a la cadena de ``base`` y devuelve el documento.

    Es exactamente lo que hace el botón "Anexar nueva versión" del panel de
    gestión: el mismo ``bulk_create`` del alta con un ``parent_id`` de más.
    """
    kw.setdefault("title", f"e2e_ver_{uuid.uuid4().hex[:8]}")
    return SVC.bulk_create(db, [item(parent_id=base.id, **kw)], author_id=None)[0]


def test_list_documents_oculta_por_defecto_las_versiones_superadas(db_session):
    """Sin decir nada, la lista devuelve solo la punta de la cadena."""
    area = make_area(db_session)
    raiz = SVC.bulk_create(
        db_session, [item(code="VER-1", version="1.0", area_id=area.id)], author_id=None,
    )[0]
    nueva = anexar(db_session, raiz, code="VER-1", version="2.0", area_id=area.id)

    page = SVC.list_documents(db_session, DocumentFilters(area_id=area.id), page=1, per_page=20)
    assert page.total == 1
    assert [d.id for d in page.items] == [nueva.id]


def test_list_documents_con_only_current_false_incluye_las_superadas(db_session):
    """Es el checkbox "Ver versiones anteriores" de la barra de filtros."""
    area = make_area(db_session)
    raiz = SVC.bulk_create(
        db_session, [item(code="VER-2", area_id=area.id)], author_id=None,
    )[0]
    nueva = anexar(db_session, raiz, code="VER-2", area_id=area.id)

    page = SVC.list_documents(
        db_session, DocumentFilters(area_id=area.id, only_current=False),
        page=1, per_page=20,
    )
    assert page.total == 2
    assert {d.id for d in page.items} == {raiz.id, nueva.id}


def test_only_current_coacciona_lo_que_manda_el_query_string(db_session):
    """``?only_current=`` vacío o ausente vale ``True``; ``false``/``0`` lo apagan.

    Un checkbox sin marcar no manda nada y un formulario reenviado manda el
    parámetro vacío: los dos casos tienen que significar "solo las vigentes",
    no un 422.
    """
    assert DocumentFilters().only_current is True
    assert DocumentFilters(only_current="").only_current is True
    assert DocumentFilters(only_current=None).only_current is True
    assert DocumentFilters(only_current="true").only_current is True
    assert DocumentFilters(only_current="false").only_current is False
    assert DocumentFilters(only_current="0").only_current is False
    assert DocumentFilters(only_current=False).only_current is False


def test_anexar_version_cuelga_de_la_raiz_y_supera_la_cadena_entera(db_session):
    """Las tres cosas del anexado, de golpe y en la misma transacción."""
    area = make_area(db_session)
    raiz = SVC.bulk_create(
        db_session, [item(code="VER-3", version="1.0", area_id=area.id)], author_id=None,
    )[0]
    hija = anexar(db_session, raiz, code="VER-3", version="2.0", area_id=area.id)
    # Se anexa sobre la HIJA: el puntero tiene que normalizarse a la raíz, no
    # quedarse en el padre inmediato, o la cadena dejaría de ser plana.
    nieta = anexar(db_session, hija, code="VER-3", version="3.0", area_id=area.id)

    assert hija.parent_id == raiz.id
    assert nieta.parent_id == raiz.id
    assert nieta.is_current is True

    # `_supersede_chain` actualiza en lote con `synchronize_session=False`, y la
    # sesión del harness es `expire_on_commit=False`: hay que releer, igual que
    # hace en producción el commit del request.
    db_session.expire_all()
    cadena = SVC.list_versions(db_session, raiz.id)
    assert [d.id for d in cadena] == [raiz.id, hija.id, nieta.id]
    assert [d.is_current for d in cadena] == [False, False, True]
    assert [d.status for d in cadena] == ["Obsoleto", "Obsoleto", "Borrador"]


def test_anexar_deja_exactamente_una_punta_en_la_cadena(db_session):
    """La invariante que sostiene todo: una sola fila ``is_current`` por cadena."""
    area = make_area(db_session)
    raiz = SVC.bulk_create(db_session, [item(area_id=area.id)], author_id=None)[0]
    for _ in range(3):
        anexar(db_session, raiz, area_id=area.id)

    db_session.expire_all()
    cadena = SVC.list_versions(db_session, raiz.id)
    assert len(cadena) == 4
    assert sum(1 for d in cadena if d.is_current) == 1


def test_bulk_create_con_parent_id_inexistente_es_400(db_session):
    """400 con mensaje, no el ``IntegrityError`` a 500 del legacy."""
    antes = db_session.query(AdhocDocument).count()
    with pytest.raises(ValueError):
        SVC.bulk_create(db_session, [item(parent_id=99_999_999)], author_id=None)
    db_session.rollback()
    assert db_session.query(AdhocDocument).count() == antes


def test_bulk_create_sin_parent_id_nace_vigente_y_sin_padre(db_session):
    """No regresión: el alta normal sigue siendo raíz de su propia cadena."""
    doc = SVC.bulk_create(db_session, [item()], author_id=None)[0]
    assert doc.parent_id is None
    assert doc.is_current is True


def test_list_versions_devuelve_la_cadena_con_la_raiz_primero(db_session):
    raiz = SVC.bulk_create(db_session, [item(code="VER-4")], author_id=None)[0]
    v2 = anexar(db_session, raiz, code="VER-4")
    v3 = anexar(db_session, v2, code="VER-4")

    assert [d.id for d in SVC.list_versions(db_session, raiz.id)] == [raiz.id, v2.id, v3.id]


def test_list_versions_desde_un_hijo_devuelve_la_cadena_completa(db_session):
    """El caso que importa: el modal se abre desde la fila visible, que es la punta."""
    raiz = SVC.bulk_create(db_session, [item(code="VER-5")], author_id=None)[0]
    v2 = anexar(db_session, raiz, code="VER-5")
    v3 = anexar(db_session, v2, code="VER-5")

    esperado = [raiz.id, v2.id, v3.id]
    assert [d.id for d in SVC.list_versions(db_session, v3.id)] == esperado
    assert [d.id for d in SVC.list_versions(db_session, v2.id)] == esperado
    assert [d.id for d in SVC.list_versions(db_session, raiz.id)] == esperado


def test_list_versions_de_un_documento_suelto_devuelve_una_sola_fila(db_session):
    doc = SVC.bulk_create(db_session, [item()], author_id=None)[0]
    assert [d.id for d in SVC.list_versions(db_session, doc.id)] == [doc.id]


def test_list_versions_de_un_id_inexistente_es_404(db_session):
    with pytest.raises(LookupError):
        SVC.list_versions(db_session, 99_999_999)


def test_list_versions_no_ordena_por_la_columna_version(db_session):
    """``version`` es ``String(10)``, así que ordenar por ella es ordenar texto.

    La cadena se da de alta en el orden natural de un documento que ya lleva
    diez revisiones —``1.0``, ``2.0``, …, ``10.0``—, que es donde el historial
    de verdad importa. Ordenado por id (lo correcto: cronológico de alta) sale
    ``1.0 → 2.0 → 10.0``; ordenado por la columna ``version`` Postgres compara
    texto y ``'10.0' < '2.0'``, así que saldría ``1.0 → 10.0 → 2.0``. Las dos
    aserciones de abajo separan un caso del otro.
    """
    raiz = SVC.bulk_create(db_session, [item(code="VER-6", version="1.0")], author_id=None)[0]
    segunda = anexar(db_session, raiz, code="VER-6", version="2.0")
    decima = anexar(db_session, segunda, code="VER-6", version="10.0")

    cadena = SVC.list_versions(db_session, raiz.id)
    assert [d.id for d in cadena] == [raiz.id, segunda.id, decima.id]
    assert [d.version for d in cadena] == ["1.0", "2.0", "10.0"]
    assert [d.version for d in cadena] != ["1.0", "10.0", "2.0"]


def test_update_no_puede_mover_la_cadena_de_versiones(db_session):
    """``is_current`` y ``parent_id`` no son campos del PATCH: ``extra="ignore"``.

    Si se pudieran escribir por aquí, una edición cualquiera dejaría cadenas con
    dos puntas o con ninguna y la lista —que oculta las superadas— pasaría a
    mentir sobre cuál es el documento vigente.
    """
    raiz = SVC.bulk_create(db_session, [item(code="VER-7")], author_id=None)[0]
    nueva = anexar(db_session, raiz, code="VER-7")

    payload = DocumentUpdate(title="Editada", is_current=False, parent_id=raiz.id)
    enviados = payload.model_dump(exclude_unset=True)
    assert "is_current" not in enviados
    assert "parent_id" not in enviados

    SVC.update(db_session, nueva.id, payload)
    db_session.refresh(nueva)
    assert nueva.title == "Editada"
    assert nueva.is_current is True
    assert nueva.parent_id == raiz.id


# --------------------------------------------------------------------------
# El anexado y el flujo de aprobación
# --------------------------------------------------------------------------
#
# `status='Obsoleto'` es TERMINAL, así que la cadena que se supera no puede
# quedarse con tareas de flujo vivas: son tareas de un documento que las dos
# listas ya ocultan, y aprobarlas devuelve la versión superada a 'Aprobado',
# deshaciendo el 'Obsoleto' que el anexado acababa de escribir.

def tarea_de_flujo(db, doc, status="En Revisión"):
    """Una tarea de aprobación viva sobre ``doc``, como la que crea ``start_flow``.

    Va con ``commit`` y no con ``flush`` a propósito: ``bulk_create`` hace
    ``rollback`` cuando el anexado se rechaza, y una tarea solo *flusheada* se
    iría con él —dejando el test sin la fila cuya supervivencia quiere probar—.
    Con el commit se comporta como la tarea real, que ya estaba en la BD antes
    de que nadie intentara anexar.
    """
    tarea = AdhocTask(
        description=f"Aprobar Documento: {doc.title}",
        status=status,
        priority="Alta",
        document_id=doc.id,
    )
    db.add(tarea)
    db.commit()
    return tarea


@pytest.mark.parametrize("status_tarea", ["En Revisión", "En Espera"])
def test_anexar_version_con_el_flujo_en_curso_es_conflicto(db_session, status_tarea):
    """409 y **nada** se toca: ni la cadena, ni la tarea del validador."""
    raiz = SVC.bulk_create(db_session, [item(code="VER-F1")], author_id=None)[0]
    tarea = tarea_de_flujo(db_session, raiz, status_tarea)

    with pytest.raises(AdhocConflict):
        anexar(db_session, raiz, code="VER-F1")

    db_session.refresh(raiz)
    db_session.refresh(tarea)
    assert raiz.is_current is True          # sigue siendo la vigente
    assert raiz.status == "Borrador"        # no se marcó obsoleta a medias
    assert tarea.status == status_tarea     # la tarea del validador sigue igual
    assert SVC.list_versions(db_session, raiz.id) == [raiz]


def test_anexar_version_mira_la_cadena_entera_no_solo_la_punta(db_session):
    """La tarea viva puede colgar de cualquier versión, no solo de la que se anexa."""
    raiz = SVC.bulk_create(db_session, [item(code="VER-F2")], author_id=None)[0]
    punta = anexar(db_session, raiz, code="VER-F2")
    tarea_de_flujo(db_session, raiz)        # la tarea viva es de la RAÍZ

    with pytest.raises(AdhocConflict):
        anexar(db_session, punta, code="VER-F2")


@pytest.mark.parametrize("status_tarea", ["Completada", "Rechazada"])
def test_anexar_version_con_el_flujo_ya_cerrado_si_procede(db_session, status_tarea):
    """Cerrado el flujo, el anexado vuelve a ser el camino normal.

    Es la otra mitad del contrato: el 409 bloquea el flujo **en curso**, no el
    historial de un documento que ya pasó por aprobación —que son casi todos.
    """
    raiz = SVC.bulk_create(db_session, [item(code="VER-F3")], author_id=None)[0]
    tarea_de_flujo(db_session, raiz, status_tarea)

    nueva = anexar(db_session, raiz, code="VER-F3")

    db_session.refresh(raiz)
    assert nueva.is_current is True
    assert raiz.is_current is False
    assert raiz.status == "Obsoleto"


def test_delete_de_la_raiz_con_versiones_anexadas_es_conflicto(db_session):
    """Sin este guard es un ``ForeignKeyViolation`` → 500 sin mensaje.

    ``fk_adhoc_documents_parent_id`` no tiene ``ON DELETE``, así que Postgres
    rechaza el borrado de la raíz mientras cuelgue de ella una versión. El
    camino es real desde el panel: anexar crea la cadena, "Ver versiones
    anteriores" enseña la raíz y su fila trae la papelera como cualquier otra.
    """
    raiz = SVC.bulk_create(db_session, [item(code="VER-F4")], author_id=None)[0]
    anexar(db_session, raiz, code="VER-F4")

    with pytest.raises(AdhocConflict) as exc:
        SVC.delete(db_session, raiz.id)
    assert "raíz" in str(exc.value)
    # El guard corre ANTES de tocar la sesión: no hay nada que revertir.
    assert db_session.get(AdhocDocument, raiz.id) is not None


def test_delete_de_una_version_anexada_si_procede(db_session):
    """Solo la raíz está protegida: la punta se borra y la cadena se acorta."""
    raiz = SVC.bulk_create(db_session, [item(code="VER-F5")], author_id=None)[0]
    nueva = anexar(db_session, raiz, code="VER-F5")

    SVC.delete(db_session, nueva.id)

    assert db_session.get(AdhocDocument, nueva.id) is None
    assert [d.id for d in SVC.list_versions(db_session, raiz.id)] == [raiz.id]


# ==========================================================================
# Vigencia — los tres cubos
# ==========================================================================
#
# `vencidos` / `por_vencer_30d` / `vigentes` son **disjuntos y exhaustivos**:
# cada documento cae en uno y solo uno, incluidos los que no tienen
# `expiration_date` (que son "vigentes": no hay vigencia que controlar). Los
# bordes son lo único que se puede equivocar aquí —un `<` donde va un `<=`—,
# así que se prueban los cinco: ayer, hoy, hoy+30, hoy+31 y NULL.

#: `expiry_state` de `document_out` <-> cubo del filtro SQL. Son dos
#: implementaciones del mismo criterio (aritmética en Python contra predicado
#: en Postgres) y el badge de la tabla se pinta con la primera mientras el
#: filtro usa la segunda: si divergen, el usuario ve un badge rojo en una fila
#: que el filtro "vencidos" no devuelve.
_CUBO_POR_ESTADO = {
    "vencido": "vencidos",
    "por_vencer": "por_vencer_30d",
    "vigente": "vigentes",
    None: "vigentes",
}


@pytest.fixture
def cubos_de_vigencia(db_session):
    """Los cinco casos frontera de ``expiration_date``, todos en la misma área.

    El área recién creada es el aislante: la BD de desarrollo tiene 202
    documentos reales (197 con vigencia, 47 vencidos), así que un filtro sin
    acotar no diría nada.
    """
    hoy = date.today()
    area = make_area(db_session)
    fechas = {
        "ayer": hoy - timedelta(days=1),
        "hoy": hoy,
        "limite": hoy + timedelta(days=DOCUMENT_EXPIRY_SOON_DAYS),
        "pasado_limite": hoy + timedelta(days=DOCUMENT_EXPIRY_SOON_DAYS + 1),
        "sin_fecha": None,
    }
    docs = SVC.bulk_create(
        db_session,
        [item(area_id=area.id, expiration_date=fecha) for fecha in fechas.values()],
        author_id=None,
    )
    return area, dict(zip(fechas, docs))


def _ids_del_cubo(db, area, cubo):
    page = SVC.list_documents(
        db, DocumentFilters(area_id=area.id, expiring=cubo), page=1, per_page=50,
    )
    return {d.id for d in page.items}


def test_los_tres_cubos_de_vigencia_reparten_los_bordes(db_session, cubos_de_vigencia):
    area, docs = cubos_de_vigencia
    assert _ids_del_cubo(db_session, area, "vencidos") == {docs["ayer"].id}
    assert _ids_del_cubo(db_session, area, "por_vencer_30d") == {
        docs["hoy"].id, docs["limite"].id,
    }
    assert _ids_del_cubo(db_session, area, "vigentes") == {
        docs["pasado_limite"].id, docs["sin_fecha"].id,
    }


def test_los_tres_cubos_de_vigencia_son_disjuntos_y_exhaustivos(db_session, cubos_de_vigencia):
    """Cada documento cae en exactamente uno de los tres, y entre los tres están todos."""
    area, docs = cubos_de_vigencia
    vencidos = _ids_del_cubo(db_session, area, "vencidos")
    por_vencer = _ids_del_cubo(db_session, area, "por_vencer_30d")
    vigentes = _ids_del_cubo(db_session, area, "vigentes")

    assert vencidos & por_vencer == set()
    assert por_vencer & vigentes == set()
    assert vencidos & vigentes == set()
    assert vencidos | por_vencer | vigentes == {d.id for d in docs.values()}
    assert len(vencidos) + len(por_vencer) + len(vigentes) == len(docs)


def test_expiry_state_coincide_con_el_cubo_que_devuelve_el_sql(db_session, cubos_de_vigencia):
    """El badge y el filtro no pueden discrepar: misma fila, mismo veredicto."""
    area, docs = cubos_de_vigencia
    por_cubo = {
        cubo: _ids_del_cubo(db_session, area, cubo)
        for cubo in ("vencidos", "por_vencer_30d", "vigentes")
    }
    for nombre, doc in docs.items():
        estado = document_out(doc)["expiry_state"]
        assert doc.id in por_cubo[_CUBO_POR_ESTADO[estado]], nombre


def test_el_hoy_se_inyecta_de_fuera_en_las_dos_implementaciones(db_session, cubos_de_vigencia):
    """El criterio de vigencia está escrito dos veces —SQL y aritmética— y las
    dos tienen que poder recibir el MISMO "hoy".

    Cada una con su ``date.today()`` funcionaba el 99,99% del tiempo y fallaba
    en la ventana en que la petición cruza la medianoche: el ``WHERE`` decide
    con el día de ayer y el badge con el de hoy, y la lista devuelve una fila
    cuyo ``expiry_state`` contradice al filtro que la trajo. Aquí el reloj se
    adelanta más allá del documento que vencía "pasado el límite" (hoy + 30 + 1):
    con ese "hoy" tiene que caer en el cubo ``vencidos`` **y** serializarse como
    ``'vencido'``, las dos cosas.
    """
    area, docs = cubos_de_vigencia
    futuro = date.today() + timedelta(days=DOCUMENT_EXPIRY_SOON_DAYS + 2)

    page = SVC.list_documents(
        db_session,
        DocumentFilters(area_id=area.id, expiring="vencidos"),
        page=1, per_page=50, today=futuro,
    )
    assert docs["pasado_limite"].id in {d.id for d in page.items}
    assert document_out(docs["pasado_limite"], today=futuro)["expiry_state"] == "vencido"
    # Sin inyectarlo, el mismo documento sigue siendo el de siempre.
    assert document_out(docs["pasado_limite"])["expiry_state"] == "vigente"


def test_document_out_calcula_los_dias_que_faltan_para_vencer(db_session, cubos_de_vigencia):
    """``days_to_expire`` es negativo si ya venció y ``None`` si no hay fecha."""
    _, docs = cubos_de_vigencia
    assert document_out(docs["ayer"])["days_to_expire"] == -1
    assert document_out(docs["ayer"])["is_expired"] is True
    assert document_out(docs["hoy"])["days_to_expire"] == 0
    assert document_out(docs["hoy"])["is_expired"] is False
    assert document_out(docs["limite"])["days_to_expire"] == DOCUMENT_EXPIRY_SOON_DAYS
    assert document_out(docs["sin_fecha"])["days_to_expire"] is None
    assert document_out(docs["sin_fecha"])["expiry_state"] is None
    assert document_out(docs["sin_fecha"])["is_expired"] is False


def test_update_acepta_expiration_date_y_un_vacio_la_limpia(db_session):
    """Quitarle la vigencia a un documento es una edición legítima, no un error."""
    doc = SVC.bulk_create(db_session, [item()], author_id=None)[0]
    assert doc.expiration_date is None

    vence = date.today() + timedelta(days=45)
    SVC.update(db_session, doc.id, DocumentUpdate(expiration_date=vence))
    db_session.refresh(doc)
    assert doc.expiration_date == vence
    assert document_out(doc)["expiry_state"] == "vigente"

    # El `""` del <input type="date"> vaciado: `AdhocSchema` lo vuelve `None`,
    # pero el campo queda *set*, así que el `exclude_unset` sí lo aplica.
    payload = DocumentUpdate(expiration_date="")
    assert "expiration_date" in payload.model_dump(exclude_unset=True)
    SVC.update(db_session, doc.id, payload)
    db_session.refresh(doc)
    assert doc.expiration_date is None
    assert document_out(doc)["expiry_state"] is None


def test_update_sin_expiration_date_no_borra_la_que_ya_tenia(db_session):
    """``exclude_unset``: un PATCH que no la menciona no puede vaciarla."""
    vence = date.today() + timedelta(days=10)
    doc = SVC.bulk_create(db_session, [item(expiration_date=vence)], author_id=None)[0]
    SVC.update(db_session, doc.id, DocumentUpdate(title="Solo el título"))
    db_session.refresh(doc)
    assert doc.expiration_date == vence
