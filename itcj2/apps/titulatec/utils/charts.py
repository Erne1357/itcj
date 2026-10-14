"""Geometria de graficas del tablero de reportes.

Puro: recibe numeros y devuelve porcentajes, puntos SVG y semanas de calendario
ya calculados, para que las plantillas solo pinten (sin aritmetica en Jinja).
"""
from __future__ import annotations

import math
from datetime import date, timedelta

_PASOS = (1, 2, 5, 10)


def _paso_bonito(crudo: float) -> float:
    """Menor paso 1/2/5 x 10^k que sea >= `crudo`."""
    exp = math.floor(math.log10(crudo))
    base = 10.0 ** exp
    for p in _PASOS:
        if p * base >= crudo * (1 - 1e-12):
            return p * base
    return 10.0 * base  # pragma: no cover - 10 siempre alcanza


def nice_ticks(vmax: float, n: int = 4) -> list[float]:
    """Marcas del eje: empieza en 0, el ultimo es >= `vmax`, paso 1/2/5 x 10^k.

    `vmax <= 0` -> `[0, 1]`.
    """
    if vmax <= 0:
        return [0, 1]
    paso = _paso_bonito(vmax / max(1, n))
    cuantos = math.ceil(vmax / paso - 1e-12)
    ticks = [round(paso * i, 10) for i in range(cuantos + 1)]
    return [int(t) if float(t).is_integer() else t for t in ticks]


def bar_rows(rows: list[tuple[str, float]], vmax: float | None = None) -> list[dict]:
    """`{"label", "value", "pct"}` con `pct` 0-100 relativo a `vmax` o al maximo."""
    tope = vmax if vmax is not None else max((v for _, v in rows), default=0)
    out = []
    for label, value in rows:
        pct = 0 if tope <= 0 else max(0, min(100, value / tope * 100))
        out.append({"label": label, "value": value, "pct": pct})
    return out


def stack_segments(parts: list[tuple[str, float]]) -> list[dict]:
    """Segmentos de una barra apilada: `{"key", "value", "x_pct", "w_pct"}`.

    Omite las partes en 0; `w_pct` suma 100. Total 0 -> lista vacia.
    """
    vivas = [(k, v) for k, v in parts if v > 0]
    total = sum(v for _, v in vivas)
    if total <= 0:
        return []
    out, acum = [], 0.0
    for key, value in vivas:
        w = value / total * 100
        out.append({"key": key, "value": value, "x_pct": acum, "w_pct": w})
        acum += w
    return out


def line_points(values: list[float], *, width: int, height: int, vmax: float,
                pad: int = 0) -> list[tuple[float, float]]:
    """Puntos (x, y) de una linea: x equiespaciado, y invertido (SVG).

    Un solo valor queda centrado en x. `vmax <= 0` deja todo sobre la base.
    """
    if not values:
        return []
    ancho = width - 2 * pad
    alto = height - 2 * pad
    base = float(height - pad)
    pts = []
    for i, v in enumerate(values):
        x = width / 2 if len(values) == 1 else pad + ancho * i / (len(values) - 1)
        frac = 0.0 if vmax <= 0 else max(0.0, min(1.0, v / vmax))
        pts.append((float(x), float(base - alto * frac)))
    return pts


def points_attr(points) -> str:
    """Atributo `points` de SVG: `"x,y x,y"` con 1 decimal."""
    return " ".join(f"{x:.1f},{y:.1f}" for x, y in points)


def sparkline(values: list[float], width: int = 96, height: int = 24) -> str:
    """Atributo `points` de una mini linea escalada a su propio maximo."""
    if not values:
        return ""
    vmax = max(values)
    return points_attr(line_points(values, width=width, height=height,
                                   vmax=vmax if vmax > 0 else 1, pad=2))


def bin_index(n: int, vmax: int, bins: int = 5) -> int:
    """Cubeta del heatmap: 0 si `n == 0`; si no, 1..`bins`."""
    if n <= 0:
        return 0
    if vmax <= 0:
        return 1
    return min(bins, max(1, math.ceil(n / vmax * bins)))


def calendar_weeks(counts: dict[date, int], start: date, end: date,
                   today: date) -> list[list[dict]]:
    """Semanas lun-vie que cubren `[start, end]`.

    Celda: `{"date", "n", "bin", "in_range", "is_today"}`. Las cubetas se
    escalan al maximo dentro del rango. `start > end` -> `[]`.
    """
    if start > end:
        return []
    vmax = 0
    d = start
    while d <= end:
        vmax = max(vmax, counts.get(d, 0))
        d += timedelta(days=1)
    lunes = start - timedelta(days=start.weekday())
    weeks = []
    while lunes <= end:
        semana = []
        for i in range(5):
            dia = lunes + timedelta(days=i)
            en_rango = start <= dia <= end
            n = counts.get(dia, 0) if en_rango else 0
            semana.append({"date": dia, "n": n, "bin": bin_index(n, vmax),
                           "in_range": en_rango, "is_today": dia == today})
        weeks.append(semana)
        lunes += timedelta(days=7)
    return weeks
