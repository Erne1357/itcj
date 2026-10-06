"""Contrato del comando `titulatec init-email-tasks` (Tarea 9, spec
2026-09-28-titulatec-correos-notificaciones §6 C5).

Por que existe
--------------
Celery Beat corre con `itcj2.tasks.scheduler:DatabaseScheduler`, que SOLO lee
`core_periodic_tasks`: sin las filas de `titulatec.email_dispatch` (cada 5
minutos) y `titulatec.email_reminders` (diario 9:00) esas tareas nunca se
programan, aunque el worker las tenga registradas (`itcj2/tasks/
titulatec_tasks.py`). El DML que las da de alta vive en
`database/DML/titulatec/mail_2026_09/17_insert_email_tasks.sql` (gitignored,
calcado de `sii_2026_09/16_insert_sii_sweep_task.sql`) y entra a `SEED_FILES`
(antes del 15, que sigue último) para que una app nueva las traiga; pero en
producción `init-titulatec` completo nunca se re-ejecuta, así que este
comando corre SOLO ese archivo.

Mismo patrón que `tests/fastapi/titulatec/test_cli_survey_delta.py`:
`database/` está gitignored y el checkout de CI no lo trae, así que las
pruebas que tocan el archivo en disco se saltan ahí (`requires_dml`); las que
solo verifican las constantes de Python (`SEED_FILES`, `_DML_MAIL_2026_09_*`)
o el comando con `_run_sql_files` parchado NO necesitan el directorio y
corren siempre.
"""
import re
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from itcj2.cli.titulatec import (
    DML_TITULATEC,
    SEED_FILES,
    _DML_MAIL_2026_09_DIR,
    _DML_MAIL_2026_09_FILES,
    init_email_tasks_command,
)
from tests.fastapi.titulatec._dml_texts import (
    periodica_de_recordatorios_del_17,
    unir_literales,
)

_MAIL_SQL_NAME = "17_insert_email_tasks.sql"

requires_dml = pytest.mark.skipif(
    not (DML_TITULATEC / _DML_MAIL_2026_09_DIR).is_dir(),
    reason=(
        "database/DML/titulatec/mail_2026_09/ no esta en el checkout "
        "(gitignored a proposito). Esta prueba necesita el archivo en disco."
    ),
)


def test_seed_files_incluye_el_delta_antes_del_15():
    """Sin esto, una base NUEVA (`init-titulatec`/`core seed-reference-data`)
    nace sin las periodicas de correo: el scheduler jamas las programa."""
    nombre = f"{_DML_MAIL_2026_09_DIR}/{_MAIL_SQL_NAME}"

    assert nombre in SEED_FILES, f"{nombre} no esta en SEED_FILES"
    assert SEED_FILES.index(nombre) < SEED_FILES.index("15_grant_admin_all_perms.sql"), (
        "el delta de correo debe ir ANTES del 15 (que concede permisos "
        "dinamicamente y debe seguir siendo el ultimo)")
    assert SEED_FILES[-1] == "15_grant_admin_all_perms.sql"


def test_dry_run_lista_sin_ejecutar():
    """`--dry-run` no debe requerir `database/` en disco: solo lista lo que
    correria, sin tocar `_run_sql_files` (que sí exige el archivo)."""
    with patch("itcj2.cli.titulatec._run_sql_files") as ejecutar:
        res = CliRunner().invoke(init_email_tasks_command, ["--dry-run"])

    assert res.exit_code == 0, res.output
    ejecutar.assert_not_called()
    assert "[dry-run]" in res.output
    assert _MAIL_SQL_NAME in res.output


def test_corre_solo_el_archivo_de_correo_via_run_sql_files():
    """Sin `--dry-run`: llama `_run_sql_files` con SOLO el delta de correo,
    nunca el resto de `SEED_FILES` (ese es el trabajo de `init-titulatec`)."""
    with patch("itcj2.cli.titulatec._run_sql_files") as ejecutar:
        res = CliRunner().invoke(init_email_tasks_command, [])

    assert res.exit_code == 0, res.output
    ejecutar.assert_called_once_with(
        [f"{_DML_MAIL_2026_09_DIR}/{nombre}" for nombre in _DML_MAIL_2026_09_FILES]
    )
    assert "03_insert_role_permissions" not in str(ejecutar.call_args)


@requires_dml
def test_todo_sql_del_directorio_esta_en_la_lista():
    """Membresia disco <-> lista: un `.sql` que se cae de
    `_DML_MAIL_2026_09_FILES` no lo corre nadie y nada se pone rojo (mismo
    riesgo que le paso al 13 de `survey_2026_09/`, ver
    `test_cli_survey_delta.py::test_todo_sql_del_delta_esta_en_la_lista_del_comando`)."""
    en_disco = sorted(p.name for p in (DML_TITULATEC / _DML_MAIL_2026_09_DIR).glob("*.sql"))

    assert en_disco == sorted(_DML_MAIL_2026_09_FILES), (
        "el directorio mail_2026_09/ y la lista del comando divergen: "
        f"en disco {en_disco}, en la lista {sorted(_DML_MAIL_2026_09_FILES)}.")
    assert _MAIL_SQL_NAME in en_disco


@requires_dml
def test_el_despacho_corre_cada_5_minutos_y_se_describe_igual_que_en_el_worker():
    """Ruling 18 (spec D4/C5): el despachador corre cada 5 minutos, no cada
    minuto -- el scheduler del core crea un `core_task_runs` por ejecución y
    no hay retención. El DML lo siembra con `*/5 * * * *`, y la descripción de
    cada tarea en `core_task_definitions` es copia LITERAL de la de
    `TASK_DEFINITIONS` (itcj2/tasks/titulatec_tasks.py): una que diga «cada
    minuto» en un lado y «cada 5 minutos» en el otro miente en
    /config/system/tasks según quién la sembró."""
    from itcj2.tasks import titulatec_tasks

    sql = (DML_TITULATEC / _DML_MAIL_2026_09_DIR / _MAIL_SQL_NAME).read_text(encoding="utf-8")

    # El INSERT de `core_periodic_tasks`: task_name, cron y luego kwargs '{}'.
    cron = re.search(r"'titulatec\.email_dispatch',\s*'([^']*)',\s*'\{\}'", sql)
    assert cron, "no se encontró el cron de titulatec.email_dispatch en el DML"
    assert cron.group(1) == "*/5 * * * *"
    # Literales de SQL adyacentes (separados por un salto de línea) son UNA cadena.
    unido = unir_literales(sql)
    for definicion in titulatec_tasks.TASK_DEFINITIONS:
        if definicion["task_name"].startswith("titulatec.email_"):
            assert f"'{definicion['description']}'" in unido, (
                f"{definicion['task_name']}: la descripción del DML no es la de "
                "TASK_DEFINITIONS")
    assert "cada minuto" not in sql.lower()


@requires_dml
def test_la_periodica_de_recordatorios_menciona_el_pago_en_caja():
    """m33 (spec 2026-10-02 §3.7): la descripción de la fila de
    `core_periodic_tasks` de los recordatorios (una variante corta, no atada a
    `TASK_DEFINITIONS`) también dice que encola el del pago pendiente en Caja.
    Una base ya sembrada la recibe con el delta
    `biblioteca_2026_10/23_update_email_reminders_description.sql` (este
    archivo viejo no se re-corre en producción); que el 23 escriba este MISMO
    texto lo fija `test_cli_biblioteca_caja.py`, con el mismo lector
    (`_dml_texts.periodica_de_recordatorios_del_17`)."""
    assert "pago pendiente en Caja" in periodica_de_recordatorios_del_17()


@requires_dml
def test_los_nombres_del_dml_coinciden_con_las_tareas():
    """Los `task_name` que el SQL da de alta deben ser un subconjunto de los
    que el worker registra (`TASK_DEFINITIONS`, itcj2/tasks/titulatec_tasks.py):
    un nombre que el worker no conoce es una periodica muerta (Beat la manda,
    nadie la ejecuta), y un typo en el DML no lo detecta nada mas."""
    from itcj2.tasks import titulatec_tasks

    sql = (DML_TITULATEC / _DML_MAIL_2026_09_DIR / _MAIL_SQL_NAME).read_text(encoding="utf-8")
    nombres_en_sql = set(re.findall(r"'(titulatec\.[a-z_]+)'", sql))
    nombres_de_tareas = {d["task_name"] for d in titulatec_tasks.TASK_DEFINITIONS}

    assert nombres_en_sql, "no se encontro ningun task_name entre comillas en el SQL"
    assert nombres_en_sql <= nombres_de_tareas, (
        "el SQL da de alta un task_name que el worker no registra en "
        f"TASK_DEFINITIONS: {nombres_en_sql - nombres_de_tareas}")
    assert {"titulatec.email_dispatch", "titulatec.email_reminders"} <= nombres_en_sql, (
        f"el SQL debe dar de alta ambas tareas; encontrado: {nombres_en_sql}")
