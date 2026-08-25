"""Tests de ``itcj2.apps.adhoc.services.indicator_service``.

Corren contra Postgres real (fixture ``db_session`` de
``tests/fastapi/conftest.py``, transacción con SAVEPOINTs y rollback al final)
en vez de contra un ``MagicMock``. Motivo: las tres correcciones que este
service existe para implementar **son de base de datos** y un mock no las
prueba:

* el ``UNIQUE (indicator_id, period_index)`` que hace del tracking un upsert
  atómico en vez del ``SELECT`` + ``INSERT`` con carrera del legacy,
* el ``UNIQUE (year)`` que el alta de años tiene que absorber sin reventar,
* el ``ON DELETE CASCADE`` de año → indicadores → trackings.

Nada se persiste: el ``trans.rollback()`` del fixture limpia todo.
"""
import uuid
from types import SimpleNamespace

import pytest

from itcj2.apps.adhoc.models import (
    AdhocIndicator,
    AdhocIndicatorTracking,
    AdhocIndicatorYear,
    AdhocProcess,
)
from itcj2.apps.adhoc.services import indicator_service


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_process(db, name=None):
    proc = AdhocProcess(name=name or f"proc_{uuid.uuid4().hex[:10]}", color="#123456")
    db.add(proc)
    db.flush()
    return proc


def _free_years(db, count=1):
    """Años que hoy NO existen en la tabla (el UNIQUE es global)."""
    taken = {y for (y,) in db.query(AdhocIndicatorYear.year).all()}
    out = []
    candidate = 2100
    while len(out) < count and candidate >= 2000:
        if candidate not in taken:
            out.append(candidate)
        candidate -= 1
    assert len(out) == count, "No quedan años libres para el test"
    return out


def _make_year(db):
    year = AdhocIndicatorYear(year=_free_years(db, 1)[0])
    db.add(year)
    db.flush()
    return year


class _FakeUpload:
    """Sustituto mínimo de ``fastapi.UploadFile`` para ``save_upload``."""

    def __init__(self, filename, content=b"contenido de evidencia"):
        import io
        self.filename = filename
        self.file = io.BytesIO(content)
        self.content_type = "application/pdf"


@pytest.fixture()
def upload_root(tmp_path, monkeypatch):
    """Aísla los adjuntos en ``tmp_path`` parcheando el ``_settings`` del
    upload_service (la indirección existe justo para esto)."""
    from itcj2.apps.adhoc.services import upload_service

    fake = SimpleNamespace(
        ADHOC_UPLOAD_PATH=str(tmp_path),
        ADHOC_MAX_FILE_SIZE=10 * 1024 * 1024,
        ADHOC_ALLOWED_EXTENSIONS="pdf,docx,png,txt",
    )
    monkeypatch.setattr(upload_service, "_settings", lambda: fake)
    return tmp_path


# ---------------------------------------------------------------------------
# Años
# ---------------------------------------------------------------------------

def test_create_years_inserts_and_reports_skipped(db_session):
    years = _free_years(db_session, 2)
    result = indicator_service.IndicatorService.create_years(db_session, years)

    # ``created`` viene ordenado por año ascendente, no en el orden de captura.
    assert sorted(y.year for y in result["created"]) == sorted(years)
    assert result["skipped"] == []

    # Segunda corrida: idempotente, nada nuevo, todo omitido.
    again = indicator_service.IndicatorService.create_years(db_session, years)
    assert again["created"] == []
    assert sorted(again["skipped"]) == sorted(years)


def test_create_years_dedupes_within_the_same_batch(db_session):
    year = _free_years(db_session, 1)[0]
    result = indicator_service.IndicatorService.create_years(db_session, [year, year, year])
    assert len(result["created"]) == 1
    assert db_session.query(AdhocIndicatorYear).filter_by(year=year).count() == 1


def test_create_years_rejects_empty_list(db_session):
    with pytest.raises(ValueError):
        indicator_service.IndicatorService.create_years(db_session, [])


def test_list_years_is_descending_and_counts_indicators(db_session):
    year = _make_year(db_session)
    proc = _make_process(db_session)
    db_session.add_all([
        AdhocIndicator(year_id=year.id, process_id=proc.id, objective="a"),
        AdhocIndicator(year_id=year.id, process_id=proc.id, objective="b"),
    ])
    db_session.flush()

    rows = indicator_service.IndicatorService.list_years(db_session)
    found = [(y, n) for (y, n) in rows if y.id == year.id]
    assert found and found[0][1] == 2
    # Orden descendente por año.
    assert [y.year for (y, _n) in rows] == sorted([y.year for (y, _n) in rows], reverse=True)


def test_delete_year_cascades_to_indicators_and_trackings(db_session):
    year = _make_year(db_session)
    proc = _make_process(db_session)
    ind = AdhocIndicator(year_id=year.id, process_id=proc.id, objective="x")
    db_session.add(ind)
    db_session.flush()
    db_session.add(AdhocIndicatorTracking(indicator_id=ind.id, period_index=1, color="verde"))
    db_session.flush()
    ind_id = ind.id

    indicator_service.IndicatorService.delete_year(db_session, year.id)

    assert db_session.get(AdhocIndicatorYear, year.id) is None
    assert db_session.get(AdhocIndicator, ind_id) is None
    assert db_session.query(AdhocIndicatorTracking).filter_by(indicator_id=ind_id).count() == 0


def test_delete_year_missing_raises_lookup_error(db_session):
    with pytest.raises(LookupError):
        indicator_service.IndicatorService.delete_year(db_session, 999_999_999)


# ---------------------------------------------------------------------------
# Indicadores
# ---------------------------------------------------------------------------

def test_bulk_create_writes_the_four_threshold_columns(db_session):
    year = _make_year(db_session)
    proc = _make_process(db_session)

    created = indicator_service.IndicatorService.bulk_create(
        db_session, year.id,
        [{
            "process_id": proc.id,
            "objective": "Satisfacción del cliente",
            "frequency": "Mensual",
            "planned_white": "95%",
            "planned_red": "<70%",
            "planned_yellow": "70-85%",     # ← el guion que rompía el legacy
            "planned_green": ">85%",
        }],
    )

    assert len(created) == 1
    ind = db_session.get(AdhocIndicator, created[0].id)
    assert (ind.planned_white, ind.planned_red, ind.planned_yellow, ind.planned_green) == (
        "95%", "<70%", "70-85%", ">85%",
    )
    assert ind.frequency == "Mensual"


def test_bulk_create_accepts_null_frequency(db_session):
    """El legacy escribía ``''``; el CheckConstraint solo admite NULL o los 3
    valores. El service tiene que aceptar ``None`` sin tocar la BD con ``''``."""
    year = _make_year(db_session)
    proc = _make_process(db_session)
    created = indicator_service.IndicatorService.bulk_create(
        db_session, year.id, [{"process_id": proc.id, "frequency": None}],
    )
    assert db_session.get(AdhocIndicator, created[0].id).frequency is None


def test_bulk_create_rejects_unknown_process(db_session):
    year = _make_year(db_session)
    with pytest.raises(ValueError):
        indicator_service.IndicatorService.bulk_create(
            db_session, year.id, [{"process_id": 999_999_999}],
        )


def test_bulk_create_rejects_unknown_year(db_session):
    proc = _make_process(db_session)
    with pytest.raises(LookupError):
        indicator_service.IndicatorService.bulk_create(
            db_session, 999_999_999, [{"process_id": proc.id}],
        )


def test_bulk_create_rejects_empty_batch(db_session):
    year = _make_year(db_session)
    with pytest.raises(ValueError):
        indicator_service.IndicatorService.bulk_create(db_session, year.id, [])


def test_bulk_create_stores_relative_document_path(db_session, upload_root):
    year = _make_year(db_session)
    proc = _make_process(db_session)

    created = indicator_service.IndicatorService.bulk_create(
        db_session, year.id,
        [{"process_id": proc.id, "objective": "con evidencia"}],
        uploads=[_FakeUpload("evidencia.pdf")],
    )

    ind = db_session.get(AdhocIndicator, created[0].id)
    # RELATIVA "{indicator_id}/{filename}" — el legacy guardaba
    # "instance/app_prueba/QA/Indicators/x.pdf" (ruta del proceso).
    assert ind.document_url == f"{ind.id}/evidencia.pdf"
    assert (upload_root / "indicators" / str(ind.id) / "evidencia.pdf").is_file()


def test_bulk_create_ignores_empty_file_slots(db_session, upload_root):
    """Un ``<input type=file>`` vacío llega como parte con ``filename=''``: es
    alineación de índices, no un archivo."""
    year = _make_year(db_session)
    proc = _make_process(db_session)

    created = indicator_service.IndicatorService.bulk_create(
        db_session, year.id,
        [{"process_id": proc.id}, {"process_id": proc.id}],
        uploads=[_FakeUpload(""), _FakeUpload("real.pdf")],
    )

    assert db_session.get(AdhocIndicator, created[0].id).document_url is None
    assert db_session.get(AdhocIndicator, created[1].id).document_url is not None


def test_bulk_create_rejects_extension_outside_whitelist(db_session, upload_root):
    year = _make_year(db_session)
    proc = _make_process(db_session)
    with pytest.raises(ValueError):
        indicator_service.IndicatorService.bulk_create(
            db_session, year.id,
            [{"process_id": proc.id}],
            uploads=[_FakeUpload("payload.exe")],
        )
    # Y no deja el indicador a medias.
    assert db_session.query(AdhocIndicator).filter_by(year_id=year.id).count() == 0


def test_update_indicator_only_touches_given_keys(db_session):
    year = _make_year(db_session)
    proc = _make_process(db_session)
    ind = AdhocIndicator(
        year_id=year.id, process_id=proc.id, objective="original",
        responsible="Juan", planned_green=">85%",
    )
    db_session.add(ind)
    db_session.flush()

    indicator_service.IndicatorService.update_indicator(
        db_session, ind.id, {"objective": "editado"},
    )

    db_session.refresh(ind)
    assert ind.objective == "editado"
    assert ind.responsible == "Juan"       # intacto
    assert ind.planned_green == ">85%"     # intacto


def test_update_indicator_can_clear_a_field(db_session):
    year = _make_year(db_session)
    proc = _make_process(db_session)
    ind = AdhocIndicator(year_id=year.id, process_id=proc.id, responsible="Juan")
    db_session.add(ind)
    db_session.flush()

    indicator_service.IndicatorService.update_indicator(
        db_session, ind.id, {"responsible": None},
    )
    db_session.refresh(ind)
    assert ind.responsible is None


def test_update_indicator_rejects_null_process(db_session):
    year = _make_year(db_session)
    proc = _make_process(db_session)
    ind = AdhocIndicator(year_id=year.id, process_id=proc.id)
    db_session.add(ind)
    db_session.flush()

    with pytest.raises(ValueError):
        indicator_service.IndicatorService.update_indicator(
            db_session, ind.id, {"process_id": None},
        )


def test_update_indicator_missing_raises_lookup_error(db_session):
    with pytest.raises(LookupError):
        indicator_service.IndicatorService.update_indicator(db_session, 999_999_999, {})


def test_update_indicator_replaces_document_and_deletes_the_old_one(db_session, upload_root):
    year = _make_year(db_session)
    proc = _make_process(db_session)
    created = indicator_service.IndicatorService.bulk_create(
        db_session, year.id, [{"process_id": proc.id}],
        uploads=[_FakeUpload("viejo.pdf")],
    )
    ind_id = created[0].id
    old = upload_root / "indicators" / str(ind_id) / "viejo.pdf"
    assert old.is_file()

    indicator_service.IndicatorService.update_indicator(
        db_session, ind_id, {}, upload=_FakeUpload("nuevo.pdf"),
    )

    ind = db_session.get(AdhocIndicator, ind_id)
    assert ind.document_url == f"{ind_id}/nuevo.pdf"
    assert not old.exists()


def test_delete_indicator_removes_row_and_file(db_session, upload_root):
    year = _make_year(db_session)
    proc = _make_process(db_session)
    created = indicator_service.IndicatorService.bulk_create(
        db_session, year.id, [{"process_id": proc.id}],
        uploads=[_FakeUpload("evidencia.pdf")],
    )
    ind_id = created[0].id
    path = upload_root / "indicators" / str(ind_id) / "evidencia.pdf"

    indicator_service.IndicatorService.delete_indicator(db_session, ind_id)

    assert db_session.get(AdhocIndicator, ind_id) is None
    assert not path.exists()


def test_delete_indicator_missing_raises_lookup_error(db_session):
    with pytest.raises(LookupError):
        indicator_service.IndicatorService.delete_indicator(db_session, 999_999_999)


def test_list_indicators_returns_only_the_year_asked_for(db_session):
    year_a = _make_year(db_session)
    year_b = _make_year(db_session)
    proc = _make_process(db_session)
    db_session.add_all([
        AdhocIndicator(year_id=year_a.id, process_id=proc.id, objective="A"),
        AdhocIndicator(year_id=year_b.id, process_id=proc.id, objective="B"),
    ])
    db_session.flush()

    rows = indicator_service.IndicatorService.list_indicators(db_session, year_a.id)
    assert [r.objective for r in rows] == ["A"]


def test_list_indicators_missing_year_raises_lookup_error(db_session):
    with pytest.raises(LookupError):
        indicator_service.IndicatorService.list_indicators(db_session, 999_999_999)


def test_document_path_resolves_and_rejects_missing_document(db_session, upload_root):
    year = _make_year(db_session)
    proc = _make_process(db_session)
    created = indicator_service.IndicatorService.bulk_create(
        db_session, year.id, [{"process_id": proc.id}, {"process_id": proc.id}],
        uploads=[_FakeUpload("evidencia.pdf"), _FakeUpload("")],
    )

    path = indicator_service.IndicatorService.document_path(db_session, created[0].id)
    assert path.is_file() and path.name == "evidencia.pdf"

    with pytest.raises(LookupError):
        indicator_service.IndicatorService.document_path(db_session, created[1].id)


# ---------------------------------------------------------------------------
# Seguimiento (upsert)
# ---------------------------------------------------------------------------

def test_upsert_tracking_inserts_then_updates_the_same_row(db_session):
    """Regresión del bug del legacy: sin el UNIQUE, dos escrituras concurrentes
    del mismo periodo dejaban dos filas y el tablero pintaba una al azar."""
    year = _make_year(db_session)
    proc = _make_process(db_session)
    ind = AdhocIndicator(year_id=year.id, process_id=proc.id, frequency="Mensual")
    db_session.add(ind)
    db_session.flush()

    first = indicator_service.IndicatorService.upsert_tracking(
        db_session, ind.id, 3, real_value="80", color="amarillo",
    )
    second = indicator_service.IndicatorService.upsert_tracking(
        db_session, ind.id, 3, real_value="92", color="verde",
    )

    assert first.id == second.id
    assert db_session.query(AdhocIndicatorTracking).filter_by(indicator_id=ind.id).count() == 1
    assert (second.real_value, second.color) == ("92", "verde")


def test_upsert_tracking_defaults_color_to_blanco(db_session):
    year = _make_year(db_session)
    proc = _make_process(db_session)
    ind = AdhocIndicator(year_id=year.id, process_id=proc.id, frequency="Anual")
    db_session.add(ind)
    db_session.flush()

    row = indicator_service.IndicatorService.upsert_tracking(db_session, ind.id, 1, color=None)
    assert row.color == "blanco"


def test_upsert_tracking_rejects_period_out_of_range(db_session):
    year = _make_year(db_session)
    proc = _make_process(db_session)
    ind = AdhocIndicator(year_id=year.id, process_id=proc.id, frequency="Mensual")
    db_session.add(ind)
    db_session.flush()

    with pytest.raises(ValueError):
        indicator_service.IndicatorService.upsert_tracking(db_session, ind.id, 13)


def test_upsert_tracking_rejects_invalid_color(db_session):
    year = _make_year(db_session)
    proc = _make_process(db_session)
    ind = AdhocIndicator(year_id=year.id, process_id=proc.id, frequency="Anual")
    db_session.add(ind)
    db_session.flush()

    with pytest.raises(ValueError):
        indicator_service.IndicatorService.upsert_tracking(db_session, ind.id, 1, color="morado")


def test_upsert_tracking_missing_indicator_raises_lookup_error(db_session):
    with pytest.raises(LookupError):
        indicator_service.IndicatorService.upsert_tracking(db_session, 999_999_999, 1)
