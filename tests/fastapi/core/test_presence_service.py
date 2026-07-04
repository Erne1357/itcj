"""Tests de presence_service (contrato C5) — Redis REAL del stack, in-container.

fakeredis NO está en requirements (decisión de spec §4); estos tests corren
contra el Redis del compose dev. Los uids 991xxxx son sintéticos para no chocar
con presencia real; el fixture limpia presence:notify:* antes y después.
"""
import time

import pytest

from itcj2.config import get_settings
from itcj2.core.services import presence_service as ps
from itcj2.core.utils.redis_conn import get_redis


def _flush_presence(client):
    keys = list(client.scan_iter(match="presence:notify:*", count=100))
    if keys:
        client.delete(*keys)


@pytest.fixture()
def r():
    client = get_redis()
    try:
        client.ping()
    except Exception:
        pytest.skip("Redis no disponible")
    _flush_presence(client)
    yield client
    _flush_presence(client)


def test_mark_online_cuenta_por_bucket(r):
    ps.mark_online(r, 9910001, "staff")
    ps.mark_online(r, 9910002, "students")
    ps.mark_online(r, 9910003, "admins")
    counts = ps.get_counts(r)
    assert counts == {"total": 3, "students": 1, "staff": 1, "admins": 1}


def test_mark_online_es_idempotente_por_uid(r):
    ps.mark_online(r, 9910001, "staff")
    ps.mark_online(r, 9910001, "staff")  # refresca timestamp, no duplica
    assert ps.get_counts(r)["staff"] == 1


def test_mark_offline_remueve(r):
    ps.mark_online(r, 9910001, "staff")
    ps.mark_offline(r, 9910001, "staff")
    counts = ps.get_counts(r)
    assert counts["staff"] == 0
    assert counts["total"] == 0


def test_mismo_uid_en_dos_buckets_total_es_union(r):
    # simula claims cambiados en pleno vuelo (p.ej. cambio de rol): la entrada
    # vieja sigue vigente en la ventana mientras ya se registró en el bucket
    # nuevo. Cada bucket lo cuenta por separado (semántica documentada), pero
    # el total NO debe duplicarlo.
    ps.mark_online(r, 9910099, "staff")
    ps.mark_online(r, 9910099, "students")
    counts = ps.get_counts(r)
    assert counts["staff"] == 1
    assert counts["students"] == 1
    assert counts["admins"] == 0
    assert counts["total"] == 1  # unión, no suma (que daría 2)


def test_poda_en_lectura_por_ventana_default(r):
    window = get_settings().PRESENCE_WINDOW_SECONDS
    # miembro "fantasma": score fuera de la ventana (simula worker matado sin disconnect)
    r.zadd("presence:notify:staff", {"9910009": time.time() - window - 10})
    ps.mark_online(r, 9910001, "staff")
    counts = ps.get_counts(r)
    assert counts["staff"] == 1
    # la poda es FÍSICA (zremrangebyscore), no solo filtrado
    assert r.zscore("presence:notify:staff", "9910009") is None


def test_ventana_es_configurable(r, monkeypatch):
    monkeypatch.setattr(get_settings(), "PRESENCE_WINDOW_SECONDS", 5)
    r.zadd("presence:notify:admins", {"9910011": time.time() - 6})   # fuera de ventana corta
    ps.mark_online(r, 9910012, "admins")
    assert ps.get_counts(r)["admins"] == 1


@pytest.mark.parametrize(
    "claims,expected",
    [
        ({"role": "admin", "cn": None}, "admins"),
        ({"role": "student", "cn": "20211111"}, "students"),
        ({"role": "", "cn": "21111182"}, "students"),   # cn presente => estudiante
        ({"role": "", "cn": ""}, "staff"),               # cn vacío NO cuenta como presente
        ({"role": None, "cn": None}, "staff"),
        ({"role": "coordinator", "cn": None}, "staff"),
        ({"role": "admin", "cn": "20211111"}, "admins"), # admin gana sobre cn (C5: role primero)
    ],
)
def test_bucket_for(claims, expected):
    assert ps.bucket_for(claims) == expected
