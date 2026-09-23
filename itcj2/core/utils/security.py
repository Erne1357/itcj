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
