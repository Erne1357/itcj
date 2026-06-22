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

# Proveedor de API de marcadores (apagado por default). Se lee por-llamada (no al
# importar) para no requerir reimportar el módulo si cambian las env vars.
def _provider_cfg() -> tuple[str, str, str]:
    """(provider, api_key, api_url) desde el entorno. provider='none' = apagado."""
    return (
        os.getenv("MUNDIAL_API_PROVIDER", "none").lower(),
        os.getenv("MUNDIAL_API_KEY", ""),
        os.getenv("MUNDIAL_API_URL", ""),
    )


def _map_fd_status(s: str | None) -> str:
    """Mapea el status de football-data.org al nuestro (scheduled|live|finished)."""
    s = (s or "").upper()
    if s == "FINISHED":
        return "finished"
    if s in ("IN_PLAY", "PAUSED", "SUSPENDED"):
        return "live"
    return "scheduled"


def _fetch_api_scores(today_matches: list) -> dict | None:
    """Devuelve {fixture_id: {status, score}} desde la API, o None si está apagada/falla.

    Apagado por default (provider='none'). Mapea los partidos de la API a los del
    fixture por el par de equipos: football-data da el `tla` (p.ej. MEX) que casa con
    el `code` del fixture. Orienta el marcador según quién es local. Cualquier error
    -> None (degradar a solo-horario, nunca rompe el dashboard).
    """
    provider, api_key, api_url = _provider_cfg()
    if provider == "none" or not api_key or not today_matches:
        return None
    if provider != "footballdata":
        return None
    try:
        import httpx

        # Rango de fechas UTC que cubre los partidos de hoy CJ (±1 día por zona horaria)
        dates = []
        for m in today_matches:
            try:
                dates.append(_parse_utc(m["kickoff_utc"]).date())
            except Exception:
                pass
        if not dates:
            return None
        d_from = (min(dates) - timedelta(days=1)).isoformat()
        d_to = (max(dates) + timedelta(days=1)).isoformat()

        url = api_url or "https://api.football-data.org/v4/competitions/WC/matches"
        resp = httpx.get(
            url,
            params={"dateFrom": d_from, "dateTo": d_to},
            headers={"X-Auth-Token": api_key},
            timeout=10.0,
        )
        resp.raise_for_status()

        # Indexar los partidos de la API por par de TLAs (sin orden)
        api_by_pair: dict = {}
        for am in resp.json().get("matches", []):
            home = am.get("homeTeam") or {}
            away = am.get("awayTeam") or {}
            h_tla = (home.get("tla") or "").upper()
            a_tla = (away.get("tla") or "").upper()
            if not h_tla or not a_tla:
                continue
            ft = (am.get("score") or {}).get("fullTime") or {}
            api_by_pair[frozenset((h_tla, a_tla))] = {
                "status": _map_fd_status(am.get("status")),
                "home_tla": h_tla,
                "home_goals": ft.get("home"),
                "away_goals": ft.get("away"),
            }

        # Mapear a cada fixture por code, orientando el marcador al local/visitante correcto
        out: dict = {}
        for m in today_matches:
            h_code = ((m.get("home") or {}).get("code") or "").upper()
            a_code = ((m.get("away") or {}).get("code") or "").upper()
            if not h_code or not a_code or "TBD" in (h_code, a_code):
                continue
            info = api_by_pair.get(frozenset((h_code, a_code)))
            if not info:
                continue
            hg, ag = info["home_goals"], info["away_goals"]
            score = None
            if hg is not None and ag is not None:
                if info["home_tla"] == h_code:
                    score = {"home": hg, "away": ag}
                else:  # la API tiene los equipos invertidos respecto al fixture
                    score = {"home": ag, "away": hg}
            out[m["id"]] = {"status": info["status"], "score": score}
        return out or None
    except Exception:
        return None


def get_provider_name() -> str:
    """Nombre del proveedor de marcadores configurado ('none' si está apagado)."""
    return _provider_cfg()[0]


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
    today = merge_scores(today, _fetch_api_scores(today["matches"]))
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


def clear_cache(hard: bool = False) -> None:
    """Borra el cache de partidos (today + fixtures).

    Con hard=True también borra el historial de resultados (mundial:results) y el
    cache del tema activo (core:active_theme) — reset total.
    """
    try:
        r = get_redis()
        keys = [_KEY_TODAY, _KEY_FIXTURES]
        if hard:
            keys += [_KEY_RESULTS, "core:active_theme"]
        r.delete(*keys)
    except Exception:
        pass
