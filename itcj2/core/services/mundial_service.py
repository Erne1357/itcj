"""Servicio del tema Mundial 2026: fixture, zona horaria CJ, partidos del día.

Parte 1: carga del fixture, helpers de tz y cálculo de 'hoy'.
Parte 2: cache Redis, merge de marcadores, scope, cron sync.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path

from itcj2.core.utils.redis_conn import get_redis

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


# ── Parte 2: cache Redis, merge de marcadores, scope, cron sync ──────────────

THEME_NAME = "Mundial 2026"
TASK_NAME = "itcj2.tasks.mundial_tasks.refresh_mundial_matches"
PERIODIC_TASK_NAME = "Refresco diario de partidos del Mundial"

_KEY_TODAY = "mundial:today"
_KEY_FIXTURES = "mundial:fixtures:all"
_KEY_RESULTS = "mundial:results"
_TODAY_TTL = 26 * 3600  # ~26h

# Proveedor de API (apagado por default)
_PROVIDER = os.getenv("MUNDIAL_API_PROVIDER", "none").lower()
_API_KEY = os.getenv("MUNDIAL_API_KEY", "")
_API_URL = os.getenv("MUNDIAL_API_URL", "")


def _fetch_api_scores(date_str: str) -> dict | None:
    """Devuelve {match_id: {status, score}} desde la API si está habilitada, si no None.

    Apagado por default (_PROVIDER='none'). Cualquier error -> None (degradar).
    """
    if _PROVIDER == "none" or not _API_KEY:
        return None
    try:
        import httpx
        # Implementación específica por proveedor. Esqueleto football-data.org:
        if _PROVIDER == "footballdata":
            url = _API_URL or "https://api.football-data.org/v4/competitions/WC/matches"
            resp = httpx.get(url, params={"dateFrom": date_str, "dateTo": date_str},
                             headers={"X-Auth-Token": _API_KEY}, timeout=8.0)
            resp.raise_for_status()
            out: dict = {}
            for m in resp.json().get("matches", []):
                # El mapeo id-API -> id-fixture depende del proveedor; aquí por equipos+fecha.
                # Se deja como punto de extensión: requiere tabla de mapeo o match por nombres.
                pass
            return out or None
        return None
    except Exception:
        return None


def merge_scores(today: dict, api_data: dict | None) -> dict:
    """Aplica marcadores de la API (por id) sobre los partidos de today (sin mutar el input)."""
    if not api_data:
        return today
    new_matches = []
    for m in today.get("matches", []):
        upd = api_data.get(m.get("id"))
        if upd:
            m = {**m, "status": upd.get("status", m.get("status")), "score": upd.get("score", m.get("score"))}
        new_matches.append(m)
    return {**today, "matches": new_matches}


def persist_results(today: dict) -> None:
    """Guarda partidos finished con score en el hash mundial:results (persistente)."""
    try:
        r = get_redis()
        for m in today.get("matches", []):
            if m.get("status") == "finished" and m.get("score"):
                r.hset(_KEY_RESULTS, m["id"], json.dumps({
                    "status": "finished", "score": m["score"],
                }))
    except Exception:
        pass


def get_today_cached(force: bool = False) -> dict:
    """Lee mundial:today de Redis; en miss/force recalcula, mergea API y cachea."""
    r = None
    try:
        r = get_redis()
        if not force:
            cached = r.get(_KEY_TODAY)
            if cached:
                return json.loads(cached)
    except Exception:
        r = None

    fixtures = load_fixtures()
    today = compute_today(fixtures)
    today = merge_scores(today, _fetch_api_scores(today["date"]))
    persist_results(today)

    try:
        if r is not None:
            r.setex(_KEY_TODAY, _TODAY_TTL, json.dumps(today))
            r.setex(_KEY_FIXTURES, _TODAY_TTL, json.dumps(fixtures))
    except Exception:
        pass
    return today


def _load_results() -> dict:
    try:
        raw = get_redis().hgetall(_KEY_RESULTS) or {}
        return {k: json.loads(v) for k, v in raw.items()}
    except Exception:
        return {}


def get_matches(scope: str = "today") -> dict:
    """Partidos por scope: today | past | upcoming | all (con marcadores cacheados)."""
    if scope == "today":
        return get_today_cached()

    tz = _tz()
    ref = now_cj()
    today_str = ref.strftime("%Y-%m-%d")
    results = _load_results()
    fixtures = load_fixtures()

    out = []
    for m in fixtures:
        dm = _decorate(m, tz)
        res = results.get(m["id"])
        if res:
            dm["status"] = res.get("status", dm["status"])
            dm["score"] = res.get("score", dm.get("score"))
        local_date = _parse_utc(m["kickoff_utc"]).astimezone(tz).strftime("%Y-%m-%d")
        if scope == "past" and local_date < today_str:
            out.append(dm)
        elif scope == "upcoming" and local_date > today_str:
            out.append(dm)
        elif scope == "all":
            out.append(dm)

    reverse = scope == "past"
    out.sort(key=lambda x: x["kickoff_utc"], reverse=reverse)
    return {"scope": scope, "date": today_str, "tz": MUNDIAL_TZ, "matches": out, "next_match": None}


def is_theme_active(db) -> bool:
    """True si el tema 'Mundial 2026' está activo."""
    try:
        from itcj2.core.services import themes_service
        theme = themes_service.get_theme_by_name(db, THEME_NAME)
        return bool(theme and theme.is_active())
    except Exception:
        return False


def sync_periodic_task(db) -> bool:
    """Pone core_periodic_tasks.is_active = (tema Mundial activo). Devuelve el estado aplicado."""
    from sqlalchemy import text
    active = is_theme_active(db)
    db.execute(
        text("UPDATE core_periodic_tasks SET is_active = :a, updated_at = NOW() WHERE task_name = :t"),
        {"a": active, "t": TASK_NAME},
    )
    db.commit()
    return active


def clear_cache() -> None:
    """Borra las keys de partidos (usado cuando el tema se desactiva)."""
    try:
        r = get_redis()
        r.delete(_KEY_TODAY, _KEY_FIXTURES)
    except Exception:
        pass
