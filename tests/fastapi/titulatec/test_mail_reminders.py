"""`MailReminders`: barrido diario de recordatorios por correo (spec 2026-09-28
§5 #8/#10/#11 y §6 C4; Tarea 8).

Lo que se fija aquí:

1. Cita (#8): la VIGENTE `scheduled`/`confirmed` cuya FECHA es la de mañana —el
   borde de medianoche es el Review Focus 3—, una vez por cita; se omite la que
   se agendó o se cambió hace menos de 24 h (acaba de recibir su correo #7) y
   `appt_days_before() == 0` la apaga.
2. Documentos (#10) y encuesta (#11): la cadencia de `due_index` (a los 3 días
   del ancla, luego cada 7, máximo 3), contando lo ya encolado para ESA ancla;
   una subida o un rechazo nuevos mueven el ancla y la cuenta vuelve a empezar.
   Pago pendiente en Caja (spec 2026-10-01-titulatec-biblioteca-caja-design.md
   §4.11, D14): la misma cadencia con ancla `ready_at` -la entrada VIGENTE a
   Caja, Ruling R10-, en cualquier fase; deja de salir al liberarse.
3. Idempotencia: correr el barrido dos veces no duplica filas ni avisos in-app
   (el in-app solo nace si el correo se encoló de verdad).
4. Solo procesos `active`; con el correo apagado no toca la BD; consultas por
   lote (sin N+1 por proceso); correo e in-app de un candidato quedan juntos o
   no queda ninguno, y el que falla no detiene a los demás.

AISLAMIENTO. El barrido recorre TODOS los procesos activos de la base, y la de
dev trae procesos reales. Por eso el reloj va fijo en el pasado (`AHORA`, 2001,
el mismo recurso que `test_mail_dispatch.py`): ninguna ancla ni cita real vence
a esa hora, así que los conteos de `run` son solo los de la prueba. Cada fila de
prueba lleva sus fechas explícitas respecto de su reloj. La excepción es el
borde de medianoche, con el reloj que pide el Review Focus 3 (2026-10-01): ahí
se afirma por proceso, nunca por conteo.
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

import itcj2.models  # noqa: F401

AHORA = datetime(2001, 2, 3, 9, 0)             # el barrido corre a las 9:00
MANANA_10 = datetime(2001, 2, 4, 10, 0)
CEROS = {"appt": 0, "docs": 0, "survey": 0, "library": 0}
LOGGER = "itcj2.apps.titulatec.services.mail_reminders"


def _conteo(**kw):
    return {**CEROS, **kw}


# ---------------------------------------------------------------------------
# Andamiaje local
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _correo_encendido(monkeypatch):
    """Correo encendido sin depender del `.env` del contenedor, y la cadencia
    moderada del spec (C6, D6) parcheada en `MailSettings`, nunca en
    `get_settings`: 3 días, luego cada 7, máximo 3; la cita, un día antes."""
    from itcj2.apps.titulatec.services.student_mail import MailSettings
    from itcj2.config import get_settings

    monkeypatch.setattr(get_settings(), "TITULATEC_EMAIL_ENABLED", True)
    for nombre, valor in (("first_days", 3), ("every_days", 7), ("max_reminders", 3),
                          ("appt_days_before", 1)):
        monkeypatch.setattr(MailSettings, nombre, staticmethod(lambda v=valor: v))


@pytest.fixture(autouse=True)
def _graph_prohibido(monkeypatch):
    """El barrido solo ENCOLA (manda el despachador): pedir el token de Graph o
    enviar revienta la prueba."""
    def _prohibido(*_a, **_k):
        raise AssertionError("el barrido no envía correo: eso es del despachador")

    monkeypatch.setattr("itcj2.core.utils.msgraph_mail.acquire_token_silent", _prohibido)
    monkeypatch.setattr("itcj2.core.utils.msgraph_mail.graph_send_mail", _prohibido)


@pytest.fixture()
def catalogos(seed_phase_defs, seed_document_types):
    """Fases y tipos de documento: la CI corre con `create_all` y sin DML."""
    seed_phase_defs()
    seed_document_types()


def _fase(db, proc, numero):
    from itcj2.apps.titulatec.models import ProcessPhase

    return db.query(ProcessPhase).filter_by(process_id=proc.id, phase_number=numero).one()


@pytest.fixture()
def con_cita(catalogos, db_session, make_student, make_process, make_appointment):
    """Proceso en la fase 2 con su cita VIGENTE en `cuando`, agendada `hace`
    antes de `now` (por omisión hace 3 días: fuera de las 24 h). Su fase 2 no
    tiene `started_at`, así que no entra al recordatorio de la encuesta."""
    def _make(cuando=MANANA_10, *, now=AHORA, hace=timedelta(days=3),
              status="scheduled", proceso="active", location="Ventanilla 3"):
        proc = make_process(make_student(), current_phase=2, status=proceso)
        appt = make_appointment(proc, when=cuando, status=status, location=location)
        appt.created_at = now - hace
        db_session.flush()
        return proc, appt

    return _make


@pytest.fixture()
def en_documentos(catalogos, db_session, make_student, make_process):
    """Proceso en la fase 1 sin ningún documento, con la fase iniciada en
    `inicio` (por omisión hace 4 días: vence el primer recordatorio y el
    segundo todavía no)."""
    def _make(inicio=AHORA - timedelta(days=4), *, proceso="active"):
        proc = make_process(make_student(), current_phase=1, status=proceso)
        _fase(db_session, proc, 1).started_at = inicio
        db_session.flush()
        return proc

    return _make


@pytest.fixture()
def en_cotejo(catalogos, db_session, make_student, make_process):
    """Proceso en la fase 2 SIN encuesta enviada, con la fase iniciada en
    `inicio` (por omisión hace 4 días)."""
    def _make(inicio=AHORA - timedelta(days=4), *, proceso="active"):
        proc = make_process(make_student(), current_phase=2, status=proceso)
        _fase(db_session, proc, 2).started_at = inicio
        db_session.flush()
        return proc

    return _make


@pytest.fixture()
def en_caja(catalogos, db_session, make_student, make_process, make_library_clearance):
    """Proceso con su no adeudo `awaiting_payment` (adeudo $300 + donación $800
    = $1,100) que ENTRÓ a Caja en `entrada` (por omisión hace 4 días: vence el
    primer recordatorio y el segundo todavía no). En la fase 2 sin
    `started_at` (no entra al de la encuesta); `fase=1` lo deja en documentos
    con el alta de hoy como ancla, que a la hora de `AHORA` no vence."""
    def _make(entrada=AHORA - timedelta(days=4), *, proceso="active", fase=2):
        proc = make_process(make_student(), current_phase=fase, status=proceso,
                            library_clearance=None)
        make_library_clearance(proc, status="awaiting_payment",
                               debt_amount=Decimal("300.00"),
                               donation_amount=Decimal("800.00"),
                               total_amount=Decimal("1100.00"), ready_at=entrada)
        return proc

    return _make


def _filas(db, pid, kind=None):
    """Filas del outbox del proceso en orden de llegada. El flush es EXPLÍCITO:
    en producción `autoflush=False`."""
    from itcj2.apps.titulatec.models import EmailOutbox

    db.flush()
    q = db.query(EmailOutbox).filter_by(process_id=pid)
    if kind is not None:
        q = q.filter_by(kind=kind)
    return q.order_by(EmailOutbox.id).all()


def _avisos(db, user_id, tipo=None):
    """Avisos in-app de titulatec del usuario."""
    from itcj2.core.models.notification import Notification

    db.flush()
    q = db.query(Notification).filter_by(user_id=user_id, app_name="titulatec")
    if tipo is not None:
        q = q.filter_by(type=tipo)
    return q.order_by(Notification.id).all()


def _barrer(db, now=AHORA):
    from itcj2.apps.titulatec.services.mail_reminders import MailReminders

    return MailReminders.run(db, now=now)


@contextmanager
def _lecturas(db):
    """Los SELECT que llegan a Postgres mientras dura el bloque."""
    from sqlalchemy import event

    conn = db.connection()
    vistas: list[str] = []

    def _antes(_conn, _cursor, sql, *_resto):
        if sql.lstrip().upper().startswith("SELECT"):
            vistas.append(sql)

    event.listen(conn, "before_cursor_execute", _antes)
    try:
        yield vistas
    finally:
        event.remove(conn, "before_cursor_execute", _antes)


# ---------------------------------------------------------------------------
# #8 — recordatorio de la cita
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("estado", ["scheduled", "confirmed"])
def test_cita_de_manana_encola_una_vez_y_notifica(db_session, con_cita, estado):
    proc, appt = con_cita(status=estado)

    assert _barrer(db_session) == _conteo(appt=1)

    (fila,) = _filas(db_session, proc.id)
    assert (fila.kind, fila.status, fila.user_id) == ("appt_reminder", "pending",
                                                      proc.student_id)
    assert fila.dedupe_key == f"appt_reminder:{appt.id}"
    assert fila.payload == {"appt_id": appt.id, "scheduled_at": "2001-02-04T10:00:00",
                            "location": "Ventanilla 3"}
    (aviso,) = _avisos(db_session, proc.student_id)
    assert (aviso.type, aviso.title) == ("APPOINTMENT_REMINDER", "Mañana es tu cita de cotejo")
    assert aviso.body == "04 feb 2001 · 10:00 · Ventanilla 3"          # fecha · lugar
    assert aviso.data == {"url": "/titulatec/student/fase/2", "process_id": proc.id,
                          "phase_number": 2}


def test_correr_dos_veces_no_duplica(db_session, con_cita, en_documentos, en_cotejo,
                                    en_caja):
    """Los cuatro recordatorios a la vez: la segunda corrida (mismo reloj) no
    encola nada ni vuelve a avisar en la app."""
    cita, _ = con_cita()
    docs = en_documentos()
    encuesta = en_cotejo()
    pago = en_caja()

    assert _barrer(db_session) == _conteo(appt=1, docs=1, survey=1, library=1)
    assert _barrer(db_session) == CEROS

    for proc, kind, tipo in ((cita, "appt_reminder", "APPOINTMENT_REMINDER"),
                             (docs, "docs_reminder", "DOCUMENTS_REMINDER"),
                             (encuesta, "survey_reminder", "SURVEY_REMINDER"),
                             (pago, "library_reminder", "LIBRARY_REMINDER")):
        assert [f.kind for f in _filas(db_session, proc.id)] == [kind]
        assert [a.type for a in _avisos(db_session, proc.student_id)] == [tipo]


@pytest.mark.parametrize("hace, recuerda", [
    (timedelta(hours=23, minutes=59), False),
    (timedelta(hours=24), True),
], ids=["hace-23h59", "hace-24h"])
def test_cita_recien_agendada_no_recibe_recordatorio(db_session, con_cita, hace, recuerda):
    """Se agendó (o se movió: `reschedule` inserta una fila NUEVA, con su propio
    `created_at`) hace menos de 24 h: acaba de recibir el correo #7 con los
    mismos datos."""
    proc, _ = con_cita(hace=hace)

    assert _barrer(db_session) == _conteo(appt=int(recuerda))
    assert len(_filas(db_session, proc.id)) == int(recuerda)
    assert len(_avisos(db_session, proc.student_id)) == int(recuerda)


def test_cita_de_pasado_manana_no(db_session, con_cita):
    manana, _ = con_cita(MANANA_10)
    pasado_manana, _ = con_cita(MANANA_10 + timedelta(days=1))
    hoy_mas_tarde, _ = con_cita(AHORA + timedelta(hours=5))

    assert _barrer(db_session) == _conteo(appt=1)
    assert len(_filas(db_session, manana.id)) == 1
    assert _filas(db_session, pasado_manana.id) == []
    assert _filas(db_session, hoy_mas_tarde.id) == []


@pytest.mark.parametrize("estado", ["in_progress", "attended", "no_show"])
def test_cita_vigente_que_ya_no_esta_activa_no(db_session, con_cita, estado):
    proc, _ = con_cita(status=estado)

    assert _barrer(db_session) == CEROS
    assert _filas(db_session, proc.id) == []


def test_cita_que_ya_no_es_la_vigente_no(db_session, catalogos, make_student, make_process,
                                        make_appointment):
    """Un intento viejo (cancelado o reemplazado) de mañana no recuerda nada."""
    proc = make_process(make_student(), current_phase=2)
    for estado in ("cancelled", "superseded"):
        vieja = make_appointment(proc, when=MANANA_10, status=estado, is_current=False)
        vieja.created_at = AHORA - timedelta(days=3)
    db_session.flush()

    assert _barrer(db_session) == CEROS


def test_dias_antes_cero_apaga(db_session, con_cita, monkeypatch):
    from itcj2.apps.titulatec.services.student_mail import MailSettings

    monkeypatch.setattr(MailSettings, "appt_days_before", staticmethod(lambda: 0))
    manana, _ = con_cita(MANANA_10)
    hoy_mas_tarde, _ = con_cita(AHORA + timedelta(hours=5))

    assert _barrer(db_session) == CEROS
    assert _filas(db_session, manana.id) == [] == _filas(db_session, hoy_mas_tarde.id)


def test_dos_dias_antes_no_dice_manana(db_session, con_cita, monkeypatch):
    """El setting admite hasta 7 días: con 2, el aviso no puede decir «mañana»."""
    from itcj2.apps.titulatec.services.student_mail import MailSettings

    monkeypatch.setattr(MailSettings, "appt_days_before", staticmethod(lambda: 2))
    en_dos_dias, _ = con_cita(MANANA_10 + timedelta(days=1))
    manana, _ = con_cita(MANANA_10)

    assert _barrer(db_session) == _conteo(appt=1)
    assert _filas(db_session, manana.id) == []
    (aviso,) = _avisos(db_session, en_dos_dias.student_id)
    assert aviso.title == "Tu cita de cotejo es en 2 días"


def test_borde_de_medianoche(db_session, con_cita, monkeypatch):
    """Review Focus 3: «mañana» es la FECHA siguiente en `APP_TZ`, no «dentro de
    24 horas». A las 9:00 del 1 de octubre, la cita del 2 a las 00:30 (15 h y
    media después) sí recibe recordatorio; la del 1 a las 23:30 (14 h y media
    después, pero HOY) no.

    Por proceso y no por conteo: con este reloj pueden vencer citas reales de la
    base de dev. Documentos y encuesta, apagados: aquí solo importa la cita."""
    from itcj2.apps.titulatec.services.student_mail import MailSettings

    monkeypatch.setattr(MailSettings, "max_reminders", staticmethod(lambda: 0))
    now = datetime(2026, 10, 1, 9, 0)
    casos = {
        datetime(2026, 10, 1, 23, 30): False,      # hoy en la noche
        datetime(2026, 10, 2, 0, 0): True,         # primer minuto de mañana
        datetime(2026, 10, 2, 0, 30): True,        # mañana de madrugada
        datetime(2026, 10, 2, 23, 59): True,       # último minuto de mañana
        datetime(2026, 10, 3, 0, 0): False,        # pasado mañana
    }
    procesos = {cuando: con_cita(cuando, now=now)[0] for cuando in casos}

    _barrer(db_session, now=now)

    for cuando, recuerda in casos.items():
        filas = _filas(db_session, procesos[cuando].id, "appt_reminder")
        assert len(filas) == int(recuerda), cuando


# ---------------------------------------------------------------------------
# Cadencia de documentos y encuesta
# ---------------------------------------------------------------------------
_ANCLA = datetime(2001, 1, 1, 15, 30)


@pytest.mark.parametrize("pasado, enviados, esperado", [
    (timedelta(days=2), 0, None),
    (timedelta(days=3) - timedelta(seconds=1), 0, None),
    (timedelta(days=3), 0, 0),
    (timedelta(days=9), 1, None),
    (timedelta(days=10), 1, 1),
    (timedelta(days=17), 2, 2),
    (timedelta(days=24), 3, None),
], ids=["dia-2", "dia-3-menos-1s", "dia-3", "dia-9", "dia-10", "dia-17", "dia-24-tope"])
def test_due_index_cadencia(pasado, enviados, esperado):
    """3 días desde el ancla, luego cada 7, máximo 3: el índice que toca es el
    número de los ya encolados, o `None`."""
    from itcj2.apps.titulatec.services.mail_reminders import MailReminders

    assert MailReminders.due_index(_ANCLA, _ANCLA + pasado, enviados) == esperado


@pytest.mark.parametrize("anterior, ahora, esperado", [
    (datetime(2001, 3, 1, 9, 0), datetime(2001, 3, 1, 9, 0), None),       # mismo día
    (datetime(2001, 3, 1, 9, 0), datetime(2001, 3, 7, 9, 0), None),       # 6 días
    (datetime(2001, 3, 1, 9, 0), datetime(2001, 3, 8, 9, 0), 1),          # 7 días
    (datetime(2001, 3, 1, 9, 0), datetime(2001, 3, 9, 9, 0), 1),          # 8 días
    # El barrido de la semana siguiente arrancó unos segundos MÁS TEMPRANO que
    # el que encoló el anterior (beat no dispara al mismo microsegundo): siguen
    # siendo 7 días de calendario y toca.
    (datetime(2001, 3, 1, 9, 0, 5), datetime(2001, 3, 8, 9, 0, 1), 1),
], ids=["mismo-dia", "6-dias", "7-dias", "8-dias", "7-dias-segundos-antes"])
def test_due_index_espera_every_days_desde_el_recordatorio_anterior(anterior, ahora,
                                                                    esperado):
    """Ruling 19: del segundo en adelante (`sent >= 1`) exige ADEMÁS que desde el
    recordatorio anterior de ESA ancla hayan pasado `every_days()` días. Aquí la
    fórmula del ancla ya venció de sobra (ancla dos meses atrás): lo único que
    decide es la separación con el anterior, contada en días de CALENDARIO."""
    from itcj2.apps.titulatec.services.mail_reminders import MailReminders

    assert MailReminders.due_index(_ANCLA, ahora, 1, anterior) == esperado


def test_ancla_vieja_no_manda_recordatorios_en_dias_seguidos(db_session, en_documentos,
                                                            en_cotejo):
    """Ruling 19: con un ancla de 19 días (el primer barrido de producción, o
    el correo que se vuelve a encender), la fórmula del ancla ya venció para
    los índices 0, 1 y 2. Antes, un barrido diario los mandaba en tres días
    seguidos; ahora sale el 0 el primer día y los siguientes cada 7 días desde
    el anterior. Igual para documentos y para la encuesta."""
    docs = en_documentos(inicio=AHORA - timedelta(days=19))
    encuesta = en_cotejo(inicio=AHORA - timedelta(days=19))

    por_dia = {}
    for dia in (0, 1, 2, 6, 7, 8, 13, 14, 15, 21):
        conteo = _barrer(db_session, now=AHORA + timedelta(days=dia))
        por_dia[dia] = (conteo["docs"], conteo["survey"])

    assert por_dia == {0: (1, 1), 1: (0, 0), 2: (0, 0), 6: (0, 0), 7: (1, 1), 8: (0, 0),
                       13: (0, 0), 14: (1, 1), 15: (0, 0), 21: (0, 0)}
    for proc, kind in ((docs, "docs_reminder"), (encuesta, "survey_reminder")):
        filas = _filas(db_session, proc.id, kind)
        assert [f.payload["index"] for f in filas] == [0, 1, 2]
        # La separación se mide con el `created_at` de cada recordatorio, que es
        # el reloj del barrido que lo encoló (no el `NOW()` real de la BD).
        assert [f.created_at for f in filas] == [
            AHORA, AHORA + timedelta(days=7), AHORA + timedelta(days=14)]


def test_due_index_con_maximo_cero_nunca(monkeypatch):
    """`TITULATEC_REMINDER_MAX = 0` = sin recordatorios de documentos/encuesta."""
    from itcj2.apps.titulatec.services.mail_reminders import MailReminders
    from itcj2.apps.titulatec.services.student_mail import MailSettings

    monkeypatch.setattr(MailSettings, "max_reminders", staticmethod(lambda: 0))

    assert MailReminders.due_index(_ANCLA, _ANCLA + timedelta(days=400), 0) is None


def test_cadencia_de_documentos_en_el_barrido(db_session, en_documentos):
    """La fórmula contra la cuenta REAL de filas encoladas (la llave de
    `StudentMail`): un barrido diario manda el 0 al día 3, el 1 al 10, el 2 al 17
    y ya nada más."""
    proc = en_documentos(inicio=_ANCLA)

    por_dia = {dia: _barrer(db_session, now=_ANCLA + timedelta(days=dia))["docs"]
               for dia in (2, 3, 4, 9, 10, 11, 17, 24, 31)}

    assert por_dia == {2: 0, 3: 1, 4: 0, 9: 0, 10: 1, 11: 0, 17: 1, 24: 0, 31: 0}
    filas = _filas(db_session, proc.id, "docs_reminder")
    assert [f.payload for f in filas] == [
        {"anchor": "2001-01-01T15:30:00", "index": i} for i in range(3)]
    assert [f.dedupe_key for f in filas] == [
        f"docs_reminder:{proc.id}:20010101T153000:{i}" for i in range(3)]
    assert len(_avisos(db_session, proc.student_id, "DOCUMENTS_REMINDER")) == 3


def test_documentos_faltantes_recuerdan_por_nombre(db_session, en_documentos):
    proc = en_documentos()

    assert _barrer(db_session) == _conteo(docs=1)

    (fila,) = _filas(db_session, proc.id)
    assert fila.kind == "docs_reminder"
    assert fila.payload == {"anchor": (AHORA - timedelta(days=4)).isoformat(), "index": 0}
    (aviso,) = _avisos(db_session, proc.student_id)
    assert (aviso.type, aviso.title) == ("DOCUMENTS_REMINDER", "Te faltan documentos por subir")
    assert aviso.body == ("Por subir: Acta de nacimiento, Certificado de bachillerato, "
                          "CURP certificada.")
    assert aviso.data["url"] == "/titulatec/student/fase/1"


def test_documento_por_corregir_si_recuerda(db_session, en_documentos, make_document):
    proc = en_documentos()
    make_document(proc, type_code="birth_certificate")
    make_document(proc, type_code="high_school_cert", review_status="approved")
    make_document(proc, type_code="curp", review_status="rejected", note="Ilegible")

    assert _barrer(db_session) == _conteo(docs=1)

    (aviso,) = _avisos(db_session, proc.student_id, "DOCUMENTS_REMINDER")
    assert aviso.title == "Te faltan documentos por corregir"
    assert aviso.body == "Por corregir: CURP certificada."


def test_documentos_completos_no_recuerda(db_session, en_documentos, make_document):
    """Los 3 enviados y en revisión: no hay nada que pedirle al egresado."""
    proc = en_documentos()
    for code in ("birth_certificate", "high_school_cert", "curp"):
        make_document(proc, type_code=code)

    assert _barrer(db_session) == CEROS
    assert _filas(db_session, proc.id) == []
    assert _avisos(db_session, proc.student_id) == []


@pytest.mark.parametrize("evento", ["document_uploaded", "document_rejected"])
def test_subida_nueva_reinicia_el_ancla(db_session, en_documentos, make_document, evento):
    """Ancla = última actividad. Con el ancla vieja, a los 2 días de la subida ya
    tocaría el recordatorio 1 (inicio + 3 + 7 = AHORA); con la nueva, la cuenta
    empieza de cero y el primero vence a los 3 días de la subida."""
    from itcj2.apps.titulatec.models import ProcessEvent

    inicio = AHORA - timedelta(days=10)
    proc = en_documentos(inicio=inicio)
    assert _barrer(db_session, now=AHORA)["docs"] == 1          # el 0 del ancla vieja

    movida = AHORA + timedelta(days=1)
    make_document(proc, type_code="curp",
                  review_status="rejected" if evento == "document_rejected" else "pending")
    db_session.add(ProcessEvent(process_id=proc.id, event_type=evento, phase_number=1,
                                created_at=movida))
    db_session.flush()

    assert _barrer(db_session, now=AHORA + timedelta(days=2))["docs"] == 0
    assert _barrer(db_session, now=movida + timedelta(days=3))["docs"] == 1

    vieja, nueva = _filas(db_session, proc.id, "docs_reminder")
    assert vieja.payload == {"anchor": inicio.isoformat(), "index": 0}
    assert nueva.payload == {"anchor": movida.isoformat(), "index": 0}


def test_sin_inicio_de_fase_el_ancla_es_el_alta_del_proceso(db_session, en_documentos):
    proc = en_documentos(inicio=None)
    proc.created_at = AHORA - timedelta(days=5)
    db_session.flush()

    assert _barrer(db_session) == _conteo(docs=1)
    (fila,) = _filas(db_session, proc.id)
    assert fila.payload["anchor"] == (AHORA - timedelta(days=5)).isoformat()


def test_encuesta_enviada_no_recuerda(db_session, en_cotejo, make_survey_review):
    """Con la encuesta enviada (cualquier estado de GTV) este recordatorio de
    ENVÍO deja de aplicar: ya no hay qué empujar. M-8 (revisión final): esto
    NO significa que ya pueda agendar -D1 (revierte D2 del 2026-09-15) exige
    además que GTV la LIBERE-, solo que enviarla apaga esta bandeja en
    concreto, que nunca vigiló la liberación. Sin inicio de la fase 2 no hay
    ancla: se omite."""
    enviada = en_cotejo()
    make_survey_review(enviada)
    sin_inicio = en_cotejo(inicio=None)
    pendiente = en_cotejo()

    assert _barrer(db_session) == _conteo(survey=1)

    assert _filas(db_session, enviada.id) == [] == _filas(db_session, sin_inicio.id)
    (fila,) = _filas(db_session, pendiente.id)
    assert fila.kind == "survey_reminder"
    assert fila.dedupe_key.startswith(f"survey_reminder:{pendiente.id}:")
    assert fila.payload == {"anchor": (AHORA - timedelta(days=4)).isoformat(), "index": 0}
    (aviso,) = _avisos(db_session, pendiente.student_id)
    assert (aviso.type, aviso.title) == ("SURVEY_REMINDER", "Llena tu encuesta de egresados")
    assert aviso.body == "Sin ella no puedes agendar tu cita de cotejo."
    assert aviso.data["url"] == "/titulatec/student/fase/2"


# ---------------------------------------------------------------------------
# Pago pendiente en Caja (spec 2026-10-01 §4.11, D14)
# ---------------------------------------------------------------------------
def test_pago_pendiente_recuerda_con_el_total_y_su_aviso(db_session, en_caja):
    proc = en_caja()
    entrada = AHORA - timedelta(days=4)

    assert _barrer(db_session) == _conteo(library=1)

    (fila,) = _filas(db_session, proc.id)
    assert (fila.kind, fila.status, fila.user_id) == ("library_reminder", "pending",
                                                      proc.student_id)
    assert fila.payload == {"anchor": entrada.isoformat(), "index": 0}
    assert fila.dedupe_key == f"library_reminder:{proc.id}:{entrada:%Y%m%dT%H%M%S}:0"
    (aviso,) = _avisos(db_session, proc.student_id)
    assert (aviso.type, aviso.title) == ("LIBRARY_REMINDER",
                                         "Tienes pendiente tu pago de $1,100.00 en Caja")
    assert aviso.body == ("Acude a Caja (Recursos Financieros) con tu número de control; "
                          "no necesitas cita.")
    assert aviso.data["url"] == "/titulatec/student/fase/2"


def test_cadencia_del_pago_en_el_barrido(db_session, en_caja):
    """La de `due_index` contra la cuenta REAL de filas: el 0 al día 3 de la
    entrada a Caja, el 1 al 10, el 2 al 17 y ya nada más."""
    proc = en_caja(entrada=_ANCLA)

    por_dia = {dia: _barrer(db_session, now=_ANCLA + timedelta(days=dia))["library"]
               for dia in (2, 3, 4, 9, 10, 11, 17, 24, 31)}

    assert por_dia == {2: 0, 3: 1, 4: 0, 9: 0, 10: 1, 11: 0, 17: 1, 24: 0, 31: 0}
    filas = _filas(db_session, proc.id, "library_reminder")
    assert [f.payload for f in filas] == [
        {"anchor": "2001-01-01T15:30:00", "index": i} for i in range(3)]
    assert len(_avisos(db_session, proc.student_id, "LIBRARY_REMINDER")) == 3


def test_en_cualquier_fase(db_session, en_caja):
    """El no adeudo corre desde la fase 1 (D3): el recordatorio no mira la fase."""
    en_documentos = en_caja(fase=1)
    en_cotejo = en_caja(fase=2)

    assert _barrer(db_session) == _conteo(library=2)
    for proc in (en_documentos, en_cotejo):
        assert [f.kind for f in _filas(db_session, proc.id)] == ["library_reminder"]


def test_al_liberarse_deja_de_recordar(db_session, en_caja):
    """Caja registró el pago: la fila ya no está `awaiting_payment` y el
    siguiente recordatorio de la cadencia no sale."""
    from itcj2.apps.titulatec.models import LibraryClearance

    proc = en_caja(entrada=_ANCLA)
    assert _barrer(db_session, now=_ANCLA + timedelta(days=3))["library"] == 1

    fila = db_session.query(LibraryClearance).filter_by(process_id=proc.id).one()
    fila.status, fila.cleared_via = "cleared", "payment"
    db_session.flush()

    assert _barrer(db_session, now=_ANCLA + timedelta(days=10))["library"] == 0
    assert len(_filas(db_session, proc.id, "library_reminder")) == 1


def test_una_nueva_entrada_a_caja_reinicia_el_ancla(db_session, en_caja):
    """Ruling R10: revertir el pago vuelve a fijar `ready_at`. Con el ancla
    vieja, a los 2 días de la nueva entrada ya tocaría el recordatorio 1
    (entrada + 3 + 7 = AHORA); con la nueva, la cuenta empieza de cero."""
    from itcj2.apps.titulatec.models import LibraryClearance

    vieja = AHORA - timedelta(days=10)
    proc = en_caja(entrada=vieja)
    assert _barrer(db_session, now=AHORA)["library"] == 1          # el 0 del ancla vieja

    nueva = AHORA + timedelta(days=1)
    fila = db_session.query(LibraryClearance).filter_by(process_id=proc.id).one()
    fila.ready_at = nueva
    db_session.flush()

    assert _barrer(db_session, now=AHORA + timedelta(days=2))["library"] == 0
    assert _barrer(db_session, now=nueva + timedelta(days=3))["library"] == 1

    primero, segundo = _filas(db_session, proc.id, "library_reminder")
    assert primero.payload == {"anchor": vieja.isoformat(), "index": 0}
    assert segundo.payload == {"anchor": nueva.isoformat(), "index": 0}


def test_maximo_cero_apaga_el_de_pago(db_session, en_caja, monkeypatch):
    from itcj2.apps.titulatec.services.student_mail import MailSettings

    monkeypatch.setattr(MailSettings, "max_reminders", staticmethod(lambda: 0))
    proc = en_caja()

    assert _barrer(db_session) == CEROS
    assert _filas(db_session, proc.id) == []


# ---------------------------------------------------------------------------
# Alcance, apagado, lotes y aislamiento
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("estado", ["on_hold", "cancelled", "completed"])
def test_proceso_en_pausa_o_revocado_no(db_session, con_cita, en_documentos, en_cotejo,
                                        en_caja, estado):
    procesos = [con_cita(proceso=estado)[0], en_documentos(proceso=estado),
                en_cotejo(proceso=estado), en_caja(proceso=estado)]

    assert _barrer(db_session) == CEROS
    for proc in procesos:
        assert _filas(db_session, proc.id) == []
        assert _avisos(db_session, proc.student_id) == []


def test_apagado_no_toca_nada(db_session, con_cita, en_documentos, en_cotejo, en_caja,
                              monkeypatch):
    """`TITULATEC_EMAIL_ENABLED = false`: termina sin tocar la BD (spec C2, §9.5)."""
    from itcj2.apps.titulatec.services.mail_reminders import MailReminders
    from itcj2.apps.titulatec.services.student_mail import MailSettings

    monkeypatch.setattr(MailSettings, "enabled", staticmethod(lambda: False))

    class _SinBD:
        def __getattr__(self, nombre):
            raise AssertionError(f"con el correo apagado no se toca la BD (db.{nombre})")

    assert MailReminders.run(_SinBD(), now=AHORA) == {"disabled": True}

    procesos = [con_cita()[0], en_documentos(), en_cotejo(), en_caja()]
    assert MailReminders.run(db_session, now=AHORA) == {"disabled": True}
    for proc in procesos:
        assert _filas(db_session, proc.id) == []
        assert _avisos(db_session, proc.student_id) == []


def test_consultas_por_lote_sin_n_mas_1(db_session, con_cita, en_documentos, en_cotejo,
                                       en_caja):
    """Las lecturas no crecen con los candidatos: con uno de cada tipo y con
    tres de cada tipo, el barrido hace EXACTAMENTE los mismos SELECT (lo que sí
    crece son las escrituras, una fila y un aviso por recordatorio)."""
    con_cita()
    en_documentos()
    en_cotejo()
    en_caja()
    with _lecturas(db_session) as uno:
        assert _barrer(db_session) == _conteo(appt=1, docs=1, survey=1, library=1)

    otro_dia = AHORA + timedelta(days=1)
    for _ in range(3):
        con_cita(MANANA_10 + timedelta(days=1), now=otro_dia)
        en_documentos(inicio=otro_dia - timedelta(days=4))
        en_cotejo(inicio=otro_dia - timedelta(days=4))
        en_caja(entrada=otro_dia - timedelta(days=4))
    with _lecturas(db_session) as tres:
        assert _barrer(db_session, now=otro_dia) == _conteo(appt=3, docs=3, survey=3,
                                                            library=3)

    assert len(tres) == len(uno), "\n\n".join(tres)


def test_un_candidato_que_falla_no_detiene_a_los_demas(db_session, con_cita, monkeypatch,
                                                      caplog):
    """Correo e in-app del mismo candidato van en su propio SAVEPOINT: si algo
    revienta, se deshacen los dos (la llave deja reintentarlo en la corrida
    siguiente) y el barrido sigue con los demás."""
    from itcj2.apps.titulatec.services.appointment_service import AppointmentService

    primero, _ = con_cita()
    segundo, _ = con_cita()
    original = AppointmentService._notify_appt

    def _notify(db, process_id, *args, **kwargs):
        if process_id == primero.id:
            raise RuntimeError("falla de prueba en el aviso in-app")
        return original(db, process_id, *args, **kwargs)

    monkeypatch.setattr(AppointmentService, "_notify_appt", staticmethod(_notify))
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        assert _barrer(db_session) == _conteo(appt=1)

    assert _filas(db_session, primero.id) == []           # sin correo huérfano
    assert _avisos(db_session, primero.student_id) == []
    assert len(_filas(db_session, segundo.id)) == 1
    assert "RuntimeError" in caplog.text

    monkeypatch.setattr(AppointmentService, "_notify_appt", staticmethod(original))
    assert _barrer(db_session) == _conteo(appt=1)          # la siguiente corrida lo toma
    assert len(_filas(db_session, primero.id)) == 1


def test_el_corte_de_celery_se_propaga_y_lo_encolado_antes_queda_firme(
        db_session, con_cita, en_documentos, monkeypatch):
    """Que celery corte la tarea (`SoftTimeLimitExceeded`) NO es la falla de un
    candidato: `_aislado` no se lo traga (antes lo contaba como «no se encoló»
    y el barrido seguía como si nada, ya pasado el límite). El candidato a
    medias se deshace con su SAVEPOINT, lo encolado ANTES del corte queda
    firme (commit, mismo patrón del despachador) y la excepción sigue su
    camino: el barrido termina ahí."""
    from celery.exceptions import SoftTimeLimitExceeded

    from itcj2.apps.titulatec.services.appointment_service import AppointmentService

    primero, _ = con_cita()
    cortado, _ = con_cita()
    docs = en_documentos()
    db_session.commit()                    # el andamiaje, a salvo del rollback de abajo
    original = AppointmentService._notify_appt

    def _notify(db, process_id, *args, **kwargs):
        if process_id == cortado.id:
            raise SoftTimeLimitExceeded()
        return original(db, process_id, *args, **kwargs)

    monkeypatch.setattr(AppointmentService, "_notify_appt", staticmethod(_notify))

    with pytest.raises(SoftTimeLimitExceeded):
        _barrer(db_session)

    db_session.rollback()                  # lo que el barrido no commiteó se pierde aquí
    assert len(_filas(db_session, primero.id)) == 1        # antes del corte: firme
    assert len(_avisos(db_session, primero.student_id)) == 1
    assert _filas(db_session, cortado.id) == []            # a medias: se deshizo entero
    assert _avisos(db_session, cortado.student_id) == []
    assert _filas(db_session, docs.id) == []               # después del corte: no corrió


def test_un_aviso_que_revienta_en_la_bd_no_deja_el_correo_solo(db_session, con_cita,
                                                               monkeypatch):
    """El caso real: `notify_student` se traga el error de su flush, pero
    Postgres ya deshizo el SAVEPOINT del candidato (y con él su correo). El
    barrido no lo cuenta y los demás siguen."""
    from itcj2.core.services.notification_service import NotificationService

    primero, _ = con_cita()
    segundo, _ = con_cita()
    original = NotificationService.create

    def _create(db, user_id, *args, **kwargs):
        if user_id == primero.student_id:
            user_id = -1                         # FK rota: el flush revienta en Postgres
        return original(db, user_id, *args, **kwargs)

    monkeypatch.setattr(NotificationService, "create", staticmethod(_create))

    assert _barrer(db_session) == _conteo(appt=1)
    assert _filas(db_session, primero.id) == []
    assert len(_filas(db_session, segundo.id)) == 1
    assert len(_avisos(db_session, segundo.student_id)) == 1
