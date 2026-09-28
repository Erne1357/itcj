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


def test_upgrade_fija_lock_timeout_antes_de_cualquier_ddl():
    """Alembic corre `tt20260927a` y `tt20260927b` en UNA transacción: los
    `ADD COLUMN` de aquí retienen ACCESS EXCLUSIVE sobre solicitudes y consultas
    hasta el COMMIT, y el `ALTER ... TYPE` de la b espera el de
    `titulatec_cohorts`. Sin tope, un lock ajeno sobre convocatorias congela la
    inscripción entera en vez de abortar el deploy. `SET LOCAL` vale para el
    resto de la transacción (las dos revisiones) y tiene que ir PRIMERO."""
    upgrade = _cuerpo("upgrade", _fuente())
    sentencias = [ln.strip() for ln in upgrade.splitlines()
                  if ln.strip() and not ln.strip().startswith("#")]

    assert sentencias[0] == 'op.execute("SET LOCAL lock_timeout = \'10s\'")', sentencias[:2]
    assert upgrade.index("lock_timeout") < upgrade.index("op.add_column")


def test_el_docstring_describe_el_dominio_real():
    """Revisión final (F2): una migración es historia durable. El docstring no
    puede invertir `not_needed`/NULL, atribuir `form` al modo oficial ni
    presentar el relleno como código muerto (el código desplegado desde
    `0b72d5f7` ya escribía `payload.nip_source='sii'`)."""
    import ast

    doc = ast.get_docstring(ast.parse(_fuente()))
    plano = " ".join(doc.split())

    assert "not_needed" in plano and "SI tenia cuenta" in plano
    assert "(tiene cuenta" not in plano, "NULL no significa «tiene cuenta»"
    assert "0b72d5f7" in plano, "el porqué real del relleno"
    assert "LEGADO desde el dia uno" not in plano
    assert "`school_services`/" not in plano, "`form` es solo del modo alterno"


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
