"""Fase 4b (Task 2): sitios de helpdesk que `work.measured()` cubre
(task-2-brief.md) — LibreOffice (solicitud/orden de trabajo), el export de
inventario a Excel, los 5 reportes CSV de inventario y el oficio de baja.

Cada test parchea SOLO lo caro (`subprocess.run`, el `Workbook`/escritor) y
afirma UNA observación con las etiquetas EXACTAS del contrato.

Nota de alcance (brief): los 5 `export_*_csv` de `InventoryReportsService`
construyen el string COMPLETO de forma síncrona — no son generadores
perezosos — así que se mide todo el armado del CSV, no un consumo por
streaming. Fuera de alcance: los escritores inline de
`itcj2/tasks/helpdesk_tasks.py` (Celery, opción (i)) y los export de
auditoría de config.
"""
import logging
import subprocess
from io import BytesIO
from types import SimpleNamespace

import pytest

import itcj2.models  # noqa: F401 (resuelve mappers antes de tocar servicios)

from ._work_site_helpers import counts, delta, only


# ---------------------------------------------------------------------------
# document_service.py — _convert_docx_to_pdf (LibreOffice)
# ---------------------------------------------------------------------------

def _fake_soffice_run(cmd, **kwargs):
    """Simula `soffice --convert-to pdf`: escribe `document.pdf` en `--outdir`
    (lo que `_convert_docx_to_pdf` espera encontrar tras un returncode 0)."""
    outdir = cmd[cmd.index("--outdir") + 1]
    with open(f"{outdir}/document.pdf", "wb") as f:
        f.write(b"%PDF-1.4 fake")
    return SimpleNamespace(returncode=0, stdout="", stderr="")


class TestDocumentServiceLibreOffice:
    LABELS = {"kind": "solicitud", "engine": "libreoffice"}

    def test_ok_records_one_observation_with_exact_labels(self, monkeypatch):
        from itcj2.apps.helpdesk.services import document_service

        monkeypatch.setattr(document_service, "_find_libreoffice_cmd", lambda: "soffice")
        monkeypatch.setattr(document_service.subprocess, "run", _fake_soffice_run)

        before = counts(self.LABELS)
        result = document_service._convert_docx_to_pdf(BytesIO(b"docx"), kind="solicitud")

        assert result.read().startswith(b"%PDF")
        assert delta(before, counts(self.LABELS)) == only("ok")

    @pytest.mark.parametrize(
        "returncode, stderr",
        [
            (1, "boom LibreOffice"),
            # Matado por señal (OOM dentro del límite del worker): el stderr
            # sale VACÍO y el returncode es lo único que lo distingue de un
            # documento que LibreOffice rechazó.
            (-9, ""),
        ],
        ids=["error-de-conversion", "matado-por-senal"],
    )
    def test_returncode_nonzero_records_error_and_still_raises(
        self, monkeypatch, caplog, returncode, stderr
    ):
        """`returncode != 0` hoy ya lanza (RuntimeError con el stderr en el
        mensaje) — la instrumentación no debe cambiar ni la excepción ni el
        mensaje, solo clasificarlo como outcome=error. El returncode no es
        etiqueta (contrato): va en la línea de log."""
        from itcj2.apps.helpdesk.services import document_service

        def _fake_run(cmd, **kwargs):
            return SimpleNamespace(returncode=returncode, stdout="", stderr=stderr)

        monkeypatch.setattr(document_service, "_find_libreoffice_cmd", lambda: "soffice")
        monkeypatch.setattr(document_service.subprocess, "run", _fake_run)

        before = counts(self.LABELS)
        with caplog.at_level(logging.ERROR, logger=document_service.logger.name):
            with pytest.raises(RuntimeError) as info:
                document_service._convert_docx_to_pdf(BytesIO(b"docx"), kind="solicitud")

        # Regla de oro 2: el mensaje de la excepción, byte a byte, el de antes.
        assert str(info.value) == f"Error al convertir a PDF: {stderr}"
        assert delta(before, counts(self.LABELS)) == only("error")
        [line] = [
            r.getMessage() for r in caplog.records
            if r.name == document_service.logger.name and r.levelno == logging.ERROR
        ]
        assert f"returncode={returncode}" in line
        assert "kind=solicitud" in line

    def test_exit_zero_without_pdf_records_error_and_raises_the_same(self, monkeypatch):
        """soffice que sale con 0 sin escribir el PDF (típico: le pasa el
        trabajo a otra instancia que ya usa el mismo perfil). El negocio ya
        fallaba igual; lo que cambia es que el panel lo cuente como error y no
        como éxito."""
        from itcj2.apps.helpdesk.services import document_service

        def _fake_run(cmd, **kwargs):
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        monkeypatch.setattr(document_service, "_find_libreoffice_cmd", lambda: "soffice")
        monkeypatch.setattr(document_service.subprocess, "run", _fake_run)

        before = counts(self.LABELS)
        with pytest.raises(RuntimeError) as info:
            document_service._convert_docx_to_pdf(BytesIO(b"docx"), kind="solicitud")

        assert str(info.value) == "No se generó el archivo PDF"
        assert delta(before, counts(self.LABELS)) == only("error")

    def test_timeout_records_timeout_and_reraises_the_same_exception(self, monkeypatch):
        from itcj2.apps.helpdesk.services import document_service

        exc = subprocess.TimeoutExpired(["soffice"], 60)

        def _fake_run(cmd, **kwargs):
            raise exc

        monkeypatch.setattr(document_service, "_find_libreoffice_cmd", lambda: "soffice")
        monkeypatch.setattr(document_service.subprocess, "run", _fake_run)

        before = counts(self.LABELS)
        with pytest.raises(subprocess.TimeoutExpired) as info:
            document_service._convert_docx_to_pdf(BytesIO(b"docx"), kind="solicitud")

        assert info.value is exc
        assert delta(before, counts(self.LABELS)) == only("timeout")

    def test_orden_trabajo_uses_its_own_kind_label(self, monkeypatch):
        """`generate_orden_trabajo_pdf` debe pasar kind='orden_trabajo', no
        'solicitud' (el kind lo decide el llamador, no `_convert_docx_to_pdf`)."""
        from itcj2.apps.helpdesk.services import document_service

        monkeypatch.setattr(document_service, "_find_libreoffice_cmd", lambda: "soffice")
        monkeypatch.setattr(document_service.subprocess, "run", _fake_soffice_run)

        labels = {"kind": "orden_trabajo", "engine": "libreoffice"}
        before = counts(labels)
        document_service._convert_docx_to_pdf(BytesIO(b"docx"), kind="orden_trabajo")
        assert delta(before, counts(labels)) == only("ok")


# ---------------------------------------------------------------------------
# inventory_export_service.py — export_items (openpyxl)
# ---------------------------------------------------------------------------

def test_inventory_export_records_one_ok_observation(monkeypatch):
    from itcj2.apps.helpdesk.services.inventory_export_service import InventoryExportService

    # Lo caro (armar/guardar el workbook) es lo que se mide; la consulta a BD
    # no: se parchea para no depender de una sesión real.
    monkeypatch.setattr(InventoryExportService, "_query_items", lambda db, user, params: ([], []))

    labels = {"kind": "inventory_export", "engine": "openpyxl"}
    before = counts(labels)

    buf, filename = InventoryExportService.export_items(None, {"sub": "1"}, {})

    assert filename.startswith("inventario_")
    assert delta(before, counts(labels)) == only("ok")


# ---------------------------------------------------------------------------
# inventory_reports_service.py — 5 export_*_csv (síncronos, no lazy)
# ---------------------------------------------------------------------------

class TestInventoryReportsCsv:
    def test_export_equipment_csv(self, monkeypatch):
        from itcj2.apps.helpdesk.services.inventory_reports_service import InventoryReportsService

        monkeypatch.setattr(
            InventoryReportsService, "get_equipment_report",
            lambda db, filters: {"items": []},
        )
        labels = {"kind": "inventory_report_equipment", "engine": "csv"}
        before = counts(labels)

        content = InventoryReportsService.export_equipment_csv(None, {})

        assert "No. Inventario" in content
        assert delta(before, counts(labels)) == only("ok")

    def test_export_movements_csv(self, monkeypatch):
        from itcj2.apps.helpdesk.services.inventory_reports_service import InventoryReportsService

        monkeypatch.setattr(
            InventoryReportsService, "get_movements_report",
            lambda db, filters: {"events": []},
        )
        labels = {"kind": "inventory_report_movements", "engine": "csv"}
        before = counts(labels)

        content = InventoryReportsService.export_movements_csv(None, {})

        assert "Tipo de Evento" in content
        assert delta(before, counts(labels)) == only("ok")

    def test_export_warranty_csv(self, monkeypatch):
        from itcj2.apps.helpdesk.services.inventory_reports_service import InventoryReportsService
        from itcj2.apps.helpdesk.services.inventory_stats_service import InventoryStatsService

        monkeypatch.setattr(InventoryStatsService, "get_warranty_report", lambda db: {})
        labels = {"kind": "inventory_report_warranty", "engine": "csv"}
        before = counts(labels)

        content = InventoryReportsService.export_warranty_csv(None)

        assert "Días Restantes" in content
        assert delta(before, counts(labels)) == only("ok")

    def test_export_maintenance_csv(self, monkeypatch):
        from itcj2.apps.helpdesk.services.inventory_reports_service import InventoryReportsService
        from itcj2.apps.helpdesk.services.inventory_stats_service import InventoryStatsService

        monkeypatch.setattr(InventoryStatsService, "get_maintenance_report", lambda db: {})
        labels = {"kind": "inventory_report_maintenance", "engine": "csv"}
        before = counts(labels)

        content = InventoryReportsService.export_maintenance_csv(None)

        assert "Próx. Mantenimiento" in content
        assert delta(before, counts(labels)) == only("ok")

    def test_export_lifecycle_csv(self, monkeypatch):
        from itcj2.apps.helpdesk.services.inventory_reports_service import InventoryReportsService
        from itcj2.apps.helpdesk.services.inventory_stats_service import InventoryStatsService

        monkeypatch.setattr(InventoryStatsService, "get_lifecycle_report", lambda db: {})
        labels = {"kind": "inventory_report_lifecycle", "engine": "csv"}
        before = counts(labels)

        content = InventoryReportsService.export_lifecycle_csv(None)

        assert "Antigüedad" in content
        assert delta(before, counts(labels)) == only("ok")


# ---------------------------------------------------------------------------
# retirement_document_service.py — fill_excel_template (openpyxl, sin PDF)
# ---------------------------------------------------------------------------

def test_retirement_oficio_records_one_ok_observation(monkeypatch):
    from itcj2.apps.helpdesk.services import retirement_document_service as rds

    fake_ctx = {
        "folio": "OFICIO-TEST",
        "fecha_oficio": None,
        "location_text": "Depto X",
        "causa": "obsoleto",
        "responsable": None,
        "signers": {
            1: {"id": None, "full_name": None, "title": "Jefe"},
            2: {"id": None, "full_name": None, "title": "Subdirector"},
            3: {"id": None, "full_name": None, "title": "Director"},
        },
        "signatures_by_step": {},
        "items": [],
    }
    # Se parchea `_request_context` (las consultas a BD) para no depender de
    # una sesión real; `db` solo necesita ser truthy para llegar ahí.
    monkeypatch.setattr(rds, "_request_context", lambda db, request: fake_ctx)

    labels = {"kind": "retirement_oficio", "engine": "openpyxl"}
    before = counts(labels)

    result = rds.RetirementDocumentService.fill_excel_template(request=object(), db=object())

    assert isinstance(result, (bytes, bytearray)) and len(result) > 0
    assert delta(before, counts(labels)) == only("ok")
