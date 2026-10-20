"""Contrato de `core_programs.level` (spec 2026-09-30-titulatec-posgrado-
design.md D1, §4.1): nivel academico de una carrera. Es la unica pieza que
TitulaTec usara (tarea aparte, `TrackService`) para resolver el perfil
"posgrado" de un proceso de titulacion -- nadie mas debe comparar nombres de
carrera ni `level` directamente.

Solo modelo + migracion (`tt20260930a`): sin service ni DML de clasificacion
todavia (esos son tareas aparte del mismo plan).
"""
import importlib.util
from pathlib import Path

import pytest
import itcj2
from sqlalchemy import CheckConstraint
from sqlalchemy.exc import IntegrityError

from itcj2.core.models.program import Program

_MIGRACION = (
    Path(itcj2.__file__).resolve().parent.parent
    / "migrations"
    / "versions"
    / "tt20260930a_core_programs_level.py"
)


def _modulo():
    spec = importlib.util.spec_from_file_location("tt20260930a_mig", _MIGRACION)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _nombre_unico(etiqueta: str) -> str:
    """`Program.name` es UNIQUE y `db_session` corre contra la BD de dev
    compartida: un nombre fijo chocaria con otro test o con una carrera real.
    """
    import uuid
    return f"{etiqueta} {uuid.uuid4().hex[:8]}"


def test_nivel_por_omision_es_licenciatura(db_session):
    prog = Program(name=_nombre_unico("Nivel por omision"))
    db_session.add(prog)
    db_session.flush()
    db_session.refresh(prog)

    assert prog.level == "licenciatura"


def test_check_rechaza_nivel_fuera_de_dominio(db_session):
    prog = Program(name=_nombre_unico("Nivel invalido"))
    db_session.add(prog)
    db_session.flush()

    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            prog.level = "especialidad"
            db_session.flush()


def test_is_postgraduate(db_session):
    maestria = Program(name=_nombre_unico("Maestria"), level="maestria")
    doctorado = Program(name=_nombre_unico("Doctorado"), level="doctorado")
    licenciatura = Program(name=_nombre_unico("Licenciatura"), level="licenciatura")
    db_session.add_all([maestria, doctorado, licenciatura])
    db_session.flush()

    assert maestria.is_postgraduate is True
    assert doctorado.is_postgraduate is True
    assert licenciatura.is_postgraduate is False


def test_migracion_encadena_sobre_tt20260929a():
    mod = _modulo()
    assert mod.revision == "tt20260930a"
    assert mod.down_revision == "tt20260929a"


def test_migracion_y_modelo_nombran_el_mismo_check():
    """El modelo (`create_all`, CI) y la migracion (dev/prod) tienen que
    cerrar el MISMO dominio -- si alguno de los dos cambia sin el otro, un
    entorno acepta un nivel que el otro rechaza.
    """
    checks = [c for c in Program.__table__.constraints
              if isinstance(c, CheckConstraint)]
    assert len(checks) == 1, "Program debe declarar exactamente un CheckConstraint"

    check = checks[0]
    assert check.name == "ck_core_programs_level"

    dominio = str(check.sqltext)
    src = _MIGRACION.read_text(encoding="utf-8")

    assert "ck_core_programs_level" in src
    assert dominio in src
