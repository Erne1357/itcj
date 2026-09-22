"""Fase 4b (Task 2): agendatec/api/admin/reports.py — `export_requests_xlsx`
envuelve la llamada a `_write_excel(buf, ...)` (el buffer se arma ENTERO antes
del `StreamingResponse`) con `measured("agendatec_report", "xlsxwriter")`.
"""
from unittest.mock import MagicMock

from ._work_site_helpers import counts, delta, only


def test_agendatec_report_records_one_ok_observation():
    from itcj2.apps.agendatec.api.admin import reports as agendatec_reports

    db = MagicMock()
    # `base_qry.all()` -> sin solicitudes: ejercita el camino real de
    # `_write_excel` (hojas vacías) sin necesitar Postgres.
    db.query.return_value.options.return_value.filter.return_value.all.return_value = []

    labels = {"kind": "agendatec_report", "engine": "xlsxwriter"}
    before = counts(labels)

    response = agendatec_reports.export_requests_xlsx(
        from_=None, to=None, type=None, status=None, appointment_status=None,
        program_id=None, coordinator_id=None, period_id=None, q="",
        order_by="created_at", order_dir="asc", citas_cols="", bajas_cols="",
        citas_summary="total,coordinator", bajas_summary="total", filename="",
        user={"sub": "1"}, db=db,
    )

    assert response.media_type.startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert delta(before, counts(labels)) == only("ok")
