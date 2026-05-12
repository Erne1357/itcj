"""
Tests unitarios para itcj2/apps/helpdesk/utils/catalog_cache.py

Cubre:
- get_priority_codes(db) cachea; segunda llamada NO golpea BD
- invalidate_priorities() limpia cache; siguiente llamada SÍ golpea BD
- Mismo para statuses, transitions, areas, notification_templates
- Fallback defensivo de areas: si BD inalcanzable, devuelve {'DESARROLLO','SOPORTE'}
- get_status_flags(code) abre sesión efímera si cache vacío
- is_transition_allowed self-transition siempre True (from == to)
"""
from unittest.mock import MagicMock, patch, call

import pytest


# =============================================================================
# Helpers
# =============================================================================

def _make_mock_priority(code: str, sla_hours: int = 24, is_active: bool = True):
    m = MagicMock()
    m.code = code
    m.sla_hours = sla_hours
    m.is_active = is_active
    m.display_order = 1
    m.to_dict.return_value = {
        "code": code,
        "sla_hours": sla_hours,
        "is_active": is_active,
        "display_order": 1,
    }
    return m


def _make_mock_status(code: str, is_active: bool = True, is_terminal: bool = False):
    m = MagicMock()
    m.code = code
    m.is_active = is_active
    m.is_terminal = is_terminal
    m.display_order = 1
    m.to_dict.return_value = {
        "code": code,
        "is_active": is_active,
        "is_terminal": is_terminal,
        "display_order": 1,
    }
    return m


def _make_mock_area(code: str, is_active: bool = True):
    m = MagicMock()
    m.code = code
    m.is_active = is_active
    m.display_order = 1
    m.to_dict.return_value = {"code": code, "is_active": is_active, "display_order": 1}
    return m


def _make_mock_template(code: str, is_active: bool = True):
    m = MagicMock()
    m.code = code
    m.is_active = is_active
    m.to_dict.return_value = {"code": code, "is_active": is_active}
    return m


def _make_db_mock_for(model_module_path: str, items: list):
    """Crea un mock de db.query(...).order_by(...).all() que devuelve items."""
    db = MagicMock()
    chain = MagicMock()
    chain.order_by.return_value = chain
    chain.filter_by.return_value = chain
    chain.all.return_value = items
    db.query.return_value = chain
    return db


# =============================================================================
# Prioridades
# =============================================================================

class TestPrioritiesCache:
    def setup_method(self):
        """Limpia el cache antes de cada test."""
        import itcj2.apps.helpdesk.utils.catalog_cache as cc
        cc._PRIORITIES_BY_CODE = None

    def test_get_priorities_loads_from_db_on_first_call(self):
        """Con cache vacío, get_priorities() llama a db.query para cargar datos."""
        import itcj2.apps.helpdesk.utils.catalog_cache as cc

        mock_p = _make_mock_priority("ALTA")
        db = MagicMock()
        db.query.return_value.order_by.return_value.all.return_value = [mock_p]

        # _ensure_loaded importa Priority en su body — no necesita patch en catalog_cache
        result = cc.get_priorities(db)
        assert db.query.called
        # El cache ahora tiene "ALTA"
        assert "ALTA" in cc._PRIORITIES_BY_CODE

    def test_get_priorities_second_call_does_not_hit_db(self):
        """Con cache poblado, segunda llamada a get_priorities() NO golpea BD."""
        import itcj2.apps.helpdesk.utils.catalog_cache as cc

        mock_p = _make_mock_priority("BAJA")
        db = MagicMock()
        db.query.return_value.order_by.return_value.all.return_value = [mock_p]

        # Primera llamada llena el cache
        cc.get_priorities(db)
        call_count_after_first = db.query.call_count

        # Segunda llamada — no debe tocar BD
        cc.get_priorities(db)
        assert db.query.call_count == call_count_after_first

    def test_invalidate_priorities_clears_cache(self):
        import itcj2.apps.helpdesk.utils.catalog_cache as cc

        # Llenar el cache manualmente
        cc._PRIORITIES_BY_CODE = {"BAJA": {"code": "BAJA", "is_active": True}}
        assert cc._PRIORITIES_BY_CODE is not None

        cc.invalidate_priorities()
        assert cc._PRIORITIES_BY_CODE is None

    def test_get_priority_codes_active_only(self):
        import itcj2.apps.helpdesk.utils.catalog_cache as cc

        cc._PRIORITIES_BY_CODE = {
            "ALTA": {"code": "ALTA", "is_active": True},
            "BAJA": {"code": "BAJA", "is_active": False},
        }
        db = MagicMock()

        codes = cc.get_priority_codes(db, active_only=True)
        assert "ALTA" in codes
        assert "BAJA" not in codes

    def test_get_priority_codes_include_inactive(self):
        import itcj2.apps.helpdesk.utils.catalog_cache as cc

        cc._PRIORITIES_BY_CODE = {
            "ALTA": {"code": "ALTA", "is_active": True},
            "BAJA": {"code": "BAJA", "is_active": False},
        }
        db = MagicMock()

        codes = cc.get_priority_codes(db, active_only=False)
        assert "ALTA" in codes
        assert "BAJA" in codes

    def test_get_sla_hours_returns_correct_value(self):
        import itcj2.apps.helpdesk.utils.catalog_cache as cc

        cc._PRIORITIES_BY_CODE = {
            "URGENTE": {"code": "URGENTE", "sla_hours": 4, "is_active": True}
        }
        db = MagicMock()

        assert cc.get_sla_hours(db, "URGENTE") == 4

    def test_get_sla_hours_returns_none_for_unknown(self):
        import itcj2.apps.helpdesk.utils.catalog_cache as cc

        cc._PRIORITIES_BY_CODE = {}
        db = MagicMock()

        assert cc.get_sla_hours(db, "UNKNOWN") is None

    def teardown_method(self):
        import itcj2.apps.helpdesk.utils.catalog_cache as cc
        cc._PRIORITIES_BY_CODE = None


# =============================================================================
# Estados (TicketStatus)
# =============================================================================

class TestStatusesCache:
    def setup_method(self):
        import itcj2.apps.helpdesk.utils.catalog_cache as cc
        cc._STATUSES_BY_CODE = None

    def test_get_statuses_loads_on_first_call(self):
        import itcj2.apps.helpdesk.utils.catalog_cache as cc

        mock_s = _make_mock_status("PENDING")
        db = MagicMock()
        db.query.return_value.order_by.return_value.all.return_value = [mock_s]

        with patch("itcj2.apps.helpdesk.utils.catalog_cache.TicketStatus", create=True):
            cc._ensure_statuses_loaded(db)

        assert db.query.called

    def test_invalidate_statuses_clears_cache(self):
        import itcj2.apps.helpdesk.utils.catalog_cache as cc

        cc._STATUSES_BY_CODE = {"PENDING": {"code": "PENDING", "is_active": True}}
        cc.invalidate_statuses()
        assert cc._STATUSES_BY_CODE is None

    def test_get_status_codes_active_only(self):
        import itcj2.apps.helpdesk.utils.catalog_cache as cc

        cc._STATUSES_BY_CODE = {
            "PENDING": {"code": "PENDING", "is_active": True},
            "CLOSED": {"code": "CLOSED", "is_active": False},
        }
        db = MagicMock()
        codes = cc.get_status_codes(db, active_only=True)
        assert "PENDING" in codes
        assert "CLOSED" not in codes

    def test_second_call_does_not_hit_db(self):
        import itcj2.apps.helpdesk.utils.catalog_cache as cc

        cc._STATUSES_BY_CODE = {"PENDING": {"code": "PENDING", "is_active": True}}
        db = MagicMock()

        cc.get_statuses(db)
        cc.get_statuses(db)
        # Con cache ya poblado, db.query NO debe llamarse
        assert not db.query.called

    def teardown_method(self):
        import itcj2.apps.helpdesk.utils.catalog_cache as cc
        cc._STATUSES_BY_CODE = None


# =============================================================================
# Transiciones (StatusTransition)
# =============================================================================

class TestTransitionsCache:
    def setup_method(self):
        import itcj2.apps.helpdesk.utils.catalog_cache as cc
        cc._TRANSITIONS_BY_FROM_CODE = None
        cc._TRANSITIONS_FULL = None

    def test_is_transition_allowed_self_transition_always_true(self):
        import itcj2.apps.helpdesk.utils.catalog_cache as cc

        db = MagicMock()
        # from == to → siempre permitido sin consultar BD
        assert cc.is_transition_allowed(db, "PENDING", "PENDING") is True
        assert not db.query.called

    def test_is_transition_allowed_with_cached_data(self):
        import itcj2.apps.helpdesk.utils.catalog_cache as cc

        cc._TRANSITIONS_BY_FROM_CODE = {"PENDING": {"ASSIGNED"}}
        cc._TRANSITIONS_FULL = {("PENDING", "ASSIGNED"): {"from_code": "PENDING"}}
        db = MagicMock()

        assert cc.is_transition_allowed(db, "PENDING", "ASSIGNED") is True
        assert cc.is_transition_allowed(db, "PENDING", "CLOSED") is False

    def test_invalidate_transitions_clears_both_indexes(self):
        import itcj2.apps.helpdesk.utils.catalog_cache as cc

        cc._TRANSITIONS_BY_FROM_CODE = {"A": {"B"}}
        cc._TRANSITIONS_FULL = {("A", "B"): {}}
        cc.invalidate_transitions()

        assert cc._TRANSITIONS_BY_FROM_CODE is None
        assert cc._TRANSITIONS_FULL is None

    def test_get_allowed_transitions_returns_empty_set_for_unknown(self):
        import itcj2.apps.helpdesk.utils.catalog_cache as cc

        cc._TRANSITIONS_BY_FROM_CODE = {}
        cc._TRANSITIONS_FULL = {}
        db = MagicMock()

        result = cc.get_allowed_transitions(db, "NONEXISTENT")
        assert result == set()

    def teardown_method(self):
        import itcj2.apps.helpdesk.utils.catalog_cache as cc
        cc._TRANSITIONS_BY_FROM_CODE = None
        cc._TRANSITIONS_FULL = None


# =============================================================================
# Áreas
# =============================================================================

class TestAreasCache:
    def setup_method(self):
        import itcj2.apps.helpdesk.utils.catalog_cache as cc
        cc._AREAS_BY_CODE = None

    def test_get_area_codes_loads_from_db(self):
        import itcj2.apps.helpdesk.utils.catalog_cache as cc

        mock_a = _make_mock_area("DESARROLLO")
        db = MagicMock()
        db.query.return_value.order_by.return_value.all.return_value = [mock_a]

        with patch("itcj2.apps.helpdesk.utils.catalog_cache.Area", create=True):
            cc._ensure_areas_loaded(db)

        assert db.query.called

    def test_fallback_when_db_unreachable(self):
        """Si la BD lanza excepción, get_area_codes devuelve {'DESARROLLO','SOPORTE'}."""
        import itcj2.apps.helpdesk.utils.catalog_cache as cc

        cc._AREAS_BY_CODE = None
        db = MagicMock()
        db.query.side_effect = Exception("DB connection failed")

        result = cc.get_area_codes(db)
        assert result == {"DESARROLLO", "SOPORTE"}

    def test_fallback_with_none_db(self):
        """get_area_codes(None) con cache vacío devuelve {'DESARROLLO','SOPORTE'}."""
        import itcj2.apps.helpdesk.utils.catalog_cache as cc

        cc._AREAS_BY_CODE = None
        # db=None lanzará AttributeError al intentar query → fallback
        result = cc.get_area_codes(None)
        assert result == {"DESARROLLO", "SOPORTE"}

    def test_fallback_when_cache_empty_dict(self):
        """Cache poblado vacío (sin áreas) también devuelve fallback."""
        import itcj2.apps.helpdesk.utils.catalog_cache as cc

        cc._AREAS_BY_CODE = {}  # cache vacío
        db = MagicMock()

        result = cc.get_area_codes(db)
        assert result == {"DESARROLLO", "SOPORTE"}

    def test_invalidate_areas_clears_cache(self):
        import itcj2.apps.helpdesk.utils.catalog_cache as cc

        cc._AREAS_BY_CODE = {"DESARROLLO": {"code": "DESARROLLO", "is_active": True}}
        cc.invalidate_areas()
        assert cc._AREAS_BY_CODE is None

    def test_second_call_uses_cache(self):
        import itcj2.apps.helpdesk.utils.catalog_cache as cc

        cc._AREAS_BY_CODE = {
            "DESARROLLO": {"code": "DESARROLLO", "is_active": True, "display_order": 1}
        }
        db = MagicMock()

        cc.get_areas(db)
        cc.get_areas(db)
        assert not db.query.called  # cache ya estaba listo

    def teardown_method(self):
        import itcj2.apps.helpdesk.utils.catalog_cache as cc
        cc._AREAS_BY_CODE = None


# =============================================================================
# Notification Templates
# =============================================================================

class TestNotificationTemplatesCache:
    def setup_method(self):
        import itcj2.apps.helpdesk.utils.catalog_cache as cc
        cc._NOTIFICATION_TEMPLATES_BY_CODE = None

    def test_get_notification_template_loads_from_db(self):
        import itcj2.apps.helpdesk.utils.catalog_cache as cc

        mock_t = _make_mock_template("ticket_created")
        db = MagicMock()
        db.query.return_value.all.return_value = [mock_t]

        with patch("itcj2.apps.helpdesk.utils.catalog_cache.NotificationTemplate", create=True):
            cc._ensure_notification_templates_loaded(db)

        assert db.query.called

    def test_get_notification_template_returns_none_for_inactive(self):
        """Plantilla is_active=False devuelve None (no debe usarse)."""
        import itcj2.apps.helpdesk.utils.catalog_cache as cc

        cc._NOTIFICATION_TEMPLATES_BY_CODE = {
            "ticket_created": {"code": "ticket_created", "is_active": False}
        }
        db = MagicMock()

        result = cc.get_notification_template(db, "ticket_created")
        assert result is None

    def test_get_notification_template_returns_active(self):
        import itcj2.apps.helpdesk.utils.catalog_cache as cc

        cc._NOTIFICATION_TEMPLATES_BY_CODE = {
            "ticket_resolved": {"code": "ticket_resolved", "is_active": True}
        }
        db = MagicMock()

        result = cc.get_notification_template(db, "ticket_resolved")
        assert result is not None
        assert result["code"] == "ticket_resolved"

    def test_invalidate_notification_templates_clears_cache(self):
        import itcj2.apps.helpdesk.utils.catalog_cache as cc

        cc._NOTIFICATION_TEMPLATES_BY_CODE = {"x": {"code": "x"}}
        cc.invalidate_notification_templates()
        assert cc._NOTIFICATION_TEMPLATES_BY_CODE is None

    def test_second_call_uses_cache_not_db(self):
        import itcj2.apps.helpdesk.utils.catalog_cache as cc

        cc._NOTIFICATION_TEMPLATES_BY_CODE = {
            "ticket_created": {"code": "ticket_created", "is_active": True}
        }
        db = MagicMock()

        cc.get_notification_templates(db)
        cc.get_notification_templates(db)
        assert not db.query.called

    def teardown_method(self):
        import itcj2.apps.helpdesk.utils.catalog_cache as cc
        cc._NOTIFICATION_TEMPLATES_BY_CODE = None
