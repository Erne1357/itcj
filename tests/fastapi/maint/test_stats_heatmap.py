"""Tests para heatmap de stats (location y building)."""
from datetime import date
from unittest.mock import MagicMock

import pytest

import itcj2.models  # noqa: F401

from itcj2.apps.maint.services import stats_service as ss


def _row(loc, cat_id, cnt):
    """Fila tipo MaintTicket query result."""
    r = MagicMock()
    r.loc = loc
    r.category_id = cat_id
    r.cnt = cnt
    return r


def _row_building(location, month, cnt):
    r = MagicMock()
    r.location = location
    r.month = month
    r.cnt = cnt
    return r


def _mock_db(query_rows, category_objs=None):
    """Mock que retorna query_rows en .all() y categorías cuando se piden."""
    db = MagicMock()
    call_state = {"i": 0}

    def _query_side_effect(*args, **kwargs):
        chain = MagicMock()
        if args and hasattr(args[0], "__name__") and args[0].__name__ == "MaintCategory":
            chain.filter.return_value.all.return_value = category_objs or []
        else:
            chain.filter.return_value.group_by.return_value.all.return_value = query_rows
        return chain

    db.query.side_effect = _query_side_effect
    return db


class TestHeatmapByLocation:
    def test_basic_aggregation(self):
        rows = [
            _row("aula 1", 1, 5),
            _row("aula 1", 2, 2),
            _row("lab 5", 1, 3),
        ]
        cat1 = MagicMock(id=1)
        cat1.name = "Eléctrico"
        cat2 = MagicMock(id=2)
        cat2.name = "AC"
        db = _mock_db(rows, [cat1, cat2])

        result = ss.get_heatmap_by_location(
            db, date(2026, 1, 1), date(2026, 12, 31), top_n=10
        )
        assert result["group_by"] == "location"
        assert "axes" in result
        assert "matrix" in result
        # Top 1 location is "aula 1" (5+2=7)
        assert result["axes"]["y"][0] == "aula 1"

    def test_empty(self):
        db = _mock_db([])
        result = ss.get_heatmap_by_location(
            db, date(2026, 1, 1), date(2026, 12, 31)
        )
        assert result["matrix"] == []
        assert result["axes"]["y"] == []

    def test_respects_top_n(self):
        # 5 ubicaciones, top_n=2 → solo 2 en la respuesta
        rows = [_row(f"loc-{i}", 1, 10 - i) for i in range(5)]
        cat = MagicMock(id=1)
        cat.name = "Cat1"
        db = _mock_db(rows, [cat])

        result = ss.get_heatmap_by_location(
            db, date(2026, 1, 1), date(2026, 12, 31), top_n=2
        )
        assert len(result["axes"]["y"]) == 2
        # Top 2 = loc-0 (10), loc-1 (9)
        assert result["axes"]["y"][0] == "loc-0"
        assert result["axes"]["y"][1] == "loc-1"


class TestHeatmapByBuilding:
    def test_uses_location_parser(self):
        rows = [
            _row_building("Edificio A — aula 12", "2026-01", 4),
            _row_building("Edificio A planta 2", "2026-02", 2),
            _row_building("Lab 5", "2026-01", 3),
            _row_building("Cancha de fútbol", "2026-01", 1),
        ]
        db = _mock_db(rows)

        result = ss.get_heatmap_by_building(
            db, date(2026, 1, 1), date(2026, 12, 31)
        )
        assert result["group_by"] == "building"
        # Edificio A debe agruparse en una sola fila aunque vienen 2 raw rows
        buildings = result["axes"]["y"]
        assert "Edificio A" in buildings
        assert "Lab 5" in buildings
        # "Cancha…" no matchea regex → "Sin clasificar"
        assert "Sin clasificar" in buildings

    def test_unclassified_at_bottom(self):
        rows = [
            _row_building("Pasillo", "2026-01", 1),
            _row_building("Edificio Z", "2026-01", 1),
        ]
        db = _mock_db(rows)

        result = ss.get_heatmap_by_building(
            db, date(2026, 1, 1), date(2026, 12, 31)
        )
        # "Sin clasificar" debe estar al final del eje Y
        assert result["axes"]["y"][-1] == "Sin clasificar"

    def test_empty(self):
        db = _mock_db([])
        result = ss.get_heatmap_by_building(
            db, date(2026, 1, 1), date(2026, 12, 31)
        )
        assert result["matrix"] == []
