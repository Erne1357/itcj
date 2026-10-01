"""Contrato del DML `biblioteca_2026_10/` + comando `titulatec init-biblioteca-caja`
(Tarea 2, spec 2026-10-01-titulatec-biblioteca-caja-design.md §4.6/§6).

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

`init-biblioteca-caja` ademas RE-BACKFILLEA `titulatec_library_clearances`
con el MISMO predicado que el backfill de la migracion `tt20261001a`
(`migrations/versions/tt20261001a_titulatec_biblioteca_caja.py`, BACKFILL_SQL):
alcanza los procesos creados durante la ventana blue/green, entre que corrio
la migracion y que corre este comando (Review Focus #5 del plan).

Mismo patron que `test_cli_posgrado.py`/`test_cli_survey_delta.py`:
`database/` esta gitignored y el checkout de CI no lo trae, asi que las
pruebas que tocan el archivo en disco (o invocan el comando de verdad) se
saltan ahi (`requires_dml`); las que solo verifican constantes de Python
corren siempre.

Hermeticidad (mismo criterio que `test_cli_posgrado.py`): las pruebas a
nivel comando (`CliRunner`) parchan `execute_sql_file`/`_verify_biblioteca_caja`/
`_library_clearance_rebackfill` -- ninguna toca la BD de dev de verdad.
`_library_clearance_rebackfill` en si misma SI se prueba contra Postgres
real, pero DENTRO del savepoint de `db_session` (`patched_session_local`
intercepta su `SessionLocal()` interno) -- nunca contra el engine de
produccion sin aislar.
"""
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from itcj2.cli.titulatec import (
    DML_TITULATEC,
    SEED_FILES,
    _DML_BIBLIOTECA_2026_10_DIR,
    _DML_BIBLIOTECA_2026_10_FILES,
    _PERMISOS_BIBLIOTECA_CAJA_2026_10,
    _PERMISOS_ROL_CASHIER,
    _PERMISOS_ROL_LIBRARY,
    _PUESTO_CASHIER,
    _PUESTO_LIBRARY,
    _ROL_CASHIER,
    _ROL_LIBRARY,
    _library_clearance_rebackfill,
    init_biblioteca_caja_command,
)

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


def test_el_delta_esta_en_seed_files_con_su_prefijo_de_subcarpeta():
    """Sin esto, una base NUEVA (`core seed-reference-data`) nace sin los 3."""
    for nombre in _DML_BIBLIOTECA_2026_10_FILES:
        assert f"{_DML_BIBLIOTECA_2026_10_DIR}/{nombre}" in SEED_FILES, (
            f"{nombre} no esta en SEED_FILES con el prefijo {_DML_BIBLIOTECA_2026_10_DIR}/")


def test_el_delta_va_antes_del_grant_de_admin():
    """15_grant_admin_all_perms.sql concede dinamicamente TODOS los permisos
    de titulatec existentes al correr: si este delta corriera despues, el
    rol admin se quedaria sin los 10 codigos nuevos hasta la siguiente
    corrida completa de `init-titulatec` -- y en produccion esa corrida
    nunca pasa. Sin BD: solo verifica el orden de la lista en memoria."""
    quince = SEED_FILES.index("15_grant_admin_all_perms.sql")
    for nombre in _DML_BIBLIOTECA_2026_10_FILES:
        idx = SEED_FILES.index(f"{_DML_BIBLIOTECA_2026_10_DIR}/{nombre}")
        assert idx < quince, f"{nombre} debe ir ANTES de 15_grant_admin_all_perms.sql"


# ---------------------------------------------------------------------------
# Disco: requieren database/DML/titulatec/biblioteca_2026_10/ en el checkout.
# ---------------------------------------------------------------------------
@requires_dml
def test_todo_sql_del_delta_esta_en_la_lista_del_comando():
    """Membresia: ningun .sql del directorio puede quedarse sin comando
    (mismo riesgo que perdio el 13 de survey_2026_09, ver test_cli_survey_delta.py)."""
    en_disco = sorted(p.name for p in
                      (DML_TITULATEC / _DML_BIBLIOTECA_2026_10_DIR).glob("*.sql"))

    assert en_disco == sorted(_DML_BIBLIOTECA_2026_10_FILES), (
        "el directorio del delta y la lista del comando divergen: "
        f"en disco {en_disco}, en la lista {sorted(_DML_BIBLIOTECA_2026_10_FILES)}. "
        "Un .sql que no este en la lista NO lo corre ningun comando, y nada mas "
        "se pone rojo.")

    for nombre in ("20_insert_library_cashier_positions.sql",
                   "21_insert_library_cashier_roles_perms.sql",
                   "22_library_requirement_auto.sql"):
        assert nombre in en_disco, f"falta {nombre} en el directorio del delta"


@requires_dml
def test_dry_run_no_ejecuta_sql_ni_verifica():
    with patch("itcj2.cli.core.execute_sql_file") as ejecutar, \
         patch("itcj2.cli.titulatec._verify_biblioteca_caja") as verificar, \
         patch("itcj2.cli.titulatec._library_clearance_rebackfill",
               return_value=0) as rebackfill:
        res = CliRunner().invoke(init_biblioteca_caja_command, ["--dry-run"])

    assert res.exit_code == 0, res.output
    ejecutar.assert_not_called()
    verificar.assert_not_called()
    rebackfill.assert_called_once_with(dry_run=True)
    assert "[dry-run]" in res.output
    assert "Dry-run: no se ejecutó nada." in res.output


@requires_dml
def test_corre_todos_los_archivos_del_delta_y_ninguno_mas():
    with patch("itcj2.cli.core.execute_sql_file", return_value=True) as ejecutar, \
         patch("itcj2.cli.titulatec._verify_biblioteca_caja", return_value=[]), \
         patch("itcj2.cli.titulatec._library_clearance_rebackfill",
               return_value=3) as rebackfill:
        res = CliRunner().invoke(init_biblioteca_caja_command, [])

    assert res.exit_code == 0, res.output
    corridos = [str(c.args[0]) for c in ejecutar.call_args_list]
    assert len(corridos) == len(_DML_BIBLIOTECA_2026_10_FILES), corridos
    for nombre in _DML_BIBLIOTECA_2026_10_FILES:
        assert any(r.endswith(nombre) for r in corridos), f"no corrio {nombre}"
    # NUNCA el DML base ni otros deltas: solo los 3 de este.
    assert not any("01_insert_roles" in r or "03_insert_role_permissions" in r
                   or "survey_2026_09" in r or "posgrado_2026_10" in r
                   for r in corridos), corridos
    rebackfill.assert_called_once_with(dry_run=False)
    assert "3" in res.output


@requires_dml
def test_aborta_si_la_verificacion_reporta_un_problema():
    with patch("itcj2.cli.core.execute_sql_file", return_value=True), \
         patch("itcj2.cli.titulatec._library_clearance_rebackfill", return_value=0), \
         patch("itcj2.cli.titulatec._verify_biblioteca_caja",
               return_value=["permiso ausente: titulatec.library_payment.api.revert"]):
        res = CliRunner().invoke(init_biblioteca_caja_command, [])

    assert res.exit_code != 0, "un delta a medias NO puede salir 0"
    assert "titulatec.library_payment.api.revert" in res.output


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
