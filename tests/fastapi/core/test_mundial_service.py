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
    with patch("itcj2.core.services.mundial_service.get_redis", return_value=fake_redis), \
         patch("itcj2.core.services.mundial_service._fetch_api_scores", return_value=None):
        result = mundial_service.get_today_cached()
    assert "matches" in result
    assert fake_redis.setex.called  # escribió hoy + fixtures


def test_merge_scores_applies_by_id():
    from itcj2.core.services import mundial_service
    today = {"date": "x", "matches": [{"id": "A", "status": "scheduled", "score": None}], "next_match": None}
    api = {"A": {"status": "finished", "score": {"home": 2, "away": 1}}}
    merged = mundial_service.merge_scores(today, api)
    assert merged["matches"][0]["status"] == "finished"
    assert merged["matches"][0]["score"] == {"home": 2, "away": 1}


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
