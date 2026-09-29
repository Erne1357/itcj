"""Tareas celery de TitulaTec: las del SII (spec 2026-09-25 §3.4, Tarea 4), el
despacho de correos del proceso (spec 2026-09-28 §6 C3/C5) y el barrido diario
de recordatorios (§6 C4/C5).

Sin broker ni worker: se llama el cuerpo de la tarea (`task.run`, que en una
tarea `bind=True` ya trae `self`) con el service parcheado
(`EligibilityService`, `MailDispatcher`, `MailReminders`), y el `retry` de la
tarea se sustituye por un registro. `SessionLocal` apunta a la sesión del test
(`patched_session_local`).
"""
from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

import itcj2.tasks.titulatec_tasks as tasks
from itcj2.apps.titulatec.services.eligibility_service import EligibilityService


class _Retry(Exception):
    pass


@pytest.fixture()
def reintentos(monkeypatch):
    """`self.retry(...)` registra sus argumentos y corta como lo hace celery."""
    llamadas = []

    def _retry(*args, **kwargs):
        llamadas.append(kwargs)
        raise _Retry()

    monkeypatch.setattr(tasks.sii_check_request, "retry", _retry)
    return llamadas


@pytest.fixture()
def consulta(monkeypatch, patched_session_local):
    """`EligibilityService.check` devuelve lo que diga la prueba y anota cómo
    se llamó."""
    estado = {"resultado": None, "llamadas": []}

    def _check(db, req_id, *, attempt=1, force=False):
        estado["llamadas"].append({"db": db, "req_id": req_id, "attempt": attempt,
                                   "force": force})
        return estado["resultado"]

    monkeypatch.setattr(EligibilityService, "check", staticmethod(_check))
    monkeypatch.setattr(EligibilityService, "max_attempts", staticmethod(lambda: 3))
    return estado


def _chk(status, attempt=1, retryable=None):
    """`retryable`: el error fue `SiiUnavailable` (lo fija `check`)."""
    if retryable is None and status == "error":
        retryable = True
    return SimpleNamespace(id=77, status=status, attempt=attempt, retryable=retryable)


def test_las_tareas_estan_registradas_y_el_worker_las_carga():
    from itcj2.celery_app import celery_app

    assert "itcj2.tasks.titulatec_tasks" in celery_app.conf.include
    assert "titulatec.sii_check_request" in celery_app.tasks


def test_los_nombres_de_las_tareas_son_los_del_spec():
    """Spec 2026-09-25 §3.4: `titulatec.sii_check_request` y
    `titulatec.sii_sweep`. `enqueue_check` manda la consulta por NOMBRE
    (`send_task`): si su constante y el `name=` de la tarea divergen, el worker
    descarta el mensaje y la solicitud solo la recoge el barrido."""
    from itcj2.apps.titulatec.services.eligibility_service import CHECK_TASK_NAME

    assert tasks.sii_check_request.name == "titulatec.sii_check_request"
    assert tasks.sii_sweep.name == "titulatec.sii_sweep"
    assert CHECK_TASK_NAME == tasks.sii_check_request.name


def test_consulta_apta_no_reintenta(consulta, reintentos, db_session):
    consulta["resultado"] = _chk("apt")

    out = tasks.sii_check_request.run(req_id=5)

    assert out == {"req_id": 5, "check_id": 77, "status": "apt", "attempt": 1}
    assert reintentos == []
    llamada, = consulta["llamadas"]
    assert llamada["req_id"] == 5 and llamada["attempt"] == 1 and llamada["force"] is False
    assert llamada["db"].get_bind() is db_session.get_bind(), "usa SessionLocal()"


def test_error_reintenta_con_el_siguiente_intento_y_espera_creciente(consulta, reintentos):
    consulta["resultado"] = _chk("error", attempt=1)
    with pytest.raises(_Retry):
        tasks.sii_check_request.run(req_id=5)

    consulta["resultado"] = _chk("error", attempt=2)
    with pytest.raises(_Retry):
        tasks.sii_check_request.run(req_id=5, attempt=2)

    primero, segundo = reintentos
    assert primero["kwargs"] == {"req_id": 5, "attempt": 2, "force": False}
    assert segundo["kwargs"] == {"req_id": 5, "attempt": 3, "force": False}
    assert 0 < primero["countdown"] < segundo["countdown"] <= 3600


def test_un_error_que_no_es_del_sii_caido_no_reintenta(consulta, reintentos):
    """Spec §3.4: backoff SOLO ante `SiiUnavailable`. Una regla rota o una
    consulta inválida no se arreglan esperando: queda «Error» para SE."""
    consulta["resultado"] = _chk("error", attempt=1, retryable=False)

    out = tasks.sii_check_request.run(req_id=5)

    assert out["status"] == "error"
    assert reintentos == []


def test_en_el_tope_de_intentos_ya_no_reintenta(consulta, reintentos):
    consulta["resultado"] = _chk("error", attempt=3)

    out = tasks.sii_check_request.run(req_id=5, attempt=3)

    assert out["status"] == "error"
    assert reintentos == []


def test_un_reintento_forzado_no_arrastra_force(consulta, reintentos):
    """«Reintentar consulta» fuerza SOLO la primera; los reintentos por error
    ya siguen la cuenta normal (y respetan el tope)."""
    consulta["resultado"] = _chk("error", attempt=1)

    with pytest.raises(_Retry):
        tasks.sii_check_request.run(req_id=5, force=True)

    assert consulta["llamadas"][0]["force"] is True
    assert reintentos[0]["kwargs"]["force"] is False


def test_sin_consulta_no_hace_nada(consulta, reintentos):
    consulta["resultado"] = None

    out = tasks.sii_check_request.run(req_id=5)

    assert out == {"req_id": 5, "skipped": True}
    assert reintentos == []


def test_la_tarea_no_hace_nada_con_sii_no_configurado(
    monkeypatch, patched_session_local, db_session, make_cohort, modo_sii, reintentos,
):
    """Spec 2026-09-27 D11: con `TITULATEC_SII_BACKEND=disabled` una tarea que
    llegue de todos modos (encolada antes del cambio, o a mano) no escribe nada
    ni se reintenta. Con el `EligibilityService.check` REAL."""
    from itcj2.apps.titulatec.models import EligibilityCheck, EnrollmentRequest
    from itcj2.apps.titulatec.services.sii.client import SiiConfig

    monkeypatch.setattr(SiiConfig, "backend", staticmethod(lambda: "disabled"))
    cohort = make_cohort(status="open")
    req = EnrollmentRequest(
        cohort_id=cohort.id, control_number="99580140", first_name="EGRESADA",
        last_name="DEL SII", program_text="Ingenieria Ficticia", phone="6561234567",
        contact_email="sii@example.invalid", has_efirma=True, kind="unknown",
        status="pending_review", verify_send_count=0)
    db_session.add(req)
    db_session.flush()

    out = tasks.sii_check_request.run(req_id=req.id)

    assert out == {"req_id": req.id, "skipped": True}
    assert reintentos == []
    assert db_session.query(EligibilityCheck).filter_by(request_id=req.id).count() == 0
    db_session.refresh(req)
    assert req.last_check_id is None


# ---------------------------------------------------------------------------
# sii_sweep (periódica) y su alta en la BD
# ---------------------------------------------------------------------------
def test_el_barrido_esta_registrado_y_catalogado():
    from itcj2.celery_app import celery_app

    assert "titulatec.sii_sweep" in celery_app.tasks
    definicion, = [d for d in tasks.TASK_DEFINITIONS
                   if d["task_name"] == tasks.sii_sweep.name]
    assert definicion["app_name"] == "titulatec"


def test_el_barrido_corre_con_su_sesion_y_su_presupuesto(monkeypatch, patched_session_local,
                                                         db_session):
    llamadas = []

    def _sweep(db, *, now=None, cohort_id=None, max_seconds=None):
        llamadas.append((db.get_bind() is db_session.get_bind(), cohort_id, max_seconds))
        return {"checked": 2, "retried": 0}

    monkeypatch.setattr(EligibilityService, "sweep", staticmethod(_sweep))

    out = tasks.sii_sweep.run()

    assert out == {"checked": 2, "retried": 0}
    (misma_sesion, cohort_id, presupuesto), = llamadas
    assert misma_sesion and cohort_id is None
    assert 0 < presupuesto < tasks.sii_sweep.soft_time_limit, (
        "el presupuesto termina antes de que celery corte la tarea")


def test_la_periodica_se_da_de_alta_con_los_seeders_de_titulatec():
    """El scheduler lee `core_periodic_tasks` (DatabaseScheduler): el alta va
    por DML plegado a `SEED_FILES` (`init-titulatec`), antes del 15 que debe
    seguir siendo el último."""
    from itcj2.cli.titulatec import SEED_FILES

    nombre = "sii_2026_09/16_insert_sii_sweep_task.sql"
    assert nombre in SEED_FILES
    assert SEED_FILES.index(nombre) < SEED_FILES.index("15_grant_admin_all_perms.sql")
    assert SEED_FILES[-1] == "15_grant_admin_all_perms.sql"


def test_el_dml_de_la_periodica_programa_la_tarea_por_su_nombre_registrado():
    """Beat manda `core_periodic_tasks.task_name` tal cual: un nombre que el
    worker no registró es una periódica que nunca corre, sin error visible.
    `database/` no se versiona; sin el archivo (CI) no hay nada que comparar."""
    from itcj2.cli.titulatec import DML_TITULATEC

    dml = DML_TITULATEC / "sii_2026_09" / "16_insert_sii_sweep_task.sql"
    if not dml.exists():
        pytest.skip("database/ no está en este entorno")
    sql = dml.read_text(encoding="utf-8")

    # Una vez en `core_task_definitions` y otra en `core_periodic_tasks`.
    assert sql.count(f"'{tasks.sii_sweep.name}'") >= 2


# ---------------------------------------------------------------------------
# email_dispatch (periódica, cada 5 minutos): correos del proceso al egresado
# ---------------------------------------------------------------------------
_DESPACHO = {"sent": 2, "failed": 0, "retry": 1, "no_recipient": 0, "obsolete": 0,
             "waiting": 1}


def test_el_despacho_de_correos_esta_registrado_y_catalogado():
    """Spec C5: nombre por `name=` (el DML de la periódica, Tarea 9, la programa
    por nombre), límites de celery del contrato y su entrada en
    `TASK_DEFINITIONS`."""
    from itcj2.celery_app import celery_app

    assert tasks.email_dispatch.name == "titulatec.email_dispatch"
    assert "titulatec.email_dispatch" in celery_app.tasks
    assert (tasks.email_dispatch.soft_time_limit, tasks.email_dispatch.time_limit) == (50, 58)
    definicion, = [d for d in tasks.TASK_DEFINITIONS
                   if d["task_name"] == tasks.email_dispatch.name]
    assert definicion["app_name"] == "titulatec"
    assert definicion["default_args"] == {}


def test_el_despacho_se_describe_cada_5_minutos():
    """Ruling 18: el despachador corre cada 5 minutos (`*/5 * * * *` en el DML),
    y su descripción —la que enseña /config/system/tasks y que el DML copia
    literal— lo dice así, no «cada minuto»."""
    definicion, = [d for d in tasks.TASK_DEFINITIONS
                   if d["task_name"] == tasks.email_dispatch.name]

    assert definicion["description"].startswith("Cada 5 minutos: ")
    assert "cada minuto" not in definicion["description"].lower()


def test_el_despacho_corre_con_su_sesion_y_devuelve_su_resultado(
    monkeypatch, patched_session_local, db_session, caplog,
):
    """La tarea solo abre la sesión (`SessionLocal` importado DENTRO) y llama
    a `MailDispatcher.run` con sus valores por omisión (`now` = `db_now()` y el
    lote de 50 los decide el service); devuelve su dict y lo deja en el log."""
    from itcj2.apps.titulatec.services.mail_dispatch import MailDispatcher

    llamadas = []

    def _run(db, *, now=None, limit=50):
        llamadas.append((db.get_bind() is db_session.get_bind(), now, limit))
        return dict(_DESPACHO)

    monkeypatch.setattr(MailDispatcher, "run", staticmethod(_run))

    with caplog.at_level(logging.INFO, logger="itcj2.tasks.titulatec_tasks"):
        out = tasks.email_dispatch.run()

    assert out == _DESPACHO
    assert llamadas == [(True, None, 50)], "usa SessionLocal() y los valores del service"
    assert str(_DESPACHO) in caplog.text


def test_el_despacho_sin_movimiento_no_llena_el_log(monkeypatch, patched_session_local,
                                                    caplog):
    """Corre cada 5 minutos: una corrida en ceros va a DEBUG, no a INFO (288
    líneas al día sin información)."""
    from itcj2.apps.titulatec.services.mail_dispatch import MailDispatcher

    ceros = dict.fromkeys(_DESPACHO, 0)
    monkeypatch.setattr(MailDispatcher, "run", staticmethod(lambda db, **kw: dict(ceros)))

    with caplog.at_level(logging.INFO, logger="itcj2.tasks.titulatec_tasks"):
        assert tasks.email_dispatch.run() == ceros

    assert not [r for r in caplog.records if r.name == "itcj2.tasks.titulatec_tasks"]


# ---------------------------------------------------------------------------
# email_reminders (periódica, diaria 9:00): recordatorios por correo
# ---------------------------------------------------------------------------
def test_los_recordatorios_estan_registrados_y_catalogados():
    """Spec C5: nombre por `name=` (el DML de la periódica, Tarea 9, la programa
    por nombre), límites de celery del contrato y su entrada en
    `TASK_DEFINITIONS`."""
    from itcj2.celery_app import celery_app

    assert tasks.email_reminders.name == "titulatec.email_reminders"
    assert "titulatec.email_reminders" in celery_app.tasks
    assert (tasks.email_reminders.soft_time_limit,
            tasks.email_reminders.time_limit) == (540, 600)
    definicion, = [d for d in tasks.TASK_DEFINITIONS
                   if d["task_name"] == tasks.email_reminders.name]
    assert definicion["app_name"] == "titulatec"
    assert definicion["default_args"] == {}
    assert definicion["display_name"] and definicion["description"]


def test_los_recordatorios_corren_con_su_sesion_y_devuelven_su_resultado(
    monkeypatch, patched_session_local, db_session, caplog,
):
    """La tarea solo abre la sesión (`SessionLocal` importado DENTRO) y llama a
    `MailReminders.run` con su reloj por omisión (`db_now()`, lo decide el
    service); devuelve su dict y lo deja en el log (corre una vez al día)."""
    from itcj2.apps.titulatec.services.mail_reminders import MailReminders

    resultado = {"appt": 2, "docs": 1, "survey": 0}
    llamadas = []

    def _run(db, *, now=None):
        llamadas.append((db.get_bind() is db_session.get_bind(), now))
        return dict(resultado)

    monkeypatch.setattr(MailReminders, "run", staticmethod(_run))

    with caplog.at_level(logging.INFO, logger="itcj2.tasks.titulatec_tasks"):
        out = tasks.email_reminders.run()

    assert out == resultado
    assert llamadas == [(True, None)], "usa SessionLocal() y el reloj del service"
    assert str(resultado) in caplog.text


def test_los_recordatorios_con_el_correo_apagado_no_hacen_nada(monkeypatch,
                                                              patched_session_local):
    """Con el `MailReminders.run` REAL: `TITULATEC_EMAIL_ENABLED=false` → nada."""
    from itcj2.apps.titulatec.services.student_mail import MailSettings

    monkeypatch.setattr(MailSettings, "enabled", staticmethod(lambda: False))

    assert tasks.email_reminders.run() == {"disabled": True}


# ---------------------------------------------------------------------------
# CLI `titulatec sii-sweep`
# ---------------------------------------------------------------------------
def _cli(*args):
    from click.testing import CliRunner
    from itcj2.cli.titulatec import titulatec_cli

    return CliRunner().invoke(titulatec_cli, list(args))


def _modo(monkeypatch, mode):
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )
    monkeypatch.setattr(EnrollmentRequestService, "reviewer_mode",
                        staticmethod(lambda: mode))


def test_cli_sii_sweep_imprime_lo_que_hizo(monkeypatch, patched_session_local):
    _modo(monkeypatch, "sii")
    llamadas = []

    def _sweep(db, *, now=None, cohort_id=None, max_seconds=None):
        llamadas.append(cohort_id)
        return {"checked": 3, "retried": 1}

    monkeypatch.setattr(EligibilityService, "sweep", staticmethod(_sweep))

    res = _cli("sii-sweep", "--cohort", "12")

    assert res.exit_code == 0, res.output
    assert llamadas == [12]
    assert "consultadas: 3" in res.output.lower()
    assert "reintentadas: 1" in res.output.lower()
    # El barrido ya no aprueba (spec 2026-09-27 §A3): no hay nada que contar.
    assert "aprobadas" not in res.output.lower()


def test_cli_sii_sweep_fuera_del_modo_sii_avisa_y_no_barre(monkeypatch, patched_session_local):
    _modo(monkeypatch, "school_services")
    monkeypatch.setattr(EligibilityService, "sweep",
                        staticmethod(lambda *a, **k: pytest.fail("no debió barrer")))

    res = _cli("sii-sweep")

    assert res.exit_code == 0, res.output
    assert "school_services" in res.output
