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


# ---------------------------------------------------------------------------
# Pasos de UNA rampa (Ronda 2; Ronda 0 de U2, decisión del controlador):
# tonos por motivo y por parte que se distinguen. Sustituye a `tints` (9 tintes
# a 10 % de aclarado: los vecinos no se distinguían y los claros no llegaban a
# 2:1). Mismas fórmulas que `validate_palette.js` de la skill dataviz
# (luminancia WCAG y L de OKLab), para que lo que aquí pasa allá también pase.
# ---------------------------------------------------------------------------
SURFACE_LIGHT = "#fcfcfb"     # superficie de referencia del validador (modo claro)
LIGHT_FLOOR = 2.0             # contraste mínimo del paso más claro (`--ordinal`)
MIN_STEP_L = 0.06             # separación mínima de L (OKLab) entre pasos vecinos


def _rgb(hex_color: str) -> list[int]:
    return [int(hex_color[i:i + 2], 16) for i in (1, 3, 5)]


def _hex(rgb) -> str:
    return "#" + "".join(f"{max(0, min(255, round(c))):02x}" for c in rgb)


def _mix(hex_color: str, toward: int, t: float) -> str:
    """Mezcla con blanco (`toward` 255, tinte) o negro (0, sombra) al `t` (0-1)."""
    return _hex(c + (toward - c) * t for c in _rgb(hex_color))


def _lin(c8: float) -> float:
    c = c8 / 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def rel_luminance(hex_color: str) -> float:
    r, g, b = (_lin(c) for c in _rgb(hex_color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(a: str, b: str) -> float:
    """Contraste WCAG entre dos colores «#rrggbb»."""
    hi, lo = sorted((rel_luminance(a), rel_luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def ok_lightness(hex_color: str) -> float:
    """L de OKLab (0-1): la claridad percibida que mide el validador."""
    r, g, b = (_lin(c) for c in _rgb(hex_color))
    lms = (0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b,
           0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b,
           0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b)
    l_, m_, s_ = (v ** (1 / 3) for v in lms)
    return 0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_


def _toward_lightness(hex_color: str, target: float, toward: int, t_max: float) -> str:
    """El color de la mezcla `hex_color`→`toward` (hasta `t_max`) cuya L de OKLab
    queda más cerca de `target` (bisección: L es monótona en `t`)."""
    lo, hi = 0.0, t_max
    sube = toward == 255
    for _ in range(40):
        mid = (lo + hi) / 2
        if (ok_lightness(_mix(hex_color, toward, mid)) < target) == sube:
            lo = mid
        else:
            hi = mid
    return _mix(hex_color, toward, (lo + hi) / 2)


def ramp_steps(hex_color: str, k: int, *, surface: str = SURFACE_LIGHT,
               floor: float = LIGHT_FLOOR, min_step: float = MIN_STEP_L,
               max_tint: float = 0.7) -> list[str]:
    """`k` pasos de la rampa de `hex_color`, del más OSCURO al más claro, con la
    misma separación de L (OKLab) entre vecinos (>= `min_step`) y el más claro
    con contraste >= `floor` contra `surface` (los criterios de
    `validate_palette.js --ordinal`).

    Primero aclara (tintes hacia blanco, hasta el tope de contraste). Si ese
    tramo no alcanza para `k` pasos separados, baja la base con sombras (hacia
    negro): misma rampa, mismo tono. Con margen de 5 % para el redondeo a
    «#rrggbb». `k <= 1` -> `[hex_color]`; la base sale tal cual cuando el tramo
    de tintes alcanza.
    """
    if k <= 1:
        return [hex_color]
    t_top = 0.0
    paso = 0.005
    t = paso
    while t <= max_tint + 1e-9:
        if contrast_ratio(_mix(hex_color, 255, t), surface) >= floor:
            t_top = t
        t += paso
    claro = _mix(hex_color, 255, t_top)
    l_base, l_top = ok_lightness(hex_color), ok_lightness(claro)
    piso = min(l_base, l_top - (k - 1) * min_step * 1.05)
    out = []
    for j in range(k):
        meta = piso + (l_top - piso) * j / (k - 1)
        if j == k - 1:
            out.append(claro)
        elif abs(meta - l_base) < 1e-9:
            out.append(hex_color)
        elif meta > l_base:
            out.append(_toward_lightness(hex_color, meta, 255, t_top))
        else:
            out.append(_toward_lightness(hex_color, meta, 0, 1.0))
    return out


def interleave_steps(steps: list[str], n: int) -> list[str]:
    """`n` colores tomados en ciclo de `steps` (oscuro -> claro, `k` pasos) en el
    orden pares-luego-nones (`[0, 2, 1, 3]` con 4). Dos posiciones a distancia
    menor que `k` nunca comparten paso, y las vecinas quedan casi siempre a dos
    pasos (con 4: 2, 1, 2 y 3 al dar la vuelta). `n <= k` -> los primeros `n`
    pasos, en orden."""
    k = len(steps)
    if n <= k:
        return list(steps[:n])
    orden = list(range(0, k, 2)) + list(range(1, k, 2))
    return [steps[orden[i % k]] for i in range(n)]


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
