"""Tests para itcj2.apps.maint.services.analysis_service.

Estrategia: testear helpers puros directamente, y endpoints públicos
(get_outliers, get_kmeans, get_distribution) con un Session mockeado
que devuelve filas predefinidas.
"""
import math
from datetime import date
from unittest.mock import MagicMock

import pytest

from itcj2.apps.maint.services import analysis_service as svc


# ─────────────────────────────────────────────────────────────────────
# Helpers puros
# ─────────────────────────────────────────────────────────────────────

class TestPercentile:
    def test_basic_quartiles(self):
        vals = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
        sorted_vals = sorted(vals)
        assert svc._percentile(sorted_vals, 25) == 3.25
        assert svc._percentile(sorted_vals, 50) == 5.5
        assert svc._percentile(sorted_vals, 75) == 7.75

    def test_empty(self):
        assert svc._percentile([], 50) == 0.0

    def test_single(self):
        assert svc._percentile([42], 99) == 42.0

    def test_max_percentile(self):
        assert svc._percentile([1, 2, 3], 100) == 3.0


class TestEuclidean:
    def test_known_distance(self):
        assert svc._euclidean([0.0, 0.0], [3.0, 4.0]) == pytest.approx(5.0)

    def test_zero_distance(self):
        assert svc._euclidean([1.0, 1.0, 1.0], [1.0, 1.0, 1.0]) == 0.0

    def test_3d(self):
        assert svc._euclidean([0, 0, 0], [1, 2, 2]) == pytest.approx(3.0)


class TestMeanCentroid:
    def test_basic(self):
        result = svc._mean_centroid([[0, 0], [2, 2], [4, 4]])
        assert result == [2.0, 2.0]

    def test_empty_returns_zero_3d(self):
        assert svc._mean_centroid([]) == [0.0, 0.0, 0.0]


class TestNormalize:
    def test_min_max(self):
        result = svc._normalize([0, 5, 10])
        assert result == [0.0, 0.5, 1.0]

    def test_all_same(self):
        result = svc._normalize([7, 7, 7])
        assert result == [0.5, 0.5, 0.5]


# ─────────────────────────────────────────────────────────────────────
# get_outliers — IQR sobre datos mockeados
# ─────────────────────────────────────────────────────────────────────

def _mock_db_with_rows(rows):
    """Crea un MagicMock Session cuyo query().filter().all() retorna rows."""
    db = MagicMock()
    chain = db.query.return_value.filter.return_value
    chain.all.return_value = rows
    return db


class TestGetOutliers:
    def test_no_outliers_in_uniform(self):
        rows = [(i, f"MANT-{i:06d}", float(10 + i)) for i in range(20)]
        db = _mock_db_with_rows(rows)
        result = svc.get_outliers(
            db, date(2026, 1, 1), date(2026, 12, 31), metric="time_invested"
        )
        data = result["data"]
        assert data["count_above"] == 0
        assert data["count_below"] == 0
        assert data["q1"] < data["q3"]

    def test_high_outlier(self):
        rows = [(i, f"MANT-{i:06d}", float(i)) for i in range(1, 11)]
        rows.append((99, "MANT-000099", 9999.0))  # outlier severo
        db = _mock_db_with_rows(rows)
        result = svc.get_outliers(
            db, date(2026, 1, 1), date(2026, 12, 31), metric="time_invested"
        )
        assert result["data"]["count_above"] >= 1
        # Sample contiene el outlier
        ids = [o["id"] for o in result["data"]["outliers_above"]]
        assert 99 in ids

    def test_empty_dataset(self):
        db = _mock_db_with_rows([])
        result = svc.get_outliers(
            db, date(2026, 1, 1), date(2026, 12, 31), metric="time_invested"
        )
        assert result["data"]["count_above"] == 0
        assert result["data"]["count_below"] == 0
        assert result["data"]["q1"] is None

    def test_invalid_metric_raises(self):
        db = _mock_db_with_rows([])
        with pytest.raises(ValueError, match="Métrica inválida"):
            svc.get_outliers(
                db, date(2026, 1, 1), date(2026, 12, 31), metric="bogus"
            )


# ─────────────────────────────────────────────────────────────────────
# get_kmeans — necesita query con 5 columnas (id, num, time, att, speed)
# ─────────────────────────────────────────────────────────────────────

def _mock_db_kmeans_rows(rows):
    db = MagicMock()
    chain = db.query.return_value.filter.return_value
    chain.all.return_value = rows
    return db


class TestGetKmeans:
    def test_three_distinct_clusters(self):
        # Cluster A: tiempo bajo, ratings altos
        # Cluster B: tiempo medio, ratings medios
        # Cluster C: tiempo alto, ratings bajos
        rows = []
        for i in range(10):
            rows.append((i, f"A-{i}", 30, 5, 5))
        for i in range(10, 20):
            rows.append((i, f"B-{i}", 120, 3, 3))
        for i in range(20, 30):
            rows.append((i, f"C-{i}", 600, 1, 1))

        db = _mock_db_kmeans_rows(rows)
        result = svc.get_kmeans(
            db, date(2026, 1, 1), date(2026, 12, 31), k=3
        )
        clusters = result["data"]["clusters"]
        assert len(clusters) == 3
        sizes = sorted(c["size"] for c in clusters)
        assert sizes == [10, 10, 10]

    def test_k_too_high(self):
        rows = [(1, "T-1", 100, 5, 5), (2, "T-2", 200, 4, 4)]
        db = _mock_db_kmeans_rows(rows)
        result = svc.get_kmeans(
            db, date(2026, 1, 1), date(2026, 12, 31), k=5
        )
        assert "note" in result["data"]
        assert "insuficientes" in result["data"]["note"].lower()

    def test_invalid_k_raises(self):
        db = _mock_db_kmeans_rows([])
        with pytest.raises(ValueError):
            svc.get_kmeans(db, date(2026, 1, 1), date(2026, 12, 31), k=0)
        with pytest.raises(ValueError):
            svc.get_kmeans(db, date(2026, 1, 1), date(2026, 12, 31), k=21)

    def test_deterministic_seed(self):
        rows = [(i, f"T-{i}", 50 + i * 10, 3 + (i % 3), 4 + (i % 2)) for i in range(15)]
        db1 = _mock_db_kmeans_rows(rows)
        db2 = _mock_db_kmeans_rows(rows)
        r1 = svc.get_kmeans(db1, date(2026, 1, 1), date(2026, 12, 31), k=3)
        r2 = svc.get_kmeans(db2, date(2026, 1, 1), date(2026, 12, 31), k=3)
        # Mismo seed (42) → mismas centroides
        for ca, cb in zip(r1["data"]["clusters"], r2["data"]["clusters"]):
            for x, y in zip(ca["centroid"], cb["centroid"]):
                assert math.isclose(x, y, rel_tol=1e-6)


# ─────────────────────────────────────────────────────────────────────
# get_distribution — histograma
# ─────────────────────────────────────────────────────────────────────

class TestGetDistribution:
    def test_uniform_histogram(self):
        rows = [(i, f"T-{i}", float(i)) for i in range(0, 100)]
        db = _mock_db_with_rows(rows)
        result = svc.get_distribution(
            db, date(2026, 1, 1), date(2026, 12, 31),
            metric="time_invested", bins=10,
        )
        bins = result["data"]["bins"]
        assert len(bins) == 10
        assert sum(b["count"] for b in bins) == 100
        # Bins ordenados sin gap
        for i in range(len(bins) - 1):
            assert bins[i]["upper"] == pytest.approx(bins[i + 1]["lower"])

    def test_all_same_value_one_bin(self):
        rows = [(i, f"T-{i}", 42.0) for i in range(5)]
        db = _mock_db_with_rows(rows)
        result = svc.get_distribution(
            db, date(2026, 1, 1), date(2026, 12, 31),
            metric="time_invested", bins=5,
        )
        # Cuando min==max el servicio devuelve 1 solo bin
        assert result["bins"] == 1
        assert result["data"]["bins"][0]["count"] == 5

    def test_empty(self):
        db = _mock_db_with_rows([])
        result = svc.get_distribution(
            db, date(2026, 1, 1), date(2026, 12, 31),
            metric="time_invested", bins=10,
        )
        assert result["data"]["bins"] == []

    def test_invalid_bins(self):
        db = _mock_db_with_rows([])
        with pytest.raises(ValueError):
            svc.get_distribution(
                db, date(2026, 1, 1), date(2026, 12, 31),
                metric="time_invested", bins=1,
            )
        with pytest.raises(ValueError):
            svc.get_distribution(
                db, date(2026, 1, 1), date(2026, 12, 31),
                metric="time_invested", bins=101,
            )

    def test_invalid_metric(self):
        db = _mock_db_with_rows([])
        with pytest.raises(ValueError):
            svc.get_distribution(
                db, date(2026, 1, 1), date(2026, 12, 31),
                metric="invalid", bins=10,
            )
