"""Token del QR de la credencial: HMAC-SHA256, vida de 60 s, sin estado en BD.

Formato ``{ref}.{iat_base36}.{mac}``. ``ref`` es el aleatorio de
``credencial_photos`` (nunca el id ni el nº de control); ``mac`` son los primeros
16 bytes del HMAC en base64url sin relleno. La llave se deriva de ``SECRET_KEY``
con una etiqueta propia: la cookie de sesión firma sus JWT con ese mismo
``SECRET_KEY`` crudo, así que un MAC de aquí nunca sirve como firma allá.
"""
import base64
import hashlib
import hmac
import re
from dataclasses import dataclass
from datetime import datetime, timezone

TOKEN_TTL_SECONDS = 60
TOKEN_REFRESH_SECONDS = 30
_MAX_FUTURE_SECONDS = 5
_MAX_TOKEN_LEN = 80
_KEY_LABEL = b"credencial-qr-v1"
# Solo ASCII: hmac.compare_digest con str no ASCII lanza TypeError en vez de decir «no».
_REF = r"[A-Za-z0-9_-]{1,24}"
_TOKEN_RE = re.compile(rf"({_REF})\.([0-9a-z]{{1,8}})\.([A-Za-z0-9_-]{{22}})")
_B36 = "0123456789abcdefghijklmnopqrstuvwxyz"


class TokenInvalid(Exception):
    """Forma incorrecta o firma que no coincide."""


class TokenExpired(Exception):
    """Firma válida pero fuera de la ventana de 60 s (o emitido en el futuro)."""


@dataclass(frozen=True)
class TokenClaims:
    ref: str
    issued_at: datetime


def _b36(n: int) -> str:
    out = ""
    while True:
        n, r = divmod(n, 36)
        out = _B36[r] + out
        if not n:
            return out


def _key() -> bytes:
    from itcj2.config import get_settings
    return hmac.new(get_settings().SECRET_KEY.encode(), _KEY_LABEL, hashlib.sha256).digest()


def _mac(ref: str, iat_b36: str) -> str:
    digest = hmac.new(_key(), f"{ref}.{iat_b36}".encode(), hashlib.sha256).digest()[:16]
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


class CredentialTokenService:
    @staticmethod
    def issue(ref: str, now: datetime | None = None) -> str:
        if not re.fullmatch(_REF, ref or ""):
            raise ValueError("ref fuera del alfabeto del token")  # si no, el QR nunca verificaria
        iat = _b36(int((now or datetime.now(timezone.utc)).timestamp()))
        return f"{ref}.{iat}.{_mac(ref, iat)}"

    @staticmethod
    def parse(token: str, now: datetime | None = None) -> TokenClaims:
        if not isinstance(token, str) or len(token) > _MAX_TOKEN_LEN:
            raise TokenInvalid("longitud")
        m = _TOKEN_RE.fullmatch(token)
        if not m:
            raise TokenInvalid("forma")
        ref, iat_b36, mac = m.groups()
        if not hmac.compare_digest(_mac(ref, iat_b36).encode(), mac.encode()):
            raise TokenInvalid("firma")
        iat = int(iat_b36, 36)
        age = (now or datetime.now(timezone.utc)).timestamp() - iat
        if age > TOKEN_TTL_SECONDS or age < -_MAX_FUTURE_SECONDS:
            raise TokenExpired()
        return TokenClaims(ref=ref, issued_at=datetime.fromtimestamp(iat, timezone.utc))
