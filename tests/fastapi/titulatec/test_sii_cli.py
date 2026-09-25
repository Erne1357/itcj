"""Comandos `titulatec sii-ping`, `sii-rules-validate` y `sii-check` (Tarea 2,
spec 2026-09-25 §3.4 y §7).

Corren con el SII FALSO y las reglas sintéticas de `sii_fixtures/` (parcheando
`SiiConfig`, nunca `get_settings`): en CI no hay `database/SII/` ni driver.
`sii-check` es un dry-run: imprime el veredicto por regla, hechos, identidad y
el NIP ENMASCARADO; no escribe nada.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from itcj2.apps.titulatec.services.sii.client import SiiConfig
from itcj2.cli.titulatec import titulatec_cli

FIXTURES = Path(__file__).parent / "sii_fixtures"


@pytest.fixture()
def sii(monkeypatch):
    """SII falso + reglas sintéticas. Devuelve un setter para cambiar backend."""
    state = {"backend": "fake", "fake": FIXTURES / "fake_sii.json", "rules": FIXTURES}
    monkeypatch.setattr(SiiConfig, "backend", staticmethod(lambda: state["backend"]))
    monkeypatch.setattr(SiiConfig, "fake_file", staticmethod(lambda: Path(state["fake"])))
    monkeypatch.setattr(SiiConfig, "rules_dir", staticmethod(lambda: Path(state["rules"])))
    monkeypatch.setattr(SiiConfig, "odbc_connection_string", staticmethod(lambda: ""))
    return state


def _run(*args):
    return CliRunner().invoke(titulatec_cli, list(args))


class TestSiiRulesValidate:
    def test_reglas_validas(self, sii):
        res = _run("sii-rules-validate")
        assert res.exit_code == 0, res.output
        assert "test-2026-09-25.1" in res.output
        assert "6 reglas" in res.output and "3 consultas" in res.output
        assert "OK" in res.output

    def test_reglas_invalidas_con_dir(self, sii, tmp_path):
        (tmp_path / "queries").mkdir()
        (tmp_path / "queries" / "q.sql").write_text(
            "UPDATE x SET a = 1 WHERE c = ?", encoding="utf-8")
        (tmp_path / "rules.toml").write_text(
            'version = "t"\n[[query]]\nid = "q"\nfile = "queries/q.sql"\n'
            'params = ["control_number"]\n[[rule]]\nid = "r"\nquery = "q"\n'
            'criterion = { kind = "magia" }\nmessage = "x"\n', encoding="utf-8")
        res = _run("sii-rules-validate", "--dir", str(tmp_path))
        assert res.exit_code != 0
        assert "UPDATE" in res.output and "magia" in res.output

    def test_carpeta_sin_reglas(self, sii, tmp_path):
        sii["rules"] = tmp_path / "no_existe"
        res = _run("sii-rules-validate")
        assert res.exit_code != 0
        assert "rules.toml" in res.output


class TestSiiPing:
    def test_fake_ok(self, sii):
        res = _run("sii-ping")
        assert res.exit_code == 0, res.output
        assert "fake" in res.output and "OK" in res.output

    def test_disabled(self, sii):
        sii["backend"] = "disabled"
        res = _run("sii-ping")
        assert res.exit_code != 0
        assert "deshabilitada" in res.output

    def test_fake_sin_archivo(self, sii, tmp_path):
        sii["fake"] = tmp_path / "no.json"
        res = _run("sii-ping")
        assert res.exit_code != 0
        assert "no.json" in res.output


class TestSiiCheck:
    def test_apta_con_nip_enmascarado(self, sii):
        res = _run("sii-check", " 20110001 ")
        assert res.exit_code == 0, res.output
        out = res.output
        assert "APTA" in out and "NO APTA" not in out
        for rule in ("existe", "estatus", "creditos", "servicio_social", "residencia",
                     "sin_adeudos"):
            assert rule in out
        assert "Créditos completos (260)." in out
        assert "estatus" in out and "EGRESADO" in out          # hechos
        assert "first_name" in out and "Ana" in out             # identidad
        assert "NIP: ****" in out
        assert "4321" not in out
        assert "ms" in out
        assert "test-2026-09-25.1" in out

    def test_no_apta_con_motivos(self, sii):
        res = _run("sii-check", "20110002")
        assert res.exit_code == 0, res.output
        assert "NO APTA" in res.output
        assert "Le faltan créditos: 200 de 260." in res.output
        assert "8765" not in res.output

    def test_apta_sin_nip(self, sii):
        res = _run("sii-check", "20110003")
        assert res.exit_code == 0, res.output
        assert "sin NIP" in res.output

    def test_error_sale_distinto_de_cero(self, sii):
        res = _run("sii-check", "20119999")
        assert res.exit_code != 0
        assert "ERROR" in res.output and "alumno" in res.output

    def test_disabled(self, sii):
        sii["backend"] = "disabled"
        res = _run("sii-check", "20110001")
        assert res.exit_code != 0
        assert "deshabilitada" in res.output

    def test_columna_del_nip_mal_escrita_no_pasa_en_verde(self, sii, tmp_path):
        """`[credential] column = "nip"` pero `nip.sql` devuelve NIP_ALUMNO:
        antes decía «sin NIP» y salía 0; es un error de configuración."""
        sii["fake"] = _fake_con_nip(tmp_path, [{"NIP_ALUMNO": "4321"}])
        res = _run("sii-check", "20110001")
        assert res.exit_code != 0, res.output
        assert "Veredicto: APTA" in res.output
        assert "no devuelve la columna" in res.output
        assert "sin NIP" not in res.output
        assert "4321" not in res.output

    def test_consulta_del_nip_fallida_no_pasa_en_verde(self, sii, tmp_path):
        sii["fake"] = _fake_con_nip(tmp_path, {"error": "query"})
        res = _run("sii-check", "20110001")
        assert res.exit_code != 0, res.output
        assert "no se pudo consultar" in res.output


def _fake_con_nip(tmp_path, entry) -> Path:
    """El SII falso de las fixtures con otra respuesta de `nip` para 20110001."""
    data = json.loads((FIXTURES / "fake_sii.json").read_text(encoding="utf-8"))
    data["queries"]["nip"]["20110001"] = entry
    path = tmp_path / "fake_sii.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


class TestSiiCheckConConvocatoria:
    def test_abierta_se_aprobaria(self, sii, patched_session_local, make_cohort):
        cohort = make_cohort(name="Convocatoria SII prueba", status="open")
        res = _run("sii-check", "20110001", "--cohort", str(cohort.id))
        assert res.exit_code == 0, res.output
        assert "Convocatoria SII prueba" in res.output
        assert "se aprobaría automáticamente" in res.output

    def test_cerrada_quedaria_por_revisar(self, sii, patched_session_local, make_cohort):
        cohort = make_cohort(status="closed")
        res = _run("sii-check", "20110001", "--cohort", str(cohort.id))
        assert res.exit_code == 0, res.output
        assert "Por revisar" in res.output

    def test_no_apta_quedaria_por_revisar(self, sii, patched_session_local, make_cohort):
        cohort = make_cohort(status="open")
        res = _run("sii-check", "20110002", "--cohort", str(cohort.id))
        assert "Por revisar" in res.output

    def test_convocatoria_inexistente(self, sii, patched_session_local):
        res = _run("sii-check", "20110001", "--cohort", "999999999")
        assert res.exit_code != 0
        assert "999999999" in res.output
