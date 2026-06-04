"""Tests del servicio de días de cotejo."""
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

import itcj2.models  # noqa: F401
from itcj2.apps.titulatec.services.review_day_service import ReviewDayService


def test_set_days_sincroniza():
    """Borra las fechas que sobran y agrega las nuevas."""
    db = MagicMock()
    existing = [SimpleNamespace(date=date(2026, 6, 15)), SimpleNamespace(date=date(2026, 6, 16))]
    db.query.return_value.filter_by.return_value.all.return_value = existing
    ReviewDayService.set_days(db, cohort_id=1,
                              dates={date(2026, 6, 16), date(2026, 6, 17)}, created_by_id=7)
    db.commit.assert_called_once()


def test_is_allowed_true_false():
    db = MagicMock()
    db.query.return_value.filter_by.return_value.first.return_value = object()
    assert ReviewDayService.is_allowed(db, 1, date(2026, 6, 15)) is True
    db.query.return_value.filter_by.return_value.first.return_value = None
    assert ReviewDayService.is_allowed(db, 1, date(2026, 6, 20)) is False
