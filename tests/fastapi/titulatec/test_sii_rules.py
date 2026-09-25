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

    @pytest.mark.parametrize("kind", ["truthy", "falsy"])
    def test_null_no_cumple_ni_truthy_ni_falsy(self, tmp_path, kind):
        """Revisión final (spec §8): NULL no es «falso», es «no se sabe». Como
        toda comparación, no cumple (fail-closed) — antes `falsy` sobre NULL
        cumplía y aprobaba sin dato."""
        rs = _one_rule(tmp_path, f'{{ kind = "{kind}", column = "t" }}')
        v = rs.evaluate(_Stub({"q": {"C1": [{"n": 1, "m": 1, "s": "", "t": None}]}}), "C1")
        assert v.status == "not_apt"
        assert v.results[0].ok is False


# ---------------------------------------------------------------------------
# truthy / falsy estrictos (revisión final C4, spec §8)
# ---------------------------------------------------------------------------
class TestTruthyEstricto:
    """Solo bool, 0/1 y un conjunto CERRADO de textos. Cualquier otro valor es
    error de la regla: «NO ACREDITADO» ya no cuenta como verdadero."""

    @pytest.mark.parametrize("valor", [
        True, 1, Decimal("1"), "1", "S", "si", "SI", "SÍ", "sí", "Y", "yes", "T",
        "true", "TRUE", "V", "verdadero", " Verdadero ",
    ])
    def test_valores_verdaderos(self, tmp_path, valor):
        rs = _one_rule(tmp_path, '{ kind = "truthy", column = "t" }')
        v = rs.evaluate(_Stub({"q": {"C1": [{"n": 1, "m": 1, "s": "", "t": valor}]}}), "C1")
        assert v.status == "apt", (valor, v)

    @pytest.mark.parametrize("valor", [
        False, 0, Decimal("0"), "0", "N", "no", "NO", "F", "false", "FALSO", "falso",
    ])
    def test_valores_falsos(self, tmp_path, valor):
        rs = _one_rule(tmp_path, '{ kind = "falsy", column = "t" }')
        v = rs.evaluate(_Stub({"q": {"C1": [{"n": 1, "m": 1, "s": "", "t": valor}]}}), "C1")
        assert v.status == "apt", (valor, v)
        rs2 = _one_rule(tmp_path / "t", '{ kind = "truthy", column = "t" }')
        v2 = rs2.evaluate(_Stub({"q": {"C1": [{"n": 1, "m": 1, "s": "", "t": valor}]}}), "C1")
        assert v2.status == "not_apt", (valor, v2)

    @pytest.mark.parametrize("valor", [
        "NO ACREDITADO", "NO LIBERADO", "PENDIENTE", "EN TRÁMITE", "SIN LIBERAR", "-",
        "", "X", 2, -1, Decimal("0.5"), 1.5,
    ])
    @pytest.mark.parametrize("kind", ["truthy", "falsy"])
    def test_cualquier_otro_valor_es_error_de_la_regla(self, tmp_path, kind, valor):
        rs = _one_rule(tmp_path, f'{{ kind = "{kind}", column = "t" }}')
        v = rs.evaluate(_Stub({"q": {"C1": [{"n": 1, "m": 1, "s": "", "t": valor}]}}), "C1")
        assert v.status == "error", (valor, v)
        assert "'t'" in v.error and "r" in v.error

    def test_equals_booleano_tambien_es_estricto(self, tmp_path):
        """`equals value = true` compara con la misma regla: «NO ACREDITADO»
        contra `true` es error, no «verdadero»."""
        rs = _one_rule(tmp_path, '{ kind = "equals", column = "t", value = true }')
        v = rs.evaluate(_Stub({"q": {"C1": [{"n": 1, "m": 1, "s": "", "t": "NO ACREDITADO"}]}}),
                        "C1")
        assert v.status == "error", v
        ok = rs.evaluate(_Stub({"q": {"C1": [{"n": 1, "m": 1, "s": "", "t": "S"}]}}), "C1")
        assert ok.status == "apt"


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

    def test_curp_ya_no_es_un_parametro_permitido(self, tmp_path):
        """Revisión final (spec §8): el formulario no captura CURP, así que
        `curp` nunca llegaba y solo dejaba reglas que fallarían siempre."""
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
        assert any("curp" in e for e in rs.validate())
        stub = _Stub({"q": {"C1": _ROWS}})
        assert rs.evaluate(stub, "C1").status == "error"
        assert stub.calls == []


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
        # Revisión final (spec §8): verbos de ASE y una segunda sentencia SIN `;`
        # (T-SQL no la necesita).
        "SELECT a FROM x WHERE ctl = ? SELECT b FROM y",
        "SELECT a FROM x WHERE ctl = ?\nSELECT b FROM y",
        "WITH a AS (SELECT ctl FROM x) SELECT * FROM a WHERE ctl = ? SELECT 1",
        "SELECT a FROM x WHERE ctl = ? sp_configure",
        "SELECT a FROM x WHERE ctl = ? xp_cmdshell",
        "SELECT a INTO #tmp FROM x WHERE ctl = ?",
        "SELECT a FROM x WHERE ctl = ? WAITFOR DELAY '00:00:05'",
        "SELECT a FROM x WHERE ctl = ? DBCC traceon",
        "SELECT a FROM x WHERE ctl = ? DUMP DATABASE d TO 'x'",
    ])
    def test_sql_que_no_es_un_select(self, tmp_path, sql):
        assert _errores(tmp_path, sql=sql) != []

    @pytest.mark.parametrize("segunda", [
        "SETUSER 'dbo'",
        "PRINT 'x'",
        "RAISERROR 20001 'x'",
        "QUIESCE DATABASE t HOLD d",
        "REORG REBUILD x",
        "MOUNT DATABASE ALL FROM 'm'",
        "UNMOUNT DATABASE d TO 'm'",
        "ONLINE DATABASE d",
        "GOTO fin",
        "RETURN",
        "IF 1 = 1 PRINT 'x'",
        "WHILE 1 = 1 BREAK",
        "CONTINUE",
        "OPEN c",
        "FETCH c",
        "CLOSE c",
        "CONNECT TO srv",
        "DISCONNECT",
        "REMOVE JAVA PACKAGE p",
        "TRANSFER TABLE x TO 'f'",
        "REFRESH PRECOMPUTED RESULT SET prs",
    ])
    def test_una_segunda_sentencia_sin_punto_y_coma_con_cualquier_verbo(
        self, tmp_path, segunda,
    ):
        """Revisión de F1 (brief punto 7): T-SQL separa sentencias sin `;`, así
        que un segundo statement de nivel superior que NO empiece con SELECT
        (`… WHERE ctl = ? SETUSER 'dbo'`) también se rechaza, no solo un
        segundo SELECT."""
        sql = f"SELECT a FROM x WHERE ctl = ? {segunda}"
        errs = _errores(tmp_path / "misma", sql=sql)
        verbo = segunda.split()[0].upper()
        assert any(verbo in e for e in errs), (sql, errs)
        # En otra línea, y en minúsculas, igual.
        otra = f"SELECT a FROM x WHERE ctl = ?\n{segunda.lower()}"
        assert _errores(tmp_path / "otra", sql=otra) != []

    def test_una_columna_que_se_llama_como_un_verbo_va_entre_corchetes(self, tmp_path):
        sql = "SELECT [print], [online], [transfer] FROM x WHERE ctl = ?"
        assert _errores(tmp_path / "con", sql=sql) == []
        errs = _errores(tmp_path / "sin", sql="SELECT online FROM x WHERE ctl = ?")
        assert any("ONLINE" in e and "corchetes" in e for e in errs), errs

    @pytest.mark.parametrize("sql", [
        "SELECT * FROM x WHERE ctl = ?;",
        "  -- comentario con DELETE; y UPDATE\nSELECT a FROM x WHERE ctl = ?",
        "SELECT 'UPDATE; DROP' AS txt FROM x WHERE ctl = ?",
        "WITH a AS (SELECT ctl FROM x) SELECT * FROM a WHERE ctl = ?",
        "select updated_at, created_by FROM x WHERE ctl = ?",
        "SELECT a FROM x WHERE ctl = ? UNION SELECT a FROM y",
        "SELECT a FROM x WHERE ctl = ? UNION ALL SELECT a FROM y",
        "SELECT a FROM x WHERE ctl = ? EXCEPT SELECT a FROM y",
        "SELECT a FROM x WHERE ctl = ? INTERSECT SELECT a FROM y",
        "SELECT t.a FROM (SELECT a, ctl FROM x) t WHERE t.ctl = ?",
        "SELECT a FROM x WHERE ctl = ? AND EXISTS (SELECT 1 FROM y WHERE y.a = x.a)",
        # Una columna que empiece con sp_/xp_ se escribe entre corchetes.
        "SELECT [sp_total], [xp_nivel] FROM x WHERE ctl = ?",
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

    @pytest.mark.parametrize("crudo,esperado", [
        (123, "0123"), (Decimal("7"), "0007"), (4321, "4321"), ("0123", "0123"),
        # Columna FLOAT/REAL (revisión de F1): 427.0 no es «427.0».
        (427.0, "0427"), (7.0, "0007"), (Decimal("427.00"), "0427"),
    ])
    def test_un_nip_numerico_conserva_los_ceros_a_la_izquierda(self, crudo, esperado):
        """Si el SII guarda el NIP como número, «0123» llegaba como «123» y la
        cuenta no se podía crear (revisión final C13)."""
        rs = RuleSet.load(FIXTURES)
        s = rs.fetch_credential(_Stub({"nip": {"C": [{"nip": crudo}]}}), "C")
        assert s.reveal() == esperado

    @pytest.mark.parametrize("crudo", [427.5, Decimal("427.5"), float("nan"), float("inf")])
    def test_un_nip_numerico_con_decimales_no_se_trunca(self, crudo):
        """Solo se rellena un número ENTERO: 427.5 no se vuelve «0427» (sería
        otro NIP); queda con otro formato y la cuenta no se crea."""
        from itcj2.apps.titulatec.services.enrollment_request_service import nip_format_ok

        rs = RuleSet.load(FIXTURES)
        s = rs.fetch_credential(_Stub({"nip": {"C": [{"nip": crudo}]}}), "C")
        assert s is not None and not nip_format_ok(s.reveal())

    def test_varias_filas_con_nip_distinto_es_error_de_reglas(self, caplog):
        """Antes se tomaba la primera fila: un NIP al azar. Ahora es error de
        configuración, sin ningún valor en el mensaje ni en el log."""
        caplog.set_level(logging.DEBUG)
        rs = RuleSet.load(FIXTURES)
        stub = _Stub({"nip": {"C": [{"nip": "1111"}, {"nip": "2222"}]}})
        with pytest.raises(SiiRulesError) as ei:
            rs.fetch_credential(stub, "C")
        texto = " ".join([str(ei.value), repr(ei.value), caplog.text])
        assert "1111" not in texto and "2222" not in texto
        assert "varias filas" in str(ei.value)

    def test_varias_filas_con_el_mismo_nip_no_es_error(self):
        rs = RuleSet.load(FIXTURES)
        stub = _Stub({"nip": {"C": [{"nip": "1111"}, {"nip": 1111}, {"nip": None}]}})
        assert rs.fetch_credential(stub, "C").reveal() == "1111"

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


# ---------------------------------------------------------------------------
# Advertencias: `[identity]` es obligatoria para aprobar sola (revisión final C3)
# ---------------------------------------------------------------------------
class TestAdvertencias:
    def test_las_reglas_sinteticas_no_advierten(self):
        assert RuleSet.load(FIXTURES).advisories() == []

    def test_sin_identity_advierte_que_nada_se_aprueba_solo(self, tmp_path):
        rs = RuleSet.load(_write(tmp_path, _BASE_TOML, {"q.sql": _Q}))
        assert rs.validate() == [], "sigue siendo válida: es una advertencia"
        avisos = rs.advisories()
        assert len(avisos) == 1
        assert "[identity]" in avisos[0] and "first_name" in avisos[0]

    def test_identity_sin_apellido_paterno_advierte(self, tmp_path):
        toml = _BASE_TOML + """
            [identity]
            query = "q"
            columns = { first_name = "n", middle_name = "m" }
        """
        rs = RuleSet.load(_write(tmp_path, toml, {"q.sql": _Q}))
        assert rs.validate() == []
        avisos = rs.advisories()
        assert len(avisos) == 1 and "last_name" in avisos[0]
