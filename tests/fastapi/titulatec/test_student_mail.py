"""`StudentMail`: encolar los correos del proceso al egresado (spec 2026-09-28 §5, §6 C2/C7).

Lo que se fija aquí. Los ganchos de los services, la composición, el
despachador y los recordatorios son tareas aparte que consumen EXACTAMENTE
estas firmas y estos payloads:

1. `enqueue` escribe en la transacción del LLAMADOR: ni commit ni flush. Si el
   evento revierte, la fila nunca existió (Review Focus 4).
2. Apagado (`MailSettings.enabled()` falso) = no se escribe nada, tampoco por
   la rama con llave.
3. Recordatorios con `dedupe_key`: `INSERT … ON CONFLICT DO NOTHING`; la
   segunda vez devuelve False y no hay segunda fila. Un error de Postgres en
   ese INSERT no deja abortada la transacción del llamador.
4. Nunca lanza: lo que no se puede encolar deja un warning y devuelve False.
5. Destinatario (D2): perfil → solicitud que convirtió el proceso (la más
   reciente) → None. Nunca el institucional, y leerlo no crea perfiles.
6. Ligas (D10/C7): `{PUBLIC_ORIGIN}/itcj/login?next=<ruta codificada>`, la
   ruta pasa `safe_next`; un solo origen público en toda la app.
7. Payload exacto de cada evento, grupo y llave.

Los settings se parchean en `MailSettings`, nunca en `get_settings` (salvo la
prueba del propio `MailSettings`, que es justo lo que verifica).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path

import pytest

LOGGER = "itcj2.apps.titulatec.services.student_mail"


# ---------------------------------------------------------------------------
# Andamiaje local
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _correo_encendido(monkeypatch):
    """Estas pruebas no dependen del `.env` del contenedor: correo encendido.

    Mismo molde que `_modo_oficial_por_defecto` del conftest: se fija el
    ATRIBUTO del singleton de `get_settings()`, no el método, para que
    `test_mail_settings_lee_cada_variable` vea el getter REAL. La prueba del
    apagado parchea `MailSettings.enabled` encima y gana.
    """
    from itcj2.config import get_settings

    monkeypatch.setattr(get_settings(), "TITULATEC_EMAIL_ENABLED", True)


@pytest.fixture()
def proceso(make_student, make_process):
    """Proceso vivo de un egresado ficticio (sin sus 9 fases: aquí no hacen falta)."""
    def _make():
        return make_process(make_student(), phases=False)

    return _make


@pytest.fixture()
def perfil(db_session):
    """`core_student_profile` con el correo PERSONAL dado (puede ser vacío o None)."""
    from itcj2.core.models.student_profile import StudentProfile

    def _make(user_id, contact_email):
        row = StudentProfile(user_id=user_id, contact_email=contact_email)
        db_session.add(row)
        db_session.flush()
        return row

    return _make


@pytest.fixture()
def solicitud_convertida(db_session):
    """`EnrollmentRequest` ya `converted` hacia `process`. Datos inventados; el
    índice parcial de solicitudes vivas deja fuera `converted`, así que varias
    con el mismo número de control no chocan."""
    from itcj2.apps.titulatec.models import EnrollmentRequest

    def _make(process, contact_email):
        row = EnrollmentRequest(
            cohort_id=process.cohort_id, control_number="99000000",
            first_name="JUAN", last_name="PEREZ", phone="6560000000",
            contact_email=contact_email, has_efirma=False, kind="known",
            status="converted", converted_process_id=process.id,
        )
        db_session.add(row)
        db_session.flush()
        return row

    return _make


def _nuevas(db):
    """Filas del outbox AGREGADAS a la sesión y todavía sin flush."""
    from itcj2.apps.titulatec.models import EmailOutbox

    return [o for o in db.new if isinstance(o, EmailOutbox)]


def _filas(db, process_id):
    """Filas del outbox del proceso ya en la BD. El flush es EXPLÍCITO: el
    contrato no puede depender del autoflush, que en producción está apagado
    (`itcj2/database.py`) y en este arnés prendido."""
    from itcj2.apps.titulatec.models import EmailOutbox

    db.flush()
    return (db.query(EmailOutbox).filter_by(process_id=process_id)
            .order_by(EmailOutbox.id).all())


# ---------------------------------------------------------------------------
# enqueue: transacción del llamador, apagado, llave, nunca lanza
# ---------------------------------------------------------------------------
def test_encola_con_el_alumno_como_destinatario_y_sin_commit(db_session, proceso):
    from itcj2.apps.titulatec.models import EmailOutbox
    from itcj2.apps.titulatec.services.student_mail import StudentMail

    proc = proceso()
    db_session.commit()                  # el setup sobrevive al rollback de abajo
    pid, alumno = proc.id, proc.student_id

    ok = StudentMail.enqueue(
        db_session, kind="phase_rejected", process=proc,
        payload={"phase_number": 1, "phase_name": "Documentos iniciales",
                 "reason": "Falta la firma"},
    )

    assert ok is True
    (nueva,) = _nuevas(db_session)       # en la sesión, sin flush propio
    assert (nueva.user_id, nueva.process_id) == (alumno, pid)
    (fila,) = _filas(db_session, pid)
    assert fila.kind == "phase_rejected"
    assert fila.status == "pending"

    db_session.rollback()                # el evento revierte ...
    # ... y el correo con él: enqueue no commiteó nada por su cuenta.
    assert db_session.query(EmailOutbox).filter_by(process_id=pid).count() == 0


def test_apagado_no_escribe(db_session, proceso, make_appointment, monkeypatch):
    from itcj2.apps.titulatec.services.student_mail import MailSettings, StudentMail

    monkeypatch.setattr(MailSettings, "enabled", staticmethod(lambda: False))
    proc = proceso()
    cita = make_appointment(proc)

    assert StudentMail.enqueue(
        db_session, kind="phase_rejected", process=proc,
        payload={"phase_number": 1, "phase_name": "Documentos iniciales", "reason": None},
    ) is False
    assert StudentMail.appointment_changed(
        db_session, proc, event="scheduled", appt=cita, by="officer") is False
    # la rama con llave (INSERT directo) tampoco escribe
    assert StudentMail.appointment_reminder(db_session, proc, appt=cita) is False
    assert _nuevas(db_session) == []
    assert _filas(db_session, proc.id) == []


def test_dedupe_dos_veces_una_fila(db_session, proceso):
    from itcj2.apps.titulatec.models import EmailOutbox
    from itcj2.apps.titulatec.services.student_mail import StudentMail

    proc = proceso()
    db_session.commit()
    llave = f"docs_reminder:{proc.id}:20260920T083005:0"
    carga = {"anchor": "2026-09-20T08:30:05", "index": 0}

    primera = StudentMail.enqueue(db_session, kind="docs_reminder", process=proc,
                                  payload=carga, dedupe_key=llave)
    segunda = StudentMail.enqueue(db_session, kind="docs_reminder", process=proc,
                                  payload=carga, dedupe_key=llave)

    assert (primera, segunda) == (True, False)
    filas = db_session.query(EmailOutbox).filter_by(dedupe_key=llave).all()
    assert len(filas) == 1
    assert filas[0].user_id == proc.student_id

    db_session.rollback()                # con llave tampoco commitea
    assert db_session.query(EmailOutbox).filter_by(dedupe_key=llave).count() == 0


def test_error_de_bd_en_el_insert_con_llave_no_aborta_la_transaccion(
        db_session, proceso, caplog):
    """Un error de Postgres deja abortada la transacción ENTERA: sin el
    SAVEPOINT, el siguiente statement del llamador (el resto del barrido, o el
    commit del evento) revienta aunque `enqueue` haya devuelto False."""
    from types import SimpleNamespace

    from itcj2.apps.titulatec.services.student_mail import StudentMail

    proc = proceso()
    alumno_inexistente = SimpleNamespace(id=proc.id, student_id=-1)  # rompe la FK
    carga = {"anchor": "2026-09-20T08:30:05", "index": 0}

    with caplog.at_level(logging.WARNING, logger=LOGGER):
        ok = StudentMail.enqueue(db_session, kind="docs_reminder",
                                 process=alumno_inexistente, payload=carga,
                                 dedupe_key=f"docs_reminder:{proc.id}:a:0")

    assert ok is False
    assert "docs_reminder" in caplog.text
    # la transacción del llamador sigue viva
    assert StudentMail.enqueue(db_session, kind="docs_reminder", process=proc,
                               payload=carga,
                               dedupe_key=f"docs_reminder:{proc.id}:b:0") is True
    assert len(_filas(db_session, proc.id)) == 1


def test_payload_no_serializable_no_lanza(db_session, proceso, caplog):
    from itcj2.apps.titulatec.services.student_mail import StudentMail

    proc = proceso()
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        ok = StudentMail.enqueue(
            db_session, kind="phase_rejected", process=proc,
            payload={"phase_number": 1, "cuando": datetime(2026, 9, 28, 10, 0)},
        )

    assert ok is False
    assert _nuevas(db_session) == []
    assert _filas(db_session, proc.id) == []
    assert "phase_rejected" in caplog.text


def test_un_evento_mal_formado_no_lanza(db_session, proceso, caplog):
    """Los ganchos llaman ANTES del commit del evento: una excepción aquí
    tumbaría el dictamen o la cita. Fuera de dominio o con datos rotos: False,
    un warning por caso, ninguna fila."""
    from itcj2.apps.titulatec.services.student_mail import StudentMail

    proc = proceso()
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        casos = [
            StudentMail.enqueue(db_session, kind="no_existe", process=proc, payload={}),
            StudentMail.survey_result(db_session, proc, result="pending"),
            StudentMail.appointment_changed(db_session, proc, event="moved",
                                            appt=None, by="officer"),
            StudentMail.appointment_changed(db_session, proc, event="cancelled",
                                            appt=None, by="alumno"),
            StudentMail.appointment_changed(db_session, proc, event="scheduled",
                                            appt=None, by="officer"),
            StudentMail.doc_reviewed(db_session, proc, type_code="curp",
                                     doc_name="CURP", status="pending", note=None),
            StudentMail.doc_reviewed(db_session, None, type_code="curp",
                                     doc_name="CURP", status="approved", note=None),
        ]

    assert casos == [False] * len(casos)
    assert _filas(db_session, proc.id) == []
    assert caplog.text.count("No se encoló") == len(casos)


# ---------------------------------------------------------------------------
# Destinatario (D2)
# ---------------------------------------------------------------------------
def test_contact_email_perfil_gana(db_session, proceso, perfil, solicitud_convertida):
    from itcj2.apps.titulatec.services.student_mail import StudentMail

    proc = proceso()
    perfil(proc.student_id, "  perfil.personal@example.invalid ")
    solicitud_convertida(proc, "solicitud@example.invalid")

    assert StudentMail.contact_email(db_session, proc) == "perfil.personal@example.invalid"


def test_contact_email_respaldo_solicitud_mas_reciente(
        db_session, proceso, perfil, solicitud_convertida):
    from itcj2.apps.titulatec.services.student_mail import StudentMail

    proc, otro = proceso(), proceso()
    perfil(proc.student_id, None)                         # perfil sin correo
    solicitud_convertida(proc, "vieja@example.invalid")
    solicitud_convertida(proc, "nueva@example.invalid")
    # id mayor que las dos de arriba, pero convirtió OTRO proceso
    solicitud_convertida(otro, "de.otro.proceso@example.invalid")

    assert StudentMail.contact_email(db_session, proc) == "nueva@example.invalid"


def test_contact_email_ninguno(db_session, proceso):
    """Sin correo personal no hay destinatario, aunque la cuenta tenga su
    correo institucional: ese NUNCA es respaldo (D2)."""
    from itcj2.apps.titulatec.services.student_mail import StudentMail
    from itcj2.core.models.user import User

    proc = proceso()
    assert db_session.get(User, proc.student_id).email      # sí tiene institucional

    assert StudentMail.contact_email(db_session, proc) is None


def test_contact_email_vacio_es_ausente(db_session, proceso, perfil, solicitud_convertida):
    from itcj2.apps.titulatec.services.student_mail import StudentMail

    con_respaldo, sin_nada = proceso(), proceso()
    perfil(con_respaldo.student_id, "   ")
    solicitud_convertida(con_respaldo, "respaldo@example.invalid")
    perfil(sin_nada.student_id, "")
    solicitud_convertida(sin_nada, "  ")

    assert StudentMail.contact_email(db_session, con_respaldo) == "respaldo@example.invalid"
    assert StudentMail.contact_email(db_session, sin_nada) is None


def test_contact_email_no_crea_perfil(db_session, proceso):
    from itcj2.apps.titulatec.services.student_mail import StudentMail
    from itcj2.core.models.student_profile import StudentProfile

    proc = proceso()

    assert StudentMail.contact_email(db_session, proc) is None
    assert not [o for o in db_session.new if isinstance(o, StudentProfile)]
    db_session.flush()
    assert db_session.query(StudentProfile).filter_by(user_id=proc.student_id).count() == 0


# ---------------------------------------------------------------------------
# Ligas (D10, C7)
# ---------------------------------------------------------------------------
def test_link_codifica_y_pasa_safe_next():
    from urllib.parse import parse_qs, unquote, urlsplit

    from itcj2.apps.titulatec.services.email_helper import PUBLIC_ORIGIN
    from itcj2.apps.titulatec.services.student_mail import StudentMail
    from itcj2.core.pages.auth import safe_next

    ruta = "/titulatec/student/dashboard?fase=2"
    liga = StudentMail.link(ruta)

    assert liga == (f"{PUBLIC_ORIGIN}/itcj/login"
                    "?next=%2Ftitulatec%2Fstudent%2Fdashboard%3Ffase%3D2")
    assert safe_next(unquote(liga.split("next=", 1)[1])) == ruta
    # un parser de URL real devuelve la ruta ENTERA como `next` (el `?fase=2`
    # no se escapa como parámetro propio de /itcj/login)
    partes = urlsplit(liga)
    assert f"{partes.scheme}://{partes.netloc}" == PUBLIC_ORIGIN
    assert partes.path == "/itcj/login"
    assert parse_qs(partes.query) == {"next": [ruta]}


@pytest.mark.parametrize("ruta", [
    "//evil", "https://x", "/\\evil", "titulatec/student/dashboard", "",
    " /titulatec/student/cita",
])
def test_link_rechaza_rutas_externas(ruta):
    from itcj2.apps.titulatec.services.student_mail import StudentMail

    with pytest.raises(ValueError):
        StudentMail.link(ruta)


# ---------------------------------------------------------------------------
# Grupos y espera
# ---------------------------------------------------------------------------
def test_fase_1_aprobada_va_al_grupo_de_documentos(db_session, seed_phase_defs, proceso):
    """§5 #1b: el aviso de la fase `initial_docs` sale en el MISMO correo que el
    dictamen de sus documentos."""
    from itcj2.apps.titulatec.services.phase_service import PhaseService
    from itcj2.apps.titulatec.services.student_mail import StudentMail

    seed_phase_defs()
    inicial = PhaseService.phase_number_for_code(db_session, "initial_docs")
    proc = proceso()

    assert StudentMail.phase_approved(
        db_session, proc, phase_number=inicial, phase_name="Documentos iniciales",
        next_phase=inicial + 1, next_name="Cita de cotejo", handoff=False,
    ) is True

    (fila,) = _filas(db_session, proc.id)
    assert fila.kind == "phase_approved"
    assert fila.group_key == StudentMail.docs_group(proc.id) == f"docs:{proc.id}"
    assert fila.payload == {
        "phase_number": inicial, "phase_name": "Documentos iniciales",
        "next_phase": inicial + 1, "next_name": "Cita de cotejo",
        "handoff": False, "completed": False,
    }


def test_fase_2_aprobada_es_individual(db_session, seed_phase_defs, proceso):
    from itcj2.apps.titulatec.services.student_mail import StudentMail

    seed_phase_defs()
    proc = proceso()

    assert StudentMail.phase_approved(
        db_session, proc, phase_number=2, phase_name="Cita de cotejo",
        next_phase=3, next_name="Formato B", handoff=True,
    ) is True

    (fila,) = _filas(db_session, proc.id)
    assert fila.kind == "phase_approved"
    assert fila.group_key is None
    assert (fila.payload["handoff"], fila.payload["completed"]) == (True, False)


def test_no_show_espera_la_gracia(db_session, proceso, make_appointment, monkeypatch):
    """«No se presentó» espera la misma ventana del agrupado (D8): si el
    encargado lo deshace dentro de ella, el correo ya no aplica."""
    from itcj2.apps.titulatec.services.student_mail import MailSettings, StudentMail
    from itcj2.core.utils.timezone import db_now

    monkeypatch.setattr(MailSettings, "digest_minutes", staticmethod(lambda: 17))
    proc = proceso()
    cita = make_appointment(proc, status="no_show")

    antes = db_now()
    assert StudentMail.appointment_no_show(db_session, proc, appt=cita) is True
    despues = db_now()

    (fila,) = _filas(db_session, proc.id)
    assert fila.kind == "appt_no_show"
    espera = timedelta(minutes=17)
    assert antes + espera <= fila.not_before <= despues + espera
    assert (fila.group_key, fila.dedupe_key) == (None, None)


# ---------------------------------------------------------------------------
# Payload exacto de cada evento (lo leen la composición y el barrido)
# ---------------------------------------------------------------------------
def test_cada_evento_arma_su_payload_grupo_y_llave(db_session, proceso, make_appointment):
    from itcj2.apps.titulatec.services.student_mail import StudentMail

    proc = proceso()
    pid = proc.id
    cita = make_appointment(proc, when=datetime(2029, 3, 5, 10, 30),
                            location="Edificio X · Ventanilla 2")
    ancla = datetime(2026, 9, 20, 8, 30, 5)

    resultados = [
        StudentMail.doc_reviewed(db_session, proc, type_code="curp",
                                 doc_name="CURP certificada", status="rejected",
                                 note="Ilegible"),
        StudentMail.phase_rejected(db_session, proc, phase_number=1,
                                   phase_name="Documentos iniciales",
                                   reason="Falta un documento"),
        StudentMail.phase_approved(db_session, proc, phase_number=8,
                                   phase_name="Acto protocolario", next_phase=None,
                                   next_name=None, handoff=False),
        StudentMail.survey_result(db_session, proc, result="approved"),
        StudentMail.survey_result(db_session, proc, result="rejected",
                                  reason="Faltan respuestas"),
        StudentMail.survey_result(db_session, proc, result="revoked",
                                  reason="Se liberó por error"),
        StudentMail.appointment_changed(db_session, proc, event="rescheduled",
                                        appt=cita, by="officer"),
        StudentMail.appointment_no_show(db_session, proc, appt=cita),
        StudentMail.appointment_reminder(db_session, proc, appt=cita),
        StudentMail.docs_reminder(db_session, proc, anchor=ancla, index=1),
        StudentMail.survey_reminder(db_session, proc, anchor=ancla, index=0),
    ]
    assert resultados == [True] * len(resultados)

    iso = "2029-03-05T10:30:00"
    lugar = "Edificio X · Ventanilla 2"
    esperado = {  # kind: (payload, group_key, dedupe_key)
        "docs_review": ({"type_code": "curp", "name": "CURP certificada",
                         "status": "rejected", "note": "Ilegible"}, f"docs:{pid}", None),
        "phase_rejected": ({"phase_number": 1, "phase_name": "Documentos iniciales",
                            "reason": "Falta un documento"}, None, None),
        "phase_approved": ({"phase_number": 8, "phase_name": "Acto protocolario",
                            "next_phase": None, "next_name": None, "handoff": False,
                            "completed": True}, None, None),
        "survey_approved": ({"reason": None, "origin": "submission"}, None, None),
        "survey_rejected": ({"reason": "Faltan respuestas", "origin": "submission"}, None, None),
        "survey_revoked": ({"reason": "Se liberó por error", "origin": "submission"}, None, None),
        "appt_changed": ({"event": "rescheduled", "by": "officer", "reason": None,
                          "appt_id": cita.id, "scheduled_at": iso, "location": lugar},
                         f"cita:{pid}", None),
        "appt_no_show": ({"appt_id": cita.id, "scheduled_at": iso}, None, None),
        "appt_reminder": ({"appt_id": cita.id, "scheduled_at": iso, "location": lugar},
                          None, f"appt_reminder:{cita.id}"),
        "docs_reminder": ({"anchor": "2026-09-20T08:30:05", "index": 1}, None,
                          f"docs_reminder:{pid}:20260920T083005:1"),
        "survey_reminder": ({"anchor": "2026-09-20T08:30:05", "index": 0}, None,
                            f"survey_reminder:{pid}:20260920T083005:0"),
    }
    por_kind = {f.kind: f for f in _filas(db_session, pid)}
    assert set(por_kind) == set(esperado)
    for kind, (payload, grupo, llave) in esperado.items():
        fila = por_kind[kind]
        assert fila.payload == payload, kind
        assert (fila.group_key, fila.dedupe_key) == (grupo, llave), kind
        assert fila.user_id == proc.student_id, kind


def test_history_mas_nuevo_primero_y_solo_del_proceso(db_session, proceso):
    from itcj2.apps.titulatec.services.student_mail import StudentMail
    from itcj2.core.utils.timezone import db_now

    mio, ajeno = proceso(), proceso()
    for n in range(3):
        StudentMail.phase_rejected(db_session, mio, phase_number=1,
                                   phase_name="Documentos iniciales", reason=f"motivo {n}")
    StudentMail.phase_rejected(db_session, ajeno, phase_number=1,
                               phase_name="Documentos iniciales", reason="ajeno")
    filas = _filas(db_session, mio.id)
    # Misma transacción = mismo NOW(): desempata el id. Se adelanta la primera
    # para probar que manda `created_at`.
    filas[0].created_at = db_now() + timedelta(days=1)
    db_session.flush()

    motivos = [f.payload["reason"] for f in StudentMail.history(db_session, mio.id)]
    assert motivos == ["motivo 0", "motivo 2", "motivo 1"]
    assert len(StudentMail.history(db_session, mio.id, limit=2)) == 2


# ---------------------------------------------------------------------------
# Catálogo, settings y origen público
# ---------------------------------------------------------------------------
def test_kind_labels_cubre_todos_los_kinds():
    from itcj2.apps.titulatec.models.email_outbox import OUTBOX_KINDS
    from itcj2.apps.titulatec.services.student_mail import StudentMail

    assert set(StudentMail.KIND_LABELS) == set(OUTBOX_KINDS)
    for kind, etiqueta in StudentMail.KIND_LABELS.items():
        assert etiqueta and etiqueta != kind, kind
        assert "_" not in etiqueta and etiqueta[:1].isupper(), (kind, etiqueta)


def test_mail_settings_lee_cada_variable(monkeypatch):
    """Cada getter lee SU variable: valores distintos delatan un cruce."""
    from itcj2.apps.titulatec.services.student_mail import MailSettings
    from itcj2.config import get_settings

    valores = {
        "TITULATEC_EMAIL_ENABLED": False,
        "TITULATEC_EMAIL_DIGEST_MINUTES": 11,
        "TITULATEC_EMAIL_MAX_ATTEMPTS": 12,
        "TITULATEC_REMINDER_FIRST_DAYS": 13,
        "TITULATEC_REMINDER_EVERY_DAYS": 14,
        "TITULATEC_REMINDER_MAX": 15,
        "TITULATEC_APPT_REMINDER_DAYS_BEFORE": 16,
    }
    for nombre, valor in valores.items():
        monkeypatch.setattr(get_settings(), nombre, valor)

    assert MailSettings.enabled() is False
    assert (MailSettings.digest_minutes(), MailSettings.max_attempts(),
            MailSettings.first_days(), MailSettings.every_days(),
            MailSettings.max_reminders(), MailSettings.appt_days_before()
            ) == (11, 12, 13, 14, 15, 16)


def test_un_solo_origen_publico():
    """C7: el origen vive en `email_helper.PUBLIC_ORIGIN`. `PUBLIC_BASE_URL` es
    su alias (conserva el nombre: lo usan `_verify_link` y sus pruebas) y ningún
    otro `.py` de la app repite el literal."""
    import itcj2
    from itcj2.apps.titulatec.services import email_helper, enrollment_request_service

    assert enrollment_request_service.PUBLIC_BASE_URL == email_helper.PUBLIC_ORIGIN
    assert email_helper._BASE_URL == f"{email_helper.PUBLIC_ORIGIN}/titulatec"

    app = Path(itcj2.__file__).resolve().parent / "apps" / "titulatec"
    host = email_helper.PUBLIC_ORIGIN.split("://", 1)[1]
    con_literal = sorted(
        p.relative_to(app).as_posix() for p in app.rglob("*.py")
        if host in p.read_text(encoding="utf-8")
    )
    assert con_literal == ["services/email_helper.py"]
