from functools import lru_cache

from werkzeug.security import check_password_hash, generate_password_hash

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


def verify_nip(nip: str, nip_hash: str) -> bool:
    try:
        return check_password_hash(nip_hash, nip)
    except Exception:
        return False


@lru_cache(maxsize=4096)
def is_default_password_hash(nip_hash: str) -> bool:
    """¿`nip_hash` es el de `DEFAULT_PASSWORD`? Memoizado por hash.

    `password_state` lo pregunta en cada carga de página del personal, y cada
    verificación es un scrypt de ~100 ms y ~32 MB (perf 2026-10-07: p50 127 ms
    en prod). El resultado depende SOLO del hash, que es único por usuario y
    por contraseña (lleva sal): cambiar la contraseña cambia la llave, así que
    no hay nada que invalidar. Es por proceso; la llave es el hash que ya vive
    en la BD, nunca el texto plano. `verify_nip` se resuelve en cada llamada
    (global del módulo) para que un parche en las pruebas lo alcance.
    """
    return verify_nip(DEFAULT_PASSWORD, nip_hash)
