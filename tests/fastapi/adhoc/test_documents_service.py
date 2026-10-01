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

El último bloque es el de A14, el **gate de edición**: hasta entonces el
``PATCH`` no lo llamaba nadie y corregir una errata pasaba por borrar el
documento y volverlo a subir. Al conectarlo hubo que decidir qué es editable, y
la decisión —solo 'Borrador' y 'Rechazado', nunca una versión superada, el
archivo solo en 'Borrador'— se prueba **en el service**, que es donde se impone:
``document_out`` publica los mismos flags para que el panel pinte el botón, pero
un botón deshabilitado no es un gate.

``db_session`` es la sesión transaccional de ``tests/fastapi/conftest.py``.
"""
import uuid
from datetime import date, datetime, timedelta
from io import BytesIO
from pathlib import Path

import pytest

from itcj2.apps.adhoc.models import (
    AdhocApprovalFlow,
    AdhocApprovalFlowStep,
    AdhocArea,
    AdhocDocument,
    AdhocDocumentAcknowledgement,
    AdhocDocumentCategory,
    AdhocDocumentVisibility,
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


# ==========================================================================
# A14 — el gate de edición: qué documento se puede tocar y cuándo
# ==========================================================================
#
# Hasta A14 el ``PATCH`` existía, tenía permiso propio y **no lo llamaba nadie**:
# los 202 documentos del SGC no se podían editar desde ninguna pantalla, así que
# un título mal escrito solo se arreglaba borrando el documento y volviéndolo a
# subir —perdiendo por el camino sus tareas y su archivo—. Al conectarlo hubo
# que decidir qué es editable, y la respuesta ISO es estrecha: **lo que ya pasó
# por el flujo de aprobación es inmutable**; se corrige anexando una versión
# nueva, no reescribiendo la aprobada.
#
# Tres reglas, y las tres viven en el SERVICE. Es la lección que dejó B1:
# `DOCUMENT_STATUSES_STARTABLE` existía desde la migración y solo la respetaba
# `documents-panel.js`, así que un POST a mano arrancaba un flujo sobre un
# documento obsoleto. Un botón deshabilitado no es un gate; esto sí.

def con_estado(db, doc, status, *, is_current=True):
    """Deja ``doc`` en el estado que interesa probar, sin pasar por ``update``.

    Se escribe a pelo a propósito: el motor de flujo hace exactamente eso
    (``document_flow_service`` y ``task_workflow_service`` asignan ``doc.status``
    directamente, nunca por el service), así que este atajo reproduce cómo llegan
    de verdad a la BD los 138 'Aprobado' y los 60 'Obsoleto' migrados.
    """
    doc.status = status
    doc.is_current = is_current
    db.flush()
    return doc


#: ``(status, is_current)`` -> ``(is_editable, file_replaceable)``. Es la tabla
#: de verdad completa del gate, y la comparte el serializador: ``document_out``
#: publica los dos flags para que el panel pinte el botón, pero quien manda es
#: ``update``. Están juntas en un solo sitio porque el riesgo real no es que una
#: de las dos se equivoque, sino que **divergan**: el panel ofrecería un
#: formulario que el servidor rechaza entero.
_MATRIZ_DE_EDICION = [
    # Editables: la punta de la cadena que aún no ha sido aprobada.
    ("Borrador",    True,  True,  True),
    # 'Rechazado' admite metadatos pero NO archivo: sus validadores rechazaron
    # *ese* PDF y la decisión quedó escrita en `adhoc_task_approvals`.
    ("Rechazado",   True,  True,  False),
    # Ya pasó (o está pasando) por el flujo: inmutable.
    ("Aprobado",    True,  False, False),
    ("En Revisión", True,  False, False),
    ("Obsoleto",    True,  False, False),
    # Versión superada: histórico del SGC. Ni siquiera un 'Borrador' se salva —
    # es el cruce que separa las dos reglas, porque con solo el gate de `status`
    # esta fila pasaría.
    ("Borrador",    False, False, False),
    ("Rechazado",   False, False, False),
    ("Aprobado",    False, False, False),
    ("Obsoleto",    False, False, False),
]


# --------------------------------------------------------------------------
# Regla 2 — solo se edita desde 'Borrador' y 'Rechazado'
# --------------------------------------------------------------------------

@pytest.mark.parametrize("status", ["Borrador", "Rechazado"])
def test_update_sobre_un_documento_editable_y_vigente_pasa(db_session, status):
    """La otra mitad del contrato: el gate no puede cerrar los 4 que sí se editan.

    Hoy son 4 de 202 documentos (los 4 en 'Borrador'; cero en 'Rechazado'). Es la
    cifra correcta, no un efecto colateral —lo aprobado se corrige anexando—,
    pero justamente por lo estrecha que es, cerrar de más aquí dejaría la app
    otra vez sin ninguna forma de arreglar una errata.
    """
    doc = SVC.bulk_create(
        db_session, [item(code="A14-OK", title="Original")], author_id=None,
    )[0]
    con_estado(db_session, doc, status)

    SVC.update(db_session, doc.id, DocumentUpdate(title="Corregido"))

    db_session.refresh(doc)
    assert doc.title == "Corregido"
    assert doc.status == status          # editar no mueve el estado
    assert doc.code == "A14-OK"


@pytest.mark.parametrize("status", ["Aprobado", "En Revisión", "Obsoleto"])
def test_update_sobre_un_estado_no_editable_es_conflicto_y_no_escribe_nada(
    db_session, status,
):
    """409 **y** la fila intacta. Un gate que lanza después de mutar no sirve.

    La relectura es la mitad que importa: si los guards estuvieran detrás del
    ``model_dump``, los ``setattr`` ya habrían ensuciado la sesión y el primer
    ``autoflush`` posterior —cualquier query del mismo request— escribiría el
    título nuevo en un documento que la API acaba de declarar inmutable.
    """
    doc = SVC.bulk_create(db_session, [item(title="Original")], author_id=None)[0]
    con_estado(db_session, doc, status)
    doc_id = doc.id

    with pytest.raises(AdhocConflict) as exc:
        SVC.update(db_session, doc_id, DocumentUpdate(title="Editado a la fuerza"))
    assert status in str(exc.value)      # el mensaje dice POR QUÉ, no "conflicto"

    # Ni en memoria: la sesión no puede quedar sucia. `expire_all` por sí solo no
    # bastaría —descarta los cambios pendientes en lugar de escribirlos, así que
    # taparía justo el fallo que se busca—, por eso primero se fuerza el flush.
    assert db_session.is_modified(doc) is False
    assert doc.title == "Original"

    db_session.flush()                   # lo que estuviera sucio se escribiría AQUÍ
    db_session.expire_all()
    recargado = db_session.query(AdhocDocument).filter_by(id=doc_id).one()
    assert recargado.title == "Original"
    assert recargado.status == status


# --------------------------------------------------------------------------
# Regla 1 — el histórico no se edita, aunque su estado lo permitiera
# --------------------------------------------------------------------------

def test_update_sobre_una_version_superada_es_conflicto_aunque_este_en_borrador(db_session):
    """El cruce que demuestra que hacen falta las DOS reglas, no una.

    ``('Borrador', is_current=False)`` es el único caso en el que el gate de
    ``status`` diría que sí: es la fila que pasaría si solo existiera la lista de
    estados editables. Y es histórico del SGC —alguien la sustituyó por una
    versión más nueva—, así que en una auditoría ISO 9001 tiene que seguir
    diciendo exactamente lo que decía cuando se firmó.

    Se llega a él por el camino normal del panel: anexar una versión deja la
    cadena anterior superada y obsoleta; aquí se le devuelve el 'Borrador' a mano
    para que el ÚNICO motivo de rechazo posible sea ``is_current=False``.
    """
    raiz = SVC.bulk_create(
        db_session, [item(code="A14-VER", title="Versión vieja")], author_id=None,
    )[0]
    anexar(db_session, raiz, code="A14-VER")
    db_session.expire_all()

    raiz = db_session.query(AdhocDocument).filter_by(id=raiz.id).one()
    assert raiz.is_current is False
    con_estado(db_session, raiz, "Borrador", is_current=False)

    with pytest.raises(AdhocConflict) as exc:
        SVC.update(db_session, raiz.id, DocumentUpdate(title="Reescribiendo el histórico"))
    assert "superada" in str(exc.value)

    assert db_session.is_modified(raiz) is False
    db_session.flush()
    db_session.expire_all()
    recargado = db_session.query(AdhocDocument).filter_by(id=raiz.id).one()
    assert recargado.title == "Versión vieja"


# --------------------------------------------------------------------------
# Regla 3 — el archivo solo se reemplaza en 'Borrador'
# --------------------------------------------------------------------------

def test_update_con_archivo_sobre_un_borrador_sustituye_el_adjunto(db_session, uploads_root):
    """La mitad permitida del gate de archivo: en 'Borrador' sí se reemplaza."""
    doc = SVC.bulk_create(
        db_session, [item()], author_id=None, uploads=[_FakeUpload("borrador.pdf")],
    )[0]
    con_estado(db_session, doc, "Borrador")
    viejo = uploads_root / "documents" / str(doc.id) / "borrador.pdf"

    SVC.update(db_session, doc.id, DocumentUpdate(), upload=_FakeUpload("corregido.pdf"))

    db_session.refresh(doc)
    assert doc.file_url == f"{doc.id}/corregido.pdf"
    assert (uploads_root / "documents" / str(doc.id) / "corregido.pdf").is_file()
    assert not viejo.exists()            # el reemplazo sí borra el anterior


def test_update_con_archivo_sobre_un_rechazado_es_conflicto_y_no_toca_el_disco(
    db_session, uploads_root,
):
    """El rechazo no puede dejar basura ni borrar nada.

    ``'Rechazado'`` es editable pero su archivo no: el reemplazo borra el binario
    anterior sin vuelta atrás y sus validadores rechazaron *ese* archivo por
    escrito. El guard corre **antes** de ``save_upload``, así que el directorio
    tiene que quedar exactamente como estaba: ni el nuevo escrito, ni el viejo
    borrado. Y como el 409 tumba la petición entera, el título tampoco cambia.
    """
    doc = SVC.bulk_create(
        db_session, [item(title="Original")], author_id=None,
        uploads=[_FakeUpload("rechazado.pdf")],
    )[0]
    con_estado(db_session, doc, "Rechazado")
    carpeta = uploads_root / "documents" / str(doc.id)

    with pytest.raises(AdhocConflict) as exc:
        SVC.update(
            db_session, doc.id,
            DocumentUpdate(title="Editado"),
            upload=_FakeUpload("colado.pdf"),
        )
    assert "Rechazado" in str(exc.value)

    assert [p.name for p in carpeta.iterdir()] == ["rechazado.pdf"]
    assert db_session.is_modified(doc) is False
    db_session.flush()
    db_session.expire_all()
    recargado = db_session.query(AdhocDocument).filter_by(id=doc.id).one()
    assert recargado.file_url == f"{doc.id}/rechazado.pdf"
    assert recargado.title == "Original"


def test_update_sin_archivo_sobre_un_rechazado_si_corrige_los_metadatos(
    db_session, uploads_root,
):
    """Los dos gates son independientes: metadatos sí, adjunto no.

    Es el caso de uso real del rechazo —el validador escribe "el código está
    mal", el autor lo arregla y lo vuelve a mandar a flujo—, y sería imposible si
    el gate de archivo se hubiera escrito como parte del gate de estado.
    """
    doc = SVC.bulk_create(
        db_session, [item(code="A14-MAL", title="Original")], author_id=None,
        uploads=[_FakeUpload("rechazado.pdf")],
    )[0]
    con_estado(db_session, doc, "Rechazado")

    SVC.update(db_session, doc.id, DocumentUpdate(code="A14-BIEN", title="Corregido"))

    db_session.refresh(doc)
    assert doc.code == "A14-BIEN"
    assert doc.title == "Corregido"
    assert doc.file_url == f"{doc.id}/rechazado.pdf"     # el adjunto, intacto
    assert (uploads_root / "documents" / str(doc.id) / "rechazado.pdf").is_file()


# --------------------------------------------------------------------------
# Coherencia — los flags que publica document_out y el gate que impone update
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "status,is_current,editable,archivo",
    _MATRIZ_DE_EDICION,
    ids=[f"{s}-{'vigente' if c else 'superada'}" for s, c, _, _ in _MATRIZ_DE_EDICION],
)
def test_document_out_publica_los_flags_que_el_service_impone(
    db_session, uploads_root, status, is_current, editable, archivo,
):
    """Mismo documento, mismo veredicto por los dos caminos.

    La regla está escrita dos veces —el gate de ``update`` y ``_editable`` de
    ``schemas.documents``— por la misma razón que la vigencia: el servidor la
    impone y el panel la pinta. Que **divergan** es el fallo caro, no que una se
    equivoque: el usuario vería el botón "Editar" encendido, rellenaría el
    formulario y recibiría un 409 al guardar.
    """
    doc = SVC.bulk_create(
        db_session, [item(title="Original")], author_id=None,
        uploads=[_FakeUpload("adjunto.pdf")],
    )[0]
    con_estado(db_session, doc, status, is_current=is_current)

    serializado = document_out(doc)
    assert serializado["is_editable"] is editable
    assert serializado["file_replaceable"] is archivo

    # Y lo prometido se cumple: `is_editable` predice si el PATCH de metadatos
    # pasa, y `file_replaceable` si además admite reemplazo de archivo.
    def intenta(**kw):
        try:
            SVC.update(db_session, doc.id, DocumentUpdate(title="Editado"), **kw)
            return True
        except AdhocConflict:
            return False

    assert intenta() is editable
    assert intenta(upload=_FakeUpload("otro.pdf")) is archivo


def test_file_replaceable_implica_is_editable():
    """La implicación de la que depende el panel.

    Sin ella ofrecería un ``<input type=file>`` dentro de un formulario que el
    servidor va a rechazar entero, que es la peor forma de enterarse.
    """
    for status, is_current, editable, archivo in _MATRIZ_DE_EDICION:
        assert not archivo or editable, (status, is_current)


# --------------------------------------------------------------------------
# El 409 explica la causa REAL, y la causa no es la misma para todos
# --------------------------------------------------------------------------
#
# El mensaje es lo único que la pantalla enseña: `documents-panel.js` pinta el
# `detail` del 409 tal cual. Si el texto inventa una historia, el usuario no
# tiene forma de saber qué le pasa de verdad a su documento.

def test_el_409_de_un_obsoleto_retirado_no_habla_de_una_aprobacion_que_no_hubo(
    db_session,
):
    """'Obsoleto' se alcanza también SIN flujo, por el camino que la app ofrece.

    ``DOCUMENT_STATUSES_VIA_PATCH`` incluye 'Obsoleto' justamente porque retirar
    un documento es una decisión legítima de Calidad, y ese PATCH no exige flujo
    ninguno. En los datos reales ya hay filas así (obsoletas con ``flow_id IS
    NULL``), y la población crece con cada borrador que Calidad retire.

    Aquí se recorre ese camino entero —dar de alta, retirar, intentar editar—
    sin tocar el motor de flujo, y se comprueba que el 409 no le achaca el
    bloqueo a una aprobación que nunca existió.
    """
    doc = SVC.bulk_create(
        db_session, [item(code="A14-RET", title="Borrador retirado")], author_id=None,
    )[0]

    # El retiro por PATCH: es lo que la constante declara como legítimo.
    SVC.update(db_session, doc.id, DocumentUpdate(status="Obsoleto"))
    db_session.refresh(doc)
    assert doc.status == "Obsoleto"
    assert doc.flow_id is None and doc.current_step_id is None   # nunca hubo flujo

    with pytest.raises(AdhocConflict) as exc:
        SVC.update(db_session, doc.id, DocumentUpdate(title="Recuperar"))

    mensaje = str(exc.value)
    assert "flujo de aprobación" not in mensaje, (
        "El 409 le achaca el bloqueo a una aprobación inexistente: este "
        f"documento nunca entró a un flujo. Mensaje: {mensaje}"
    )
    assert "terminal" in mensaje                 # la causa real, comprobable
    assert "Obsoleto" in mensaje
    assert "anexe una versión nueva" in mensaje  # y la salida, que sí funciona


def test_el_409_de_un_aprobado_si_habla_del_flujo(db_session):
    """La otra mitad: donde el flujo SÍ es la causa, el mensaje la nombra.

    Sin esta prueba, "arreglar" el mensaje anterior borrando la frase de todas
    partes pasaría desapercibido, y el 409 más frecuente —138 de 202 documentos
    están 'Aprobado'— dejaría de decir por qué lo aprobado no se reescribe.
    """
    doc = SVC.bulk_create(db_session, [item(title="Aprobado")], author_id=None)[0]
    con_estado(db_session, doc, "Aprobado")

    with pytest.raises(AdhocConflict) as exc:
        SVC.update(db_session, doc.id, DocumentUpdate(title="Editando lo aprobado"))
    assert "flujo de aprobación" in str(exc.value)


# --------------------------------------------------------------------------
# El gate del archivo mira la evidencia, no un `status` que él mismo escribe
# --------------------------------------------------------------------------

def con_flujo(db, doc):
    """Deja ``doc`` con ``flow_id``/``current_step_id`` puestos, como start_flow.

    Es el estado en que ``task_workflow_service`` deja un documento rechazado:
    escribe ``status='Rechazado'`` y **no limpia** ninguno de los dos, así que la
    fila sigue apuntando al paso que rechazó su archivo.
    """
    flow = AdhocApprovalFlow(name=f"e2e_flow_{uuid.uuid4().hex[:8]}")
    db.add(flow)
    db.flush()
    paso = AdhocApprovalFlowStep(
        flow_id=flow.id, name="Revisión", days_limit=3, step_order=1,
    )
    db.add(paso)
    db.flush()
    doc.flow_id = flow.id
    doc.current_step_id = paso.id
    db.flush()
    return doc


def test_el_rechazado_no_recupera_el_reemplazo_de_archivo_pasando_por_borrador(
    db_session, uploads_root,
):
    """El gate no se puede saltar repitiéndolo: dos PATCH no valen más que uno.

    Con el gate mirando solo el ``status`` de entrada bastaban dos llamadas, un
    solo actor y un solo permiso (``adhoc.documents.api.update``, que tienen
    admin y supervisor_doc): la primera escribe ``status='Borrador'``
    —permitido, porque 'Rechazado' es editable y 'Borrador' está en
    ``DOCUMENT_STATUSES_VIA_PATCH``—, la segunda manda el archivo y ya pasa. El
    resultado es exactamente lo que la constante dice impedir: filas de
    ``adhoc_task_approvals`` registrando por escrito el rechazo de un archivo que
    ya nadie puede ver, con ``flow_id``/``current_step_id`` intactos apuntando al
    paso que lo rechazó.
    """
    doc = SVC.bulk_create(
        db_session, [item(title="Rechazado")], author_id=None,
        uploads=[_FakeUpload("rechazado.pdf")],
    )[0]
    con_estado(db_session, doc, "Rechazado")
    con_flujo(db_session, doc)
    carpeta = uploads_root / "documents" / str(doc.id)

    # Paso 1: el lavado de estado. Sigue permitido —es una transición que el
    # endpoint declara— y por eso el gate del archivo no puede apoyarse en él.
    SVC.update(db_session, doc.id, DocumentUpdate(status="Borrador"))
    db_session.refresh(doc)
    assert doc.status == "Borrador"
    assert doc.flow_id is not None and doc.current_step_id is not None

    # Paso 2: el reemplazo. Aquí es donde tiene que cerrarse.
    with pytest.raises(AdhocConflict) as exc:
        SVC.update(db_session, doc.id, DocumentUpdate(), upload=_FakeUpload("colado.pdf"))
    assert "circuló" in str(exc.value)

    assert [q.name for q in carpeta.iterdir()] == ["rechazado.pdf"]
    db_session.expire_all()
    recargado = db_session.query(AdhocDocument).filter_by(id=doc.id).one()
    assert recargado.file_url == f"{doc.id}/rechazado.pdf"


def test_el_borrador_que_nunca_entro_a_flujo_si_reemplaza_su_archivo(
    db_session, uploads_root,
):
    """La otra mitad: el gate nuevo no puede cerrarle la puerta al caso normal.

    Un borrador recién dado de alta —y el que nace al anexar una versión, que
    tampoco lleva flujo— es justo el documento que la pantalla deja corregir.
    """
    doc = SVC.bulk_create(
        db_session, [item()], author_id=None, uploads=[_FakeUpload("borrador.pdf")],
    )[0]
    assert doc.flow_id is None and doc.current_step_id is None

    SVC.update(db_session, doc.id, DocumentUpdate(), upload=_FakeUpload("corregido.pdf"))

    db_session.refresh(doc)
    assert doc.file_url == f"{doc.id}/corregido.pdf"


def test_document_out_tampoco_le_ofrece_el_archivo_al_que_ya_circulo(
    db_session, uploads_root,
):
    """Las dos copias de la regla siguen coincidiendo con la condición nueva.

    ``is_editable`` no cambia —un 'Borrador' se edita— pero ``file_replaceable``
    sí: si el serializador no mirara el flujo, el panel pintaría el
    ``<input type=file>`` de un formulario cuyo envío el servidor rechaza
    entero, que es la peor forma de enterarse.
    """
    doc = SVC.bulk_create(
        db_session, [item(title="Con flujo")], author_id=None,
        uploads=[_FakeUpload("adjunto.pdf")],
    )[0]
    con_estado(db_session, doc, "Borrador")
    con_flujo(db_session, doc)

    serializado = document_out(doc)
    assert serializado["is_editable"] is True
    assert serializado["file_replaceable"] is False

    SVC.update(db_session, doc.id, DocumentUpdate(title="Corregido"))   # metadatos, sí
    with pytest.raises(AdhocConflict):
        SVC.update(db_session, doc.id, DocumentUpdate(), upload=_FakeUpload("otro.pdf"))


# --------------------------------------------------------------------------
# La divergencia que el <select> del modal tiene que sobrevivir
# --------------------------------------------------------------------------

def test_el_area_dada_de_baja_sale_del_catalogo_pero_sigue_en_el_documento(db_session):
    """Las dos mitades del gotcha 22, medidas contra la BD.

    El panel llena sus desplegables con ``_document_catalogs``, que **filtra las
    áreas por ``is_active``**; la relación del documento no filtra nada —dar de
    baja un área no la desengancha de sus documentos—, así que ``document_out``
    sigue trayendo la suya. Esa asimetría es correcta en las dos puntas: un área
    retirada no debe ofrecerse para documentos nuevos, y el histórico no puede
    perder la que ya tenía.

    Lo que la hace peligrosa es la tercera pieza, la de abajo: en este PATCH un
    ``''`` **limpia la columna**. Un ``<select>`` que no encuentre su valor cae
    al placeholder y manda exactamente eso, así que corregir una errata del
    título borraría el área. Por eso ``makeCatalogSelect`` conserva el valor
    guardado como opción propia; este test es la razón de que exista.
    """
    from itcj2.apps.adhoc.pages.documents import _document_catalogs

    area = make_area(db_session)
    doc = SVC.bulk_create(
        db_session, [item(title="Con área", area_id=area.id)], author_id=None,
    )[0]

    area.is_active = False
    db_session.flush()

    catalogo = [fila["id"] for fila in _document_catalogs(db_session)["areas"]]
    assert area.id not in catalogo          # el desplegable ya no la ofrece

    serializado = document_out(doc)
    assert serializado["area"]["id"] == area.id
    assert serializado["area"]["name"] == area.name     # y trae el nombre: el
    #                                                     rótulo de la opción

    # La tercera pieza: el vacío no es "no la toques", es "bórrala".
    SVC.update(db_session, doc.id, DocumentUpdate(area_id=""))
    db_session.refresh(doc)
    assert doc.area_id is None

# ==========================================================================
# B6 — acknowledgement_panel: la difusión del documento y sus acuses
# ==========================================================================
#
# Hallazgo A9. Dos tablas con datos y cero lecturas: ``adhoc_document_visibility``
# (9 390 filas, 55 usuarios, 198 de los 202 documentos) y
# ``adhoc_document_acknowledgements`` (987 acuses con fecha real, de 2019-11-15 a
# 2025-02-12). La ISO 9001:2015 §7.5.3 exige controlar la **distribución** de la
# información documentada; esto es esa evidencia, y solo eso: aquí no se
# registran acuses nuevos.
#
# Lo que se prueba en el service —y no en la API— son las tres decisiones que
# hacen que el número signifique algo: de dónde sale la colección (de la
# visibilidad, no de los acuses), cómo se cruza el par y qué se dice cuando el
# llamante no pudo resolver quién tiene acceso hoy.

def difundir(db, doc, *users):
    """Lista de distribución: a quién le tocaba conocer el documento."""
    for u in users:
        db.add(AdhocDocumentVisibility(document_id=doc.id, user_id=u.id))
    db.flush()


def acusar(db, doc, user, when=datetime(2020, 2, 3, 8, 45)):
    """Acuse con fecha REAL.

    ``acknowledged_at`` es NOT NULL a propósito en el modelo: un acuse sin fecha
    no sostiene una auditoría, así que aquí tampoco se siembra ninguno sin ella.
    """
    db.add(AdhocDocumentAcknowledgement(
        document_id=doc.id, user_id=user.id, acknowledged_at=when,
    ))
    db.flush()


def persona(db, first, last):
    """Usuario con apellido controlado: el orden del panel es por apellido."""
    tag = uuid.uuid4().hex[:10]
    u = User(
        first_name=first, last_name=last,
        username=f"e2e_adhoc_dif_{tag}",
        email=f"e2e_adhoc_dif_{tag}@test.local",
    )
    db.add(u)
    db.flush()
    return u


def documento(db, **kw):
    return SVC.bulk_create(db, [item(**kw)], author_id=None)[0]


def test_panel_de_difusion_inexistente_es_404(db_session):
    with pytest.raises(LookupError):
        SVC.acknowledgement_panel(db_session, 99999999)


def test_la_coleccion_sale_de_la_visibilidad_no_de_los_acuses(db_session):
    """Partir de los acuses contestaría solo por los 61 documentos que tienen alguno.

    La lista de distribución es la **pregunta** ("a quién le tocaba conocer este
    documento") y el acuse es la respuesta. Con la colección al revés, el 89.5 %
    de los pares que no acusaron —justo lo que una auditoría viene a mirar—
    quedaría invisible.
    """
    doc = documento(db_session)
    acusa = persona(db_session, "Ana", "AAA")
    calla = persona(db_session, "Beto", "BBB")
    difundir(db_session, doc, acusa, calla)
    acusar(db_session, doc, acusa)

    panel = SVC.acknowledgement_panel(db_session, doc.id)

    assert [f["user"].id for f in panel["recipients"]] == [acusa.id, calla.id]
    assert panel["summary"]["assigned"] == 2
    assert panel["summary"]["acknowledged"] == 1
    assert panel["summary"]["pending"] == 1


def test_un_acuse_sin_fila_de_visibilidad_no_aparece(db_session):
    """La invariante documentada del ``LEFT JOIN``, fijada como test.

    Hoy se cumple —0 de 987 acuses quedan fuera de la visibilidad— y es coherente
    con el origen, porque el SGC legacy solo difundía a quien tenía el documento
    asignado; pero **no la garantiza ninguna FK**. Este test es lo que hará
    ruido el día que se implemente el registro de acuses nuevos: o el alta crea
    las dos filas, o esta consulta pasa a partir de la unión de ambas tablas.
    """
    doc = documento(db_session)
    en_la_lista = persona(db_session, "Ana", "AAA")
    fuera_de_la_lista = persona(db_session, "Beto", "BBB")
    difundir(db_session, doc, en_la_lista)
    acusar(db_session, doc, fuera_de_la_lista)

    panel = SVC.acknowledgement_panel(db_session, doc.id)

    assert [f["user"].id for f in panel["recipients"]] == [en_la_lista.id]
    assert panel["summary"]["acknowledged"] == 0


def test_cada_destinatario_sale_una_vez_y_con_un_acuse_como_mucho(db_session):
    """El par ``(document_id, user_id)`` es ``UNIQUE`` en las dos tablas.

    Es lo que sostiene el ``LEFT JOIN``: sin esa unicidad, un documento con
    varias filas de visibilidad por persona duplicaría destinatarios y el
    denominador de la cobertura dejaría de ser el número de personas.
    """
    doc = documento(db_session)
    otro = documento(db_session)
    ana = persona(db_session, "Ana", "AAA")
    difundir(db_session, doc, ana)
    difundir(db_session, otro, ana)
    acusar(db_session, doc, ana)
    acusar(db_session, otro, ana, when=datetime(2024, 9, 9, 12, 0))

    panel = SVC.acknowledgement_panel(db_session, doc.id)

    assert len(panel["recipients"]) == 1
    assert panel["recipients"][0]["acknowledged_at"] == datetime(2020, 2, 3, 8, 45)


def test_el_orden_es_el_de_los_pickers(db_session):
    """``last_name, first_name, id`` — el mismo de ``_picker_rows``.

    La lista de destinatarios se lee buscando un nombre; ordenar por acuse
    movería de sitio a una persona cada vez que alguien acusa.
    """
    doc = documento(db_session)
    zeta = persona(db_session, "Ana", "ZZZ")
    alfa_b = persona(db_session, "Beto", "AAA")
    alfa_a = persona(db_session, "Ana", "AAA")
    difundir(db_session, doc, zeta, alfa_b, alfa_a)
    acusar(db_session, doc, zeta)

    panel = SVC.acknowledgement_panel(db_session, doc.id)

    assert [f["user"].id for f in panel["recipients"]] == [alfa_a.id, alfa_b.id, zeta.id]


def test_el_resumen_redondea_la_cobertura_a_un_decimal(db_session):
    """1 de 3 es 33.3, no 33 ni 33.333333333333336.

    El porcentaje lo calcula el servidor porque es el número que se enseña como
    cobertura de difusión, y una división en el navegador es también una
    división entre cero el día que el documento no tenga destinatarios.
    """
    doc = documento(db_session)
    uno = persona(db_session, "Ana", "AAA")
    dos = persona(db_session, "Beto", "BBB")
    tres = persona(db_session, "Cruz", "CCC")
    difundir(db_session, doc, uno, dos, tres)
    acusar(db_session, doc, uno)

    assert SVC.acknowledgement_panel(db_session, doc.id)["summary"]["coverage_pct"] == 33.3


def test_sin_destinatarios_no_hay_division_entre_cero(db_session):
    """4 de los 202 documentos no tienen lista de distribución. No es un error."""
    doc = documento(db_session)

    panel = SVC.acknowledgement_panel(db_session, doc.id)

    assert panel["recipients"] == []
    assert panel["summary"]["assigned"] == 0
    assert panel["summary"]["pending"] == 0
    assert panel["summary"]["coverage_pct"] == 0.0


def test_con_el_conjunto_de_acceso_se_marca_y_se_cuenta(db_session):
    """La marca no filtra: los 26 de 55 que ya no entran siguen en la lista."""
    doc = documento(db_session)
    dentro = persona(db_session, "Ana", "AAA")
    fuera = persona(db_session, "Beto", "BBB")
    difundir(db_session, doc, dentro, fuera)

    panel = SVC.acknowledgement_panel(db_session, doc.id, app_user_ids={dentro.id})

    por_usuario = {f["user"].id: f for f in panel["recipients"]}
    assert por_usuario[dentro.id]["has_app_access"] is True
    assert por_usuario[fuera.id]["has_app_access"] is False
    assert panel["summary"]["without_access"] == 1
    assert panel["summary"]["assigned"] == 2


def test_sin_el_conjunto_no_se_afirma_nada_sobre_el_acceso(db_session):
    """``None``, no ``False``: la misma prudencia que ``serialize_task``.

    Quien llama es ``api/documents``, que resuelve el conjunto con
    ``_app_user_ids``; si no hay fila de ``adhoc`` en ``core_apps`` devuelve
    ``None`` y el panel se sirve igual —un acuse de 2021 no deja de ser
    evidencia porque el servidor no pueda decir quién entra hoy—. El
    serializador omite las dos claves cuando valen ``None``.
    """
    doc = documento(db_session)
    ana = persona(db_session, "Ana", "AAA")
    difundir(db_session, doc, ana)

    panel = SVC.acknowledgement_panel(db_session, doc.id)

    assert panel["recipients"][0]["has_app_access"] is None
    assert panel["summary"]["without_access"] is None
    # Lo que sí se sabe no se calla.
    assert panel["summary"]["assigned"] == 1


def test_el_panel_no_recorta_la_cadena_de_versiones(db_session):
    """Aquí no aplica el filtro de control documental de las dos listas.

    Se entra por un documento concreto y lo que se pregunta es a quién se le
    distribuyó **ese**. 2 679 de las 9 390 filas de visibilidad apuntan a una
    versión superada: si el panel las escondiera, esa evidencia volvería a no
    tener ninguna pantalla, que es el hallazgo del que venimos.
    """
    raiz = documento(db_session, title="Manual")
    nueva = anexar(db_session, raiz, title="Manual")
    ana = persona(db_session, "Ana", "AAA")
    difundir(db_session, raiz, ana)
    acusar(db_session, raiz, ana)

    # `_supersede_chain` actualiza en lote con `synchronize_session=False` y la
    # sesión del harness es `expire_on_commit=False`: sin releer, el objeto de
    # la raíz seguiría diciendo `is_current=True` en Python.
    db_session.expire_all()
    superada = SVC.acknowledgement_panel(db_session, raiz.id)
    vigente = SVC.acknowledgement_panel(db_session, nueva.id)

    assert superada["document"].is_current is False
    assert superada["summary"]["assigned"] == 1
    assert superada["summary"]["acknowledged"] == 1
    # Y la vigente no hereda la difusión de su raíz.
    assert vigente["summary"]["assigned"] == 0
