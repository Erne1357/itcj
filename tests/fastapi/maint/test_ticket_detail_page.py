"""Contexto JS (TICKET_CTX) que la plantilla del detalle de ticket entrega al front.

El backend deja resolver a cualquier técnico ACTIVO del ticket que tenga
`maint.tickets.api.resolve` — los coordinadores (general y de área) lo tienen
y pueden asignarse como ejecutores. El botón «Resolver» depende de
`TICKET_CTX.canResolve`, así que la plantilla debe encenderlo también para ellos.
"""
import re

import pytest

from itcj2.apps.maint.pages.nav import maint_templates


def _render_page_vars(user_roles):
    template = maint_templates.env.get_template("maint/tickets/detail.html")
    ctx = template.new_context({
        "ticket_id": 1,
        "current_user": {"sub": "10"},
        "user_roles": user_roles,
        "can_assign": False,
    })
    return "".join(template.blocks["page_vars"](ctx))


def _can_resolve(user_roles) -> bool:
    match = re.search(r"canResolve:\s*(true|false)", _render_page_vars(user_roles))
    assert match, "TICKET_CTX.canResolve no aparece en la plantilla"
    return match.group(1) == "true"


@pytest.mark.parametrize("roles", [
    ["tech_maint"],
    ["dispatcher"],
    ["admin"],
    ["maint_general_coordinator"],
    ["maint_area_coordinator"],
])
def test_can_resolve_for_executor_roles(roles):
    assert _can_resolve(roles) is True


@pytest.mark.parametrize("roles", [
    ["department_head"],
    ["secretary"],
    ["staff"],
    [],
])
def test_cannot_resolve_for_requester_roles(roles):
    assert _can_resolve(roles) is False
