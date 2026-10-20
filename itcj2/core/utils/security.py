import hashlib
import logging
from functools import lru_cache

from werkzeug.security import check_password_hash, generate_password_hash

from itcj2.observability.tracing import traced

logger = logging.getLogger(__name__)

# Contraseña que recibe toda cuenta recién dada de alta o restablecida por un
# administrador. Vive AQUÍ, junto a las funciones que la hashean y verifican,
# porque tenía dos copias literales (`core/api/users.py` y
# `core/api/users_admin.py`) y en cuanto alguien cambiara una, la otra seguiría
# creando cuentas con la vieja sin que nada fallara.
#
# `core/api/users.py::password_state` la usa para decidir `must_change`: quien
# tenga EXACTAMENTE esta contraseña recibe la pantalla de cambio obligatorio al
# entrar. Por eso restablecerla no deja una cuenta con credencial permanente
# conocida, sino una que se obliga a cambiarla.
DEFAULT_PASSWORD = "tecno#2K"


def hash_nip(nip: str) -> str:
    return generate_password_hash(nip)


# Un scrypt (~100 ms de CPU) era el hueco sin nombre de cada login y de cada
# fallo de caché de `password_state`. Sin atributos: ni el resultado ni nada
# del usuario (el login también verifica contra un hash ficticio).
@traced("auth.password_verify")
def verify_nip(nip: str, nip_hash: str) -> bool:
    try:
        return check_password_hash(nip_hash, nip)
    except Exception:
        return False


# Veredicto de `is_default_password_hash` compartido entre procesos. La llave es
# el sha256 del hash (nunca el hash ni el texto plano); el valor, "1" o "0".
# Vence a los 30 días: una contraseña cambiada deja una llave que nadie vuelve a
# pedir, y que no se acumule.
_SHARED_PREFIX = "pwdefault:v1"
_SHARED_TTL = 30 * 24 * 3600


def _shared_redis():
    """Cliente Redis síncrono compartido, o None (cada proceso calcula el suyo)."""
    try:
        from itcj2.core.utils.redis_conn import get_redis
        return get_redis()
    except Exception as exc:  # pragma: no cover - defensivo
        logger.warning("password default: no se pudo obtener Redis (%s)", exc)
        return None


@lru_cache(maxsize=4096)
def is_default_password_hash(nip_hash: str) -> bool:
    """¿`nip_hash` es el de `DEFAULT_PASSWORD`? Memoizado por hash.

    `password_state` lo pregunta en cada carga de página del personal, y cada
    verificación es un scrypt de ~100 ms y ~32 MB (perf 2026-10-07: p50 127 ms
    en prod). El resultado depende SOLO del hash, que es único por usuario y
    por contraseña (lleva sal): cambiar la contraseña cambia la llave, así que
    no hay nada que invalidar. La llave es el hash que ya vive en la BD, nunca
    el texto plano. `verify_nip` se resuelve en cada llamada (global del
    módulo) para que un parche en las pruebas lo alcance.

    Dos niveles (rendimiento 2026-10-14): este `lru_cache` por proceso y, detrás,
    Redis por el sha256 del hash. Solo con el del proceso, cada uno de los 4
    workers de cada color volvía a pagar el scrypt por usuario y cada deploy lo
    vaciaba (Tempo: ~35 `password-state` al día de ~130 ms). Redis caído o mudo
    = se calcula aquí, como antes.
    """
    llave = f"{_SHARED_PREFIX}:{hashlib.sha256(nip_hash.encode()).hexdigest()}"
    r = _shared_redis()
    if r is not None:
        try:
            guardado = r.get(llave)
            if guardado is not None:
                return guardado == "1"
        except Exception as exc:
            logger.warning("password default: Redis no respondió (%s); se calcula", exc)
            r = None

    es_por_omision = verify_nip(DEFAULT_PASSWORD, nip_hash)
    if r is not None:
        try:
            r.set(llave, "1" if es_por_omision else "0", ex=_SHARED_TTL)
        except Exception as exc:
            logger.warning("password default: no se guardó en Redis (%s)", exc)
    return es_por_omision
