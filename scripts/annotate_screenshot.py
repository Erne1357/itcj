"""Anota PNGs con Pillow (rectángulos, flechas, badges numerados, banners).

Uso programático::

    from scripts.annotate_screenshot import annotate

    annotate(
        "in.png",
        "out.png",
        banner="Paso 2: Selecciona la categoría",
        boxes=[
            {"xywh": (40, 200, 880, 320), "label": "1", "color": "#ef4444"},
        ],
        arrows=[
            {"from": (200, 600), "to": (200, 540), "label": "Aquí"},
        ],
    )

Uso CLI::

    python scripts/annotate_screenshot.py in.png out.png \
        --banner "Paso 2" \
        --box 40,200,880,320,1 \
        --arrow 200,600,200,540,Aqui

Pensado para anotar capturas estáticas del manual de Mantenimiento.
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageDraw, ImageFont


# ---------------------------------------------------------------------------
# Defaults visuales
# ---------------------------------------------------------------------------

DEFAULT_COLOR = "#ef4444"        # red-500
BANNER_BG = (37, 71, 79, 235)    # blue-grey 800 con alpha
BANNER_FG = (255, 255, 255)
BOX_WIDTH = 4
BADGE_RADIUS = 18
BADGE_FONT_SIZE = 22
BANNER_FONT_SIZE = 26
BANNER_HEIGHT = 56


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Intenta usar una TTF estándar; cae en bitmap si no hay."""
    candidates = [
        "C:/Windows/Fonts/seguisb.ttf",      # Segoe UI Semibold
        "C:/Windows/Fonts/segoeui.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/Library/Fonts/Arial Bold.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


def _draw_box(draw: ImageDraw.ImageDraw, xywh, color: str, width: int = BOX_WIDTH):
    x, y, w, h = xywh
    draw.rectangle([x, y, x + w, y + h], outline=color, width=width)
    # Halo semitransparente — pintamos un segundo rect un poco mayor en gris
    draw.rectangle(
        [x - 2, y - 2, x + w + 2, y + h + 2],
        outline=(0, 0, 0, 80), width=1,
    )


def _draw_badge(draw: ImageDraw.ImageDraw, xy, label: str, color: str,
                font: ImageFont.FreeTypeFont | ImageFont.ImageFont):
    cx, cy = xy
    r = BADGE_RADIUS
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=color, outline="white", width=3)
    bbox = draw.textbbox((0, 0), label, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    draw.text((cx - tw / 2 - bbox[0], cy - th / 2 - bbox[1]), label, fill="white", font=font)


def _draw_arrow(draw: ImageDraw.ImageDraw, src, dst, color: str, width: int = 4):
    import math
    sx, sy = src
    dx, dy = dst
    draw.line([(sx, sy), (dx, dy)], fill=color, width=width)
    angle = math.atan2(dy - sy, dx - sx)
    head = 16
    spread = math.radians(25)
    p1 = (dx - head * math.cos(angle - spread), dy - head * math.sin(angle - spread))
    p2 = (dx - head * math.cos(angle + spread), dy - head * math.sin(angle + spread))
    draw.polygon([(dx, dy), p1, p2], fill=color)


def _draw_banner(img: Image.Image, text: str, font_size: int = BANNER_FONT_SIZE):
    """Inserta una franja superior con `text`. Devuelve nueva imagen con altura mayor."""
    font = _load_font(font_size)
    new = Image.new("RGB", (img.width, img.height + BANNER_HEIGHT), (0, 0, 0))
    new.paste(img, (0, BANNER_HEIGHT))
    overlay = Image.new("RGBA", (img.width, BANNER_HEIGHT), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    od.rectangle([0, 0, img.width, BANNER_HEIGHT], fill=BANNER_BG)
    bbox = od.textbbox((0, 0), text, font=font)
    th = bbox[3] - bbox[1]
    od.text((20, (BANNER_HEIGHT - th) / 2 - bbox[1]), text, fill=BANNER_FG, font=font)
    new.paste(overlay, (0, 0), overlay)
    return new


def annotate(
    src: str | Path,
    dst: str | Path,
    *,
    banner: str | None = None,
    boxes: Iterable[dict] | None = None,
    arrows: Iterable[dict] | None = None,
):
    """Anota `src` y guarda en `dst`.

    Parámetros:
        banner: texto de franja superior. None = sin banner.
        boxes:  lista de dicts {"xywh": (x,y,w,h), "label": "1", "color": "#hex"}.
                Si `label` no está, no se dibuja el badge.
        arrows: lista de dicts {"from": (x,y), "to": (x,y), "color": "#hex"}.
    """
    src = Path(src)
    dst = Path(dst)
    img = Image.open(src).convert("RGB")

    # Calculamos offset: si añadimos banner, las coords del usuario se desplazan.
    y_offset = BANNER_HEIGHT if banner else 0

    draw = ImageDraw.Draw(img, "RGBA")
    badge_font = _load_font(BADGE_FONT_SIZE)

    for b in (boxes or []):
        color = b.get("color", DEFAULT_COLOR)
        x, y, w, h = b["xywh"]
        _draw_box(draw, (x, y, w, h), color=color)
        label = b.get("label")
        if label:
            _draw_badge(draw, (x + 14, y + 14), str(label), color=color, font=badge_font)

    for a in (arrows or []):
        color = a.get("color", DEFAULT_COLOR)
        _draw_arrow(draw, a["from"], a["to"], color=color)

    # El banner se aplica al final porque cambia la altura de la imagen
    if banner:
        img = _draw_banner(img, banner)

    dst.parent.mkdir(parents=True, exist_ok=True)
    img.save(dst, format="PNG", optimize=True)
    return dst


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_box(spec: str) -> dict:
    parts = spec.split(",")
    if len(parts) < 4:
        raise argparse.ArgumentTypeError("box format: x,y,w,h[,label[,color]]")
    x, y, w, h = (int(p) for p in parts[:4])
    out: dict = {"xywh": (x, y, w, h)}
    if len(parts) >= 5 and parts[4]:
        out["label"] = parts[4]
    if len(parts) >= 6 and parts[5]:
        out["color"] = parts[5]
    return out


def _parse_arrow(spec: str) -> dict:
    parts = spec.split(",")
    if len(parts) < 4:
        raise argparse.ArgumentTypeError("arrow format: x1,y1,x2,y2[,color]")
    x1, y1, x2, y2 = (int(p) for p in parts[:4])
    out: dict = {"from": (x1, y1), "to": (x2, y2)}
    if len(parts) >= 5 and parts[4]:
        out["color"] = parts[4]
    return out


def main():
    ap = argparse.ArgumentParser(description="Anota un PNG con Pillow.")
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--banner", default=None)
    ap.add_argument("--box", action="append", type=_parse_box, default=[])
    ap.add_argument("--arrow", action="append", type=_parse_arrow, default=[])
    args = ap.parse_args()
    out = annotate(args.src, args.dst, banner=args.banner, boxes=args.box, arrows=args.arrow)
    print(f"OK -> {out}")


if __name__ == "__main__":
    main()
