"""Presencia de revisión («quién lo está revisando», fase 3 §8.3).

`fakeredis` no está instalado en el contenedor: doble mínimo con hash,
expire y pipeline.
"""
from __future__ import annotations

import pytest

from itcj2.apps.titulatec.services import review_presence as mod
from itcj2.apps.titulatec.services.review_presence import ReviewPresence


class _Pipe:
    def __init__(self, r):
        self.r, self.ops = r, []

    def __getattr__(self, name):
        def _q(*a):
            self.ops.append((name, a))
            return self
        return _q

    def execute(self):
        self.r.round_trips += 1
        return [getattr(self.r, n)(*a) for n, a in self.ops]


class FakeRedis:
    def __init__(self):
        self.h, self.ttl, self.round_trips = {}, {}, 0

    def pipeline(self):
        return _Pipe(self)

    def hset(self, key, field, value):
        self.h.setdefault(key, {})[field] = value

    def expire(self, key, secs):
        self.ttl[key] = secs

    def hgetall(self, key):
        return dict(self.h.get(key, {}))

    def hdel(self, key, field):
        self.h.get(key, {}).pop(field, None)

    def keys(self, *a):
        raise AssertionError("nunca KEYS")

    scan = scan_iter = keys


@pytest.fixture()
def redis_falso(monkeypatch):
    r = FakeRedis()
    monkeypatch.setattr("itcj2.core.utils.redis_conn.get_redis", lambda: r)
    reloj = {"t": 1_000_000.0}
    monkeypatch.setattr(mod, "_now", lambda: reloj["t"])
    r.reloj = reloj
    return r


def test_viewers_excluye_al_propio_usuario(redis_falso):
    ReviewPresence.touch("format_b", 10, 1, "Luis")
    ReviewPresence.touch("format_b", 10, 2, "Ana")
    ReviewPresence.touch("format_b", 11, 1, "Luis")
    assert ReviewPresence.viewers("format_b", [10, 11, 12], exclude_user_id=1) == {10: ["Ana"]}
    assert ReviewPresence.viewers("format_b", [10], exclude_user_id=2) == {10: ["Luis"]}


def test_la_marca_expira_a_los_120_s_y_el_hash_lleva_expire_300(redis_falso):
    ReviewPresence.touch("format_b", 10, 2, "Ana")
    assert redis_falso.ttl["titulatec:presence:format_b:10"] == 300
    redis_falso.reloj["t"] += 119
    assert ReviewPresence.viewers("format_b", [10], 1) == {10: ["Ana"]}
    redis_falso.reloj["t"] += 2
    assert ReviewPresence.viewers("format_b", [10], 1) == {}
    # renovar la devuelve
    ReviewPresence.touch("format_b", 10, 2, "Ana")
    assert ReviewPresence.viewers("format_b", [10], 1) == {10: ["Ana"]}


def test_clear_borra_la_marca(redis_falso):
    ReviewPresence.touch("format_b", 10, 2, "Ana")
    ReviewPresence.clear("format_b", 10, 2)
    assert ReviewPresence.viewers("format_b", [10], 1) == {}


def test_una_sola_ida_por_pagina(redis_falso):
    ReviewPresence.touch("format_b", 10, 2, "Ana")
    redis_falso.round_trips = 0
    ReviewPresence.viewers("format_b", range(1, 51), 1)
    assert redis_falso.round_trips == 1
    ReviewPresence.viewers("format_b", [], 1)            # sin ids: ninguna ida
    assert redis_falso.round_trips == 1


def test_el_kind_aisla_las_marcas(redis_falso):
    ReviewPresence.touch("format_b", 10, 2, "Ana")
    assert ReviewPresence.viewers("anexo_iii", [10], 1) == {}


def test_redis_que_lanza_es_no_op(monkeypatch, caplog):
    def boom():
        raise ConnectionError("caido")
    monkeypatch.setattr("itcj2.core.utils.redis_conn.get_redis", boom)
    with caplog.at_level("WARNING"):
        ReviewPresence.touch("format_b", 10, 2, "Ana")
        ReviewPresence.clear("format_b", 10, 2)
        assert ReviewPresence.viewers("format_b", [10], 1) == {}
    assert sum("presencia" in r.message for r in caplog.records) == 3


def test_basura_en_el_hash_se_ignora(redis_falso):
    redis_falso.hset("titulatec:presence:format_b:10", "7", "no-es-json")
    ReviewPresence.touch("format_b", 10, 2, "Ana")
    assert ReviewPresence.viewers("format_b", [10], 1) == {10: ["Ana"]}
