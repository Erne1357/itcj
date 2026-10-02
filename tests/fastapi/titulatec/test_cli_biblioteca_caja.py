"""Contrato del DML `biblioteca_2026_10/` + comandos `titulatec init-biblioteca-caja`
y `titulatec activar-biblioteca-caja` (Tarea 2, spec
2026-10-01-titulatec-biblioteca-caja-design.md §4.6/§6; despliegue en dos pasos
desde la Ruling R19 de la revisión final, promoción D17 de la Ruling R20).

Por que existe
--------------
Biblioteca revisa en FIFO el no-adeudo de todo inscrito y Caja cobra adeudo +
donacion voluntaria de libro; el pago libera el requisito de cotejo
`library_clearance`. Puestos nuevos (`library_clearance_info_center`,
`cashier_financial_resources`), roles nuevos (`titulatec_library`,
`titulatec_cashier`) y 10 permisos nuevos (88 -> 98) viven en su propia
subcarpeta `biblioteca_2026_10/` -- NUNCA en el 01/02/03/05, cuyos DELETE del
03 se re-aplican en cada corrida de `init-titulatec` y revocarian cualquier
permiso concedido ahi.

Despliegue en DOS pasos (Ruling R19): `init-biblioteca-caja` corre SOLO el 20
y el 21 (puestos, roles, permisos: no enciende nada) más el 23 (m33 de
2026-10-02: la descripción de la tarea de recordatorios por correo, que ahora
menciona el pago pendiente en Caja) y `activar-biblioteca-
caja` -tras sus pre-chequeos de ocupantes y donación, que abortan sin
`--force`- corre el 22 (el candado), RE-BACKFILLEA `titulatec_library_
clearances` con el MISMO predicado que el backfill de la migracion
`tt20261001a` (`migrations/versions/tt20261001a_titulatec_biblioteca_caja.py`,
BACKFILL_SQL; Review Focus #5 del plan) y PROMUEVE a `cleared/legacy` las
`pending` marcadas a mano después de la migración (Ruling R20, D17).

Mismo patron que `test_cli_posgrado.py`/`test_cli_survey_delta.py`:
`database/` esta gitignored y el checkout de CI no lo trae, asi que las
pruebas que tocan el archivo en disco (o invocan el comando de verdad) se
saltan ahi (`requires_dml`); las que solo verifican constantes de Python
corren siempre.

Hermeticidad (mismo criterio que `test_cli_posgrado.py`): las pruebas a
nivel comando (`CliRunner`) parchan `execute_sql_file`, los `_verify_*`, los
pre-chequeos, los conteos, el re-backfill y la promoción -- ninguna toca la BD
de dev de verdad. `_library_clearance_rebackfill`, `_library_clearance_promote`
y `_precheck_activar_biblioteca` en si mismas SI se prueban contra Postgres
real, pero DENTRO del savepoint de `db_session` (`patched_session_local`
intercepta su `SessionLocal()` interno) -- nunca contra el engine de
produccion sin aislar.
"""
from datetime import timedelta
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from itcj2.cli.titulatec import (
    DML_TITULATEC,
    SEED_FILES,
    _DML_BIBLIOTECA_2026_10_ACTIVAR_FILES,
    _DML_BIBLIOTECA_2026_10_DIR,
    _DML_BIBLIOTECA_2026_10_FILES,
    _PERM_CERTIFICATE_PAGE_LIST,
    _PERM_SURVEY_PRINT_CERTIFICATES,
    _PERMISOS_BIBLIOTECA_CAJA_2026_10,
    _PERMISOS_ROL_CASHIER,
    _PERMISOS_ROL_LIBRARY,
    _PUESTO_CASHIER,
    _PUESTO_LIBRARY,
    _PUESTOS_BIBLIOTECA_CAJA,
    _ROL_ADMIN,
    _ROL_CASHIER,
    _ROL_GTV,
    _ROL_JEFATURA_ESCOLARES,
    _ROL_LIBRARY,
    _ROL_OPERATIVO_ESCOLARES,
    _library_clearance_promote,
    _library_clearance_rebackfill,
    _precheck_activar_biblioteca,
    _verify_biblioteca_caja,
    activar_biblioteca_caja_command,
    init_biblioteca_caja_command,
)
from itcj2.core.utils.timezone import db_now

_TODOS_LOS_DEL_DELTA = _DML_BIBLIOTECA_2026_10_FILES + _DML_BIBLIOTECA_2026_10_ACTIVAR_FILES

_MOD = "itcj2.cli.titulatec"
_PRE_OK = {"ocupantes": {_PUESTO_LIBRARY: 1, _PUESTO_CASHIER: 2},
           "sin_donacion": [], "problemas": []}
_PRE_MAL = {"ocupantes": {_PUESTO_LIBRARY: 0, _PUESTO_CASHIER: None},
            "sin_donacion": [{"cohort_id": 7, "name": "Convocatoria X", "pending": 3}],
            "problemas": ["puesto library_clearance_info_center sin ocupante vigente",
                          "convocatoria «Convocatoria X» (id 7) sin donación"]}

requires_dml = pytest.mark.skipif(
    not (DML_TITULATEC / _DML_BIBLIOTECA_2026_10_DIR).is_dir(),
    reason=(
        "database/DML/titulatec/biblioteca_2026_10/ no esta en el checkout "
        "(gitignored a proposito: trae PII real y nunca llega a CI). Esta "
        "prueba invoca el comando de verdad, que exige el directorio en "
        "disco antes de que los mocks entren en juego."
    ),
)


# ---------------------------------------------------------------------------
# Constantes de Python (sin BD, sin disco): corren siempre.
# ---------------------------------------------------------------------------
def test_los_diez_codigos_del_delta_son_los_del_contrato():
    assert set(_PERMISOS_BIBLIOTECA_CAJA_2026_10) == {
        "titulatec.library_clearance.page.list",
        "titulatec.library_clearance.api.register",
        "titulatec.library_clearance.api.prior",
        "titulatec.library_clearance.api.revert",
        "titulatec.library_clearance.api.print_certificates",
        "titulatec.library_payment.page.list",
        "titulatec.library_payment.api.register",
        "titulatec.library_payment.api.revert",
        "titulatec.survey_review.api.print_certificates",
        "titulatec.certificate.page.list",
    }
    assert len(_PERMISOS_BIBLIOTECA_CAJA_2026_10) == 10


def test_el_reparto_de_los_roles_nuevos_es_exacto():
    """spec §4.6: titulatec_library = los 5 library_clearance.* MAS
    certificate.page.list (6); titulatec_cashier = SOLO los 3 library_payment.*."""
    assert set(_PERMISOS_ROL_LIBRARY) == {
        "titulatec.library_clearance.page.list",
        "titulatec.library_clearance.api.register",
        "titulatec.library_clearance.api.prior",
        "titulatec.library_clearance.api.revert",
        "titulatec.library_clearance.api.print_certificates",
        "titulatec.certificate.page.list",
    }
    assert set(_PERMISOS_ROL_CASHIER) == {
        "titulatec.library_payment.page.list",
        "titulatec.library_payment.api.register",
        "titulatec.library_payment.api.revert",
    }
    # Los dos repartos son subconjuntos de los 10 del delta -- ninguno de los
    # dos roles nuevos deberia recibir un codigo que el delta no declara.
    assert set(_PERMISOS_ROL_LIBRARY) <= set(_PERMISOS_BIBLIOTECA_CAJA_2026_10)
    assert set(_PERMISOS_ROL_CASHIER) <= set(_PERMISOS_BIBLIOTECA_CAJA_2026_10)


def test_las_dos_listas_reparten_el_delta_sin_solaparse():
    """Ruling R19: `init-biblioteca-caja` = 20 + 21 (no enciende nada) + 23
    (m33, spec 2026-10-02 §6: la descripción de los recordatorios por correo,
    que ahora mencionan el pago pendiente en Caja); `activar-biblioteca-caja`
    = SOLO el 22 (el candado). Ninguno corre lo del otro."""
    assert _DML_BIBLIOTECA_2026_10_FILES == [
        "20_insert_library_cashier_positions.sql",
        "21_insert_library_cashier_roles_perms.sql",
        "23_update_email_reminders_description.sql",
    ]
    assert _DML_BIBLIOTECA_2026_10_ACTIVAR_FILES == ["22_library_requirement_auto.sql"]
    assert not set(_DML_BIBLIOTECA_2026_10_FILES) & set(_DML_BIBLIOTECA_2026_10_ACTIVAR_FILES)


def test_el_delta_esta_en_seed_files_con_su_prefijo_de_subcarpeta():
    """Sin esto, una base NUEVA (`core seed-reference-data`) nace sin el
    delta: `SEED_FILES` conserva el 20, el 21 Y el 22 (desde cero, encender
    de inmediato está bien: no hay procesos que proteger) y el 23 (ahí no
    cambia nada: el 17 ya siembra el texto nuevo; lo deja al día si el 17 en
    disco fuera una copia vieja)."""
    for nombre in _TODOS_LOS_DEL_DELTA:
        assert f"{_DML_BIBLIOTECA_2026_10_DIR}/{nombre}" in SEED_FILES, (
            f"{nombre} no esta en SEED_FILES con el prefijo {_DML_BIBLIOTECA_2026_10_DIR}/")


def test_el_delta_va_antes_del_grant_de_admin():
    """15_grant_admin_all_perms.sql concede dinamicamente TODOS los permisos
    de titulatec existentes al correr: si este delta corriera despues, el
    rol admin se quedaria sin los 10 codigos nuevos hasta la siguiente
    corrida completa de `init-titulatec` -- y en produccion esa corrida
    nunca pasa. Sin BD: solo verifica el orden de la lista en memoria."""
    quince = SEED_FILES.index("15_grant_admin_all_perms.sql")
    for nombre in _TODOS_LOS_DEL_DELTA:
        idx = SEED_FILES.index(f"{_DML_BIBLIOTECA_2026_10_DIR}/{nombre}")
        assert idx < quince, f"{nombre} debe ir ANTES de 15_grant_admin_all_perms.sql"


def test_los_puestos_a_ocupar_son_los_dos_nuevos():
    assert set(_PUESTOS_BIBLIOTECA_CAJA) == {_PUESTO_LIBRARY, _PUESTO_CASHIER}


# ---------------------------------------------------------------------------
# Disco: requieren database/DML/titulatec/biblioteca_2026_10/ en el checkout.
# ---------------------------------------------------------------------------
@requires_dml
def test_todo_sql_del_delta_esta_en_una_lista_de_comando():
    """Membresia: ningun .sql del directorio puede quedarse sin comando
    (mismo riesgo que perdio el 13 de survey_2026_09, ver
    test_cli_survey_delta.py). Desde la Ruling R19 son DOS listas -la de
    `init-biblioteca-caja` y la de `activar-biblioteca-caja`- y entre las dos
    cubren el directorio entero."""
    en_disco = sorted(p.name for p in
                      (DML_TITULATEC / _DML_BIBLIOTECA_2026_10_DIR).glob("*.sql"))

    assert en_disco == sorted(_TODOS_LOS_DEL_DELTA), (
        "el directorio del delta y las listas de los comandos divergen: "
        f"en disco {en_disco}, en las listas {sorted(_TODOS_LOS_DEL_DELTA)}. "
        "Un .sql que no este en ninguna lista NO lo corre ningun comando, y nada "
        "mas se pone rojo.")

    for nombre in ("20_insert_library_cashier_positions.sql",
                   "21_insert_library_cashier_roles_perms.sql",
                   "22_library_requirement_auto.sql",
                   "23_update_email_reminders_description.sql"):
        assert nombre in en_disco, f"falta {nombre} en el directorio del delta"


def _periodica_de_recordatorios_del_17() -> str:
    """La descripción de 'TitulaTec: recordatorios por correo' que siembra el
    DML 17 (`mail_2026_09/`) en `core_periodic_tasks`, con sus literales de
    SQL adyacentes unidos."""
    import re

    sql = (DML_TITULATEC / "mail_2026_09" / "17_insert_email_tasks.sql").read_text(
        encoding="utf-8")
    unido = re.sub(r"'\s*\n\s*'", "", sql)
    fila = re.search(r"'TitulaTec: recordatorios por correo',\s*'titulatec\.email_reminders',"
                     r"\s*'[^']*',\s*'\{\}',\s*TRUE,\s*'([^']*)'", unido)
    assert fila, "no se encontró la periódica de recordatorios en el DML 17"
    return fila.group(1)


@requires_dml
def test_el_23_deja_las_dos_descripciones_como_las_siembra_el_17():
    """m33 (spec 2026-10-02 §6): una base YA sembrada (producción: el 17 viejo
    nunca se re-corre) recibe con el 23 las MISMAS dos descripciones que una
    instalación desde cero recibe del 17: la de `core_task_definitions`, copia
    literal de `TASK_DEFINITIONS` (itcj2/tasks/titulatec_tasks.py), y la de la
    fila de `core_periodic_tasks`. Solo UPDATE (no da de alta la tarea ni
    borra nada) e idempotente (`IS DISTINCT FROM`: re-correrlo no toca
    `updated_at`)."""
    import re

    from itcj2.tasks import titulatec_tasks

    sql = (DML_TITULATEC / _DML_BIBLIOTECA_2026_10_DIR
           / "23_update_email_reminders_description.sql").read_text(encoding="utf-8")
    codigo = "\n".join(linea for linea in sql.splitlines()
                       if not linea.lstrip().startswith("--"))
    unido = re.sub(r"'\s*\n\s*'", "", codigo)
    definicion, = [d for d in titulatec_tasks.TASK_DEFINITIONS
                   if d["task_name"] == "titulatec.email_reminders"]

    assert f"'{definicion['description']}'" in unido, (
        "la descripción de core_task_definitions del 23 no es la de TASK_DEFINITIONS")
    assert f"'{_periodica_de_recordatorios_del_17()}'" in unido, (
        "la descripción de core_periodic_tasks del 23 no es la que siembra el 17")
    assert "pago pendiente en Caja" in definicion["description"]
    assert not re.search(r"\b(INSERT|DELETE|TRUNCATE|DROP)\b", codigo, re.IGNORECASE)
    assert "UPDATE core_task_definitions" in codigo
    assert "UPDATE core_periodic_tasks" in codigo
    assert codigo.count("IS DISTINCT FROM") == 2


# --- init-biblioteca-caja (paso 1: NO enciende nada) -----------------------
@requires_dml
def test_init_dry_run_no_ejecuta_sql_ni_verifica():
    with patch("itcj2.cli.core.execute_sql_file") as ejecutar, \
         patch(f"{_MOD}._verify_biblioteca_caja") as verificar, \
         patch(f"{_MOD}._library_clearance_rebackfill") as rebackfill, \
         patch(f"{_MOD}._library_clearance_promote") as promover:
        res = CliRunner().invoke(init_biblioteca_caja_command, ["--dry-run"])

    assert res.exit_code == 0, res.output
    ejecutar.assert_not_called()
    verificar.assert_not_called()
    rebackfill.assert_not_called()
    promover.assert_not_called()
    assert "20_insert_library_cashier_positions.sql" in res.output
    assert "23_update_email_reminders_description.sql" in res.output
    assert "22_library_requirement_auto.sql" not in res.output
    assert "Dry-run: no se ejecutó nada." in res.output


@requires_dml
def test_init_corre_el_20_21_y_23_y_no_enciende_nada():
    with patch("itcj2.cli.core.execute_sql_file", return_value=True) as ejecutar, \
         patch(f"{_MOD}._verify_biblioteca_caja", return_value=[]) as verificar, \
         patch(f"{_MOD}._verify_candado_biblioteca") as verificar_candado, \
         patch(f"{_MOD}._library_clearance_rebackfill") as rebackfill, \
         patch(f"{_MOD}._library_clearance_promote") as promover:
        res = CliRunner().invoke(init_biblioteca_caja_command, [])

    assert res.exit_code == 0, res.output
    corridos = [str(c.args[0]) for c in ejecutar.call_args_list]
    assert [r.rsplit("/", 1)[-1] for r in corridos] == _DML_BIBLIOTECA_2026_10_FILES, corridos
    # NUNCA el 22 (el candado), ni el DML base, ni otros deltas -- tampoco el
    # 17 viejo de `mail_2026_09/` (regla del proyecto: un DML viejo no se
    # re-corre en producción; su texto nuevo llega con el 23).
    assert not any("22_library_requirement_auto" in r or "01_insert_roles" in r
                   or "03_insert_role_permissions" in r or "survey_2026_09" in r
                   or "posgrado_2026_10" in r or "mail_2026_09" in r
                   for r in corridos), corridos
    verificar.assert_called_once_with()
    verificar_candado.assert_not_called()
    rebackfill.assert_not_called()
    promover.assert_not_called()
    assert "candado sigue APAGADO" in res.output
    assert "activar-biblioteca-caja" in res.output


@requires_dml
def test_init_aborta_si_la_verificacion_reporta_un_problema():
    with patch("itcj2.cli.core.execute_sql_file", return_value=True), \
         patch(f"{_MOD}._verify_biblioteca_caja",
               return_value=["permiso ausente: titulatec.library_payment.api.revert"]):
        res = CliRunner().invoke(init_biblioteca_caja_command, [])

    assert res.exit_code != 0, "un delta a medias NO puede salir 0"
    assert "titulatec.library_payment.api.revert" in res.output


# --- activar-biblioteca-caja (paso 2: el candado) --------------------------
def _activar(args, *, pre, verif=(), orden=None):
    """Corre `activar-biblioteca-caja` con TODO lo que toca la BD parchado.
    `orden` (lista) recibe el nombre de cada paso que de verdad escribe, en
    el orden en que corre."""
    orden = orden if orden is not None else []

    def _anota(nombre, valor=None):
        def _hace(*args, **kwargs):
            if kwargs.get("dry_run") is not True:
                orden.append(nombre)
            return valor
        return _hace

    mocks = {
        "ejecutar": patch("itcj2.cli.core.execute_sql_file",
                          side_effect=_anota("dml", True)),
        "pre": patch(f"{_MOD}._precheck_activar_biblioteca", return_value=pre),
        "off": patch(f"{_MOD}._library_requirements_off", return_value=(2, 5)),
        "rebackfill": patch(f"{_MOD}._library_clearance_rebackfill",
                            side_effect=_anota("rebackfill", 4)),
        "promover": patch(f"{_MOD}._library_clearance_promote",
                          side_effect=_anota("promover", 6)),
        "verificar": patch(f"{_MOD}._verify_candado_biblioteca",
                           side_effect=_anota("verificar", list(verif))),
    }
    activos = {k: m.start() for k, m in mocks.items()}
    try:
        res = CliRunner().invoke(activar_biblioteca_caja_command, args)
    finally:
        for m in mocks.values():
            m.stop()
    return res, activos, orden


@requires_dml
def test_activar_corre_el_22_rebackfill_promocion_y_verificacion_en_ese_orden():
    res, m, orden = _activar([], pre=_PRE_OK)

    assert res.exit_code == 0, res.output
    assert orden == ["dml", "rebackfill", "promover", "verificar"]
    corridos = [str(c.args[0]) for c in m["ejecutar"].call_args_list]
    assert [r.rsplit("/", 1)[-1] for r in corridos] == ["22_library_requirement_auto.sql"]
    m["rebackfill"].assert_called_once_with(dry_run=False)
    m["promover"].assert_called_once_with(dry_run=False)
    # Los conteos de cada paso.
    assert "2 fila(s) encendida(s) de 5" in res.output
    assert "Re-backfill de no adeudo: 4 fila(s)" in res.output
    assert "Promoción D17: 6 fila(s)" in res.output
    assert "ENCENDIDO" in res.output


@requires_dml
def test_activar_sin_force_aborta_si_fallan_los_prechequeos_sin_escribir():
    res, m, orden = _activar([], pre=_PRE_MAL)

    assert res.exit_code != 0, res.output
    assert orden == [], "no debe escribir NADA"
    m["ejecutar"].assert_not_called()
    m["rebackfill"].assert_not_called()
    m["promover"].assert_not_called()
    for problema in _PRE_MAL["problemas"]:
        assert problema in res.output
    assert "Convocatoria X (id 7): 3 proceso(s)" in res.output
    assert "NO EXISTE" in res.output             # el puesto de Caja, en el reporte


@requires_dml
def test_activar_con_force_sigue_aunque_fallen_los_prechequeos():
    res, m, orden = _activar(["--force"], pre=_PRE_MAL)

    assert res.exit_code == 0, res.output
    assert orden == ["dml", "rebackfill", "promover", "verificar"]
    assert "ADVERTENCIA: --force" in res.output
    for problema in _PRE_MAL["problemas"]:
        assert problema in res.output


@requires_dml
def test_activar_dry_run_cuenta_cada_paso_sin_escribir():
    res, m, orden = _activar(["--dry-run"], pre=_PRE_OK)

    assert res.exit_code == 0, res.output
    assert orden == []
    m["ejecutar"].assert_not_called()
    m["verificar"].assert_not_called()
    m["rebackfill"].assert_called_once_with(dry_run=True)
    m["promover"].assert_called_once_with(dry_run=True)
    assert "22_library_requirement_auto.sql" in res.output
    assert "Requisitos de no adeudo por encender: 2 de 5" in res.output
    assert "Dry-run: no se ejecutó nada." in res.output


@requires_dml
def test_activar_dry_run_sale_distinto_de_0_si_la_corrida_real_abortaria():
    res, _m, orden = _activar(["--dry-run"], pre=_PRE_MAL)

    assert res.exit_code != 0, res.output
    assert orden == []
    assert "la corrida real abortaría" in res.output

    con_force, _m, _o = _activar(["--dry-run", "--force"], pre=_PRE_MAL)
    assert con_force.exit_code == 0, con_force.output


@requires_dml
def test_activar_aborta_si_la_verificacion_reporta_un_problema():
    res, _m, _orden = _activar([], pre=_PRE_OK,
                               verif=["1 fila(s) de titulatec_cotejo_requirements sin "
                                      "auto_source (el 22 no aterrizo)"])

    assert res.exit_code != 0, res.output
    assert "el 22 no aterrizo" in res.output


# ---------------------------------------------------------------------------
# `_library_clearance_rebackfill` contra Postgres real, DENTRO del savepoint
# de `db_session` (Ruling R3 del brief: mismo predicado que el backfill de
# la migracion tt20261001a, probado sobre pending/legacy/fase 2
# aprobada/revocado).
# ---------------------------------------------------------------------------
def _req_library_clearance(db_session, cohort):
    """Fila `CotejoRequirement(code='library_clearance')` de esa convocatoria,
    escrita a mano (patron de `test_requirement_service.py::_req`)."""
    from itcj2.apps.titulatec.models import CotejoRequirement
    row = CotejoRequirement(
        cohort_id=cohort.id, label="No-adeudo de biblioteca", icon="book",
        hint="Constancia de no adeudo vigente.", code="library_clearance",
        auto_source=None, is_required=True, is_active=True, order_index=4,
    )
    db_session.add(row)
    db_session.flush()
    return row


def _fulfillment(db_session, process, requirement, status):
    from itcj2.apps.titulatec.models import RequirementFulfillment
    row = RequirementFulfillment(
        process_id=process.id, requirement_id=requirement.id,
        requirement_code="library_clearance", status=status, source="officer",
    )
    db_session.add(row)
    db_session.flush()
    return row


def test_rebackfill_respeta_el_predicado_pending_legacy_fase2_revocado(
    db_session, patched_session_local, make_cohort, make_student, make_process,
):
    """Los 4 casos de la Ruling R3: pending, legacy (fulfilled Y waived),
    fase 2 ya aprobada (excluido) y revocado/cancelled (excluido) -- mas un
    proceso que YA tiene fila (excluido, NOT EXISTS) y uno on_hold (incluido,
    mismo que active). Ninguno de los `make_process` de abajo deja que la
    fabrica cree su fila automatica (`library_clearance=None`): se trata de
    simular procesos creados en el blue/green SIN fila todavia.
    """
    from itcj2.apps.titulatec.models import LibraryClearance

    cohort = make_cohort()
    requisito = _req_library_clearance(db_session, cohort)

    # 1. pending: activo, fase 2 NO aprobada, sin cumplimiento, sin fila.
    p_pending = make_process(make_student(), cohort=cohort, current_phase=1,
                             status="active", library_clearance=None)

    # 2. legacy via fulfilled.
    p_legacy_fulfilled = make_process(make_student(), cohort=cohort, current_phase=1,
                                      status="active", library_clearance=None)
    _fulfillment(db_session, p_legacy_fulfilled, requisito, "fulfilled")

    # 3. legacy via waived.
    p_legacy_waived = make_process(make_student(), cohort=cohort, current_phase=1,
                                   status="active", library_clearance=None)
    _fulfillment(db_session, p_legacy_waived, requisito, "waived")

    # 4. on_hold: mismo trato que active (incluido en status IN (...)).
    p_on_hold = make_process(make_student(), cohort=cohort, current_phase=1,
                             status="on_hold", library_clearance=None)

    # 5. fase 2 YA aprobada (current_phase=3 -> fases 0,1,2 quedan 'approved'):
    #    EXCLUIDO aunque no tenga fila ni cumplimiento.
    p_fase2_aprobada = make_process(make_student(), cohort=cohort, current_phase=3,
                                    status="active", library_clearance=None)

    # 6. revocado: EXCLUIDO por status.
    p_cancelado = make_process(make_student(), cohort=cohort, current_phase=1,
                               status="cancelled", library_clearance=None)

    # 7. ya tiene fila (la crea la propia fabrica): EXCLUIDO por NOT EXISTS,
    #    y su fila original NO debe tocarse ni duplicarse.
    p_ya_tiene_fila = make_process(make_student(), cohort=cohort, current_phase=1,
                                   status="active", library_clearance="pending")

    # Checkpoint (igual que test_cli_posgrado.py): bajo
    # join_transaction_mode="create_savepoint", el `db.rollback()` interno
    # del dry-run regresa al ULTIMO commit, no al inicio de la sesion. Sin
    # este commit, el dry-run de abajo se llevaria por delante las fixtures.
    db_session.commit()

    # --- dry-run: cuenta sin escribir. Delta antes/despues (no igualdad
    # exacta): la BD de dev es COMPARTIDA y podria traer otros procesos
    # reales que tambien casen el predicado (mismo criterio que
    # test_cli_posgrado.py, "Membresia/no-membresia... fragil ante ambiente").
    antes = _library_clearance_rebackfill(dry_run=True)
    despues = _library_clearance_rebackfill(dry_run=True)
    assert despues == antes, "el dry-run no debe escribir (dos corridas, mismo conteo)"
    assert despues >= 4, "deberian contarse AL MENOS los 4 candidatos de este test"

    assert db_session.query(LibraryClearance).filter(
        LibraryClearance.process_id.in_([p_pending.id, p_legacy_fulfilled.id,
                                         p_legacy_waived.id, p_on_hold.id])
    ).count() == 0, "el dry-run no debe haber escrito ninguna fila"

    # --- real: inserta SOLO los 4 candidatos ---
    creadas = _library_clearance_rebackfill(dry_run=False)
    assert creadas == despues, "la corrida real deberia crear las mismas que conto el dry-run"

    filas = {
        row.process_id: (row.status, row.cleared_via)
        for row in db_session.query(LibraryClearance).filter(
            LibraryClearance.process_id.in_([
                p_pending.id, p_legacy_fulfilled.id, p_legacy_waived.id,
                p_on_hold.id, p_fase2_aprobada.id, p_cancelado.id,
                p_ya_tiene_fila.id,
            ])
        )
    }
    assert filas[p_pending.id] == ("pending", None)
    assert filas[p_legacy_fulfilled.id] == ("cleared", "legacy")
    assert filas[p_legacy_waived.id] == ("cleared", "legacy")
    assert filas[p_on_hold.id] == ("pending", None)
    assert p_fase2_aprobada.id not in filas, "fase 2 ya aprobada: NO debe crearse fila"
    assert p_cancelado.id not in filas, "proceso cancelado: NO debe crearse fila"
    assert filas[p_ya_tiene_fila.id][0] == "pending", "la fila que ya existia no debe cambiar"

    n_fila_previa = (db_session.query(LibraryClearance)
                     .filter_by(process_id=p_ya_tiene_fila.id).count())
    assert n_fila_previa == 1, "el re-backfill NO debe duplicar una fila ya existente"

    # --- idempotencia: segunda corrida real no inserta nada mas ---
    otra_vez = _library_clearance_rebackfill(dry_run=False)
    assert otra_vez == 0, "segunda corrida: NOT EXISTS ya excluye todo, 0 filas nuevas"


# ---------------------------------------------------------------------------
# `_library_clearance_promote` (Ruling R20, I2): la promoción D17 de la
# ventana de transición, contra Postgres real DENTRO del savepoint.
# ---------------------------------------------------------------------------
def _fase2_aprobada(db_session, process):
    from itcj2.apps.titulatec.models import ProcessPhase
    (db_session.query(ProcessPhase)
     .filter_by(process_id=process.id, phase_number=2)
     .update({"status": "approved"}))
    db_session.flush()


def test_promocion_d17_de_lo_marcado_a_mano_tras_la_migracion(
    db_session, patched_session_local, make_cohort, make_student, make_process,
    make_library_clearance,
):
    """Marcado A MANO después de la migración (la fila ya existía `pending`,
    así que el re-backfill no la revisita): `cleared/legacy` si el requisito
    quedó `fulfilled`/`waived`, o si la fase 2 ya está `approved`. NO se
    promueve lo que Biblioteca ya tocó (`library_at`), ni lo que no está
    `pending`, ni lo que no tiene ninguna de las dos razones."""
    from datetime import datetime

    from itcj2.apps.titulatec.models import LibraryClearance

    cohort = make_cohort()
    requisito = _req_library_clearance(db_session, cohort)

    def _proc(**kw):
        return make_process(make_student(), cohort=cohort, current_phase=kw.pop("fase", 2),
                            status="active", library_clearance=None)

    a_mano = _proc()
    make_library_clearance(a_mano, status="pending")
    _fulfillment(db_session, a_mano, requisito, "fulfilled")

    dispensado = _proc()
    make_library_clearance(dispensado, status="pending")
    _fulfillment(db_session, dispensado, requisito, "waived")

    ya_cotejado = _proc(fase=2)
    make_library_clearance(ya_cotejado, status="pending")
    _fase2_aprobada(db_session, ya_cotejado)          # sin cumplimiento: igual pasa

    tocado = _proc()                                   # Biblioteca ya lo registró
    make_library_clearance(tocado, status="pending",
                           library_at=datetime(2026, 9, 30, 10, 0))
    _fulfillment(db_session, tocado, requisito, "fulfilled")

    en_caja = _proc()                                  # solo `pending` se promueve
    make_library_clearance(en_caja, status="awaiting_payment")
    _fulfillment(db_session, en_caja, requisito, "fulfilled")

    sin_razon = _proc()
    make_library_clearance(sin_razon, status="pending")

    # Checkpoint: el dry-run hace `rollback()`, que bajo `create_savepoint`
    # regresa al ÚLTIMO commit (mismo patrón que la prueba del re-backfill).
    db_session.commit()

    antes = _library_clearance_promote(dry_run=True)
    assert _library_clearance_promote(dry_run=True) == antes, "el dry-run no escribe"
    assert antes >= 3, "al menos los 3 candidatos de esta prueba"

    promovidas = _library_clearance_promote(dry_run=False)
    assert promovidas == antes

    filas = {row.process_id: (row.status, row.cleared_via)
             for row in db_session.query(LibraryClearance).filter(
                 LibraryClearance.process_id.in_([
                     a_mano.id, dispensado.id, ya_cotejado.id, tocado.id,
                     en_caja.id, sin_razon.id]))}
    assert filas[a_mano.id] == ("cleared", "legacy")
    assert filas[dispensado.id] == ("cleared", "legacy")
    assert filas[ya_cotejado.id] == ("cleared", "legacy")
    assert filas[tocado.id] == ("pending", None), "Biblioteca ya lo tocó: no se promueve"
    assert filas[en_caja.id] == ("awaiting_payment", None)
    assert filas[sin_razon.id] == ("pending", None)

    # Sin eventos: es dato, como el backfill.
    from itcj2.apps.titulatec.models import ProcessEvent
    assert db_session.query(ProcessEvent).filter(
        ProcessEvent.process_id.in_([a_mano.id, dispensado.id, ya_cotejado.id]),
        ProcessEvent.event_type.like("library_%")).count() == 0

    assert _library_clearance_promote(dry_run=False) == 0, "idempotente"


# ---------------------------------------------------------------------------
# `_precheck_activar_biblioteca` (Ruling R19): pre-chequeos de SOLO LECTURA,
# contra Postgres real DENTRO del savepoint.
# ---------------------------------------------------------------------------
def _puestos_reales(db_session, make_position):
    """Los dos puestos nuevos (los crea si la base no los trae -CI-; en dev
    ya existen por el DML) SIN ocupantes vigentes: los que hubiera se
    desactivan DENTRO de la transacción de la prueba (se deshace al final)."""
    from itcj2.core.models.position import UserPosition

    puestos = {code: make_position(code=code, title=code) for code in _PUESTOS_BIBLIOTECA_CAJA}
    (db_session.query(UserPosition)
     .filter(UserPosition.position_id.in_([p.id for p in puestos.values()]))
     .update({"is_active": False}, synchronize_session=False))
    db_session.flush()
    return puestos


def test_precheck_puestos_sin_ocupante_vigente_y_luego_con_ocupante(
    db_session, patched_session_local, make_position, make_user, assign_position,
):
    puestos = _puestos_reales(db_session, make_position)

    vacio = _precheck_activar_biblioteca()
    assert vacio["ocupantes"] == {code: 0 for code in _PUESTOS_BIBLIOTECA_CAJA}
    for code in _PUESTOS_BIBLIOTECA_CAJA:
        assert any(code in p and "sin ocupante" in p for p in vacio["problemas"]), code

    # Ocupantes que NO cuentan: asignación vencida y usuario desactivado.
    assign_position(make_user(), puestos[_PUESTO_LIBRARY],
                    start_date=db_now().date() - timedelta(days=30),
                    end_date=db_now().date() - timedelta(days=1))
    assign_position(make_user(is_active=False), puestos[_PUESTO_CASHIER])
    assert _precheck_activar_biblioteca()["ocupantes"] == {
        code: 0 for code in _PUESTOS_BIBLIOTECA_CAJA}

    # Un ocupante vigente en cada uno: ya no hay problema de puestos.
    for puesto in puestos.values():
        assign_position(make_user(), puesto)
    lleno = _precheck_activar_biblioteca()
    assert lleno["ocupantes"] == {code: 1 for code in _PUESTOS_BIBLIOTECA_CAJA}
    assert not any("puesto" in p for p in lleno["problemas"]), lleno["problemas"]


def test_precheck_puesto_inexistente_pide_correr_init(
    db_session, patched_session_local, monkeypatch,
):
    monkeypatch.setattr(f"{_MOD}._PUESTOS_BIBLIOTECA_CAJA",
                        ("tt_test_puesto_que_no_existe",))

    pre = _precheck_activar_biblioteca()

    assert pre["ocupantes"] == {"tt_test_puesto_que_no_existe": None}
    assert any("puesto ausente" in p and "init-biblioteca-caja" in p
               for p in pre["problemas"]), pre["problemas"]


def test_precheck_convocatoria_con_candado_sin_donacion(
    db_session, patched_session_local, make_cohort, make_student, make_process,
):
    from decimal import Decimal

    sin = make_cohort(name="Convocatoria precheck sin donacion R19")
    _req_library_clearance(db_session, sin)
    make_process(make_student(), cohort=sin, current_phase=1, status="active")
    make_process(make_student(), cohort=sin, current_phase=1, status="on_hold")
    make_process(make_student(), cohort=sin, current_phase=1, status="cancelled")  # no cuenta
    make_process(make_student(), cohort=sin, current_phase=3, status="active")     # ya cotejado

    con = make_cohort(name="Convocatoria precheck con donacion R19",
                      book_donation_amount=Decimal("0.00"))
    _req_library_clearance(db_session, con)
    make_process(make_student(), cohort=con, current_phase=1)

    sin_candado = make_cohort(name="Convocatoria precheck sin candado R19")
    make_process(make_student(), cohort=sin_candado, current_phase=1)

    pre = _precheck_activar_biblioteca()
    por_id = {c["cohort_id"]: c for c in pre["sin_donacion"]}

    assert por_id[sin.id] == {"cohort_id": sin.id, "name": sin.name, "pending": 2}
    assert con.id not in por_id, "con donación (aunque sea $0) no es problema"
    assert sin_candado.id not in por_id, "sin fila library_clearance no quedará con candado"
    assert any(sin.name in p and "donación" in p for p in pre["problemas"])


# ---------------------------------------------------------------------------
# `_verify_biblioteca_caja` (m04): contra Postgres real, DENTRO del savepoint
# de `db_session` (igual que `_precheck_activar_biblioteca` arriba). Antes
# abría `_get_engine().connect()` crudo -invisible para `patched_session_
# local`, así que las 3 pruebas de comando de arriba la parchean- ahora abre
# `SessionLocal()` como sus vecinas de este archivo.
#
# La BD de dev es COMPARTIDA y `init-biblioteca-caja` ya corrió ahí de verdad
# (el delta no es hipotético): sin neutralizar lo AMBIENTE, una prueba que
# sembrara "falta el mapeo X" podría ver el mapeo real de todos modos (mismo
# código/puesto que ya existe en dev) y la aserción sería no-determinista --
# mismo riesgo que ya resuelve `_puestos_reales` arriba para el precheck.
# Por eso `_limpiar_y_sembrar` primero BORRA, dentro del savepoint, los
# `RolePermission`/`PositionAppRole` de los 2 roles/puestos nuevos que caigan
# en el universo de los 10 códigos del delta, y DESPUÉS siembra exactamente
# lo que el 20/21 crean -así la prueba es la misma sin importar qué tan
# sembrada esté la base real por debajo.
# ---------------------------------------------------------------------------
def _limpiar_y_sembrar_biblioteca_caja(db_session, titulatec_app, make_position, make_perms,
                                       make_role, bind_position_role, *,
                                       sin_mapeo_cashier=False):
    from itcj2.core.models.permission import Permission
    from itcj2.core.models.position import PositionAppRole
    from itcj2.core.models.role import Role
    from itcj2.core.models.role_permission import RolePermission

    make_perms(_PERMISOS_BIBLIOTECA_CAJA_2026_10)

    pos_library = make_position(code=_PUESTO_LIBRARY)
    pos_cashier = make_position(code=_PUESTO_CASHIER)

    perm_ids = {
        pid for (pid,) in db_session.query(Permission.id).filter(
            Permission.app_id == titulatec_app.id,
            Permission.code.in_(_PERMISOS_BIBLIOTECA_CAJA_2026_10))
    }
    role_ids = {
        rid for (rid,) in db_session.query(Role.id)
        .filter(Role.name.in_([_ROL_LIBRARY, _ROL_CASHIER]))
    }
    if perm_ids and role_ids:
        (db_session.query(RolePermission)
         .filter(RolePermission.role_id.in_(role_ids), RolePermission.perm_id.in_(perm_ids))
         .delete(synchronize_session=False))
    (db_session.query(PositionAppRole)
     .filter(PositionAppRole.position_id.in_([pos_library.id, pos_cashier.id]))
     .delete(synchronize_session=False))
    db_session.flush()

    rol_library = make_role(_ROL_LIBRARY, _PERMISOS_ROL_LIBRARY)
    rol_cashier = make_role(_ROL_CASHIER, _PERMISOS_ROL_CASHIER)
    make_role(_ROL_GTV, [_PERM_SURVEY_PRINT_CERTIFICATES, _PERM_CERTIFICATE_PAGE_LIST])
    make_role(_ROL_OPERATIVO_ESCOLARES, ["titulatec.library_clearance.api.prior"])
    make_role(_ROL_JEFATURA_ESCOLARES, ["titulatec.library_clearance.api.prior"])
    make_role(_ROL_ADMIN, _PERMISOS_BIBLIOTECA_CAJA_2026_10)

    bind_position_role(pos_library, rol_library)
    if not sin_mapeo_cashier:
        bind_position_role(pos_cashier, rol_cashier)


def test_verify_biblioteca_caja_sin_problemas_con_todo_bien_sembrado(
    db_session, patched_session_local, titulatec_app, make_position, make_perms, make_role,
    bind_position_role,
):
    _limpiar_y_sembrar_biblioteca_caja(
        db_session, titulatec_app, make_position, make_perms, make_role, bind_position_role)

    assert _verify_biblioteca_caja() == []


def test_verify_biblioteca_caja_detecta_un_mapeo_puesto_rol_faltante(
    db_session, patched_session_local, titulatec_app, make_position, make_perms, make_role,
    bind_position_role,
):
    """Todo lo demás sembrado correctamente (spec §4.6); SOLO falta mapear
    `_PUESTO_CASHIER` -> `_ROL_CASHIER` en `core_position_app_roles` -el
    `_limpiar_y_sembrar_biblioteca_caja` de arriba ya se encargó de que
    ningún mapeo AMBIENTE de la BD de dev real lo tape."""
    _limpiar_y_sembrar_biblioteca_caja(
        db_session, titulatec_app, make_position, make_perms, make_role, bind_position_role,
        sin_mapeo_cashier=True)

    assert _verify_biblioteca_caja() == [
        f"mapeo puesto→rol de {_ROL_CASHIER}: falta {_PUESTO_CASHIER} (hay [])"
    ]
