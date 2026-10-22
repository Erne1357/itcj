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
P_NWD_LIST = "titulatec.non_working_day.page.list"
P_NWD_MANAGE = "titulatec.non_working_day.api.manage"
P_ANX_OWN = "titulatec.anexo_iii.api.generate.own"
P_ANX_GEN = "titulatec.anexo_iii.api.generate"
P_ANX_REV = "titulatec.anexo_iii.api.review"
SINODAL_GRANTS = {"titulatec.synodal.page.my_reviews", "titulatec.synodal.api.vote",
                  "titulatec.chat.page.view", "titulatec.chat.api.read",
                  "titulatec.chat.api.send", "titulatec.chat.api.upload"}


def _dml_en_tmp(tmp_path):
    """Stub del 01 en un directorio temporal: el test no depende de database/ (gitignored)."""
    carpeta = tmp_path / "fase_2"
    carpeta.mkdir(parents=True)
    for nombre in ("01_titulacion_formato_b.sql", "02_sinodales.sql", "03_revision_sinodales.sql",
                   "04_anexo_iii.sql"):
        (carpeta / nombre).write_text("-- stub", encoding="utf-8")
    return tmp_path


def test_expected_son_exactamente_los_grants_del_spec():
    from itcj2.cli.titulatec import fase2

    assert fase2._FASE_2_EXPECTED == {
        "titulatec_titulacion": {P_LIST, P_READ_ALL, P_CORRECT, P_SYN_READ, P_NWD_LIST, P_NWD_MANAGE,
                                 P_ANX_GEN, P_ANX_REV},
        "titulatec_titulaciones": {P_LIST, P_CORRECT, P_SYN_READ, P_SYN_LIST, P_SYN_ASSIGN,
                                   P_SYN_REPLACE, P_TEACHER_LIST, P_TEACHER_MANAGE,
                                   P_NWD_LIST, P_NWD_MANAGE, P_ANX_GEN, P_ANX_REV},
        "titulatec_vinculacion": {P_TEACHER_LIST, P_TEACHER_MANAGE, P_SYN_REPLACE, P_ANX_GEN},
        "admin": {P_LIST, P_CORRECT, P_TEACHER_LIST, P_TEACHER_MANAGE, P_SYN_REPLACE,
                  P_PD_LIST, P_PD_MANAGE, P_NWD_LIST, P_NWD_MANAGE, P_ANX_GEN, P_ANX_REV},
        "graduate": {P_ANX_OWN},
        "titulatec_sinodal": SINODAL_GRANTS,
    }
    assert fase2._DML_FASE_2_DIR == "fase_2"
    assert fase2._DML_FASE_2_FILES == ["01_titulacion_formato_b.sql", "02_sinodales.sql",
                                       "03_revision_sinodales.sql", "04_anexo_iii.sql"]
    assert fase2._FASE_2_NEW_PERMISSIONS == {P_TEACHER_LIST, P_TEACHER_MANAGE, P_SYN_REPLACE,
                                             P_PD_LIST, P_PD_MANAGE, P_NWD_LIST, P_NWD_MANAGE,
                                             P_ANX_OWN, P_ANX_GEN, P_ANX_REV}
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
            patch.object(cli, "_reactivar_d12", return_value=3) as d12, \
            patch.object(cli, "_saltar_egel_fase6", return_value=2) as egel, \
            patch.object(cli, "_verify_fase_2", return_value=[]) as verificar, \
            patch.object(cli, "_avisos_fase_2", return_value=[]) as avisos:
        res = CliRunner().invoke(cli.init_titulatec_fase_2_command, [])

    assert res.exit_code == 0, res.output
    assert ejecutados == [("01_titulacion_formato_b.sql", {"invalidate_authz": False}),
                          ("02_sinodales.sql", {"invalidate_authz": False}),
                          ("03_revision_sinodales.sql", {"invalidate_authz": False}),
                          ("04_anexo_iii.sql", {"invalidate_authz": False})]
    inv.assert_called_once_with("titulatec")
    d12.assert_called_once_with()
    egel.assert_called_once_with()
    verificar.assert_called_once_with()
    avisos.assert_called_once_with()
    # I3: la corrida REAL reporta D12 (antes solo un RAISE NOTICE que nadie leía).
    assert "D12: 3 proceso(s) reactivado(s)." in res.output
    assert res.output.index("Completado: fase_2/04") < res.output.index("D12: 3")
    # C10: la correccion EGEL va DESPUES del 04 y se reporta con su conteo.
    assert "EGEL: 2 proceso(s) saltaron la fase 6." in res.output
    assert res.output.index("D12: 3") < res.output.index("EGEL: 2")
    assert "OK" in res.output


def test_los_avisos_se_imprimen_y_no_abortan(tmp_path, monkeypatch):
    """Una carrera corregida en «Carreras por departamento» ya no coincide con
    la siembra: es un AVISO (echo), nunca un problema que aborte."""
    from itcj2.cli.titulatec import fase2 as cli

    monkeypatch.setattr(cli, "DML_TITULATEC", _dml_en_tmp(tmp_path))
    aviso = "la carrera 'Ing. Tics' esta mapeada a ead (la siembra dice sys_computing)"
    with patch("itcj2.cli.core.execute_sql_file"), \
            patch("itcj2.core.services.authz_cache.invalidate_app"), \
            patch.object(cli, "_reactivar_d12", return_value=0), \
            patch.object(cli, "_saltar_egel_fase6", return_value=0), \
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
            patch.object(cli, "_reactivar_d12", return_value=0), \
            patch.object(cli, "_saltar_egel_fase6", return_value=0), \
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
    with patch("itcj2.cli.core.execute_sql_file") as correr, \
            patch.object(cli, "_reactivar_d12") as d12, \
            patch.object(cli, "_procesos_d12", return_value=7):
        res = CliRunner().invoke(cli.init_titulatec_fase_2_command, ["--dry-run"])

    assert res.exit_code == 0, res.output
    correr.assert_not_called()
    d12.assert_not_called()                     # el dry-run solo cuenta
    assert ARCHIVO in res.output
    assert "fase_2/02_sinodales.sql" in res.output
    assert "fase_2/03_revision_sinodales.sql" in res.output
    assert "se reactivarian 7 proceso(s)" in res.output


def _en_pausa_con_cotejo(db_session, make_user, make_process, seed_phase_defs, *, aprobado=True):
    """Proceso 'on_hold' con la fase `review_appointment` (por código) aprobada o no."""
    from sqlalchemy import text

    from itcj2.apps.titulatec.models import ProcessPhase

    seed_phase_defs()  # el CI arranca con el catalogo vacio
    num = db_session.execute(text(
        "SELECT number FROM titulatec_phase_definitions WHERE code = 'review_appointment'")).scalar()
    proc = make_process(make_user())
    proc.status = "on_hold"
    fase = db_session.query(ProcessPhase).filter_by(process_id=proc.id, phase_number=num).first()
    if fase is None:
        fase = ProcessPhase(process_id=proc.id, phase_number=num)
        db_session.add(fase)
    fase.status = "approved" if aprobado else "in_progress"
    db_session.flush()
    return proc


def test_contar_d12_es_solo_lectura_y_cuenta_los_en_pausa_con_cotejo_aprobado(
        db_session, make_user, make_process, seed_phase_defs, patched_session_local):
    from itcj2.cli.titulatec import fase2 as cli

    antes = cli._contar_d12(db_session)
    proc = _en_pausa_con_cotejo(db_session, make_user, make_process, seed_phase_defs)

    assert cli._contar_d12(db_session) == antes + 1
    assert cli._procesos_d12() == antes + 1
    assert db_session.get(type(proc), proc.id).status == "on_hold"  # nada se escribio


@pytest.mark.usefixtures("audit_mark")
def test_reactivar_d12_pasa_a_active_con_su_evento_y_es_idempotente(
        db_session, make_user, make_process, seed_phase_defs, patched_session_local):
    """I3 (revisión final): D12 ya no es un UPDATE crudo del SQL (sin rastro). Por
    ORM: 'active' + un `process_resumed` por proceso (`actor_id` NULL, payload
    `{"reason": "checkpoint", "source": "init-titulatec-fase-2"}`), que la red de
    la bitácora espeja. Solo los que pasaron el primer checkpoint; la segunda
    corrida no encuentra a nadie."""
    from itcj2.apps.titulatec.models import ProcessEvent
    from itcj2.cli.titulatec import fase2 as cli
    from tests.fastapi.titulatec.conftest import audit_query

    con = _en_pausa_con_cotejo(db_session, make_user, make_process, seed_phase_defs)
    sin = _en_pausa_con_cotejo(db_session, make_user, make_process, seed_phase_defs, aprobado=False)
    db_session.commit()
    pendientes = cli._contar_d12(db_session)
    assert pendientes >= 1

    assert cli._reactivar_d12() == pendientes
    db_session.expire_all()

    assert db_session.get(type(con), con.id).status == "active"
    assert db_session.get(type(sin), sin.id).status == "on_hold"
    (evento,) = db_session.query(ProcessEvent).filter_by(process_id=con.id,
                                                         event_type="process_resumed").all()
    assert evento.actor_id is None
    assert evento.payload == {"reason": "checkpoint", "source": "init-titulatec-fase-2"}
    assert evento.phase_number == con.current_phase
    assert not db_session.query(ProcessEvent).filter_by(process_id=sin.id).filter(
        ProcessEvent.event_type == "process_resumed").count()
    # La red de la bitácora espeja el evento (canal de quien corre el comando).
    espejo = audit_query(db_session).filter_by(source="process_event",
                                               action="process.process_resumed",
                                               process_id=con.id).all()
    assert len(espejo) == 1

    # Idempotente: nadie más que reactivar, ningún evento nuevo.
    assert cli._reactivar_d12() == 0
    assert db_session.query(ProcessEvent).filter_by(
        process_id=con.id, event_type="process_resumed").count() == 1


def test_verify_fase_2_exige_la_tarea_periodica_y_el_responsable(
        db_session, patched_session_local, monkeypatch):
    from sqlalchemy import text

    from itcj2.cli.titulatec import fase2 as cli

    monkeypatch.setattr(cli, "_FASE_2_PERIODIC_TASK", "titulatec.zz_inexistente")
    db_session.execute(text("UPDATE titulatec_phase_definitions SET responsible = 'vinculacion' "
                            "WHERE code = 'synodal_review'"))
    db_session.flush()
    texto = " | ".join(cli._verify_fase_2())
    assert "la fase synodal_review no tiene responsible=synodals" in texto
    assert "falta la tarea periodica titulatec.zz_inexistente" in texto

    db_session.execute(text(
        "INSERT INTO core_task_definitions (task_name, display_name, app_name, category, "
        "default_args, is_active) VALUES ('titulatec.zz_inexistente', 'zz', 'titulatec', "
        "'notification', '{}', TRUE)"))
    db_session.execute(text(
        "INSERT INTO core_periodic_tasks (name, task_name, cron_expression, kwargs_json, is_active) "
        "VALUES ('zz test', 'titulatec.zz_inexistente', '15 9 * * *', '{}', FALSE)"))
    db_session.flush()
    # M2 (revisión final): pausada desde /config/system/tasks NO aborta el re-run;
    # existe, así que el verificador calla y queda como AVISO.
    texto = " | ".join(cli._verify_fase_2())
    assert "titulatec.zz_inexistente" not in texto
    avisos = [a for a in cli._avisos_fase_2() if "titulatec.zz_inexistente" in a]
    assert len(avisos) == 1 and "esta inactiva" in avisos[0]


def test_la_tarea_activa_no_da_aviso(db_session, patched_session_local, monkeypatch):
    from sqlalchemy import text

    from itcj2.cli.titulatec import fase2 as cli

    monkeypatch.setattr(cli, "_FASE_2_PERIODIC_TASK", "titulatec.zz_activa")
    db_session.execute(text(
        "INSERT INTO core_task_definitions (task_name, display_name, app_name, category, "
        "default_args, is_active) VALUES ('titulatec.zz_activa', 'zz', 'titulatec', "
        "'notification', '{}', TRUE)"))
    db_session.execute(text(
        "INSERT INTO core_periodic_tasks (name, task_name, cron_expression, kwargs_json, is_active) "
        "VALUES ('zz activa', 'titulatec.zz_activa', '15 9 * * *', '{}', TRUE)"))
    db_session.flush()

    assert not [a for a in cli._avisos_fase_2() if "titulatec.zz_activa" in a]
    assert not [p for p in cli._verify_fase_2() if "titulatec.zz_activa" in p]


def _literales_unidos(sql: str) -> str:
    """`'a'\\n   'b'` -> `'ab'`: PostgreSQL une literales separados por un salto."""
    import re
    return re.sub(r"'\s*\n\s*'", "", sql)


@requires_dml
def test_el_03_siembra_lo_que_el_verificador_espera():
    sql = (DML / "fase_2/03_revision_sinodales.sql").read_text(encoding="utf-8")
    cuerpo = sql.split("DO $$", 1)[1]
    for codigo in (P_NWD_LIST, P_NWD_MANAGE, *SINODAL_GRANTS):
        assert f"'{codigo}'" in cuerpo
    assert "'titulatec.review_reminders'" in cuerpo and "'15 9 * * *'" in cuerpo
    assert "responsible = 'synodals'" in cuerpo and "'synodal_review'" in cuerpo
    # I3: D12 ya no vive en el SQL (lo hace el comando, por ORM, con su evento).
    assert "UPDATE titulatec_processes" not in cuerpo
    assert "review_appointment" not in cuerpo
    assert "ON CONFLICT (app_id, code) DO UPDATE SET description = EXCLUDED.description" in cuerpo
    assert "read.all" not in cuerpo
    assert "permission_id" not in cuerpo


@requires_dml
def test_el_03_copia_exacta_la_definicion_de_la_tarea():
    """M1 (revisión final): el ON CONFLICT del 03 reescribe `description` de
    `core_task_definitions`; si no es la de `TASK_DEFINITIONS` pisa la del código
    (y decía que avisaba «al departamento», falso)."""
    from itcj2.tasks.titulatec_tasks import TASK_DEFINITIONS

    (defn,) = [d for d in TASK_DEFINITIONS if d["task_name"] == "titulatec.review_reminders"]
    sql = _literales_unidos((DML / "fase_2/03_revision_sinodales.sql").read_text(encoding="utf-8"))
    cuerpo = sql.split("DO $$", 1)[1]
    assert f"'{defn['description']}'" in cuerpo
    assert f"'{defn['display_name']}'" in cuerpo
    assert "departamento" not in cuerpo.lower()
    assert "--" not in defn["description"], "execute_sql_file recorta tras dos guiones"


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

    for codigo in cli._FASE_2_NEW_PERMISSIONS - {P_NWD_LIST, P_NWD_MANAGE,
                                                  P_ANX_OWN, P_ANX_GEN, P_ANX_REV}:  # nacen en el 03 / 04
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


# ---------------------------------------------------------------------------
# 04_anexo_iii (fase 6)
# ---------------------------------------------------------------------------
@requires_dml
def test_el_04_siembra_lo_que_el_verificador_espera():
    sql = (DML / "fase_2/04_anexo_iii.sql").read_text(encoding="utf-8")
    cuerpo = sql.split("DO $$", 1)[1]
    for codigo in (P_ANX_OWN, P_ANX_GEN, P_ANX_REV):
        assert codigo in cuerpo
    assert "ON CONFLICT (app_id, code) DO NOTHING" in cuerpo
    assert "ON CONFLICT DO NOTHING" in cuerpo
    assert "permission_id" not in cuerpo
    assert "Informe técnico de residencia profesional" in cuerpo
    assert "Informe de proyecto de investigación" in cuerpo
    assert "product_label IS NULL" in cuerpo
    assert "'[4, 5, 6]'" in cuerpo


def test_verify_fase_2_exige_product_label_y_el_salto_de_egel(
        db_session, patched_session_local):
    from sqlalchemy import text

    from itcj2.apps.titulatec.models import Modality
    from itcj2.cli.titulatec import fase2 as cli

    for codigo in cli._FASE_2_PRODUCT_MODALITIES:
        if db_session.query(Modality).filter_by(code=codigo).first() is None:
            db_session.add(Modality(code=codigo, name=codigo))
    egel = db_session.query(Modality).filter_by(code="egel").first()
    if egel is None:
        egel = Modality(code="egel", name="EGEL")
        db_session.add(egel)
    db_session.flush()
    db_session.execute(text(
        "UPDATE titulatec_modalities SET product_label = NULL WHERE code = ANY(:c)"),
        {"c": list(cli._FASE_2_PRODUCT_MODALITIES)})
    egel.skips_phases = [4, 5]
    db_session.flush()

    problemas = cli._verify_fase_2()
    for codigo in cli._FASE_2_PRODUCT_MODALITIES:
        assert f"la modalidad {codigo} no tiene product_label" in problemas
    assert "la modalidad egel no salta [4, 5, 6]" in problemas

    db_session.execute(text(
        "UPDATE titulatec_modalities SET product_label = 'X' WHERE code = ANY(:c)"),
        {"c": list(cli._FASE_2_PRODUCT_MODALITIES)})
    egel.skips_phases = [4, 5, 6]
    db_session.flush()
    problemas = cli._verify_fase_2()
    assert not [x for x in problemas if "product_label" in x or "egel" in x]


def _en_fase_6(db_session, make_user, make_process, make_modality, seed_phase_defs,
               *, skips, status="active"):
    from itcj2.apps.titulatec.models import ProcessPhase

    seed_phase_defs()
    mod = make_modality(skips_phases=skips)
    proc = make_process(make_user(), modality=mod, current_phase=6, status=status)
    ph6 = db_session.query(ProcessPhase).filter_by(process_id=proc.id, phase_number=6).one()
    ph6.status = "in_progress"
    db_session.flush()
    db_session.commit()
    return proc


def test_saltar_egel_fase6_avanza_a_la_siguiente_y_es_idempotente(
        db_session, make_user, make_process, make_modality, seed_phase_defs,
        patched_session_local):
    from itcj2.apps.titulatec.models import ProcessEvent, ProcessPhase
    from itcj2.cli.titulatec import fase2 as cli

    egel = _en_fase_6(db_session, make_user, make_process, make_modality,
                      seed_phase_defs, skips=[4, 5, 6])
    normal = _en_fase_6(db_session, make_user, make_process, make_modality,
                        seed_phase_defs, skips=[4, 5])
    pausado = _en_fase_6(db_session, make_user, make_process, make_modality,
                         seed_phase_defs, skips=[4, 5, 6], status="on_hold")
    eventos_antes = db_session.query(ProcessEvent).filter_by(process_id=egel.id).count()

    assert cli._procesos_egel_fase6(db_session) >= 1
    assert cli._saltar_egel_fase6() >= 1
    db_session.expire_all()

    assert egel.current_phase == 7
    fases = {f.phase_number: f
             for f in db_session.query(ProcessPhase).filter_by(process_id=egel.id)}
    assert fases[6].status == "skipped"
    assert fases[7].status == "in_progress" and fases[7].started_at is not None
    # R1: la correccion no crea ni escribe ningun evento del expediente.
    assert db_session.query(ProcessEvent).filter_by(process_id=egel.id).count() == eventos_antes
    # Lo que no salta la fase 6 o no esta activo no se toca.
    assert normal.current_phase == 6 and pausado.current_phase == 6

    assert cli._saltar_egel_fase6() == 0
    assert egel.current_phase == 7


def test_el_dry_run_no_corrige_nada(tmp_path, monkeypatch):
    from itcj2.cli.titulatec import fase2 as cli

    monkeypatch.setattr(cli, "DML_TITULATEC", _dml_en_tmp(tmp_path))
    with patch("itcj2.cli.core.execute_sql_file"), \
            patch.object(cli, "_procesos_d12", return_value=0), \
            patch.object(cli, "_procesos_egel_fase6", return_value=4), \
            patch.object(cli, "_saltar_egel_fase6") as saltar:
        res = CliRunner().invoke(cli.init_titulatec_fase_2_command, ["--dry-run"])

    assert res.exit_code == 0, res.output
    saltar.assert_not_called()
    assert "fase_2/04_anexo_iii.sql" in res.output
    assert "se saltarian la fase 6 4 proceso(s)" in res.output
