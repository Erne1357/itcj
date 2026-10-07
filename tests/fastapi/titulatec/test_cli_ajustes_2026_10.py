"""Contrato del delta `ajustes_2026_10/` + comando `titulatec init-ajustes-2026-10`.

Spec 2026-10-07-titulatec-liberados-biblioteca-helpdesk-design.md (D1, D2,
D7, D8, §1.1, §3, §6, §7):

- Permiso NUEVO `titulatec.process.page.summary` (expediente resumido).
- `titulatec_titulacion` (jefa del Depto. de Titulación) CONVERGE a su set
  EXACTO de 16 (22 - 7 + el resumido). El usuario editó a mano sus permisos
  en la BD: el delta concede lo que falte del set y quita todo lo de
  titulatec fuera de él; idempotente.
- `titulatec_school_services` y `titulatec_school_services_head` ganan la
  bandeja de Liberados: `handoff.page.list` + `handoff.api.export` (sin set
  exacto).
- `admin` recibe el permiso nuevo EXPLÍCITO (el 15 nunca se re-corre en
  producción).
- `titulatec_titulaciones` (25) NO cambia.
- El requisito de cotejo `library_clearance` se llama «Constancia de no
  adeudo de biblioteca» (antes «No-adeudo de biblioteca»).

En producción el DML viejo nunca se re-corre: el delta va en su propia
subcarpeta con su comando, que verifica contra la BD al final e invalida el
caché de authz de titulatec con `invalidate_app` -- NUNCA `invalidate_all`
(cada `execute_sql_file` lo dispararía por omisión: el comando lo llama con
`invalidate_authz=False`).

Hermeticidad (mismo criterio que `test_cli_biblioteca_caja.py`): las pruebas
a nivel comando parchan `execute_sql_file`, el snapshot y la invalidación;
ninguna escribe en la BD de dev. La prueba del SQL de verdad corre DENTRO del
savepoint de `db_session` (`patched_session_local` intercepta el
`SessionLocal()` del snapshot) y se deshace al terminar. Las que leen
`database/` llevan `requires_dml` (gitignored: el checkout de CI no lo trae).
"""
import re
from unittest.mock import call, patch

import pytest
from click.testing import CliRunner
from sqlalchemy import text

from itcj2.cli.titulatec import (
    DML_TITULATEC,
    SEED_FILES,
    _DML_AJUSTES_2026_10_DIR,
    _DML_AJUSTES_2026_10_FILES,
    _ETIQUETA_BIBLIOTECA,
    _ETIQUETA_BIBLIOTECA_VIEJA,
    _PERM_PROCESS_SUMMARY,
    _PERMISOS_HANDOFF,
    _PERMISOS_RETIRADOS_TITULACION,
    _PERMISOS_ROL_TITULACION,
    _PERMISOS_ROL_TITULACIONES_DIV,
    _ROL_JEFATURA_ESCOLARES,
    _ROL_OPERATIVO_ESCOLARES,
    _ROL_TITULACION,
    _ROL_TITULACIONES_DIV,
    _ROLES_AJUSTES_2026_10,
    _esperado_ajustes_2026_10,
    _snapshot_ajustes_2026_10,
    _verify_ajustes_2026_10,
    init_ajustes_2026_10_command,
)

_MOD = "itcj2.cli.titulatec"
_DIR = DML_TITULATEC / _DML_AJUSTES_2026_10_DIR

requires_dml = pytest.mark.skipif(
    not _DIR.is_dir(),
    reason=(
        "database/DML/titulatec/ajustes_2026_10/ no esta en el checkout "
        "(gitignored a proposito: nunca llega a CI)."
    ),
)

# Los 22 de antes del 2026-10-07: los 16 de hoy sin el resumido + los 7 retirados.
_VIEJOS_22 = ((set(_PERMISOS_ROL_TITULACION) - {_PERM_PROCESS_SUMMARY})
              | set(_PERMISOS_RETIRADOS_TITULACION))
_SE_ANTES = {"titulatec.dashboard.school_services", "titulatec.process.page.list"}
_JEFA_ANTES = {"titulatec.dashboard.school_services", "titulatec.process.api.read.all"}


def _snap(perms, etiquetas, *, existe_summary, admin_summary,
          roles=_ROLES_AJUSTES_2026_10):
    return {"roles": set(roles), "perms": {r: set(c) for r, c in perms.items()},
            "existe_summary": existe_summary, "admin_summary": admin_summary,
            "etiquetas": dict(etiquetas)}


def _antes(titulacion=None):
    return _snap({
        _ROL_TITULACION: set(_VIEJOS_22 if titulacion is None else titulacion),
        _ROL_TITULACIONES_DIV: set(_PERMISOS_ROL_TITULACIONES_DIV),
        _ROL_OPERATIVO_ESCOLARES: set(_SE_ANTES),
        _ROL_JEFATURA_ESCOLARES: set(_JEFA_ANTES),
    }, {_ETIQUETA_BIBLIOTECA_VIEJA: 3, "Etiqueta propia de SE": 1},
        existe_summary=False, admin_summary=False)


def _despues():
    return _snap({
        _ROL_TITULACION: set(_PERMISOS_ROL_TITULACION),
        _ROL_TITULACIONES_DIV: set(_PERMISOS_ROL_TITULACIONES_DIV),
        _ROL_OPERATIVO_ESCOLARES: _SE_ANTES | set(_PERMISOS_HANDOFF),
        _ROL_JEFATURA_ESCOLARES: _JEFA_ANTES | set(_PERMISOS_HANDOFF),
    }, {_ETIQUETA_BIBLIOTECA: 3, "Etiqueta propia de SE": 1},
        existe_summary=True, admin_summary=True)


# ---------------------------------------------------------------------------
# Constantes de Python (sin BD, sin disco): corren siempre.
# ---------------------------------------------------------------------------
def test_las_etiquetas_del_requisito_son_las_de_la_spec():
    """§3: «No-adeudo de biblioteca» (requisito) -> «Constancia de no adeudo de
    biblioteca». El mismo texto lo usa `cotejo_requirement_service.DEFAULTS`."""
    assert _ETIQUETA_BIBLIOTECA_VIEJA == "No-adeudo de biblioteca"
    assert _ETIQUETA_BIBLIOTECA == "Constancia de no adeudo de biblioteca"


def test_el_set_de_titulacion_son_los_22_menos_7_mas_el_resumido():
    assert len(_VIEJOS_22) == 22
    assert len(set(_PERMISOS_RETIRADOS_TITULACION)) == 7
    assert set(_PERMISOS_ROL_TITULACION) == (
        _VIEJOS_22 - set(_PERMISOS_RETIRADOS_TITULACION)) | {_PERM_PROCESS_SUMMARY}
    assert len(set(_PERMISOS_ROL_TITULACION)) == 16


def test_el_delta_son_dos_archivos_y_no_va_en_seed_files():
    """Una instalación nueva ya nace con el estado nuevo (02 + 03 + 15 + 22 de
    `biblioteca_2026_10/`): el delta es solo el camino de producción."""
    assert _DML_AJUSTES_2026_10_FILES == [
        "01_liberados_permisos.sql",
        "02_requisito_constancia.sql",
    ]
    assert not any(f.startswith(f"{_DML_AJUSTES_2026_10_DIR}/") for f in SEED_FILES)


def test_los_roles_que_toca_el_delta():
    assert set(_ROLES_AJUSTES_2026_10) == {
        "titulatec_titulacion", "titulatec_titulaciones",
        "titulatec_school_services", "titulatec_school_services_head",
    }


def test_lo_esperado_converge_titulacion_y_suma_liberados_a_se():
    esperado = _esperado_ajustes_2026_10(_antes()["perms"])

    assert esperado == _despues()["perms"]
    assert len(esperado[_ROL_TITULACION]) == 16


def test_lo_esperado_converge_titulacion_aunque_la_hayan_editado_a_mano():
    """D8: el usuario editó el rol a mano. Le falte lo que le falte o le
    sobre lo que le sobre, lo esperado es SIEMPRE el set exacto."""
    editado = (_VIEJOS_22 - {"titulatec.process.api.hold", "titulatec.handoff.api.export"}) | {
        "titulatec.cohort.page.list"}
    esperado = _esperado_ajustes_2026_10(_antes(editado)["perms"])

    assert esperado[_ROL_TITULACION] == set(_PERMISOS_ROL_TITULACION)


def test_lo_esperado_es_idempotente():
    """Correrlo dos veces: lo esperado de un estado ya ajustado es él mismo."""
    despues = _despues()["perms"]
    assert _esperado_ajustes_2026_10(despues) == despues


# --- _verify_ajustes_2026_10 (pura: antes, despues) -------------------------
def test_verify_sano_no_reporta_nada():
    assert _verify_ajustes_2026_10(_antes(), _despues()) == []
    assert _verify_ajustes_2026_10(_despues(), _despues()) == []


@pytest.mark.parametrize("extra", ["titulatec.process.page.detail", "titulatec.cohort.page.list"])
def test_verify_titulacion_con_un_permiso_de_mas(extra):
    despues = _despues()
    despues["perms"][_ROL_TITULACION].add(extra)

    problemas = _verify_ajustes_2026_10(_antes(), despues)

    assert any(f"{_ROL_TITULACION} " in p and extra in p for p in problemas), problemas


def test_verify_titulacion_exige_el_set_exacto_aunque_antes_le_faltara_uno():
    """El contrato de titulación es ABSOLUTO: si antes le faltaba uno (edición
    a mano) y después le sigue faltando, el delta no convergió."""
    antes = _antes(_VIEJOS_22 - {"titulatec.process.api.hold"})
    despues = _despues()
    despues["perms"][_ROL_TITULACION].discard("titulatec.process.api.hold")

    problemas = _verify_ajustes_2026_10(antes, despues)

    assert any("titulatec.process.api.hold" in p for p in problemas), problemas


@pytest.mark.parametrize("rol", [_ROL_OPERATIVO_ESCOLARES, _ROL_JEFATURA_ESCOLARES])
def test_verify_servicios_escolares_sin_liberados(rol):
    despues = _despues()
    despues["perms"][rol].discard("titulatec.handoff.page.list")

    problemas = _verify_ajustes_2026_10(_antes(), despues)

    assert any(rol in p and "titulatec.handoff.page.list" in p for p in problemas), problemas


@pytest.mark.parametrize("rol", [_ROL_OPERATIVO_ESCOLARES, _ROL_JEFATURA_ESCOLARES])
def test_verify_servicios_escolares_no_pierden_nada_mas(rol):
    """Lo de antes + Liberados: el delta no puede quitarles nada."""
    despues = _despues()
    despues["perms"][rol].discard("titulatec.dashboard.school_services")

    problemas = _verify_ajustes_2026_10(_antes(), despues)

    assert any(rol in p and "titulatec.dashboard.school_services" in p
               for p in problemas), problemas


def test_verify_titulaciones_no_cambia():
    despues = _despues()
    despues["perms"][_ROL_TITULACIONES_DIV].discard("titulatec.process.page.list")

    problemas = _verify_ajustes_2026_10(_antes(), despues)

    assert any(_ROL_TITULACIONES_DIV in p for p in problemas), problemas


def test_verify_permiso_nuevo_ausente_o_sin_admin():
    sin_permiso = _despues()
    sin_permiso["existe_summary"] = False
    assert any("permiso ausente" in p and _PERM_PROCESS_SUMMARY in p
               for p in _verify_ajustes_2026_10(_antes(), sin_permiso))

    sin_admin = _despues()
    sin_admin["admin_summary"] = False
    assert any("admin" in p and _PERM_PROCESS_SUMMARY in p
               for p in _verify_ajustes_2026_10(_antes(), sin_admin))


def test_verify_etiqueta_vieja_que_sobrevive():
    despues = _despues()
    despues["etiquetas"][_ETIQUETA_BIBLIOTECA_VIEJA] = 1

    problemas = _verify_ajustes_2026_10(_antes(), despues)

    assert any(_ETIQUETA_BIBLIOTECA_VIEJA in p for p in problemas), problemas


def test_verify_rol_ausente():
    despues = _despues()
    despues["roles"].discard(_ROL_JEFATURA_ESCOLARES)

    problemas = _verify_ajustes_2026_10(_antes(), despues)

    assert any("rol ausente" in p and _ROL_JEFATURA_ESCOLARES in p for p in problemas), problemas


# ---------------------------------------------------------------------------
# Disco: requieren database/DML/titulatec/ajustes_2026_10/ en el checkout.
# ---------------------------------------------------------------------------
def _leer(nombre: str) -> str:
    return (_DIR / nombre).read_text(encoding="utf-8")


def _sin_comentarios(sql: str) -> str:
    return re.sub(r"--[^\n]*", "", sql)


def _codigos(stmt: str) -> set[str]:
    return set(re.findall(r"'(titulatec\.[^']+)'", stmt))


def _como_execute_sql_file(sql: str) -> str:
    """Reproduce el preprocesamiento de `execute_sql_file` (strip de `--`
    línea a línea, sin entender literales): un `--` dentro de un texto se
    trunca igual que en producción (mismo helper que `test_cli_posgrado.py`)."""
    limpias = []
    for linea in sql.split("\n"):
        if "--" in linea:
            linea = linea[:linea.find("--")].rstrip()
        if linea.strip():
            limpias.append(linea)
    return "\n".join(limpias)


@requires_dml
def test_todo_sql_del_directorio_esta_en_la_lista_del_comando():
    """Un `.sql` que se cae de la lista no lo corre nadie y nada se pone rojo."""
    en_disco = sorted(p.name for p in _DIR.glob("*.sql"))
    assert en_disco == sorted(_DML_AJUSTES_2026_10_FILES)


@requires_dml
@pytest.mark.parametrize("nombre", ["01_liberados_permisos.sql", "02_requisito_constancia.sql"])
def test_cada_archivo_documenta_su_sql_inverso(nombre):
    """Spec §6: la reversa del delta es su SQL inverso, documentado en la
    cabecera de cada archivo (comentario, nunca código que corra)."""
    lineas = _leer(nombre).splitlines()
    primera_de_codigo = next(i for i, linea in enumerate(lineas)
                             if linea.strip() and not linea.lstrip().startswith("--"))
    cabecera = "\n".join(lineas[:primera_de_codigo])

    assert lineas[primera_de_codigo].strip() == "DO $$"
    assert "SQL INVERSO" in cabecera
    if nombre.startswith("01"):
        # Devuelve a titulación los 7 retirados, le quita el resumido (y a
        # admin), quita Liberados a SE y borra el permiso nuevo.
        for codigo in (*_PERMISOS_RETIRADOS_TITULACION, *_PERMISOS_HANDOFF,
                       _PERM_PROCESS_SUMMARY):
            assert codigo in cabecera, f"el inverso del 01 no menciona {codigo}"
    else:
        assert f"SET label = '{_ETIQUETA_BIBLIOTECA_VIEJA}'" in cabecera


@requires_dml
def test_el_01_crea_el_permiso_converge_titulacion_y_concede_liberados():
    plano = _sin_comentarios(_leer("01_liberados_permisos.sql"))
    perms = re.findall(r"INSERT\s+INTO\s+core_permissions[^;]*;", plano)
    deletes = re.findall(r"DELETE\s+FROM\s+core_role_permissions[^;]*;", plano)
    grants = re.findall(r"INSERT\s+INTO\s+core_role_permissions[^;]*;", plano)

    # El permiso nuevo, idempotente.
    assert len(perms) == 1
    assert re.search(r"\(\s*v_app_id\s*,\s*'" + re.escape(_PERM_PROCESS_SUMMARY) + "'", perms[0])
    assert "ON CONFLICT (app_id, code) DO NOTHING" in perms[0]

    # Convergencia: INSERT del set exacto + DELETE de todo lo de titulatec fuera de él.
    assert len(deletes) == 1, deletes
    assert "r.name = 'titulatec_titulacion'" in deletes[0]
    assert "p.app_id = v_app_id" in deletes[0]
    not_in, = re.findall(r"p\.code\s+NOT\s+IN\s*\(([^)]*)\)", deletes[0])
    assert _codigos(not_in) == set(_PERMISOS_ROL_TITULACION)

    por_rol = {}
    for g in grants:
        roles = frozenset(re.findall(r"'(titulatec_[a-z_]+|admin)'", g))
        por_rol[roles] = _codigos(g)
        assert "ON CONFLICT DO NOTHING" in g
    assert por_rol == {
        frozenset({"titulatec_titulacion"}): set(_PERMISOS_ROL_TITULACION),
        frozenset({"titulatec_school_services", "titulatec_school_services_head"}):
            set(_PERMISOS_HANDOFF),
        frozenset({"admin"}): {_PERM_PROCESS_SUMMARY},
    }
    # Nada de titulaciones (D1: no cambia).
    assert "titulatec_titulaciones" not in plano


@requires_dml
def test_el_02_renombra_solo_la_etiqueta_vieja_del_requisito_de_biblioteca():
    """Respeta lo que Servicios Escolares haya reescrito a mano (la etiqueta es
    suya; el código no): solo toca filas que siguen con el texto viejo."""
    plano = " ".join(_sin_comentarios(_leer("02_requisito_constancia.sql")).split())

    assert (f"UPDATE titulatec_cotejo_requirements SET label = '{_ETIQUETA_BIBLIOTECA}', "
            "updated_at = NOW() WHERE code = 'library_clearance' "
            f"AND label = '{_ETIQUETA_BIBLIOTECA_VIEJA}';") in plano
    assert not re.search(r"\b(INSERT|DELETE|TRUNCATE|DROP)\b", plano, re.IGNORECASE)


@requires_dml
def test_el_22_base_tambien_trae_la_etiqueta_nueva():
    """Instalación desde cero: el 13 de `survey_2026_09/` siembra la etiqueta
    vieja en convocatorias previas y el 22 (que corre después en
    `SEED_FILES`) la pone al día con el mismo UPDATE condicionado."""
    veintidos = (DML_TITULATEC / "biblioteca_2026_10"
                 / "22_library_requirement_auto.sql").read_text(encoding="utf-8")
    plano = " ".join(_sin_comentarios(veintidos).split())

    assert (f"SET label = '{_ETIQUETA_BIBLIOTECA}', updated_at = NOW() "
            "WHERE code = 'library_clearance' "
            f"AND label = '{_ETIQUETA_BIBLIOTECA_VIEJA}';") in plano
    assert (SEED_FILES.index("biblioteca_2026_10/22_library_requirement_auto.sql")
            > SEED_FILES.index("survey_2026_09/13_seed_cotejo_reqs_all_cohorts.sql"))


# --- El comando, con todo lo que toca la BD parchado ------------------------
def _invoca(args, *, snapshots, verif=None):
    """Corre el comando con execute_sql_file, el snapshot y la invalidación
    parchados. `snapshots` es la lista de lo que devuelve cada snapshot."""
    with patch("itcj2.cli.core.execute_sql_file", return_value=False) as ejecutar, \
         patch(f"{_MOD}._snapshot_ajustes_2026_10", side_effect=list(snapshots)) as snap, \
         patch("itcj2.core.services.authz_cache.invalidate_app") as inv_app, \
         patch("itcj2.core.services.authz_cache.invalidate_all") as inv_all:
        if verif is not None:
            with patch(f"{_MOD}._verify_ajustes_2026_10", return_value=list(verif)):
                res = CliRunner().invoke(init_ajustes_2026_10_command, args)
        else:
            res = CliRunner().invoke(init_ajustes_2026_10_command, args)
    return res, {"ejecutar": ejecutar, "snap": snap, "inv_app": inv_app, "inv_all": inv_all}


@requires_dml
def test_dry_run_reporta_que_agregaria_y_quitaria_sin_escribir():
    """D8: con el rol editado a mano (le falta `process.api.hold`, le sobra
    `cohort.page.list`), el dry-run dice por código qué agregaría y qué
    quitaría, y lista el set de hoy para la reversa."""
    editado = (_VIEJOS_22 - {"titulatec.process.api.hold"}) | {"titulatec.cohort.page.list"}
    res, m = _invoca(["--dry-run"], snapshots=[_antes(editado)])

    assert res.exit_code == 0, res.output
    m["ejecutar"].assert_not_called()
    m["inv_app"].assert_not_called()
    m["inv_all"].assert_not_called()
    assert m["snap"].call_count == 1
    for nombre in _DML_AJUSTES_2026_10_FILES:
        assert nombre in res.output
    assert f"{_ROL_TITULACION}: 22 → 16" in res.output
    assert f"{_ROL_OPERATIVO_ESCOLARES}: 2 → 4" in res.output
    assert f"{_ROL_JEFATURA_ESCOLARES}: 2 → 4" in res.output
    assert f"{_ROL_TITULACIONES_DIV}: 25 → 25" in res.output
    for quitaria in (*_PERMISOS_RETIRADOS_TITULACION, "titulatec.cohort.page.list"):
        assert f"- {quitaria}" in res.output, quitaria
    for agregaria in (_PERM_PROCESS_SUMMARY, "titulatec.process.api.hold",
                      "titulatec.handoff.api.export"):
        assert f"+ {agregaria}" in res.output, agregaria
    assert f"admin: + {_PERM_PROCESS_SUMMARY}" in res.output
    assert "se crearía" in res.output
    assert "guárdalo para la reversa" in res.output
    assert "3 fila(s)" in res.output
    assert "Dry-run: no se ejecutó nada." in res.output


@requires_dml
def test_corre_los_dos_sql_sin_invalidate_all_e_invalida_solo_titulatec():
    res, m = _invoca([], snapshots=[_antes(), _despues()])

    assert res.exit_code == 0, res.output
    assert m["ejecutar"].call_args_list == [
        call(str(_DIR / nombre), invalidate_authz=False)
        for nombre in _DML_AJUSTES_2026_10_FILES
    ]
    m["inv_app"].assert_called_once_with("titulatec")
    m["inv_all"].assert_not_called()
    assert m["snap"].call_count == 2
    assert f"{_ROL_TITULACION}: 22 → 16" in res.output
    assert f"{_ROL_OPERATIVO_ESCOLARES}: 2 → 4" in res.output
    assert "OK" in res.output


@requires_dml
def test_aborta_si_la_verificacion_reporta_un_problema():
    res, m = _invoca([], snapshots=[_antes(), _despues()],
                     verif=["titulatec_titulacion no quedó con exactamente sus 16 permisos"])

    assert res.exit_code != 0, "un delta a medias NO puede salir 0"
    assert "exactamente sus 16" in res.output
    # El SQL ya se aplicó: el caché se invalida igual, antes de verificar.
    m["inv_app"].assert_called_once_with("titulatec")


@requires_dml
def test_aborta_sin_escribir_si_falta_un_archivo(monkeypatch, tmp_path):
    (tmp_path / _DML_AJUSTES_2026_10_DIR).mkdir()
    (tmp_path / _DML_AJUSTES_2026_10_DIR / "01_liberados_permisos.sql").write_text("-- x")
    monkeypatch.setattr(f"{_MOD}.DML_TITULATEC", tmp_path)

    res, m = _invoca([], snapshots=[_antes(), _despues()])

    assert res.exit_code != 0
    m["ejecutar"].assert_not_called()
    m["inv_app"].assert_not_called()
    assert "02_requisito_constancia.sql" in res.output


# ---------------------------------------------------------------------------
# SQL de verdad, DENTRO del savepoint de `db_session` (se deshace al terminar).
# ---------------------------------------------------------------------------
def _ejecuta_delta(db_session):
    for nombre in _DML_AJUSTES_2026_10_FILES:
        with db_session.begin_nested():
            db_session.execute(text(_como_execute_sql_file(_leer(nombre))))


_BORRA_GRANTS = (
    "DELETE FROM core_role_permissions crp USING core_roles r, core_permissions p, core_apps a "
    " WHERE crp.role_id = r.id AND crp.perm_id = p.id AND p.app_id = a.id "
    "   AND a.key = 'titulatec' AND r.name = ANY(:roles) AND p.code = ANY(:codes)"
)


@requires_dml
def test_el_delta_converge_al_reparto_exacto_y_es_idempotente(
    db_session, patched_session_local, make_role, make_perms, make_cohort,
):
    """Arma en el savepoint el estado de ANTES con el rol de titulación
    EDITADO A MANO (los 22 de siempre menos `process.api.hold`, más
    `cohort.page.list`), SE sin Liberados, `admin` sin el resumido, una
    convocatoria con la etiqueta vieja y otra con una etiqueta propia; corre
    los dos `.sql` como los corre `execute_sql_file` y verifica con las mismas
    funciones que el comando. La segunda corrida no cambia nada."""
    from itcj2.apps.titulatec.models import CotejoRequirement

    make_perms(_PERMISOS_HANDOFF)
    for rol in (*_ROLES_AJUSTES_2026_10, "admin"):
        make_role(rol)
    db_session.execute(text(
        "DELETE FROM core_role_permissions crp USING core_roles r, core_permissions p, core_apps a "
        " WHERE crp.role_id = r.id AND crp.perm_id = p.id AND p.app_id = a.id "
        "   AND a.key = 'titulatec' AND r.name = :rol"), {"rol": _ROL_TITULACION})
    editado = (_VIEJOS_22 - {"titulatec.process.api.hold"}) | {"titulatec.cohort.page.list"}
    make_role(_ROL_TITULACION, sorted(editado))
    db_session.execute(text(_BORRA_GRANTS), {
        "roles": [_ROL_OPERATIVO_ESCOLARES, _ROL_JEFATURA_ESCOLARES],
        "codes": list(_PERMISOS_HANDOFF)})
    db_session.execute(text(_BORRA_GRANTS), {
        "roles": ["admin"], "codes": [_PERM_PROCESS_SUMMARY]})

    vieja = CotejoRequirement(cohort_id=make_cohort().id, label=_ETIQUETA_BIBLIOTECA_VIEJA,
                              icon="book", code="library_clearance",
                              auto_source="library_clearance", order_index=4)
    propia = CotejoRequirement(cohort_id=make_cohort().id, label="No adeudo (editada por SE)",
                               icon="book", code="library_clearance",
                               auto_source="library_clearance", order_index=4)
    db_session.add_all([vieja, propia])
    db_session.flush()

    antes = _snapshot_ajustes_2026_10()
    assert antes["perms"][_ROL_TITULACION] == editado
    assert not set(_PERMISOS_HANDOFF) & antes["perms"][_ROL_OPERATIVO_ESCOLARES]
    assert antes["admin_summary"] is False
    assert antes["etiquetas"].get(_ETIQUETA_BIBLIOTECA_VIEJA, 0) >= 1

    _ejecuta_delta(db_session)
    despues = _snapshot_ajustes_2026_10()

    assert _verify_ajustes_2026_10(antes, despues) == []
    assert despues["perms"][_ROL_TITULACION] == set(_PERMISOS_ROL_TITULACION)
    for rol in (_ROL_OPERATIVO_ESCOLARES, _ROL_JEFATURA_ESCOLARES):
        assert despues["perms"][rol] == antes["perms"][rol] | set(_PERMISOS_HANDOFF)
    assert despues["perms"][_ROL_TITULACIONES_DIV] == antes["perms"][_ROL_TITULACIONES_DIV]
    assert despues["existe_summary"] and despues["admin_summary"]
    db_session.refresh(vieja)
    db_session.refresh(propia)
    assert vieja.label == _ETIQUETA_BIBLIOTECA
    assert propia.label == "No adeudo (editada por SE)"

    _ejecuta_delta(db_session)
    otra_vez = _snapshot_ajustes_2026_10()
    assert otra_vez == despues
    assert _verify_ajustes_2026_10(despues, otra_vez) == []
