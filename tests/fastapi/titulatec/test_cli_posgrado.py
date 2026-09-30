"""Contrato del DML `posgrado_2026_10/` + comando `titulatec init-posgrado`
(Tarea 7, spec 2026-09-30-titulatec-posgrado-design.md §4.2/§5/§6).

Por que existe
--------------
Las 4 carreras de posgrado (2 maestrias + la de industrial + el doctorado)
YA EXISTEN en produccion, tecleadas a mano con ortografia desconocida; en
dev/CI no existen. `18_classify_posgrado_programs.sql` las ubica por NOMBRE
NORMALIZADO (nunca por id ni "las ultimas 4", D2) y aborta SIN escribir ante
cualquier ambiguedad o carrera de posgrado a medias -- nunca duplica
(invariante 7). `19_insert_posgrado_doc_types.sql` da de alta los 4 tipos de
documento extra de fase 1 (`DocumentService.POSGRADO_EXTRA_DOCS`). Ambos
viven en su propia subcarpeta con comando propio (D10, patron de
`init-email-tasks`): produccion ya corrio `init-titulatec` y ese comando
nunca se re-ejecuta alli.

`init-posgrado` tambien re-sincroniza la fase 1 de los procesos de posgrado
que siguen en esa fase (§5, regla R-G): `DocumentService.sync_initial_phase`
solo corre como efecto secundario de subir/borrar un documento, asi que
clasificar la carrera no mueve por si sola a un proceso que ya estaba
`in_review` esperando SOLO 3. Nunca toca un proceso cuya fase 1 ya cerro
(invariante 8, D9): ni el DML ni el resync regresan un `approved`.

Mismo patron que `test_cli_mail_tasks.py`/`test_cli_survey_delta.py`:
`database/` esta gitignored y el checkout de CI no lo trae, asi que las
pruebas que tocan el archivo en disco (o ejecutan el SQL de verdad) se saltan
ahi (`requires_dml`); las que solo verifican constantes de Python o el
comando con `_run_sql_files`/`_verify_posgrado`/`_resync_posgrado_phase1`
parchados NO necesitan el directorio y corren siempre.
"""
import re

import pytest
from click.testing import CliRunner
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from unittest.mock import patch

from itcj2.apps.titulatec.services.document_service import DocumentService
from itcj2.cli.titulatec import (
    DML_TITULATEC,
    SEED_FILES,
    _DML_POSGRADO_2026_10_DIR,
    _DML_POSGRADO_2026_10_FILES,
    _resync_posgrado_phase1,
    _verify_posgrado,
    init_posgrado_command,
)

requires_dml = pytest.mark.skipif(
    not (DML_TITULATEC / _DML_POSGRADO_2026_10_DIR).is_dir(),
    reason=(
        "database/DML/titulatec/posgrado_2026_10/ no esta en el checkout "
        "(gitignored a proposito). Esta prueba necesita el archivo en disco."
    ),
)

# Los 4 patrones EXACTOS del 18 (spec §4.2): (nivel esperado, patron1, patron2).
_PATRONES = (
    ("maestria", "MAESTRIA%", "%NEGOCIOS%"),
    ("maestria", "MAESTRIA%", "%ADMINISTRATIVA%"),
    ("maestria", "MAESTRIA%", "%INDUSTRIAL%"),
    ("doctorado", "DOCTORADO%", None),
)
_NORM = "upper(translate(name, 'áéíóúüÁÉÍÓÚÜ', 'aeiouuAEIOUU'))"


def _contar_patron(db_session, patron1, patron2):
    condicion = f"{_NORM} LIKE :p1"
    params = {"p1": patron1}
    if patron2:
        condicion += f" AND {_NORM} LIKE :p2"
        params["p2"] = patron2
    return db_session.execute(
        text(f"SELECT id, level, name FROM core_programs WHERE {condicion}"), params
    ).fetchall()


def _como_execute_sql_file(sql: str) -> str:
    """Reproduce el preprocesamiento de `execute_sql_file`
    (`itcj2/cli/core.py:60-69`): strip de comentarios `--` LINEA A LINEA, sin
    entender strings SQL -- un `--` dentro de un literal (p. ej. en un mensaje
    de `RAISE`) se trunca igual que en producción.

    Las pruebas de este archivo NO deben pasar el `.sql` crudo a `text()`:
    eso NO atrapa el bug real que sí atrapó correr `init-posgrado` de verdad
    en dev (Tarea 7, 2026-09-30) -- un `--` embebido en un `RAISE NOTICE` que
    rompía SOLO al pasar por `execute_sql_file`, nunca al ejecutar el texto
    crudo del archivo directamente. Mismo motivo por el que el hint del
    controlador pide "ejecutar la SQL como lo hace el comando".
    """
    cleaned_lines = []
    for line in sql.split("\n"):
        if "--" in line:
            comment_pos = line.find("--")
            line = line[:comment_pos].rstrip()
        if line.strip():
            cleaned_lines.append(line)
    return "\n".join(cleaned_lines)


# ---------------------------------------------------------------------------
# Constantes de Python (sin BD, corren siempre)
# ---------------------------------------------------------------------------
def test_seed_files_incluye_los_dos_archivos_en_orden_antes_del_15():
    """Sin esto, una base NUEVA (`init-titulatec`/`core seed-reference-data`)
    nace sin las 4 carreras de posgrado clasificadas ni sus 4 tipos de doc."""
    nombres = [f"{_DML_POSGRADO_2026_10_DIR}/{n}" for n in _DML_POSGRADO_2026_10_FILES]
    for nombre in nombres:
        assert nombre in SEED_FILES, f"{nombre} no esta en SEED_FILES"

    idx_18 = SEED_FILES.index(nombres[0])
    idx_19 = SEED_FILES.index(nombres[1])
    idx_15 = SEED_FILES.index("15_grant_admin_all_perms.sql")
    assert idx_18 < idx_19 < idx_15, (
        "el delta de posgrado debe ir ANTES del 15 (que concede permisos "
        "dinamicamente y debe seguir siendo el ultimo), en orden 18 -> 19")
    assert SEED_FILES[-1] == "15_grant_admin_all_perms.sql"


def test_dry_run_lista_archivos_y_procesos_sin_ejecutar():
    """`--dry-run` no debe requerir `database/` en disco: solo lista lo que
    correria, sin tocar `_run_sql_files` (que si exige el archivo)."""
    with patch("itcj2.cli.titulatec._run_sql_files") as ejecutar:
        res = CliRunner().invoke(init_posgrado_command, ["--dry-run"])

    assert res.exit_code == 0, res.output
    ejecutar.assert_not_called()
    assert "[dry-run]" in res.output
    for nombre in _DML_POSGRADO_2026_10_FILES:
        assert nombre in res.output
    assert "no se ejecut" in res.output.lower()


def test_real_run_ejecuta_solo_los_dos_archivos_del_delta():
    """Sin `--dry-run`: `_run_sql_files` recibe EXACTAMENTE las 2 rutas del
    delta de posgrado, nunca el resto de `SEED_FILES`."""
    rutas_esperadas = [f"{_DML_POSGRADO_2026_10_DIR}/{n}" for n in _DML_POSGRADO_2026_10_FILES]

    with patch("itcj2.cli.titulatec._run_sql_files") as ejecutar, \
         patch("itcj2.cli.titulatec._verify_posgrado", return_value=[]), \
         patch("itcj2.cli.titulatec._resync_posgrado_phase1", return_value=[]) as resync:
        res = CliRunner().invoke(init_posgrado_command, [])

    assert res.exit_code == 0, res.output
    ejecutar.assert_called_once_with(rutas_esperadas)
    resync.assert_called_once_with(dry_run=False)


def test_real_run_aborta_si_la_verificacion_reporta_problemas():
    """Un delta a medias (`_verify_posgrado` no vacio) NO puede salir 0, y no
    debe re-sincronizar nada con una base que no aterrizo bien."""
    with patch("itcj2.cli.titulatec._run_sql_files"), \
         patch("itcj2.cli.titulatec._verify_posgrado",
               return_value=["carrera de posgrado (DOCTORADO%): se esperaba 1, hay 0"]), \
         patch("itcj2.cli.titulatec._resync_posgrado_phase1") as resync:
        res = CliRunner().invoke(init_posgrado_command, [])

    assert res.exit_code != 0, "un delta a medias NO puede salir 0"
    assert "DOCTORADO%" in res.output
    resync.assert_not_called()


# ---------------------------------------------------------------------------
# Disco: membresia directorio <-> lista, y codigos del 19 == el contrato de
# DocumentService (requieren `database/DML/titulatec/posgrado_2026_10/` real)
# ---------------------------------------------------------------------------
@requires_dml
def test_directorio_lista_exactamente_los_dos_archivos():
    en_disco = sorted(p.name for p in (DML_TITULATEC / _DML_POSGRADO_2026_10_DIR).glob("*.sql"))

    assert en_disco == sorted(_DML_POSGRADO_2026_10_FILES), (
        "el directorio posgrado_2026_10/ y la lista del comando divergen: "
        f"en disco {en_disco}, en la lista {sorted(_DML_POSGRADO_2026_10_FILES)}.")


@requires_dml
def test_los_codigos_del_19_son_los_de_document_service():
    """El 19 no puede inventar codigos propios: deben ser exactamente
    `DocumentService.POSGRADO_EXTRA_DOCS` -- ese contrato es el que consume
    `sync_initial_phase`/`initial_docs_all_approved` (Tareas 2/3)."""
    sql = (DML_TITULATEC / _DML_POSGRADO_2026_10_DIR
           / "19_insert_posgrado_doc_types.sql").read_text(encoding="utf-8")

    codigos = set(re.findall(r"\(\s*'([a-z_]+)',\s*'[^']+',\s*1,\s*'pdf',", sql))

    assert codigos == set(DocumentService.POSGRADO_EXTRA_DOCS), (
        f"codigos del 19: {codigos}, se esperaban {set(DocumentService.POSGRADO_EXTRA_DOCS)}")
    assert len(codigos) == 4


# ---------------------------------------------------------------------------
# SQL de verdad (Postgres real, dentro de `begin_nested()` -- ver hint del
# controlador: `:=`/`::` en PL/pgSQL no chocan con los bind params de
# `text()` porque SQLAlchemy exige un caracter de palabra justo despues del
# `:`; el mismo patron ya corre en produccion via `execute_sql_file`).
# ---------------------------------------------------------------------------
@requires_dml
def test_el_18_clasifica_cada_patron_exactamente_una_vez_e_idempotente(db_session):
    """Valido en dev CON o SIN posgrados ya sembrados (una corrida real previa
    de `init-posgrado`, o la base limpia que describe el spec): cada patron
    debe casar EXACTAMENTE 1 carrera con su nivel, y correrlo una segunda vez
    no debe cambiar el conteo de `core_programs` (no duplica)."""
    sql = _como_execute_sql_file(
        (DML_TITULATEC / _DML_POSGRADO_2026_10_DIR
         / "18_classify_posgrado_programs.sql").read_text(encoding="utf-8")
    )

    with db_session.begin_nested():
        db_session.execute(text(sql))
    conteo_1 = db_session.execute(text("SELECT COUNT(*) FROM core_programs")).scalar()

    for nivel, p1, p2 in _PATRONES:
        filas = _contar_patron(db_session, p1, p2)
        assert len(filas) == 1, f"{p1} {p2}: se esperaba 1 carrera, hay {len(filas)} ({filas})"
        assert filas[0][1] == nivel, f"{filas[0][2]} (id {filas[0][0]}): nivel {filas[0][1]!r}, se esperaba {nivel!r}"

    # Segunda corrida: idempotente, no duplica (cae en el escenario "ya
    # existen" y solo confirma el nivel).
    with db_session.begin_nested():
        db_session.execute(text(sql))
    conteo_2 = db_session.execute(text("SELECT COUNT(*) FROM core_programs")).scalar()
    assert conteo_2 == conteo_1, "correr el 18 dos veces no debe cambiar el conteo de core_programs"

    for nivel, p1, p2 in _PATRONES:
        filas = _contar_patron(db_session, p1, p2)
        assert len(filas) == 1
        assert filas[0][1] == nivel


@requires_dml
def test_el_18_aborta_sin_escribir_ante_un_casi_duplicado(db_session, make_program):
    """Review Focus 5 del plan: un casi-duplicado (con y sin acentos/mayusculas
    apuntando al mismo programa) debe abortar con `DBAPIError` y no cambiar
    nada -- ni el conteo ni el nivel de ninguna de las dos filas."""
    make_program("MAESTRIA EN INGENIERIA INDUSTRIAL", level="licenciatura")
    make_program("Maestría en Ingeniería Industrial", level="licenciatura")

    antes = db_session.execute(text("SELECT COUNT(*) FROM core_programs")).scalar()

    sql = _como_execute_sql_file(
        (DML_TITULATEC / _DML_POSGRADO_2026_10_DIR
         / "18_classify_posgrado_programs.sql").read_text(encoding="utf-8")
    )

    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(text(sql))

    despues = db_session.execute(text("SELECT COUNT(*) FROM core_programs")).scalar()
    assert despues == antes, "el DML no debe escribir nada si aborta"

    niveles = dict(db_session.execute(text(
        "SELECT name, level FROM core_programs WHERE name IN "
        "('MAESTRIA EN INGENIERIA INDUSTRIAL', 'Maestría en Ingeniería Industrial')"
    )).fetchall())
    assert niveles == {
        "MAESTRIA EN INGENIERIA INDUSTRIAL": "licenciatura",
        "Maestría en Ingeniería Industrial": "licenciatura",
    }, "ninguna de las dos filas casi-duplicadas debe cambiar de nivel"


# ---------------------------------------------------------------------------
# `_resync_posgrado_phase1` (§5, regla R-G / invariante 8)
# ---------------------------------------------------------------------------
def test_resync_re_sincroniza_solo_posgrado_en_fase_1_y_respeta_dry_run(
    db_session, patched_session_local, make_program, make_user, make_process,
    make_document, seed_phase_defs,
):
    from itcj2.apps.titulatec.models import ProcessPhase

    seed_phase_defs()

    programa_pg = make_program("Maestría en Ingeniería Industrial", level="maestria")
    programa_lic = make_program("Ingeniería en Sistemas Computacionales")

    # Posgrado en fase 1 `in_review` con SOLO los 3 base (asi quedo, bajo la
    # regla vieja, antes de este despliegue).
    proceso_pg = make_process(make_user(), program=programa_pg, current_phase=1, status="active")
    # Licenciatura en fase 1 `in_progress` con sus 3 (completos para SU set,
    # que no cambio): si el resync la tocara por error, pasaria a `in_review`.
    proceso_lic = make_process(make_user(), program=programa_lic, current_phase=1, status="active")
    # Posgrado que YA PASO la fase 1 (aprobada) antes del despliegue, sin
    # ninguno de los 4 extras (D9/R-G): no debe tocarse ni aparecer.
    proceso_pg_cerrado = make_process(make_user(), program=programa_pg, current_phase=2, status="active")

    for proceso in (proceso_pg, proceso_lic):
        for code in ("birth_certificate", "high_school_cert", "curp"):
            make_document(proceso, type_code=code)

    fase1_pg = db_session.query(ProcessPhase).filter_by(
        process_id=proceso_pg.id, phase_number=1).first()
    fase1_pg.status = "in_review"

    # Checkpoint: bajo `join_transaction_mode="create_savepoint"` (conftest.py
    # de esta suite), `session.rollback()` -- el dry-run de abajo -- vuelve al
    # ULTIMO commit, no al inicio de la sesion. Sin este commit, el rollback
    # se llevaria por delante las fixtures de arriba.
    db_session.commit()

    # --- dry-run: calcula pero NO escribe ---
    resultados = _resync_posgrado_phase1(dry_run=True)
    assert resultados == [(proceso_pg.id, proceso_pg.folio, "in_progress")]

    db_session.expire_all()
    fase1_pg = db_session.query(ProcessPhase).filter_by(
        process_id=proceso_pg.id, phase_number=1).first()
    fase1_lic = db_session.query(ProcessPhase).filter_by(
        process_id=proceso_lic.id, phase_number=1).first()
    fase1_pg_cerrado = db_session.query(ProcessPhase).filter_by(
        process_id=proceso_pg_cerrado.id, phase_number=1).first()
    assert fase1_pg.status == "in_review", "el dry-run no debe escribir"
    assert fase1_lic.status == "in_progress", "licenciatura nunca se toca"
    assert fase1_pg_cerrado.status == "approved", "una fase 1 ya cerrada no se toca (R-G/D9)"

    # --- real: escribe SOLO el proceso de posgrado en fase 1 abierta ---
    resultados = _resync_posgrado_phase1(dry_run=False)
    assert resultados == [(proceso_pg.id, proceso_pg.folio, "in_progress")]

    db_session.expire_all()
    fase1_pg = db_session.query(ProcessPhase).filter_by(
        process_id=proceso_pg.id, phase_number=1).first()
    fase1_lic = db_session.query(ProcessPhase).filter_by(
        process_id=proceso_lic.id, phase_number=1).first()
    fase1_pg_cerrado = db_session.query(ProcessPhase).filter_by(
        process_id=proceso_pg_cerrado.id, phase_number=1).first()
    assert fase1_pg.status == "in_progress"
    assert fase1_lic.status == "in_progress", "licenciatura sigue intacta tras el resync real"
    assert fase1_pg_cerrado.status == "approved", "sigue sin tocarse tras el resync real"
