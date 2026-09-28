"""Comandos `titulatec sii-ping`, `sii-rules-validate` y `sii-check` (Tarea 2,
spec 2026-09-25 §3.4 y §7).

Corren con el SII FALSO y las reglas sintéticas de `sii_fixtures/` (parcheando
`SiiConfig`, nunca `get_settings`): en CI no hay `database/SII/` ni driver.
`sii-check` es un dry-run: imprime el veredicto por regla, hechos, identidad y
el estado del NIP (el valor ENMASCARADO); con `--cohort`, el botón que vería
Servicios Escolares. No escribe nada. `sii-sweep` con el SII sin configurar
avisa y sale en 0 (spec 2026-09-27 §A7, D11).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from itcj2.apps.titulatec.services.sii.client import SiiConfig
from itcj2.cli.titulatec import titulatec_cli

FIXTURES = Path(__file__).parent / "sii_fixtures"


@pytest.fixture()
def sii(monkeypatch):
    """SII falso + reglas sintéticas. Devuelve un setter para cambiar backend."""
    state = {"backend": "fake", "fake": FIXTURES / "fake_sii.json", "rules": FIXTURES}
    monkeypatch.setattr(SiiConfig, "backend", staticmethod(lambda: state["backend"]))
    monkeypatch.setattr(SiiConfig, "fake_file", staticmethod(lambda: Path(state["fake"])))
    monkeypatch.setattr(SiiConfig, "rules_dir", staticmethod(lambda: Path(state["rules"])))
    monkeypatch.setattr(SiiConfig, "odbc_connection_string", staticmethod(lambda: ""))
    return state


def _run(*args):
    return CliRunner().invoke(titulatec_cli, list(args))


class TestSiiRulesValidate:
    def test_reglas_validas(self, sii):
        res = _run("sii-rules-validate")
        assert res.exit_code == 0, res.output
        assert "test-2026-09-25.1" in res.output
        assert "6 reglas" in res.output and "3 consultas" in res.output
        assert "OK" in res.output

    def test_reglas_invalidas_con_dir(self, sii, tmp_path):
        (tmp_path / "queries").mkdir()
        (tmp_path / "queries" / "q.sql").write_text(
            "UPDATE x SET a = 1 WHERE c = ?", encoding="utf-8")
        (tmp_path / "rules.toml").write_text(
            'version = "t"\n[[query]]\nid = "q"\nfile = "queries/q.sql"\n'
            'params = ["control_number"]\n[[rule]]\nid = "r"\nquery = "q"\n'
            'criterion = { kind = "magia" }\nmessage = "x"\n', encoding="utf-8")
        res = _run("sii-rules-validate", "--dir", str(tmp_path))
        assert res.exit_code != 0
        assert "UPDATE" in res.output and "magia" in res.output

    def test_sin_identity_advierte_pero_sale_en_cero(self, sii, tmp_path):
        """Revisión final C3: sin `[identity]` con nombre y apellido el nombre
        no se compara con el formulario. Las reglas siguen siendo válidas: es
        una advertencia, y ya no habla de aprobarse sola (spec 2026-09-27)."""
        (tmp_path / "queries").mkdir()
        (tmp_path / "queries" / "q.sql").write_text(
            "SELECT a FROM x WHERE c = ?", encoding="utf-8")
        (tmp_path / "rules.toml").write_text(
            'version = "t"\n[[query]]\nid = "q"\nfile = "queries/q.sql"\n'
            'params = ["control_number"]\n[[rule]]\nid = "r"\nquery = "q"\n'
            'criterion = { kind = "exists" }\nmessage = "x"\n', encoding="utf-8")
        res = _run("sii-rules-validate", "--dir", str(tmp_path))
        assert res.exit_code == 0, res.output
        assert "Advertencia" in res.output and "[identity]" in res.output
        assert "cada aprobación pedirá confirmación" in res.output
        assert "No se pudo comparar el nombre con el SII" in res.output
        assert "aprobará sola" not in res.output

    def test_carpeta_sin_reglas(self, sii, tmp_path):
        sii["rules"] = tmp_path / "no_existe"
        res = _run("sii-rules-validate")
        assert res.exit_code != 0
        assert "rules.toml" in res.output


class TestSiiPing:
    def test_fake_ok(self, sii):
        res = _run("sii-ping")
        assert res.exit_code == 0, res.output
        assert "fake" in res.output and "OK" in res.output

    def test_disabled(self, sii):
        sii["backend"] = "disabled"
        res = _run("sii-ping")
        assert res.exit_code != 0
        assert "deshabilitada" in res.output

    def test_fake_sin_archivo(self, sii, tmp_path):
        sii["fake"] = tmp_path / "no.json"
        res = _run("sii-ping")
        assert res.exit_code != 0
        assert "no.json" in res.output


class TestSiiCheck:
    def test_apta_con_nip_enmascarado(self, sii):
        res = _run("sii-check", " 20110001 ")
        assert res.exit_code == 0, res.output
        out = res.output
        assert "APTA" in out and "NO APTA" not in out
        for rule in ("existe", "estatus", "creditos", "servicio_social", "residencia",
                     "sin_adeudos"):
            assert rule in out
        assert "Créditos completos (260)." in out
        assert "estatus" in out and "EGRESADO" in out          # hechos
        assert "first_name" in out and "Ana" in out             # identidad
        assert "NIP: disponible" in out and "****" in out
        assert "4321" not in out
        assert "ms" in out
        assert "test-2026-09-25.1" in out

    def test_no_apta_con_motivos(self, sii):
        res = _run("sii-check", "20110002")
        assert res.exit_code == 0, res.output
        assert "NO APTA" in res.output
        assert "Le faltan créditos: 200 de 260." in res.output
        assert "8765" not in res.output

    def test_apta_sin_nip(self, sii):
        res = _run("sii-check", "20110003")
        assert res.exit_code == 0, res.output
        assert "sin NIP" in res.output

    def test_error_sale_distinto_de_cero(self, sii):
        res = _run("sii-check", "20119999")
        assert res.exit_code != 0
        assert "ERROR" in res.output and "alumno" in res.output
        assert "NIP: sin revisar" in res.output, "con veredicto error no se pide el NIP"

    @pytest.mark.parametrize("respuesta,estado,sale", [
        ([{"nip": "4321"}], "disponible", 0),
        (None, "no tiene", 0),
        ([{"nip": "12AB"}], "formato inválido", 1),
        ({"error": "unavailable"}, "no se pudo leer", 1),
        ({"error": "query"}, "error de configuración", 1),
    ], ids=["available", "missing", "invalid", "unavailable", "error"])
    def test_imprime_el_estado_del_nip(self, sii, tmp_path, respuesta, estado, sale):
        """Spec 2026-09-27 §A7: el mismo estado que guardaría la consulta
        (`classify_sii_nip`), legible; el valor jamás. Sale 1 en los mismos
        casos que antes (el NIP no serviría para crear la cuenta)."""
        sii["fake"] = _fake_alumno(tmp_path, "99589001", respuesta)
        res = _run("sii-check", "99589001")
        assert res.exit_code == sale, res.output
        assert "Veredicto: APTA" in res.output
        assert f"NIP: {estado}" in res.output
        assert "4321" not in res.output and "12AB" not in res.output

    def test_disabled(self, sii):
        sii["backend"] = "disabled"
        res = _run("sii-check", "20110001")
        assert res.exit_code != 0
        assert "deshabilitada" in res.output

    def test_columna_del_nip_mal_escrita_no_pasa_en_verde(self, sii, tmp_path):
        """`[credential] column = "nip"` pero `nip.sql` devuelve NIP_ALUMNO:
        antes decía «sin NIP» y salía 0; es un error de configuración."""
        sii["fake"] = _fake_con_nip(tmp_path, [{"NIP_ALUMNO": "4321"}])
        res = _run("sii-check", "20110001")
        assert res.exit_code != 0, res.output
        assert "Veredicto: APTA" in res.output
        assert "no devuelve la columna" in res.output
        assert "sin NIP" not in res.output
        assert "4321" not in res.output

    def test_dice_si_el_nip_tiene_4_digitos_sin_mostrarlo(self, sii):
        """Revisión final C13: el formato se reporta, el valor jamás."""
        res = _run("sii-check", "20110001")
        assert res.exit_code == 0, res.output
        assert "4 dígitos: sí" in res.output
        assert "4321" not in res.output

    @pytest.mark.parametrize("nip", ["12AB", "123", "１２３４"])
    def test_un_nip_con_otro_formato_no_pasa_en_verde(self, sii, tmp_path, nip):
        sii["fake"] = _fake_con_nip(tmp_path, [{"nip": nip}])
        res = _run("sii-check", "20110001")
        assert res.exit_code != 0, res.output
        assert "4 dígitos: no" in res.output
        assert nip not in res.output

    def test_consulta_del_nip_fallida_no_pasa_en_verde(self, sii, tmp_path):
        sii["fake"] = _fake_con_nip(tmp_path, {"error": "query"})
        res = _run("sii-check", "20110001")
        assert res.exit_code != 0, res.output
        assert "no se pudo consultar" in res.output


def _fake_con_nip(tmp_path, entry) -> Path:
    """El SII falso de las fixtures con otra respuesta de `nip` para 20110001."""
    data = json.loads((FIXTURES / "fake_sii.json").read_text(encoding="utf-8"))
    data["queries"]["nip"]["20110001"] = entry
    path = tmp_path / "fake_sii.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _fake_alumno(tmp_path, control, nip) -> Path:
    """El SII falso de las fixtures más `control` (copia de la fila apta de
    20110001) con esa respuesta de `nip` (`None` = el SII no tiene NIP).
    Controles `9958xxxx`: «¿tiene cuenta?» se decide contra `core_users` y los
    `2011xxxx` podrían existir en la BD de dev."""
    data = json.loads((FIXTURES / "fake_sii.json").read_text(encoding="utf-8"))
    fila = dict(data["queries"]["alumno"]["20110001"][0], no_de_control=control)
    data["queries"]["alumno"][control] = [fila]
    if nip is not None:
        data["queries"]["nip"][control] = nip
    path = tmp_path / "fake_sii.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


class TestSiiCheckConConvocatoria:
    """Spec 2026-09-27 §A7: con `--cohort`, lo que vería Servicios Escolares
    en «Por revisar»: el botón que se le ofrecería según «¿tiene cuenta?»
    (contra `core_users`, como al aprobar) y el estado del NIP. Nada se
    aprueba solo, así que no hay «automática» que anunciar."""

    @pytest.mark.parametrize("nip,con_cuenta,boton,sale", [
        ([{"nip": "4321"}], False, "Aprobar y dar acceso", 0),
        (None, False, "Aprobar y pasar a Accesos", 0),
        ([{"nip": "12AB"}], False, "Aprobar y pasar a Accesos", 1),
        ({"error": "unavailable"}, False, "Aprobar y pasar a Accesos", 1),
        ([{"nip": "4321"}], True, "Aprobar y enviar liga", 0),
        (None, True, "Aprobar y enviar liga", 0),
    ], ids=["available", "missing", "invalid", "unavailable", "cuenta_con_nip",
            "cuenta_sin_nip"])
    def test_dice_el_boton_que_veria_servicios_escolares(
            self, sii, tmp_path, patched_session_local, make_cohort, make_user,
            nip, con_cuenta, boton, sale):
        control = "99589002"
        sii["fake"] = _fake_alumno(tmp_path, control, nip)
        if con_cuenta:
            make_user(control_number=control)
        cohort = make_cohort(name="Convocatoria SII prueba", status="open")

        res = _run("sii-check", control, "--cohort", str(cohort.id))

        assert res.exit_code == sale, res.output
        assert "Convocatoria SII prueba" in res.output
        assert f"Servicios Escolares vería: {boton}" in res.output
        assert "automátic" not in res.output
        assert "4321" not in res.output and "12AB" not in res.output

    @pytest.mark.parametrize("control,estado", [
        ("20110002", "open"),      # no apta: la decide SE igual
        ("20110001", "closed"),    # convocatoria cerrada: se sigue viendo
    ])
    def test_cualquier_veredicto_llega_a_servicios_escolares(
            self, sii, patched_session_local, make_cohort, control, estado):
        cohort = make_cohort(name="Convocatoria SII prueba", status=estado)
        res = _run("sii-check", control, "--cohort", str(cohort.id))
        assert res.exit_code == 0, res.output
        assert f"(id {cohort.id}, {estado})" in res.output
        assert "Servicios Escolares vería: Aprobar y" in res.output
        assert "automátic" not in res.output

    def test_con_veredicto_error_sigue_siendo_aprobable(
            self, sii, tmp_path, patched_session_local, make_cohort):
        """Review Focus 1: el SII con error no deja la fila sin botón."""
        sii["fake"] = tmp_path / "fake_sii.json"
        sii["fake"].write_text(json.dumps({"queries": {
            "alumno": {"99589003": {"error": "unavailable"}}, "adeudos": {}, "nip": {}}}),
            encoding="utf-8")
        cohort = make_cohort(status="open")
        res = _run("sii-check", "99589003", "--cohort", str(cohort.id))
        assert res.exit_code != 0
        assert "Veredicto: ERROR" in res.output and "NIP: sin revisar" in res.output
        assert "Servicios Escolares vería: Aprobar y pasar a Accesos" in res.output

    def test_un_control_con_formato_invalido_no_busca_la_cuenta(
            self, sii, tmp_path, patched_session_local, make_cohort, make_user):
        """Mismo corte que `check()` y la aprobación: un control fuera de
        `CONTROL_NUMBER_RE` no se busca en `core_users`, cuenta como sin
        cuenta aunque exista un usuario con ese texto (p. ej. un legado)."""
        control = "9958904"          # 7 dígitos
        sii["fake"] = _fake_alumno(tmp_path, control, None)
        make_user(control_number=control)
        cohort = make_cohort(status="open")

        res = _run("sii-check", control, "--cohort", str(cohort.id))

        assert "Cuenta: no" in res.output, res.output
        assert "Servicios Escolares vería: Aprobar y pasar a Accesos" in res.output

    def test_convocatoria_inexistente(self, sii, patched_session_local):
        res = _run("sii-check", "20110001", "--cohort", "999999999")
        assert res.exit_code != 0
        assert "999999999" in res.output


class TestSiiSweepReconsultarErrores:
    """Revisión final C12: tras corregir la configuración, las consultas en
    error (reintentables o no) y las colgadas se reconsultan en bloque.

    `modo_sii` vive en conftest.py (Tarea 1: una sola copia compartida en vez
    de 6 duplicadas por archivo)."""

    def test_encola_y_dice_cuantas(self, sii, modo_sii, patched_session_local,
                                   monkeypatch):
        from itcj2.apps.titulatec.services.eligibility_service import EligibilityService

        llamadas = []

        def _recheck(db, *, cohort_id=None, now=None):
            llamadas.append(cohort_id)
            return {"queued": 4, "failed": 1}

        monkeypatch.setattr(EligibilityService, "recheck_errors", staticmethod(_recheck))
        res = _run("sii-sweep", "--reconsultar-errores", "--cohort", "7")
        assert res.exit_code == 0, res.output
        assert llamadas == [7]
        assert "4" in res.output and "reconsulta" in res.output.lower()
        assert "1" in res.output and "no se pudo" in res.output.lower()

    def test_fuera_del_modo_sii_no_hace_nada(self, sii, patched_session_local,
                                            monkeypatch):
        from itcj2.apps.titulatec.services.eligibility_service import EligibilityService

        monkeypatch.setattr(EligibilityService, "recheck_errors",
                            staticmethod(lambda *a, **k: pytest.fail("no debió correr")))
        res = _run("sii-sweep", "--reconsultar-errores")
        assert res.exit_code == 0, res.output
        assert "no 'sii'" in res.output


class TestSiiSweepSinSiiConfigurado:
    """Spec 2026-09-27 D11 (el caso de producción hoy): con el backend
    `disabled` el barrido no consulta ni encola nada; lo dice y sale en 0 (la
    periódica y un operador que lo corra a mano no deben verlo como falla)."""

    @pytest.mark.parametrize("extra", [(), ("--reconsultar-errores",)],
                             ids=["barrido", "reconsultar_errores"])
    def test_avisa_y_sale_en_cero(self, sii, modo_sii, patched_session_local, extra):
        sii["backend"] = "disabled"
        # Acotado a una convocatoria inexistente: si el corte faltara, no
        # barrería la BD de dev entera.
        res = _run("sii-sweep", "--cohort", "999999999", *extra)
        assert res.exit_code == 0, res.output
        assert ("El SII no está configurado (TITULATEC_SII_BACKEND=disabled); "
                "no se consultó nada.") in res.output
        assert "Consultadas" not in res.output and "Reconsultas" not in res.output
