"""Contrato de layout de Citas de cotejo.

Decision del usuario del 2026-09-03: NADA tapa nada y NADA se encoge al abrir un
alumno. La regla que lo garantiza es que cada sub-vista declara su rejilla UNA
vez por breakpoint y ninguna clase de ESTADO la reescribe.

Lo que habia antes, medido en Chromium a 1280 px con el alumno 31 abierto:

    agenda            676 px  ->  340 px
    celda calendario  91.6    ->  43.6
    "Por agendar"     x=956,y=107  ->  x=264,y=634   (692 px y 527 px de salto)

y a 390 px la ficha (1204 px de alto) se insertaba ARRIBA, empujando agenda y
cola 1220 px hacia abajo. La regla culpable era `.tt-appt.has-detail`.

Este archivo existe para que eso no vuelva por descuido.
"""
import re
from pathlib import Path

import pytest

CSS = Path(__file__).resolve().parents[3] / "itcj2/apps/titulatec/static/css/titulatec.css"

# Selectores que dependen del ESTADO de la vista, no del breakpoint.
_ESTADO = re.compile(
    r"(\.has-detail\b|\.is-panel\b|\.has-[a-z-]+\b|\[data-[a-z-]*=[\"']?(abierto|open)\b)",
    re.I,
)
_REJILLA = re.compile(r"grid-template-(columns|areas|rows)")

SUBVISTAS = ("appt-agenda", "appt-attend", "appt-spaces")


def _reglas(texto):
    """[(selector, cuerpo)] de cada regla del archivo, sin comentarios."""
    limpio = re.sub(r"/\*.*?\*/", "", texto, flags=re.S)
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", limpio):
        yield m.group(1).strip(), m.group(2)


def test_ninguna_clase_de_estado_redefine_la_rejilla():
    culpables = [
        sel for sel, cuerpo in _reglas(CSS.read_text(encoding="utf-8"))
        if _ESTADO.search(sel) and _REJILLA.search(cuerpo)
    ]
    assert not culpables, (
        "Una clase de ESTADO redefine la rejilla, o sea que abrir algo cambia el "
        "tamano de otra cosa. Es exactamente lo que el rediseno vino a quitar.\n"
        + "\n".join("  " + c for c in culpables)
    )


@pytest.mark.parametrize("vista", SUBVISTAS)
def test_cada_subvista_declara_su_rejilla_con_areas_nombradas(vista):
    """Declarar solo `grid-template-columns` deja la colocacion al azar.

    `#appt-agenda` tiene CUATRO hijos (filtros, carril de dias, tablero, cola) y
    dos columnas: con auto-colocacion, el carril de dias -unica forma de cambiar
    de dia desde que murio el calendario mensual- cae en la pista de 320 px,
    donde caben 2.3 chips en un monitor de 1920.
    """
    decls = [c for sel, c in _reglas(CSS.read_text(encoding="utf-8")) if f"#{vista}" in sel]
    assert decls, f"#{vista} no declara ninguna rejilla en titulatec.css"
    assert any("grid-template-areas" in c for c in decls), (
        f"#{vista} declara columnas pero no areas: la auto-colocacion decide por ti"
    )
