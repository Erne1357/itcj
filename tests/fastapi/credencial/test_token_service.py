"""Token del QR de la credencial: firma HMAC, vida de 60 s, sin estado en BD."""
import base64
import hashlib
import hmac
from datetime import datetime, timedelta, timezone

import pytest

from itcj2.apps.credencial.services import token_service
from itcj2.apps.credencial.services.token_service import (
    TOKEN_REFRESH_SECONDS,
    TOKEN_TTL_SECONDS,
    CredentialTokenService as T,
    TokenExpired,
    TokenInvalid,
)
from itcj2.config import get_settings

T0 = datetime(2026, 11, 3, 18, 0, 0, tzinfo=timezone.utc)
REF = "Ab3_x-9QzKp2Lm0n"


def test_constants():
    assert (TOKEN_TTL_SECONDS, TOKEN_REFRESH_SECONDS) == (60, 30)


def test_roundtrip():
    tok = T.issue(REF, now=T0)
    claims = T.parse(tok, now=T0)
    assert claims.ref == REF
    assert claims.issued_at == T0
    assert len(tok) <= 80


def test_tampered_mac_invalid():
    ref, iat, mac = T.issue(REF, now=T0).rsplit(".", 2)
    bad = ("B" if mac[0] == "A" else "A") + mac[1:]
    with pytest.raises(TokenInvalid):
        T.parse(f"{ref}.{iat}.{bad}", now=T0)


def test_tampered_ref_invalid():
    _, iat, mac = T.issue(REF, now=T0).rsplit(".", 2)
    with pytest.raises(TokenInvalid):
        T.parse(f"Zz9_otroAlumno01.{iat}.{mac}", now=T0)


def test_tampered_iat_invalid():
    """Mover la hora de emisión hacia adelante (alargar la vida) rompe la firma."""
    ref, _, mac = T.issue(REF, now=T0).rsplit(".", 2)
    later = token_service._b36(int(T0.timestamp()) + 3600)
    with pytest.raises(TokenInvalid):
        T.parse(f"{ref}.{later}.{mac}", now=T0 + timedelta(seconds=3600))


def test_expired_after_61s():
    tok = T.issue(REF, now=T0)
    with pytest.raises(TokenExpired):
        T.parse(tok, now=T0 + timedelta(seconds=61))


def test_valid_at_59s():
    tok = T.issue(REF, now=T0)
    assert T.parse(tok, now=T0 + timedelta(seconds=59)).ref == REF


def test_future_iat_invalid():
    """Emitido más de 5 s en el futuro: no se acepta (TokenExpired por contrato)."""
    tok = T.issue(REF, now=T0 + timedelta(seconds=10))
    with pytest.raises(TokenExpired):
        T.parse(tok, now=T0)


def test_overlong_token_invalid(monkeypatch):
    """Más de 80 caracteres: el tope decide solo, antes de la regex y del MAC.

    La regex también acotaría la longitud; por eso se sustituyen las dos por algo
    que revienta: si el tope desaparece, este test falla."""
    class _BoomRe:
        def fullmatch(self, *a, **k):
            raise AssertionError("no debió evaluar la regex")

    def _boom(*a, **k):
        raise AssertionError("no debió calcular el MAC")

    monkeypatch.setattr(token_service, "_TOKEN_RE", _BoomRe())
    monkeypatch.setattr(token_service, "_mac", _boom)
    with pytest.raises(TokenInvalid):
        T.parse("A" * 81, now=T0)


@pytest.mark.parametrize("raw", [
    "", "sin-puntos", "a.b", "a..c", ".1a.mac",
    "ñandú.1a.AAAAAAAAAAAAAAAAAAAAAA",   # no ASCII: compare_digest reventaría
    "ref.+1a.AAAAAAAAAAAAAAAAAAAAAA",    # int() aceptaría el signo
    "ref.1_a.AAAAAAAAAAAAAAAAAAAAAA",    # int() aceptaría el guion bajo
    "ref.1a.AAAA",                        # MAC corto
])
def test_malformed_tokens_invalid(raw):
    with pytest.raises(TokenInvalid):
        T.parse(raw, now=T0)


def test_key_differs_from_jwt_secret(monkeypatch):
    tok = T.issue(REF, now=T0)
    settings = get_settings()

    monkeypatch.setattr(settings, "JWT_SECRET_KEY", "otro-secreto-jwt")
    assert T.parse(tok, now=T0).ref == REF

    # La llave del QR se deriva con etiqueta propia: nunca es el SECRET_KEY crudo
    # (con el que la cookie de sesión firma sus JWT).
    assert token_service._key() != settings.SECRET_KEY.encode()
    ref, iat, mac = tok.rsplit(".", 2)
    raw = hmac.new(settings.SECRET_KEY.encode(), f"{ref}.{iat}".encode(), hashlib.sha256).digest()[:16]
    assert mac != base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    monkeypatch.setattr(settings, "SECRET_KEY", "otro-secret-key")
    with pytest.raises(TokenInvalid):
        T.parse(tok, now=T0)


def test_issue_rejects_ref_outside_token_alphabet():
    """Un ref que parse() no aceptaría produciría un QR que nunca verifica."""
    with pytest.raises(ValueError):
        T.issue("ref.con.puntos", now=T0)
