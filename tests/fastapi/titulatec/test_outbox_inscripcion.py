"""Outbox para los correos de inscripción SIN secreto (Tarea R6; spec
`2026-10-05-titulatec-rendimiento-design.md` §3.7, decisión P-D1).

Cuatro correos de la inscripción dejan de mandarse dentro de la petición y se
encolan en `titulatec_email_outbox`, en la MISMA transacción que los origina;
los manda el despachador (`titulatec.email_dispatch`, cada 5 minutos):

    verify  -> enrollment_verified  (aviso con folio, al INSTITUCIONAL)
    reject  -> enrollment_rejected  (motivo, al correo PERSONAL de la solicitud)
    create  -> already_enrolled     («ya tienes un proceso», al INSTITUCIONAL)
    cancel  -> process_cancelled    (revocada, institucional + personal)

Lo que se fija aquí:

1. Esquema: `enrollment_request_id` (FK, NULL, indizada) y `user_id` NULL;
   modelo y migración con los mismos nombres; la regla «alumno o solicitud» es
   de la aplicación.
2. Cada escritor encola su fila y NO llama a Graph en la petición.
3. El despachador manda al MISMO destinatario de hoy, con el MISMO correo
   (plantilla, asunto y HTML idénticos al envío en línea), sella
   `rejection_sent_at` al salir y re-valida (D8): el rechazo que ya no está
   rechazado y la revocación de un proceso reactivado quedan `obsolete`.
4. Interruptor (invariante 5): con `TITULATEC_EMAIL_ENABLED` apagado los 4 se
   mandan en línea, como hoy, y no se encola nada.
5. La bandeja dice «en cola» mientras haya fila `pending`, y rechazar avisa
   «Se enviará el correo al egresado».
6. Invariante 1: ningún `payload` lleva token, liga, NIP ni contraseña.
7. Barrido de escritores: los 4 `send_*` solo se llaman desde la caída en
   línea de quien encola.

AISLAMIENTO. Igual que `test_mail_dispatch.py`: el despachador toma TODO lo
pendiente de la tabla y la BD de dev trae filas reales, así que corre con un
`now` fijo en 2001 (`AHORA`) y las filas de la prueba se «vencen» a mano. Graph
siempre espiado; nunca se cuenta nada que no se haya sembrado aquí.
"""
from __future__ import annotations

import ast
import hashlib
import secrets
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import unquote

import pytest

import itcj2.models  # noqa: F401

AHORA = datetime(2001, 2, 3, 10, 0)
PERSONAL = "personal.r6@example.invalid"
KINDS = ("enrollment_verified", "enrollment_rejected", "already_enrolled",
         "process_cancelled")
PREFIJO = "[TitulaTec ITCJ] "
ASUNTO_RECHAZO = PREFIJO + "Sobre tu solicitud de inscripción"
ASUNTO_FOLIO = PREFIJO + "Tu inscripción quedó registrada"
ASUNTO_YA = PREFIJO + "Ya tienes un proceso de titulación"
ASUNTO_REVOCADA = PREFIJO + "Cambio en tu inscripción a titulación"
AVISO_RECHAZO = "Se enviará el correo al egresado."
SE_URL = "/titulatec/admin/solicitudes"
ACC_URL = "/titulatec/admin/accesos"
SE_PERMS = (
    "titulatec.enrollment_request.page.list",
    "titulatec.enrollment_request.api.approve",
    "titulatec.enrollment_request.api.reject",
    "titulatec.process.api.read.all",
)
CC_PERMS = (
    "titulatec.enrollment_access.page.list",
    "titulatec.enrollment_access.api.grant",
    "titulatec.enrollment_access.api.return",
    "titulatec.enrollment_access.api.reject",
)
CEROS = {"sent": 0, "failed": 0, "retry": 0, "no_recipient": 0, "obsolete": 0, "waiting": 0}

_APP = Path(__file__).resolve().parents[3] / "itcj2" / "apps" / "titulatec"
_MIGRACION = (Path(__file__).resolve().parents[3] / "migrations" / "versions"
              / "tt20261005d_titulatec_outbox_inscripcion.py")


def _conteo(**kw):
    return {**CEROS, **kw}


# ---------------------------------------------------------------------------
# Andamiaje local
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _correo_encendido(monkeypatch):
    """Correo encendido sin depender del `.env` (se parchea `MailSettings`,
    nunca `get_settings`); espera y tope fijos."""
    from itcj2.apps.titulatec.services.student_mail import MailSettings

    monkeypatch.setattr(MailSettings, "enabled", staticmethod(lambda: True))
    monkeypatch.setattr(MailSettings, "digest_minutes", staticmethod(lambda: 10))
    monkeypatch.setattr(MailSettings, "max_attempts", staticmethod(lambda: 6))


@pytest.fixture()
def apagado(monkeypatch):
    """`TITULATEC_EMAIL_ENABLED = false`: `enqueue` no escribe nada."""
    from itcj2.apps.titulatec.services.student_mail import MailSettings

    monkeypatch.setattr(MailSettings, "enabled", staticmethod(lambda: False))


class _Resp:
    def __init__(self, status_code):
        self.status_code = status_code
        self.text = "respuesta de prueba"


@pytest.fixture()
def graph(monkeypatch):
    """Graph espiado en el módulo FUENTE. `token=None` = cuenta no conectada."""
    estado = SimpleNamespace(enviados=[], token="token-de-prueba", status=202)

    def _enviar(access_token, subject, content_html, to_list, save_to_sent=True):
        estado.enviados.append((subject, list(to_list), content_html))
        return _Resp(estado.status)

    monkeypatch.setattr("itcj2.core.utils.msgraph_mail.acquire_token_silent",
                        lambda app_key: estado.token)
    monkeypatch.setattr("itcj2.core.utils.msgraph_mail.graph_send_mail", _enviar)
    return estado


def _solicitud(db, cohort, *, control, status="pending_review", email=PERSONAL,
               con_token=False, **kw):
    """Solicitud a mano: `(req, token)` (token = `None` sin liga emitida)."""
    from itcj2.apps.titulatec.models import EnrollmentRequest

    token = secrets.token_urlsafe(32) if con_token else None
    row = EnrollmentRequest(
        cohort_id=cohort.id, control_number=control,
        first_name="EGRESADA", last_name="DE PRUEBA", middle_name=None,
        program_id=None, program_text="Ingenieria Ficticia",
        phone="6561234567", contact_email=email, has_efirma=False,
        kind="unknown", status=status, verify_send_count=1 if token else 0,
        verify_token_hash=(hashlib.sha256(token.encode("utf-8")).hexdigest()
                           if token else None),
        verify_expires_at=(datetime.now() + timedelta(days=7)) if token else None,
        verify_sent_at=(datetime.now() - timedelta(hours=1)) if token else None,
        reviewed_at=(datetime.now() - timedelta(hours=1)) if token else None,
    )
    for k, v in kw.items():
        setattr(row, k, v)
    db.add(row)
    db.flush()
    return row, token


def _cuenta(db, make_user, control):
    """Cuenta que YA existe, con contraseña: la liga la puede inscribir."""
    from itcj2.core.utils.security import hash_nip

    user = make_user(first_name="ALUMNA", last_name="REAL", control_number=control,
                     username=control)
    user.password_hash = hash_nip("9999")
    user.must_change_password = False
    db.flush()
    return user


def _filas(db, **filtro):
    """Filas del outbox que casan con `filtro`, frescas de la BD."""
    from itcj2.apps.titulatec.models import EmailOutbox

    db.flush()
    return (db.query(EmailOutbox).filter_by(**filtro)
            .order_by(EmailOutbox.id).populate_existing().all())


def _vencer(db, filas, *, hace=1):
    for fila in filas:
        fila.created_at = fila.not_before = AHORA - timedelta(minutes=hace)
    db.flush()


def _despachar(db, **kw):
    from itcj2.apps.titulatec.services.mail_dispatch import MailDispatcher

    kw.setdefault("now", AHORA)
    return MailDispatcher.run(db, **kw)


def _svc():
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )
    return EnrollmentRequestService


def _revocable(db, make_student, make_process, *, personal=PERSONAL):
    """Proceso vivo convertido desde una solicitud con correo personal."""
    proc = make_process(make_student(first_name="REVOCADA"), phases=False)
    from itcj2.apps.titulatec.models import Cohort

    cohort = db.get(Cohort, proc.cohort_id)
    req, _ = _solicitud(db, cohort, control=f"99{secrets.randbelow(10**6):06d}",
                        status="converted", email=personal,
                        converted_process_id=proc.id)
    return proc, req


def _ya_inscrito(db, make_cohort, make_student, make_process, seed_phase_defs):
    """Alumno con proceso vivo en OTRA convocatoria + la abierta donde lo intenta."""
    seed_phase_defs()
    otra = make_cohort(status="closed")
    cohort = make_cohort(status="open")
    alumno = make_student(first_name="YA INSCRITA")
    proc = make_process(alumno, cohort=otra)
    return alumno, proc, cohort


def _form(control, program_id, email="alguien.r6@example.invalid"):
    return {"control_number": control, "first_name": "ALUMNA", "last_name": "INVENTADA",
            "middle_name": "", "program_id": str(program_id), "phone": "6561234567",
            "contact_email": email, "contact_email_confirm": email,
            "has_efirma": "0", "has_english": "1", "website": ""}


def _solo_esta_convocatoria(db, cohort):
    from itcj2.apps.titulatec.models import Cohort
    (db.query(Cohort).filter(Cohort.id != cohort.id)
     .update({Cohort.status: "closed"}, synchronize_session=False))
    db.flush()


def _fila_html(html: str, prefijo: str, req) -> str:
    marca = f'id="{prefijo}-{req.id}"'
    assert marca in html, f"no está la fila de la solicitud {req.id}"
    return html.split(marca, 1)[1].split("</tr>", 1)[0]


@pytest.fixture()
def make_cc(make_user, make_role, grant_user_role):
    """Centro de Cómputo sintético (rol DIRECTO), como en `test_access_inbox.py`."""
    def _make():
        user = make_user(first_name="CENTRO", last_name="COMPUTO")
        grant_user_role(user, make_role("tt_test_computer_center", CC_PERMS))
        return user

    return _make


# ===========================================================================
# 1. Esquema: modelo y migración
# ===========================================================================
def test_el_catalogo_suma_los_4_kinds_de_inscripcion():
    from itcj2.apps.titulatec.models.email_outbox import ENROLLMENT_KINDS, OUTBOX_KINDS

    assert ENROLLMENT_KINDS == KINDS
    assert set(ENROLLMENT_KINDS) <= set(OUTBOX_KINDS)


def test_el_modelo_declara_la_solicitud_y_el_alumno_opcional():
    from itcj2.apps.titulatec.models import EmailOutbox

    cols = EmailOutbox.__table__.c
    col = cols.enrollment_request_id
    assert type(col.type).__name__ == "BigInteger"
    assert col.nullable is True and col.index is True
    (fk,) = col.foreign_keys
    assert fk.target_fullname == "titulatec_enrollment_requests.id"
    assert cols.user_id.nullable is True


def test_la_migracion_declara_lo_mismo_que_el_modelo():
    src = _MIGRACION.read_text(encoding="utf-8")
    assert 'revision = "tt20261005d"' in src
    assert 'down_revision = "tt20261005c"' in src
    assert '_COLUMN = "enrollment_request_id"' in src
    assert '_REQUESTS = "titulatec_enrollment_requests"' in src
    assert '_FK = "titulatec_email_outbox_enrollment_request_id_fkey"' in src
    assert '_INDEX = "ix_titulatec_email_outbox_enrollment_request_id"' in src
    assert "sa.Column(_COLUMN, sa.BigInteger(), nullable=True)" in src

    up = src.split("def upgrade():", 1)[1].split("def downgrade():", 1)[0]
    down = src.split("def downgrade():", 1)[1]
    sentencias = [ln.strip() for ln in up.splitlines() if ln.strip()]
    assert sentencias[0] == 'op.execute("SET LOCAL lock_timeout = \'10s\'")'
    assert 'op.alter_column(_TABLE, "user_id", existing_type=sa.BigInteger(), nullable=True)' in up
    # Bajada: primero se van las filas sin alumno, LUEGO vuelve el NOT NULL.
    assert down.index("WHERE user_id IS NULL") < down.index("nullable=False")


def test_el_indice_del_modelo_se_llama_como_el_de_la_migracion():
    from itcj2.apps.titulatec.models import EmailOutbox

    nombres = {ix.name for ix in EmailOutbox.__table__.indexes}
    if "ix_titulatec_email_outbox_enrollment_request_id" not in nombres:
        # `index=True` sin nombre: SQLAlchemy lo nombra al crear con la
        # convención por omisión `ix_<tabla>_<columna>`.
        from sqlalchemy.schema import CreateIndex
        from sqlalchemy.dialects import postgresql

        ddl = [str(CreateIndex(ix).compile(dialect=postgresql.dialect()))
               for ix in EmailOutbox.__table__.indexes]
        assert any("ix_titulatec_email_outbox_enrollment_request_id" in d for d in ddl), ddl


def test_una_fila_sin_alumno_ni_solicitud_no_se_inserta(db_session):
    """CHECK de la aplicación (spec §3.7), no de la BD."""
    from itcj2.apps.titulatec.models import EmailOutbox

    with pytest.raises(ValueError, match="alumno o solicitud"):
        with db_session.begin_nested():
            db_session.add(EmailOutbox(kind="enrollment_rejected", payload={}))
            db_session.flush()


def test_una_fila_solo_con_la_solicitud_si_se_inserta(db_session, make_cohort):
    from itcj2.apps.titulatec.models import EmailOutbox

    req, _ = _solicitud(db_session, make_cohort(), control="99606001", status="rejected")
    fila = EmailOutbox(kind="enrollment_rejected", enrollment_request_id=req.id,
                       payload={})
    db_session.add(fila)
    db_session.flush()

    assert fila.id is not None and fila.user_id is None and fila.process_id is None


# ===========================================================================
# 2. `enqueue` acepta la solicitud
# ===========================================================================
def test_enqueue_con_la_solicitud_deja_la_fila_sin_alumno(db_session, make_cohort):
    from itcj2.apps.titulatec.services.student_mail import StudentMail

    req, _ = _solicitud(db_session, make_cohort(), control="99606002", status="rejected")

    assert StudentMail.enqueue(db_session, kind="enrollment_rejected",
                               enrollment_request=req, payload={"reason": "x"}) is True

    (fila,) = _filas(db_session, enrollment_request_id=req.id)
    assert (fila.kind, fila.user_id, fila.process_id, fila.status) == (
        "enrollment_rejected", None, None, "pending")


def test_enqueue_sin_proceso_ni_solicitud_no_escribe(db_session):
    from itcj2.apps.titulatec.models import EmailOutbox
    from itcj2.apps.titulatec.services.student_mail import StudentMail

    assert StudentMail.enqueue(db_session, kind="enrollment_rejected", payload={}) is False
    assert not [o for o in db_session.new if isinstance(o, EmailOutbox)]


# ===========================================================================
# 3. Cada escritor encola y no manda en la petición
# ===========================================================================
def test_rechazar_encola_sin_llamar_a_graph(db_session, make_cohort, make_user, graph,
                                           monkeypatch):
    actor = make_user()
    req, _ = _solicitud(db_session, make_cohort(), control="99606010")
    commits = []
    real = db_session.commit
    monkeypatch.setattr(db_session, "commit", lambda: commits.append(1) or real())

    assert _svc().reject(db_session, req.id, note="  No aparece en el padrón. ",
                         actor_id=actor.id) is True

    assert graph.enviados == [], "el rechazo ya no sale dentro de la petición"
    assert len(commits) == 1, "la fila entra en el MISMO commit del rechazo"
    (fila,) = _filas(db_session, enrollment_request_id=req.id)
    assert (fila.kind, fila.status, fila.user_id, fila.process_id) == (
        "enrollment_rejected", "pending", None, None)
    assert fila.payload == {"reason": "No aparece en el padrón.",
                            "revisor": "Servicios Escolares"}
    db_session.refresh(req)
    assert req.status == "rejected" and req.rejection_sent_at is None


def test_en_modo_alterno_el_rechazo_encolado_lo_firma_centro_de_computo(
    db_session, make_cohort, make_user, modo_alterno, graph,
):
    """Quién firma (`reviewer_label`) se congela en el payload al rechazar, y el
    correo despachado lo pinta igual que el envío en línea."""
    req, _ = _solicitud(db_session, make_cohort(status="open"), control="99606011")

    assert _svc().reject(db_session, req.id, note="No aparece en el padrón.",
                         actor_id=make_user().id) is True

    (fila,) = _filas(db_session, enrollment_request_id=req.id)
    assert fila.payload["revisor"] == "Centro de Cómputo"
    _vencer(db_session, [fila])
    db_session.commit()
    assert _despachar(db_session) == _conteo(sent=1)
    ((_a, _d, html),) = graph.enviados
    assert "Centro de Cómputo" in html and "Servicios Escolares" not in html


def test_verificar_encola_el_aviso_con_folio(db_session, make_cohort, make_user,
                                             seed_phase_defs, titulatec_app, graph):
    from itcj2.apps.titulatec.models import TitulationProcess

    seed_phase_defs()
    cohort = make_cohort(status="open")
    cuenta = _cuenta(db_session, make_user, "99606020")
    req, token = _solicitud(db_session, cohort, control="99606020", status="approved",
                            con_token=True, kind="known")

    _req, outcome = _svc().verify(db_session, token)

    assert outcome == "converted"
    assert graph.enviados == [], "el aviso con folio ya no sale en la petición"
    proc = db_session.get(TitulationProcess, req.converted_process_id)
    (fila,) = _filas(db_session, enrollment_request_id=req.id)
    assert (fila.kind, fila.process_id, fila.user_id, fila.status) == (
        "enrollment_verified", proc.id, cuenta.id, "pending")
    assert fila.payload == {"folio": proc.folio}


def test_revocar_encola_el_aviso_una_sola_vez(db_session, make_student, make_process,
                                              make_user, graph):
    from itcj2.apps.titulatec.services.process_service import ProcessService

    proc, _req = _revocable(db_session, make_student, make_process)
    actor = make_user()

    ok, _ = ProcessService.cancel(db_session, proc.id, reason="Documentación falsa",
                                  actor_id=actor.id)
    otra, _ = ProcessService.cancel(db_session, proc.id, reason="Otra vez",
                                    actor_id=actor.id)

    assert ok and not otra
    assert graph.enviados == []
    (fila,) = _filas(db_session, process_id=proc.id, kind="process_cancelled")
    assert (fila.user_id, fila.enrollment_request_id, fila.status) == (
        proc.student_id, None, "pending")
    assert fila.payload == {}, "el aviso de revocación no lleva el motivo (D1)"


def test_create_de_un_ya_inscrito_encola_el_aviso(db_session, make_cohort, make_student,
                                                  make_process, seed_phase_defs, graph):
    from itcj2.apps.titulatec.models import EnrollmentRequest

    alumno, proc, cohort = _ya_inscrito(db_session, make_cohort, make_student,
                                        make_process, seed_phase_defs)

    req, outcome = _svc().create(
        db_session, cohort,
        {"control_number": alumno.control_number, "first_name": "X", "last_name": "Y",
         "phone": "6560000000", "contact_email": "extrano.r6@example.invalid",
         "has_efirma": False},
        client_ip=None)

    assert (req, outcome) == (None, "existing_process")
    assert graph.enviados == []
    assert (db_session.query(EnrollmentRequest)
            .filter_by(control_number=alumno.control_number).count()) == 0
    (fila,) = _filas(db_session, process_id=proc.id, kind="already_enrolled")
    assert (fila.user_id, fila.enrollment_request_id, fila.payload) == (
        alumno.id, None, {"folio": proc.folio})


def test_post_inscripcion_de_un_ya_inscrito_encola_ya_inscrito(
    client, db_session, make_cohort, make_student, make_process, seed_phase_defs,
    make_program, graph,
):
    alumno, proc, cohort = _ya_inscrito(db_session, make_cohort, make_student,
                                        make_process, seed_phase_defs)
    programa = make_program("Ingeniería Ficticia R6")
    _solo_esta_convocatoria(db_session, cohort)
    client.cookies.clear()

    resp = client.post("/titulatec/inscripcion",
                       data=_form(alumno.control_number, programa.id),
                       headers={"X-Real-IP": "203.0.113.61"}, follow_redirects=False)

    assert resp.status_code == 200
    assert 'data-tt-notice="generic"' in resp.text
    assert graph.enviados == []
    (fila,) = _filas(db_session, process_id=proc.id, kind="already_enrolled")
    assert fila.status == "pending"


# ===========================================================================
# 4. El despachador: destinatario, sello y re-validación
# ===========================================================================
def _rechazada_en_cola(db, make_cohort, make_user, *, control, email=PERSONAL):
    req, _ = _solicitud(db, make_cohort(), control=control, email=email)
    assert _svc().reject(db, req.id, note="No aparece en el padrón.",
                         actor_id=make_user().id) is True
    filas = _filas(db, enrollment_request_id=req.id)
    _vencer(db, filas)
    db.commit()
    return req, filas[0]


def test_el_despachador_manda_el_rechazo_y_sella(db_session, make_cohort, make_user,
                                                 graph):
    req, fila = _rechazada_en_cola(db_session, make_cohort, make_user, control="99606030")

    assert _despachar(db_session) == _conteo(sent=1)

    (asunto, destinatarios, html), = graph.enviados
    assert (asunto, destinatarios) == (ASUNTO_RECHAZO, [PERSONAL])
    assert "No aparece en el padrón." in html and "99606030" in html
    db_session.refresh(fila)
    db_session.refresh(req)
    assert (fila.status, fila.sent_to, fila.subject, fila.sent_at, fila.last_error) == (
        "sent", PERSONAL, ASUNTO_RECHAZO, AHORA, None)
    assert req.rejection_sent_at == AHORA, "el despachador sella en su transacción"


def test_una_solicitud_sin_usuario_tambien_se_despacha(db_session, make_cohort,
                                                       make_user, graph):
    from itcj2.core.models.user import User

    req, fila = _rechazada_en_cola(db_session, make_cohort, make_user, control="99606031")
    assert db_session.query(User).filter_by(control_number="99606031").first() is None
    assert fila.user_id is None

    assert _despachar(db_session) == _conteo(sent=1)
    db_session.refresh(fila)
    assert fila.status == "sent"


def test_el_rechazo_que_ya_no_esta_rechazado_queda_obsoleto(db_session, make_cohort,
                                                            make_user, graph):
    req, fila = _rechazada_en_cola(db_session, make_cohort, make_user, control="99606032")
    req.status = "pending_review"
    db_session.commit()

    assert _despachar(db_session) == _conteo(obsolete=1)

    assert graph.enviados == []
    db_session.refresh(fila)
    db_session.refresh(req)
    assert (fila.status, fila.last_error) == ("obsolete", "la solicitud ya no está rechazada")
    assert req.rejection_sent_at is None


def test_sin_cuenta_de_graph_reintenta_y_no_sella(db_session, make_cohort, make_user,
                                                  graph):
    graph.token = None
    req, fila = _rechazada_en_cola(db_session, make_cohort, make_user, control="99606033")

    assert _despachar(db_session) == _conteo(retry=1)

    db_session.refresh(fila)
    db_session.refresh(req)
    assert (fila.status, fila.attempts, fila.last_error) == (
        "pending", 1, "Cuenta de correo no conectada")
    assert req.rejection_sent_at is None


def test_un_rechazo_sin_correo_personal_queda_sin_destinatario(db_session, make_cohort,
                                                               make_user, graph):
    req, fila = _rechazada_en_cola(db_session, make_cohort, make_user, control="99606034",
                                   email="")

    assert _despachar(db_session) == _conteo(no_recipient=1)

    assert graph.enviados == []
    db_session.refresh(fila)
    assert fila.status == "no_recipient"


def test_el_folio_sale_al_institucional_aunque_luego_revoquen(
    db_session, make_cohort, make_user, seed_phase_defs, titulatec_app, graph,
):
    """`enrollment_verified` no tiene forma de quedar obsoleto (spec §3.7): la
    revocación posterior no lo calla (es la alarma de la dueña de la cuenta), y
    el «proceso revocado → obsoleto» del despachador no se come el aviso de la
    revocación."""
    from itcj2.apps.titulatec.models import TitulationProcess
    from itcj2.apps.titulatec.services.process_service import ProcessService
    from itcj2.core.utils.email_tools import student_email

    seed_phase_defs()
    cohort = make_cohort(status="open")
    cuenta = _cuenta(db_session, make_user, "99606040")
    req, token = _solicitud(db_session, cohort, control="99606040", status="approved",
                            con_token=True, kind="known")
    assert _svc().verify(db_session, token)[1] == "converted"
    proc = db_session.get(TitulationProcess, req.converted_process_id)
    ok, _ = ProcessService.cancel(db_session, proc.id, reason="Duplicada",
                                  actor_id=make_user().id)
    assert ok
    filas = _filas(db_session, process_id=proc.id)
    assert [f.kind for f in filas] == ["enrollment_verified", "process_cancelled"]
    _vencer(db_session, filas)
    db_session.commit()

    assert _despachar(db_session) == _conteo(sent=2)

    institucional = student_email(cuenta)
    # La revocación es UN mensaje con los dos buzones en «Para» (revisión
    # final M2): una sola llamada a Graph.
    assert [(a, d) for a, d, _h in graph.enviados] == [
        (ASUNTO_FOLIO, [institucional]),
        (ASUNTO_REVOCADA, [institucional, PERSONAL]),
    ]
    assert proc.folio in graph.enviados[0][2]
    filas = _filas(db_session, process_id=proc.id)
    assert [f.status for f in filas] == ["sent", "sent"]
    assert filas[1].sent_to == f"{institucional}, {PERSONAL}"


def test_la_revocacion_que_no_sale_no_se_manda_a_medias(
    db_session, make_student, make_process, make_user, graph,
):
    """Revisión final M2: con Graph fallando, la revocación es UN intento de
    UNA llamada (no una por buzón: dos esperas de hasta 30 s contra el
    `soft_time_limit=50` de la tarea) y el reintento la vuelve a mandar
    ENTERA, nunca a un buzón que ya la recibió."""
    from itcj2.apps.titulatec.services.process_service import ProcessService

    proc, _req = _revocable(db_session, make_student, make_process)
    assert ProcessService.cancel(db_session, proc.id, reason="x",
                                 actor_id=make_user().id)[0]
    (fila,) = _filas(db_session, process_id=proc.id, kind="process_cancelled")
    _vencer(db_session, [fila])
    db_session.commit()
    graph.status = 500

    assert _despachar(db_session) == _conteo(retry=1)

    ((asunto, destinatarios, _html),) = graph.enviados
    assert asunto == ASUNTO_REVOCADA
    assert len(destinatarios) == 2 and PERSONAL in destinatarios
    (fila,) = _filas(db_session, process_id=proc.id, kind="process_cancelled")
    assert (fila.status, fila.attempts, fila.last_error) == (
        "pending", 1, "Error al enviar")


def test_la_revocacion_de_un_proceso_reactivado_queda_obsoleta(
    db_session, make_student, make_process, make_user, graph,
):
    from itcj2.apps.titulatec.services.process_service import ProcessService

    proc, _req = _revocable(db_session, make_student, make_process)
    assert ProcessService.cancel(db_session, proc.id, reason="x",
                                 actor_id=make_user().id)[0]
    filas = _filas(db_session, process_id=proc.id, kind="process_cancelled")
    _vencer(db_session, filas)
    proc.status = "active"
    db_session.commit()

    assert _despachar(db_session) == _conteo(obsolete=1)

    assert graph.enviados == []
    db_session.refresh(filas[0])
    assert (filas[0].status, filas[0].last_error) == (
        "obsolete", "la inscripción ya no está revocada")


def test_ya_inscrito_sale_al_institucional(db_session, make_cohort, make_student,
                                           make_process, seed_phase_defs, graph):
    from itcj2.core.utils.email_tools import student_email

    alumno, proc, cohort = _ya_inscrito(db_session, make_cohort, make_student,
                                        make_process, seed_phase_defs)
    _svc().create(db_session, cohort,
                  {"control_number": alumno.control_number, "first_name": "X",
                   "last_name": "Y", "phone": "6560000000",
                   "contact_email": "extrano.r6@example.invalid", "has_efirma": False},
                  client_ip=None)
    filas = _filas(db_session, process_id=proc.id, kind="already_enrolled")
    _vencer(db_session, filas)
    db_session.commit()

    assert _despachar(db_session) == _conteo(sent=1)

    ((asunto, destinatarios, html),) = graph.enviados
    assert (asunto, destinatarios) == (ASUNTO_YA, [student_email(alumno)])
    assert "extrano.r6@example.invalid" not in destinatarios, "E8: nunca al tecleado"
    assert proc.folio in html


# ---------------------------------------------------------------------------
# El MISMO correo que en línea: plantilla, asunto, destinatarios y HTML.
# ---------------------------------------------------------------------------
def _escenario(kind, db, *, make_cohort, make_user, make_student, make_process,
               seed_phase_defs):
    """Prepara el caso de `kind` y devuelve `(en_linea, encolar)`: la llamada
    de HOY al helper y la del servicio que ahora encola."""
    from itcj2.apps.titulatec.models import TitulationProcess
    from itcj2.apps.titulatec.services.email_helper import TitulaTecEmailHelper as H
    from itcj2.apps.titulatec.services.process_service import ProcessService

    if kind == "enrollment_rejected":
        req, _ = _solicitud(db, make_cohort(), control="99606050")
        actor = make_user().id

        def _encolar():
            assert _svc().reject(db, req.id, note="Motivo <b>con</b> HTML", actor_id=actor)

        def _en_linea():
            H.send_enrollment_rejected(db, req)
        return _en_linea, _encolar

    if kind == "enrollment_verified":
        seed_phase_defs()
        cohort = make_cohort(status="open")
        _cuenta(db, make_user, "99606051")
        req, token = _solicitud(db, cohort, control="99606051", status="approved",
                                con_token=True, kind="known")

        def _encolar():
            assert _svc().verify(db, token)[1] == "converted"

        def _en_linea():
            H.send_enrollment_done(db, req, db.get(TitulationProcess,
                                                   req.converted_process_id))
        return _en_linea, _encolar

    if kind == "already_enrolled":
        alumno, proc, cohort = _ya_inscrito(db, make_cohort, make_student, make_process,
                                            seed_phase_defs)

        def _encolar():
            _svc().create(db, cohort, {"control_number": alumno.control_number,
                                       "first_name": "X", "last_name": "Y",
                                       "phone": "6560000000",
                                       "contact_email": "otro.r6@example.invalid",
                                       "has_efirma": False}, client_ip=None)

        def _en_linea():
            H.send_already_enrolled(db, alumno, proc)
        return _en_linea, _encolar

    proc, _req = _revocable(db, make_student, make_process)
    actor = make_user().id

    def _encolar():
        assert ProcessService.cancel(db, proc.id, reason="x", actor_id=actor)[0]

    def _en_linea():
        H.send_process_cancelled(db, proc)
    return _en_linea, _encolar


@pytest.mark.parametrize("kind", KINDS)
def test_el_despachador_manda_el_mismo_correo_que_en_linea(
    kind, db_session, make_cohort, make_user, make_student, make_process,
    seed_phase_defs, titulatec_app, graph,
):
    from itcj2.apps.titulatec.models import EmailOutbox

    en_linea, encolar = _escenario(
        kind, db_session, make_cohort=make_cohort, make_user=make_user,
        make_student=make_student, make_process=make_process,
        seed_phase_defs=seed_phase_defs)
    antes = {f.id for f in _filas(db_session, kind=kind, status="pending")}
    encolar()
    filas = [f for f in _filas(db_session, kind=kind, status="pending")
             if f.id not in antes]
    assert len(filas) == 1
    _vencer(db_session, filas)
    db_session.commit()
    assert graph.enviados == []

    assert _despachar(db_session) == _conteo(sent=1)
    despachado = list(graph.enviados)
    graph.enviados.clear()
    en_linea()                      # el envío de HOY, con el estado ya escrito

    assert despachado == graph.enviados, "outbox y en línea tienen que ser el MISMO correo"
    assert db_session.get(EmailOutbox, filas[0].id).status == "sent"


# ===========================================================================
# 5. Interruptor apagado: los 4 en línea, como hoy (invariante 5)
# ===========================================================================
def test_apagado_los_cuatro_mandan_en_linea_y_no_encolan(
    apagado, db_session, make_cohort, make_user, make_student, make_process,
    seed_phase_defs, titulatec_app, graph,
):
    from itcj2.apps.titulatec.models import TitulationProcess
    from itcj2.apps.titulatec.services.process_service import ProcessService
    from itcj2.core.models.user import User
    from itcj2.core.utils.email_tools import student_email

    # rechazo -> correo personal, sellado como hoy
    req, _ = _solicitud(db_session, make_cohort(), control="99606060")
    assert _svc().reject(db_session, req.id, note="Motivo", actor_id=make_user().id)
    db_session.refresh(req)
    assert req.rejection_sent_at is not None

    # liga abierta -> folio al institucional
    seed_phase_defs()
    cohort = make_cohort(status="open")
    cuenta = _cuenta(db_session, make_user, "99606061")
    req2, token = _solicitud(db_session, cohort, control="99606061", status="approved",
                             con_token=True, kind="known")
    assert _svc().verify(db_session, token)[1] == "converted"

    # ya inscrito -> institucional
    alumno, proc3, cohort3 = _ya_inscrito(db_session, make_cohort, make_student,
                                          make_process, seed_phase_defs)
    _svc().create(db_session, cohort3,
                  {"control_number": alumno.control_number, "first_name": "X",
                   "last_name": "Y", "phone": "6560000000",
                   "contact_email": "otro.r6@example.invalid", "has_efirma": False},
                  client_ip=None)

    # revocación -> institucional + personal
    proc4, _r = _revocable(db_session, make_student, make_process)
    assert ProcessService.cancel(db_session, proc4.id, reason="x",
                                 actor_id=make_user().id)[0]

    proc2 = db_session.get(TitulationProcess, req2.converted_process_id)
    assert [(a, d) for a, d, _h in graph.enviados] == [
        (ASUNTO_RECHAZO, [PERSONAL]),
        (ASUNTO_FOLIO, [student_email(cuenta)]),
        (ASUNTO_YA, [student_email(alumno)]),
        (ASUNTO_REVOCADA, [student_email(db_session.get(User, proc4.student_id)),
                           PERSONAL]),
    ]
    assert _filas(db_session, enrollment_request_id=req.id) == []
    for pid in (proc2.id, proc3.id, proc4.id):
        assert [f for f in _filas(db_session, process_id=pid) if f.kind in KINDS] == []


# ===========================================================================
# 6. La bandeja: «en cola» y el aviso al rechazar
# ===========================================================================
def _pendiente(db, req, status="pending"):
    from itcj2.apps.titulatec.models import EmailOutbox

    fila = EmailOutbox(kind="enrollment_rejected", enrollment_request_id=req.id,
                       payload={"reason": req.review_note}, status=status)
    db.add(fila)
    db.flush()
    return fila


@pytest.mark.parametrize("estado,pildora", [
    ("pending", "en cola"),
    ("failed", "correo no enviado"),
    (None, "correo no enviado"),
])
def test_solicitudes_dice_en_cola_mientras_haya_fila_pendiente(
    estado, pildora, client_as, db_session, make_head, make_cohort,
):
    head = make_head(perm_codes=SE_PERMS)
    cohort = make_cohort(status="open")
    req, _ = _solicitud(db_session, cohort, control="99606070", status="rejected",
                        review_note="No aparece en el padrón.")
    if estado is not None:
        _pendiente(db_session, req, estado)

    html = client_as(head).get(f"{SE_URL}/body?status=rejected&cohort_id={cohort.id}").text
    fila = _fila_html(html, "tt-req", req)

    assert pildora in fila
    otra = {"en cola", "correo no enviado"} - {pildora}
    assert otra.pop() not in fila


def test_accesos_dice_en_cola_mientras_haya_fila_pendiente(
    client_as, db_session, make_cc, make_cohort, modo_alterno,
):
    cohort = make_cohort(status="open")
    en_cola, _ = _solicitud(db_session, cohort, control="99606071", status="rejected",
                            review_note="Duplicada.")
    sin_fila, _ = _solicitud(db_session, cohort, control="99606072", status="rejected",
                             review_note="Duplicada.")
    _pendiente(db_session, en_cola)

    html = client_as(make_cc()).get(
        f"{ACC_URL}/body?status=rejected&cohort_id={cohort.id}").text

    assert "en cola" in _fila_html(html, "tt-acc", en_cola)
    assert "correo no enviado" not in _fila_html(html, "tt-acc", en_cola)
    assert "correo no enviado" in _fila_html(html, "tt-acc", sin_fila)


def test_rechazar_en_solicitudes_avisa_que_se_enviara(
    client_as, db_session, make_head, make_cohort, graph,
):
    head = make_head(perm_codes=SE_PERMS)
    cohort = make_cohort(status="open")
    req, _ = _solicitud(db_session, cohort, control="99606080")

    resp = client_as(head).post(f"{SE_URL}/{req.id}/rechazar", data={
        "note": "No aparece en el padrón.", "status": "rejected",
        "cohort_id": str(cohort.id)})

    assert resp.status_code == 200, unquote(resp.headers.get("X-Tt-Error", ""))
    assert unquote(resp.headers["X-Tt-Notice"]) == AVISO_RECHAZO
    assert resp.headers["X-Tt-Notice-Kind"] == "success"
    assert graph.enviados == []
    assert "en cola" in _fila_html(resp.text, "tt-req", req)


def test_rechazar_en_accesos_avisa_que_se_enviara(
    client_as, db_session, make_cc, make_cohort, modo_alterno, graph,
):
    cohort = make_cohort(status="open")
    req, _ = _solicitud(db_session, cohort, control="99606081")

    resp = client_as(make_cc()).post(f"{ACC_URL}/{req.id}/rechazar", data={
        "note": "No procede.", "status": "rejected", "cohort_id": str(cohort.id)})

    assert resp.status_code == 200, unquote(resp.headers.get("X-Tt-Error", ""))
    assert unquote(resp.headers["X-Tt-Notice"]) == AVISO_RECHAZO
    assert resp.headers["X-Tt-Notice-Kind"] == "success"
    assert graph.enviados == []


def test_apagado_rechazar_no_promete_un_envio_que_ya_ocurrio(
    apagado, client_as, db_session, make_head, make_cohort, graph,
):
    """Con el interruptor apagado el rechazo sale en línea (como hoy): la ruta
    responde como hoy, sin el aviso, y la píldora dice la verdad."""
    head = make_head(perm_codes=SE_PERMS)
    cohort = make_cohort(status="open")
    req, _ = _solicitud(db_session, cohort, control="99606082")

    resp = client_as(head).post(f"{SE_URL}/{req.id}/rechazar", data={
        "note": "No aparece en el padrón.", "status": "rejected",
        "cohort_id": str(cohort.id)})

    assert resp.status_code == 200
    assert "X-Tt-Notice" not in resp.headers
    assert [d for _a, d, _h in graph.enviados] == [[PERSONAL]]
    fila = _fila_html(resp.text, "tt-req", req)
    assert "en cola" not in fila and "correo no enviado" not in fila


# ===========================================================================
# 7. Invariante 1: ningún secreto en el payload de los 4 kinds
# ===========================================================================
_PROHIBIDAS = ("token", "link", "liga", "nip", "password", "contrasena", "contraseña")


def _claves_y_textos(valor, claves, textos):
    if isinstance(valor, dict):
        for k, v in valor.items():
            claves.append(str(k).lower())
            _claves_y_textos(v, claves, textos)
    elif isinstance(valor, (list, tuple)):
        for v in valor:
            _claves_y_textos(v, claves, textos)
    elif isinstance(valor, str):
        textos.append(valor)


def test_ningun_payload_de_inscripcion_lleva_secretos(
    db_session, make_cohort, make_user, make_student, make_process, seed_phase_defs,
    titulatec_app, graph,
):
    from itcj2.apps.titulatec.services.process_service import ProcessService

    seed_phase_defs()
    cohort = make_cohort(status="open")
    _cuenta(db_session, make_user, "99606090")
    verificada, token_v = _solicitud(db_session, cohort, control="99606090",
                                     status="approved", con_token=True, kind="known")
    assert _svc().verify(db_session, token_v)[1] == "converted"
    # Un rechazo de una solicitud con la liga EN CAMINO: el token existía.
    rechazada, token_r = _solicitud(db_session, cohort, control="99606091",
                                    status="approved", con_token=True)
    hash_r = rechazada.verify_token_hash
    assert _svc().reject(db_session, rechazada.id, note="Cancelada", actor_id=make_user().id)
    alumno, proc, cohort3 = _ya_inscrito(db_session, make_cohort, make_student,
                                         make_process, seed_phase_defs)
    _svc().create(db_session, cohort3,
                  {"control_number": alumno.control_number, "first_name": "X",
                   "last_name": "Y", "phone": "6560000000",
                   "contact_email": "otro.r6@example.invalid", "has_efirma": False},
                  client_ip=None)
    assert ProcessService.cancel(db_session, proc.id, reason="x",
                                 actor_id=make_user().id)[0]

    filas = (_filas(db_session, enrollment_request_id=verificada.id)
             + _filas(db_session, enrollment_request_id=rechazada.id)
             + [f for f in _filas(db_session, process_id=proc.id) if f.kind in KINDS])
    assert sorted(f.kind for f in filas) == sorted(KINDS)
    secretos = {token_v, token_r, hash_r, hashlib.sha256(token_v.encode()).hexdigest()}
    for fila in filas:
        claves, textos = [], []
        _claves_y_textos(fila.payload, claves, textos)
        for clave in claves:
            assert not any(p in clave for p in _PROHIBIDAS), (fila.kind, clave)
        for texto in textos:
            assert not any(s in texto for s in secretos), (fila.kind, "secreto en el payload")
            assert "http" not in texto, (fila.kind, "una liga en el payload")


# ===========================================================================
# 8. Barrido de escritores: nadie manda en línea sin haber intentado encolar
# ===========================================================================
# `send_*` de hoy -> la función de `StudentMail` que lo encola.
_EN_LINEA_A_COLA = {
    "send_enrollment_done": "enrollment_verified",
    "send_enrollment_rejected": "enrollment_rejected",
    "send_already_enrolled": "already_enrolled",
    "send_process_cancelled": "process_cancelled",
}
# Los ÚNICOS lugares que hoy mandan esos 4 correos (todo lo demás es el helper).
_ESCRITORES = {
    "EnrollmentRequestService.verify": "send_enrollment_done",
    "EnrollmentRequestService.reject": "send_enrollment_rejected",
    "EnrollmentRequestService.create": "send_already_enrolled",
    "ProcessService.cancel": "send_process_cancelled",
}


def _funciones():
    for path in sorted((_APP / "services").rglob("*.py")) + sorted((_APP / "pages").glob("*.py")):
        if path.name == "email_helper.py":
            continue
        arbol = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for nodo in arbol.body:
            if isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)):
                yield f"{path.stem}.{nodo.name}", nodo
            elif isinstance(nodo, ast.ClassDef):
                for item in nodo.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        yield f"{nodo.name}.{item.name}", item


def _llamadas(fn):
    return {n.func.attr for n in ast.walk(fn)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}


def _llamadas_a_student_mail(fn):
    return {n.func.attr for n in ast.walk(fn)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and isinstance(n.func.value, ast.Name) and n.func.value.id == "StudentMail"}


def test_los_cuatro_envios_en_linea_solo_viven_en_su_caida():
    """Todo lugar que llama a uno de los 4 `send_*` es uno de los 4 escritores
    registrados, y ese escritor llama ANTES a su `StudentMail.<kind>`: el envío
    en línea es solo la caída con el interruptor apagado (lo prueba
    `test_apagado_los_cuatro_mandan_en_linea_y_no_encolan`; que no salga nada
    con el interruptor encendido, las pruebas de la sección 3)."""
    encontrados = {}
    for nombre, fn in _funciones():
        envios = _llamadas(fn) & set(_EN_LINEA_A_COLA)
        if envios:
            encontrados[nombre] = envios
    assert encontrados == {n: {s} for n, s in _ESCRITORES.items()}, encontrados

    funciones = dict(_funciones())
    for nombre, envio in _ESCRITORES.items():
        assert _EN_LINEA_A_COLA[envio] in _llamadas_a_student_mail(funciones[nombre]), (
            f"{nombre} manda {envio} en línea sin encolar antes")


def test_la_regla_de_ubicacion_del_envio_es_una_rama_condicional():
    """La llamada en línea de cada escritor vive DENTRO de un `if` (la caída),
    nunca suelta en el cuerpo: si quedara suelta saldría siempre, también con
    el interruptor encendido."""
    funciones = dict(_funciones())
    for nombre, envio in _ESCRITORES.items():
        fn = funciones[nombre]
        dentro_de_if = set()
        for nodo in ast.walk(fn):
            if isinstance(nodo, ast.If):
                for sub in ast.walk(nodo):
                    if (isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute)
                            and sub.func.attr == envio):
                        dentro_de_if.add(id(sub))
        todas = [sub for sub in ast.walk(fn)
                 if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute)
                 and sub.func.attr == envio]
        assert todas and all(id(c) in dentro_de_if for c in todas), nombre
        # Y la condición menciona lo que devolvió el encolado.
        assert "not encolado" in ast.unparse(fn), nombre
