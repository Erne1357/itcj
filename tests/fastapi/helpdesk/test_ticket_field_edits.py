"""Task 2 (7) de la feature "Partir ticket": extrae la validacion + mutacion +
auditoria de `update_pending_ticket` a una funcion reutilizable
`apply_ticket_field_edits(db, ticket, updated_by_id, *, area, category_id,
priority, title, description, location) -> int`, para que el servicio de
split (Task 3) pueda editar el ticket original en ASSIGNED/IN_PROGRESS con
las MISMAS reglas que el flujo "Editar" existente (que solo opera sobre
PENDING).

Este archivo se escribio y corrio en VERDE contra el codigo ACTUAL, ANTES del
refactor (ver task-2-report.md para la evidencia) — es la red de seguridad
del refactor sin cambio de conducta. `TestUpdatePendingTicketCharacterization`
caracteriza el contrato publico de `update_pending_ticket` tal cual existe
hoy; `TestApplyTicketFieldEditsDirect` prueba la funcion NUEVA que el
refactor introduce (contra el codigo actual estos fallan con AttributeError
— `ticket_service` todavia no la expone — esa es la evidencia RED).

Se importa el MODULO (`ticket_service`), no la funcion, para que la resolucion
de `apply_ticket_field_edits` ocurra en tiempo de llamada y no de import: asi
un `pytest -k Characterization` corre limpio incluso antes de que la funcion
exista, sin tumbar la coleccion de todo el archivo por un ImportError.

Cubre:
  * `update_pending_ticket` sobre un ticket ASSIGNED -> 400.
  * `update_pending_ticket` sobre un ticket inexistente -> 404.
  * Cambiar titulo+descripcion en PENDING -> 2 `TicketEditLog` + `updated_by_id`,
    y el cambio sobrevive a un rollback (prueba que update_pending_ticket hace commit).
  * Cambiar de categoria con `custom_fields` poblado -> quedan `{}` + log de
    `custom_fields` ademas del de `category_id`.
  * Area nueva sin categoria -> 400.
  * Sin cambios -> 0 `TicketEditLog`.
  * `apply_ticket_field_edits` funciona directo sobre un ticket ASSIGNED (no
    revisa estado) y NO commitea (el cambio desaparece tras
    `db_session.rollback()`).
"""
from fastapi import HTTPException
import pytest

from itcj2.apps.helpdesk.models.ticket import Ticket
from itcj2.apps.helpdesk.models.ticket_edit_log import TicketEditLog
from itcj2.apps.helpdesk.services import ticket_service
from itcj2.core.models.user import User

from ._catalog import ensure_helpdesk_category


# ─────────────────────────── infraestructura de test ───────────────────────────

def _user(db, last) -> User:
    u = User(first_name="T", last_name=last, is_active=True)
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _ticket(db, number, requester, category, **overrides) -> Ticket:
    defaults = dict(
        ticket_number=number,
        requester_id=requester.id,
        requester_department_id=None,
        area="SOPORTE",
        category_id=category.id,
        priority="MEDIA",
        title=f"{number} - ticket de prueba",
        description="Descripcion de prueba con longitud suficiente para pasar validaciones.",
        status="PENDING",
        created_by_id=requester.id,
        updated_by_id=requester.id,
    )
    defaults.update(overrides)
    t = Ticket(**defaults)
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


def _edit_logs(db, ticket_id) -> list[TicketEditLog]:
    return (
        db.query(TicketEditLog)
        .filter_by(ticket_id=ticket_id)
        .order_by(TicketEditLog.id)
        .all()
    )


# ────────────────────── caracterizacion: update_pending_ticket ──────────────────────

class TestUpdatePendingTicketCharacterization:
    """Contrato publico ACTUAL de `update_pending_ticket` — debe seguir en
    verde despues del refactor sin tocar una sola linea de estos tests."""

    def test_ticket_not_found_returns_404(self, db_session):
        editor = _user(db_session, "EditorMissing")

        with pytest.raises(HTTPException) as exc_info:
            ticket_service.update_pending_ticket(db_session, 999_999_999, editor.id)

        assert exc_info.value.status_code == 404
        assert exc_info.value.detail == "Ticket no encontrado"

    def test_ticket_not_pending_returns_400(self, db_session):
        editor = _user(db_session, "EditorAssigned")
        category = ensure_helpdesk_category(db_session, code="tfe_char_assigned", area="SOPORTE")
        ticket = _ticket(db_session, "TFE-CHAR-1", editor, category, status="ASSIGNED")

        with pytest.raises(HTTPException) as exc_info:
            ticket_service.update_pending_ticket(db_session, ticket.id, editor.id)

        assert exc_info.value.status_code == 400
        assert exc_info.value.detail == "Solo se pueden editar tickets en estado PENDING"

    def test_title_and_description_change_creates_two_logs_and_sets_updated_by(self, db_session):
        creator = _user(db_session, "CreatorTD")
        editor = _user(db_session, "EditorTD")
        category = ensure_helpdesk_category(db_session, code="tfe_char_title_desc", area="SOPORTE")
        ticket = _ticket(db_session, "TFE-CHAR-2", creator, category)
        original_title = ticket.title
        original_description = ticket.description
        new_title = "Titulo nuevo con longitud valida"
        new_description = (
            "Descripcion nueva con longitud suficiente para pasar la "
            "validacion de veinte caracteres."
        )

        result = ticket_service.update_pending_ticket(
            db_session, ticket.id, editor.id,
            title=new_title,
            description=new_description,
        )

        assert result.title == new_title
        assert result.description == new_description
        assert result.updated_by_id == editor.id

        logs = _edit_logs(db_session, ticket.id)
        assert [l.field_name for l in logs] == ["title", "description"]
        assert logs[0].old_value == original_title
        assert logs[0].new_value == new_title
        assert logs[1].old_value == original_description
        assert logs[1].new_value == new_description
        assert all(l.changed_by_id == editor.id for l in logs)

        # A diferencia de `apply_ticket_field_edits` (ver
        # TestApplyTicketFieldEditsDirect.test_does_not_commit),
        # `update_pending_ticket` SI hace commit: el cambio debe sobrevivir a
        # un rollback posterior.
        db_session.rollback()
        assert ticket.title == new_title

    def test_category_change_clears_custom_fields_and_logs_it(self, db_session):
        editor = _user(db_session, "EditorCat")
        old_category = ensure_helpdesk_category(db_session, code="tfe_char_cat_old", area="SOPORTE")
        new_category = ensure_helpdesk_category(db_session, code="tfe_char_cat_new", area="SOPORTE")
        original_custom_fields = {"campo_x": "valor_x"}
        ticket = _ticket(
            db_session, "TFE-CHAR-3", editor, old_category,
            custom_fields=original_custom_fields,
        )

        result = ticket_service.update_pending_ticket(
            db_session, ticket.id, editor.id,
            category_id=new_category.id,
        )

        assert result.category_id == new_category.id
        assert result.custom_fields == {}

        logs = _edit_logs(db_session, ticket.id)
        assert [l.field_name for l in logs] == ["category_id", "custom_fields"]
        assert logs[0].old_value == old_category.name
        assert logs[0].new_value == new_category.name
        assert logs[1].old_value == str(original_custom_fields)
        assert logs[1].new_value == "{}"

    def test_new_area_without_category_returns_400(self, db_session):
        editor = _user(db_session, "EditorArea")
        category = ensure_helpdesk_category(db_session, code="tfe_char_area", area="SOPORTE")
        ticket = _ticket(db_session, "TFE-CHAR-4", editor, category, area="SOPORTE")

        with pytest.raises(HTTPException) as exc_info:
            ticket_service.update_pending_ticket(
                db_session, ticket.id, editor.id,
                area="DESARROLLO",
            )

        assert exc_info.value.status_code == 400
        assert exc_info.value.detail == "Al cambiar de area debe seleccionar una nueva categoria"
        assert _edit_logs(db_session, ticket.id) == []

    def test_no_changes_returns_ticket_without_edit_logs(self, db_session):
        editor = _user(db_session, "EditorNoop")
        category = ensure_helpdesk_category(db_session, code="tfe_char_noop", area="SOPORTE")
        ticket = _ticket(db_session, "TFE-CHAR-5", editor, category)
        original_updated_at = ticket.updated_at
        original_updated_by = ticket.updated_by_id

        result = ticket_service.update_pending_ticket(db_session, ticket.id, editor.id)

        assert result.id == ticket.id
        assert result.updated_at == original_updated_at
        assert result.updated_by_id == original_updated_by
        assert _edit_logs(db_session, ticket.id) == []


# ────────────────────── funcion nueva: apply_ticket_field_edits ──────────────────────

class TestApplyTicketFieldEditsDirect:
    """`apply_ticket_field_edits` es la funcion que el refactor EXTRAE de
    `update_pending_ticket`. Contra el codigo actual (pre-refactor)
    `ticket_service` no la expone todavia: estos tests fallan con
    `AttributeError` — es la evidencia RED antes de implementar. Despues del
    refactor deben quedar en verde sin modificarse."""

    def test_works_on_assigned_ticket_without_status_check(self, db_session):
        editor = _user(db_session, "EditorDirectOk")
        category = ensure_helpdesk_category(db_session, code="tfe_direct_ok", area="SOPORTE")
        # `_ticket` ya commitea internamente (add/commit/refresh) — el setup
        # queda persistido en un SAVEPOINT propio antes de que la funcion bajo
        # prueba mute nada, tal como pide el brief.
        ticket = _ticket(db_session, "TFE-DIRECT-1", editor, category, status="ASSIGNED")

        changed = ticket_service.apply_ticket_field_edits(
            db_session, ticket, editor.id,
            title="Titulo nuevo suficientemente largo",
        )

        assert changed == 1
        assert ticket.title == "Titulo nuevo suficientemente largo"
        assert ticket.status == "ASSIGNED"  # no revisa ni toca el estado
        assert ticket.updated_by_id == editor.id

        logs = _edit_logs(db_session, ticket.id)
        assert len(logs) == 1
        assert logs[0].field_name == "title"
        assert logs[0].changed_by_id == editor.id

    def test_no_changes_returns_zero_without_touching_ticket(self, db_session):
        editor = _user(db_session, "EditorDirectZero")
        category = ensure_helpdesk_category(db_session, code="tfe_direct_zero", area="SOPORTE")
        ticket = _ticket(db_session, "TFE-DIRECT-2", editor, category, status="IN_PROGRESS")
        original_updated_at = ticket.updated_at

        changed = ticket_service.apply_ticket_field_edits(db_session, ticket, editor.id)

        assert changed == 0
        assert ticket.updated_at == original_updated_at
        assert _edit_logs(db_session, ticket.id) == []

    def test_does_not_commit(self, db_session):
        editor = _user(db_session, "EditorNoCommit")
        category = ensure_helpdesk_category(db_session, code="tfe_direct_nocommit", area="SOPORTE")
        ticket = _ticket(db_session, "TFE-DIRECT-3", editor, category, status="ASSIGNED")
        original_title = ticket.title

        changed = ticket_service.apply_ticket_field_edits(
            db_session, ticket, editor.id,
            title="Titulo que no deberia sobrevivir al rollback",
        )
        assert changed == 1
        # Mutado en memoria/flush dentro de la transaccion actual...
        assert ticket.title == "Titulo que no deberia sobrevivir al rollback"
        assert len(_edit_logs(db_session, ticket.id)) == 1

        # ...pero nunca commiteado: rollback al SAVEPOINT del setup (`_ticket`
        # ya habia hecho commit) borra tanto el UPDATE como el INSERT del log.
        db_session.rollback()

        assert ticket.title == original_title
        assert _edit_logs(db_session, ticket.id) == []
