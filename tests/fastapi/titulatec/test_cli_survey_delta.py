"""Contrato del comando `titulatec load-survey-2026-09`.

Por que existe
--------------
Los `RAISE NOTICE` del DML son INVISIBLES: nada en `itcj2/` lee
`connection.notices`, asi que sin una verificacion posterior el operador ve
"OK" pase lo que pase — incluido el caso en que el rol al que se concede el
permiso no existe todavia y el `INSERT ... SELECT` inserta CERO filas sin
error. Es el mismo motivo por el que `itcj2/cli/directory.py:78-95` tiene
`_verify_settings_permission`, y este comando esta calcado de aquel.

`execute_sql_file` se importa DENTRO de la funcion del comando (import local,
convencion del proyecto contra los circulares), asi que el patch va sobre el
modulo FUENTE `itcj2.cli.core`, no sobre `itcj2.cli.titulatec`.
"""
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from itcj2.cli.titulatec import (
    DML_TITULATEC,
    SEED_FILES,
    _DML_SURVEY_2026_09_DIR,
    _DML_SURVEY_2026_09_FILES,
    _SURVEY_2026_09_PERMS,
    load_survey_2026_09_command,
)

# `load_survey_2026_09_command` exige el directorio EN DISCO (comprueba
# `dml_dir.is_dir()` antes de llegar a cualquier mock: itcj2/cli/titulatec.py,
# guarda al inicio de `load_survey_2026_09_command`). `database/` esta
# gitignored y el workflow de deploy nunca lo hace checkout (trae PII real),
# asi que en CI ese directorio no existe: sin este guard,
# `test_dry_run_no_ejecuta_sql_ni_verifica`,
# `test_todo_sql_del_delta_esta_en_la_lista_del_comando`,
# `test_corre_todos_los_archivos_del_delta_y_ninguno_mas` y
# `test_aborta_si_la_verificacion_reporta_un_permiso_sin_aterrizar` abortan
# ANTES de que sus mocks entren en juego, y el "Tests (BLOQUEANTE — suite
# completa)" del deploy sale rojo en cada push a main. Mismo patron que
# `requires_dml` en test_permissions_contract.py:148-155. Las dos pruebas que
# solo verifican las constantes de Python (`SEED_FILES`, `_SURVEY_2026_09_PERMS`)
# NO necesitan el directorio: se quedan sin guard para que CI las siga
# ejerciendo.
requires_dml = pytest.mark.skipif(
    not (DML_TITULATEC / _DML_SURVEY_2026_09_DIR).is_dir(),
    reason=(
        "database/DML/titulatec/survey_2026_09/ no esta en el checkout "
        "(gitignored a proposito: trae PII real y nunca llega a CI). Esta "
        "prueba invoca el comando de verdad, que exige el directorio en "
        "disco antes de que los mocks de execute_sql_file/_verify_survey_2026_09 "
        "entren en juego."
    ),
)


def test_el_delta_esta_en_seed_files_con_su_prefijo_de_subcarpeta():
    """Sin esto, una base NUEVA (`core seed-reference-data`) nace sin los 8.

    `_titulatec_seed_files()` (itcj2/cli/core.py:205-215) hace
    `f"titulatec/{name}"` y el bucle de `seed_reference_data_command`
    (`:346-352`) OMITE EN SILENCIO el archivo que no existe, saliendo 0.
    """
    for nombre in _DML_SURVEY_2026_09_FILES:
        assert f"survey_2026_09/{nombre}" in SEED_FILES, (
            f"{nombre} no esta en SEED_FILES con el prefijo survey_2026_09/")


def test_los_once_codigos_del_delta_son_los_del_contrato():
    assert set(_SURVEY_2026_09_PERMS) == {
        "titulatec.survey.page.list",
        "titulatec.survey.api.read",
        "titulatec.survey.api.export",
        "titulatec.survey.api.manage",
        "titulatec.enrollment_request.page.list",
        "titulatec.enrollment_request.api.approve",
        "titulatec.enrollment_request.api.reject",
        "titulatec.process.api.requirement.mark",
        # 2026-09-15: liberacion de la encuesta por GTV (spec
        # 2026-09-15-titulatec-liberacion-gtv).
        "titulatec.survey_review.page.list",
        "titulatec.survey_review.api.approve",
        "titulatec.survey_review.api.reject",
    }


@requires_dml
def test_dry_run_no_ejecuta_sql_ni_verifica():
    with patch("itcj2.cli.core.execute_sql_file") as ejecutar, \
         patch("itcj2.cli.titulatec._verify_survey_2026_09") as verificar:
        res = CliRunner().invoke(load_survey_2026_09_command, ["--dry-run"])

    assert res.exit_code == 0, res.output
    ejecutar.assert_not_called()
    verificar.assert_not_called()
    assert "[dry-run]" in res.output


@requires_dml
def test_todo_sql_del_delta_esta_en_la_lista_del_comando():
    """Membresia: ningun .sql del directorio puede quedarse sin comando.

    Asi se perdio el 13 (B3 de la revision final). El archivo existia en disco,
    no lo referenciaba NADA --ni `SEED_FILES` ni `_DML_SURVEY_2026_09_FILES` ni
    `itcj2/` ni `scripts/`-- y por tanto ni `init-titulatec` ni
    `load-survey-2026-09` lo corrian. El sintoma no era un error: era que la
    guarda de la fase 2 no disparaba NUNCA en ninguna convocatoria anterior al
    2026-09-08, porque `RequirementService.missing_required` devuelve `[]`
    cuando la convocatoria tiene cero requisitos.

    Se compara contra el disco, no contra una lista escrita a mano, para que el
    delta siguiente no pueda repetirlo: agregar un .sql sin agregarlo aqui sale
    rojo. La direccion contraria la cubre el `assert` de abajo.
    """
    en_disco = sorted(p.name for p in
                      (DML_TITULATEC / _DML_SURVEY_2026_09_DIR).glob("*.sql"))

    assert en_disco == sorted(_DML_SURVEY_2026_09_FILES), (
        "el directorio del delta y la lista del comando divergen: "
        f"en disco {en_disco}, en la lista {sorted(_DML_SURVEY_2026_09_FILES)}. "
        "Un .sql que no este en la lista NO lo corre ningun comando, y nada mas "
        "se pone rojo.")

    # Piso explicito: comparar disco contra lista no detecta que se borren los
    # dos lados a la vez. Estos seis son el delta tal como se diseno (el 14 entro
    # el 2026-09-15 con el rol `graduate`).
    for nombre in ("09_insert_survey_perms.sql",
                   "10_insert_survey_role_permissions.sql",
                   "11_seed_survey_form.sql",
                   "12_seed_cotejo_codes.sql",
                   "13_seed_cotejo_reqs_all_cohorts.sql",
                   "14_graduate_role_backfill.sql"):
        assert nombre in en_disco, f"falta {nombre} en el directorio del delta"


def test_el_backfill_de_graduate_corre_despues_del_13_y_de_los_roles():
    """El 14 mueve cuentas a `graduate`: sin el 01 (crea el rol) y el 03 (le da los
    permisos) aborta, y va justo despues del 13 para que el orden del delta siga
    siendo el de su numeracion."""
    catorce = SEED_FILES.index("survey_2026_09/14_graduate_role_backfill.sql")

    assert catorce == SEED_FILES.index("survey_2026_09/13_seed_cotejo_reqs_all_cohorts.sql") + 1
    assert catorce > SEED_FILES.index("01_insert_roles.sql")
    assert catorce > SEED_FILES.index("03_insert_role_permissions.sql")


@requires_dml
def test_el_backfill_de_graduate_no_toca_permisos_de_rol():
    """`load-survey-2026-09` existe para NO correr el 03 en produccion, y el 14 viaja
    en ese comando: no puede conceder ni revocar permisos de rol. Solo mueve
    asignaciones de usuario y el alias legado `core_users.role_id`."""
    import re

    cuerpo = (DML_TITULATEC / _DML_SURVEY_2026_09_DIR
              / "14_graduate_role_backfill.sql").read_text(encoding="utf-8")
    sin_comentarios = re.sub(r"--[^\n]*", "", cuerpo)

    assert not re.search(r"(INSERT\s+INTO|DELETE\s+FROM|UPDATE)\s+core_role_permissions",
                         sin_comentarios, re.IGNORECASE)
    for pieza in ("titulatec_processes", "'graduate'", "'student'", "'agendatec'",
                  "RAISE NOTICE"):
        assert pieza in sin_comentarios, pieza


@requires_dml
def test_corre_todos_los_archivos_del_delta_y_ninguno_mas():
    with patch("itcj2.cli.core.execute_sql_file", return_value=True) as ejecutar, \
         patch("itcj2.cli.titulatec._verify_survey_2026_09", return_value=[]):
        res = CliRunner().invoke(load_survey_2026_09_command, [])

    assert res.exit_code == 0, res.output
    corridos = [str(c.args[0]) for c in ejecutar.call_args_list]
    assert len(corridos) == len(_DML_SURVEY_2026_09_FILES), corridos
    for nombre in _DML_SURVEY_2026_09_FILES:
        assert any(r.endswith(nombre) for r in corridos), f"no corrio {nombre}"
    # NUNCA el DML base: el 03 revocaria permisos concedidos a mano.
    assert not any("03_insert_role_permissions" in r for r in corridos), corridos


@requires_dml
def test_aborta_si_la_verificacion_reporta_un_permiso_sin_aterrizar():
    with patch("itcj2.cli.core.execute_sql_file", return_value=True), \
         patch("itcj2.cli.titulatec._verify_survey_2026_09",
               return_value=["sin grant a la jefatura: titulatec.survey.api.export"]):
        res = CliRunner().invoke(load_survey_2026_09_command, [])

    assert res.exit_code != 0, "un delta a medias NO puede salir 0"
    assert "titulatec.survey.api.export" in res.output
