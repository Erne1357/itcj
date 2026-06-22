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
    # Si el partido ya trae status (p.ej. de la API), respétalo; si no, derívalo por hora.
    out["status"] = match.get("status") or _derive_status(kick_utc, now_utc)
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
_KEY_STANDINGS = "mundial:standings"
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


# Mapa TLA (football-data) -> bandera emoji. Default 🏳️ si no está.
_TLA_FLAG = {
    "MEX": "🇲🇽", "USA": "🇺🇸", "CAN": "🇨🇦", "BRA": "🇧🇷", "ARG": "🇦🇷",
    "FRA": "🇫🇷", "GER": "🇩🇪", "ESP": "🇪🇸", "POR": "🇵🇹", "ENG": "🏴",
    "NED": "🇳🇱", "BEL": "🇧🇪", "ITA": "🇮🇹", "CRO": "🇭🇷", "URU": "🇺🇾",
    "COL": "🇨🇴", "JPN": "🇯🇵", "KOR": "🇰🇷", "AUS": "🇦🇺", "MAR": "🇲🇦",
    "SEN": "🇸🇳", "GHA": "🇬🇭", "NGA": "🇳🇬", "CMR": "🇨🇲", "EGY": "🇪🇬",
    "SUI": "🇨🇭", "DEN": "🇩🇰", "POL": "🇵🇱", "SRB": "🇷🇸", "ECU": "🇪🇨",
    "CRC": "🇨🇷", "QAT": "🇶🇦", "KSA": "🇸🇦", "IRN": "🇮🇷", "TUN": "🇹🇳",
    "WAL": "🏴", "SCO": "🏴", "AUT": "🇦🇹", "CZE": "🇨🇿", "TUR": "🇹🇷",
    "UKR": "🇺🇦", "NOR": "🇳🇴", "SWE": "🇸🇪", "PER": "🇵🇪", "CHI": "🇨🇱",
    "PAR": "🇵🇾", "VEN": "🇻🇪", "BOL": "🇧🇴", "PAN": "🇵🇦", "HON": "🇭🇳",
    "JAM": "🇯🇲", "ALG": "🇩🇿", "CIV": "🇨🇮", "RSA": "🇿🇦", "NZL": "🇳🇿",
}


def _tla_flag(tla: str | None) -> str:
    return _TLA_FLAG.get((tla or "").upper(), "🏳️")


def _map_stage(s: str | None) -> str:
    return {
        "GROUP_STAGE": "group", "LAST_32": "round32",
        "LAST_16": "round16", "ROUND_OF_16": "round16",
        "QUARTER_FINALS": "quarter", "SEMI_FINALS": "semi",
        "THIRD_PLACE": "third", "FINAL": "final",
    }.get((s or "").upper(), (s or "group").lower())


def _clean_group(g: str | None) -> str | None:
    g = (g or "").upper().replace("GROUP_", "").replace("GROUP ", "").strip()
    return g or None


def _competition() -> str:
    """Código de competición football-data (default 'WC'). Se deriva de
    MUNDIAL_API_COMPETITION o de la URL configurada; nunca de filtros de fecha."""
    comp = os.getenv("MUNDIAL_API_COMPETITION", "").strip()
    if comp:
        return comp
    _, _, api_url = _provider_cfg()
    if "/competitions/" in api_url:
        return api_url.split("/competitions/")[-1].split("/")[0] or "WC"
    return "WC"


def _matches_endpoint() -> str:
    # Sin parámetros de fecha: trae el calendario COMPLETO (los 104 partidos).
    return f"https://api.football-data.org/v4/competitions/{_competition()}/matches"


def _standings_endpoint() -> str:
    return f"https://api.football-data.org/v4/competitions/{_competition()}/standings"


def _api_match_to_fixture(am: dict) -> dict | None:
    """Convierte un partido de football-data al shape de nuestro fixture."""
    ku = am.get("utcDate")
    if not ku:
        return None
    home = am.get("homeTeam") or {}
    away = am.get("awayTeam") or {}
    score = am.get("score") or {}
    ft = score.get("fullTime") or {}
    hg, ag = ft.get("home"), ft.get("away")
    # winner: 'HOME_TEAM' | 'AWAY_TEAM' | 'DRAW' | None (respeta penales en eliminatoria)
    return {
        "id": "FD-" + str(am.get("id")),
        "kickoff_utc": ku,
        "stage": _map_stage(am.get("stage")),
        "group": _clean_group(am.get("group")),
        "home": {"code": (home.get("tla") or "").upper(),
                 "name": home.get("shortName") or home.get("name") or "?",
                 "flag": _tla_flag(home.get("tla"))},
        "away": {"code": (away.get("tla") or "").upper(),
                 "name": away.get("shortName") or away.get("name") or "?",
                 "flag": _tla_flag(away.get("tla"))},
        "venue": am.get("venue") or "",
        "status": _map_fd_status(am.get("status")),
        "score": {"home": hg, "away": ag} if (hg is not None and ag is not None) else None,
        "winner": score.get("winner"),
    }


def _fetch_api_all() -> list | None:
    """Calendario completo del Mundial desde la API (equipos reales + marcadores),
    en el shape de nuestro fixture. None si la API está apagada o falla.

    Cuando la API está activa ES la fuente de verdad: resuelve el problema de los
    rivales 'TBD' del fixture estático (que impedía casar marcadores). El JSON
    estático queda solo como respaldo offline. Cualquier error -> None (degradar).
    """
    provider, api_key, api_url = _provider_cfg()
    if provider != "footballdata" or not api_key:
        return None
    try:
        import httpx
        resp = httpx.get(_matches_endpoint(), headers={"X-Auth-Token": api_key}, timeout=12.0)
        resp.raise_for_status()
        out = []
        for am in resp.json().get("matches", []):
            fx = _api_match_to_fixture(am)
            if fx:
                out.append(fx)
        return out or None
    except Exception:
        return None


def _fetch_api_standings() -> list | None:
    """Tablas de la fase de grupos desde la API. Lista de {group, table:[...]} o None."""
    provider, api_key, _ = _provider_cfg()
    if provider != "footballdata" or not api_key:
        return None
    try:
        import httpx
        resp = httpx.get(_standings_endpoint(), headers={"X-Auth-Token": api_key}, timeout=12.0)
        resp.raise_for_status()
        out = []
        for s in resp.json().get("standings", []):
            # Solo la tabla total por grupo (ignora desgloses HOME/AWAY si los hubiera)
            if s.get("type") and s.get("type") != "TOTAL":
                continue
            rows = []
            for row in s.get("table", []):
                team = row.get("team") or {}
                rows.append({
                    "position": row.get("position"),
                    "team": {
                        "name": team.get("shortName") or team.get("name") or "?",
                        "code": (team.get("tla") or "").upper(),
                        "flag": _tla_flag(team.get("tla")),
                    },
                    "played": row.get("playedGames"),
                    "won": row.get("won"),
                    "draw": row.get("draw"),
                    "lost": row.get("lost"),
                    "gf": row.get("goalsFor"),
                    "ga": row.get("goalsAgainst"),
                    "gd": row.get("goalDifference"),
                    "points": row.get("points"),
                })
            if rows:
                out.append({"group": _clean_group(s.get("group")), "table": rows})
        return out or None
    except Exception:
        return None


def api_diagnostic() -> dict:
    """Diagnóstico de la API de marcadores: por qué salen (o no) los partidos."""
    provider, api_key, api_url = _provider_cfg()
    info = {"provider": provider, "enabled": provider != "none" and bool(api_key),
            "ok": False, "status_code": None, "error": None,
            "count": 0, "today_count": 0, "sample": []}
    if not info["enabled"]:
        info["error"] = "provider='none' o sin API key (revisa MUNDIAL_API_PROVIDER / MUNDIAL_API_KEY en el entorno del contenedor)"
        return info
    if provider != "footballdata":
        info["error"] = f"provider '{provider}' no soportado (usa 'footballdata')"
        return info
    try:
        import httpx
        resp = httpx.get(_matches_endpoint(), headers={"X-Auth-Token": api_key}, timeout=12.0)
        info["status_code"] = resp.status_code
        resp.raise_for_status()
        matches = resp.json().get("matches", [])
        info["count"] = len(matches)
        info["ok"] = True
        tz = _tz()
        today_str = now_cj().strftime("%Y-%m-%d")
        for am in matches:
            ku = am.get("utcDate")
            if not ku:
                continue
            try:
                if _parse_utc(ku).astimezone(tz).strftime("%Y-%m-%d") == today_str:
                    info["today_count"] += 1
            except Exception:
                pass
        for am in matches[:8]:
            h = (am.get("homeTeam") or {}).get("tla") or "?"
            a = (am.get("awayTeam") or {}).get("tla") or "?"
            d = (am.get("utcDate") or "")[:10]
            info["sample"].append(f"{h} vs {a} {d} [{am.get('status')}]")
        return info
    except Exception as e:
        info["error"] = str(e)
        return info


def get_provider_name() -> str:
    """Nombre del proveedor de marcadores configurado ('none' si está apagado)."""
    return _provider_cfg()[0]


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
    """Lee mundial:today de Redis; en miss/force recalcula y cachea.

    Fuente de los partidos: la API (calendario real + marcadores) si está activa;
    si no, el fixture estático de respaldo.
    """
    r = None
    try:
        r = get_redis()
        if not force:
            cached = r.get(_KEY_TODAY)
            if cached:
                return json.loads(cached)
    except Exception:
        r = None

    api_all = _fetch_api_all()
    fixtures = api_all if api_all is not None else load_fixtures()
    today = compute_today(fixtures)
    persist_results(today)
    # Este es el punto de refresco periódico: aprovecha para refrescar standings.
    standings = _fetch_api_standings()

    try:
        if r is not None:
            r.setex(_KEY_TODAY, _TODAY_TTL, json.dumps(today))
            r.setex(_KEY_FIXTURES, _TODAY_TTL, json.dumps(fixtures))
            if standings is not None:
                r.setex(_KEY_STANDINGS, _TODAY_TTL, json.dumps(standings))
    except Exception:
        pass
    return today


def get_standings() -> list:
    """Tablas de la fase de grupos (cache mundial:standings, con fetch-on-miss)."""
    try:
        raw = get_redis().get(_KEY_STANDINGS)
        if raw:
            return json.loads(raw)
    except Exception:
        pass
    st = _fetch_api_standings()
    if st is not None:
        try:
            get_redis().setex(_KEY_STANDINGS, _TODAY_TTL, json.dumps(st))
        except Exception:
            pass
        return st
    return []


def _load_results() -> dict:
    try:
        raw = get_redis().hgetall(_KEY_RESULTS) or {}
        return {k: json.loads(v) for k, v in raw.items()}
    except Exception:
        return {}


def _get_fixtures_cached() -> list:
    """Calendario para los scopes past/upcoming/all y el bracket.

    Orden: cache Redis (mundial:fixtures:all) → fetch-on-miss a la API (calendario
    completo, lo cachea) → fixture estático de respaldo. Así Lista/Bracket traen los
    104 partidos aunque el cron aún no haya calentado el cache.
    """
    try:
        raw = get_redis().get(_KEY_FIXTURES)
        if raw:
            return json.loads(raw)
    except Exception:
        pass
    api_all = _fetch_api_all()
    if api_all is not None:
        try:
            get_redis().setex(_KEY_FIXTURES, _TODAY_TTL, json.dumps(api_all))
        except Exception:
            pass
        return api_all
    return load_fixtures()


def get_matches(scope: str = "today") -> dict:
    """Partidos por scope: today | past | upcoming | all (con marcadores cacheados)."""
    if scope == "today":
        return get_today_cached()

    tz = _tz()
    ref = now_cj()
    today_str = ref.strftime("%Y-%m-%d")
    results = _load_results()
    fixtures = _get_fixtures_cached()

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
        keys = [_KEY_TODAY, _KEY_FIXTURES, _KEY_STANDINGS]
        if hard:
            keys += [_KEY_RESULTS, "core:active_theme"]
        r.delete(*keys)
    except Exception:
        pass
