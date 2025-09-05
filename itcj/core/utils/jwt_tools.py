# utils/jwt_tools.py
import os, time, jwt
from flask import current_app

SECRET = os.getenv("SECRET_KEY", "dev")
ALGO = "HS256"

def encode_jwt(payload: dict, hours: int = 12) -> str:
    now = int(time.time())
    body = {**payload, "iat": now, "exp": now + hours * 3600}
    token = jwt.encode(body, SECRET, algorithm=ALGO)
    return token.decode("utf-8") if isinstance(token, bytes) else token

def decode_jwt(token: str | None):
    if not token:
        return None
    try:
        # leeway para pequeños desfases de reloj
        return jwt.decode(
            token,
            SECRET,
            algorithms=[ALGO],
            options={"verify_aud": False},
            leeway=30,
        )
    except jwt.ExpiredSignatureError as e:
        current_app.logger.warning("JWT expired: %s", e)
    except jwt.InvalidSignatureError as e:
        current_app.logger.error("JWT bad signature: %s", e)
    except jwt.DecodeError as e:
        current_app.logger.error("JWT decode error: %s", e)
    except jwt.PyJWTError as e:
        current_app.logger.error("JWT generic error: %s", e)
    return None
