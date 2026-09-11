"""Verificación de la liga de inscripción y conversión a proceso (§6.9).

`import_rows` COMMITEA POR SU CUENTA POR OMISIÓN (`import_service.py:558-561`,
parámetro `commit: bool = True`), así que todo lo que pueda invalidar la
conversión se revisa ANTES de llamarlo, y lo que se comprueba DESPUÉS es la
existencia del proceso, nunca un contador.

RONDA DE ARREGLOS 1, IMPORTANT 1: la llamada de `_convert`
(`enrollment_request_service.py`) SÍ pasa `commit=False` -corregido tras la
revisión, que encontró que faltaba y que sin él un fallo real después de
`import_rows` dejaba un `User`/`TitulationProcess` huérfanos y commiteados.
`_convert` es entonces dueño único de su transacción; el `import_rows` interno
del importador CSV admin (`pages/admin.py`) sigue commiteando por su cuenta,
sin cambios.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta


def _solo_esta_convocatoria(db_session, cohort):
    """Deja `cohort` como la ÚNICA abierta (ver test_enrollment_public.py)."""
    from itcj2.apps.titulatec.models import Cohort
    (db_session.query(Cohort)
     .filter(Cohort.id != cohort.id)
     .update({Cohort.status: "closed"}, synchronize_session=False))
    db_session.flush()


def _make_req(db_session, cohort, *, control, kind, status="unverified", **kw):
    """Solicitud + su token en claro. Devuelve `(req, token)`.

    Se construye a mano en vez de llamar a `create()` para que la prueba tenga el
    texto claro del token sin depender de Redis.
    """
    from itcj2.apps.titulatec.models import EnrollmentRequest
    from itcj2.apps.titulatec.services.enrollment_request_service import VERIFY_TTL_HOURS

    token = secrets.token_urlsafe(32)
    row = EnrollmentRequest(
        cohort_id=cohort.id,
        control_number=control,
        first_name="ALUMNA", last_name="INVENTADA", middle_name=None,
        program_id=None, program_text=None,
        phone="6561234567", contact_email="alguien@example.invalid",
        has_efirma=False, kind=kind, status=status,
        verify_token_hash=hashlib.sha256(token.encode("utf-8")).hexdigest(),
        verify_expires_at=datetime.now() + timedelta(hours=VERIFY_TTL_HOURS),
        verify_sent_at=datetime.now(), verify_send_count=1,
        verify_sent_to="alguien@example.invalid",
    )
    for k, v in kw.items():
        setattr(row, k, v)
    db_session.add(row)
    db_session.flush()
    return row, token


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
    """Los dos parámetros nuevos nacen con el valor de hoy: `admin.py` no se toca."""
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


def test_conocido_verifica_y_queda_inscrito_con_folio(
    client, db_session, make_cohort, make_student, seed_phase_defs, titulatec_app,
):
    seed_phase_defs()
    cohort = make_cohort(status="open")
    _solo_esta_convocatoria(db_session, cohort)
    student = make_student(control_number="99770010")
    student.password_hash = "hash-que-ya-existe"
    db_session.flush()
    req, token = _make_req(db_session, cohort, control="99770010", kind="known")
    client.cookies.clear()

    resp = client.get(f"/titulatec/inscripcion/verificar?t={token}",
                      follow_redirects=False)

    assert resp.status_code == 200, resp.text[:400]
    db_session.refresh(req)
    assert req.status == "converted"
    assert req.converted_process_id is not None

    from itcj2.apps.titulatec.models import TitulationProcess
    proc = db_session.get(TitulationProcess, req.converted_process_id)
    assert proc.student_id == student.id
    assert proc.cohort_id == cohort.id
    assert proc.folio in resp.text


def test_token_re_presentado_re_renderiza_la_misma_tarjeta_de_exito(
    client, db_session, make_cohort, make_student, seed_phase_defs, titulatec_app,
):
    """Outlook Safe Links prefetchea la liga: la 2a visita NO puede dar error."""
    seed_phase_defs()
    cohort = make_cohort(status="open")
    _solo_esta_convocatoria(db_session, cohort)
    student = make_student(control_number="99770011")
    student.password_hash = "hash-que-ya-existe"
    db_session.flush()
    req, token = _make_req(db_session, cohort, control="99770011", kind="known")
    client.cookies.clear()

    r1 = client.get(f"/titulatec/inscripcion/verificar?t={token}", follow_redirects=False)
    r2 = client.get(f"/titulatec/inscripcion/verificar?t={token}", follow_redirects=False)

    assert r1.status_code == 200 and r2.status_code == 200
    assert r1.content == r2.content


def test_desconocido_cae_a_pending_review_y_su_token_se_reconoce_despues(
    client, db_session, make_cohort, seed_phase_defs, titulatec_app,
):
    seed_phase_defs()
    cohort = make_cohort(status="open")
    _solo_esta_convocatoria(db_session, cohort)
    req, token = _make_req(db_session, cohort, control="99770012", kind="unknown")
    client.cookies.clear()

    r1 = client.get(f"/titulatec/inscripcion/verificar?t={token}", follow_redirects=False)
    r2 = client.get(f"/titulatec/inscripcion/verificar?t={token}", follow_redirects=False)

    assert r1.status_code == 200
    assert "Servicios Escolares" in r1.text
    assert r1.content == r2.content
    db_session.refresh(req)
    assert req.status == "pending_review"
    assert req.converted_process_id is None


def test_token_inexistente_muestra_la_tarjeta_de_error(client, db_session, make_cohort):
    cohort = make_cohort(status="open")
    _solo_esta_convocatoria(db_session, cohort)
    client.cookies.clear()

    resp = client.get("/titulatec/inscripcion/verificar?t=no-existe-este-token",
                      follow_redirects=False)

    assert resp.status_code == 200, resp.text[:400]
    assert "no pudimos validar" in resp.text.lower()


def test_conocido_sin_password_hash_cae_a_revision_y_no_queda_con_su_control(
    client, db_session, make_cohort, make_student, seed_phase_defs, titulatec_app,
):
    """Criterio 11. `import_rows` le pondría el control de contraseña.

    Ojo con el orden de argumentos: `verify_nip(nip, nip_hash)`.
    """
    from itcj2.core.utils.security import verify_nip

    seed_phase_defs()
    cohort = make_cohort(status="open")
    _solo_esta_convocatoria(db_session, cohort)
    student = make_student(control_number="99770020")
    student.password_hash = None
    db_session.flush()
    req, token = _make_req(db_session, cohort, control="99770020", kind="known")
    client.cookies.clear()

    resp = client.get(f"/titulatec/inscripcion/verificar?t={token}",
                      follow_redirects=False)

    assert resp.status_code == 200, resp.text[:400]
    db_session.refresh(req)
    assert req.status == "pending_review"
    assert req.converted_process_id is None

    db_session.refresh(student)
    assert not verify_nip("99770020", student.password_hash)

    from itcj2.apps.titulatec.models import TitulationProcess
    assert db_session.query(TitulationProcess).filter_by(
        student_id=student.id, cohort_id=cohort.id).first() is None


def test_proceso_preexistente_de_un_csv_se_trata_como_conversion_exitosa(
    client, db_session, make_cohort, make_student, make_process,
    seed_phase_defs, titulatec_app,
):
    """La carrera con el CSV: el personal importó mientras la persona no daba clic.

    No se ramifica sobre `processes_created` (§6.9): se busca el proceso por
    `(student_id, cohort_id)` y, si existe, la conversión es exitosa.
    """
    seed_phase_defs()
    cohort = make_cohort(status="open")
    _solo_esta_convocatoria(db_session, cohort)
    student = make_student(control_number="99770021")
    student.password_hash = "hash-que-ya-existe"
    db_session.flush()
    req, token = _make_req(db_session, cohort, control="99770021", kind="known")
    proc = make_process(student, cohort=cohort)      # lo creó el CSV, antes del clic
    client.cookies.clear()

    resp = client.get(f"/titulatec/inscripcion/verificar?t={token}",
                      follow_redirects=False)

    assert resp.status_code == 200, resp.text[:400]
    assert "ya estás inscrito" in resp.text
    assert proc.folio in resp.text
    db_session.refresh(req)
    assert req.status == "converted"
    assert req.converted_process_id == proc.id

    from itcj2.apps.titulatec.models import ProcessEvent
    ev = (db_session.query(ProcessEvent)
          .filter_by(process_id=proc.id, event_type="enrollment_self_service")
          .first())
    assert ev is not None
    assert ev.payload["preexisting_process"] is True


# ---------------------------------------------------------------------------
# Cobertura propia de esta tarea (más allá de lo que trae el brief), pensada
# para cerrar huecos que la auto-mutación expuso. Ver task-20-report.md.
# ---------------------------------------------------------------------------

def test_token_vencido_no_convierte_y_la_tarjeta_dice_que_vencio(
    client, db_session, make_cohort, make_student, seed_phase_defs, titulatec_app,
):
    """`verify` declara 6 salidas y `expired` es una de ellas — el brief no la
    probaba (ninguno de sus 6 tests construye un token vencido). Sin este test,
    "que un token expirado se acepte" (auto-mutación) no muere en nada.
    """
    seed_phase_defs()
    cohort = make_cohort(status="open")
    _solo_esta_convocatoria(db_session, cohort)
    student = make_student(control_number="99770030")
    student.password_hash = "hash-que-ya-existe"
    db_session.flush()
    req, token = _make_req(db_session, cohort, control="99770030", kind="known")
    req.verify_expires_at = datetime.now() - timedelta(hours=1)
    db_session.flush()
    client.cookies.clear()

    resp = client.get(f"/titulatec/inscripcion/verificar?t={token}",
                      follow_redirects=False)

    assert resp.status_code == 200, resp.text[:400]
    assert "venció" in resp.text.lower()
    db_session.refresh(req)
    assert req.status == "unverified"
    assert req.converted_process_id is None

    from itcj2.apps.titulatec.models import TitulationProcess
    assert db_session.query(TitulationProcess).filter_by(
        student_id=student.id, cohort_id=cohort.id).first() is None


def test_dos_verificaciones_seguidas_no_duplican_proceso_ni_evento_ni_correo(
    client, db_session, make_cohort, make_student, seed_phase_defs, titulatec_app,
):
    """Pulsar la liga dos veces no puede crear un segundo proceso — ni, más sutil,
    volver a ejecutar `_convert` por dentro con efectos secundarios duplicados
    (un segundo `ProcessEvent`, un segundo correo). El único test del brief que
    repite la llamada (`test_token_re_presentado_...`) solo compara el HTML
    byte a byte, y ese байт a byte NO cambia aunque `_convert` se re-ejecute
    completo la segunda vez (el folio es el mismo) — así que ese test por sí
    solo no basta para probar que el atajo `already_converted` existe y hace su
    trabajo. Este test mira la BD, no el HTML.
    """
    seed_phase_defs()
    cohort = make_cohort(status="open")
    _solo_esta_convocatoria(db_session, cohort)
    student = make_student(control_number="99770040")
    student.password_hash = "hash-que-ya-existe"
    db_session.flush()
    req, token = _make_req(db_session, cohort, control="99770040", kind="known")
    client.cookies.clear()

    r1 = client.get(f"/titulatec/inscripcion/verificar?t={token}", follow_redirects=False)
    r2 = client.get(f"/titulatec/inscripcion/verificar?t={token}", follow_redirects=False)
    assert r1.status_code == 200 and r2.status_code == 200

    from itcj2.apps.titulatec.models import ProcessEvent, TitulationProcess
    procs = (db_session.query(TitulationProcess)
             .filter_by(student_id=student.id, cohort_id=cohort.id).all())
    assert len(procs) == 1, "la segunda pulsación no puede crear un segundo proceso"

    events = (db_session.query(ProcessEvent)
              .filter_by(process_id=procs[0].id, event_type="enrollment_self_service")
              .all())
    assert len(events) == 1, (
        "el atajo already_converted debe evitar una segunda pasada por _convert")


def test_verify_usa_comparacion_en_tiempo_constante(db_session):
    """E7: el token es una credencial al portador. Un `==` de Python sale en el
    primer byte distinto y el tiempo de respuesta filtra cuántos bytes acertó
    quien lo intenta; `hmac.compare_digest` tarda lo mismo acierte o falle.

    Mutar esto a `==` NO cambia ningún resultado observable por un assert
    funcional -un comparador en tiempo constante calcula la MISMA igualdad que
    `==`, solo que sin filtrarla por temporización-, así que ningún test de
    comportamiento puede detectar esta regresión. La única forma de cerrarla es
    leer la fuente, igual que hacen ya `test_scope_guard.py` /
    `test_admin_nav_swap.py` en esta misma suite para otras invariantes
    estructurales.
    """
    import inspect

    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )

    src = inspect.getsource(EnrollmentRequestService.verify)
    assert "hmac.compare_digest(" in src
    # Debe haber UNA sola comparación "== digest" en todo el método: la del
    # filtro SQLAlchemy (`EnrollmentRequest.verify_token_hash == digest`, que
    # arma una expresión SQL, no una comparación de Python). Si la decisiva
    # también quedara como `==`, este conteo sube a 2.
    assert src.count("== digest") == 1, (
        "debe haber una sola comparación '== digest' (el filtro SQLAlchemy); "
        "la decisiva tiene que ser hmac.compare_digest, no ==")


def test_el_token_nunca_aparece_en_los_logs(
    client, db_session, make_cohort, make_student, seed_phase_defs, titulatec_app, caplog,
):
    """Es una credencial al portador que viaja en la URL: ni en un
    `logger.info`, ni en un mensaje de excepción, ni en la traza de un
    `logger.exception`. Se ejercita el camino más rico (conversión exitosa,
    que además dispara el helper de correo) porque es el que más módulos toca.

    Se acota a los loggers propios de la app (`itcj2.*`): el cliente HTTP de
    pruebas (`httpx`) loguea la URL completa de cada request -token incluido-
    en su propio logger de transporte, y eso no tiene nada que ver con si n
    ITCJ2 loguea el token. En producción esa capa es nginx/uvicorn (logs de
    acceso), un riesgo ya aceptado por cualquier diseño "token en query string
    de un GET" y fuera del alcance de este módulo.
    """
    import logging

    seed_phase_defs()
    cohort = make_cohort(status="open")
    _solo_esta_convocatoria(db_session, cohort)
    student = make_student(control_number="99770050")
    student.password_hash = "hash-que-ya-existe"
    db_session.flush()
    req, token = _make_req(db_session, cohort, control="99770050", kind="known")
    client.cookies.clear()

    with caplog.at_level(logging.DEBUG):
        client.get(f"/titulatec/inscripcion/verificar?t={token}", follow_redirects=False)
        client.get(f"/titulatec/inscripcion/verificar?t={token}", follow_redirects=False)

    propios = [r for r in caplog.records if r.name.startswith("itcj2")]
    assert propios, "el request no pasó por ningún logger de itcj2 — el test no prueba nada"
    for record in propios:
        assert token not in record.getMessage(), (
            f"el token en claro salió en un log: {record.name}/{record.levelname}")
        if record.exc_text:
            assert token not in record.exc_text


def test_un_error_inesperado_al_verificar_no_produce_500(
    client, db_session, make_cohort, monkeypatch,
):
    """Ninguna entrada del visitante puede producir un 500 (docstring del
    módulo): esta ruta la abre un clic real de correo, sin htmx de por medio,
    así que un 500 no es un stack trace invisible en un log — es la pantalla
    que ve un egresado que ya demostró quién es. Se fuerza el fallo con
    monkeypatch porque no hay una entrada de formulario que lo dispare de forma
    determinista (a diferencia de `survey_submit`/`enroll_submit`, que sí lo
    prueban con datos).
    """
    from itcj2.apps.titulatec.services import enrollment_request_service as svc_mod

    def _boom(db, token):
        raise RuntimeError("fallo inesperado simulado")

    monkeypatch.setattr(svc_mod.EnrollmentRequestService, "verify", staticmethod(_boom))
    cohort = make_cohort(status="open")
    _solo_esta_convocatoria(db_session, cohort)
    client.cookies.clear()

    resp = client.get("/titulatec/inscripcion/verificar?t=cualquiera",
                      follow_redirects=False)

    assert resp.status_code == 200, resp.text[:400]


# ---------------------------------------------------------------------------
# Ronda de arreglos 1: Important 1 (falta commit=False) e Important 2 (falta
# guarda de idempotencia con lock). Ver task-20-report.md §6-7.
# ---------------------------------------------------------------------------

def test_fallo_entre_import_rows_y_el_commit_final_no_deja_usuario_ni_proceso_huerfanos(
    client, db_session, make_cohort, seed_phase_defs, titulatec_app, monkeypatch,
):
    """Important 1. Sin `commit=False` en la llamada a `import_rows` dentro de
    `_convert`, `import_rows` commitea por su cuenta ANTES de que `_convert`
    llegue a `req.status="converted"`. Un fallo real en lo único que queda
    entre ese commit y el final (`StudentProfileService.set_fields`, que aquí
    se rompe con monkeypatch) deja un `User` y un `TitulationProcess` REALES y
    COMMITEADOS, con la solicitud congelada en `status="verified"` -un estado
    fuera del contrato de seis salidas- y sin bandeja en `pages/admin.py` que
    lo exponga a Servicios Escolares. `_convert` DEBE ser dueño único de su
    transacción para que esto no pueda pasar.

    `kind="known"` con un `control_number` que NO corresponde a ningún `User`
    existente reproduce el caso exacto del revisor: `import_rows` es quien
    CREA al usuario dentro de esta misma llamada, así que la exposición es
    máxima (usuario Y proceso nuevos, no solo uno reparado).
    """
    import itcj2.core.services.student_profile_service as sps_mod

    def _boom(db, user_id, **fields):
        raise RuntimeError("mutación deliberada: fallo tras import_rows")

    monkeypatch.setattr(sps_mod.StudentProfileService, "set_fields", staticmethod(_boom))

    seed_phase_defs()
    cohort = make_cohort(status="open")
    _solo_esta_convocatoria(db_session, cohort)
    req, token = _make_req(db_session, cohort, control="99770070", kind="known")
    client.cookies.clear()

    resp = client.get(f"/titulatec/inscripcion/verificar?t={token}",
                      follow_redirects=False)

    assert resp.status_code == 200, resp.text[:400]

    from itcj2.core.models.user import User
    from itcj2.apps.titulatec.models import TitulationProcess
    assert db_session.query(User).filter_by(control_number="99770070").first() is None, (
        "no debe quedar un usuario huerfano si la conversion no termino")
    assert db_session.query(TitulationProcess).filter_by(cohort_id=cohort.id).count() == 0, (
        "no debe quedar un proceso huerfano si la conversion no termino")


def test_verify_toma_lock_advisory_por_solicitud_y_refresca_antes_de_leer_status():
    """Important 2, mitad estructural. El lock POR SÍ SOLO no basta: bajo READ
    COMMITTED, el `req` en memoria de una transacción que esperó el lock puede
    seguir mostrando el estado de ANTES de esperarlo -SQLAlchemy no relee un
    atributo solo porque el lock se liberó del lado de Postgres-. El
    `db.refresh(req)` DESPUÉS del lock y ANTES de la primera lectura de
    `req.status` es la mitad que hace que el lock sirva de algo. No es
    reproducible con una prueba de comportamiento (el arnés de pruebas no
    puede montar dos transacciones reales concurrentes sobre la misma fila de
    prueba, ver el reporte), así que se fija leyendo la fuente y el ORDEN de
    las tres piezas, mismo patrón que `test_verify_usa_comparacion_en_tiempo_constante`.
    """
    import inspect

    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )

    src = inspect.getsource(EnrollmentRequestService.verify)
    # El docstring del método MENCIONA estas mismas piezas en prosa (para
    # explicar el porqué) — buscar la primera aparición sin cortarlo encuentra
    # esa mención, no el código. Se corta el docstring partiendo en las dos
    # primeras comillas triples y se busca solo en lo que queda.
    _, _, cuerpo = src.partition('"""')
    _, _, cuerpo = cuerpo.partition('"""')
    assert "pg_advisory_xact_lock" in cuerpo
    assert "db.refresh(req)" in cuerpo
    lock_pos = cuerpo.index("pg_advisory_xact_lock")
    refresh_pos = cuerpo.index("db.refresh(req)")
    status_pos = cuerpo.index('req.status == "converted"')
    assert lock_pos < refresh_pos < status_pos, (
        "orden obligatorio: primero el lock, luego el refresh, y solo hasta "
        "entonces la primera lectura de req.status")


def test_dos_llamadas_seguidas_a_verify_no_duplican_evento_ni_correo(
    db_session, make_cohort, make_student, seed_phase_defs, titulatec_app,
):
    """Important 2, mitad de comportamiento — AL NIVEL DEL SERVICIO, sin pasar
    por `client` (que fuerza una sola sesión compartida entre las dos
    peticiones HTTP, y por eso no distingue "el gate de verify() funciona" de
    "es la misma sesión, claro que ve lo que ella misma escribió"). Esta
    prueba llama a `EnrollmentRequestService.verify` DIRECTO, dos veces
    seguidas, con el `db_session` del test.

    Aun así, ambas llamadas comparten esa MISMA sesión/transacción: NO es una
    prueba de concurrencia real (dos conexiones separadas compitiendo por el
    lock) — el arnés de pruebas no puede montarla, porque los datos de
    `db_session` viven en un SAVEPOINT que una segunda conexión de verdad no
    vería. Es la propiedad de idempotencia bajo re-invocación SECUENCIAL, que
    sí es reproducible al 100%. La concurrencia real queda como hueco
    declarado (ver el reporte) y se sostiene solo por el razonamiento sobre
    READ COMMITTED + lock transaccional + refresh, no por un test.
    """
    from itcj2.apps.titulatec.models import ProcessEvent, TitulationProcess
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )

    seed_phase_defs()
    cohort = make_cohort(status="open")
    _solo_esta_convocatoria(db_session, cohort)
    student = make_student(control_number="99770080")
    student.password_hash = "hash-que-ya-existe"
    db_session.flush()
    req, token = _make_req(db_session, cohort, control="99770080", kind="known")

    _, outcome1 = EnrollmentRequestService.verify(db_session, token)
    _, outcome2 = EnrollmentRequestService.verify(db_session, token)

    assert outcome1 == "converted"
    assert outcome2 == "already_converted"

    procs = (db_session.query(TitulationProcess)
             .filter_by(student_id=student.id, cohort_id=cohort.id).all())
    assert len(procs) == 1
    events = (db_session.query(ProcessEvent)
              .filter_by(process_id=procs[0].id, event_type="enrollment_self_service")
              .all())
    assert len(events) == 1


def test_convert_directo_dos_veces_sigue_sin_guarda_propia_por_diseno(
    db_session, make_cohort, make_student, seed_phase_defs, titulatec_app,
):
    """Documenta el LÍMITE del arreglo de Important 2, para que no se confunda
    con un hueco sin cerrar la próxima vez que alguien lea este archivo.

    El ruling de la Ronda 1 puso el lock en `verify()` (su único llamador en
    producción), NO dentro de `_convert()` -que sigue con guion bajo, sigue
    siendo un detalle de implementación privado-. Llamar a `_convert(db, req)`
    DIRECTO, dos veces, saltándose `verify()` -exactamente como hizo el
    revisor para diagnosticar el hallazgo original- SIGUE duplicando el
    `ProcessEvent` y el intento de correo. Es el comportamiento ESPERADO, no
    una regresión: en producción no hay ningún camino que llegue a `_convert`
    sin pasar por `verify()` primero.
    """
    from itcj2.apps.titulatec.models import ProcessEvent, TitulationProcess
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )

    seed_phase_defs()
    cohort = make_cohort(status="open")
    _solo_esta_convocatoria(db_session, cohort)
    student = make_student(control_number="99770081")
    student.password_hash = "hash-que-ya-existe"
    db_session.flush()
    req, _ = _make_req(db_session, cohort, control="99770081", kind="known")

    ok1, _ = EnrollmentRequestService._convert(db_session, req)
    ok2, _ = EnrollmentRequestService._convert(db_session, req)

    assert ok1 is True and ok2 is True
    procs = (db_session.query(TitulationProcess)
             .filter_by(student_id=student.id, cohort_id=cohort.id).all())
    assert len(procs) == 1, "import_rows ya es idempotente por (student_id, cohort_id)"
    events = (db_session.query(ProcessEvent)
              .filter_by(process_id=procs[0].id, event_type="enrollment_self_service")
              .all())
    assert len(events) == 2, (
        "esto SÍ se duplica llamando _convert directo -por diseño, la guarda "
        "vive en verify(), no aquí. Si esto empieza a dar 1, alguien blindó "
        "_convert() por su cuenta: actualiza este test para reflejarlo.")
