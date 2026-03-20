import logging
import os
import time

import jwt

logger = logging.getLogger(__name__)

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
        return jwt.decode(
            token,
            SECRET,
            algorithms=[ALGO],
            options={"verify_aud": False},
            leeway=30,
        )
    except jwt.ExpiredSignatureError as e:
        logger.warning("JWT expired: %s", e)
    except jwt.InvalidSignatureError as e:
        logger.error("JWT bad signature: %s", e)
    except jwt.DecodeError as e:
        logger.error("JWT decode error: %s", e)
    except jwt.PyJWTError as e:
        logger.error("JWT generic error: %s", e)
    return None
