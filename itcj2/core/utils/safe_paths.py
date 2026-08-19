"""Contención de rutas: garantiza que una ruta derivada de datos del usuario no
escape del directorio raíz al que pertenece.

Contexto (agosto 2026). La auditoría que siguió al incidente de
``instance/apps/`` — un escaneo automatizado creó ~80 directorios con nombres de
payload porque el callback OAuth pasaba el query param ``state`` crudo hasta un
``mkdir(parents=True)`` — encontró el mismo patrón en varios lugares más:

* ``os.path.join(raiz, parte_del_usuario)`` descarta ``raiz`` por completo si la
  parte del usuario es absoluta (``os.path.join("/a/b", "/etc/passwd")`` es
  ``"/etc/passwd"``). Es una trampa silenciosa: el código *parece* anclado.
* ``..`` en un parámetro de ruta de FastAPI declarado ``{x:path}`` llega tal cual;
  nginx hace ``proxy_pass`` sin normalizar.

Usa ``safe_join`` en TODA ruta cuyo último tramo venga de una petición HTTP, de
una columna JSON escrita por el cliente, o de un CSV importado.
"""
from __future__ import annotations

import os
from pathlib import Path


class UnsafePath(ValueError):
    """La ruta resultante cae fuera de la raíz permitida."""


def safe_join(root: str | os.PathLike, *parts: str) -> Path:
    """Une ``parts`` bajo ``root`` y verifica que el resultado siga dentro.

    Lanza :class:`UnsafePath` si algún tramo es absoluto, contiene ``..`` que
    escape, o si un symlink saca la ruta final de ``root``.

    La comparación se hace sobre rutas ya resueltas (``os.path.realpath``), así
    que también cubre el caso de un symlink plantado dentro del directorio de
    uploads.
    """
    root_real = Path(os.path.realpath(str(root)))

    candidate = Path(root_real)
    for part in parts:
        if part is None:
            raise UnsafePath("tramo de ruta nulo")
        part = str(part)
        # Rechazo explícito: os.path.join() con un tramo absoluto tira la raíz.
        if os.path.isabs(part) or (os.name == "nt" and ":" in part.split(os.sep)[0][:2]):
            raise UnsafePath(f"tramo absoluto no permitido: {part!r}")
        if "\x00" in part:
            raise UnsafePath("byte nulo en la ruta")
        candidate = candidate / part

    final = Path(os.path.realpath(str(candidate)))
    if final != root_real and root_real not in final.parents:
        raise UnsafePath(f"la ruta escapa de {root_real}: {'/'.join(map(str, parts))!r}")
    return final


def is_within(root: str | os.PathLike, target: str | os.PathLike) -> bool:
    """True si ``target`` (ya construida) cae dentro de ``root``. Sin excepciones."""
    root_real = Path(os.path.realpath(str(root)))
    final = Path(os.path.realpath(str(target)))
    return final == root_real or root_real in final.parents
