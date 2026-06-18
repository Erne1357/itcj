"""Servicio del tema Mundial 2026: fixture, zona horaria CJ, partidos del día.

Parte 1 (este task): carga del fixture, helpers de tz y cálculo de 'hoy'.
La parte 2 (cache Redis, merge de marcadores, scope, cron) se agrega en Task 3.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore

MUNDIAL_TZ = os.getenv("MUNDIAL_TZ", "America/Ciudad_Juarez")

# itcj2/core/services/ -> itcj2/core/data/mundial_2026_fixtures.json
_FIXTURES_PATH = Path(__file__).resolve().parent.parent / "data" / "mundial_2026_fixtures.json"

# Duración aproximada de un partido (para derivar 'live'/'finished' sin API)
_MATCH_DURATION = timedelta(minutes=110)


def _tz():
    """Devuelve el tzinfo de CJ; cae a UTC-6 fijo si tzdata no está disponible."""
    if ZoneInfo is not None:
        try:
            return ZoneInfo(MUNDIAL_TZ)
        except Exception:
            pass
    from datetime import timezone
    return timezone(timedelta(hours=-6))  # MDT aproximado (verano CJ)


def now_cj() -> datetime:
    """Ahora, en zona Cd. Juárez (tz-aware)."""
    return datetime.now(_tz())


def load_fixtures() -> list[dict]:
    """Carga la lista de partidos del JSON estático. Lista vacía si falla."""
    try:
        with open(_FIXTURES_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return list(data.get("matches", []))
    except Exception:
        return []


def _parse_utc(kickoff_utc: str) -> datetime:
    """ISO '...Z' -> datetime tz-aware UTC."""
    from datetime import timezone
    return datetime.fromisoformat(kickoff_utc.replace("Z", "+00:00")).astimezone(timezone.utc)


def _derive_status(kick_utc: datetime, now_utc: datetime) -> str:
    if now_utc < kick_utc:
        return "scheduled"
    if now_utc < kick_utc + _MATCH_DURATION:
        return "live"
    return "finished"


def _decorate(match: dict, tz, now_utc=None) -> dict:
    """Agrega kickoff_local/label/status a una copia del partido."""
    from datetime import timezone
    kick_utc = _parse_utc(match["kickoff_utc"])
    local = kick_utc.astimezone(tz)
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    out = dict(match)
    out["kickoff_local"] = local.strftime("%H:%M")
    out["kickoff_label"] = local.strftime("%d/%m %H:%M")
    out["status"] = _derive_status(kick_utc, now_utc)
    out.setdefault("score", None)
    return out


def compute_today(fixtures: list[dict], now: datetime | None = None) -> dict:
    """Partidos de HOY (fecha CJ) + próximo partido futuro."""
    tz = _tz()
    ref = now.astimezone(tz) if now else now_cj()
    today_str = ref.strftime("%Y-%m-%d")

    from datetime import timezone
    now_utc = ref.astimezone(timezone.utc)

    today_matches = []
    future = []
    for m in fixtures:
        local = _parse_utc(m["kickoff_utc"]).astimezone(tz)
        if local.strftime("%Y-%m-%d") == today_str:
            today_matches.append(_decorate(m, tz, now_utc))
        elif local > ref:
            future.append((local, m))

    today_matches.sort(key=lambda x: x["kickoff_utc"])
    next_match = None
    if future:
        future.sort(key=lambda x: x[0])
        next_match = _decorate(future[0][1], tz, now_utc)

    return {"date": today_str, "tz": MUNDIAL_TZ, "matches": today_matches, "next_match": next_match}
