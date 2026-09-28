"""Configuración del SII (Tarea 1 del plan «Elegibilidad automática contra el
SII», 2026-09-25): settings nuevos para el backend ODBC/fake/disabled y el
modo `sii` de `TITULATEC_ENROLLMENT_REVIEWER`.

Estos settings los leen SOLO métodos estáticos del servicio (Tarea 2+); aquí
solo se prueban defaults, validación de rangos y que el secreto del ODBC
jamás aparezca en un `repr(Settings())`.

Ver `docs/superpowers/specs/2026-09-25-titulatec-elegibilidad-sii-design.md`.
"""
from __future__ import annotations

import pytest


class TestDefaultsDelSii:
    def test_los_defaults_son_los_del_spec(self, monkeypatch):
        """`_env_file=None` + `delenv` de las ocho variables aísla el default
        real declarado en `Field(...)`/la asignación directa, igual que el
        patrón usado para `TITULATEC_ENROLLMENT_LINK_TTL_DAYS`."""
        from itcj2.config import Settings

        for var in (
            "TITULATEC_SII_BACKEND",
            "TITULATEC_SII_ODBC",
            "TITULATEC_SII_RULES_DIR",
            "TITULATEC_SII_FAKE_FILE",
            "TITULATEC_SII_CONNECT_TIMEOUT_S",
            "TITULATEC_SII_QUERY_TIMEOUT_S",
            "TITULATEC_SII_AUTO_APPROVE_DELAY_HOURS",
            "TITULATEC_SII_MAX_ATTEMPTS",
        ):
            monkeypatch.delenv(var, raising=False)

        s = Settings(_env_file=None)
        assert s.TITULATEC_SII_BACKEND == "disabled"
        assert s.TITULATEC_SII_ODBC.get_secret_value() == ""
        assert s.TITULATEC_SII_RULES_DIR == "database/SII/titulatec"
        assert s.TITULATEC_SII_FAKE_FILE == "database/SII/titulatec/fake_sii.json"
        assert s.TITULATEC_SII_CONNECT_TIMEOUT_S == 5
        assert s.TITULATEC_SII_QUERY_TIMEOUT_S == 10
        assert s.TITULATEC_SII_AUTO_APPROVE_DELAY_HOURS == 0
        assert s.TITULATEC_SII_MAX_ATTEMPTS == 5


class TestValidacionDelSii:
    def test_sii_backend_solo_admite_los_tres_valores(self):
        from pydantic import ValidationError
        from itcj2.config import Settings

        with pytest.raises(ValidationError):
            Settings(TITULATEC_SII_BACKEND="x")
        for valido in ("disabled", "fake", "odbc"):
            # `fake` solo fuera de producción (ver abajo): el entorno se fija.
            assert (Settings(TITULATEC_SII_BACKEND=valido, FLASK_ENV="development")
                    .TITULATEC_SII_BACKEND == valido)

    def test_el_sii_falso_no_arranca_en_produccion(self):
        """Revisión final (spec §8): con `fake` en producción cualquiera que
        edite el JSON decide quién es apto. Truena al arrancar."""
        from pydantic import ValidationError
        from itcj2.config import Settings

        with pytest.raises(ValidationError) as ei:
            Settings(TITULATEC_SII_BACKEND="fake", FLASK_ENV="production")
        assert "fake" in str(ei.value)
        for backend in ("disabled", "odbc"):
            assert (Settings(TITULATEC_SII_BACKEND=backend, FLASK_ENV="production")
                    .TITULATEC_SII_BACKEND == backend)

    def test_connect_timeout_va_de_1_a_60(self):
        from pydantic import ValidationError
        from itcj2.config import Settings

        for invalido in (0, -1, 61):
            with pytest.raises(ValidationError):
                Settings(TITULATEC_SII_CONNECT_TIMEOUT_S=invalido)
        for valido in (1, 5, 60):
            assert (Settings(TITULATEC_SII_CONNECT_TIMEOUT_S=valido)
                    .TITULATEC_SII_CONNECT_TIMEOUT_S == valido)

    def test_query_timeout_va_de_1_a_120(self):
        from pydantic import ValidationError
        from itcj2.config import Settings

        for invalido in (0, -1, 121):
            with pytest.raises(ValidationError):
                Settings(TITULATEC_SII_QUERY_TIMEOUT_S=invalido)
        for valido in (1, 10, 120):
            assert (Settings(TITULATEC_SII_QUERY_TIMEOUT_S=valido)
                    .TITULATEC_SII_QUERY_TIMEOUT_S == valido)

    def test_auto_approve_delay_va_de_0_a_168(self):
        from pydantic import ValidationError
        from itcj2.config import Settings

        for invalido in (-1, 169):
            with pytest.raises(ValidationError):
                Settings(TITULATEC_SII_AUTO_APPROVE_DELAY_HOURS=invalido,
                         TITULATEC_SII_VERDICT_MAX_AGE_HOURS=200)
        for valido in (0, 24, 168):
            # La edad máxima del veredicto tiene que superar la ventana
            # (`TestEdadMaximaDelVeredicto`).
            assert (Settings(TITULATEC_SII_AUTO_APPROVE_DELAY_HOURS=valido,
                             TITULATEC_SII_VERDICT_MAX_AGE_HOURS=valido + 1)
                    .TITULATEC_SII_AUTO_APPROVE_DELAY_HOURS == valido)

    def test_max_attempts_va_de_1_a_20(self):
        from pydantic import ValidationError
        from itcj2.config import Settings

        for invalido in (0, -1, 21):
            with pytest.raises(ValidationError):
                Settings(TITULATEC_SII_MAX_ATTEMPTS=invalido)
        for valido in (1, 5, 20):
            assert (Settings(TITULATEC_SII_MAX_ATTEMPTS=valido)
                    .TITULATEC_SII_MAX_ATTEMPTS == valido)


class TestEdadMaximaDelVeredicto:
    """Revisión final C5 (spec §8): un veredicto apto que terminó hace más de
    esto se reconsulta en vez de aprobar."""

    @pytest.mark.parametrize("delay,max_age", [(0, 0), (24, 24), (24, 10), (168, 24)])
    def test_tiene_que_superar_la_ventana_de_veto(self, delay, max_age):
        """La edad se cuenta desde que terminó la consulta (spec §8), y la
        aprobación solo llega al vencer la ventana: con max_age ≤ delay todo
        veredicto llegaría viejo y se reconsultaría sin fin. Truena al arrancar
        (revisión de F1)."""
        from pydantic import ValidationError
        from itcj2.config import Settings

        with pytest.raises(ValidationError) as ei:
            Settings(TITULATEC_SII_AUTO_APPROVE_DELAY_HOURS=delay,
                     TITULATEC_SII_VERDICT_MAX_AGE_HOURS=max_age)
        assert "TITULATEC_SII_VERDICT_MAX_AGE_HOURS" in str(ei.value)

    @pytest.mark.parametrize("delay,max_age", [(0, 1), (0, 24), (23, 24), (168, 169)])
    def test_mayor_que_la_ventana_si_arranca(self, delay, max_age):
        from itcj2.config import Settings

        s = Settings(TITULATEC_SII_AUTO_APPROVE_DELAY_HOURS=delay,
                     TITULATEC_SII_VERDICT_MAX_AGE_HOURS=max_age)
        assert s.TITULATEC_SII_VERDICT_MAX_AGE_HOURS == max_age

    def test_default_24_y_minimo_1(self, monkeypatch):
        from pydantic import ValidationError
        from itcj2.config import Settings

        monkeypatch.delenv("TITULATEC_SII_VERDICT_MAX_AGE_HOURS", raising=False)
        assert Settings(_env_file=None).TITULATEC_SII_VERDICT_MAX_AGE_HOURS == 24
        for invalido in (0, -1):
            with pytest.raises(ValidationError):
                Settings(TITULATEC_SII_VERDICT_MAX_AGE_HOURS=invalido)
        assert (Settings(TITULATEC_SII_VERDICT_MAX_AGE_HOURS=1)
                .TITULATEC_SII_VERDICT_MAX_AGE_HOURS == 1)

    def test_se_lee_por_metodo_estatico(self, monkeypatch):
        from itcj2.apps.titulatec.services.eligibility_service import EligibilityService
        from itcj2.config import get_settings

        monkeypatch.setattr(get_settings(), "TITULATEC_SII_VERDICT_MAX_AGE_HOURS", 7)
        assert EligibilityService.verdict_max_age_hours() == 7


class TestElRevisorGanaElModoSii:
    def test_el_revisor_admite_sii_ademas_de_los_dos_modos_previos(self):
        """El modo nuevo se SUMA a `school_services`/`computer_center`
        (D6, sin tocarlos): un typo sigue tronando al arrancar."""
        from pydantic import ValidationError
        from itcj2.config import Settings

        with pytest.raises(ValidationError):
            Settings(TITULATEC_ENROLLMENT_REVIEWER="x")
        for valido in ("school_services", "computer_center", "sii"):
            assert (Settings(TITULATEC_ENROLLMENT_REVIEWER=valido)
                    .TITULATEC_ENROLLMENT_REVIEWER == valido)

    def test_el_default_es_sii(self, monkeypatch):
        """D3: `sii` pasa a ser el flujo por omisión; `school_services` y
        `computer_center` quedan como respaldo, activables solo por variable de
        entorno. `_env_file=None` + `delenv` aísla el default declarado."""
        from itcj2.config import Settings

        monkeypatch.delenv("TITULATEC_ENROLLMENT_REVIEWER", raising=False)
        assert Settings(_env_file=None).TITULATEC_ENROLLMENT_REVIEWER == "sii"


class TestElSecretoNuncaSeAsoma:
    def test_titulatec_sii_odbc_no_aparece_en_repr_de_settings(self, monkeypatch):
        """El NIP/credenciales del SII viajan en la cadena ODBC: si el campo
        aparece en `repr(Settings())` (logs de arranque, tracebacks de
        validación, etc.) la cadena completa queda expuesta. `Field(repr=False)`
        lo saca del repr aunque el tipo siga siendo `SecretStr`."""
        from itcj2.config import Settings

        monkeypatch.setenv(
            "TITULATEC_SII_ODBC",
            "DRIVER=FreeTDS;SERVER=x;PWD=un-secreto-que-no-debe-salir",
        )
        texto = repr(Settings())
        assert "TITULATEC_SII_ODBC" not in texto
        assert "un-secreto-que-no-debe-salir" not in texto
