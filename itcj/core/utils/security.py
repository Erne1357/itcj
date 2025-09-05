from werkzeug.security import generate_password_hash, check_password_hash

def hash_nip(nip: str) -> str:
    return generate_password_hash(nip)  # pbkdf2:sha256 por defecto

def verify_nip(nip: str, nip_hash: str) -> bool:
    try:
        return check_password_hash(nip_hash, nip)
    except Exception:
        return False
