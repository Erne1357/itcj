"""SII FALSO compartido por las pruebas de titulatec que consultan al SII.

Arma el JSON del SII falso por prueba en `tmp_path` y parchea `SiiConfig`
(nunca `get_settings`), con las reglas sintéticas de `sii_fixtures/`. Los
números de control son sintéticos (`9955xxxx`, `9958xxxx`): los `2011xxxx` de
`sii_fixtures/fake_sii.json` podrían existir como cuentas reales en la BD de
dev, y «¿tiene cuenta?» se decide contra `core_users`.

`pide_nip` es el espía de `fetch_sii_nip` (anota cada control al que se le
pidió el NIP y deja responder al real); antes vivía duplicado en
`test_enrollment_approve.py` y `test_eligibility_service.py`.

Uso desde un archivo de prueba (pytest toma la fixture del espacio de nombres
del módulo; mismo patrón que `test_documents_fifo.py`)::

    from tests.fastapi.titulatec._sii_fake import pide_nip, sii  # noqa: F401
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from itcj2.apps.titulatec.services.sii.client import SiiConfig

FIXTURES = Path(__file__).parent / "sii_fixtures"
NIP_SII = "4321"
RULES_VERSION = "test-2026-09-25.1"


class FakeSii:
    """El JSON del SII falso de UNA prueba (controles sintéticos)."""

    def __init__(self, path: Path):
        self.path = path
        self.data = {"queries": {"alumno": {}, "adeudos": {}, "nip": {}}}
        self.backend = "fake"
        self.rules = FIXTURES
        self._write()

    def _write(self):
        self.path.write_text(json.dumps(self.data), encoding="utf-8")

    def alumno(self, control, *, nombre="EGRESADA", paterno="DEL SII", materno=None,
               carrera="Ingenieria Ficticia", nip=NIP_SII, **over):
        """Alumno apto. `nip=None` no toca el NIP que ya hubiera (ver `sin_nip`)."""
        row = {"no_de_control": control, "nombre": nombre, "apellido_paterno": paterno,
               "apellido_materno": materno, "carrera": carrera, "anio_ingreso": 2019,
               "estatus": "EGRESADO", "creditos_aprobados": 260, "creditos_carrera": 260,
               "servicio_social": "S", "residencia": "S"}
        row.update(over)
        self.data["queries"]["alumno"][control] = [row]
        if nip is not None:
            self.data["queries"]["nip"][control] = [{"nip": nip}]
        self._write()

    def no_apta(self, control, **kw):
        self.alumno(control, creditos_aprobados=200, **kw)

    def sin_nip(self, control):
        """El SII responde, pero ya no tiene NIP para `control` (0 filas)."""
        self.data["queries"]["nip"].pop(control, None)
        self._write()

    def caido(self, control):
        self.data["queries"]["alumno"][control] = {"error": "unavailable"}
        self._write()

    def nip_caido(self, control):
        self.data["queries"]["nip"][control] = {"error": "unavailable"}
        self._write()

    def consulta_invalida(self, control):
        """`SiiQueryError`: el SII respondió, pero la consulta no sirve."""
        self.data["queries"]["alumno"][control] = {"error": "query"}
        self._write()

    def nip_invalido(self, control):
        """`SiiQueryError` al pedir el NIP (p. ej. sin permiso sobre la tabla)."""
        self.data["queries"]["nip"][control] = {"error": "query"}
        self._write()


@pytest.fixture()
def sii(monkeypatch, tmp_path):
    """SII falso (backend `fake`) sobre un JSON propio de la prueba."""
    fake = FakeSii(tmp_path / "fake_sii.json")
    monkeypatch.setattr(SiiConfig, "backend", staticmethod(lambda: fake.backend))
    monkeypatch.setattr(SiiConfig, "fake_file", staticmethod(lambda: fake.path))
    monkeypatch.setattr(SiiConfig, "rules_dir", staticmethod(lambda: Path(fake.rules)))
    monkeypatch.setattr(SiiConfig, "odbc_connection_string", staticmethod(lambda: ""))
    return fake


@pytest.fixture()
def pide_nip(monkeypatch):
    """Espía de `fetch_sii_nip`: anota el control y deja responder al real."""
    from itcj2.apps.titulatec.services import eligibility_service as elig

    llamadas = []
    real = elig.fetch_sii_nip

    def _espia(control):
        llamadas.append(control)
        return real(control)

    monkeypatch.setattr(elig, "fetch_sii_nip", _espia)
    return llamadas
