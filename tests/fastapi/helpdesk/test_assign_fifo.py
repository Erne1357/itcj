"""
FIFO en la pantalla de asignación (`/help-desk/admin/assign-tickets`).

Las tres listas server-side (Cola, Asignados, En proceso) se piden con
`sort="oldest"` tanto en la página completa como en el fragmento `?tab=`, y la
alerta de urgentes del JS se ordena por `created_at` ascendente.

No hay BD: se parchea `itcj2.database.SessionLocal` (la función la abre con
import local) y `ticket_service.list_tickets`.
"""
import re
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from itcj2.apps.helpdesk.pages.admin import _query_assign_lists_ctx

LIST_TICKETS = "itcj2.apps.helpdesk.services.ticket_service.list_tickets"
SESSION_LOCAL = "itcj2.database.SessionLocal"
JS_PATH = (
    Path(__file__).resolve().parents[3]
    / "itcj2/apps/helpdesk/static/js/admin/assign_tickets.js"
)


@pytest.fixture
def mock_list_tickets():
    with patch(SESSION_LOCAL, MagicMock()), \
         patch(LIST_TICKETS, return_value={"tickets": []}) as m:
        yield m


def test_pagina_completa_pide_las_tres_listas_en_fifo(mock_list_tickets):
    _query_assign_lists_ctx(None, 1, set())

    assert mock_list_tickets.call_count == 3
    for call in mock_list_tickets.call_args_list:
        assert call.kwargs.get("sort") == "oldest"


@pytest.mark.parametrize("tab", ["queue", "assigned", "inprogress"])
def test_fragmento_por_tab_en_fifo(mock_list_tickets, tab):
    _query_assign_lists_ctx(None, 1, set(), tab=tab)

    assert mock_list_tickets.call_count == 1
    assert mock_list_tickets.call_args.kwargs.get("sort") == "oldest"


def test_alerta_urgentes_ordena_por_antiguedad():
    src = JS_PATH.read_text(encoding="utf-8")
    start = src.index("async function loadDashboardStats")
    end = src.index("function showUrgentAlert")
    body = src[start:end]

    sort_match = re.search(r"\.sort\(\s*\(a,\s*b\)\s*=>\s*new Date\(a\.created_at\)\s*-\s*new Date\(b\.created_at\)\s*\)", body)
    assert sort_match, "urgentTickets debe ordenarse por created_at ASC en loadDashboardStats"
    assert sort_match.start() < body.index("showUrgentAlert(urgentTickets)")
