"""Tests del service de eventos de programa (calendario del SGC).

Escritos ANTES del service (TDD). Cada bloque cubre un bug real del legacy
documentado en ``docs/adhoc/analysis/src_api.md``:

- **#18** — los adjuntos no se registraban en BD (``os.listdir``) y no se
  borraban al eliminar el evento: quedaban huérfanos en disco.
- **duplicate** — folio ``f"{folio}-COPY"`` colisiona al duplicar dos veces y
  la copia perdía ``location`` y ``real_date`` (``api_programs.py:133``).
- **lote abortado a medias** — ``strptime`` sin ``try`` y ``except Exception``
  que tragaba el error: el usuario veía un redirect "exitoso" sin datos.
- **sin whitelist de extensión** en los adjuntos.

Se usa la BD real (fixture ``db_session``, transacción con rollback) en vez de
``MagicMock``: el service vive de queries (paginación, filtros, cascada de
archivos) que un mock no puede verificar. Los adjuntos se escriben en
``tmp_path`` parcheando ``upload_service._settings`` — el **módulo fuente**,
que es el que lee la config en cada llamada.
"""
import uuid
from datetime import date
from io import BytesIO

import pytest

from itcj2.apps.adhoc.models import (
    AdhocArea,
    AdhocProcess,
    AdhocProgramCategory,
    AdhocProgramEvent,
    AdhocProgramEventFile,
)
from itcj2.apps.adhoc.schemas.programs import (
    ProgramEventCreate,
    ProgramEventFilters,
    ProgramEventUpdate,
)
from itcj2.apps.adhoc.services import program_event_service as svc
from itcj2.apps.adhoc.services import upload_service


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------

class _FakeSettings:
    def __init__(self, root):
        self.ADHOC_UPLOAD_PATH = str(root)
        self.ADHOC_MAX_FILE_SIZE = 1024 * 1024
        self.ADHOC_ALLOWED_EXTENSIONS = "pdf,png,txt"


class _FakeUpload:
    """Duck-type de ``fastapi.UploadFile``."""

    def __init__(self, filename, content=b"contenido", content_type="application/pdf"):
        self.filename = filename
        self.content_type = content_type
        self.file = BytesIO(content)


@pytest.fixture()
def uploads_root(tmp_path, monkeypatch):
    monkeypatch.setattr(upload_service, "_settings", lambda: _FakeSettings(tmp_path))
    return tmp_path


@pytest.fixture()
def catalogs(db_session):
    """Un área, un proceso y una categoría, con nombres únicos por test."""
    tag = uuid.uuid4().hex[:8]
    area = AdhocArea(name="e2e_area_" + tag, color="#111111")
    process = AdhocProcess(name="e2e_proc_" + tag, color="#222222")
    category = AdhocProgramCategory(name="e2e_cat_" + tag)
    db_session.add_all([area, process, category])
    db_session.flush()
    return {"area": area, "process": process, "category": category}


def _create(db, **kwargs):
    """Atajo: crea UN evento vía el service y lo devuelve."""
    payload = {"title": "Evento de prueba"}
    payload.update(kwargs)
    return svc.bulk_create(db, [ProgramEventCreate(**payload)])[0]


# --------------------------------------------------------------------------
# bulk_create
# --------------------------------------------------------------------------

def test_bulk_create_persiste_varios_eventos_con_defaults(db_session):
    created = svc.bulk_create(db_session, [
        ProgramEventCreate(title="Auditoria interna"),
        ProgramEventCreate(title="Revision por la direccion", priority="Alta"),
    ])

    assert len(created) == 2
    assert [e.title for e in created] == ["Auditoria interna", "Revision por la direccion"]
    # Vocabularios cerrados: el legacy escribia None aqui (radio sin marcar).
    assert created[0].priority == "Media"
    assert created[0].status == "Planeado"
    assert created[1].priority == "Alta"
    assert all(e.id is not None for e in created)


def test_bulk_create_acepta_las_tres_fechas_como_date(db_session):
    event = _create(
        db_session,
        start_date=date(2026, 3, 1),
        commitment_date=date(2026, 3, 31),
        real_date=date(2026, 3, 20),
    )
    assert event.start_date == date(2026, 3, 1)
    assert event.commitment_date == date(2026, 3, 31)
    assert event.real_date == date(2026, 3, 20)


def test_bulk_create_registra_los_adjuntos_en_bd_y_en_disco(db_session, uploads_root):
    created = svc.bulk_create(
        db_session,
        [ProgramEventCreate(title="Con adjuntos"), ProgramEventCreate(title="Sin adjuntos")],
        files_by_index={0: [_FakeUpload("evidencia.pdf"), _FakeUpload("acta.txt")]},
    )
    event = created[0]

    rows = db_session.query(AdhocProgramEventFile).filter_by(event_id=event.id).all()
    assert len(rows) == 2, "bug #18: el legacy no registraba los archivos en BD"
    assert {r.original_name for r in rows} == {"evidencia.pdf", "acta.txt"}
    assert all(r.file_path.startswith(str(event.id) + "/") for r in rows)
    for row in rows:
        assert upload_service.open_stored("program_events", row.file_path).is_file()

    assert db_session.query(AdhocProgramEventFile).filter_by(event_id=created[1].id).count() == 0


def test_bulk_create_rechaza_extension_fuera_de_whitelist_sin_dejar_rastro(db_session, uploads_root):
    antes = db_session.query(AdhocProgramEvent).count()

    with pytest.raises(ValueError) as exc:
        svc.bulk_create(
            db_session,
            [ProgramEventCreate(title="Malicioso")],
            files_by_index={0: [_FakeUpload("shell.php", content_type="application/x-php")]},
        )

    assert "php" in str(exc.value).lower()
    # Ni evento ni archivo: el lote es atomico (el legacy dejaba el archivo en
    # disco aunque el commit posterior fallara).
    assert db_session.query(AdhocProgramEvent).count() == antes
    assert not list(uploads_root.rglob("*.php"))


def test_bulk_create_exige_al_menos_un_evento(db_session):
    with pytest.raises(ValueError):
        svc.bulk_create(db_session, [])


# --------------------------------------------------------------------------
# list_events / get_event
# --------------------------------------------------------------------------

def test_list_events_pagina_y_ordena_por_id_descendente(db_session):
    svc.bulk_create(db_session, [ProgramEventCreate(title="Evento " + str(i)) for i in range(5)])

    page1 = svc.list_events(db_session, ProgramEventFilters(), page=1, per_page=2)
    assert len(page1.items) == 2
    assert page1.total >= 5
    assert page1.items[0].id > page1.items[1].id


def test_list_events_filtra_por_status_area_y_texto(db_session, catalogs):
    area = catalogs["area"]
    svc.bulk_create(db_session, [
        ProgramEventCreate(title="Simulacro de incendio", area_id=area.id, status="Completado"),
        ProgramEventCreate(title="Capacitacion ISO", area_id=area.id, status="Planeado"),
        ProgramEventCreate(title="Simulacro de sismo", status="Completado"),
    ])

    solo_area = svc.list_events(db_session, ProgramEventFilters(area_id=area.id), page=1, per_page=50)
    assert solo_area.total == 2

    completados = svc.list_events(
        db_session, ProgramEventFilters(area_id=area.id, status="Completado"), page=1, per_page=50
    )
    assert [e.title for e in completados.items] == ["Simulacro de incendio"]

    por_texto = svc.list_events(
        db_session, ProgramEventFilters(area_id=area.id, search="simulacro"), page=1, per_page=50
    )
    assert [e.title for e in por_texto.items] == ["Simulacro de incendio"]


def test_list_events_filtra_por_rango_de_fechas(db_session, catalogs):
    area = catalogs["area"]
    svc.bulk_create(db_session, [
        ProgramEventCreate(title="Enero", area_id=area.id, start_date=date(2026, 1, 15)),
        ProgramEventCreate(title="Junio", area_id=area.id, start_date=date(2026, 6, 15)),
        ProgramEventCreate(title="Sin fecha", area_id=area.id),
    ])

    result = svc.list_events(
        db_session,
        ProgramEventFilters(area_id=area.id, date_from=date(2026, 5, 1), date_to=date(2026, 12, 31)),
        page=1, per_page=50,
    )
    assert [e.title for e in result.items] == ["Junio"]


def test_get_event_inexistente_lanza_event_not_found(db_session):
    with pytest.raises(svc.EventNotFound):
        svc.get_event(db_session, 99_999_999)


# --------------------------------------------------------------------------
# update_event
# --------------------------------------------------------------------------

def test_update_event_solo_toca_los_campos_enviados(db_session):
    event = _create(db_session, title="Original", location="Aula Magna", priority="Alta")

    updated = svc.update_event(
        db_session, event.id, ProgramEventUpdate.model_validate({"title": "Renombrado"})
    )

    assert updated.title == "Renombrado"
    assert updated.location == "Aula Magna"
    assert updated.priority == "Alta"


def test_update_event_limpia_una_nullable_con_cadena_vacia(db_session):
    event = _create(db_session, location="Aula Magna")
    updated = svc.update_event(
        db_session, event.id, ProgramEventUpdate.model_validate({"location": ""})
    )
    assert updated.location is None


def test_update_event_ignora_null_explicito_en_columnas_not_null(db_session):
    """``priority``/``status`` son NOT NULL: un null explicito no debe reventar."""
    event = _create(db_session, priority="Urgente", status="En Proceso")

    updated = svc.update_event(
        db_session, event.id,
        ProgramEventUpdate.model_validate({"priority": None, "status": None, "title": "Sigue vivo"}),
    )

    assert updated.priority == "Urgente"
    assert updated.status == "En Proceso"
    assert updated.title == "Sigue vivo"


def test_update_event_inexistente_lanza_event_not_found(db_session):
    with pytest.raises(svc.EventNotFound):
        svc.update_event(db_session, 99_999_999, ProgramEventUpdate(title="X"))


def test_update_event_title_vacio_lanza_valueerror(db_session):
    """D2: ``title`` es NOT NULL sin default razonable — a diferencia de
    ``priority``/``status`` (que se ignoran cuando llegan en ``None``), un
    ``""`` en ``title`` se rechaza en vez de escribir NULL y reventar con
    ``IntegrityError`` (500 sin traducir)."""
    event = _create(db_session, title="Original")

    with pytest.raises(ValueError):
        svc.update_event(db_session, event.id, ProgramEventUpdate.model_validate({"title": ""}))

    db_session.expire(event)
    assert event.title == "Original"


# --------------------------------------------------------------------------
# Validación de FKs (D5)
# --------------------------------------------------------------------------

def test_bulk_create_con_fk_inexistente_no_crea_nada(db_session):
    """D5: mismo patrón que ``IncidentService._check_refs`` — todo el lote se
    valida antes de insertar; una FK inexistente aborta sin dejar basura."""
    with pytest.raises(ValueError):
        svc.bulk_create(db_session, [
            ProgramEventCreate(title="Con área fantasma", area_id=987654321),
        ])

    assert db_session.query(AdhocProgramEvent).filter_by(title="Con área fantasma").first() is None


def test_bulk_create_con_fk_inexistente_en_cualquier_fila_aborta_el_lote(db_session):
    """El legacy insertaba las filas válidas y reventaba a media tanda con la
    inválida; aquí es todo o nada."""
    with pytest.raises(ValueError):
        svc.bulk_create(db_session, [
            ProgramEventCreate(title="Válido"),
            ProgramEventCreate(title="Con responsable fantasma", responsible_id=987654321),
        ])

    assert db_session.query(AdhocProgramEvent).filter_by(title="Válido").first() is None


def test_update_event_con_fk_inexistente_lanza_y_no_muta(db_session):
    event = _create(db_session, title="Intacto")

    with pytest.raises(ValueError):
        svc.update_event(
            db_session, event.id, ProgramEventUpdate.model_validate({"process_id": 987654321})
        )

    db_session.expire(event)
    assert event.title == "Intacto"
    assert event.process_id is None


# --------------------------------------------------------------------------
# delete_event  (bug #18)
# --------------------------------------------------------------------------

def test_delete_event_borra_sus_archivos_de_bd_y_de_disco(db_session, uploads_root):
    created = svc.bulk_create(
        db_session,
        [ProgramEventCreate(title="Con adjuntos")],
        files_by_index={0: [_FakeUpload("evidencia.pdf")]},
    )
    event = created[0]
    event_id = event.id
    stored = db_session.query(AdhocProgramEventFile).filter_by(event_id=event_id).one()
    on_disk = upload_service.open_stored("program_events", stored.file_path)
    assert on_disk.is_file()

    svc.delete_event(db_session, event_id)

    assert db_session.get(AdhocProgramEvent, event_id) is None
    assert db_session.query(AdhocProgramEventFile).filter_by(event_id=event_id).count() == 0
    assert not on_disk.exists(), "bug #18: el legacy dejaba los archivos huerfanos en disco"
    assert not on_disk.parent.exists(), "el directorio del evento tambien se limpia"


def test_delete_event_inexistente_lanza_event_not_found(db_session):
    with pytest.raises(svc.EventNotFound):
        svc.delete_event(db_session, 99_999_999)


# --------------------------------------------------------------------------
# duplicate_event
# --------------------------------------------------------------------------

def test_duplicate_event_dos_veces_no_colisiona_de_folio(db_session):
    original = _create(db_session, title="Auditoria", folio="PRG-2026-001")

    copia1 = svc.duplicate_event(db_session, original.id)
    copia2 = svc.duplicate_event(db_session, original.id)

    assert copia1.folio == "PRG-2026-001-COPY"
    assert copia2.folio != copia1.folio, "el legacy generaba el mismo '-COPY' siempre"
    assert copia2.folio.startswith("PRG-2026-001-COPY")
    assert all(len(c.folio) <= 50 for c in (copia1, copia2))


def test_duplicate_event_conserva_location_y_resetea_avance(db_session, catalogs):
    original = _create(
        db_session,
        title="Auditoria",
        folio="PRG-2026-002",
        location="Sala de juntas",
        real_date=date(2026, 4, 1),
        status="Completado",
        priority="Alta",
        start_date=date(2026, 3, 1),
        commitment_date=date(2026, 3, 31),
        area_id=catalogs["area"].id,
        process_id=catalogs["process"].id,
        category_id=catalogs["category"].id,
    )

    copia = svc.duplicate_event(db_session, original.id)

    # Lo que SI se copia (el legacy perdia `location`).
    assert copia.location == "Sala de juntas"
    assert copia.priority == "Alta"
    assert copia.start_date == date(2026, 3, 1)
    assert copia.commitment_date == date(2026, 3, 31)
    assert copia.area_id == original.area_id
    assert copia.process_id == original.process_id
    assert copia.category_id == original.category_id
    assert copia.title == "Copia de Auditoria"
    # Lo que NO se copia: el avance real del evento original.
    assert copia.real_date is None
    assert copia.status == "Planeado"
    assert copia.id != original.id


def test_duplicate_event_sin_folio_deja_folio_nulo(db_session):
    original = _create(db_session, title="Sin folio")
    copia = svc.duplicate_event(db_session, original.id)
    assert copia.folio is None


def test_duplicate_event_no_copia_los_adjuntos(db_session, uploads_root):
    created = svc.bulk_create(
        db_session,
        [ProgramEventCreate(title="Con adjuntos", folio="PRG-2026-003")],
        files_by_index={0: [_FakeUpload("evidencia.pdf")]},
    )
    copia = svc.duplicate_event(db_session, created[0].id)
    assert db_session.query(AdhocProgramEventFile).filter_by(event_id=copia.id).count() == 0


def test_duplicate_event_inexistente_lanza_event_not_found(db_session):
    with pytest.raises(svc.EventNotFound):
        svc.duplicate_event(db_session, 99_999_999)


# --------------------------------------------------------------------------
# Archivos: add / list / get / delete
# --------------------------------------------------------------------------

def test_add_files_y_list_files(db_session, uploads_root):
    event = _create(db_session, title="Evento")

    saved = svc.add_files(db_session, event.id, [_FakeUpload("plan.pdf")], uploaded_by_id=None)

    assert len(saved) == 1
    assert saved[0].original_name == "plan.pdf"
    assert saved[0].size_bytes > 0
    assert [f.id for f in svc.list_files(db_session, event.id)] == [saved[0].id]


def test_add_files_a_evento_inexistente_lanza_event_not_found(db_session, uploads_root):
    with pytest.raises(svc.EventNotFound):
        svc.add_files(db_session, 99_999_999, [_FakeUpload("plan.pdf")], uploaded_by_id=None)


def test_add_files_sin_archivos_lanza_value_error(db_session, uploads_root):
    event = _create(db_session, title="Evento")
    with pytest.raises(ValueError):
        svc.add_files(db_session, event.id, [], uploaded_by_id=None)


def test_delete_file_borra_la_fila_y_el_archivo(db_session, uploads_root):
    event = _create(db_session, title="Evento")
    saved = svc.add_files(db_session, event.id, [_FakeUpload("plan.pdf")], uploaded_by_id=None)[0]
    on_disk = upload_service.open_stored("program_events", saved.file_path)
    file_id = saved.id

    svc.delete_file(db_session, file_id)

    assert db_session.get(AdhocProgramEventFile, file_id) is None
    assert not on_disk.exists()


def test_get_file_inexistente_lanza_file_not_found(db_session):
    with pytest.raises(svc.EventFileNotFound):
        svc.get_file(db_session, 99_999_999)


def test_delete_file_inexistente_lanza_file_not_found(db_session):
    with pytest.raises(svc.EventFileNotFound):
        svc.delete_file(db_session, 99_999_999)


def test_open_file_devuelve_la_ruta_absoluta_verificada(db_session, uploads_root):
    event = _create(db_session, title="Evento")
    saved = svc.add_files(db_session, event.id, [_FakeUpload("plan.pdf")], uploaded_by_id=None)[0]

    path = svc.open_file(saved)

    assert path.is_file()
    assert path.name == "plan.pdf"
