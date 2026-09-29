"""Despachador de los correos del proceso (spec 2026-09-28 §6 C3; Tarea 7).

Lo que se fija aquí:

1. Una fila suelta sale UNA vez por Graph (siempre espiado: nunca un envío
   real) y queda `sent` con `sent_at`, `sent_to` y `subject`.
2. Grupos (D7, Review Focus 5): no salen antes de la espera; después, UN correo
   y todas sus filas con el mismo desenlace. Un movimiento nuevo reinicia la
   espera, y el grupo se toma completo aunque el `limit` lo corte.
3. Revocado → obsoleto; sin correo personal → `no_recipient`; el `Obsolete`
   del compositor → obsoleto con su motivo.
4. Reintentos con espera creciente y `failed` al tope; un error inesperado
   cuenta como intento (ruling 2026-09-29) y no detiene el lote.
5. Concurrencia (Review Focus 1): la consulta usa `FOR UPDATE SKIP LOCKED`; una
   segunda corrida no reenvía; una fila que otra corrida mandó mientras esta
   estaba ocupada tampoco.
6. E9 ampliado: `[TT-MAIL]` solo fuera de producción y solo sin cuenta.
7. `_deliver` (los 6 correos de inscripción) sin cambios; `deliver_detailed`
   da el motivo del fallo.

AISLAMIENTO. El despachador toma TODO lo pendiente de la tabla, y la BD de dev
puede traer filas reales pendientes. Por eso cada prueba corre con un `now`
fijo en el pasado (`AHORA`, 2001): lo real, creado con el reloj de verdad, no
está vencido a esa hora y ni se toca. Las filas de la prueba llevan
`created_at`/`not_before` explícitos respecto de `AHORA`.

La sesión del arnés vive en un savepoint y el despachador hace commit por
unidad (y rollback ante un error): cada prueba hace `db_session.commit()` tras
armar sus datos, o el rollback de una unidad se llevaría el andamiaje.
"""
from __future__ import annotations

import inspect
import logging
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

import itcj2.models  # noqa: F401

AHORA = datetime(2001, 2, 3, 10, 0)
CORREO = "personal@example.invalid"
PREFIJO = "[TitulaTec ITCJ] "
ASUNTO_FASE = PREFIJO + "Una fase necesita correcciones: Fase 01 · Documentos iniciales"
CEROS = {"sent": 0, "failed": 0, "retry": 0, "no_recipient": 0, "obsolete": 0, "waiting": 0}


def _conteo(**kw):
    return {**CEROS, **kw}


# ---------------------------------------------------------------------------
# Andamiaje local
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _correo_encendido(monkeypatch):
    """Correo encendido sin depender del `.env` del contenedor (mismo molde
    que `test_student_mail.py`); la espera y el tope, los del spec C6,
    parcheados en `MailSettings` (nunca en `get_settings`)."""
    from itcj2.apps.titulatec.services.student_mail import MailSettings
    from itcj2.config import get_settings

    monkeypatch.setattr(get_settings(), "TITULATEC_EMAIL_ENABLED", True)
    monkeypatch.setattr(MailSettings, "digest_minutes", staticmethod(lambda: 10))
    monkeypatch.setattr(MailSettings, "max_attempts", staticmethod(lambda: 6))


class _Resp:
    def __init__(self, status_code):
        self.status_code = status_code
        self.text = "respuesta de prueba"


@pytest.fixture()
def graph(monkeypatch):
    """Graph espiado en el módulo FUENTE (los imports de `email_helper` son
    locales). `token=None` = cuenta no conectada; `status` = lo que responde el
    envío; `al_enviar` = efecto colateral durante el envío (otra corrida, un
    Graph lento)."""
    estado = SimpleNamespace(enviados=[], token="token-de-prueba", status=202,
                             al_enviar=None)

    def _token(app_key):
        return estado.token

    def _enviar(access_token, subject, content_html, to_list, save_to_sent=True):
        estado.enviados.append((subject, list(to_list), content_html))
        if estado.al_enviar is not None:
            estado.al_enviar()
        return _Resp(estado.status)

    monkeypatch.setattr("itcj2.core.utils.msgraph_mail.acquire_token_silent", _token)
    monkeypatch.setattr("itcj2.core.utils.msgraph_mail.graph_send_mail", _enviar)
    return estado


@pytest.fixture()
def egresado(db_session, make_student, make_process):
    """Proceso de un egresado ficticio con su correo PERSONAL en el perfil (D2).
    `correo=None` = sin perfil ni solicitud: no hay a dónde mandar."""
    from itcj2.core.models.student_profile import StudentProfile

    def _make(correo=CORREO, status="active"):
        proc = make_process(make_student(first_name="ALUMNA"), phases=False, status=status)
        if correo is not None:
            db_session.add(StudentProfile(user_id=proc.student_id, contact_email=correo))
            db_session.flush()
        return proc

    return _make


def _filas(db, pid):
    """Filas del outbox del proceso por id, leídas de la BD (no de memoria)."""
    from itcj2.apps.titulatec.models import EmailOutbox

    db.flush()
    return (db.query(EmailOutbox).filter_by(process_id=pid)
            .order_by(EmailOutbox.id).populate_existing().all())


def _vencer(db, filas, *, hace):
    """`created_at` = `not_before` = `AHORA - hace` minutos."""
    for fila in filas:
        fila.created_at = fila.not_before = AHORA - timedelta(minutes=hace)
    db.flush()


def _suelta(db, proc, *, hace=1, motivo="Falta la firma del director."):
    """Una fila SUELTA (`phase_rejected`, #3) por el contrato real de `StudentMail`."""
    from itcj2.apps.titulatec.services.student_mail import StudentMail

    assert StudentMail.phase_rejected(db, proc, phase_number=1,
                                      phase_name="Fase 01 · Documentos iniciales",
                                      reason=motivo) is True
    fila = _filas(db, proc.id)[-1]
    _vencer(db, [fila], hace=hace)
    return fila


_DOCS = (("birth_certificate", "Acta de nacimiento", "approved", None),
         ("curp", "CURP certificada", "rejected", "Ilegible."),
         ("high_school_cert", "Certificado de bachillerato", "approved", None))


def _dictamenes(db, proc, *, hace, cuantos=2):
    """Dictámenes del grupo `docs:{pid}` (#1), por el contrato real de `StudentMail`."""
    from itcj2.apps.titulatec.services.student_mail import StudentMail

    antes = {f.id for f in _filas(db, proc.id)}
    for code, name, status, note in _DOCS[:cuantos]:
        assert StudentMail.doc_reviewed(db, proc, type_code=code, doc_name=name,
                                        status=status, note=note) is True
    filas = [f for f in _filas(db, proc.id) if f.id not in antes]
    _vencer(db, filas, hace=hace)
    return filas


def _despachar(db, **kw):
    from itcj2.apps.titulatec.services.mail_dispatch import MailDispatcher

    kw.setdefault("now", AHORA)
    return MailDispatcher.run(db, **kw)


def _refrescar(db, *filas):
    for fila in filas:
        db.refresh(fila)
    return filas


# ---------------------------------------------------------------------------
# Envío
# ---------------------------------------------------------------------------
def test_envia_una_suelta(db_session, egresado, graph):
    proc = egresado()
    fila = _suelta(db_session, proc)
    db_session.commit()

    out = _despachar(db_session)

    assert out == _conteo(sent=1)
    (asunto, destinatarios, html), = graph.enviados
    assert destinatarios == [CORREO]
    assert asunto == ASUNTO_FASE
    assert "Falta la firma del director." in html
    _refrescar(db_session, fila)
    assert (fila.status, fila.sent_to, fila.subject, fila.sent_at) == (
        "sent", CORREO, ASUNTO_FASE, AHORA)
    assert (fila.attempts, fila.last_error) == (0, None)


def test_sin_now_usa_db_now(db_session, egresado, graph, monkeypatch):
    """El reloj es `db_now()` (hora local naive, la de `NOW()`), nunca otro."""
    from itcj2.apps.titulatec.services import mail_dispatch

    monkeypatch.setattr(mail_dispatch, "db_now", lambda: AHORA)
    fila = _suelta(db_session, egresado())
    db_session.commit()

    assert mail_dispatch.MailDispatcher.run(db_session) == _conteo(sent=1)
    _refrescar(db_session, fila)
    assert fila.sent_at == AHORA


# ---------------------------------------------------------------------------
# Grupos (D7, Review Focus 5)
# ---------------------------------------------------------------------------
def test_grupo_espera_y_luego_sale_una_vez(db_session, egresado, graph):
    proc = egresado()
    filas = _dictamenes(db_session, proc, hace=5)      # último movimiento: hace 5 min
    db_session.commit()

    assert _despachar(db_session) == _conteo(waiting=1)
    assert graph.enviados == []
    for fila in _refrescar(db_session, *filas):
        assert (fila.status, fila.attempts, fila.subject, fila.last_error) == (
            "pending", 0, None, None)

    # Justo al cumplir la espera (10 min sin movimiento) sale: `created_at <= now - espera`.
    despues = AHORA + timedelta(minutes=5)
    assert _despachar(db_session, now=despues) == _conteo(sent=1)

    (asunto, destinatarios, html), = graph.enviados
    assert destinatarios == [CORREO]
    assert asunto.startswith(PREFIJO)
    assert "Acta de nacimiento" in html and "CURP certificada" in html
    assert "Ilegible." in html
    for fila in _refrescar(db_session, *filas):
        assert (fila.status, fila.subject, fila.sent_to, fila.sent_at) == (
            "sent", asunto, CORREO, despues)

    assert _despachar(db_session, now=despues + timedelta(hours=1)) == CEROS
    assert len(graph.enviados) == 1


def test_un_movimiento_nuevo_reinicia_la_espera(db_session, egresado, graph):
    """Dictaminar → dictaminar otra vez dentro de la espera = un solo correo con
    TODO, cuando el ÚLTIMO movimiento cumple la espera."""
    proc = egresado()
    primeras = _dictamenes(db_session, proc, hace=8)
    db_session.commit()
    assert _despachar(db_session) == _conteo(waiting=1)

    from itcj2.apps.titulatec.services.student_mail import StudentMail
    assert StudentMail.doc_reviewed(db_session, proc, type_code="high_school_cert",
                                    doc_name="Certificado de bachillerato",
                                    status="approved", note=None) is True
    nueva = _filas(db_session, proc.id)[-1]
    _vencer(db_session, [nueva], hace=-1)              # llegó 1 min DESPUÉS de AHORA
    db_session.commit()

    # A AHORA+10 las primeras ya llevan 18 min, pero la nueva apenas 9: el grupo espera.
    assert _despachar(db_session, now=AHORA + timedelta(minutes=10)) == _conteo(waiting=1)
    assert graph.enviados == []

    # A AHORA+11 la nueva cumple sus 10 min: sale TODO en un correo.
    assert _despachar(db_session, now=AHORA + timedelta(minutes=11)) == _conteo(sent=1)
    (_asunto, _dest, html), = graph.enviados
    assert "Certificado de bachillerato" in html and "Acta de nacimiento" in html
    assert {f.status for f in _refrescar(db_session, *primeras, nueva)} == {"sent"}


def test_el_grupo_sale_completo_aunque_el_limite_lo_corte(db_session, egresado, graph):
    """`limit` acota las CANDIDATAS; el grupo se carga entero (todas sus
    `pending`), así que sale en UN correo y ninguna fila se queda atrás."""
    proc = egresado()
    filas = _dictamenes(db_session, proc, hace=30, cuantos=3)
    db_session.commit()

    assert _despachar(db_session, limit=1) == _conteo(sent=1)

    (_asunto, _dest, html), = graph.enviados
    for _code, name, _status, _note in _DOCS:
        assert name in html
    assert {f.status for f in _refrescar(db_session, *filas)} == {"sent"}


# ---------------------------------------------------------------------------
# Ya no aplica / sin destinatario
# ---------------------------------------------------------------------------
def test_revocado_obsoleto(db_session, egresado, graph):
    """C3.3: lo pendiente de un proceso revocado no sale (ya salió
    `send_process_cancelled`); grupo y suelta por igual."""
    proc = egresado(status="cancelled")
    _dictamenes(db_session, proc, hace=30)
    _suelta(db_session, proc)
    db_session.commit()

    assert _despachar(db_session) == _conteo(obsolete=2)

    assert graph.enviados == []
    filas = _filas(db_session, proc.id)
    assert len(filas) == 3
    for fila in filas:
        assert (fila.status, fila.last_error, fila.subject, fila.attempts) == (
            "obsolete", "inscripción revocada", None, 0)


def test_sin_correo_personal(db_session, egresado, graph):
    """D2: sin perfil ni solicitud, `no_recipient`. Nunca el institucional
    (el alumno ficticio sí tiene `core_users.email`)."""
    proc = egresado(correo=None)
    fila = _suelta(db_session, proc)
    db_session.commit()

    assert _despachar(db_session) == _conteo(no_recipient=1)

    assert graph.enviados == []
    _refrescar(db_session, fila)
    assert (fila.status, fila.sent_to, fila.subject, fila.attempts) == (
        "no_recipient", None, None, 0)


def test_compose_obsoleto(db_session, egresado, graph, monkeypatch):
    """`Obsolete.reason` va tal cual a `last_error` (contrato de la Tarea 6)."""
    from itcj2.apps.titulatec.services.mail_compose import MailComposer, Obsolete

    monkeypatch.setattr(MailComposer, "compose",
                        staticmethod(lambda db, rows, process, user:
                                     Obsolete("ya no aplicaba: motivo de prueba")))
    fila = _suelta(db_session, egresado())
    db_session.commit()

    assert _despachar(db_session) == _conteo(obsolete=1)

    assert graph.enviados == []
    _refrescar(db_session, fila)
    assert (fila.status, fila.last_error, fila.subject) == (
        "obsolete", "ya no aplicaba: motivo de prueba", None)


def test_fila_sin_proceso_queda_obsoleta(db_session, make_student, graph):
    """`process_id` admite NULL en el modelo, aunque `enqueue` siempre lo llena.
    Una fila así no se puede componer ni tiene a quién ir: se cierra con su
    motivo en vez de ocupar un lugar del lote cada minuto."""
    from itcj2.apps.titulatec.models import EmailOutbox

    fila = EmailOutbox(kind="phase_rejected", process_id=None,
                       user_id=make_student().id, payload={"reason": None},
                       created_at=AHORA - timedelta(minutes=1),
                       not_before=AHORA - timedelta(minutes=1))
    db_session.add(fila)
    db_session.commit()

    assert _despachar(db_session) == _conteo(obsolete=1)

    assert graph.enviados == []
    _refrescar(db_session, fila)
    assert (fila.status, fila.last_error) == ("obsolete", "el proceso o su alumno ya no existe")


def test_no_se_presento_deshecho_no_sale(db_session, egresado, make_appointment, graph):
    """D8 con el compositor REAL: si el encargado deshizo el «no se presentó»
    dentro de la gracia, la re-validación al enviar lo da por obsoleto."""
    from itcj2.apps.titulatec.services.student_mail import StudentMail

    proc = egresado()
    cita = make_appointment(proc, status="no_show")
    assert StudentMail.appointment_no_show(db_session, proc, appt=cita) is True
    fila = _filas(db_session, proc.id)[-1]
    _vencer(db_session, [fila], hace=1)
    cita.status = "scheduled"                       # «deshacer no se presentó»
    db_session.commit()

    assert _despachar(db_session) == _conteo(obsolete=1)

    assert graph.enviados == []
    _refrescar(db_session, fila)
    assert fila.status == "obsolete" and fila.last_error


# ---------------------------------------------------------------------------
# Reintentos
# ---------------------------------------------------------------------------
def test_backoff_minutes():
    from itcj2.apps.titulatec.services.mail_dispatch import MailDispatcher

    assert [MailDispatcher.backoff_minutes(n) for n in range(1, 9)] == [
        1, 2, 4, 8, 16, 32, 60, 60]
    assert MailDispatcher.backoff_minutes(0) == 1


def test_sin_cuenta_reintenta_con_espera(db_session, egresado, graph):
    graph.token = None
    fila = _suelta(db_session, egresado())
    db_session.commit()

    assert _despachar(db_session) == _conteo(retry=1)

    assert graph.enviados == []
    _refrescar(db_session, fila)
    assert (fila.status, fila.attempts, fila.not_before, fila.last_error) == (
        "pending", 1, AHORA + timedelta(minutes=1), "Cuenta de correo no conectada")
    assert (fila.subject, fila.sent_to, fila.sent_at) == (None, None, None)

    # Antes de su espera no se vuelve a intentar; a su hora sí, con la siguiente espera.
    assert _despachar(db_session, now=AHORA + timedelta(seconds=30)) == CEROS
    assert _despachar(db_session, now=AHORA + timedelta(minutes=1)) == _conteo(retry=1)
    _refrescar(db_session, fila)
    assert (fila.attempts, fila.not_before) == (2, AHORA + timedelta(minutes=3))


def test_agota_intentos_y_falla(db_session, egresado, graph, monkeypatch):
    from itcj2.apps.titulatec.services.student_mail import MailSettings

    monkeypatch.setattr(MailSettings, "max_attempts", staticmethod(lambda: 3))
    graph.token = None
    fila = _suelta(db_session, egresado())
    db_session.commit()

    cuando = AHORA
    for intento in (1, 2):
        assert _despachar(db_session, now=cuando) == _conteo(retry=1)
        _refrescar(db_session, fila)
        assert (fila.status, fila.attempts) == ("pending", intento)
        cuando = fila.not_before

    assert _despachar(db_session, now=cuando) == _conteo(failed=1)

    _refrescar(db_session, fila)
    assert (fila.status, fila.attempts, fila.last_error) == (
        "failed", 3, "Cuenta de correo no conectada")
    assert _despachar(db_session, now=cuando + timedelta(days=1)) == CEROS
    assert graph.enviados == []


def test_graph_5xx_reintenta(db_session, egresado, graph, monkeypatch, caplog):
    from itcj2.apps.titulatec.services import email_helper

    monkeypatch.setattr(email_helper, "_is_production", lambda: False)
    graph.status = 503
    fila = _suelta(db_session, egresado())
    db_session.commit()

    with caplog.at_level(logging.DEBUG, logger="itcj2"):
        assert _despachar(db_session) == _conteo(retry=1)

    assert len(graph.enviados) == 1, "sí se intentó"
    _refrescar(db_session, fila)
    assert (fila.status, fila.attempts, fila.not_before, fila.last_error) == (
        "pending", 1, AHORA + timedelta(minutes=1), "Error al enviar")
    assert (fila.subject, fila.sent_to) == (None, None)
    assert "[TT-MAIL]" not in caplog.text, "E9 es solo para la cuenta no conectada"


def test_plantilla_rota_reintenta(db_session, egresado, graph, monkeypatch):
    from itcj2.apps.titulatec.services import email_helper

    monkeypatch.setattr(email_helper, "_render", lambda name, ctx: None)
    fila = _suelta(db_session, egresado())
    db_session.commit()

    assert _despachar(db_session) == _conteo(retry=1)

    assert graph.enviados == []
    _refrescar(db_session, fila)
    assert (fila.status, fila.attempts, fila.last_error) == (
        "pending", 1, "Error en la plantilla")


def test_excepcion_en_compose_cuenta_como_intento(db_session, egresado, graph,
                                                  monkeypatch):
    """Ruling 2026-09-29: rollback de la unidad y, en otra transacción,
    intento fallido de sus filas; el lote sigue. Al tope, `failed`."""
    from itcj2.apps.titulatec.services.mail_compose import MailComposer
    from itcj2.apps.titulatec.services.student_mail import MailSettings

    mala = _suelta(db_session, egresado(correo="mala@example.invalid"))
    buena = _suelta(db_session, egresado(correo="buena@example.invalid"))
    db_session.commit()
    real = MailComposer.compose

    def _compose(db, rows, process, user):
        if rows[0].id == mala.id:
            raise RuntimeError("se rompió al componer")
        return real(db, rows, process, user)

    monkeypatch.setattr(MailComposer, "compose", staticmethod(_compose))

    assert _despachar(db_session) == _conteo(retry=1, sent=1)

    (_asunto, destinatarios, _html), = graph.enviados
    assert destinatarios == ["buena@example.invalid"]
    _refrescar(db_session, mala, buena)
    assert (mala.status, mala.attempts, mala.not_before, mala.last_error) == (
        "pending", 1, AHORA + timedelta(minutes=1), "Error interno al preparar el correo")
    assert buena.status == "sent"

    monkeypatch.setattr(MailSettings, "max_attempts", staticmethod(lambda: 2))
    assert _despachar(db_session, now=AHORA + timedelta(minutes=1)) == _conteo(failed=1)
    _refrescar(db_session, mala)
    assert (mala.status, mala.attempts, mala.last_error) == (
        "failed", 2, "Error interno al preparar el correo")


def test_limite_suave_de_celery_corta_sin_contar_intento(db_session, egresado, graph,
                                                         monkeypatch):
    """Que celery corte la tarea no es un fallo del correo: se propaga, sin
    intento contado, y la fila sale en la siguiente corrida."""
    from celery.exceptions import SoftTimeLimitExceeded

    from itcj2.apps.titulatec.services.mail_compose import MailComposer

    def _cortada(db, rows, process, user):
        raise SoftTimeLimitExceeded()

    monkeypatch.setattr(MailComposer, "compose", staticmethod(_cortada))
    fila = _suelta(db_session, egresado())
    db_session.commit()

    with pytest.raises(SoftTimeLimitExceeded):
        _despachar(db_session)

    _refrescar(db_session, fila)
    assert (fila.status, fila.attempts, fila.last_error) == ("pending", 0, None)
    assert graph.enviados == []


def test_presupuesto_de_tiempo_deja_el_resto_para_la_siguiente_corrida(
    db_session, egresado, graph, monkeypatch,
):
    """Un Graph lento no lleva la corrida hasta el corte de celery: pasado el
    presupuesto no se toman más unidades, y lo que quedó sale después."""
    from itcj2.apps.titulatec.services import mail_dispatch

    reloj = {"t": 0.0}
    monkeypatch.setattr(mail_dispatch, "_reloj", lambda: reloj["t"])

    def _lento():
        reloj["t"] += mail_dispatch._PRESUPUESTO_S + 1

    graph.al_enviar = _lento
    proc = egresado()
    filas = [_suelta(db_session, proc, motivo=f"motivo {n}") for n in range(3)]
    db_session.commit()

    assert _despachar(db_session) == _conteo(sent=1)

    assert [f.status for f in _refrescar(db_session, *filas)] == ["sent", "pending", "pending"]
    assert [f.attempts for f in filas] == [0, 0, 0]


# ---------------------------------------------------------------------------
# Concurrencia (Review Focus 1)
# ---------------------------------------------------------------------------
def test_segunda_corrida_no_reenvia(db_session, egresado, graph):
    proc = egresado()
    _suelta(db_session, proc)
    _dictamenes(db_session, proc, hace=30)
    db_session.commit()

    assert _despachar(db_session) == _conteo(sent=2)
    assert _despachar(db_session) == CEROS
    assert _despachar(db_session, now=AHORA + timedelta(days=1)) == CEROS
    assert len(graph.enviados) == 2


def test_la_fila_que_otra_corrida_ya_mando_no_sale_otra_vez(db_session, egresado, graph):
    """El commit de cada unidad suelta TODOS los candados, también los de la
    selección: otra corrida puede tomar y mandar una fila que esta ya tenía
    en su lista. Cada unidad vuelve a tomar sus filas en la BD, y la que ya no
    está `pending` no sale."""
    from sqlalchemy import text

    proc = egresado()
    primera = _suelta(db_session, proc, motivo="primera")
    segunda = _suelta(db_session, proc, motivo="segunda")
    db_session.commit()

    def _otra_corrida():
        # Otro worker manda la segunda por su cuenta (SQL directo: la copia en
        # memoria de esta corrida sigue diciendo `pending`).
        db_session.connection().execute(
            text("UPDATE titulatec_email_outbox SET status = 'sent', "
                 "sent_to = 'otra.corrida@example.invalid' WHERE id = :id"),
            {"id": segunda.id})
        graph.al_enviar = None

    graph.al_enviar = _otra_corrida

    assert _despachar(db_session) == _conteo(sent=1)

    (_asunto, _dest, html), = graph.enviados
    assert "primera" in html
    _refrescar(db_session, primera, segunda)
    assert primera.status == "sent"
    assert (segunda.status, segunda.sent_to) == ("sent", "otra.corrida@example.invalid")


def test_la_fila_que_otra_corrida_reprogramo_espera_su_turno(db_session, egresado, graph):
    """Otra corrida la intentó entretanto y le dio su espera: sigue `pending`,
    pero ya no está vencida. Se lee fresca de la BD (no de la copia en memoria)
    y no se intenta antes de tiempo."""
    from sqlalchemy import text

    proc = egresado()
    primera = _suelta(db_session, proc, motivo="primera")
    segunda = _suelta(db_session, proc, motivo="segunda")
    db_session.commit()

    def _otra_corrida():
        db_session.connection().execute(
            text("UPDATE titulatec_email_outbox SET attempts = 1, not_before = :nb, "
                 "last_error = 'Cuenta de correo no conectada' WHERE id = :id"),
            {"id": segunda.id, "nb": AHORA + timedelta(minutes=1)})
        graph.al_enviar = None

    graph.al_enviar = _otra_corrida

    assert _despachar(db_session) == _conteo(sent=1)

    assert len(graph.enviados) == 1
    _refrescar(db_session, primera, segunda)
    assert primera.status == "sent"
    assert (segunda.status, segunda.attempts, segunda.not_before) == (
        "pending", 1, AHORA + timedelta(minutes=1))


def test_grupo_con_una_fila_tomada_por_otra_corrida_se_deja_entero(
    db_session, egresado, graph, monkeypatch,
):
    """Si otra corrida tiene tomada UNA fila del grupo, `SKIP LOCKED` la salta:
    mandar lo demás sería un correo con medio grupo (y la otra corrida mandaría
    el resto). Se deja entero para después. El arnés es UNA conexión, así que
    el candado ajeno se simula ocultando esa fila de toda lectura con candado,
    que es lo que haría `SKIP LOCKED`."""
    from sqlalchemy.orm import Query

    from itcj2.apps.titulatec.models import EmailOutbox

    proc = egresado()
    filas = _dictamenes(db_session, proc, hace=30, cuantos=3)
    db_session.commit()
    tomada = filas[1]
    original = Query.with_for_update

    def _con_candado_ajeno(self, *args, **kwargs):
        # La selección ya trae `LIMIT`: sin las aserciones de `Query`, el filtro
        # queda en el WHERE y se aplica ANTES del LIMIT, igual que el salto de
        # `SKIP LOCKED`.
        oculta = self.enable_assertions(False).filter(EmailOutbox.id != tomada.id)
        return original(oculta, *args, **kwargs)

    monkeypatch.setattr(Query, "with_for_update", _con_candado_ajeno)
    assert _despachar(db_session) == CEROS
    assert graph.enviados == []
    assert {(f.status, f.attempts) for f in _refrescar(db_session, *filas)} == {("pending", 0)}

    monkeypatch.setattr(Query, "with_for_update", original)     # la otra corrida soltó
    assert _despachar(db_session) == _conteo(sent=1)
    (_asunto, _dest, html), = graph.enviados
    for _code, name, _status, _note in _DOCS:
        assert name in html


def test_la_consulta_usa_skip_locked(db_session, egresado, graph):
    """Estructural: toda lectura con candado del outbox es `FOR UPDATE SKIP
    LOCKED` (la de candidatas y la de cada unidad). Un `FOR UPDATE` a secas
    esperaría a la otra corrida (y con grupos, podría trabarse con ella)."""
    from sqlalchemy import event

    proc = egresado()
    _suelta(db_session, proc)
    _dictamenes(db_session, proc, hace=30)
    db_session.commit()

    sentencias = []

    def _captura(conn, cursor, statement, parameters, context, executemany):
        sentencias.append(" ".join(statement.split()))

    engine = db_session.get_bind().engine
    event.listen(engine, "before_cursor_execute", _captura)
    try:
        assert _despachar(db_session) == _conteo(sent=2)
    finally:
        event.remove(engine, "before_cursor_execute", _captura)

    con_candado = [s for s in sentencias
                   if "FROM titulatec_email_outbox" in s and "FOR UPDATE" in s]
    candidatas = [s for s in con_candado if "not_before <=" in s]
    assert len(candidatas) == 1, sentencias
    assert "ORDER BY titulatec_email_outbox.id" in candidatas[0]
    assert "LIMIT" in candidatas[0]
    assert len(con_candado) >= 3, "la selección y cada unidad toman sus filas"
    assert all(s.endswith("FOR UPDATE SKIP LOCKED") for s in con_candado), con_candado


def test_respeta_el_limite(db_session, egresado, graph):
    proc = egresado()
    filas = [_suelta(db_session, proc, motivo=f"motivo {n}") for n in range(3)]
    db_session.commit()

    assert _despachar(db_session, limit=2) == _conteo(sent=2)
    assert len(graph.enviados) == 2
    assert [f.status for f in _refrescar(db_session, *filas)] == ["sent", "sent", "pending"]

    assert _despachar(db_session, limit=2) == _conteo(sent=1)
    assert len(graph.enviados) == 3


# ---------------------------------------------------------------------------
# Apagado y E9
# ---------------------------------------------------------------------------
class _SinBD:
    def __getattr__(self, nombre):
        raise AssertionError(f"con el correo apagado no se toca la BD (db.{nombre})")


def test_apagado_no_toca_nada(db_session, egresado, graph, monkeypatch):
    """§9.5: apagado de emergencia. Lo ya encolado (antes de apagar) se queda
    `pending`, intacto, y sale al volver a encender."""
    from itcj2.apps.titulatec.services.mail_dispatch import MailDispatcher
    from itcj2.apps.titulatec.services.student_mail import MailSettings

    fila = _suelta(db_session, egresado())      # encolado con el correo encendido
    db_session.commit()
    monkeypatch.setattr(MailSettings, "enabled", staticmethod(lambda: False))

    assert MailDispatcher.run(_SinBD(), now=AHORA) == {"disabled": True}
    assert _despachar(db_session) == {"disabled": True}
    _refrescar(db_session, fila)
    assert (fila.status, fila.attempts) == ("pending", 0)
    assert graph.enviados == []


@pytest.mark.parametrize("produccion", [False, True], ids=["dev", "produccion"])
def test_log_tt_mail_solo_fuera_de_produccion(db_session, egresado, graph, monkeypatch,
                                              caplog, produccion):
    from itcj2.apps.titulatec.services import email_helper
    from itcj2.apps.titulatec.services.student_mail import StudentMail

    monkeypatch.setattr(email_helper, "_is_production", lambda: produccion)
    graph.token = None
    _suelta(db_session, egresado())
    db_session.commit()
    liga = StudentMail.link("/titulatec/student/dashboard?fase=1")

    with caplog.at_level(logging.DEBUG, logger="itcj2"):
        assert _despachar(db_session) == _conteo(retry=1)

    lineas = [r.getMessage() for r in caplog.records if "[TT-MAIL]" in r.getMessage()]
    if produccion:
        assert lineas == []
        assert liga not in caplog.text
        assert CORREO not in caplog.text
    else:
        assert lineas == [f"[TT-MAIL] phase_rejected -> {CORREO} · {ASUNTO_FASE} · {liga}"]


# ---------------------------------------------------------------------------
# email_helper: `_deliver` intacto y `deliver_detailed`
# ---------------------------------------------------------------------------
def _envio(**cambios):
    from itcj2.apps.titulatec.services.email_helper import PUBLIC_ORIGIN

    kw = dict(template="phase_rejected.html",
              context={"first_name": "ANA", "link": f"{PUBLIC_ORIGIN}/itcj/login",
                       "phase_name": "Fase 01 · Documentos iniciales", "reason": None},
              subject=PREFIJO + "Prueba", to="a@example.invalid", que="prueba",
              link=f"{PUBLIC_ORIGIN}/titulatec/inscripcion/verificar?t=prueba")
    kw.update(cambios)
    return kw


def test_deliver_publico_sin_cambios(graph, monkeypatch, caplog):
    """Los 6 correos de inscripción pasan por `_deliver`: misma firma, `bool`,
    y E9 (`[TT-VERIFY-LINK]`) igual que antes."""
    from itcj2.apps.titulatec.services import email_helper

    firma = inspect.signature(email_helper._deliver)
    assert list(firma.parameters) == ["template", "context", "subject", "to", "que", "link"]
    assert all(p.kind is inspect.Parameter.KEYWORD_ONLY for p in firma.parameters.values())
    assert firma.parameters["link"].default is None
    monkeypatch.setattr(email_helper, "_is_production", lambda: False)
    kw = _envio()

    with caplog.at_level(logging.DEBUG, logger="itcj2"):
        assert email_helper._deliver(**kw) is True
    assert "[titulatec] prueba -> a@example.invalid" in caplog.text
    (asunto, destinatarios, _html), = graph.enviados
    assert (asunto, destinatarios) == (kw["subject"], ["a@example.invalid"])

    graph.token = None
    caplog.clear()
    with caplog.at_level(logging.DEBUG, logger="itcj2"):
        assert email_helper._deliver(**kw) is False
    assert f"[TT-VERIFY-LINK] a@example.invalid -> {kw['link']}" in caplog.text

    assert email_helper._deliver(**_envio(to=None)) is False
    monkeypatch.setattr(email_helper, "_is_production", lambda: True)
    caplog.clear()
    with caplog.at_level(logging.DEBUG, logger="itcj2"):
        assert email_helper._deliver(**kw) is False
    assert "[TT-VERIFY-LINK]" not in caplog.text
    assert len(graph.enviados) == 1


def test_deliver_detailed_da_el_motivo(graph, monkeypatch):
    from itcj2.apps.titulatec.services import email_helper

    monkeypatch.setattr(email_helper, "_is_production", lambda: True)

    assert email_helper.deliver_detailed(**_envio()) == (True, None)
    assert email_helper.deliver_detailed(**_envio(to="")) == (False, "sin_destinatario")
    graph.status = 503
    assert email_helper.deliver_detailed(**_envio()) == (False, "envio")
    graph.token = None
    assert email_helper.deliver_detailed(**_envio()) == (False, "cuenta_no_conectada")
    graph.token = "token-de-prueba"
    monkeypatch.setattr(email_helper, "_render", lambda name, ctx: None)
    assert email_helper.deliver_detailed(**_envio()) == (False, "plantilla")
    assert len(graph.enviados) == 2, "solo el primero y el del 503 llegaron a Graph"
