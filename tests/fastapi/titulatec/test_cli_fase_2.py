"""Comando `titulatec init-titulatec-fase-2`: unico camino del DML de la fase 2
del desarrollo (fases 3-8). Primer archivo: `fase_2/01_titulacion_formato_b.sql`.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

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
            patch.object(cli, "_verify_fase_2", return_value=[]) as verificar:
        res = CliRunner().invoke(cli.init_titulatec_fase_2_command, [])

    assert res.exit_code == 0, res.output
    assert ejecutados == [("01_titulacion_formato_b.sql", {"invalidate_authz": False}),
                          ("02_sinodales.sql", {"invalidate_authz": False})]
    inv.assert_called_once_with("titulatec")
    verificar.assert_called_once_with()
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
