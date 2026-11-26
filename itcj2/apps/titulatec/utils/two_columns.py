"""Lector de archivos de dos columnas (`control` + un valor), sobre TEXTO.

Lo comparten la CLI (`cli/titulatec/_common._leer_dos_columnas`, que lee el
archivo del disco y traduce el `ValueError` a `ClickException`) y la carga por
archivo de la bandeja «Promedios» (spec 2026-11-26 §5). Sin BD ni E/S.
"""
from __future__ import annotations

import csv
import io
import unicodedata

CONTROL_HEADERS = {"control", "no_control", "numero_control", "numero_de_control",
                   "num_control", "n_control", "no._control"}


def _norm(h: str) -> str:
    sin = unicodedata.normalize("NFKD", h or "").encode("ascii", "ignore").decode()
    return sin.strip().lower().replace(" ", "_")


def _filas_csv(lector):
    """El lector de `csv`, pero un archivo roto (comillas sin cerrar, campo de más
    de 128 KB) sale como `ValueError` con texto de ventanilla y no como 500."""
    try:
        yield from lector
    except csv.Error as exc:
        raise ValueError("No se pudo leer el archivo como CSV: revisa que no haya "
                         "comillas sin cerrar.") from exc


def leer_dos_columnas(texto: str, valor: str, alias_valor: set[str], *,
                      estricto: bool = False) -> list[tuple[str, str]]:
    """Lee `(control, <valor>)` de un CSV/TXT con encabezado. Acepta BOM (Excel),
    `,` `;` o tabulador, y `no_control`/`numero_control` como encabezado del
    control. La celda del valor se deja TAL CUAL: validarla es del servicio.
    `ValueError` si falta una columna.

    `estricto`: una fila con MÁS celdas que el encabezado se devuelve con el
    valor roto a propósito (las celdas sobrantes pegadas con un espacio). Es lo
    que pasa con «85,5» sin comillas en un CSV separado por comas: sin esto se
    leería «85» y el «5» se perdería en silencio."""
    primera = texto.splitlines()[0] if texto.strip() else ""
    delim = max(("\t", ";", ","), key=primera.count)
    lector = _filas_csv(csv.reader(io.StringIO(texto), delimiter=delim))

    encabezado = [_norm(h) for h in next(lector, [])]
    i_control = next((i for i, h in enumerate(encabezado) if h in CONTROL_HEADERS), None)
    i_valor = next((i for i, h in enumerate(encabezado) if h in alias_valor), None)
    if i_control is None or i_valor is None:
        raise ValueError(
            f"El archivo necesita un encabezado con las columnas «control» y «{valor}» "
            "(también vale «no_control» o «numero_control»).")
    filas = []
    for r in lector:
        if not any((c or "").strip() for c in r):
            continue
        celda = r[i_valor] if i_valor < len(r) else ""
        if estricto and any((c or "").strip() for c in r[len(encabezado):]):
            celda = " ".join([celda, *r[len(encabezado):]])
        filas.append((r[i_control] if i_control < len(r) else "", celda))
    return filas
