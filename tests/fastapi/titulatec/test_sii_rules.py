"""Motor de reglas de elegibilidad del SII (Tarea 2 del plan «Elegibilidad
automática contra el SII», spec 2026-09-25 §3.2).

Sin BD y sin driver: las reglas son TOML + `.sql` escritos en `tmp_path` (o las
sintéticas de `sii_fixtures/`) y el SII es un cliente de mentira que cuenta
las llamadas. Lo que se fija aquí:

- cada `criterion.kind` del vocabulario cerrado, en `all` y en `any`;
- `exists`/`not_exists` con 0 filas y el fail-closed de las comparaciones
  sin filas (una regla que no ve datos NUNCA cumple);
- placeholders del mensaje (faltante → `{columna}` literal, sin KeyError);
- el validador (TOML inválido, `UPDATE`, `;` intermedio, params fuera de la
  lista, rutas fuera de la carpeta, la credencial colada en reglas/hechos);
- un SII caído o una regla mal escrita dan `error`, jamás `apt`;
- el NIP no aparece en results, facts, identity, repr ni en el log.
"""
from __future__ import annotations

import logging
import textwrap
from decimal import Decimal
from pathlib import Path

import pytest

from itcj2.apps.titulatec.services.sii.errors import (
    SiiQueryError,
    SiiRulesError,
    SiiUnavailable,
)
from itcj2.apps.titulatec.services.sii.rules import RuleSet, Secret, Verdict

FIXTURES = Path(__file__).parent / "sii_fixtures"

NIP = "4321"


class _Stub:
    """SII de mentira: `{query_id: {control: [filas]}}` y un contador de
    llamadas para probar que cada consulta corre UNA vez por evaluación."""

    def __init__(self, data=None, errors=None):
        self.data = data or {}
        self.errors = errors or {}
        self.calls: list[tuple[str | None, str, tuple]] = []
        self.sensitive: list[str | None] = []  # consultas pedidas en modo sensible

    def query(self, sql, params, *, query_id=None, sensitive=False):
        self.calls.append((query_id, sql, tuple(params)))
        if sensitive:
            self.sensitive.append(query_id)
        if query_id in self.errors:
            raise self.errors[query_id]
        rows = self.data.get(query_id, {}).get(params[0], [])
        return [dict(r) for r in rows]

    def ping(self):
        return None

    def close(self):
        return None


def _write(tmp_path: Path, toml: str, queries: dict[str, str] | None = None) -> Path:
    base = tmp_path / "reglas"
    (base / "queries").mkdir(parents=True)
    (base / "rules.toml").write_text(textwrap.dedent(toml), encoding="utf-8")
    for name, sql in (queries or {}).items():
        (base / "queries" / name).write_text(textwrap.dedent(sql), encoding="utf-8")
    return base


_Q = "SELECT n, m, s, t FROM x WHERE ctl = ?\n"


def _one_rule(tmp_path, criterion: str, message="Falla {n}.") -> RuleSet:
    toml = f"""
        version = "t-1"
        [[query]]
        id = "q"
        file = "queries/q.sql"
        params = ["control_number"]
        [[rule]]
        id = "r"
        query = "q"
        criterion = {criterion}
        message = "{message}"
    """
    rs = RuleSet.load(_write(tmp_path, toml, {"q.sql": _Q}))
    assert rs.validate() == []
    return rs


_ROWS = [
    {"n": 5, "m": 5, "s": "A", "t": "S"},
    {"n": 10, "m": 20, "s": "B ", "t": "N"},
]


# ---------------------------------------------------------------------------
# Reglas sintéticas del repo
# ---------------------------------------------------------------------------
class TestFixturesDelRepo:
    def test_las_reglas_sinteticas_son_validas(self):
        rs = RuleSet.load(FIXTURES)
        assert rs.validate() == []
        assert rs.version == "test-2026-09-25.1"

    def test_apto_con_hechos_e_identidad_de_la_lista_blanca(self):
        rs = RuleSet.load(FIXTURES)
        stub = _Stub({
            "alumno": {"20110001": [{
                "no_de_control": "20110001", "nombre": "Ana", "apellido_paterno": "Pérez",
                "apellido_materno": "Ruiz", "carrera": "ISC", "anio_ingreso": 2020,
                "estatus": "EGRESADO", "creditos_aprobados": Decimal("260"),
                "creditos_carrera": 260, "servicio_social": "S", "residencia": "S",
                "curp": "XXXX000000HXXXXX00",
            }]},
            "adeudos": {},
        })
        v = rs.evaluate(stub, "20110001")

        assert isinstance(v, Verdict)
        assert v.status == "apt", v
        assert v.error is None
        assert v.rules_version == "test-2026-09-25.1"
        assert all(r.ok for r in v.results)
        assert [r.rule for r in v.results] == [
            "existe", "estatus", "creditos", "servicio_social", "residencia", "sin_adeudos",
        ]
        # Hechos = SOLO la lista blanca declarada (sin nombre, sin CURP).
        assert v.facts == {"estatus": "EGRESADO", "creditos_aprobados": 260,
                           "creditos_carrera": 260, "anio_ingreso": 2020}
        assert v.identity == {"first_name": "Ana", "last_name": "Pérez",
                              "middle_name": "Ruiz", "entry_year": 2020, "program": "ISC"}

    def test_cada_consulta_corre_una_sola_vez_y_con_parametro_enlazado(self):
        rs = RuleSet.load(FIXTURES)
        stub = _Stub({"alumno": {"20110001": [{
            "estatus": "EGRESADO", "creditos_aprobados": 200, "creditos_carrera": 260,
            "servicio_social": "S", "residencia": "N",
        }]}})
        v = rs.evaluate(stub, "20110001")
        assert v.status == "not_apt", v
        ids = [c[0] for c in stub.calls]
        assert sorted(ids) == ["adeudos", "alumno"], "cada [[query]] UNA vez"
        for _qid, sql, params in stub.calls:
            assert params == ("20110001",)
            assert "?" in sql and "20110001" not in sql, "nunca interpolado"

    def test_la_consulta_de_la_credencial_no_corre_al_evaluar(self):
        rs = RuleSet.load(FIXTURES)
        stub = _Stub()
        rs.evaluate(stub, "20110001")
        assert "nip" not in [c[0] for c in stub.calls]


# ---------------------------------------------------------------------------
# Vocabulario cerrado de criterios
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("criterion,all_ok,any_ok", [
    ('{ kind = "equals", column = "n", value = 5 }', False, True),
    ('{ kind = "not_equals", column = "n", value = 5 }', False, True),
    ('{ kind = "in", column = "n", value = [5, 7] }', False, True),
    ('{ kind = "not_in", column = "n", value = [5] }', False, True),
    ('{ kind = "gte", column = "n", value = 5 }', True, True),
    ('{ kind = "gte", column = "n", value = 10 }', False, True),
    ('{ kind = "lte", column = "n", value = 5 }', False, True),
    ('{ kind = "gte", column = "n", value_column = "m" }', False, True),
    ('{ kind = "lte", column = "n", value_column = "m" }', True, True),
    ('{ kind = "equals", column = "n", value_column = "m" }', False, True),
    ('{ kind = "truthy", column = "t" }', False, True),
    ('{ kind = "falsy", column = "t" }', False, True),
    ('{ kind = "equals", column = "s", value = "b" }', False, True),
    ('{ kind = "in", column = "s", value = ["a", "b"] }', True, True),
    ('{ kind = "equals", column = "n", value = "5" }', False, True),
])
def test_cada_kind_en_all_y_en_any(tmp_path, criterion, all_ok, any_ok):
    for mode, esperado in (("all", all_ok), ("any", any_ok)):
        crit = criterion.replace(" }", f', mode = "{mode}" }}')
        sub = tmp_path / mode
        sub.mkdir()
        rs = _one_rule(sub, crit)
        v = rs.evaluate(_Stub({"q": {"C1": _ROWS}}), "C1")
        assert v.results[0].ok is esperado, (crit, v)
        assert v.status == ("apt" if esperado else "not_apt")


def test_el_modo_por_defecto_es_all(tmp_path):
    rs = _one_rule(tmp_path, '{ kind = "equals", column = "n", value = 5 }')
    v = rs.evaluate(_Stub({"q": {"C1": _ROWS}}), "C1")
    assert v.results[0].ok is False


class TestExistsYFilasVacias:
    def test_exists_con_y_sin_filas(self, tmp_path):
        rs = _one_rule(tmp_path, '{ kind = "exists" }', message="No existe.")
        assert rs.evaluate(_Stub({"q": {"C1": _ROWS}}), "C1").status == "apt"
        v = rs.evaluate(_Stub(), "C1")
        assert v.status == "not_apt"
        assert v.results[0].message == "No existe."

    def test_not_exists_con_y_sin_filas(self, tmp_path):
        rs = _one_rule(tmp_path, '{ kind = "not_exists" }', message="Adeuda {s}.")
        assert rs.evaluate(_Stub(), "C1").status == "apt"
        v = rs.evaluate(_Stub({"q": {"C1": _ROWS}}), "C1")
        assert v.status == "not_apt"
        assert v.results[0].message == "Adeuda A."

    @pytest.mark.parametrize("mode", ["all", "any"])
    def test_una_comparacion_sin_filas_nunca_cumple(self, tmp_path, mode):
        """`all` sobre cero filas sería verdad vacía: aprobaría a quien el SII
        no conoce. Fail-closed."""
        rs = _one_rule(tmp_path, f'{{ kind = "gte", column = "n", value = 0, mode = "{mode}" }}')
        v = rs.evaluate(_Stub(), "C1")
        assert v.results[0].ok is False
        assert v.status == "not_apt"

    @pytest.mark.parametrize("kind", ["equals", "not_equals", "gte", "lte"])
    def test_null_nunca_cumple_una_comparacion(self, tmp_path, kind):
        rs = _one_rule(tmp_path, f'{{ kind = "{kind}", column = "n", value = 5 }}')
        v = rs.evaluate(_Stub({"q": {"C1": [{"n": None, "m": 1, "s": "", "t": None}]}}), "C1")
        assert v.results[0].ok is False

    def test_null_es_falsy(self, tmp_path):
        rs = _one_rule(tmp_path, '{ kind = "falsy", column = "t" }')
        v = rs.evaluate(_Stub({"q": {"C1": [{"n": 1, "m": 1, "s": "", "t": None}]}}), "C1")
        assert v.results[0].ok is True


# ---------------------------------------------------------------------------
# Mensajes
# ---------------------------------------------------------------------------
class TestPlaceholders:
    def test_se_llenan_con_la_primera_fila_y_el_faltante_queda_literal(self, tmp_path):
        rs = _one_rule(
            tmp_path, '{ kind = "gte", column = "n", value = 100 }',
            message="Lleva {n} de {m}; {no_existe} y {n.__class__}.",
        )
        v = rs.evaluate(_Stub({"q": {"C1": _ROWS}}), "C1")
        assert v.results[0].ok is False
        assert v.results[0].message == "Lleva 5 de 5; {no_existe} y {n.__class__}."
        assert any("no_existe" in w for w in v.warnings)

    def test_la_regla_que_cumple_lleva_ok_message_o_cumple(self, tmp_path):
        rs = _one_rule(tmp_path, '{ kind = "exists" }')
        v = rs.evaluate(_Stub({"q": {"C1": _ROWS}}), "C1")
        assert v.results[0].ok is True
        assert v.results[0].message == "Cumple."


# ---------------------------------------------------------------------------
# Errores: jamás aprueban
# ---------------------------------------------------------------------------
class TestErrorNuncaAprueba:
    def test_columna_inexistente_en_el_criterio_es_error(self, tmp_path):
        rs = _one_rule(tmp_path, '{ kind = "gte", column = "no_hay", value = 1 }')
        v = rs.evaluate(_Stub({"q": {"C1": _ROWS}}), "C1")
        assert v.status == "error"
        assert "no_hay" in v.error

    def test_tipos_no_comparables_es_error(self, tmp_path):
        rs = _one_rule(tmp_path, '{ kind = "gte", column = "s", value = 3 }')
        v = rs.evaluate(_Stub({"q": {"C1": _ROWS}}), "C1")
        assert v.status == "error"

    @pytest.mark.parametrize("exc", [SiiUnavailable("SII caído"), SiiQueryError("SQL roto")])
    def test_el_sii_falla_y_evaluate_no_lanza(self, exc):
        rs = RuleSet.load(FIXTURES)
        v = rs.evaluate(_Stub(errors={"alumno": exc}), "20110001")
        assert v.status == "error"
        assert str(exc) in v.error
        assert v.results == []

    def test_reglas_invalidas_dan_error_sin_consultar(self, tmp_path):
        base = _write(tmp_path, """
            version = "t"
            [[query]]
            id = "q"
            file = "queries/q.sql"
            params = ["control_number"]
            [[rule]]
            id = "r"
            query = "q"
            criterion = { kind = "magia" }
            message = "x"
        """, {"q.sql": _Q})
        stub = _Stub({"q": {"C1": _ROWS}})
        v = RuleSet.load(base).evaluate(stub, "C1")
        assert v.status == "error"
        assert "magia" in v.error
        assert stub.calls == []

    def test_param_curp_sin_curp_es_error(self, tmp_path):
        base = _write(tmp_path, """
            version = "t"
            [[query]]
            id = "q"
            file = "queries/q.sql"
            params = ["curp"]
            [[rule]]
            id = "r"
            query = "q"
            criterion = { kind = "exists" }
            message = "x"
        """, {"q.sql": _Q})
        rs = RuleSet.load(base)
        assert rs.evaluate(_Stub(), "C1").status == "error"
        stub = _Stub({"q": {"CURP1": _ROWS}})
        assert rs.evaluate(stub, "C1", curp="CURP1").status == "apt"
        assert stub.calls[0][2] == ("CURP1",)


# ---------------------------------------------------------------------------
# Validador
# ---------------------------------------------------------------------------
_BASE_TOML = """
    version = "t"
    [[query]]
    id = "q"
    file = "queries/q.sql"
    params = ["control_number"]
    [[rule]]
    id = "r"
    query = "q"
    criterion = { kind = "exists" }
    message = "x"
"""


def _errores(tmp_path, toml=_BASE_TOML, sql=_Q, extra=None):
    queries = {"q.sql": sql}
    queries.update(extra or {})
    return RuleSet.load(_write(tmp_path, toml, queries)).validate()


class TestValidador:
    def test_la_base_es_valida(self, tmp_path):
        assert _errores(tmp_path) == []

    def test_toml_invalido_lanza_al_cargar(self, tmp_path):
        base = _write(tmp_path, "version = \n[[rule", {"q.sql": _Q})
        with pytest.raises(SiiRulesError):
            RuleSet.load(base)

    def test_sin_rules_toml_lanza_al_cargar(self, tmp_path):
        with pytest.raises(SiiRulesError):
            RuleSet.load(tmp_path)

    @pytest.mark.parametrize("sql", [
        "UPDATE alumnos SET estatus = 'X' WHERE ctl = ?",
        "SELECT * FROM x WHERE ctl = ?; DELETE FROM x",
        "SELECT * FROM x WHERE ctl = ?; SELECT 1",
        "EXEC sp_who ?",
        "SELECT * INTO copia FROM x WHERE ctl = ?",
        "WITH a AS (SELECT 1 AS z) DELETE FROM x WHERE ctl = ?",
        "SELECT * FROM x WHERE ctl = ? /* ; */ ; DROP TABLE x",
        "",
    ])
    def test_sql_que_no_es_un_select(self, tmp_path, sql):
        assert _errores(tmp_path, sql=sql) != []

    @pytest.mark.parametrize("sql", [
        "SELECT * FROM x WHERE ctl = ?;",
        "  -- comentario con DELETE; y UPDATE\nSELECT a FROM x WHERE ctl = ?",
        "SELECT 'UPDATE; DROP' AS txt FROM x WHERE ctl = ?",
        "WITH a AS (SELECT ctl FROM x) SELECT * FROM a WHERE ctl = ?",
        "select updated_at, created_by FROM x WHERE ctl = ?",
    ])
    def test_sql_valido(self, tmp_path, sql):
        assert _errores(tmp_path, sql=sql) == []

    def test_placeholders_deben_coincidir_con_params(self, tmp_path):
        errs = _errores(tmp_path, sql="SELECT * FROM x WHERE ctl = ? AND y = ?")
        assert any("?" in e for e in errs)

    def test_param_no_permitido(self, tmp_path):
        errs = _errores(tmp_path, toml=_BASE_TOML.replace('["control_number"]', '["nip"]'))
        assert any("nip" in e for e in errs)

    def test_archivo_fuera_de_la_carpeta(self, tmp_path):
        (tmp_path / "fuera.sql").write_text(_Q, encoding="utf-8")
        errs = _errores(tmp_path, toml=_BASE_TOML.replace("queries/q.sql", "../fuera.sql"))
        assert errs != []

    def test_archivo_inexistente(self, tmp_path):
        errs = _errores(tmp_path, toml=_BASE_TOML.replace("queries/q.sql", "queries/no.sql"))
        assert any("no.sql" in e for e in errs)

    @pytest.mark.parametrize("cambio", [
        ('kind = "exists"', 'kind = "magia"'),
        ('kind = "exists"', 'kind = "gte", column = "n"'),                  # sin value
        ('kind = "exists"', 'kind = "gte", column = "n", value = 1, value_column = "m"'),
        ('kind = "exists"', 'kind = "equals", value = 1'),                   # sin column
        ('kind = "exists"', 'kind = "in", column = "n", value = 1'),         # no es lista
        ('kind = "exists"', 'kind = "gte", column = "n", value = 1, mode = "most"'),
        ('kind = "exists"', 'kind = "exists", sobra = 1'),
        ('query = "q"\ncriterion', 'query = "otra"\ncriterion'),
        ('message = "x"', 'mesage = "x"'),
        ('version = "t"', ''),
    ])
    def test_reglas_mal_escritas(self, tmp_path, cambio):
        toml = textwrap.dedent(_BASE_TOML).replace(*cambio)
        assert _errores(tmp_path, toml=toml) != [], cambio

    def test_sin_reglas(self, tmp_path):
        toml = textwrap.dedent(_BASE_TOML).split("[[rule]]")[0]
        assert _errores(tmp_path, toml=toml) != []

    def test_ids_duplicados(self, tmp_path):
        toml = textwrap.dedent(_BASE_TOML) + textwrap.dedent("""
            [[rule]]
            id = "r"
            query = "q"
            criterion = { kind = "exists" }
            message = "y"
        """)
        assert any("duplicad" in e and "'r'" in e for e in _errores(tmp_path, toml=toml))

    def test_la_consulta_de_la_credencial_no_puede_alimentar_reglas_ni_hechos(self, tmp_path):
        toml = textwrap.dedent(_BASE_TOML) + textwrap.dedent("""
            [credential]
            query = "q"
            column = "nip"
        """)
        assert _errores(tmp_path, toml=toml) != []

    def test_la_columna_de_la_credencial_no_puede_ser_un_hecho(self, tmp_path):
        toml = textwrap.dedent(_BASE_TOML) + textwrap.dedent("""
            [[query]]
            id = "nipq"
            file = "queries/nip.sql"
            params = ["control_number"]
            [credential]
            query = "nipq"
            column = "nip"
            [facts]
            query = "q"
            columns = ["n", "nip"]
        """)
        errs = _errores(tmp_path, toml=toml,
                        extra={"nip.sql": "SELECT nip FROM n WHERE ctl = ?"})
        assert any("nip" in e for e in errs)


# ---------------------------------------------------------------------------
# Credencial (NIP del SII)
# ---------------------------------------------------------------------------
def _stub_con_nip():
    return _Stub({
        "alumno": {"20110001": [{"estatus": "EGRESADO", "creditos_aprobados": 260,
                                 "creditos_carrera": 260, "servicio_social": "S",
                                 "residencia": "S", "nip": NIP}]},
        "nip": {"20110001": [{"nip": NIP}]},
    })


class TestCredencial:
    def test_secret_se_enmascara(self):
        s = Secret(NIP)
        assert s.reveal() == NIP
        assert repr(s) == "****"
        assert str(s) == "****"
        assert f"{s}" == "****"
        assert NIP not in repr([s, {"k": s}])

    def test_fetch_credential_devuelve_secret(self):
        rs = RuleSet.load(FIXTURES)
        stub = _stub_con_nip()
        s = rs.fetch_credential(stub, "20110001")
        assert isinstance(s, Secret)
        assert s.reveal() == NIP
        assert [c[0] for c in stub.calls] == ["nip"]

    def test_sin_filas_o_sin_seccion_es_none(self, tmp_path):
        rs = RuleSet.load(FIXTURES)
        assert rs.fetch_credential(_Stub(), "20110001") is None
        assert rs.fetch_credential(_Stub({"nip": {"C": [{"nip": "  "}]}}), "C") is None
        sin = _one_rule(tmp_path, '{ kind = "exists" }')
        assert sin.fetch_credential(_Stub(), "C1") is None

    def test_un_sii_caido_al_pedir_el_nip_se_propaga(self):
        rs = RuleSet.load(FIXTURES)
        with pytest.raises(SiiUnavailable):
            rs.fetch_credential(_Stub(errors={"nip": SiiUnavailable("x")}), "20110001")

    def test_la_consulta_de_la_credencial_va_en_modo_sensible(self):
        """El cliente, en modo sensible, no pone el detalle del driver (que
        puede traer el valor de la fila) en el log ni en la excepción."""
        rs = RuleSet.load(FIXTURES)
        stub = _stub_con_nip()
        rs.evaluate(stub, "20110001")
        assert stub.sensitive == [], "evaluar no toca la credencial"
        rs.fetch_credential(stub, "20110001")
        assert stub.sensitive == ["nip"]

    def test_columna_de_la_credencial_que_no_viene_es_error_de_reglas(self, caplog):
        """`[credential] column = "nip"` pero la consulta devuelve NIP_ALUMNO:
        es un error de configuración, NO «el SII no da NIP» (eso es 0 filas o
        NULL). Tragarlo haría que todo alumno sin cuenta quedara «sin NIP»."""
        caplog.set_level(logging.DEBUG)
        rs = RuleSet.load(FIXTURES)
        stub = _Stub({"nip": {"20110001": [{"NIP_ALUMNO": NIP}]}})
        with pytest.raises(SiiRulesError) as ei:
            rs.fetch_credential(stub, "20110001")
        msg = str(ei.value)
        assert "'nip'" in msg and "nip_alumno" in msg
        assert NIP not in " ".join([msg, repr(ei.value), caplog.text])

    def test_columna_presente_pero_nula_sigue_siendo_sin_nip(self):
        rs = RuleSet.load(FIXTURES)
        assert rs.fetch_credential(_Stub({"nip": {"C": [{"NIP": None}]}}), "C") is None

    def test_el_nip_no_aparece_en_ningun_lado(self, caplog):
        caplog.set_level(logging.DEBUG)
        rs = RuleSet.load(FIXTURES)
        stub = _stub_con_nip()
        v = rs.evaluate(stub, "20110001")
        s = rs.fetch_credential(stub, "20110001")
        assert s.reveal() == NIP
        visible = " ".join([
            repr(v), str(v), repr(v.results), repr(v.facts), repr(v.identity),
            repr(s), str(s), repr(rs), caplog.text,
        ])
        assert NIP not in visible
