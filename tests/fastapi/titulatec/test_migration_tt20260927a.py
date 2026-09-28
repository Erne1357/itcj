"""Contrato de la migración `tt20260927a`: `nip_status` en la consulta al SII,
`nip_source` en la solicitud, y el relleno desde `ProcessEvent`.

Solo lee el archivo de la migración (patrón de
`test_enrollment_request_service.py::test_el_modelo_y_la_migracion_declaran_el_mismo_predicado`,
~línea 645): el harness de tests arma el esquema con `create_all` (sin
Alembic), así que no hay forma de "correr" la migración aquí -- se verifica
su fuente.
"""
import re
from pathlib import Path

import itcj2
from itcj2.apps.titulatec.models import EnrollmentRequest

_MIGRACION = (Path(itcj2.__file__).resolve().parent.parent / "migrations" / "versions"
              / "tt20260927a_titulatec_sii_nip_status.py")


def _fuente() -> str:
    return _MIGRACION.read_text(encoding="utf-8")


def _cuerpo(nombre: str, src: str) -> str:
    """El cuerpo de `def {nombre}(...):` hasta la siguiente `def` a nivel de módulo."""
    m = re.search(rf"\ndef {nombre}\(.*?\).*?:\n(.*?)(?=\ndef \w|\Z)", src, re.S)
    assert m, f"no se encontro 'def {nombre}(...)' en la migracion"
    return m.group(1)


def test_revision_y_down_revision():
    src = _fuente()
    assert 'revision = "tt20260927a"' in src
    assert 'down_revision = "tt20260925b"' in src


def test_las_constantes_de_tabla_apuntan_a_las_tablas_correctas():
    src = _fuente()
    assert '_CHECKS = "titulatec_eligibility_checks"' in src
    assert '_REQUESTS = "titulatec_enrollment_requests"' in src


def test_upgrade_agrega_nip_status_en_checks_y_nip_source_en_requests():
    upgrade = _cuerpo("upgrade", _fuente())

    assert 'op.add_column(_CHECKS, sa.Column("nip_status"' in upgrade
    assert 'op.add_column(_REQUESTS, sa.Column("nip_source"' in upgrade
    # Ambas nullable: son columnas nuevas sobre tablas con filas existentes.
    add_nip_status = re.search(r'op\.add_column\(_CHECKS,.*?\)\)', upgrade, re.S).group(0)
    add_nip_source = re.search(r'op\.add_column\(_REQUESTS,.*?\)\)', upgrade, re.S).group(0)
    assert "nullable=True" in add_nip_status
    assert "nullable=True" in add_nip_source


def test_el_relleno_filtra_por_nip_source_del_payload_del_process_event():
    upgrade = _cuerpo("upgrade", _fuente())

    assert "titulatec_process_events" in upgrade or "_EVENTS" in upgrade
    assert "enrollment_self_service" in upgrade
    assert "payload->>'request_id'" in upgrade
    assert "payload->>'nip_source'" in upgrade
    assert "'sii'" in upgrade
    # Solo toca filas sin resolver -- no pisa un nip_source ya escrito.
    assert "nip_source IS NULL" in upgrade


def test_downgrade_quita_las_dos_columnas():
    downgrade = _cuerpo("downgrade", _fuente())

    assert 'op.drop_column(_REQUESTS, "nip_source")' in downgrade
    assert 'op.drop_column(_CHECKS, "nip_status")' in downgrade


def test_enrollment_request_declara_nip_source():
    assert "nip_source" in EnrollmentRequest.__table__.columns
    col = EnrollmentRequest.__table__.columns["nip_source"]
    assert col.nullable is True
    assert col.type.length == 20
