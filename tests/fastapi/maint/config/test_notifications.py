"""
Tests para notificaciones maint — Fase 6.

Secciones:
  A. render_notification — unit, núcleo del fallback defensivo.
  B. catalog_cache notification templates — unit sin BD real.
  C. notify_* fallback — regresión: con BD caída, los helpers usan strings hardcoded.
  D. email_helper subjects — render_notification recibe el fallback_subject correcto.
  E. API /api/maint/v2/config/notifications — TestClient con mocks.

Estrategia:
  - BD no disponible → se parchea _load_notification_templates_from_db o
    _ensure_notification_templates_cache para simular fallo.
  - JWT admin (role='admin') → require_perms hace bypass automático.
  - Sin cookie → 401.
  - El cache de módulo de notification_templates se invalida antes de cada test
    que lo ejercite para evitar interferencia.
  - NO modifica archivos de producción.
"""
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch, call

import jwt
import pytest

import itcj2.models  # noqa: F401 — resolución de mappers
from itcj2.config import get_settings
from itcj2.database import get_db
from itcj2.main import create_app


# =============================================================================
# Helpers compartidos
# =============================================================================

def _admin_jwt(user_id: int = 1) -> str:
    """JWT con role=admin firmado con SECRET real → require_perms hace bypass."""
    settings = get_settings()
    now = int(time.time())
    payload = {
        "sub": str(user_id),
        "role": "admin",
        "cn": None,
        "name": "Admin Test",
        "iat": now,
        "exp": now + 24 * 3600,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")


def _admin_headers() -> dict:
    return {"Cookie": f"itcj_token={_admin_jwt()}"}


def _fake_notification_template(
    tid: int = 1,
    code: str = "ticket_created",
    name: str = "Ticket creado",
    channel: str = "inapp",
    subject_template: str = None,
    title_template: str = "Nueva solicitud #{{ ticket.ticket_number }}",
    body_template: str = "{{ ticket.title }}",
    variables: dict = None,
    is_active: bool = True,
    updated_at=None,
    updated_by_id: int = None,
) -> MagicMock:
    """Simula un objeto MaintNotificationTemplate."""
    t = MagicMock()
    t.id = tid
    t.code = code
    t.name = name
    t.channel = channel
    t.subject_template = subject_template
    t.title_template = title_template
    t.body_template = body_template
    t.variables = variables
    t.is_active = is_active
    t.updated_at = updated_at
    t.updated_by_id = updated_by_id
    return t


def _fake_tpl_dict(
    tid: int = 1,
    code: str = "ticket_created",
    name: str = "Ticket creado",
    channel: str = "inapp",
    subject_template: str = None,
    title_template: str = "Nueva solicitud #{{ ticket.ticket_number }}",
    body_template: str = "{{ ticket.title }}",
    variables: dict = None,
    is_active: bool = True,
) -> dict:
    """Dict plano como el que devuelve catalog_cache."""
    return {
        "id": tid,
        "code": code,
        "name": name,
        "channel": channel,
        "subject_template": subject_template,
        "title_template": title_template,
        "body_template": body_template,
        "variables": variables,
        "is_active": is_active,
        "updated_at": None,
        "updated_by_id": None,
    }


# =============================================================================
# Fixture: app_client (mismo patrón que test_priorities_audit.py)
# =============================================================================

@pytest.fixture
def app_client():
    """TestClient con get_db override y app real."""
    app = create_app()
    mock_db = MagicMock()
    app.dependency_overrides[get_db] = lambda: mock_db
    with TestClient(app) as c:
        c._mock_db = mock_db
        yield c
    app.dependency_overrides.clear()


# Importación del TestClient aquí para que el fixture esté disponible
from fastapi.testclient import TestClient


# =============================================================================
# A. render_notification — unit, núcleo del fallback defensivo
# =============================================================================

class TestRenderNotificationFallbacks:
    """render_notification nunca lanza y usa fallbacks ante cualquier fallo.

    render_notification hace 'from itcj2.apps.maint.utils.catalog_cache
    import get_notification_template' localmente en cada llamada. El patch
    correcto es sobre el módulo fuente: catalog_cache.get_notification_template.
    """

    def test_template_ausente_devuelve_fallbacks(self):
        """get_notification_template → None → devuelve exactamente los fallbacks."""
        from itcj2.apps.maint.services.notification_helper import render_notification

        db = MagicMock()
        with patch(
            "itcj2.apps.maint.utils.catalog_cache.get_notification_template",
            return_value=None,
        ):
            result = render_notification(
                db=db,
                code="ticket_created",
                context={},
                fallback_title="Título fallback",
                fallback_subject="Asunto fallback",
                fallback_body="Cuerpo fallback",
            )

        assert result == {
            "title": "Título fallback",
            "subject": "Asunto fallback",
            "body": "Cuerpo fallback",
        }

    def test_template_inactiva_devuelve_fallbacks(self):
        """Plantilla inactiva → get_notification_template ya devuelve None → fallbacks."""
        from itcj2.apps.maint.services.notification_helper import render_notification

        # get_notification_template solo retorna la plantilla si is_active; si no, None.
        db = MagicMock()
        with patch(
            "itcj2.apps.maint.utils.catalog_cache.get_notification_template",
            return_value=None,  # inactiva → ya filtrada antes de llegar aquí
        ):
            result = render_notification(
                db=db,
                code="ticket_canceled",
                context={"ticket": MagicMock(ticket_number="MANT-2026-001")},
                fallback_title="Ticket cancelado fb",
                fallback_subject=None,
                fallback_body="Cuerpo cancelado",
            )

        assert result["title"] == "Ticket cancelado fb"
        assert result["body"] == "Cuerpo cancelado"

    def test_template_activa_renderiza_con_context(self):
        """Plantilla activa con Jinja válido y contexto → renderiza usando el context."""
        from itcj2.apps.maint.services.notification_helper import render_notification

        tpl = _fake_tpl_dict(
            code="ticket_created",
            title_template="Solicitud #{{ ticket.ticket_number }}",
            body_template="{{ ticket.title }}",
            subject_template="Asunto #{{ ticket.ticket_number }}",
            is_active=True,
        )
        ticket = SimpleNamespace(
            ticket_number="MANT-2026-007",
            title="Reparar lámpara del pasillo",
        )
        context = {"ticket": ticket}

        db = MagicMock()
        with patch(
            "itcj2.apps.maint.utils.catalog_cache.get_notification_template",
            return_value=tpl,
        ):
            result = render_notification(
                db=db,
                code="ticket_created",
                context=context,
                fallback_title="FB título",
                fallback_subject="FB asunto",
                fallback_body="FB cuerpo",
            )

        assert "MANT-2026-007" in result["title"]
        assert "MANT-2026-007" in result["subject"]
        assert "Reparar" in result["body"]
        # La clave es que NO lanza excepción
        assert result["body"] is not None

    def test_template_activa_jinja_invalido_no_lanza_devuelve_fallbacks(self):
        """Plantilla con Jinja roto → NO lanza, devuelve fallbacks."""
        from itcj2.apps.maint.services.notification_helper import render_notification

        tpl = _fake_tpl_dict(
            code="ticket_created",
            title_template="{% if x %}{{ x }",  # sintaxis inválida — llave sin cerrar
            body_template="Cuerpo {{ ticket.title }}",
            is_active=True,
        )
        db = MagicMock()
        with patch(
            "itcj2.apps.maint.utils.catalog_cache.get_notification_template",
            return_value=tpl,
        ):
            try:
                result = render_notification(
                    db=db,
                    code="ticket_created",
                    context={"ticket": SimpleNamespace(title="Test")},
                    fallback_title="FB título",
                    fallback_subject="FB asunto",
                    fallback_body="FB cuerpo",
                )
            except Exception as exc:
                pytest.fail(f"render_notification lanzó excepción inesperada: {exc!r}")

        # title usa fallback porque el template es inválido
        assert result["title"] == "FB título"

    def test_variable_faltante_chainable_undefined_no_lanza(self):
        """Variable faltante en context con ChainableUndefined → NO lanza (render parcial)."""
        from itcj2.apps.maint.services.notification_helper import render_notification

        tpl = _fake_tpl_dict(
            code="ticket_created",
            title_template="{{ variable_inexistente.sub_campo }} creado",
            body_template="{{ ticket.title }}",
            is_active=True,
        )
        db = MagicMock()
        with patch(
            "itcj2.apps.maint.utils.catalog_cache.get_notification_template",
            return_value=tpl,
        ):
            try:
                result = render_notification(
                    db=db,
                    code="ticket_created",
                    context={"ticket": SimpleNamespace(title="Mi ticket")},
                    fallback_title="FB",
                    fallback_subject=None,
                    fallback_body="FB body",
                )
            except Exception as exc:
                pytest.fail(f"render_notification lanzó excepción con var faltante: {exc!r}")

        # ChainableUndefined produce string vacío para la var inexistente; no lanza
        assert isinstance(result["title"], str)
        assert isinstance(result["body"], str)

    def test_excepcion_en_get_notification_template_devuelve_fallbacks(self):
        """Excepción inesperada al buscar plantilla → fallbacks, sin propagar."""
        from itcj2.apps.maint.services.notification_helper import render_notification

        db = MagicMock()
        with patch(
            "itcj2.apps.maint.utils.catalog_cache.get_notification_template",
            side_effect=RuntimeError("Error inesperado de BD"),
        ):
            try:
                result = render_notification(
                    db=db,
                    code="ticket_resolved",
                    context={},
                    fallback_title="FB title",
                    fallback_subject="FB subject",
                    fallback_body="FB body",
                )
            except Exception as exc:
                pytest.fail(f"render_notification propagó excepción: {exc!r}")

        assert result["title"] == "FB title"
        assert result["subject"] == "FB subject"
        assert result["body"] == "FB body"

    def test_fallback_body_none_no_forzado(self):
        """fallback_title y fallback_subject pueden ser None; solo fallback_body es requerido."""
        from itcj2.apps.maint.services.notification_helper import render_notification

        db = MagicMock()
        with patch(
            "itcj2.apps.maint.utils.catalog_cache.get_notification_template",
            return_value=None,
        ):
            result = render_notification(
                db=db,
                code="ticket_created",
                context={},
                fallback_body="Solo body",
            )

        assert result["title"] is None
        assert result["subject"] is None
        assert result["body"] == "Solo body"


# =============================================================================
# B. catalog_cache — notification templates
# =============================================================================

class TestCatalogCacheNotificationTemplates:
    """catalog_cache.get_notification_template y get_notification_templates degradan silenciosamente."""

    def setup_method(self):
        """Invalida cache antes de cada test."""
        from itcj2.apps.maint.utils.catalog_cache import invalidate_notification_templates
        invalidate_notification_templates()

    def teardown_method(self):
        from itcj2.apps.maint.utils.catalog_cache import invalidate_notification_templates
        invalidate_notification_templates()

    def test_get_notification_template_bd_caida_retorna_none(self):
        """Con BD caída, get_notification_template nunca lanza y retorna None."""
        with patch(
            "itcj2.apps.maint.utils.catalog_cache._load_notification_templates_from_db",
            side_effect=Exception("BD caída"),
        ):
            from itcj2.apps.maint.utils.catalog_cache import (
                get_notification_template,
                invalidate_notification_templates,
            )
            invalidate_notification_templates()
            try:
                result = get_notification_template("ticket_created")
            except Exception as exc:
                pytest.fail(f"get_notification_template lanzó: {exc!r}")
        assert result is None

    def test_get_notification_templates_bd_caida_retorna_lista_vacia(self):
        """Con BD caída, get_notification_templates nunca lanza y retorna []."""
        with patch(
            "itcj2.apps.maint.utils.catalog_cache._load_notification_templates_from_db",
            side_effect=Exception("BD caída"),
        ):
            from itcj2.apps.maint.utils.catalog_cache import (
                get_notification_templates,
                invalidate_notification_templates,
            )
            invalidate_notification_templates()
            try:
                result = get_notification_templates()
            except Exception as exc:
                pytest.fail(f"get_notification_templates lanzó: {exc!r}")
        assert result == []

    def test_invalidate_notification_templates_idempotente(self):
        """invalidate_notification_templates() no lanza, ni con cache lleno ni vacío."""
        from itcj2.apps.maint.utils.catalog_cache import invalidate_notification_templates
        try:
            invalidate_notification_templates()
            invalidate_notification_templates()  # segunda vez, cache ya vacío
        except Exception as exc:
            pytest.fail(f"invalidate_notification_templates lanzó: {exc!r}")

    def test_get_notification_template_activa_devuelve_dict(self):
        """Con BD mockeada y plantilla activa → devuelve el dict."""
        tpl_dict = _fake_tpl_dict(
            tid=1, code="ticket_created", is_active=True,
        )
        with patch(
            "itcj2.apps.maint.utils.catalog_cache._load_notification_templates_from_db",
            return_value=[tpl_dict],
        ):
            from itcj2.apps.maint.utils.catalog_cache import (
                get_notification_template,
                invalidate_notification_templates,
            )
            invalidate_notification_templates()
            result = get_notification_template("ticket_created")

        assert result is not None
        assert result["code"] == "ticket_created"
        assert result["is_active"] is True

    def test_get_notification_template_inactiva_devuelve_none(self):
        """Plantilla inactiva → get_notification_template retorna None."""
        tpl_dict = _fake_tpl_dict(
            tid=1, code="ticket_created", is_active=False,
        )
        with patch(
            "itcj2.apps.maint.utils.catalog_cache._load_notification_templates_from_db",
            return_value=[tpl_dict],
        ):
            from itcj2.apps.maint.utils.catalog_cache import (
                get_notification_template,
                invalidate_notification_templates,
            )
            invalidate_notification_templates()
            result = get_notification_template("ticket_created")

        assert result is None

    def test_get_notification_templates_devuelve_todas_activas_e_inactivas(self):
        """get_notification_templates retorna todas las plantillas (activas e inactivas)."""
        rows = [
            _fake_tpl_dict(tid=1, code="ticket_created", is_active=True),
            _fake_tpl_dict(tid=2, code="ticket_canceled", is_active=False),
        ]
        with patch(
            "itcj2.apps.maint.utils.catalog_cache._load_notification_templates_from_db",
            return_value=rows,
        ):
            from itcj2.apps.maint.utils.catalog_cache import (
                get_notification_templates,
                invalidate_notification_templates,
            )
            invalidate_notification_templates()
            result = get_notification_templates()

        assert len(result) == 2
        codes = {r["code"] for r in result}
        assert "ticket_created" in codes
        assert "ticket_canceled" in codes

    def test_get_notification_template_cachea_resultado(self):
        """Segunda llamada no va a BD."""
        tpl_dict = _fake_tpl_dict(tid=1, code="ticket_created", is_active=True)
        with patch(
            "itcj2.apps.maint.utils.catalog_cache._load_notification_templates_from_db",
            return_value=[tpl_dict],
        ) as mock_load:
            from itcj2.apps.maint.utils.catalog_cache import (
                get_notification_template,
                invalidate_notification_templates,
            )
            invalidate_notification_templates()
            get_notification_template("ticket_created")
            get_notification_template("ticket_created")  # segunda llamada

        assert mock_load.call_count == 1

    def test_invalidate_fuerza_recarga(self):
        """Tras invalidate, el siguiente acceso recarga desde BD."""
        tpl_dict = _fake_tpl_dict(tid=1, code="ticket_created", is_active=True)
        with patch(
            "itcj2.apps.maint.utils.catalog_cache._load_notification_templates_from_db",
            return_value=[tpl_dict],
        ) as mock_load:
            from itcj2.apps.maint.utils.catalog_cache import (
                get_notification_templates,
                invalidate_notification_templates,
            )
            invalidate_notification_templates()
            get_notification_templates()       # primera carga
            invalidate_notification_templates()
            get_notification_templates()       # recarga tras invalidar

        assert mock_load.call_count == 2


# =============================================================================
# C. notify_* fallback (regresión)
# =============================================================================

class TestNotifyFallbackConBdCaida:
    """
    Con get_notification_template→None (BD caída simulada), los helpers
    usan el title/body hardcoded original. Sin lanzar excepción.
    """

    def _fake_ticket_minimal(self, ticket_number="MANT-2026-001", title="Reparar lámpara"):
        """Ticket minimal compatible con los notify_*."""
        t = MagicMock()
        t.id = 1
        t.ticket_number = ticket_number
        t.title = title
        t.priority = "ALTA"
        t.status = "PENDING"
        t.requester_id = 100
        t.requester_department_id = 5
        t.cancel_reason = None
        t.resolved_by_id = None
        t.rating_attention = None
        t.rating_speed = None
        cat = MagicMock()
        cat.name = "Eléctrico"
        t.category = cat
        req = MagicMock()
        req.full_name = "JUAN PEREZ"
        t.requester = req
        t.active_technicians = []
        t.technicians = []
        return t

    @patch("itcj2.apps.maint.services.notification_helper.NotificationService.create")
    @patch("itcj2.apps.maint.services.notification_helper._async_broadcast")
    @patch("itcj2.apps.maint.utils.catalog_cache.get_notification_template",
           return_value=None)
    def test_notify_ticket_created_usa_fallback_title(
        self, mock_tpl, mock_bc, mock_create
    ):
        """
        notify_ticket_created con plantilla ausente → title = 'Nueva solicitud #MANT-2026-001'.
        Se necesitan destinatarios para que NotificationService.create sea llamado.
        """
        from itcj2.apps.maint.services.notification_helper import MaintNotificationHelper

        ticket = self._fake_ticket_minimal(ticket_number="MANT-2026-001")

        db = MagicMock()

        # Simular que existen dispatchers/admins para que haya recipientes
        mock_app = MagicMock()
        mock_app.id = 1
        mock_role = MagicMock()
        mock_role.id = 10
        mock_assignment = MagicMock()
        mock_assignment.user_id = 200  # dispatcher distinto al requester

        def _flexible_query(model):
            q = MagicMock()
            q.filter_by.return_value.first.return_value = mock_app
            q.filter.return_value.all.return_value = [mock_assignment]
            return q

        db.query.side_effect = _flexible_query

        try:
            MaintNotificationHelper.notify_ticket_created(db, ticket)
        except Exception as exc:
            pytest.fail(f"notify_ticket_created lanzó excepción: {exc!r}")

        # Si hay llamadas a create, verificar el title usa el fallback
        if mock_create.called:
            title_used = mock_create.call_args.kwargs["title"]
            assert "MANT-2026-001" in title_used
            assert "Nueva solicitud" in title_used

    @patch("itcj2.apps.maint.services.notification_helper.NotificationService.create")
    @patch("itcj2.apps.maint.services.notification_helper._async_broadcast")
    @patch("itcj2.apps.maint.utils.catalog_cache.get_notification_template",
           return_value=None)
    def test_notify_technician_assigned_usa_fallback(
        self, mock_tpl, mock_bc, mock_create
    ):
        """notify_technician_assigned con plantilla ausente → title contiene el ticket_number."""
        from itcj2.apps.maint.services.notification_helper import MaintNotificationHelper

        ticket = self._fake_ticket_minimal(ticket_number="MANT-2026-002")

        tech = MagicMock()
        tech.full_name = "PEDRO TECH"
        db = MagicMock()
        db.get.return_value = tech

        try:
            MaintNotificationHelper.notify_technician_assigned(db, ticket, technician_id=33)
        except Exception as exc:
            pytest.fail(f"notify_technician_assigned lanzó: {exc!r}")

        assert mock_create.called
        title_used = mock_create.call_args.kwargs["title"]
        assert "MANT-2026-002" in title_used

    @patch("itcj2.apps.maint.services.notification_helper.NotificationService.create")
    @patch("itcj2.apps.maint.services.notification_helper._async_broadcast")
    @patch("itcj2.apps.maint.utils.catalog_cache.get_notification_template",
           return_value=None)
    def test_notify_ticket_resolved_usa_fallback(
        self, mock_tpl, mock_bc, mock_create
    ):
        """notify_ticket_resolved con plantilla ausente → title contiene el ticket_number."""
        from itcj2.apps.maint.services.notification_helper import MaintNotificationHelper

        ticket = self._fake_ticket_minimal(ticket_number="MANT-2026-003")
        ticket.status = "RESOLVED_SUCCESS"
        db = MagicMock()

        try:
            MaintNotificationHelper.notify_ticket_resolved(db, ticket)
        except Exception as exc:
            pytest.fail(f"notify_ticket_resolved lanzó: {exc!r}")

        assert mock_create.called
        title_used = mock_create.call_args.kwargs["title"]
        assert "MANT-2026-003" in title_used

    @patch("itcj2.apps.maint.services.notification_helper.NotificationService.create")
    @patch("itcj2.apps.maint.services.notification_helper._async_broadcast")
    @patch("itcj2.apps.maint.utils.catalog_cache.get_notification_template",
           return_value=None)
    def test_notify_comment_added_usa_fallback(
        self, mock_tpl, mock_bc, mock_create
    ):
        """notify_comment_added con plantilla ausente → title 'Nuevo comentario en #...'."""
        from itcj2.apps.maint.services.notification_helper import MaintNotificationHelper

        ticket = self._fake_ticket_minimal(ticket_number="MANT-2026-004")
        ticket.requester_id = 100
        ticket.active_technicians = []  # sin técnicos para simplificar

        comment = MagicMock()
        comment.content = "Revisé el cableado"
        comment.is_internal = False

        author = MagicMock()
        author.full_name = "ANA TECNICO"

        db = MagicMock()
        db.get.return_value = author

        try:
            MaintNotificationHelper.notify_comment_added(db, ticket, comment, author_id=99)
        except Exception as exc:
            pytest.fail(f"notify_comment_added lanzó: {exc!r}")

        # El requester recibe la notif (si no es el autor)
        if mock_create.called:
            title_used = mock_create.call_args_list[0].kwargs["title"]
            assert "MANT-2026-004" in title_used

    @patch("itcj2.apps.maint.services.notification_helper.NotificationService.create")
    @patch("itcj2.apps.maint.services.notification_helper._async_broadcast")
    @patch("itcj2.apps.maint.utils.catalog_cache.get_notification_template",
           return_value=None)
    def test_notify_no_lanza_con_bd_caida(self, mock_tpl, mock_bc, mock_create):
        """notify_technician_assigned no lanza excepción aunque la plantilla falle."""
        from itcj2.apps.maint.services.notification_helper import MaintNotificationHelper

        ticket = self._fake_ticket_minimal()
        tech = MagicMock()
        tech.full_name = "TECH"
        db = MagicMock()
        db.get.return_value = tech

        try:
            MaintNotificationHelper.notify_technician_assigned(db, ticket, technician_id=1)
        except Exception as exc:
            pytest.fail(f"notify_technician_assigned lanzó con BD caída: {exc!r}")


# =============================================================================
# D. email_helper — subjects via render_notification
# =============================================================================

class TestEmailHelperSubjectsFallback:
    """
    Los send_* de MaintEmailHelper usan render_notification para el subject.
    Con plantilla ausente → llaman render_notification con el fallback_subject
    hardcoded original. Nunca lanzan.
    """

    def _fake_ticket_email(self, ticket_number="MANT-2026-010"):
        t = MagicMock()
        t.id = 10
        t.ticket_number = ticket_number
        t.title = "Falla eléctrica"
        req = MagicMock()
        req.email = "requester@itcj.edu.mx"
        req.full_name = "JUAN"
        t.requester = req
        return t

    def _fake_technician(self, email="tech@itcj.edu.mx"):
        tech = MagicMock()
        tech.id = 5
        tech.full_name = "PEDRO TECH"
        tech.email = email
        return tech

    def test_send_assigned_pasa_fallback_subject_correcto(self):
        """
        send_assigned llama render_notification con
        fallback_subject='[Mantenimiento ITCJ] Ticket #... asignado a ti'.
        """
        from itcj2.apps.maint.services.email_helper import MaintEmailHelper

        ticket = self._fake_ticket_email("MANT-2026-010")
        tech = self._fake_technician()
        db = MagicMock()

        with patch(
            "itcj2.apps.maint.services.email_helper._acquire_token",
            return_value="fake-token",
        ), patch(
            "itcj2.apps.maint.services.email_helper._render",
            return_value="<html>cuerpo</html>",
        ), patch(
            "itcj2.apps.maint.services.email_helper._send",
            return_value=True,
        ), patch(
            "itcj2.apps.maint.services.email_helper.render_notification",
        ) as mock_render:
            # render_notification debe retornar un dict con 'subject'
            mock_render.return_value = {
                "title": None,
                "subject": "[Mantenimiento ITCJ] Ticket #MANT-2026-010 asignado a ti",
                "body": "",
            }
            result = MaintEmailHelper.send_assigned(db, ticket, tech)

        assert mock_render.called
        kwargs = mock_render.call_args.kwargs
        # render_notification llamado con code='ticket_assigned' (kwarg)
        assert kwargs.get("code") == "ticket_assigned"
        fallback_subject = kwargs.get("fallback_subject", "")
        assert "MANT-2026-010" in fallback_subject
        assert "asignado" in fallback_subject

    def test_send_assigned_no_lanza_con_plantilla_ausente(self):
        """send_assigned no lanza aunque render_notification devuelva fallback."""
        from itcj2.apps.maint.services.email_helper import MaintEmailHelper

        ticket = self._fake_ticket_email("MANT-2026-011")
        tech = self._fake_technician()
        db = MagicMock()

        with patch(
            "itcj2.apps.maint.services.email_helper._acquire_token",
            return_value="fake-token",
        ), patch(
            "itcj2.apps.maint.services.email_helper._render",
            return_value="<html></html>",
        ), patch(
            "itcj2.apps.maint.services.email_helper._send",
            return_value=False,
        ), patch(
            "itcj2.apps.maint.services.email_helper.render_notification",
            return_value={"title": None, "subject": "Fallback subject", "body": ""},
        ):
            try:
                MaintEmailHelper.send_assigned(db, ticket, tech)
            except Exception as exc:
                pytest.fail(f"send_assigned lanzó: {exc!r}")

    def test_send_resolved_pasa_fallback_subject_correcto(self):
        """send_resolved llama render_notification con fallback_subject conteniendo el ticket_number."""
        from itcj2.apps.maint.services.email_helper import MaintEmailHelper

        ticket = self._fake_ticket_email("MANT-2026-012")
        db = MagicMock()

        with patch(
            "itcj2.apps.maint.services.email_helper._acquire_token",
            return_value="tok",
        ), patch(
            "itcj2.apps.maint.services.email_helper._render",
            return_value="<html></html>",
        ), patch(
            "itcj2.apps.maint.services.email_helper._send",
            return_value=True,
        ), patch(
            "itcj2.apps.maint.services.email_helper.render_notification",
        ) as mock_render:
            mock_render.return_value = {"title": None, "subject": "Asunto fallback", "body": ""}
            MaintEmailHelper.send_resolved(db, ticket)

        assert mock_render.called
        kwargs = mock_render.call_args.kwargs
        fb_subject = kwargs.get("fallback_subject", "")
        assert "MANT-2026-012" in fb_subject

    def test_send_overdue_pasa_fallback_subject_correcto(self):
        """send_overdue llama render_notification con fallback_subject conteniendo 'vencido'."""
        from itcj2.apps.maint.services.email_helper import MaintEmailHelper

        ticket = self._fake_ticket_email("MANT-2026-013")
        recipient = self._fake_technician()
        db = MagicMock()

        with patch(
            "itcj2.apps.maint.services.email_helper._acquire_token",
            return_value="tok",
        ), patch(
            "itcj2.apps.maint.services.email_helper._render",
            return_value="<html></html>",
        ), patch(
            "itcj2.apps.maint.services.email_helper._send",
            return_value=True,
        ), patch(
            "itcj2.apps.maint.services.email_helper.render_notification",
        ) as mock_render:
            mock_render.return_value = {"title": None, "subject": "Asunto overdue", "body": ""}
            MaintEmailHelper.send_overdue(db, ticket, recipient)

        assert mock_render.called
        kwargs = mock_render.call_args.kwargs
        fb_subject = kwargs.get("fallback_subject", "")
        assert "MANT-2026-013" in fb_subject
        assert "URGENTE" in fb_subject.upper() or "vencido" in fb_subject.lower()

    def test_send_canceled_pasa_fallback_subject_correcto(self):
        """send_canceled llama render_notification con fallback_subject conteniendo 'cancelado'."""
        from itcj2.apps.maint.services.email_helper import MaintEmailHelper

        ticket = self._fake_ticket_email("MANT-2026-014")
        recipient = self._fake_technician()
        db = MagicMock()

        with patch(
            "itcj2.apps.maint.services.email_helper._acquire_token",
            return_value="tok",
        ), patch(
            "itcj2.apps.maint.services.email_helper._render",
            return_value="<html></html>",
        ), patch(
            "itcj2.apps.maint.services.email_helper._send",
            return_value=True,
        ), patch(
            "itcj2.apps.maint.services.email_helper.render_notification",
        ) as mock_render:
            mock_render.return_value = {"title": None, "subject": "Asunto cancelado", "body": ""}
            MaintEmailHelper.send_canceled(db, ticket, recipient)

        assert mock_render.called
        kwargs = mock_render.call_args.kwargs
        fb_subject = kwargs.get("fallback_subject", "")
        assert "MANT-2026-014" in fb_subject
        assert "cancelado" in fb_subject.lower()

    def test_send_sin_email_retorna_false_sin_lanzar(self):
        """Técnico sin email → send_assigned retorna False sin lanzar excepción."""
        from itcj2.apps.maint.services.email_helper import MaintEmailHelper

        ticket = self._fake_ticket_email()
        tech_sin_email = self._fake_technician(email=None)
        db = MagicMock()

        try:
            result = MaintEmailHelper.send_assigned(db, ticket, tech_sin_email)
        except Exception as exc:
            pytest.fail(f"send_assigned con técnico sin email lanzó: {exc!r}")

        assert result is False

    def test_send_sin_token_retorna_false_sin_lanzar(self):
        """Sin token de Graph → send_assigned retorna False sin lanzar excepción."""
        from itcj2.apps.maint.services.email_helper import MaintEmailHelper

        ticket = self._fake_ticket_email()
        tech = self._fake_technician()
        db = MagicMock()

        with patch(
            "itcj2.apps.maint.services.email_helper._acquire_token",
            return_value=None,
        ):
            try:
                result = MaintEmailHelper.send_assigned(db, ticket, tech)
            except Exception as exc:
                pytest.fail(f"send_assigned sin token lanzó: {exc!r}")

        assert result is False


# =============================================================================
# E. API /api/maint/v2/config/notifications
# =============================================================================

class TestNotificationTemplatesApiList:
    """GET /api/maint/v2/config/notifications"""

    def _setup_list_query(self, mock_db, items: list):
        mock_db.query.return_value.order_by.return_value.all.return_value = items

    def test_list_returns_200(self, app_client):
        """Admin obtiene 200."""
        tpl = _fake_notification_template()
        self._setup_list_query(app_client._mock_db, [tpl])

        r = app_client.get(
            "/api/maint/v2/config/notifications",
            headers=_admin_headers(),
        )
        assert r.status_code == 200

    def test_list_response_shape(self, app_client):
        """Respuesta tiene {success, data (list), total}."""
        tpl = _fake_notification_template()
        self._setup_list_query(app_client._mock_db, [tpl])

        r = app_client.get(
            "/api/maint/v2/config/notifications",
            headers=_admin_headers(),
        )
        body = r.json()
        assert body["success"] is True
        assert isinstance(body["data"], list)
        assert "total" in body

    def test_list_total_correcto(self, app_client):
        """total coincide con la cantidad de plantillas."""
        tpls = [
            _fake_notification_template(tid=i, code=f"event_{i}")
            for i in range(1, 4)
        ]
        self._setup_list_query(app_client._mock_db, tpls)

        r = app_client.get(
            "/api/maint/v2/config/notifications",
            headers=_admin_headers(),
        )
        assert r.json()["total"] == 3

    def test_list_item_estructura(self, app_client):
        """Cada item en data tiene los campos esperados."""
        tpl = _fake_notification_template(tid=1, code="ticket_created")
        self._setup_list_query(app_client._mock_db, [tpl])

        r = app_client.get(
            "/api/maint/v2/config/notifications",
            headers=_admin_headers(),
        )
        item = r.json()["data"][0]
        for field in ("id", "code", "name", "channel", "is_active",
                      "subject_template", "title_template", "body_template"):
            assert field in item, f"Campo '{field}' faltante en item"
        assert item["code"] == "ticket_created"

    def test_list_sin_cookie_retorna_401(self, app_client):
        """Sin autenticación → 401."""
        r = app_client.get("/api/maint/v2/config/notifications")
        assert r.status_code == 401

    def test_list_token_invalido_retorna_401(self, app_client):
        """Token inválido → 401."""
        r = app_client.get(
            "/api/maint/v2/config/notifications",
            headers={"Cookie": "itcj_token=garbage"},
        )
        assert r.status_code == 401


class TestNotificationTemplatesApiGet:
    """GET /api/maint/v2/config/notifications/{id}"""

    def test_get_by_id_returns_200(self, app_client):
        """Admin obtiene 200 para plantilla existente."""
        tpl = _fake_notification_template(tid=5, code="ticket_resolved")
        app_client._mock_db.get.return_value = tpl

        r = app_client.get(
            "/api/maint/v2/config/notifications/5",
            headers=_admin_headers(),
        )
        assert r.status_code == 200

    def test_get_by_id_success_true_y_data(self, app_client):
        """Respuesta tiene {success: true, data: {...}}."""
        tpl = _fake_notification_template(tid=5, code="ticket_resolved")
        app_client._mock_db.get.return_value = tpl

        r = app_client.get(
            "/api/maint/v2/config/notifications/5",
            headers=_admin_headers(),
        )
        body = r.json()
        assert body["success"] is True
        assert "data" in body
        assert body["data"]["code"] == "ticket_resolved"

    def test_get_by_id_inexistente_retorna_404(self, app_client):
        """Plantilla no encontrada → 404."""
        app_client._mock_db.get.return_value = None

        r = app_client.get(
            "/api/maint/v2/config/notifications/9999",
            headers=_admin_headers(),
        )
        assert r.status_code == 404

    def test_get_by_id_sin_cookie_retorna_401(self, app_client):
        """Sin autenticación → 401."""
        r = app_client.get("/api/maint/v2/config/notifications/1")
        assert r.status_code == 401


class TestNotificationTemplatesApiPatch:
    """PATCH /api/maint/v2/config/notifications/{id}"""

    @patch("itcj2.apps.maint.api.config.notifications.invalidate_notification_templates")
    @patch("itcj2.apps.maint.api.config.notifications.log_config_change")
    def test_patch_happy_returns_200(self, mock_log, mock_inv, app_client):
        """PATCH con plantilla existente y Jinja válido → 200."""
        tpl = _fake_notification_template(tid=3, code="ticket_created")
        app_client._mock_db.get.return_value = tpl

        r = app_client.patch(
            "/api/maint/v2/config/notifications/3",
            json={"title_template": "Nuevo título #{{ ticket.ticket_number }}"},
            headers=_admin_headers(),
        )
        assert r.status_code == 200

    @patch("itcj2.apps.maint.api.config.notifications.invalidate_notification_templates")
    @patch("itcj2.apps.maint.api.config.notifications.log_config_change")
    def test_patch_happy_success_true(self, mock_log, mock_inv, app_client):
        """PATCH exitoso devuelve {success: true, data: {...}}."""
        tpl = _fake_notification_template(tid=3, code="ticket_created")
        app_client._mock_db.get.return_value = tpl

        r = app_client.patch(
            "/api/maint/v2/config/notifications/3",
            json={"name": "Nombre actualizado"},
            headers=_admin_headers(),
        )
        body = r.json()
        assert body["success"] is True
        assert "data" in body

    def test_patch_body_template_jinja_invalido_retorna_422(self, app_client):
        """body_template con Jinja roto → 422 antes de tocar la BD."""
        tpl = _fake_notification_template(tid=3, code="ticket_created")
        app_client._mock_db.get.return_value = tpl

        r = app_client.patch(
            "/api/maint/v2/config/notifications/3",
            json={"body_template": "{% if x %}{{ x }"},  # llave sin cerrar
            headers=_admin_headers(),
        )
        assert r.status_code == 422

    def test_patch_title_template_jinja_invalido_retorna_422(self, app_client):
        """title_template con Jinja roto → 422."""
        tpl = _fake_notification_template(tid=3, code="ticket_created")
        app_client._mock_db.get.return_value = tpl

        r = app_client.patch(
            "/api/maint/v2/config/notifications/3",
            json={"title_template": "{% for x in %}{{ x }}{% endfor %}"},  # sin iterable
            headers=_admin_headers(),
        )
        assert r.status_code == 422

    def test_patch_inexistente_retorna_404(self, app_client):
        """Plantilla no encontrada → 404."""
        app_client._mock_db.get.return_value = None

        r = app_client.patch(
            "/api/maint/v2/config/notifications/9999",
            json={"name": "X"},
            headers=_admin_headers(),
        )
        assert r.status_code == 404

    def test_patch_sin_cookie_retorna_401(self, app_client):
        """Sin autenticación → 401."""
        r = app_client.patch(
            "/api/maint/v2/config/notifications/1",
            json={"name": "X"},
        )
        assert r.status_code == 401

    @patch("itcj2.apps.maint.api.config.notifications.invalidate_notification_templates")
    @patch("itcj2.apps.maint.api.config.notifications.log_config_change")
    def test_patch_invoca_log_config_change_con_entity_notification(
        self, mock_log, mock_inv, app_client
    ):
        """PATCH exitoso llama log_config_change con entity_type='notification'."""
        tpl = _fake_notification_template(tid=3, code="ticket_created")
        app_client._mock_db.get.return_value = tpl

        app_client.patch(
            "/api/maint/v2/config/notifications/3",
            json={"name": "Nombre nuevo"},
            headers=_admin_headers(),
        )
        mock_log.assert_called()
        call_kwargs = mock_log.call_args.kwargs
        assert call_kwargs.get("entity_type") == "notification"

    @patch("itcj2.apps.maint.api.config.notifications.invalidate_notification_templates")
    @patch("itcj2.apps.maint.api.config.notifications.log_config_change")
    def test_patch_invoca_invalidate_notification_templates(
        self, mock_log, mock_inv, app_client
    ):
        """PATCH exitoso llama invalidate_notification_templates()."""
        tpl = _fake_notification_template(tid=3, code="ticket_created")
        app_client._mock_db.get.return_value = tpl

        app_client.patch(
            "/api/maint/v2/config/notifications/3",
            json={"name": "Nombre nuevo"},
            headers=_admin_headers(),
        )
        mock_inv.assert_called()


class TestNotificationTemplatesApiToggle:
    """PATCH /api/maint/v2/config/notifications/{id}/toggle"""

    @patch("itcj2.apps.maint.api.config.notifications.invalidate_notification_templates")
    @patch("itcj2.apps.maint.api.config.notifications.log_config_change")
    def test_toggle_desactivar_returns_200(self, mock_log, mock_inv, app_client):
        """Desactivar plantilla activa → 200."""
        tpl = _fake_notification_template(tid=2, code="ticket_assigned", is_active=True)
        app_client._mock_db.get.return_value = tpl

        r = app_client.patch(
            "/api/maint/v2/config/notifications/2/toggle",
            json={"is_active": False},
            headers=_admin_headers(),
        )
        assert r.status_code == 200

    @patch("itcj2.apps.maint.api.config.notifications.invalidate_notification_templates")
    @patch("itcj2.apps.maint.api.config.notifications.log_config_change")
    def test_toggle_activar_returns_200(self, mock_log, mock_inv, app_client):
        """Activar plantilla inactiva → 200."""
        tpl = _fake_notification_template(tid=2, code="ticket_assigned", is_active=False)
        app_client._mock_db.get.return_value = tpl

        r = app_client.patch(
            "/api/maint/v2/config/notifications/2/toggle",
            json={"is_active": True},
            headers=_admin_headers(),
        )
        assert r.status_code == 200

    @patch("itcj2.apps.maint.api.config.notifications.invalidate_notification_templates")
    @patch("itcj2.apps.maint.api.config.notifications.log_config_change")
    def test_toggle_success_true(self, mock_log, mock_inv, app_client):
        """Toggle exitoso devuelve {success: true, data: {...}}."""
        tpl = _fake_notification_template(tid=2, is_active=True)
        app_client._mock_db.get.return_value = tpl

        r = app_client.patch(
            "/api/maint/v2/config/notifications/2/toggle",
            json={"is_active": False},
            headers=_admin_headers(),
        )
        body = r.json()
        assert body["success"] is True
        assert "data" in body

    def test_toggle_inexistente_retorna_404(self, app_client):
        """Plantilla no encontrada → 404."""
        app_client._mock_db.get.return_value = None

        r = app_client.patch(
            "/api/maint/v2/config/notifications/9999/toggle",
            json={"is_active": False},
            headers=_admin_headers(),
        )
        assert r.status_code == 404

    def test_toggle_sin_cookie_retorna_401(self, app_client):
        """Sin autenticación → 401."""
        r = app_client.patch(
            "/api/maint/v2/config/notifications/1/toggle",
            json={"is_active": True},
        )
        assert r.status_code == 401

    @patch("itcj2.apps.maint.api.config.notifications.invalidate_notification_templates")
    @patch("itcj2.apps.maint.api.config.notifications.log_config_change")
    def test_toggle_invoca_log_y_invalidate(self, mock_log, mock_inv, app_client):
        """Toggle exitoso llama log_config_change e invalidate_notification_templates."""
        tpl = _fake_notification_template(tid=2, is_active=True)
        app_client._mock_db.get.return_value = tpl

        app_client.patch(
            "/api/maint/v2/config/notifications/2/toggle",
            json={"is_active": False},
            headers=_admin_headers(),
        )
        mock_log.assert_called()
        mock_inv.assert_called()


class TestNotificationTemplatesApiPreview:
    """POST /api/maint/v2/config/notifications/{id}/preview"""

    def test_preview_con_datos_dummy_returns_200(self, app_client):
        """Preview sin ticket_id → 200 con subject/title/body/warnings."""
        tpl = _fake_notification_template(
            tid=1,
            code="ticket_created",
            title_template="Solicitud #{{ ticket.ticket_number }}",
            body_template="Título: {{ ticket.title }}",
            subject_template="[Maint] #{{ ticket.ticket_number }}",
        )
        app_client._mock_db.get.return_value = tpl

        r = app_client.post(
            "/api/maint/v2/config/notifications/1/preview",
            json={},
            headers=_admin_headers(),
        )
        assert r.status_code == 200

    def test_preview_response_shape(self, app_client):
        """Respuesta tiene {success, data: {subject, title, body, warnings}}."""
        tpl = _fake_notification_template(
            tid=1,
            code="ticket_created",
            title_template="Solicitud #{{ ticket.ticket_number }}",
            body_template="Detalle",
            subject_template="Asunto",
        )
        app_client._mock_db.get.return_value = tpl

        r = app_client.post(
            "/api/maint/v2/config/notifications/1/preview",
            json={},
            headers=_admin_headers(),
        )
        body = r.json()
        assert body["success"] is True
        data = body["data"]
        for field in ("subject", "title", "body", "warnings"):
            assert field in data, f"Campo '{field}' faltante en data de preview"

    def test_preview_warnings_es_lista(self, app_client):
        """El campo warnings es una lista."""
        tpl = _fake_notification_template(
            tid=1,
            title_template="{{ ticket.ticket_number }}",
            body_template="{{ ticket.title }}",
        )
        app_client._mock_db.get.return_value = tpl

        r = app_client.post(
            "/api/maint/v2/config/notifications/1/preview",
            json={},
            headers=_admin_headers(),
        )
        assert isinstance(r.json()["data"]["warnings"], list)

    def test_preview_renderiza_con_dummy_ticket(self, app_client):
        """Preview con datos dummy renderiza el número de ticket dummy."""
        tpl = _fake_notification_template(
            tid=1,
            title_template="Ticket #{{ ticket.ticket_number }}",
            body_template="{{ ticket.title }}",
            subject_template=None,
        )
        app_client._mock_db.get.return_value = tpl

        r = app_client.post(
            "/api/maint/v2/config/notifications/1/preview",
            json={},
            headers=_admin_headers(),
        )
        body = r.json()
        assert body["success"] is True
        # El dummy ticket tiene ticket_number='MANT-2026-000001'
        title = body["data"]["title"]
        assert "MANT-2026-000001" in title

    def test_preview_no_lanza_con_variable_faltante(self, app_client):
        """Preview con variable no provista no lanza — ChainableUndefined."""
        tpl = _fake_notification_template(
            tid=1,
            title_template="{{ variable_que_no_existe.sub_campo }}",
            body_template="{{ otro_campo_inexistente }}",
            subject_template=None,
        )
        app_client._mock_db.get.return_value = tpl

        try:
            r = app_client.post(
                "/api/maint/v2/config/notifications/1/preview",
                json={},
                headers=_admin_headers(),
            )
        except Exception as exc:
            pytest.fail(f"preview lanzó excepción con var faltante: {exc!r}")

        assert r.status_code == 200

    def test_preview_con_variable_faltante_genera_warnings(self, app_client):
        """Preview con variable faltante agrega warnings en la respuesta."""
        tpl = _fake_notification_template(
            tid=1,
            title_template="{{ variable_desconocida }}",
            body_template="Cuerpo fijo",
            subject_template=None,
        )
        app_client._mock_db.get.return_value = tpl

        r = app_client.post(
            "/api/maint/v2/config/notifications/1/preview",
            json={},
            headers=_admin_headers(),
        )
        body = r.json()
        assert body["success"] is True
        warnings = body["data"]["warnings"]
        # Debe haber al menos un warning por la variable desconocida
        assert len(warnings) >= 1
        # El warning debe mencionar la variable
        assert any("variable_desconocida" in w for w in warnings)

    def test_preview_con_ticket_id_inexistente_retorna_404(self, app_client):
        """Preview con ticket_id que no existe → 404."""
        tpl = _fake_notification_template(tid=1)
        # db.get retorna la plantilla para tpl_id=1, pero None para ticket_id
        def _get(model, pk):
            # MaintNotificationTemplate para pk=1, None para todo lo demás
            from itcj2.apps.maint.models.notification_template import MaintNotificationTemplate
            if model is MaintNotificationTemplate and pk == 1:
                return tpl
            return None

        app_client._mock_db.get.side_effect = _get

        r = app_client.post(
            "/api/maint/v2/config/notifications/1/preview",
            json={"ticket_id": 99999},
            headers=_admin_headers(),
        )
        assert r.status_code == 404

    def test_preview_plantilla_inexistente_retorna_404(self, app_client):
        """Plantilla no encontrada → 404."""
        app_client._mock_db.get.return_value = None

        r = app_client.post(
            "/api/maint/v2/config/notifications/9999/preview",
            json={},
            headers=_admin_headers(),
        )
        assert r.status_code == 404

    def test_preview_sin_cookie_retorna_401(self, app_client):
        """Sin autenticación → 401."""
        r = app_client.post(
            "/api/maint/v2/config/notifications/1/preview",
            json={},
        )
        assert r.status_code == 401
