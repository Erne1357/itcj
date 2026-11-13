"""Almacén de archivos de Prórrogas (plantillas, PDF y firmas) bajo ``PRORROGAS_UPLOAD_PATH``."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

from itcj2.config import get_settings
from itcj2.core.utils.safe_paths import safe_join


def _base() -> Path:
    return Path(get_settings().PRORROGAS_UPLOAD_PATH)


def abs_path(rel: str) -> Path:
    return safe_join(_base(), rel)


def write_atomic(rel: str, data: bytes) -> Path:
    path = abs_path(rel)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return path
