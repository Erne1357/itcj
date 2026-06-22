from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo


def test_load_fixtures_returns_list():
    from itcj2.core.services import mundial_service
    fixtures = mundial_service.load_fixtures()
    assert isinstance(fixtures, list)
    assert len(fixtures) >= 1
    assert "kickoff_utc" in fixtures[0]


def test_compute_today_filters_by_cj_date_and_formats_local():
    from itcj2.core.services import mundial_service
    fixtures = [
        {"id": "A", "kickoff_utc": "2026-06-18T19:00:00Z", "stage": "group",
         "group": "A", "home": {"code": "MEX", "name": "Mexico", "flag": "x"},
         "away": {"code": "TBD", "name": "Por definir", "flag": "y"}, "venue": "v"},
        {"id": "B", "kickoff_utc": "2026-06-20T19:00:00Z", "stage": "group",
         "group": "B", "home": {"code": "CAN", "name": "Canada", "flag": "x"},
         "away": {"code": "TBD", "name": "Por definir", "flag": "y"}, "venue": "v"},
    ]
    # 2026-06-18 12:00 en Cd. Juárez (MDT, UTC-6) == 18:00Z; el partido A (19:00Z) es hoy y futuro
    now = datetime(2026, 6, 18, 12, 0, tzinfo=ZoneInfo("America/Ciudad_Juarez"))
    result = mundial_service.compute_today(fixtures, now=now)

    assert result["date"] == "2026-06-18"
    assert len(result["matches"]) == 1
    m = result["matches"][0]
    assert m["id"] == "A"
    assert m["kickoff_local"] == "13:00"
    assert m["status"] == "scheduled"
    # next_match apunta al de mañana
    assert result["next_match"]["id"] == "B"


def test_get_today_cached_returns_cache_hit():
    from itcj2.core.services import mundial_service
    fake_redis = MagicMock()
    fake_redis.get.return_value = '{"date": "2026-06-18", "matches": [], "next_match": null}'
    with patch("itcj2.core.services.mundial_service.get_redis", return_value=fake_redis):
        result = mundial_service.get_today_cached()
    assert result["date"] == "2026-06-18"
    fake_redis.set.assert_not_called()


def test_get_today_cached_fetch_on_miss_writes_cache():
    from itcj2.core.services import mundial_service
    fake_redis = MagicMock()
    fake_redis.get.return_value = None  # miss
    api_fixtures = [{"id": "FD-1", "kickoff_utc": "2026-06-18T19:00:00Z", "stage": "group", "group": "A",
                     "home": {"code": "MEX", "name": "Mexico", "flag": "x"},
                     "away": {"code": "BRA", "name": "Brazil", "flag": "y"}, "venue": "v"}]
    with patch("itcj2.core.services.mundial_service.get_redis", return_value=fake_redis), \
         patch("itcj2.core.services.mundial_service._fetch_api_all", return_value=api_fixtures), \
         patch("itcj2.core.services.mundial_service._fetch_api_standings", return_value=None):
        result = mundial_service.get_today_cached()
    assert "matches" in result
    # API ok -> escribe mundial:today + mundial:fixtures:all
    assert fake_redis.setex.call_count == 2


def test_get_today_cached_api_down_does_not_clobber_fixtures():
    """Si la API falla, NO debe re-escribir mundial:fixtures:all (no degradar a estático)."""
    from itcj2.core.services import mundial_service
    fake_redis = MagicMock()
    fake_redis.get.return_value = None  # miss en mundial:today y en fixtures
    with patch("itcj2.core.services.mundial_service.get_redis", return_value=fake_redis), \
         patch("itcj2.core.services.mundial_service._fetch_api_all", return_value=None), \
         patch("itcj2.core.services.mundial_service.load_fixtures", return_value=[]):
        mundial_service.get_today_cached()
    # Solo mundial:today; nunca mundial:fixtures:all con datos estáticos
    keys_written = [c.args[0] for c in fake_redis.setex.call_args_list]
    assert "mundial:fixtures:all" not in keys_written


def test_api_match_to_fixture_maps_teams_and_score():
    from itcj2.core.services import mundial_service
    am = {
        "id": 12345,
        "utcDate": "2026-06-22T19:00:00Z",
        "stage": "GROUP_STAGE",
        "group": "GROUP_A",
        "status": "FINISHED",
        "homeTeam": {"name": "Mexico", "shortName": "Mexico", "tla": "MEX"},
        "awayTeam": {"name": "Brazil", "shortName": "Brazil", "tla": "BRA"},
        "score": {"fullTime": {"home": 2, "away": 1}},
    }
    fx = mundial_service._api_match_to_fixture(am)
    assert fx["id"] == "FD-12345"
    assert fx["home"]["code"] == "MEX" and fx["home"]["flag"] == "🇲🇽"
    assert fx["away"]["code"] == "BRA"
    assert fx["stage"] == "group" and fx["group"] == "A"
    assert fx["status"] == "finished"
    assert fx["score"] == {"home": 2, "away": 1}


def test_get_matches_past_scope():
    from itcj2.core.services import mundial_service
    from datetime import datetime
    from zoneinfo import ZoneInfo
    fixtures = [
        {"id": "OLD", "kickoff_utc": "2026-06-10T19:00:00Z", "stage": "group", "group": "A",
         "home": {"code": "MEX", "name": "Mexico", "flag": "x"}, "away": {"code": "T", "name": "T", "flag": "y"}, "venue": "v"},
        {"id": "FUT", "kickoff_utc": "2026-06-30T19:00:00Z", "stage": "group", "group": "A",
         "home": {"code": "CAN", "name": "Canada", "flag": "x"}, "away": {"code": "T", "name": "T", "flag": "y"}, "venue": "v"},
    ]
    fake_redis = MagicMock()
    fake_redis.get.return_value = None
    fake_redis.hgetall.return_value = {}
    with patch("itcj2.core.services.mundial_service.get_redis", return_value=fake_redis), \
         patch("itcj2.core.services.mundial_service.load_fixtures", return_value=fixtures), \
         patch("itcj2.core.services.mundial_service.now_cj",
               return_value=datetime(2026, 6, 18, 12, 0, tzinfo=ZoneInfo("America/Ciudad_Juarez"))):
        result = mundial_service.get_matches("past")
    ids = [m["id"] for m in result["matches"]]
    assert ids == ["OLD"]  # solo pasados


def test_sync_periodic_task_sets_active_from_theme():
    from itcj2.core.services import mundial_service
    db = MagicMock()
    with patch("itcj2.core.services.mundial_service.is_theme_active", return_value=True):
        applied = mundial_service.sync_periodic_task(db)
    assert applied is True
    db.execute.assert_called()  # actualizó core_periodic_tasks
    db.commit.assert_called()


def test_refresh_task_skips_when_theme_inactive():
    import itcj2.tasks.mundial_tasks as mt
    with patch("itcj2.tasks.mundial_tasks.SessionLocal") as mock_sl, \
         patch("itcj2.core.services.mundial_service.is_theme_active", return_value=False), \
         patch("itcj2.core.services.mundial_service.clear_cache") as mock_clear, \
         patch("itcj2.core.services.mundial_service.sync_periodic_task"), \
         patch("itcj2.core.services.mundial_service.get_today_cached") as mock_fetch:
        mock_sl.return_value.__enter__.return_value = MagicMock()
        result = mt._do_refresh()
    assert result.get("skipped") == "theme_inactive"
    mock_clear.assert_called_once()
    mock_fetch.assert_not_called()


def test_refresh_task_fetches_when_theme_active():
    import itcj2.tasks.mundial_tasks as mt
    with patch("itcj2.tasks.mundial_tasks.SessionLocal") as mock_sl, \
         patch("itcj2.core.services.mundial_service.is_theme_active", return_value=True), \
         patch("itcj2.core.services.mundial_service.get_today_cached",
               return_value={"date": "2026-06-18", "matches": [{"id": "A"}]}) as mock_fetch, \
         patch("itcj2.core.services.mundial_service.sync_periodic_task") as mock_sync:
        mock_sl.return_value.__enter__.return_value = MagicMock()
        result = mt._do_refresh()
    assert result["matches_count"] == 1
    mock_fetch.assert_called_once_with(force=True)
    mock_sync.assert_not_called()


def test_mundial_task_in_celery_include():
    from itcj2.celery_app import celery_app
    assert "itcj2.tasks.mundial_tasks" in (celery_app.conf.include or [])


def test_toggle_mundial_theme_syncs_cron():
    from itcj2.core.services import themes_service, mundial_service
    db = MagicMock()
    fake_theme = MagicMock()
    fake_theme.name = mundial_service.THEME_NAME
    db.get.return_value = fake_theme
    with patch("itcj2.core.services.mundial_service.sync_periodic_task") as mock_sync, \
         patch("itcj2.core.services.themes_service.invalidate_active_theme_cache"):
        themes_service.toggle_theme_enabled(db, 1, False)
    mock_sync.assert_called_once_with(db)


def test_toggle_other_theme_does_not_sync_cron():
    from itcj2.core.services import themes_service
    db = MagicMock()
    fake_theme = MagicMock()
    fake_theme.name = "Navidad"
    db.get.return_value = fake_theme
    with patch("itcj2.core.services.mundial_service.sync_periodic_task") as mock_sync, \
         patch("itcj2.core.services.themes_service.invalidate_active_theme_cache"):
        themes_service.toggle_theme_enabled(db, 1, False)
    mock_sync.assert_not_called()
