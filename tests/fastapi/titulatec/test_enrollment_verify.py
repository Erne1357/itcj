"""Liga de activación: `verify()` y `_convert()` (2026-09-15).

Desde que TODA solicitud pasa por la bandeja, la liga solo existe para una
solicitud `approved` de una cuenta que YA EXISTE en `core_users`: la emite
Servicios Escolares al aprobar y viaja al correo personal del formulario.
Abrirla es lo único que inscribe a esa cuenta (proceso + rol de la app). Una
cuenta nueva nunca pasa por aquí: recibe su NIP por correo al aprobarse (ver
`test_enrollment_approve.py`).

Invariantes que fija este archivo:
- solo `approved` convierte; `pending_review`, `rejected`, los estados legado y
  un token desconocido son `invalid`;
- la liga es idempotente (Outlook Safe Links la pre-abre);
- si `_convert` falla una revalidación, la solicitud vuelve a `pending_review`
  con la nota y SIN dejar usuario/rol/proceso a medias;
- el aviso de folio va al institucional DESPUÉS del commit;
- abrir la liga no escribe el perfil ni emite liga de contacto.

`import_rows` COMMITEA POR SU CUENTA POR OMISIÓN (`import_service.py`, parámetro
`commit`), así que `_convert` lo llama con `commit=False` y `verify()` es dueño
de la transacción entera.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta

import pytest

VERIFY_URL = "/titulatec/inscripcion/verificar"
NIP_DE_SIEMPRE = "9999"

TARJETA_LISTO = "Listo, ya tienes acceso"
TARJETA_VENCIDA = ("Esa liga venció", "Pide a Servicios Escolares que te la reenvíe.")
TARJETA_REVISION = ("Tu solicitud necesita revisión",
                    "Servicios Escolares la revisará y te escribirá por correo.")
TARJETA_INVALIDA = "No pudimos validar tu liga"


def _plano(html: str) -> str:
    return " ".join(html.split())


@pytest.fixture()
def correo_falso(monkeypatch):
    """Captura los envíos sin tocar Graph: `(asunto, destinatarios, html)`."""
    enviados = []

    class _Resp:
        status_code = 202
        text = ""

    def _fake_send(access_token, subject, content_html, to_list, save_to_sent=True):
        enviados.append((subject, list(to_list), content_html))
        return _Resp()

    monkeypatch.setattr("itcj2.core.utils.msgraph_mail.acquire_token_silent",
                        lambda app_key: "token-de-prueba")
    monkeypatch.setattr("itcj2.core.utils.msgraph_mail.graph_send_mail", _fake_send)
    return enviados


def _cuenta(make_user, db_session, control, *, password=True, is_active=True):
    """Cuenta que YA existe en `core_users`, con contraseña salvo que se diga."""
    from itcj2.core.utils.security import hash_nip

    user = make_user(first_name="ALUMNA", last_name="REAL", control_number=control,
                     username=control, is_active=is_active)
    user.password_hash = hash_nip(NIP_DE_SIEMPRE) if password else None
    user.must_change_password = False
    db_session.flush()
    return user


def _aprobada(db_session, cohort, *, control, status="approved",
              vence=timedelta(days=7), email="personal@example.invalid", **kw):
    """Solicitud con liga emitida + el texto claro del token. `(req, token)`.

    Se construye a mano en vez de pasar por `approve()` para que la prueba tenga
    el claro del token sin depender de Redis ni del correo.
    """
    from itcj2.apps.titulatec.models import EnrollmentRequest

    token = secrets.token_urlsafe(32)
    row = EnrollmentRequest(
        cohort_id=cohort.id, control_number=control,
        first_name="ALUMNA", last_name="INVENTADA", middle_name=None,
        program_id=None, program_text="Ingenieria Ficticia",
        phone="6561234567", contact_email=email,
        has_efirma=False, kind="known", status=status,
        verify_token_hash=hashlib.sha256(token.encode("utf-8")).hexdigest(),
        verify_expires_at=datetime.now() + vence,
        verify_sent_at=datetime.now() - timedelta(hours=1), verify_send_count=1,
        verify_sent_to=email, reviewed_at=datetime.now() - timedelta(hours=1),
    )
    for k, v in kw.items():
        setattr(row, k, v)
    db_session.add(row)
    db_session.flush()
    return row, token


def _procesos(db_session, user, cohort):
    from itcj2.apps.titulatec.models import TitulationProcess
    return (db_session.query(TitulationProcess)
            .filter_by(student_id=user.id, cohort_id=cohort.id).all())


# ---------------------------------------------------------------------------
# import_rows: el contrato del que depende `_convert`
# ---------------------------------------------------------------------------
def test_import_rows_con_repair_credentials_false_no_pone_el_control_de_contrasena(
    db_session, make_cohort, make_user, seed_phase_defs, titulatec_app,
):
    """Criterio 11: nadie queda con la contraseña igual a su número de control.

    Ojo con el orden de argumentos: `verify_nip(nip, nip_hash)`.
    """
    from itcj2.core.utils.security import verify_nip
    from itcj2.apps.titulatec.services.import_service import ImportService

    seed_phase_defs()
    cohort = make_cohort(status="open")
    user = make_user(control_number="99770001", username="99770001")
    user.password_hash = None
    db_session.flush()

    ImportService.import_rows(
        db_session, cohort,
        [{"control_number": "99770001", "full_name": "INVENTADA ALUMNA",
          "email": None, "program_id": None, "modality_id": None}],
        actor_id=None, source="self_service", repair_credentials=False,
    )

    db_session.refresh(user)
    assert not verify_nip("99770001", user.password_hash)


def test_import_rows_conserva_el_comportamiento_de_hoy_por_omision(
    db_session, make_cohort, make_user, seed_phase_defs, titulatec_app,
):
    """Los dos parámetros nacen con el valor de hoy: `admin.py` no se toca."""
    from itcj2.core.utils.security import verify_nip
    from itcj2.apps.titulatec.services.import_service import ImportService

    seed_phase_defs()
    cohort = make_cohort(status="open")
    user = make_user(control_number="99770002", username="99770002")
    user.password_hash = None
    db_session.flush()

    summary = ImportService.import_rows(
        db_session, cohort,
        [{"control_number": "99770002", "full_name": "INVENTADA ALUMNA",
          "email": None, "program_id": None, "modality_id": None}],
        actor_id=None, source="csv",
    )

    db_session.refresh(user)
    assert verify_nip("99770002", user.password_hash)
    assert summary["repaired_users"] == 1


# ---------------------------------------------------------------------------
# Camino feliz: solo `approved` convierte
# ---------------------------------------------------------------------------
def test_abrir_la_liga_inscribe_a_la_cuenta_y_muestra_el_folio(
    client, db_session, make_cohort, make_user, seed_phase_defs, titulatec_app,
    correo_falso,
):
    from itcj2.core.models.user_app_role import UserAppRole
    from itcj2.apps.titulatec.models import ProcessEvent, TitulationProcess

    seed_phase_defs()
    cohort = make_cohort(status="open")
    cuenta = _cuenta(make_user, db_session, "99770010")
    req, token = _aprobada(db_session, cohort, control="99770010")
    client.cookies.clear()

    resp = client.get(f"{VERIFY_URL}?t={token}", follow_redirects=False)

    assert resp.status_code == 200, resp.text[:400]
    db_session.refresh(req)
    assert req.status == "converted"
    proc = db_session.get(TitulationProcess, req.converted_process_id)
    assert proc.student_id == cuenta.id and proc.cohort_id == cohort.id

    assert 'data-tt-notice="verified"' in resp.text
    texto = _plano(resp.text)
    assert TARJETA_LISTO in texto
    assert (f"Tu folio es {proc.folio}. Entra a TitulaTec con tu número de control y "
            "tu NIP de siempre. Si no lo recuerdas, acude a Servicios Escolares.") in texto

    evento = (db_session.query(ProcessEvent)
              .filter_by(process_id=proc.id, event_type="enrollment_self_service").one())
    assert evento.payload["activation"] == "personal_email_link"
    assert evento.payload["request_id"] == req.id
    assert evento.payload["folio"] == proc.folio
    assert (db_session.query(UserAppRole)
            .filter_by(user_id=cuenta.id, app_id=titulatec_app.id).first()) is not None, (
        "abrir la liga debe dar el rol de la app, no solo el proceso")


def test_abrir_la_liga_deja_a_la_cuenta_como_graduate_y_tira_el_cache_tras_el_commit(
    db_session, make_cohort, make_user, seed_phase_defs, titulatec_app, correo_falso,
    monkeypatch,
):
    """`_convert` pasa por `import_rows(commit=False)`: la cuenta existente queda
    `graduate` (alias legado incluido) y pierde `student`. `verify()` es dueño de
    la transacción, así que el caché de authz lo tira él tras su commit."""
    from itcj2.core.models.app import App
    from itcj2.core.models.role import Role
    from itcj2.core.models.user_app_role import UserAppRole
    from itcj2.core.services import authz_cache
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )

    seed_phase_defs()
    cohort = make_cohort(status="open")
    cuenta = _cuenta(make_user, db_session, "99770090")
    student = db_session.query(Role).filter_by(name="student").one()
    cuenta.role_id = student.id
    db_session.add(UserAppRole(user_id=cuenta.id, app_id=titulatec_app.id,
                               role_id=student.id))
    db_session.flush()
    _req, token = _aprobada(db_session, cohort, control="99770090")

    orden = []
    commit_real = db_session.commit

    def _commit():
        orden.append("commit")
        return commit_real()

    monkeypatch.setattr(db_session, "commit", _commit)
    monkeypatch.setattr(authz_cache, "invalidate_user_app",
                        lambda user_id, app_key: orden.append((user_id, app_key)))

    _, outcome = EnrollmentRequestService.verify(db_session, token)

    assert outcome == "converted"
    db_session.refresh(cuenta)
    assert cuenta.role_id == db_session.query(Role.id).filter_by(name="graduate").scalar()
    roles = {(k, n) for k, n in (db_session.query(App.key, Role.name)
                                 .join(UserAppRole, UserAppRole.app_id == App.id)
                                 .join(Role, Role.id == UserAppRole.role_id)
                                 .filter(UserAppRole.user_id == cuenta.id).all())}
    assert roles == {("itcj", "graduate"), ("titulatec", "graduate")}
    invalidaciones = [i for i, x in enumerate(orden) if isinstance(x, tuple)]
    assert invalidaciones and min(invalidaciones) > orden.index("commit"), orden
    assert {orden[i] for i in invalidaciones} == {(cuenta.id, "itcj"),
                                                  (cuenta.id, "titulatec")}


def test_la_liga_es_idempotente(
    client, db_session, make_cohort, make_user, seed_phase_defs, titulatec_app,
    correo_falso,
):
    """Outlook Safe Links pre-abre la liga: la segunda visita NO puede dar error
    ni repetir efectos (segundo proceso, segundo evento, segundo aviso)."""
    from itcj2.apps.titulatec.models import ProcessEvent

    seed_phase_defs()
    cohort = make_cohort(status="open")
    cuenta = _cuenta(make_user, db_session, "99770011")
    req, token = _aprobada(db_session, cohort, control="99770011")
    client.cookies.clear()

    r1 = client.get(f"{VERIFY_URL}?t={token}", follow_redirects=False)
    r2 = client.get(f"{VERIFY_URL}?t={token}", follow_redirects=False)

    assert r1.status_code == r2.status_code == 200
    assert r1.content == r2.content
    procesos = _procesos(db_session, cuenta, cohort)
    assert len(procesos) == 1
    assert (db_session.query(ProcessEvent)
            .filter_by(process_id=procesos[0].id, event_type="enrollment_self_service")
            .count()) == 1
    assert len(correo_falso) == 1, "un solo aviso de folio aunque la liga se abra dos veces"


def test_dos_llamadas_seguidas_a_verify_devuelven_converted_y_already_converted(
    db_session, make_cohort, make_user, seed_phase_defs, titulatec_app, correo_falso,
):
    """Idempotencia AL NIVEL DEL SERVICIO. No es concurrencia real (misma sesión):
    la concurrencia la sostiene el lock + refresh que fija el test estructural."""
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )

    seed_phase_defs()
    cohort = make_cohort(status="open")
    _cuenta(make_user, db_session, "99770012")
    req, token = _aprobada(db_session, cohort, control="99770012")

    _, outcome1 = EnrollmentRequestService.verify(db_session, token)
    sellado = req.verified_at
    _, outcome2 = EnrollmentRequestService.verify(db_session, token)

    assert (outcome1, outcome2) == ("converted", "already_converted")
    assert sellado is not None, "la primera apertura sella `verified_at`"
    db_session.refresh(req)
    assert req.verified_at == sellado, "la segunda apertura no lo mueve"


@pytest.mark.parametrize("status", ["pending_review", "rejected", "unverified", "verified"])
def test_una_liga_de_una_solicitud_no_aprobada_es_invalida_y_no_toca_nada(
    db_session, make_cohort, make_user, seed_phase_defs, titulatec_app, correo_falso,
    status,
):
    """Regla 1: nadie obtiene acceso si no es por la liga de una solicitud
    APROBADA. Los estados legado traen token de verificación del flujo anterior:
    tampoco convierten."""
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )

    seed_phase_defs()
    cohort = make_cohort(status="open")
    cuenta = _cuenta(make_user, db_session, "99770013")
    req, token = _aprobada(db_session, cohort, control="99770013", status=status)

    _, outcome = EnrollmentRequestService.verify(db_session, token)

    assert outcome == "invalid"
    db_session.refresh(req)
    assert req.status == status
    assert req.verified_at is None
    assert _procesos(db_session, cuenta, cohort) == []
    assert correo_falso == []


def test_la_tarjeta_de_una_liga_en_revision_es_la_de_invalida(
    client, db_session, make_cohort, make_user,
):
    cohort = make_cohort(status="open")
    _cuenta(make_user, db_session, "99770014")
    _req, token = _aprobada(db_session, cohort, control="99770014", status="pending_review")
    client.cookies.clear()

    resp = client.get(f"{VERIFY_URL}?t={token}", follow_redirects=False)

    assert resp.status_code == 200, resp.text[:400]
    assert 'data-tt-notice="invalid"' in resp.text
    assert TARJETA_INVALIDA in resp.text


def test_token_inexistente_muestra_la_tarjeta_de_error(client):
    client.cookies.clear()

    resp = client.get(f"{VERIFY_URL}?t=no-existe-este-token", follow_redirects=False)

    assert resp.status_code == 200, resp.text[:400]
    assert TARJETA_INVALIDA in resp.text


def test_una_liga_vencida_no_convierte_y_la_tarjeta_pide_reenvio(
    client, db_session, make_cohort, make_user, seed_phase_defs, titulatec_app,
    correo_falso,
):
    seed_phase_defs()
    cohort = make_cohort(status="open")
    cuenta = _cuenta(make_user, db_session, "99770015")
    req, token = _aprobada(db_session, cohort, control="99770015",
                           vence=-timedelta(hours=1))
    client.cookies.clear()

    resp = client.get(f"{VERIFY_URL}?t={token}", follow_redirects=False)

    assert resp.status_code == 200, resp.text[:400]
    assert 'data-tt-notice="expired"' in resp.text
    for texto in TARJETA_VENCIDA:
        assert texto in resp.text
    db_session.refresh(req)
    assert req.status == "approved"
    assert req.verified_at is not None, (
        "la apertura queda sellada: la bandeja muestra que la persona sí intentó")
    assert _procesos(db_session, cuenta, cohort) == []
    assert correo_falso == []


# ---------------------------------------------------------------------------
# Revalidaciones: vuelve a revisión con la nota, sin nada a medias
# ---------------------------------------------------------------------------
def _cerrar_convocatoria(db_session, ctx):
    ctx["cohort"].status = "closed"
    db_session.flush()


def _proceso_en_otra(db_session, ctx):
    otra = ctx["make_cohort"](status="closed")
    ctx["make_process"](ctx["cuenta"], cohort=otra, status="active")


def _quitar_contrasena(db_session, ctx):
    ctx["cuenta"].password_hash = None
    db_session.flush()


def _nombre_vacio(db_session, ctx):
    ctx["req"].first_name = ""
    ctx["req"].last_name = ""
    db_session.flush()


REVALIDACIONES = [
    ("ventana-cerrada", _cerrar_convocatoria,
     "La convocatoria estaba cerrada cuando se abrió la liga de activación."),
    ("proceso-en-otra-convocatoria", _proceso_en_otra,
     "Esa persona ya tiene un proceso en otra convocatoria."),
    ("sin-contrasena", _quitar_contrasena,
     "Esa cuenta no tiene contraseña; dala de alta desde la convocatoria y rechaza "
     "esta solicitud."),
    ("datos-sin-formato", _nombre_vacio,
     "El número de control o el nombre no tienen formato válido."),
]


@pytest.mark.parametrize("romper,nota", [(r, n) for _i, r, n in REVALIDACIONES],
                         ids=[i for i, _r, _n in REVALIDACIONES])
def test_si_una_revalidacion_falla_la_solicitud_vuelve_a_revision_con_la_nota(
    client, db_session, make_cohort, make_user, make_process, seed_phase_defs,
    titulatec_app, correo_falso, romper, nota,
):
    seed_phase_defs()
    cohort = make_cohort(status="open")
    cuenta = _cuenta(make_user, db_session, "99770020")
    req, token = _aprobada(db_session, cohort, control="99770020")
    romper(db_session, {"cohort": cohort, "cuenta": cuenta, "req": req,
                        "make_cohort": make_cohort, "make_process": make_process})
    client.cookies.clear()

    resp = client.get(f"{VERIFY_URL}?t={token}", follow_redirects=False)

    assert resp.status_code == 200, resp.text[:400]
    assert 'data-tt-notice="pending"' in resp.text
    for texto in TARJETA_REVISION:
        assert texto in resp.text
    assert nota not in resp.text, "la nota es para Servicios Escolares, no para la pantalla"

    db_session.refresh(req)
    assert req.status == "pending_review"
    assert req.review_note == nota
    assert req.verified_at is not None
    assert req.verify_token_hash is None, "la liga de una solicitud devuelta queda muerta"
    assert _procesos(db_session, cuenta, cohort) == []
    assert correo_falso == []

    otra_vez = client.get(f"{VERIFY_URL}?t={token}", follow_redirects=False)
    assert TARJETA_INVALIDA in otra_vez.text


def test_sin_cuenta_en_la_bd_la_liga_devuelve_la_solicitud_a_revision(
    db_session, make_cohort, seed_phase_defs, titulatec_app, correo_falso,
):
    """`_convert` jamás crea cuentas: si la cuenta desapareció, la bandeja decide."""
    from itcj2.core.models.user import User
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )

    seed_phase_defs()
    cohort = make_cohort(status="open")
    req, token = _aprobada(db_session, cohort, control="99770021")

    _, outcome = EnrollmentRequestService.verify(db_session, token)

    assert outcome == "pending_review"
    assert req.review_note == "La cuenta de ese número de control ya no existe."
    assert db_session.query(User).filter_by(control_number="99770021").first() is None


def test_si_import_rows_no_crea_el_proceso_no_queda_el_rol_a_medias(
    db_session, make_cohort, make_user, make_role, seed_phase_defs, titulatec_app,
    correo_falso, monkeypatch,
):
    """La trampa de la revisión final (§3): `import_rows(commit=False)` ya hizo
    `flush` de lo suyo cuando `_convert` descubre que no hay proceso. Si `verify`
    commiteara ahí, la cuenta quedaría con el rol de la app y sin proceso. Y si
    hiciera `rollback()` a secas, perdería también la nota y `verified_at`.
    """
    from itcj2.core.models.user_app_role import UserAppRole
    from itcj2.apps.titulatec.services import import_service
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )

    seed_phase_defs()
    cohort = make_cohort(status="open")
    cuenta = _cuenta(make_user, db_session, "99770022")
    rol = make_role("tt_test_rol_a_medias")
    req, token = _aprobada(db_session, cohort, control="99770022")

    def _import_sin_proceso(db, cohort_, rows, **kw):
        db.add(UserAppRole(user_id=cuenta.id, app_id=titulatec_app.id, role_id=rol.id))
        db.flush()
        return {"processes_created": 0}

    monkeypatch.setattr(import_service.ImportService, "import_rows",
                        staticmethod(_import_sin_proceso))

    _, outcome = EnrollmentRequestService.verify(db_session, token)

    assert outcome == "pending_review"
    assert (db_session.query(UserAppRole)
            .filter_by(user_id=cuenta.id, role_id=rol.id).first()) is None, (
        "quedó commiteado el rol de la app de una conversión que no terminó")
    db_session.refresh(req)
    assert req.status == "pending_review"
    assert req.review_note == ("No se pudo crear el proceso al abrir la liga; revisa "
                               "los datos de la solicitud.")
    assert req.verified_at is not None


def test_una_excepcion_dentro_de_convert_no_deja_nada_y_la_liga_sigue_viva(
    client, db_session, make_cohort, make_user, seed_phase_defs, titulatec_app,
    correo_falso, monkeypatch,
):
    """Un fallo inesperado NO es una revalidación: la ruta hace `rollback()`, la
    pantalla dice "no pudimos validar" y la solicitud sigue aprobada, así que la
    misma liga funciona en cuanto el fallo desaparece."""
    from itcj2.core.models.user_app_role import UserAppRole
    from itcj2.apps.titulatec.services import import_service

    seed_phase_defs()
    cohort = make_cohort(status="open")
    cuenta = _cuenta(make_user, db_session, "99770023")
    req, token = _aprobada(db_session, cohort, control="99770023")
    # La ruta hace `db.rollback()`: sin este checkpoint se llevaría también los
    # datos del fixture (y en dev "resucitarían" filas reales).
    db_session.commit()

    original = import_service.ImportService.import_rows

    def _revienta_despues(db, cohort_, rows, **kw):
        original(db, cohort_, rows, **kw)
        raise RuntimeError("fallo simulado despues de import_rows")

    monkeypatch.setattr(import_service.ImportService, "import_rows",
                        staticmethod(_revienta_despues))
    client.cookies.clear()

    resp = client.get(f"{VERIFY_URL}?t={token}", follow_redirects=False)

    assert resp.status_code == 200, resp.text[:400]
    assert TARJETA_INVALIDA in resp.text
    db_session.refresh(req)
    assert req.status == "approved"
    assert _procesos(db_session, cuenta, cohort) == []
    assert (db_session.query(UserAppRole)
            .filter_by(user_id=cuenta.id, app_id=titulatec_app.id).first()) is None

    monkeypatch.setattr(import_service.ImportService, "import_rows", staticmethod(original))
    otra_vez = client.get(f"{VERIFY_URL}?t={token}", follow_redirects=False)
    assert TARJETA_LISTO in otra_vez.text


# ---------------------------------------------------------------------------
# Efectos colaterales: aviso al institucional, nada al perfil, nada de contacto
# ---------------------------------------------------------------------------
def test_el_aviso_de_folio_va_al_institucional_despues_del_commit(
    db_session, make_cohort, make_user, seed_phase_defs, titulatec_app, correo_falso,
    monkeypatch,
):
    from itcj2.core.utils.email_tools import student_email
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )

    seed_phase_defs()
    cohort = make_cohort(status="open")
    cuenta = _cuenta(make_user, db_session, "99770030")
    req, token = _aprobada(db_session, cohort, control="99770030",
                           email="otro.personal@example.invalid")

    orden = []
    commit_real = db_session.commit

    def _commit():
        orden.append("commit")
        return commit_real()

    monkeypatch.setattr(db_session, "commit", _commit)
    monkeypatch.setattr(
        "itcj2.core.utils.msgraph_mail.graph_send_mail",
        lambda token_, subject, html, to_list, save_to_sent=True: (
            orden.append("correo"), correo_falso.append((subject, list(to_list), html)),
            type("R", (), {"status_code": 202, "text": ""})())[-1])

    _, outcome = EnrollmentRequestService.verify(db_session, token)

    assert outcome == "converted"
    assert orden == ["commit", "correo"], "el aviso salió antes de commitear la conversión"
    (_asunto, destinatarios, html), = correo_falso
    assert destinatarios == [student_email(cuenta)], (
        "el aviso es la alarma: va al buzón institucional, nunca al que se tecleó")
    assert req.contact_email not in destinatarios
    proc = _procesos(db_session, cuenta, cohort)[0]
    assert proc.folio in html


def test_abrir_la_liga_no_toca_el_perfil_ni_emite_liga_de_contacto(
    db_session, make_cohort, make_user, seed_phase_defs, titulatec_app, correo_falso,
    monkeypatch,
):
    from itcj2.core.models.student_profile import StudentProfile
    from itcj2.core.services import student_profile_service as sps
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )

    def _prohibido(*a, **k):
        raise AssertionError("abrir la liga escribió en core_student_profile")

    monkeypatch.setattr(sps.StudentProfileService, "set_fields", staticmethod(_prohibido))
    monkeypatch.setattr(sps.StudentProfileService, "mark_contact_verified",
                        staticmethod(_prohibido))

    seed_phase_defs()
    cohort = make_cohort(status="open")
    cuenta = _cuenta(make_user, db_session, "99770031")
    req, token = _aprobada(db_session, cohort, control="99770031")

    _, outcome = EnrollmentRequestService.verify(db_session, token)

    assert outcome == "converted"
    assert db_session.get(StudentProfile, cuenta.id) is None
    assert req.contact_token_hash is None
    assert req.contact_expires_at is None
    assert not [a for a, _d, _h in correo_falso if "contacto" in a.lower()]


# ---------------------------------------------------------------------------
# Invariantes estructurales (no detectables por comportamiento)
# ---------------------------------------------------------------------------
def _cuerpo_sin_docstring(func):
    import inspect

    src = inspect.getsource(func)
    _, _, cuerpo = src.partition('"""')
    _, _, cuerpo = cuerpo.partition('"""')
    return cuerpo


def test_verify_usa_comparacion_en_tiempo_constante():
    """E7: el token es una credencial al portador. Un `==` de Python sale en el
    primer byte distinto; `hmac.compare_digest` tarda lo mismo acierte o falle.
    Mutarlo a `==` no cambia ningún resultado observable, así que se lee la
    fuente."""
    import inspect

    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )

    src = inspect.getsource(EnrollmentRequestService.verify)
    assert "hmac.compare_digest(" in src
    # Una sola comparación "== digest": la del filtro SQLAlchemy (expresión SQL).
    assert src.count("== digest") == 1


def test_verify_toma_lock_advisory_por_solicitud_y_refresca_antes_de_leer_status():
    """Bajo READ COMMITTED, quien esperó el lock puede seguir con el `req.status`
    de antes de esperarlo: sin el refresh, el lock no sirve de nada."""
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )

    cuerpo = _cuerpo_sin_docstring(EnrollmentRequestService.verify)
    assert "pg_advisory_xact_lock" in cuerpo
    assert "db.refresh(req)" in cuerpo
    lock_pos = cuerpo.index("pg_advisory_xact_lock")
    refresh_pos = cuerpo.index("db.refresh(req)")
    status_pos = cuerpo.index('req.status == "converted"')
    assert lock_pos < refresh_pos < status_pos


def test_el_token_nunca_aparece_en_los_logs(
    client, db_session, make_cohort, make_user, seed_phase_defs, titulatec_app,
    correo_falso, caplog,
):
    """Es una credencial al portador que viaja en la URL. Se acota a los loggers
    propios (`itcj2.*`): `httpx` loguea la URL completa en su transporte."""
    import logging

    seed_phase_defs()
    cohort = make_cohort(status="open")
    _cuenta(make_user, db_session, "99770050")
    _req, token = _aprobada(db_session, cohort, control="99770050")
    client.cookies.clear()

    with caplog.at_level(logging.DEBUG):
        client.get(f"{VERIFY_URL}?t={token}", follow_redirects=False)
        client.get(f"{VERIFY_URL}?t={token}", follow_redirects=False)

    propios = [r for r in caplog.records if r.name.startswith("itcj2")]
    assert propios, "el request no pasó por ningún logger de itcj2 — el test no prueba nada"
    for record in propios:
        assert token not in record.getMessage()
        if record.exc_text:
            assert token not in record.exc_text


def test_un_error_inesperado_al_verificar_no_produce_500(client, monkeypatch):
    """Esta ruta la abre un clic real de correo, sin htmx: un 500 aquí es la
    pantalla que ve la persona."""
    from itcj2.apps.titulatec.services import enrollment_request_service as svc_mod

    def _boom(db, token):
        raise RuntimeError("fallo inesperado simulado")

    monkeypatch.setattr(svc_mod.EnrollmentRequestService, "verify", staticmethod(_boom))
    client.cookies.clear()

    resp = client.get(f"{VERIFY_URL}?t=cualquiera", follow_redirects=False)

    assert resp.status_code == 200, resp.text[:400]
    assert TARJETA_INVALIDA in resp.text


def test_convert_directo_dos_veces_sigue_sin_guarda_propia_por_diseno(
    db_session, make_cohort, make_user, seed_phase_defs, titulatec_app,
):
    """Documenta el LÍMITE de la guarda: vive en `verify()` (lock + refresh), no
    dentro de `_convert()`, que es privado. Llamarlo directo dos veces duplica
    el evento; en producción ningún camino llega a `_convert` sin `verify()`."""
    from itcj2.apps.titulatec.models import ProcessEvent
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )

    seed_phase_defs()
    cohort = make_cohort(status="open")
    cuenta = _cuenta(make_user, db_session, "99770081")
    req, _ = _aprobada(db_session, cohort, control="99770081")

    ok1, _ = EnrollmentRequestService._convert(db_session, req)
    ok2, _ = EnrollmentRequestService._convert(db_session, req)

    assert ok1 is True and ok2 is True
    procesos = _procesos(db_session, cuenta, cohort)
    assert len(procesos) == 1, "import_rows ya es idempotente por (student_id, cohort_id)"
    assert (db_session.query(ProcessEvent)
            .filter_by(process_id=procesos[0].id, event_type="enrollment_self_service")
            .count()) == 2
