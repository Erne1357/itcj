"""Conector del SII (Tarea 2, spec 2026-09-25 §3.1).

- `FakeSiiClient`: el JSON sintético de `sii_fixtures/fake_sii.json` junto con
  las reglas sintéticas da los cinco casos del flujo (apta, no apta, apta sin
  NIP, adeudos, SII caído/SQL roto).
- `get_sii_client()`: elige backend leyendo SOLO `SiiConfig` (los tests
  parchean sus métodos estáticos, nunca `get_settings`).
- `OdbcSiiClient`: `pyodbc` NO está instalado en dev ni en CI (a propósito);
  aquí se simula con un módulo falso en `sys.modules`. Lo que se fija es el
  contrato con el driver (timeouts, autocommit, solo lectura, parámetros
  enlazados, filas → dict) y que ningún error saque la cadena de conexión.
"""
from __future__ import annotations

import json
import logging
import sys
import types
from pathlib import Path

import pytest

from itcj2.apps.titulatec.services.sii.client import (
    FakeSiiClient,
    OdbcSiiClient,
    SiiConfig,
    get_sii_client,
)
from itcj2.apps.titulatec.services.sii.errors import SiiQueryError, SiiUnavailable
from itcj2.apps.titulatec.services.sii.rules import RuleSet

FIXTURES = Path(__file__).parent / "sii_fixtures"
FAKE_FILE = FIXTURES / "fake_sii.json"

PASSWORD = "Contrasena-Muy-Secreta-123"
CONN = f"DRIVER=FreeTDS;SERVER=sii.local;PORT=5000;DATABASE=escolares;UID=lector;PWD={PASSWORD};TDS_Version=5.0"


# ---------------------------------------------------------------------------
# FakeSiiClient
# ---------------------------------------------------------------------------
class TestFakeSiiClient:
    def test_filas_por_consulta_y_parametro(self):
        c = FakeSiiClient(FAKE_FILE)
        c.ping()
        rows = c.query("SELECT … WHERE x = ?", ["20110001"], query_id="alumno")
        assert rows[0]["nombre"] == "Ana"
        assert c.query("SELECT 1 WHERE x = ?", ["00000000"], query_id="alumno") == []
        assert c.query("SELECT 1 WHERE x = ?", ["20110001"], query_id="no_declarada") == []

    def test_devuelve_copias(self):
        c = FakeSiiClient(FAKE_FILE)
        c.query("q", ["20110001"], query_id="alumno")[0]["nombre"] = "X"
        assert c.query("q", ["20110001"], query_id="alumno")[0]["nombre"] == "Ana"

    def test_fallas_simuladas(self):
        c = FakeSiiClient(FAKE_FILE)
        with pytest.raises(SiiUnavailable):
            c.query("q", ["20119999"], query_id="alumno")
        with pytest.raises(SiiQueryError):
            c.query("q", ["20119998"], query_id="alumno")

    def test_sin_query_id_es_error_de_consulta(self):
        with pytest.raises(SiiQueryError):
            FakeSiiClient(FAKE_FILE).query("q", ["20110001"])

    def test_archivo_inexistente_o_roto_es_sii_no_disponible(self, tmp_path):
        with pytest.raises(SiiUnavailable):
            FakeSiiClient(tmp_path / "no.json").ping()
        roto = tmp_path / "roto.json"
        roto.write_text("{no es json", encoding="utf-8")
        with pytest.raises(SiiUnavailable):
            FakeSiiClient(roto).query("q", ["1"], query_id="alumno")
        sin_queries = tmp_path / "vacio.json"
        sin_queries.write_text(json.dumps({"otra": 1}), encoding="utf-8")
        with pytest.raises(SiiUnavailable):
            FakeSiiClient(sin_queries).ping()


class TestFakeConLasReglasSinteticas:
    """Los casos que usarán el servicio (Tarea 4) y el E2E con el SII falso."""

    @pytest.fixture()
    def rs(self):
        rs = RuleSet.load(FIXTURES)
        assert rs.validate() == []
        return rs

    def test_apta_con_nip(self, rs):
        c = FakeSiiClient(FAKE_FILE)
        v = rs.evaluate(c, "20110001")
        assert v.status == "apt", v
        assert v.identity["first_name"] == "Ana"
        assert rs.fetch_credential(c, "20110001").reveal() == "4321"

    def test_no_apta_con_motivos(self, rs):
        v = rs.evaluate(FakeSiiClient(FAKE_FILE), "20110002")
        assert v.status == "not_apt"
        fallas = {r.rule: r.message for r in v.results if not r.ok}
        assert fallas == {
            "creditos": "Le faltan créditos: 200 de 260.",
            "servicio_social": "El servicio social no aparece liberado en el SII.",
        }

    def test_apta_sin_nip(self, rs):
        c = FakeSiiClient(FAKE_FILE)
        assert rs.evaluate(c, "20110003").status == "apt"
        assert rs.fetch_credential(c, "20110003") is None

    def test_adeudos(self, rs):
        v = rs.evaluate(FakeSiiClient(FAKE_FILE), "20110004")
        assert v.status == "not_apt"
        assert [r.message for r in v.results if not r.ok] == [
            "Tiene adeudos en el SII (p. ej. BIBLIOTECA)."]

    def test_no_existe(self, rs):
        v = rs.evaluate(FakeSiiClient(FAKE_FILE), "20110000")
        assert v.status == "not_apt"
        assert v.results[0].rule == "existe" and v.results[0].ok is False

    @pytest.mark.parametrize("control", ["20119999", "20119998"])
    def test_error(self, rs, control):
        v = rs.evaluate(FakeSiiClient(FAKE_FILE), control)
        assert v.status == "error"
        assert "alumno" in v.error


# ---------------------------------------------------------------------------
# get_sii_client
# ---------------------------------------------------------------------------
def _config(monkeypatch, backend, conn=CONN, fake=FAKE_FILE):
    monkeypatch.setattr(SiiConfig, "backend", staticmethod(lambda: backend))
    monkeypatch.setattr(SiiConfig, "odbc_connection_string", staticmethod(lambda: conn))
    monkeypatch.setattr(SiiConfig, "fake_file", staticmethod(lambda: Path(fake)))
    monkeypatch.setattr(SiiConfig, "connect_timeout", staticmethod(lambda: 7))
    monkeypatch.setattr(SiiConfig, "query_timeout", staticmethod(lambda: 11))


class TestGetSiiClient:
    def test_disabled_lanza_no_disponible(self, monkeypatch):
        _config(monkeypatch, "disabled")
        with pytest.raises(SiiUnavailable, match="deshabilitad"):
            get_sii_client()

    def test_fake(self, monkeypatch):
        _config(monkeypatch, "fake")
        c = get_sii_client()
        assert isinstance(c, FakeSiiClient)
        assert c.query("q", ["20110001"], query_id="alumno")[0]["nombre"] == "Ana"

    def test_odbc_no_conecta_al_construirse(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "pyodbc", None)  # ni siquiera instalado
        _config(monkeypatch, "odbc")
        c = get_sii_client()
        assert isinstance(c, OdbcSiiClient)
        assert PASSWORD not in repr(c)

    def test_odbc_sin_cadena_es_no_disponible(self, monkeypatch):
        _config(monkeypatch, "odbc", conn="  ")
        with pytest.raises(SiiUnavailable):
            get_sii_client()

    def test_config_real_lee_settings(self, monkeypatch):
        """Sin parches, `SiiConfig` sale de `get_settings()` y resuelve las
        rutas relativas contra la raíz del proyecto."""
        from pydantic import SecretStr
        from itcj2.config import get_settings

        s = get_settings()
        monkeypatch.setattr(s, "TITULATEC_SII_BACKEND", "fake")
        monkeypatch.setattr(s, "TITULATEC_SII_ODBC", SecretStr(CONN))
        monkeypatch.setattr(s, "TITULATEC_SII_FAKE_FILE", "database/SII/titulatec/fake_sii.json")
        monkeypatch.setattr(s, "TITULATEC_SII_RULES_DIR", "database/SII/titulatec")
        assert SiiConfig.backend() == "fake"
        assert SiiConfig.odbc_connection_string() == CONN
        assert SiiConfig.fake_file().is_absolute()
        assert SiiConfig.fake_file().parts[-3:] == ("SII", "titulatec", "fake_sii.json")
        assert SiiConfig.rules_dir().parts[-2:] == ("SII", "titulatec")
        assert SiiConfig.connect_timeout() == s.TITULATEC_SII_CONNECT_TIMEOUT_S
        assert SiiConfig.query_timeout() == s.TITULATEC_SII_QUERY_TIMEOUT_S


# ---------------------------------------------------------------------------
# OdbcSiiClient con pyodbc simulado
# ---------------------------------------------------------------------------
def _fake_pyodbc(*, connect_error=None, execute_error=None, rows=None, description=None):
    mod = types.ModuleType("pyodbc")

    class Error(Exception):
        pass

    class InterfaceError(Error):
        pass

    class DatabaseError(Error):
        pass

    class OperationalError(DatabaseError):
        pass

    class ProgrammingError(DatabaseError):
        pass

    mod.Error = Error
    mod.InterfaceError = InterfaceError
    mod.DatabaseError = DatabaseError
    mod.OperationalError = OperationalError
    mod.ProgrammingError = ProgrammingError
    mod.calls = {"connect": [], "execute": [], "closed": 0}

    class Cursor:
        def __init__(self):
            self.description = description

        def execute(self, sql, *params):
            mod.calls["execute"].append((sql, params))
            if execute_error is not None:
                raise execute_error(mod)
            return self

        def fetchall(self):
            return list(rows or [])

        def close(self):
            pass

    class Conn:
        timeout = 0

        def cursor(self):
            return Cursor()

        def close(self):
            mod.calls["closed"] += 1

    def connect(cs, **kwargs):
        mod.calls["connect"].append((cs, kwargs))
        if connect_error is not None:
            raise connect_error(mod)
        conn = Conn()
        mod.conn = conn
        return conn

    mod.connect = connect
    return mod


def _odbc():
    return OdbcSiiClient(CONN, connect_timeout=7, query_timeout=11)


class TestOdbcSiiClient:
    def test_contrato_con_el_driver(self, monkeypatch):
        mod = _fake_pyodbc(
            rows=[("20110001", "Ana   ", 260), ("20110001", None, 1)],
            description=[("NO_DE_CONTROL",), ("Nombre",), ("creditos",)],
        )
        monkeypatch.setitem(sys.modules, "pyodbc", mod)
        c = _odbc()
        rows = c.query("SELECT a FROM x WHERE ctl = ?", ["20110001"], query_id="alumno")

        cs, kwargs = mod.calls["connect"][0]
        assert cs == CONN
        assert kwargs == {"timeout": 7, "autocommit": True, "readonly": True}
        assert mod.conn.timeout == 11
        assert mod.calls["execute"] == [("SELECT a FROM x WHERE ctl = ?", ("20110001",))]
        assert rows == [
            {"no_de_control": "20110001", "nombre": "Ana", "creditos": 260},
            {"no_de_control": "20110001", "nombre": None, "creditos": 1},
        ]
        c.query("SELECT 1 WHERE ? = 1", ["x"])
        assert len(mod.calls["connect"]) == 1, "reutiliza la conexión"
        c.close()
        assert mod.calls["closed"] == 1

    def test_ping(self, monkeypatch):
        mod = _fake_pyodbc(rows=[(1,)], description=[("uno",)])
        monkeypatch.setitem(sys.modules, "pyodbc", mod)
        _odbc().ping()
        assert mod.calls["execute"][0][0].strip().upper().startswith("SELECT 1")

    def test_sin_pyodbc_instalado(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "pyodbc", None)
        with pytest.raises(SiiUnavailable, match="pyodbc"):
            _odbc().ping()

    def test_error_de_conexion_sin_la_cadena(self, monkeypatch, caplog):
        caplog.set_level(logging.DEBUG)
        mod = _fake_pyodbc(connect_error=lambda m: m.OperationalError(
            "08001", f"[FreeTDS] Unable to connect: {CONN} (PWD={PASSWORD})"))
        monkeypatch.setitem(sys.modules, "pyodbc", mod)
        with pytest.raises(SiiUnavailable) as ei:
            _odbc().query("SELECT 1 WHERE ? = 1", ["x"])
        exc = ei.value
        assert PASSWORD not in str(exc) and "PWD=" not in str(exc).replace("PWD=****", "")
        assert CONN not in str(exc)
        assert "08001" in str(exc)
        assert exc.__cause__ is None and exc.__suppress_context__ is True
        assert PASSWORD not in caplog.text

    def test_timeout_de_consulta_es_no_disponible(self, monkeypatch):
        mod = _fake_pyodbc(execute_error=lambda m: m.OperationalError(
            "HYT00", "[FreeTDS] Query timeout expired"))
        monkeypatch.setitem(sys.modules, "pyodbc", mod)
        c = _odbc()
        with pytest.raises(SiiUnavailable, match="HYT00"):
            c.query("SELECT 1 WHERE ? = 1", ["x"])
        # tras un SiiUnavailable se descarta la conexión: el siguiente intento reconecta
        with pytest.raises(SiiUnavailable):
            c.query("SELECT 1 WHERE ? = 1", ["x"])
        assert len(mod.calls["connect"]) == 2

    def test_sql_invalido_es_error_de_consulta(self, monkeypatch):
        mod = _fake_pyodbc(execute_error=lambda m: m.ProgrammingError(
            "42S02", f"Invalid object name 'alumnos'. PWD={PASSWORD}"))
        monkeypatch.setitem(sys.modules, "pyodbc", mod)
        with pytest.raises(SiiQueryError) as ei:
            _odbc().query("SELECT 1 WHERE ? = 1", ["x"])
        assert "42S02" in str(ei.value)
        assert PASSWORD not in str(ei.value)

    def test_el_password_suelto_tambien_se_tapa(self, monkeypatch):
        """Algunos drivers repiten solo el VALOR (sin `PWD=`)."""
        mod = _fake_pyodbc(connect_error=lambda m: m.InterfaceError(
            "28000", f"Login failed for user 'lector' with password '{PASSWORD}'"))
        monkeypatch.setitem(sys.modules, "pyodbc", mod)
        with pytest.raises(SiiUnavailable) as ei:
            _odbc().ping()
        assert PASSWORD not in str(ei.value)

    def test_repr_sin_secretos(self):
        c = _odbc()
        assert PASSWORD not in repr(c) and CONN not in repr(c)
        assert PASSWORD not in str(vars(c))


def test_importar_el_modulo_no_requiere_pyodbc():
    """Un proceso limpio, con `pyodbc` bloqueado, importa el conector y el
    motor sin tronar (el backend arranca sin el driver)."""
    import subprocess

    code = "; ".join([
        "import sys",
        "sys.modules['pyodbc'] = None",
        "import itcj2.apps.titulatec.services.sii.client as c",
        "import itcj2.apps.titulatec.services.sii.rules",
        "assert 'pyodbc' not in vars(c)",
    ])
    res = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         cwd=str(Path(__file__).resolve().parents[3]))
    assert res.returncode == 0, res.stderr
