"""Aplica anotaciones Pillow a los screenshots de login del manual de Mantenimiento.

Las capturas de login no se pueden re-tomar con CSS overlay porque la cookie
itcj_token es HttpOnly y no podemos cerrar sesión vía JS desde Playwright.
Usamos Pillow para agregar un banner explicativo encima.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.annotate_screenshot import annotate

ROOT = Path(__file__).parent.parent / "itcj2/apps/maint/static/img/help"

JOBS = [
    {
        "src": ROOT / "01_login_paso1.png",
        "banner": "Paso 1: Abre /itcj/login en tu navegador",
        "boxes": [
            {"xywh": (550, 380, 360, 90), "label": "1"},
            {"xywh": (550, 480, 360, 90), "label": "2"},
        ],
    },
    {
        "src": ROOT / "01_login_paso2.png",
        "banner": "Paso 2: Captura usuario, contraseña, presiona Iniciar sesión",
        "boxes": [
            {"xywh": (550, 600, 360, 70), "label": "Aqui", "color": "#10b981"},
        ],
    },
    {
        "src": ROOT / "01_login_paso3_dashboard.png",
        "banner": "Paso 3: Dashboard general — abre la tarjeta de Mantenimiento",
        "boxes": [],
    },
]


def main():
    for j in JOBS:
        src = j["src"]
        if not src.exists():
            print(f"SKIP -> {src.name} (no existe)")
            continue
        out = annotate(
            src,
            src,
            banner=j.get("banner"),
            boxes=j.get("boxes", []),
        )
        print(f"OK -> {out.name}")


if __name__ == "__main__":
    main()
