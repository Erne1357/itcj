"""La «L» de licenciatura en el número de control (2026-10-09).

`normalize_control` la quita en toda entrada de TitulaTec, y
`ControlFixService` (comando `titulatec fix-control-l`) corrige lo que ya
entró con ella: solicitudes sin resolver, en Accesos (liga si ya hay cuenta),
duplicadas, y cuentas «L…» que Centro de Cómputo creó (se unifican con la del
alumno o se renombran, con sus archivos).

Escenarios propios con controles «99……» (la base de dev trae casos reales con
L): cada prueba toma del plan SOLO sus solicitudes.
"""
from __future__ import annotations

from datetime import datetime

import pytest

pytestmark = pytest.mark.usefixtures("audit_mark")


# ---------------------------------------------------------------------------
# normalize_control
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("crudo, esperado", [
    ("L21111134", "21111134"), (" l21111134 ", "21111134"), ("21111134", "21111134"),
    ("b21221523", "B21221523"), ("M20110001", "M20110001"), ("L1234", "L1234"), ("", ""),
    (None, ""),
])
def test_normalize_control_quita_solo_la_l_de_licenciatura(crudo, esperado):
    from itcj2.apps.titulatec.services.import_service import normalize_control
    assert normalize_control(crudo) == esperado


# ---------------------------------------------------------------------------
# Andamiaje
# ---------------------------------------------------------------------------
@pytest.fixture()
def escena(db_session, make_cohort, make_student, make_user, make_process, monkeypatch, tmp_path):
    from itcj2.apps.titulatec.models import EnrollmentRequest
    from itcj2.apps.titulatec.services import enrollment_request_service as ers
    from itcj2.apps.titulatec.services.email_helper import TitulaTecEmailHelper

    monkeypatch.setattr("itcj2.apps.titulatec.utils.storage._base", lambda: tmp_path)
    ligas, avisos = [], []
    monkeypatch.setattr(ers, "_token_cache_put", lambda raw: None)
    monkeypatch.setattr(ers.EnrollmentRequestService, "_mail_activation",
                        staticmethod(lambda db, req, raw: ligas.append(req.id) or True))
    monkeypatch.setattr(TitulaTecEmailHelper, "send_username_changed",
                        staticmethod(lambda user, proc, **kw: avisos.append((user.id, kw)) or (True, None)))
    cohorte = make_cohort()

    class E:
        pass
    e = E()
    e.cohort, e.ligas, e.avisos, e.base = cohorte, ligas, avisos, tmp_path

    def solicitud(control, status="pending_review", **cols):
        r = EnrollmentRequest(cohort_id=cohorte.id, control_number=control, first_name="ANA",
                              last_name="PRUEBA", phone="6560000000",
                              contact_email=cols.pop("contact_email", "ana@example.com"),
                              has_efirma=True, kind="unknown", status=status, **cols)
        db_session.add(r)
        db_session.flush()
        return r
    e.solicitud = solicitud

    def alumno():
        # Con contraseña, como las cuentas del SII: sin ella no hay liga (invariante 2).
        u = make_student()
        u.password_hash = "hash-de-prueba"
        db_session.flush()
        return u
    e.alumno = alumno
    e.usuario = make_user
    e.proceso = make_process
    return e


def _accion(db, rid):
    from itcj2.apps.titulatec.services.control_fix_service import ControlFixService
    (a,) = [x for x in ControlFixService.plan(db) if x.request_id == rid]
    return a


def _aplicar(db, rid):
    from itcj2.apps.titulatec.services.control_fix_service import ControlFixService
    a = ControlFixService.apply(db, _accion(db, rid))
    assert not a.resultado.startswith("ERROR"), a.resultado
    return a


def _fresca(db, model, pk):
    db.expire_all()
    return db.get(model, pk)


# ---------------------------------------------------------------------------
# Solicitudes sin cuenta «L»
# ---------------------------------------------------------------------------
def test_pendiente_con_cuenta_se_corrige_y_queda_con_cuenta(db_session, escena):
    from itcj2.apps.titulatec.models import EnrollmentRequest
    alumno = escena.alumno()
    r = escena.solicitud("L" + alumno.control_number)

    assert _accion(db_session, r.id).tipo == "corregir"
    _aplicar(db_session, r.id)

    r = _fresca(db_session, EnrollmentRequest, r.id)
    assert (r.control_number, r.kind, r.status) == (alumno.control_number, "known", "pending_review")


def test_en_accesos_con_cuenta_recibe_la_liga_y_conserva_la_aprobacion_de_se(db_session, escena):
    from itcj2.apps.titulatec.models import EnrollmentRequest
    alumno = escena.alumno()
    se = escena.usuario(first_name="SE")
    cuando = datetime(2026, 10, 7, 9, 30)
    r = escena.solicitud("L" + alumno.control_number, status="awaiting_access",
                         reviewed_by_id=se.id, reviewed_at=cuando)

    assert _accion(db_session, r.id).tipo == "liga"
    a = _aplicar(db_session, r.id)

    r = _fresca(db_session, EnrollmentRequest, r.id)
    assert (r.control_number, r.status) == (alumno.control_number, "approved")
    assert (r.reviewed_by_id, r.reviewed_at) == (se.id, cuando)
    assert r.verify_token_hash
    assert escena.ligas == [r.id] and a.correo == "liga enviada"


def test_en_accesos_con_otra_correcta_pendiente_la_otra_hereda_y_recibe_la_liga(db_session, escena):
    from itcj2.apps.titulatec.models import EnrollmentRequest
    alumno = escena.alumno()
    se = escena.usuario(first_name="SE")
    cuando = datetime(2026, 10, 7, 9, 30)
    mala = escena.solicitud("L" + alumno.control_number, status="awaiting_access",
                            reviewed_by_id=se.id, reviewed_at=cuando)
    buena = escena.solicitud(alumno.control_number)

    a = _accion(db_session, mala.id)
    assert (a.tipo, a.otra_id) == ("liga_en_otra", buena.id)
    _aplicar(db_session, mala.id)

    mala, buena = (_fresca(db_session, EnrollmentRequest, x.id) for x in (mala, buena))
    assert mala.status == "rejected" and f"#{buena.id}" in mala.review_note
    assert (buena.status, buena.reviewed_by_id, buena.reviewed_at) == ("approved", se.id, cuando)
    assert escena.ligas == [buena.id]


def test_duplicada_de_una_ya_inscrita_se_rechaza_sin_correo(db_session, escena):
    from itcj2.apps.titulatec.models import EnrollmentRequest
    alumno = escena.alumno()
    inscrita = escena.solicitud(alumno.control_number, status="converted")
    mala = escena.solicitud("L" + alumno.control_number, status="awaiting_access")

    assert _accion(db_session, mala.id).tipo == "rechazar_dup"
    _aplicar(db_session, mala.id)

    mala = _fresca(db_session, EnrollmentRequest, mala.id)
    assert mala.status == "rejected" and f"#{inscrita.id}" in mala.review_note
    assert escena.ligas == [] and escena.avisos == []


# ---------------------------------------------------------------------------
# Cuenta «L…» creada por Centro de Cómputo
# ---------------------------------------------------------------------------
def _inscrita_con_l(db_session, escena, make_document, control):
    """Cuenta «L…» con proceso, un documento en disco y la solicitud convertida."""
    l_control = "L" + control
    cuenta_l = escena.usuario(control_number=l_control, username=l_control)
    proc = escena.proceso(cuenta_l, cohort=escena.cohort)
    rel = f"20263/{l_control}/documents/{l_control}_CURP.pdf"
    (escena.base / rel).parent.mkdir(parents=True)
    (escena.base / rel).write_bytes(b"%PDF-1.4 curp")
    doc = make_document(proc, type_code="curp", file_path=rel, uploaded_by=cuenta_l)
    r = escena.solicitud(l_control, status="converted", converted_process_id=proc.id,
                         contact_email="personal@example.com")
    return cuenta_l, proc, doc, r


def test_unificar_pasa_el_proceso_y_los_archivos_a_su_cuenta(
        db_session, escena, make_document):
    from itcj2.core.models.user import User
    from itcj2.apps.titulatec.models import Document, EnrollmentRequest, TitulationProcess
    real = escena.usuario(control_number="99" + str(datetime.now().microsecond).zfill(6),
                          is_active=False)
    cuenta_l, proc, doc, r = _inscrita_con_l(db_session, escena, make_document,
                                             real.control_number)
    dup = escena.solicitud(real.control_number, contact_email="otro@example.com")
    l_id = cuenta_l.id

    a = _accion(db_session, r.id)
    assert (a.tipo, a.otra_id) == ("unificar", dup.id)
    _aplicar(db_session, r.id)

    assert _fresca(db_session, User, l_id) is None
    real = _fresca(db_session, User, real.id)
    assert real.is_active is True
    assert _fresca(db_session, TitulationProcess, proc.id).student_id == real.id
    doc = _fresca(db_session, Document, doc.id)
    nuevo = f"20263/{real.control_number}/documents/{real.control_number}_CURP.pdf"
    assert doc.file_path == nuevo and doc.uploaded_by_id == real.id
    assert (escena.base / nuevo).read_bytes() == b"%PDF-1.4 curp"
    assert not (escena.base / f"20263/L{real.control_number}").exists()
    r = _fresca(db_session, EnrollmentRequest, r.id)
    assert (r.control_number, r.status, r.converted_process_id) == (
        real.control_number, "converted", proc.id)
    assert _fresca(db_session, EnrollmentRequest, dup.id).status == "rejected"
    ((uid, kw),) = escena.avisos
    assert uid == real.id and kw["old_control"] == "L" + real.control_number
    assert set(kw["personal_emails"]) == {"personal@example.com", "otro@example.com"}


def test_renombrar_sin_otra_cuenta_cambia_el_usuario(db_session, escena, make_document):
    from itcj2.core.models.user import User
    from itcj2.apps.titulatec.models import Document
    control = "98" + str(datetime.now().microsecond).zfill(6)
    cuenta_l, proc, doc, r = _inscrita_con_l(db_session, escena, make_document, control)

    assert _accion(db_session, r.id).tipo == "renombrar"
    _aplicar(db_session, r.id)

    u = _fresca(db_session, User, cuenta_l.id)
    assert (u.control_number, u.username) == (control, control)
    assert _fresca(db_session, Document, doc.id).file_path.startswith(f"20263/{control}/")
    assert len(escena.avisos) == 1


def test_una_segunda_corrida_ya_no_encuentra_nada(db_session, escena, make_document):
    from itcj2.apps.titulatec.services.control_fix_service import ControlFixService
    alumno = escena.alumno()
    r = escena.solicitud("L" + alumno.control_number)
    _aplicar(db_session, r.id)
    assert not [x for x in ControlFixService.plan(db_session) if x.request_id == r.id]


def test_el_aviso_va_al_institucional_y_a_los_personales_sin_repetir(monkeypatch):
    from types import SimpleNamespace
    from itcj2.apps.titulatec.services import email_helper

    enviados = {}
    monkeypatch.setattr(email_helper, "deliver_detailed",
                        lambda **kw: enviados.update(kw) or (True, None))
    user = SimpleNamespace(control_number="20110908", full_name="ALAN", email=None,
                           username="20110908")
    ok, _ = email_helper.TitulaTecEmailHelper.send_username_changed(
        user, None, old_control="L20110908", personal_emails=["a@x.com", "a@x.com", "b@x.com"])
    assert ok
    assert enviados["template"] == "username_changed.html"
    assert enviados["to"][1:] == ["a@x.com", "b@x.com"]
    assert "20110908" in enviados["to"][0]
