"""Comando `titulatec init-titulatec-fase-2`: unico camino del DML de la fase 2
del desarrollo (fases 3-8). Primer archivo: `fase_2/01_titulacion_formato_b.sql`.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from tests.fastapi.titulatec.conftest import _n
from tests.fastapi.titulatec.test_permissions_contract import requires_dml

ARCHIVO = "fase_2/01_titulacion_formato_b.sql"
DML = Path(__file__).resolve().parents[3] / "database" / "DML" / "titulatec"
P_LIST = "titulatec.titulacion.page.list"
P_READ_ALL = "titulatec.format_b.api.read.all"
P_CORRECT = "titulatec.format_b.api.correct_registry"
P_SYN_READ = "titulatec.synodal.api.read"
P_SYN_LIST = "titulatec.synodal.page.list"
P_SYN_ASSIGN = "titulatec.synodal.api.assign"
P_SYN_REPLACE = "titulatec.synodal.api.replace"
P_TEACHER_LIST = "titulatec.teacher.page.list"
P_TEACHER_MANAGE = "titulatec.teacher.api.manage"
P_PD_LIST = "titulatec.program_department.page.list"
P_PD_MANAGE = "titulatec.program_department.api.manage"


def _dml_en_tmp(tmp_path):
    """Stub del 01 en un directorio temporal: el test no depende de database/ (gitignored)."""
    carpeta = tmp_path / "fase_2"
    carpeta.mkdir(parents=True)
    for nombre in ("01_titulacion_formato_b.sql", "02_sinodales.sql"):
        (carpeta / nombre).write_text("-- stub", encoding="utf-8")
    return tmp_path


def test_expected_son_exactamente_los_grants_del_spec():
    from itcj2.cli.titulatec import fase2

    assert fase2._FASE_2_EXPECTED == {
        "titulatec_titulacion": {P_LIST, P_READ_ALL, P_CORRECT, P_SYN_READ},
        "titulatec_titulaciones": {P_LIST, P_CORRECT, P_SYN_READ, P_SYN_LIST, P_SYN_ASSIGN,
                                   P_SYN_REPLACE, P_TEACHER_LIST, P_TEACHER_MANAGE},
        "titulatec_vinculacion": {P_TEACHER_LIST, P_TEACHER_MANAGE, P_SYN_REPLACE},
        "admin": {P_LIST, P_CORRECT, P_TEACHER_LIST, P_TEACHER_MANAGE, P_SYN_REPLACE,
                  P_PD_LIST, P_PD_MANAGE},
    }
    assert fase2._DML_FASE_2_DIR == "fase_2"
    assert fase2._DML_FASE_2_FILES == ["01_titulacion_formato_b.sql", "02_sinodales.sql"]
    assert fase2._FASE_2_NEW_PERMISSIONS == {P_TEACHER_LIST, P_TEACHER_MANAGE, P_SYN_REPLACE,
                                             P_PD_LIST, P_PD_MANAGE}
    assert len(fase2._FASE_2_PROGRAM_DEPARTMENTS) == 29
    assert set(fase2._FASE_2_PROGRAM_DEPARTMENTS.values()) == set(fase2._FASE_2_DEPARTMENTS)
    assert len(fase2._FASE_2_DEPARTMENTS) == 8


def test_el_comando_corre_los_archivos_de_fase_2_y_verifica(tmp_path, monkeypatch):
    from itcj2.cli.titulatec import fase2 as cli

    monkeypatch.setattr(cli, "DML_TITULATEC", _dml_en_tmp(tmp_path))
    ejecutados = []
    with patch("itcj2.cli.core.execute_sql_file",
               side_effect=lambda ruta, **kw: ejecutados.append((Path(ruta).name, kw))), \
            patch("itcj2.core.services.authz_cache.invalidate_app") as inv, \
            patch.object(cli, "_verify_fase_2", return_value=[]) as verificar, \
            patch.object(cli, "_avisos_fase_2", return_value=[]) as avisos:
        res = CliRunner().invoke(cli.init_titulatec_fase_2_command, [])

    assert res.exit_code == 0, res.output
    assert ejecutados == [("01_titulacion_formato_b.sql", {"invalidate_authz": False}),
                          ("02_sinodales.sql", {"invalidate_authz": False})]
    inv.assert_called_once_with("titulatec")
    verificar.assert_called_once_with()
    avisos.assert_called_once_with()
    assert "OK" in res.output


def test_los_avisos_se_imprimen_y_no_abortan(tmp_path, monkeypatch):
    """Una carrera corregida en «Carreras por departamento» ya no coincide con
    la siembra: es un AVISO (echo), nunca un problema que aborte."""
    from itcj2.cli.titulatec import fase2 as cli

    monkeypatch.setattr(cli, "DML_TITULATEC", _dml_en_tmp(tmp_path))
    aviso = "la carrera 'Ing. Tics' esta mapeada a ead (la siembra dice sys_computing)"
    with patch("itcj2.cli.core.execute_sql_file"), \
            patch("itcj2.core.services.authz_cache.invalidate_app"), \
            patch.object(cli, "_verify_fase_2", return_value=[]), \
            patch.object(cli, "_avisos_fase_2", return_value=[aviso]):
        res = CliRunner().invoke(cli.init_titulatec_fase_2_command, [])

    assert res.exit_code == 0, res.output
    assert aviso in res.output and "AVISO" in res.output
    assert "OK" in res.output


def test_el_comando_aborta_si_no_aterrizo(tmp_path, monkeypatch):
    from itcj2.cli.titulatec import fase2 as cli

    monkeypatch.setattr(cli, "DML_TITULATEC", _dml_en_tmp(tmp_path))
    with patch("itcj2.cli.core.execute_sql_file"), \
            patch("itcj2.core.services.authz_cache.invalidate_app"), \
            patch.object(cli, "_verify_fase_2", return_value=["el rol admin no tiene x"]):
        res = CliRunner().invoke(cli.init_titulatec_fase_2_command, [])

    assert res.exit_code != 0
    assert "faltan archivos" not in res.output


def test_dry_run_con_archivo_ausente_aborta_sin_ejecutar(tmp_path, monkeypatch):
    from itcj2.cli.titulatec import fase2 as cli

    monkeypatch.setattr(cli, "DML_TITULATEC", tmp_path)  # sin fase_2/
    with patch("itcj2.cli.core.execute_sql_file") as correr:
        res = CliRunner().invoke(cli.init_titulatec_fase_2_command, ["--dry-run"])

    assert res.exit_code != 0
    correr.assert_not_called()
    assert "faltan archivos" in res.output


def test_dry_run_lista_el_archivo_y_no_ejecuta(tmp_path, monkeypatch):
    from itcj2.cli.titulatec import fase2 as cli

    monkeypatch.setattr(cli, "DML_TITULATEC", _dml_en_tmp(tmp_path))
    with patch("itcj2.cli.core.execute_sql_file") as correr:
        res = CliRunner().invoke(cli.init_titulatec_fase_2_command, ["--dry-run"])

    assert res.exit_code == 0, res.output
    correr.assert_not_called()
    assert ARCHIVO in res.output
    assert "fase_2/02_sinodales.sql" in res.output


def test_verify_fase_2_reporta_un_grant_faltante(db_session, make_role, patched_session_local):
    from itcj2.cli.titulatec import fase2 as cli
    from itcj2.core.models.permission import Permission
    from itcj2.core.models.role import Role
    from itcj2.core.models.role_permission import RolePermission

    for rol, codigos in cli._FASE_2_EXPECTED.items():
        make_role(rol, sorted(codigos))
    assert [x for x in cli._verify_fase_2() if x.startswith("el rol ") and " no tiene " in x] == []

    rol = db_session.query(Role).filter_by(name="titulatec_titulaciones").one()
    perm = db_session.query(Permission).filter_by(code=P_CORRECT).one()
    db_session.query(RolePermission).filter_by(role_id=rol.id, perm_id=perm.id).delete()
    db_session.flush()

    assert [x for x in cli._verify_fase_2() if x.startswith("el rol ") and " no tiene " in x] == [
        f"el rol titulatec_titulaciones no tiene {P_CORRECT}"]


@requires_dml
def test_el_sql_es_idempotente_y_concede_explicito():
    sql = (DML / ARCHIVO).read_text(encoding="utf-8")
    cuerpo = sql.split("DO $$", 1)[1]
    for codigo in (P_LIST, P_CORRECT, P_READ_ALL):
        assert codigo in cuerpo
    assert "ON CONFLICT (app_id, code) DO UPDATE SET description = EXCLUDED.description" in cuerpo
    assert "INSERT INTO core_role_permissions (role_id, perm_id)" in cuerpo
    assert "ON CONFLICT DO NOTHING" in cuerpo
    assert "permission_id" not in cuerpo


def test_verify_fase_2_detecta_cada_faltante_del_organigrama_y_los_datos(
        db_session, make_role, patched_session_local, monkeypatch):
    """El verificador de la fase 4 (spec §6, §16b): permisos, puestos, carreras,
    ajustes, option_label y fase 4. La base de prueba puede estar ya sembrada
    (dev), asi que se le piden elementos que no existen."""
    from sqlalchemy import text

    from itcj2.cli.titulatec import fase2 as cli

    monkeypatch.setattr(cli, "_FASE_2_NEW_PERMISSIONS", {"titulatec.zz.page.nope"})
    monkeypatch.setattr(cli, "_FASE_2_DEPARTMENTS", ("zz_depto",))
    monkeypatch.setattr(cli, "_FASE_2_PROGRAM_DEPARTMENTS", {"Carrera Zeta": "zz_depto"})
    monkeypatch.setattr(cli, "_FASE_2_MODALITIES", ("zz_mod",))
    db_session.execute(text("UPDATE titulatec_phase_definitions SET responsible = 'vinculacion' "
                            "WHERE code = 'synodal_assignment'"))
    db_session.flush()

    texto = " | ".join(cli._verify_fase_2())
    for fragmento in ("el permiso titulatec.zz.page.nope no existe",
                      "el puesto docente_zz_depto no existe",
                      "el puesto head_zz_depto no existe",
                      "la carrera 'Carrera Zeta' no existe en core_programs",
                      "falta el ajuste del oficio de zz_depto",
                      "la modalidad zz_mod no tiene option_label",
                      "la fase synodal_assignment no tiene responsible=academic_department"):
        assert fragmento in texto, (fragmento, texto)


@pytest.fixture()
def remapeo(db_session, make_department, make_program, make_program_department,
            make_position, monkeypatch):
    """Una carrera «sembrada» en `seed` y mapeada HOY a `destino` (con o sin
    puesto `docente_*`). El verificador solo mira las carreras y deptos que se
    le dan: la base de dev puede traer los reales."""
    from itcj2.cli.titulatec import fase2 as cli

    def _build(*, destino_con_docentes: bool, destino_en_la_lista: bool = False):
        n = _n()
        seed = make_department(code=f"zz_seed_{n}", name=f"Depto sembrado {n}")
        destino = make_department(code=f"zz_dest_{n}", name=f"Depto destino {n}")
        if destino_con_docentes:
            make_position(code=f"docente_{destino.code}", title="Docente", department=destino)
        carrera = make_program(f"Carrera Remapeada {n}")
        make_program_department(carrera, destino)
        monkeypatch.setattr(cli, "_FASE_2_PROGRAM_DEPARTMENTS", {carrera.name: seed.code})
        lista = (seed.code, destino.code) if destino_en_la_lista else (seed.code,)
        monkeypatch.setattr(cli, "_FASE_2_DEPARTMENTS", lista)
        return carrera, seed, destino
    return _build


def _de_la_carrera(textos, carrera):
    return [t for t in textos if f"'{carrera.name}'" in t]


def test_verify_fase_2_acepta_una_carrera_remapeada_a_otro_depto_con_docentes(
        remapeo, patched_session_local):
    """Hallazgo 2 de la revisión de rama: tras una corrección legítima en la
    pantalla, el comando ya no aborta para siempre. La diferencia con la
    siembra queda como aviso."""
    from itcj2.cli.titulatec import fase2 as cli

    carrera, seed, destino = remapeo(destino_con_docentes=True)

    assert _de_la_carrera(cli._verify_fase_2(), carrera) == []
    avisos = _de_la_carrera(cli._avisos_fase_2(), carrera)
    assert len(avisos) == 1 and destino.code in avisos[0] and seed.code in avisos[0]


def test_verify_fase_2_acepta_un_depto_de_la_lista_aunque_le_falte_el_puesto(
        remapeo, patched_session_local):
    from itcj2.cli.titulatec import fase2 as cli

    carrera, _seed, _destino = remapeo(destino_con_docentes=False, destino_en_la_lista=True)

    assert _de_la_carrera(cli._verify_fase_2(), carrera) == []


def test_verify_fase_2_rechaza_un_depto_sin_docentes_fuera_de_la_lista(
        remapeo, patched_session_local):
    from itcj2.cli.titulatec import fase2 as cli

    carrera, _seed, destino = remapeo(destino_con_docentes=False)

    problemas = _de_la_carrera(cli._verify_fase_2(), carrera)
    assert len(problemas) == 1 and destino.code in problemas[0]
    assert "docente_" in problemas[0]


def test_sin_remapeo_no_hay_aviso(db_session, make_department, make_program,
                                  make_program_department, make_position,
                                  patched_session_local, monkeypatch):
    from itcj2.cli.titulatec import fase2 as cli

    n = _n()
    dept = make_department(code=f"zz_igual_{n}", name=f"Depto igual {n}")
    make_position(code=f"docente_{dept.code}", title="Docente", department=dept)
    carrera = make_program(f"Carrera Sin Remapeo {n}")
    make_program_department(carrera, dept)
    monkeypatch.setattr(cli, "_FASE_2_PROGRAM_DEPARTMENTS", {carrera.name: dept.code})

    assert _de_la_carrera(cli._verify_fase_2(), carrera) == []
    assert _de_la_carrera(cli._avisos_fase_2(), carrera) == []


def test_verify_fase_2_exige_los_titulos_del_oficio(db_session, make_department,
                                                   patched_session_local, monkeypatch):
    """Hallazgo 17: el 02 siembra los títulos del oficio real; tras correrlo,
    un ajuste sin ellos es que el UPDATE no aterrizó."""
    from itcj2.apps.titulatec.models import DepartmentSettings
    from itcj2.cli.titulatec import fase2 as cli

    n = _n()
    dept = make_department(code=f"zz_tit_{n}", name=f"Depto titulos {n}")
    db_session.add(DepartmentSettings(department_id=dept.id, oficio_header="Depto",
                                      addressee_position_code="head_prof_studies_div",
                                      attn_position_code="head_titulacion"))
    db_session.flush()
    monkeypatch.setattr(cli, "_FASE_2_DEPARTMENTS", (dept.code,))

    texto = " | ".join(cli._verify_fase_2())
    assert f"el ajuste del oficio de {dept.code} no tiene el titulo del destinatario" in texto
    assert f"el ajuste del oficio de {dept.code} no tiene el titulo del Atn." in texto

    s = db_session.get(DepartmentSettings, dept.id)
    s.addressee_title, s.attn_title = cli._FASE_2_ADDRESSEE_TITLE, cli._FASE_2_ATTN_TITLE
    db_session.flush()
    texto = " | ".join(cli._verify_fase_2())
    assert f"oficio de {dept.code} no tiene" not in texto


def test_los_titulos_sembrados_son_los_del_oficio_real():
    from itcj2.cli.titulatec import fase2 as cli

    assert cli._FASE_2_ADDRESSEE_TITLE == "JEFA DE LA DIVISIÓN DE ESTUDIOS PROFESIONALES"
    assert cli._FASE_2_ATTN_TITLE == "Coordinadora de Apoyo a Titulación"


def test_verify_fase_2_detecta_read_all_en_sinodal(db_session, make_role, patched_session_local):
    from itcj2.cli.titulatec import fase2 as cli

    make_role("titulatec_sinodal", ["titulatec.document.api.read.all", "titulatec.synodal.api.read"])
    texto = " | ".join(cli._verify_fase_2())
    assert "titulatec_sinodal conserva titulatec.document.api.read.all" in texto
    assert "titulatec.synodal.api.read" not in texto.split("conserva")[-1]


@requires_dml
def test_el_02_siembra_lo_que_el_verificador_espera():
    sql = (DML / "fase_2/02_sinodales.sql").read_text(encoding="utf-8")
    cuerpo = sql.split("DO $$", 1)[1]
    from itcj2.cli.titulatec import fase2 as cli

    for codigo in cli._FASE_2_NEW_PERMISSIONS:
        assert f"'{codigo}'" in cuerpo
    for nombre in cli._FASE_2_PROGRAM_DEPARTMENTS:
        assert f"'{nombre}'" in cuerpo, nombre
    assert "ON CONFLICT (app_id, code) DO UPDATE SET description = EXCLUDED.description" in cuerpo
    assert "ON CONFLICT (program_id) DO NOTHING" in cuerpo
    assert "LIKE '%.read.all'" in cuerpo
    assert "permission_id" not in cuerpo
    # Títulos del oficio real (hallazgo 17): solo donde la columna sigue NULL,
    # para no pisar lo que se edite en la pantalla.
    assert f"addressee_title = '{cli._FASE_2_ADDRESSEE_TITLE}'" in cuerpo
    assert f"attn_title = '{cli._FASE_2_ATTN_TITLE}'" in cuerpo
    assert "addressee_title IS NULL" in cuerpo and "attn_title IS NULL" in cuerpo
