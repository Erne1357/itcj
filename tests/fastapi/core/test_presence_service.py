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
    keys += list(client.scan_iter(match="presence:app:*", count=100))
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


# ---------------------------------------------------------------------------
# Latido por app (ronda 3): presencia viva + dimensión `app`
# ---------------------------------------------------------------------------
def test_touch_refresca_bucket_y_app(r):
    ps.touch(r, 9910021, "staff", "helpdesk")
    assert ps.get_counts(r)["staff"] == 1
    assert ps.get_app_counts(r)["helpdesk"] == 1


def test_touch_normaliza_la_app_y_la_devuelve(r):
    assert ps.touch(r, 9910022, "staff", "help-desk") == "helpdesk"  # alias de la URL
    assert ps.touch(r, 9910023, "staff", "inventada") == "otro"      # fuera del conjunto
    assert ps.touch(r, 9910024, "staff", None) == "otro"             # latido sin payload
    counts = ps.get_app_counts(r)
    assert counts["helpdesk"] == 1
    assert counts["otro"] == 2


def test_get_app_counts_cuenta_usuarios_distintos(r):
    ps.touch(r, 9910031, "staff", "maint")
    ps.touch(r, 9910031, "staff", "maint")   # mismo uid, 2 latidos => 1 usuario
    ps.touch(r, 9910032, "students", "maint")
    assert ps.get_app_counts(r)["maint"] == 2


def test_get_app_counts_expone_el_conjunto_cerrado_completo(r):
    counts = ps.get_app_counts(r)
    assert set(counts) == set(ps.APPS)
    assert "otro" in counts
    assert all(v == 0 for v in counts.values())


def test_latido_viejo_se_poda_y_el_refrescado_sigue_vivo(r):
    window = get_settings().PRESENCE_WINDOW_SECONDS
    # shell que dejó de latir hace más de la ventana (5 latidos de tolerancia)
    r.zadd("presence:app:helpdesk", {"9910041": time.time() - window - 10})
    ps.touch(r, 9910042, "staff", "helpdesk")
    assert ps.get_app_counts(r)["helpdesk"] == 1
    # la poda es FÍSICA (zremrangebyscore), igual que en get_counts
    assert r.zscore("presence:app:helpdesk", "9910041") is None
    # el que sí late sigue vivo en una segunda lectura (no se auto-poda)
    assert ps.get_app_counts(r)["helpdesk"] == 1


def test_touch_retira_la_app_anterior_al_cambiar(r):
    ps.touch(r, 9910051, "staff", "helpdesk")
    ps.touch(r, 9910051, "staff", "maint", previous_app="helpdesk")
    counts = ps.get_app_counts(r)
    assert counts["helpdesk"] == 0   # sin fantasma en la app que ya cerró
    assert counts["maint"] == 1


def test_mark_offline_retira_de_los_dos_conjuntos(r):
    ps.touch(r, 9910061, "staff", "titulatec")
    ps.mark_offline(r, 9910061, "staff", "titulatec")
    assert ps.get_counts(r)["staff"] == 0
    assert ps.get_app_counts(r)["titulatec"] == 0


def test_mark_app_offline_no_toca_el_bucket(r):
    ps.touch(r, 9910071, "staff", "directory")
    ps.mark_app_offline(r, 9910071, "directory")
    assert ps.get_app_counts(r)["directory"] == 0
    assert ps.get_counts(r)["staff"] == 1


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
