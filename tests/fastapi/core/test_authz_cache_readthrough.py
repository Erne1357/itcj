"""El caché de authz solo aparecía en la suite como objetivo de patch().

Estos tests ejercitan su propia lógica: MISS computa una vez, HIT no recomputa,
la invalidación fuerza un MISS nuevo, y sin Redis se computa contra la BD.
"""
from unittest.mock import patch

import pytest

from itcj2.core.services import authz_cache as ac

UID = 5559301
APP = "helpdesk"


def _redis_or_skip():
    try:
        from itcj2.core.utils.redis_conn import get_redis
        r = get_redis()
        r.ping()
    except Exception:
        pytest.skip("Redis no disponible")
    return r


def test_miss_computes_once_and_hit_does_not_recompute():
    _redis_or_skip()
    with patch("itcj2.core.services.authz_service.get_user_permissions_for_app",
               return_value={"helpdesk.a"}) as compute:
        first = ac.cached_perms(None, UID, APP)
        second = ac.cached_perms(None, UID, APP)

    assert first == {"helpdesk.a"}
    assert second == {"helpdesk.a"}
    compute.assert_called_once()          # el segundo salió del caché


def test_invalidate_user_app_forces_a_new_miss():
    _redis_or_skip()
    with patch("itcj2.core.services.authz_service.get_user_permissions_for_app",
               return_value={"helpdesk.a"}) as compute:
        ac.cached_perms(None, UID, APP)
        ac.invalidate_user_app(UID, APP)
        ac.cached_perms(None, UID, APP)

    assert compute.call_count == 2


def test_fails_open_to_the_database_without_redis():
    """Sin Redis el caché no puede bloquear ni romper la autorización."""
    with patch.object(ac, "_redis", return_value=None), \
         patch("itcj2.core.services.authz_service.get_user_permissions_for_app",
               return_value={"helpdesk.a"}) as compute:
        assert ac.cached_perms(None, UID, APP) == {"helpdesk.a"}

    compute.assert_called_once()
