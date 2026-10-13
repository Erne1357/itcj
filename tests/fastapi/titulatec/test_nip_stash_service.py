"""`NipStashService`: NIPs precargados del SII, cifrados con Fernet.

El NIP nunca aparece en logs ni en mensajes de excepción (ERS:80-83): los
tests usan un NIP centinela y lo buscan en `caplog`.
"""
import logging

import pytest
from cryptography.fernet import Fernet

from itcj2.apps.titulatec.models import NipStash
from itcj2.apps.titulatec.services.nip_stash_service import NipStashService
from itcj2.models.base import Base

CENTINELA = "7391"


@pytest.fixture
def llave(monkeypatch):
    from itcj2.config import get_settings
    k = Fernet.generate_key().decode()
    monkeypatch.setattr(get_settings(), "TITULATEC_NIP_STASH_KEY", k)
    return k


@pytest.fixture
def sin_llave(monkeypatch):
    from itcj2.config import get_settings
    monkeypatch.setattr(get_settings(), "TITULATEC_NIP_STASH_KEY", None)


def test_la_tabla_esta_en_metadata():
    assert "titulatec_nip_stash" in Base.metadata.tables


def test_ida_y_vuelta_y_el_texto_en_bd_no_es_el_nip(db_session, llave):
    assert NipStashService.available() is True
    assert NipStashService.put(db_session, "21111134", CENTINELA, actor_id=None) is False
    db_session.flush()
    assert NipStashService.peek(db_session, "21111134") == CENTINELA
    fila = db_session.get(NipStash, "21111134")
    assert CENTINELA not in fila.nip_cipher
    assert fila.loaded_at is not None


def test_put_reemplaza(db_session, llave):
    NipStashService.put(db_session, "21111134", "1111", actor_id=None)
    assert NipStashService.put(db_session, "21111134", "2222", actor_id=None) is True
    assert NipStashService.peek(db_session, "21111134") == "2222"


@pytest.mark.parametrize("malo", ["123", "12345", "abcd", "１２３４", "", None])
def test_nip_invalido_levanta_value_error_sin_el_nip(db_session, llave, malo):
    with pytest.raises(ValueError) as exc:
        NipStashService.put(db_session, "21111134", malo, actor_id=None)
    if malo:
        assert malo not in str(exc.value)
    assert NipStashService.peek(db_session, "21111134") is None


def test_put_sin_llave_levanta_value_error(db_session, sin_llave):
    with pytest.raises(ValueError):
        NipStashService.put(db_session, "21111134", CENTINELA, actor_id=None)


def test_sin_llave_no_esta_disponible_y_peek_es_none(db_session, llave, monkeypatch):
    NipStashService.put(db_session, "21111134", CENTINELA, actor_id=None)
    from itcj2.config import get_settings
    monkeypatch.setattr(get_settings(), "TITULATEC_NIP_STASH_KEY", None)
    assert NipStashService.available() is False
    assert NipStashService.peek(db_session, "21111134") is None


def test_llave_distinta_peek_none_y_warning_sin_datos(db_session, llave, monkeypatch, caplog):
    NipStashService.put(db_session, "21111134", CENTINELA, actor_id=None)
    from itcj2.config import get_settings
    monkeypatch.setattr(get_settings(), "TITULATEC_NIP_STASH_KEY",
                        Fernet.generate_key().decode())
    with caplog.at_level(logging.DEBUG):
        assert NipStashService.peek(db_session, "21111134") is None
    avisos = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert avisos
    assert CENTINELA not in caplog.text
    assert "21111134" not in caplog.text


def test_peek_sin_fila_es_none(db_session, llave):
    assert NipStashService.peek(db_session, "99999999") is None


def test_discard(db_session, llave):
    NipStashService.put(db_session, "21111134", CENTINELA, actor_id=None)
    assert NipStashService.discard(db_session, "21111134") is True
    assert NipStashService.discard(db_session, "21111134") is False
    assert NipStashService.peek(db_session, "21111134") is None


def test_el_validador_rechaza_una_llave_mal_formada():
    from itcj2.config import Settings
    with pytest.raises(ValueError):
        Settings(_env_file=None, TITULATEC_NIP_STASH_KEY="no-es-una-llave-fernet")


def test_el_validador_acepta_llave_valida_y_ausente():
    from itcj2.config import Settings
    k = Fernet.generate_key().decode()
    assert Settings(_env_file=None, TITULATEC_NIP_STASH_KEY=k).TITULATEC_NIP_STASH_KEY == k
    assert Settings(_env_file=None, TITULATEC_NIP_STASH_KEY=None).TITULATEC_NIP_STASH_KEY is None
