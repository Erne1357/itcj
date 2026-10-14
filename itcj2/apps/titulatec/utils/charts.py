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


def scaled_segments(parts: list[tuple[str, float]], vmax: float) -> list[dict]:
    """Segmentos de una barra partida a una escala COMUN (`vmax`), no a su
    propio total: `{"key", "value", "x_pct", "w_pct"}` con `w_pct = value /
    vmax * 100`. Asi dos barras con la misma `vmax` se comparan a lo largo.

    Omite las partes en 0; `vmax <= 0` -> lista vacia. Si la suma rebasa
    `vmax`, la barra se recorta en 100 (nunca desborda).
    """
    if vmax <= 0:
        return []
    out, acum = [], 0.0
    for key, value in parts:
        if value <= 0 or acum >= 100:
            continue
        w = min(value / vmax * 100, 100 - acum)
        out.append({"key": key, "value": value, "x_pct": acum, "w_pct": w})
        acum += w
    return out


def tints(hex_color: str, n: int, *, lightest: float = 0.7) -> list[str]:
    """`n` tintes de `hex_color` («#rrggbb»): el primero es el color tal cual y
    el ultimo lo mezcla con blanco al `lightest` (0-1), en pasos iguales. Para
    partir la barra de un area por motivo sin salir de su identidad (spec §12
    + §7); por debajo de 3:1 el texto va FUERA de la marca."""
    if n <= 0:
        return []
    base = [int(hex_color[i:i + 2], 16) for i in (1, 3, 5)]
    out = []
    for i in range(n):
        t = 0.0 if n == 1 else lightest * i / (n - 1)
        out.append("#" + "".join(f"{round(c + (255 - c) * t):02x}" for c in base))
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
