"""Elegibilidad automática contra el SII: consulta y barrido (spec 2026-09-25
§3.4, Tarea 4). Nada se aprueba solo: el SII informa y Servicios Escolares
decide siempre (spec 2026-09-27 §A3).

Corre con el SII FALSO y las reglas sintéticas de `sii_fixtures/` (se parchea
`SiiConfig`, nunca `get_settings`): la fixture `sii` y `FakeSii` viven en
`_sii_fake.py`, compartidos con `test_enrollment_approve.py`. El JSON del SII
falso lo arma cada prueba en `tmp_path` con números de control `9958xxxx`:
los `2011xxxx` de `sii_fixtures/fake_sii.json` podrían existir como cuentas
reales en la BD de dev, y «¿tiene cuenta?» se decide contra `core_users`.

Máquina que fija este archivo:

    create() [modo sii]  ─commit─► enqueue_check(req_id)      (best-effort)
    check()              lock ─► fila `pending` ─commit─► SII + NIP (SIN lock)
                         ─► lock + refresh ─► apt | not_apt | error + nip_status

Con el SII sin configurar (backend `disabled`, D11) nada se consulta, encola
ni barre.
"""
from __future__ import annotations

import ast
import json
import re
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from itcj2.apps.titulatec.services.eligibility_service import (
    _PENDING_STALE, NIP_MISSING, NIP_UNAVAILABLE,
)
from itcj2.apps.titulatec.services.sii.client import SiiConfig
from tests.fastapi.titulatec._sii_fake import (  # noqa: F401
    FIXTURES, RULES_VERSION, pide_nip, sii,
)


# ---------------------------------------------------------------------------
# Fixtures locales (el SII falso, `sii`, es el compartido de `_sii_fake.py`)
# ---------------------------------------------------------------------------
# `modo_sii` vive en conftest.py (Tarea 1: una sola copia compartida en vez de
# 6 duplicadas por archivo).


@pytest.fixture(autouse=True)
def _tope(monkeypatch):
    """5 intentos, fijos aunque el `.env` del contenedor diga otra cosa."""
    from itcj2.apps.titulatec.services.eligibility_service import EligibilityService

    monkeypatch.setattr(EligibilityService, "max_attempts", staticmethod(lambda: 5))


@pytest.fixture(autouse=True)
def _sin_celery(monkeypatch):
    """`enqueue_check` jamás toca el broker en esta suite; registra las llamadas."""
    llamadas = []
    monkeypatch.setattr(
        "itcj2.apps.titulatec.services.eligibility_service.enqueue_check",
        lambda req_id, **kw: llamadas.append((req_id, kw)))
    return llamadas


@pytest.fixture()
def espia_helper(monkeypatch):
    """Sustituye TODOS los `send_*` del helper por un registro de llamadas."""
    from itcj2.apps.titulatec.services.email_helper import TitulaTecEmailHelper

    llamadas = []
    for nombre in [n for n in dir(TitulaTecEmailHelper) if n.startswith("send_")]:
        monkeypatch.setattr(
            TitulaTecEmailHelper, nombre,
            staticmethod(lambda *a, _n=nombre, **k: llamadas.append((_n, k)) or True))
    return llamadas


def _svc():
    from itcj2.apps.titulatec.services.eligibility_service import EligibilityService
    return EligibilityService


def _ers():
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )
    return EnrollmentRequestService


def _make_req(db_session, cohort, *, control, status="pending_review", program=None, **kw):
    from itcj2.apps.titulatec.models import EnrollmentRequest

    row = EnrollmentRequest(
        cohort_id=cohort.id, control_number=control,
        first_name="EGRESADA", last_name="DEL SII", middle_name=None,
        program_id=getattr(program, "id", program), program_text="Ingenieria Ficticia",
        phone="6561234567", contact_email="sii@example.invalid",
        has_efirma=True, kind="unknown", status=status, verify_send_count=0,
    )
    for k, v in kw.items():
        setattr(row, k, v)
    db_session.add(row)
    db_session.flush()
    return row


def _checks(db_session, req):
    from itcj2.apps.titulatec.models import EligibilityCheck
    return (db_session.query(EligibilityCheck).filter_by(request_id=req.id)
            .order_by(EligibilityCheck.id).all())


_COMPARADA: dict = {}


def _check_row(db_session, req, *, status, attempt=1, started_at=None, finished_at=None,
               rules_version=RULES_VERSION, retryable=None, identity_mismatch=_COMPARADA):
    """Check ya hecho (historial), apuntado como vigente. Por omisión el nombre
    se comparó con el SII y coincidió (`{}`); `None` = no se comparó."""
    from itcj2.apps.titulatec.models import EligibilityCheck

    now = datetime.now()
    chk = EligibilityCheck(request_id=req.id, status=status, attempt=attempt,
                           rules_version=rules_version, started_at=started_at or now,
                           finished_at=finished_at if status != "pending" else None,
                           retryable=retryable,
                           identity_mismatch=(dict(identity_mismatch)
                                              if identity_mismatch is not None else None))
    if status != "pending" and chk.finished_at is None:
        chk.finished_at = now
    db_session.add(chk)
    db_session.flush()
    req.last_check_id = chk.id
    db_session.flush()
    return chk


# ---------------------------------------------------------------------------
# Modo y etiqueta
# ---------------------------------------------------------------------------
def test_en_modo_sii_responde_servicios_escolares(modo_sii):
    assert _ers().reviewer_mode() == "sii"
    assert _ers().reviewer_label() == "Servicios Escolares"


def test_los_settings_se_leen_por_metodos_estaticos(monkeypatch):
    from itcj2.apps.titulatec.services.eligibility_service import EligibilityService
    from itcj2.config import get_settings

    monkeypatch.undo()   # quita el autouse que fija 5 intentos
    monkeypatch.setattr(get_settings(), "TITULATEC_SII_MAX_ATTEMPTS", 3)
    assert EligibilityService.max_attempts() == 3


def test_la_version_vigente_sale_de_las_reglas(sii):
    assert _svc().rules_version() == RULES_VERSION


# ---------------------------------------------------------------------------
# check(): veredictos
# ---------------------------------------------------------------------------
def test_apta_registra_la_consulta_con_reglas_hechos_y_version(
    db_session, make_cohort, sii, modo_sii,
):
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99580001")
    sii.alumno("99580001")

    chk = _svc().check(db_session, req.id)

    assert chk is not None
    assert chk.status == "apt"
    assert chk.attempt == 1
    assert chk.rules_version == RULES_VERSION
    assert [r["rule"] for r in chk.results] == [
        "existe", "estatus", "creditos", "servicio_social", "residencia", "sin_adeudos"]
    assert all(r["ok"] for r in chk.results)
    assert chk.facts == {"estatus": "EGRESADO", "creditos_aprobados": 260,
                         "creditos_carrera": 260, "anio_ingreso": 2019}
    assert chk.error is None
    assert chk.finished_at is not None and chk.duration_ms is not None
    assert chk.identity_mismatch == {}, "se comparó el nombre y coincide"
    assert req.last_check_id == chk.id
    assert req.status == "pending_review"
    assert _svc().latest_check(db_session, req).id == chk.id


def test_no_apta_guarda_el_motivo_exacto(db_session, make_cohort, sii, modo_sii):
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99580002")
    sii.no_apta("99580002")

    chk = _svc().check(db_session, req.id)

    assert chk.status == "not_apt"
    fallas = [r for r in chk.results if not r["ok"]]
    assert fallas == [{"rule": "creditos", "ok": False,
                       "message": "Le faltan créditos: 200 de 260."}]
    assert req.status == "pending_review", "no apta queda «Por revisar»"


def test_sii_caido_es_error_y_la_solicitud_sigue_por_revisar(
    db_session, make_cohort, sii, modo_sii,
):
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99580003")
    sii.caido("99580003")

    chk = _svc().check(db_session, req.id)

    assert chk.status == "error"
    assert "no disponible" in chk.error
    assert chk.finished_at is not None
    assert req.status == "pending_review"
    assert req.last_check_id == chk.id


def test_sin_reglas_es_error(db_session, make_cohort, sii, modo_sii, tmp_path):
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99580005")
    sii.rules = tmp_path / "no_hay_reglas"

    chk = _svc().check(db_session, req.id)

    assert chk.status == "error"
    assert "rules.toml" in chk.error


# Spec §3.4: se reintenta SOLO ante `SiiUnavailable` (conexión, timeout). Una
# regla rota o una consulta inválida no se arreglan solas: quedan en «Error»
# para Servicios Escolares, con su motivo. (Con el backend `disabled` ya no se
# llega a consultar: `test_sii_no_configurado_no_consulta`.)
@pytest.mark.parametrize("falla", ["caido", "al_conectar"])
def test_el_sii_que_no_responde_es_un_error_reintentable(
    db_session, make_cohort, sii, modo_sii, monkeypatch, falla,
):
    from itcj2.apps.titulatec.services.sii import client as sii_client
    from itcj2.apps.titulatec.services.sii.errors import SiiUnavailable

    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99580080")
    if falla == "caido":
        sii.caido("99580080")
    else:
        def _sin_conexion():
            raise SiiUnavailable("No se pudo conectar al SII.")
        monkeypatch.setattr(sii_client, "get_sii_client", _sin_conexion)

    chk = _svc().check(db_session, req.id)

    assert chk.status == "error"
    assert chk.retryable is True


@pytest.mark.parametrize("falla", ["consulta", "reglas", "inesperada"])
def test_un_error_de_configuracion_no_es_reintentable(
    db_session, make_cohort, sii, modo_sii, tmp_path, monkeypatch, falla,
):
    from itcj2.apps.titulatec.services.sii.client import FakeSiiClient

    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99580081")
    if falla == "consulta":
        sii.consulta_invalida("99580081")
    elif falla == "reglas":
        sii.rules = tmp_path / "no_hay_reglas"
    else:
        def _revienta(self, *a, **k):
            raise RuntimeError("falla del cliente")
        monkeypatch.setattr(FakeSiiClient, "query", _revienta)

    chk = _svc().check(db_session, req.id)

    assert chk.status == "error"
    assert chk.retryable is False


@pytest.mark.parametrize("donde", ["consulta", "reglas"])
def test_el_corte_de_celery_es_un_error_reintentable(
    db_session, make_cohort, sii, modo_sii, monkeypatch, donde,
):
    """Revisión final (minor): `SoftTimeLimitExceeded` es tiempo agotado, no
    configuración: se reintenta (antes quedaba como error definitivo)."""
    from celery.exceptions import SoftTimeLimitExceeded

    from itcj2.apps.titulatec.services.sii.client import FakeSiiClient
    from itcj2.apps.titulatec.services.sii.rules import RuleSet

    def _corte(*a, **k):
        raise SoftTimeLimitExceeded()

    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99580098")
    sii.alumno("99580098")
    if donde == "consulta":
        monkeypatch.setattr(FakeSiiClient, "query", _corte)
    else:
        monkeypatch.setattr(RuleSet, "load", classmethod(_corte))

    chk = _svc().check(db_session, req.id)

    assert chk.status == "error"
    assert chk.retryable is True


def test_el_corte_de_celery_al_pedir_el_nip_es_transitorio(sii, monkeypatch):
    from celery.exceptions import SoftTimeLimitExceeded

    from itcj2.apps.titulatec.services import eligibility_service as elig
    from itcj2.apps.titulatec.services.sii.client import FakeSiiClient

    def _corte(*a, **k):
        raise SoftTimeLimitExceeded()

    monkeypatch.setattr(FakeSiiClient, "query", _corte)

    assert elig.fetch_sii_nip("99580099") == (None, elig.NIP_UNAVAILABLE)


def test_el_tipo_transitorio_del_nip_es_el_de_sii_unavailable():
    from itcj2.apps.titulatec.services import eligibility_service as mod
    from itcj2.apps.titulatec.services.sii.errors import SiiUnavailable

    assert mod.NIP_UNAVAILABLE == SiiUnavailable.__name__


def test_un_veredicto_no_es_error_ni_reintentable(db_session, make_cohort, sii, modo_sii):
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99580082")
    sii.no_apta("99580082")

    chk = _svc().check(db_session, req.id)

    assert chk.status == "not_apt"
    assert chk.retryable is None


def test_una_falla_inesperada_es_error_sin_su_mensaje(
    db_session, make_cohort, sii, modo_sii, monkeypatch, caplog,
):
    """Un error que no es del SII puede traer cualquier cosa en su texto: solo
    el tipo llega a la fila y al log."""
    from itcj2.apps.titulatec.services.sii import client as sii_client

    def _revienta():
        raise RuntimeError("PWD=secreto-del-driver")

    monkeypatch.setattr(sii_client, "get_sii_client", _revienta)
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99580006")

    with caplog.at_level("DEBUG"):
        chk = _svc().check(db_session, req.id)

    assert chk.status == "error"
    assert "RuntimeError" in chk.error
    assert "secreto" not in chk.error
    assert "secreto" not in caplog.text


def test_discrepancia_de_identidad_se_registra(db_session, make_cohort, sii, modo_sii):
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99580007")
    sii.alumno("99580007", nombre="OTRA PERSONA", carrera="Arquitectura")

    chk = _svc().check(db_session, req.id)

    assert chk.status == "apt", "el veredicto es de las reglas; la identidad va aparte"
    assert chk.identity_mismatch == {
        "first_name": {"form": "EGRESADA", "sii": "OTRA PERSONA"},
        "program": {"form": "Ingenieria Ficticia", "sii": "Arquitectura"},
    }


def test_identidad_igual_salvo_acentos_y_mayusculas_no_es_discrepancia(
    db_session, make_cohort, sii, modo_sii,
):
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99580008", first_name="María José",
                    last_name="Núñez", middle_name="López")
    sii.alumno("99580008", nombre="  MARIA  JOSE ", paterno="NUNEZ", materno="LOPEZ",
               carrera="INGENIERÍA FICTICIA")

    chk = _svc().check(db_session, req.id)

    assert chk.identity_mismatch == {}, "{} = se comparó y coincide; None = no se comparó"


# La identidad FALLA CERRADO (revisión final C3/C9): sin `[identity]`, con la
# columna mal escrita o con el nombre vacío en el SII, el nombre NO se comparó
# y la consulta lo dice (`None` o `_unverified`), nunca `{}` («coincide»). Ya
# no frena una aprobación automática (se retiró, spec 2026-09-27 D2), pero es
# lo que `identity_block` convierte en la confirmación de la bandeja (D7): si
# volviera `{}`, un nombre que nadie comparó pasaría por confirmado.
_NOTA_SIN_COMPARAR = "No se pudo comparar el nombre con el SII."


def _reglas_sin(tmp_path, *, quitar=None, cambiar=None) -> Path:
    """Copia de las reglas sintéticas sin `[identity]` o con un cambio."""
    import shutil

    base = tmp_path / "reglas"
    shutil.copytree(FIXTURES, base, ignore=shutil.ignore_patterns("fake_sii.json"))
    texto = (base / "rules.toml").read_text(encoding="utf-8")
    if quitar:
        inicio = texto.index(quitar)
        fin = texto.index("\n[", inicio + 1)
        texto = texto[:inicio] + texto[fin + 1:]
    if cambiar:
        assert cambiar[0] in texto, "el cambio no aplicó: las reglas sintéticas cambiaron"
        texto = texto.replace(*cambiar)
    (base / "rules.toml").write_text(texto, encoding="utf-8")
    return base


def test_sin_identity_en_las_reglas_el_nombre_no_se_compara(
    db_session, make_cohort, sii, modo_sii, tmp_path,
):
    sii.rules = _reglas_sin(tmp_path, quitar="[identity]")
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99580070")
    sii.alumno("99580070")

    chk = _svc().check(db_session, req.id)

    assert chk.status == "apt", "el veredicto es de las reglas; la identidad va aparte"
    assert chk.identity_mismatch is None, "sin [identity] no hubo comparación (≠ {})"


def test_columna_de_identidad_mal_escrita_deja_el_nombre_sin_comparar(
    db_session, make_cohort, sii, modo_sii, tmp_path,
):
    """El motor proyecta la columna inexistente como NULL: no es «coincide»."""
    sii.rules = _reglas_sin(tmp_path, cambiar=('first_name = "nombre"',
                                               'first_name = "nombre_mal"'))
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99580071")
    sii.alumno("99580071")

    chk = _svc().check(db_session, req.id)

    assert chk.status == "apt"
    assert chk.identity_mismatch == {"_unverified": ["first_name"]}


@pytest.mark.parametrize("campo,sin_comparar", [("nombre", "first_name"),
                                                ("paterno", "last_name")])
def test_nombre_vacio_en_el_sii_queda_sin_comparar(
    db_session, make_cohort, sii, modo_sii, campo, sin_comparar,
):
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99580072")
    sii.alumno("99580072", **{campo: None})

    chk = _svc().check(db_session, req.id)

    assert chk.status == "apt"
    assert chk.identity_mismatch == {"_unverified": [sin_comparar]}


_OTRA = {"form": "EGRESADA", "sii": "OTRA PERSONA"}


@pytest.mark.parametrize("identidad,esperado", [
    (None, _NOTA_SIN_COMPARAR),
    ({"_unverified": ["last_name"]}, _NOTA_SIN_COMPARAR),
    ({"_unverified": ["first_name"], "last_name": _OTRA}, _NOTA_SIN_COMPARAR),
    ({"first_name": _OTRA}, "El nombre del formulario no coincide con el del SII (nombre); "),
    ({"first_name": _OTRA, "last_name": _OTRA, "program": _OTRA},
     "El nombre del formulario no coincide con el del SII (nombre, apellido paterno); "),
    ({}, None),
    ({"program": {"form": "Ingenieria Ficticia", "sii": "Arquitectura"}}, None),
], ids=["no_comparado", "sin_comparar", "sin_comparar_gana", "nombre_distinto",
        "dos_campos_sin_carrera", "coincide", "solo_la_carrera"])
def test_identity_block_falla_cerrado(identidad, esperado):
    """Lo que la confirmación de la bandeja (D7) dirá del nombre. Sin
    comparación → «no se pudo comparar», aunque además haya diferencias; nombre
    distinto → los CAMPOS, nunca los valores; carrera distinta sola o
    coincidencia → nada que confirmar."""
    from types import SimpleNamespace

    from itcj2.apps.titulatec.services.eligibility_service import identity_block

    texto = identity_block(SimpleNamespace(identity_mismatch=identidad))

    if esperado is None or esperado == _NOTA_SIN_COMPARAR:
        assert texto == esperado
    else:
        assert texto.startswith(esperado)
        assert "OTRA PERSONA" not in texto and "EGRESADA" not in texto


def test_identity_block_sin_consulta_falla_cerrado():
    from itcj2.apps.titulatec.services.eligibility_service import identity_block

    assert identity_block(None) == _NOTA_SIN_COMPARAR


# ---------------------------------------------------------------------------
# check(): estado del NIP (spec 2026-09-27 §A2, D6). Sin cuenta y con un
# veredicto que no es `error`, la consulta pregunta también por el NIP del SII
# y guarda SOLO en qué estado está (`nip_status`): con eso la bandeja pinta
# desde el inicio «dar acceso» o «pasar a Accesos». El valor jamás se guarda.
# El espía `pide_nip` es el compartido de `_sii_fake.py`.
# ---------------------------------------------------------------------------
def test_el_dominio_del_estado_del_nip_es_el_de_la_spec():
    from itcj2.apps.titulatec.services.eligibility_service import NIP_STATUSES

    assert NIP_STATUSES == ("available", "missing", "invalid", "unavailable", "error",
                            "not_needed")


@pytest.mark.parametrize("valor,falla,esperado", [
    ("4321", None, "available"),
    ("12345", None, "invalid"),
    (None, None, "missing"),
    (None, NIP_MISSING, "missing"),
    (None, NIP_UNAVAILABLE, "unavailable"),
    (None, "SiiQueryError", "error"),
], ids=["valido", "cinco_digitos", "sin_nip", "nip_missing", "sii_caido", "de_config"])
def test_classify_sii_nip_cubre_todo_el_dominio(valor, falla, esperado):
    """UNA función traduce `(Secret | None, falla)` de `fetch_sii_nip` (en la
    consulta y en `_approve_locked`; `NIP_MISSING` equivale a «sin NIP») al
    estado que se guarda."""
    from itcj2.apps.titulatec.services.eligibility_service import NIP_STATUSES
    from itcj2.apps.titulatec.services.sii.rules import Secret

    secret = Secret(valor) if valor is not None else None

    assert _svc().classify_sii_nip(secret, falla) == esperado
    assert esperado in NIP_STATUSES


@pytest.mark.parametrize("veredicto", ["apt", "not_apt"])
def test_la_consulta_guarda_available_sin_cuenta(
    db_session, make_cohort, sii, modo_sii, pide_nip, veredicto,
):
    """Apta o no, sin cuenta: SE decide igual, así que el NIP se revisa."""
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99580120")
    (sii.alumno if veredicto == "apt" else sii.no_apta)("99580120")

    chk = _svc().check(db_session, req.id)

    assert chk.status == veredicto
    assert chk.nip_status == "available"
    assert pide_nip == ["99580120"]


def test_la_consulta_guarda_missing_si_el_sii_no_tiene_nip(
    db_session, make_cohort, sii, modo_sii,
):
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99580121")
    sii.alumno("99580121", nip=None)

    chk = _svc().check(db_session, req.id)

    assert chk.status == "apt" and chk.nip_status == "missing"


@pytest.mark.parametrize("nip", ["12345", "12a4"])
def test_la_consulta_guarda_invalid_con_formato_raro(
    db_session, make_cohort, sii, modo_sii, nip,
):
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99580122")
    sii.alumno("99580122", nip=nip)

    chk = _svc().check(db_session, req.id)

    assert chk.status == "apt" and chk.nip_status == "invalid"


def test_la_consulta_guarda_unavailable_si_el_nip_no_responde(
    db_session, make_cohort, sii, modo_sii,
):
    """El alumno sí respondió; la consulta del NIP no (transitorio)."""
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99580123")
    sii.alumno("99580123")
    sii.nip_caido("99580123")

    chk = _svc().check(db_session, req.id)

    assert chk.status == "apt" and chk.nip_status == "unavailable"
    assert chk.error is None, "la falla del NIP no convierte el veredicto en error"


def test_la_consulta_guarda_error_si_la_consulta_del_nip_falla(
    db_session, make_cohort, sii, modo_sii,
):
    """`SiiQueryError` al pedir el NIP: `[credential]` mal configurada."""
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99580124")
    sii.alumno("99580124")
    sii.nip_invalido("99580124")

    chk = _svc().check(db_session, req.id)

    assert chk.status == "apt" and chk.nip_status == "error"


def test_la_consulta_guarda_not_needed_con_cuenta(
    db_session, make_cohort, sii, modo_sii, pide_nip,
):
    """Con cuenta sale la liga, sin NIP: ni se le pregunta al SII."""
    _cuenta(db_session, "99580125")
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99580125")
    sii.alumno("99580125")

    chk = _svc().check(db_session, req.id)

    assert chk.status == "apt" and chk.nip_status == "not_needed"
    assert pide_nip == []


def test_con_control_invalido_no_se_busca_cuenta(
    db_session, make_cohort, sii, modo_sii, pide_nip,
):
    """Mismo corte que la aprobación (`_sii_nip_unlocked`): un control que no
    cumple `CONTROL_NUMBER_RE` no se busca en `core_users`, así que una cuenta
    con ese mismo texto no lo vuelve `not_needed`: se trata como sin cuenta."""
    control = "9958015X"
    _cuenta(db_session, control)
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control=control)
    sii.alumno(control)

    chk = _svc().check(db_session, req.id)

    assert chk.status == "apt"
    assert chk.nip_status == "available", "como si no tuviera cuenta"
    assert pide_nip == [control]


def test_con_veredicto_error_no_se_pide_el_nip(
    db_session, make_cohort, sii, modo_sii, pide_nip,
):
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99580126")
    sii.caido("99580126")

    chk = _svc().check(db_session, req.id)

    assert chk.status == "error"
    assert chk.nip_status is None, "NULL = no se revisó"
    assert pide_nip == []


def test_el_nip_de_la_consulta_nunca_se_persiste_ni_se_loguea(
    db_session, make_cohort, sii, modo_sii, caplog,
):
    from itcj2.apps.titulatec.services import eligibility_service as elig
    from itcj2.apps.titulatec.services.sii.rules import Secret

    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99580009")
    sii.alumno("99580009", nip="8642")

    with caplog.at_level("DEBUG"):
        chk = _svc().check(db_session, req.id)

    assert chk.nip_status == "available", "el NIP sí se le pidió al SII"
    db_session.refresh(chk)
    guardado = json.dumps([chk.results, chk.facts, chk.error, chk.identity_mismatch,
                           chk.nip_status, repr(chk)], default=str)
    assert "8642" not in guardado
    assert "8642" not in caplog.text
    # El `Secret` se descartó en la misma línea: no quedó colgado de nada.
    for dueno in (elig, elig.EligibilityService, chk):
        assert not any(isinstance(v, Secret) for v in vars(dueno).values()), dueno


# ---------------------------------------------------------------------------
# SII no configurado (spec 2026-09-27 D11, el caso de producción hoy:
# `TITULATEC_SII_BACKEND=disabled`): nada se consulta, encola ni barre.
# ---------------------------------------------------------------------------
class _SinBD:
    """Sesión que truena al primer uso: «sin consultar la BD»."""

    def __getattr__(self, nombre):
        raise AssertionError(f"tocó la BD ({nombre}) con el SII sin configurar")


def test_sii_no_configurado_no_consulta(db_session, make_cohort, sii, modo_sii, monkeypatch):
    import importlib

    from itcj2.celery_app import celery_app

    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99580130")
    sii.alumno("99580130")
    assert _svc().sii_configured() is True, "con el SII falso sí está configurado"
    sii.backend = "disabled"

    assert _svc().sii_configured() is False
    assert _svc().check(db_session, req.id) is None
    assert _svc().check(db_session, req.id, force=True) is None
    assert _checks(db_session, req) == []
    db_session.refresh(req)
    assert req.last_check_id is None
    assert _svc().sweep(_SinBD(), cohort_id=cohort.id) == {
        "checked": 0, "retried": 0, "disabled": True}
    assert _svc().recheck_errors(_SinBD(), cohort_id=cohort.id) == {
        "queued": 0, "failed": 0, "disabled": True}

    # El `enqueue_check` REAL (sin el parche autouse) no publica nada.
    mod = importlib.import_module("itcj2.apps.titulatec.services.eligibility_service")
    monkeypatch.undo()
    monkeypatch.setattr(SiiConfig, "backend", staticmethod(lambda: "disabled"))
    enviados = []
    monkeypatch.setattr(celery_app, "send_task",
                        lambda name, **kw: enviados.append((name, kw)))

    assert mod.enqueue_check(req.id) is False
    assert mod.enqueue_check(req.id, force=True) is False
    assert enviados == []


# ---------------------------------------------------------------------------
# check(): guardas, carreras e idempotencia (Review Focus 2 y 3)
# ---------------------------------------------------------------------------
def test_fuera_del_modo_sii_no_consulta(db_session, make_cohort, sii):
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99580010")
    sii.alumno("99580010")

    assert _svc().check(db_session, req.id) is None
    assert _checks(db_session, req) == []


@pytest.mark.parametrize("estado", ["approved", "rejected", "converted", "awaiting_access"])
def test_solo_consulta_solicitudes_por_revisar(db_session, make_cohort, sii, modo_sii, estado):
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99580011", status=estado)
    sii.alumno("99580011")

    assert _svc().check(db_session, req.id) is None
    assert _checks(db_session, req) == []


def test_la_tarea_que_corre_antes_de_ver_el_alta_no_hace_nada(db_session, sii, modo_sii):
    """Carrera alta ↔ tarea: la solicitud todavía no es visible → `None`; el
    barrido la recoge después (no hay check vigente)."""
    assert _svc().check(db_session, 987654321) is None


def test_no_duplica_una_consulta_en_curso(db_session, make_cohort, sii, modo_sii):
    """Dos tareas del mismo `req_id` a la vez: la segunda ve la fila `pending`
    fresca de la primera y no consulta (ni con `force`)."""
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99580012")
    sii.alumno("99580012")
    en_curso = _check_row(db_session, req, status="pending")

    assert _svc().check(db_session, req.id, attempt=2) is None
    assert _svc().check(db_session, req.id, force=True) is None
    assert [c.id for c in _checks(db_session, req)] == [en_curso.id]


def test_una_consulta_colgada_se_retoma_con_el_siguiente_intento(
    db_session, make_cohort, sii, modo_sii,
):
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99580013")
    sii.alumno("99580013")
    _check_row(db_session, req, status="pending",
               started_at=datetime.now() - timedelta(hours=1))

    chk = _svc().check(db_session, req.id, attempt=2)

    assert chk is not None and chk.attempt == 2 and chk.status == "apt"
    assert req.last_check_id == chk.id


def test_el_mismo_intento_dos_veces_consulta_una_sola_vez(
    db_session, make_cohort, sii, modo_sii,
):
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99580014")
    sii.no_apta("99580014")

    primero = _svc().check(db_session, req.id)
    segundo = _svc().check(db_session, req.id)

    assert primero is not None and segundo is None
    assert len(_checks(db_session, req)) == 1


def test_force_consulta_otra_vez_con_el_siguiente_numero_de_intento(
    db_session, make_cohort, sii, modo_sii,
):
    """«Reintentar consulta» de la bandeja: vuelve a preguntar aunque ya haya
    veredicto (el SII pudo cambiar)."""
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99580015")
    sii.no_apta("99580015")
    _svc().check(db_session, req.id)
    sii.alumno("99580015")

    chk = _svc().check(db_session, req.id, force=True)

    assert chk.attempt == 2 and chk.status == "apt"
    assert req.last_check_id == chk.id
    assert [c.status for c in _checks(db_session, req)] == ["not_apt", "apt"]


def test_no_pasa_del_tope_de_intentos_sin_force(db_session, make_cohort, sii, modo_sii):
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99580016")
    sii.caido("99580016")
    _check_row(db_session, req, status="error", attempt=5)

    assert _svc().check(db_session, req.id, attempt=6) is None
    assert len(_checks(db_session, req)) == 1


def test_la_consulta_al_sii_corre_sin_el_lock_de_la_solicitud(
    db_session, make_cohort, sii, modo_sii, monkeypatch,
):
    """Orden: lock → fila `pending` → COMMIT (suelta el lock) → SII → lock otra
    vez → commit. Mientras el SII responde, la fila `pending` ya es la vigente
    («Consultando…» en la bandeja)."""
    from itcj2.apps.titulatec.models import EligibilityCheck
    from itcj2.apps.titulatec.services.sii.client import FakeSiiClient

    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99580017")
    sii.alumno("99580017")

    pasos = []
    commit_real, execute_real = db_session.commit, db_session.execute
    query_real = FakeSiiClient.query

    def _commit():
        pasos.append("commit")
        return commit_real()

    def _execute(stmt, *a, **k):
        if "pg_advisory_xact_lock" in str(stmt):
            pasos.append("lock")
        return execute_real(stmt, *a, **k)

    def _query(self, sql, params, **kw):
        if "sii" not in pasos:
            vigente = db_session.get(EligibilityCheck, req.last_check_id)
            pasos.append(("vigente", vigente.status if vigente else None))
        pasos.append("nip" if kw.get("sensitive") else "sii")
        return query_real(self, sql, params, **kw)

    monkeypatch.setattr(db_session, "commit", _commit)
    monkeypatch.setattr(db_session, "execute", _execute)
    monkeypatch.setattr(FakeSiiClient, "query", _query)

    _svc().check(db_session, req.id)

    primera = pasos.index(("vigente", "pending"))
    antes = [p for p in pasos[:primera] if p in ("lock", "commit")]
    assert antes == ["lock", "commit"], pasos
    despues = [p for p in pasos[primera:] if p in ("lock", "commit")]
    assert despues[:2] == ["lock", "commit"], pasos
    # El NIP (spec 2026-09-27 §A2) también se pide en ②, sin el lock.
    nip = pasos.index("nip")
    assert [p for p in pasos[primera:nip] if p in ("lock", "commit")] == [], pasos
    assert "lock" in pasos[nip:], pasos


# ---------------------------------------------------------------------------
# create(): encola tras el commit, solo en modo sii
# ---------------------------------------------------------------------------
def _datos(control):
    return {"control_number": control, "first_name": "EGRESADA", "last_name": "DEL SII",
            "phone": "6561234567", "contact_email": "sii@example.invalid",
            "has_efirma": True, "program_text": "Ingenieria Ficticia"}


def test_el_alta_en_modo_sii_encola_la_consulta_despues_del_commit(
    db_session, make_cohort, modo_sii, monkeypatch, _sin_celery,
):
    pasos = []
    commit_real = db_session.commit
    monkeypatch.setattr(db_session, "commit",
                        lambda: pasos.append("commit") or commit_real())
    monkeypatch.setattr(
        "itcj2.apps.titulatec.services.eligibility_service.enqueue_check",
        lambda req_id, **kw: pasos.append(("encola", req_id)))
    cohort = make_cohort(status="open")

    req, outcome = _ers().create(db_session, cohort, _datos("99580020"), client_ip=None)

    assert outcome == "created"
    assert pasos == ["commit", ("encola", req.id)]


def test_el_alta_fuera_del_modo_sii_no_encola(db_session, make_cohort, _sin_celery):
    cohort = make_cohort(status="open")

    req, outcome = _ers().create(db_session, cohort, _datos("99580021"), client_ip=None)

    assert outcome == "created" and req is not None
    assert _sin_celery == []


def test_enqueue_check_nunca_lanza(monkeypatch, caplog):
    """Best-effort: sin broker el alta sigue igual (y la recoge el barrido)."""
    import importlib

    mod = importlib.import_module("itcj2.apps.titulatec.services.eligibility_service")
    monkeypatch.undo()   # el `enqueue_check` real, sin el parche autouse
    monkeypatch.setattr(SiiConfig, "backend", staticmethod(lambda: "fake"))
    from itcj2.celery_app import celery_app

    def _sin_broker(*a, **k):
        raise ConnectionError("redis://:clave@broker caído")

    monkeypatch.setattr(celery_app, "send_task", _sin_broker)
    with caplog.at_level("WARNING"):
        assert mod.enqueue_check(42) is False, "devuelve si se encoló (revisión final)"
    assert "42" in caplog.text
    assert "clave" not in caplog.text


def test_enqueue_check_manda_la_tarea_por_nombre_sin_reintentar_el_broker(monkeypatch):
    import importlib

    mod = importlib.import_module("itcj2.apps.titulatec.services.eligibility_service")
    monkeypatch.undo()
    # SII configurado: con `disabled` no publica (`test_sii_no_configurado_no_consulta`).
    monkeypatch.setattr(SiiConfig, "backend", staticmethod(lambda: "fake"))
    from itcj2.celery_app import celery_app

    enviados = []
    monkeypatch.setattr(celery_app, "send_task",
                        lambda name, **kw: enviados.append((name, kw)))

    assert mod.enqueue_check(42) is True
    assert mod.enqueue_check(44, force=True) is True

    assert enviados[0] == ("titulatec.sii_check_request",
                           {"kwargs": {"req_id": 42, "attempt": 1, "force": False},
                            "retry": False})
    assert enviados[1][1]["kwargs"] == {"req_id": 44, "attempt": 1, "force": True}


# ---------------------------------------------------------------------------
# Cuentas, eventos y solicitudes aptas (los usan las secciones de abajo)
# ---------------------------------------------------------------------------
def _cuenta(db_session, control, *, password=True):
    from itcj2.core.models.user import User
    from itcj2.core.utils.security import hash_nip

    user = User(username=control, control_number=control, first_name="YA",
                last_name="EXISTIA", password_hash=hash_nip("9999") if password else None,
                is_active=True, must_change_password=False)
    db_session.add(user)
    db_session.flush()
    return user


def _usuario(db_session, control):
    from itcj2.core.models.user import User
    return db_session.query(User).filter_by(control_number=control).first()


def _eventos(db_session, proc_id):
    from itcj2.apps.titulatec.models import ProcessEvent
    return (db_session.query(ProcessEvent)
            .filter_by(process_id=proc_id, event_type="enrollment_self_service").all())


@pytest.fixture()
def listo(db_session, seed_phase_defs, titulatec_app, sii, modo_sii, espia_helper):
    """SII falso + modo sii + lo que `import_rows` necesita. Devuelve el espía
    de correos."""
    seed_phase_defs()
    return espia_helper


def _solicitud_apta(db_session, make_cohort, sii, control, *, cohort=None, **kw):
    cohort = cohort or make_cohort(status="open")
    req = _make_req(db_session, cohort, control=control)
    sii.alumno(control, **kw)
    return req, cohort


# ---------------------------------------------------------------------------
# SE decide siempre (spec 2026-09-27 §A3, D2): el SII informa, pero ninguna
# solicitud se aprueba sola — ni al consultar ni en el barrido. La aprobación
# automática, su ventana de veto y la edad del veredicto se retiraron.
# ---------------------------------------------------------------------------
def test_una_apta_no_se_aprueba_sola_al_consultar(db_session, make_cohort, sii, listo):
    """Apta, sin cuenta, nombre confirmado y convocatoria abierta: todo lo que
    antes la aprobaba sola. Ahora queda «Por revisar» para Servicios Escolares."""
    req, _ = _solicitud_apta(db_session, make_cohort, sii, "99580030")

    chk = _svc().check(db_session, req.id)

    assert chk.status == "apt" and chk.identity_mismatch == {}, "nada la frenaba"
    assert req.status == "pending_review"
    assert req.reviewed_at is None and req.reviewed_by_id is None
    assert req.review_note is None, "no hay nota: no es un frenado, es la regla"
    assert _usuario(db_session, "99580030") is None, "no nace la cuenta"
    assert listo == [], "ni correo"


def test_el_barrido_no_aprueba_aptas(db_session, make_cohort, sii, listo):
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99580064")
    sii.alumno("99580064")
    vigente = _check_row(db_session, req, status="apt",
                         finished_at=datetime.now() - timedelta(hours=1))

    out = _svc().sweep(db_session, cohort_id=cohort.id)

    assert "approved" not in out
    assert out == {"checked": 0, "retried": 0}, "una apta vigente no es trabajo del barrido"
    db_session.refresh(req)
    assert req.status == "pending_review" and req.last_check_id == vigente.id
    assert _usuario(db_session, "99580064") is None
    assert listo == []


class _LlamadasAlNucleo(ast.NodeVisitor):
    """Cada llamada a `_approve_locked(` con la clase.función que la contiene."""

    def __init__(self):
        self.pila: list[str] = []
        self.llamadas: list[str] = []

    def _dentro(self, node):
        self.pila.append(node.name)
        self.generic_visit(node)
        self.pila.pop()

    visit_ClassDef = visit_FunctionDef = visit_AsyncFunctionDef = _dentro

    def visit_Call(self, node):
        func = node.func
        nombre = (func.attr if isinstance(func, ast.Attribute)
                  else func.id if isinstance(func, ast.Name) else None)
        if nombre == "_approve_locked":
            self.llamadas.append(".".join(self.pila) or "<módulo>")
        self.generic_visit(node)


def test_nada_llama_al_nucleo_de_aprobacion_salvo_approve():
    """«Barrido de escritores»: el único que aprueba es la bandeja de Servicios
    Escolares, por `approve_detailed()` (lock, estado y el NIP del SII; desde la
    Tarea 5 `approve()` solo le delega) — Ruling R2: el conjunto permitido son
    esas dos. Se recorre TODO `itcj2/`, no solo el servicio del SII: una ruta
    desatendida nueva que llame al núcleo sale aquí en rojo. Y el símbolo
    `auto_approve` no vuelve (ni en código ni en un docstring que lo siga
    anunciando)."""
    raiz = Path(__file__).resolve().parents[3]
    servicio = "itcj2/apps/titulatec/services/enrollment_request_service.py"
    permitidas = {(servicio, "EnrollmentRequestService.approve"),
                  (servicio, "EnrollmentRequestService.approve_detailed")}
    simbolo = re.compile(r"\bauto_approve\b")

    encontradas, con_simbolo = set(), []
    for path in sorted((raiz / "itcj2").rglob("*.py")):
        texto = path.read_text(encoding="utf-8")
        rel = path.relative_to(raiz).as_posix()
        if simbolo.search(texto):
            con_simbolo.append(rel)
        if "_approve_locked" not in texto:
            continue
        visor = _LlamadasAlNucleo()
        visor.visit(ast.parse(texto, filename=rel))
        encontradas.update((rel, donde) for donde in visor.llamadas)

    assert encontradas, "alguien tiene que llamar al núcleo"
    assert encontradas <= permitidas, encontradas - permitidas
    assert con_simbolo == []


def test_settings_sin_ventana_de_veto(monkeypatch, tmp_path):
    """Los dos settings de la automática se fueron. Un `.env` viejo que aún los
    traiga —con la combinación que antes tronaba al arrancar (edad ≤ ventana)—
    no truena: `extra="ignore"`."""
    from itcj2.config import Settings

    for var in ("TITULATEC_SII_AUTO_APPROVE_DELAY_HOURS",
                "TITULATEC_SII_VERDICT_MAX_AGE_HOURS"):
        assert var not in Settings.model_fields, var
    env = tmp_path / ".env"
    env.write_text("TITULATEC_SII_AUTO_APPROVE_DELAY_HOURS=5\n"
                   "TITULATEC_SII_VERDICT_MAX_AGE_HOURS=1\n", encoding="utf-8")
    monkeypatch.setenv("TITULATEC_SII_AUTO_APPROVE_DELAY_HOURS", "5")
    monkeypatch.setenv("TITULATEC_SII_VERDICT_MAX_AGE_HOURS", "1")

    s = Settings(_env_file=env)

    assert not hasattr(s, "TITULATEC_SII_AUTO_APPROVE_DELAY_HOURS")
    assert not hasattr(s, "TITULATEC_SII_VERDICT_MAX_AGE_HOURS")


# ---------------------------------------------------------------------------
# approve() en modo sii: Servicios Escolares aprueba siempre (el SII solo informa)
# ---------------------------------------------------------------------------
def test_se_aprueba_sin_cuenta_con_el_nip_del_sii_e_ignora_el_del_formulario(
    db_session, make_cohort, make_user, sii, listo,
):
    from itcj2.core.utils.security import verify_nip

    se = make_user(first_name="SERVICIOS", last_name="ESCOLARES")
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99580050")
    sii.no_apta("99580050", nip="3579")

    ok, folio = _ers().approve(db_session, req.id, nip="1111", program_id=None,
                               actor_id=se.id)

    assert ok is True and folio
    assert req.status == "converted" and req.reviewed_by_id == se.id
    assert req.nip_source == "sii"
    user = _usuario(db_session, "99580050")
    assert verify_nip("3579", user.password_hash)
    assert not verify_nip("1111", user.password_hash)
    assert user.must_change_password is False
    ev, = _eventos(db_session, req.converted_process_id)
    assert ev.payload["nip_source"] == "sii" and "auto" not in ev.payload
    assert ev.payload["approved_by_id"] == se.id
    assert listo == [("send_enrollment_approved", {"nip": None, "reassigned": False,
                                                   "nip_source": "sii"})]


def test_un_nip_del_sii_con_otro_formato_no_crea_cuenta_ni_se_filtra(
    db_session, make_cohort, make_user, sii, listo, caplog,
):
    se = make_user()
    req, _ = _solicitud_apta(db_session, make_cohort, sii, "99580040", nip="12AB")

    with caplog.at_level("DEBUG"):
        ok, motivo = _ers().approve(db_session, req.id, nip="", program_id=None,
                                    actor_id=se.id)

    assert (ok, motivo) == (False, "El NIP del SII no tiene un formato válido (4 dígitos).")
    assert req.status == "pending_review"
    assert _usuario(db_session, "99580040") is None
    assert "12AB" not in caplog.text
    assert listo == []


@pytest.mark.parametrize("nip", ["123", "12345", "１２３４", " 12 "])
def test_solo_4_digitos_ascii_crean_la_cuenta(
    db_session, make_cohort, make_user, sii, listo, nip,
):
    """Revisión final C13: exactamente 4 dígitos ASCII. Un dígito Unicode
    («１２３４») nadie lo puede teclear en el login."""
    se = make_user()
    req, _ = _solicitud_apta(db_session, make_cohort, sii, "99580041", nip=nip)

    ok, _ = _ers().approve(db_session, req.id, nip="", program_id=None, actor_id=se.id)

    assert ok is False and req.status == "pending_review"
    assert _usuario(db_session, "99580041") is None


def test_una_falla_al_crear_la_cuenta_no_filtra_el_nip_ni_su_hash(
    db_session, make_cohort, make_user, sii, listo, monkeypatch, caplog,
):
    """Review Focus 1: el error del driver de la BD trae los parámetros del
    INSERT (el hash del NIP). Ni ese texto ni el NIP llegan al log ni al motivo."""
    from itcj2.core.utils.security import hash_nip

    se = make_user()
    req, _ = _solicitud_apta(db_session, make_cohort, sii, "99580042", nip="1593")
    db_session.commit()
    h = hash_nip("1593")

    def _revienta(*a, **k):
        raise RuntimeError(f"INSERT core_users [parameters: ('1593', '{h}')]")

    monkeypatch.setattr(_ers(), "_create_account", staticmethod(_revienta))

    with caplog.at_level("DEBUG"):
        ok, motivo = _ers().approve(db_session, req.id, nip="", program_id=None,
                                    actor_id=se.id)

    assert ok is False and motivo
    assert "1593" not in motivo and h not in motivo
    # El respaldo del modo `sii` es Accesos (spec 2026-09-27 D1), no el alta
    # desde la convocatoria.
    assert motivo == "No se pudo crear la cuenta con el NIP del SII; pásala a Accesos."
    assert req.status == "pending_review"
    assert "1593" not in caplog.text and h not in caplog.text
    assert "RuntimeError" in caplog.text


@pytest.mark.parametrize("falla,motivo", [
    ("sin_nip", "El SII no tiene NIP para esta persona."),
    ("caido", "El SII no respondió al pedir el NIP."),
    ("invalido", "No se pudo leer el NIP en el SII (revisa la configuración de las reglas)."),
])
def test_se_no_puede_aprobar_sin_cuenta_si_el_sii_no_da_el_nip(
    db_session, make_cohort, make_user, sii, listo, falla, motivo,
):
    """Sin pasarla a Accesos, cada falla del NIP da SU motivo (spec 2026-09-27
    §A4); ninguno lleva el valor. La salida es «pasar a Accesos»
    (`test_enrollment_approve.py::TestModoSiiSEDecide`)."""
    se = make_user()
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99580051")
    if falla == "sin_nip":
        sii.alumno("99580051", nip=None)
    elif falla == "caido":
        sii.alumno("99580051")
        sii.nip_caido("99580051")
    else:
        sii.alumno("99580051")
        sii.nip_invalido("99580051")

    resultado = _ers().approve(db_session, req.id, nip="", program_id=None, actor_id=se.id)

    assert resultado == (False, motivo)
    assert req.status == "pending_review" and req.reviewed_by_id is None
    assert _usuario(db_session, "99580051") is None
    assert listo == []


def test_se_aprueba_con_cuenta_en_modo_sii_como_siempre(
    db_session, make_cohort, make_user, sii, listo,
):
    se = make_user()
    _cuenta(db_session, "99580052")
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99580052")

    ok, detalle = _ers().approve(db_session, req.id, nip="", program_id=None,
                                 actor_id=se.id)

    assert (ok, detalle) == (True, "")
    assert req.status == "approved" and req.reviewed_by_id == se.id
    assert [n for n, _ in listo] == ["send_verify_enrollment"]


# ---------------------------------------------------------------------------
# El NIP del SII se pide SIN el lock de la solicitud (revisión final C6/C8 y el
# minor diferido de T4): SE no espera los timeouts del SII con el lock y la
# transacción abiertos. Después se re-toma el lock y se revalida el estado.
# ---------------------------------------------------------------------------
def _espia_del_nip(db_session, monkeypatch, *, al_pedir=None):
    """Registra `lock`/`commit` de la sesión y `nip` cuando el SII falso atiende
    la consulta de `[credential]` (la única en modo sensible)."""
    from itcj2.apps.titulatec.services.sii.client import FakeSiiClient

    pasos = []
    commit_real, execute_real = db_session.commit, db_session.execute
    query_real = FakeSiiClient.query

    def _commit():
        pasos.append("commit")
        return commit_real()

    def _execute(stmt, *a, **k):
        if "pg_advisory_xact_lock" in str(stmt):
            pasos.append("lock")
        return execute_real(stmt, *a, **k)

    def _query(self, sql, params, **kw):
        if kw.get("sensitive"):
            pasos.append("nip")
            if al_pedir is not None:
                al_pedir()
        return query_real(self, sql, params, **kw)

    monkeypatch.setattr(db_session, "commit", _commit)
    monkeypatch.setattr(db_session, "execute", _execute)
    monkeypatch.setattr(FakeSiiClient, "query", _query)
    return pasos


def _nip_sin_lock(pasos):
    i = pasos.index("nip")
    previos = [p for p in pasos[:i] if p in ("lock", "commit")]
    assert previos and previos[-1] == "commit", f"el NIP se pidió con el lock: {pasos}"
    assert "lock" in pasos[i:], f"no re-tomó el lock para revalidar: {pasos}"


def test_se_pide_el_nip_al_sii_sin_el_lock_de_la_solicitud(
    db_session, make_cohort, make_user, sii, listo, monkeypatch,
):
    se = make_user()
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99580093")
    sii.alumno("99580093")
    pasos = _espia_del_nip(db_session, monkeypatch)

    ok, folio = _ers().approve(db_session, req.id, nip="", program_id=None, actor_id=se.id)

    assert ok is True and folio
    _nip_sin_lock(pasos)
    assert pasos.count("nip") == 1


def test_si_la_resuelven_mientras_se_pide_el_nip_no_se_crea_la_cuenta(
    db_session, make_cohort, make_user, sii, listo, monkeypatch,
):
    from sqlalchemy import text

    se = make_user()
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99580094")
    sii.alumno("99580094")

    def _otra_persona_la_rechaza():
        db_session.execute(text("UPDATE titulatec_enrollment_requests SET status = 'rejected' "
                                "WHERE id = :id"), {"id": req.id})

    _espia_del_nip(db_session, monkeypatch, al_pedir=_otra_persona_la_rechaza)

    ok, motivo = _ers().approve(db_session, req.id, nip="", program_id=None, actor_id=se.id)

    assert (ok, motivo) == (False, "Esa solicitud ya se resolvió.")
    assert _usuario(db_session, "99580094") is None
    assert listo == []


# ---------------------------------------------------------------------------
# sweep(): barrido periódico (acotado a una convocatoria: la BD de dev tiene
# solicitudes reales que el barrido global también vería)
# ---------------------------------------------------------------------------
def test_el_barrido_fuera_del_modo_sii_no_hace_nada(db_session, make_cohort, sii):
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99580060")
    sii.alumno("99580060")

    assert _svc().sweep(db_session, cohort_id=cohort.id) == {"checked": 0, "retried": 0}
    assert _checks(db_session, req) == []


def test_el_barrido_consulta_y_reintenta_lo_que_toca(db_session, make_cohort, sii, listo):
    cohort = make_cohort(status="open")
    hace = datetime.now() - timedelta(hours=3)

    sin_consulta = _make_req(db_session, cohort, control="99580061")
    sii.no_apta("99580061")
    con_error = _make_req(db_session, cohort, control="99580062")
    sii.no_apta("99580062")
    _check_row(db_session, con_error, status="error", attempt=2, retryable=True)
    colgada = _make_req(db_session, cohort, control="99580063")
    sii.no_apta("99580063")
    _check_row(db_session, colgada, status="pending", started_at=hace)

    # Lo que NO se toca (una apta tampoco: la aprueba Servicios Escolares):
    apta = _make_req(db_session, cohort, control="99580064")
    sii.alumno("99580064")
    _check_row(db_session, apta, status="apt", finished_at=hace)
    con_nota = _make_req(db_session, cohort, control="99580066",
                         review_note="El SII no devolvió NIP.")
    _check_row(db_session, con_nota, status="apt", finished_at=hace)
    en_tope = _make_req(db_session, cohort, control="99580067")
    _check_row(db_session, en_tope, status="error", attempt=5, retryable=True)
    no_apta = _make_req(db_session, cohort, control="99580068")
    _check_row(db_session, no_apta, status="not_apt")
    resuelta = _make_req(db_session, cohort, control="99580069", status="rejected")
    en_curso = _make_req(db_session, cohort, control="99580070")
    _check_row(db_session, en_curso, status="pending")
    # Spec §3.4: un error de configuración (reglas, consulta) no se reintenta.
    de_config = _make_req(db_session, cohort, control="99580078")
    sii.no_apta("99580078")
    _check_row(db_session, de_config, status="error", attempt=1, retryable=False)
    intactas = {r.id: r.last_check_id
                for r in (apta, con_nota, en_tope, no_apta, resuelta, en_curso, de_config)}

    out = _svc().sweep(db_session, cohort_id=cohort.id)

    assert out == {"checked": 1, "retried": 2}
    assert [c.attempt for c in _checks(db_session, sin_consulta)] == [1]
    assert _svc().latest_check(db_session, con_error).attempt == 3
    assert _svc().latest_check(db_session, colgada).attempt == 2
    for r in (apta, con_nota, en_tope, no_apta, resuelta, en_curso, de_config):
        db_session.refresh(r)
        assert r.last_check_id == intactas[r.id], r.control_number
        assert r.status in ("pending_review", "rejected")
    assert _usuario(db_session, "99580064") is None and listo == []


def test_el_barrido_retoma_una_consulta_colgada_aunque_este_en_el_tope(
    db_session, make_cohort, sii, modo_sii,
):
    """Revisión final (spec §8): una `pending` colgada en el tope de intentos
    no la retomaba nadie. El barrido la retoma (forzada)."""
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99580097")
    sii.no_apta("99580097")
    _check_row(db_session, req, status="pending", attempt=5,
               started_at=datetime.now() - _PENDING_STALE - timedelta(minutes=1))

    out = _svc().sweep(db_session, cohort_id=cohort.id)

    assert out["retried"] == 1
    assert _svc().latest_check(db_session, req).attempt == 6
    assert _svc().latest_check(db_session, req).status == "not_apt"


# ---------------------------------------------------------------------------
# Reconsulta masiva de errores (revisión final C12, spec §8):
# `titulatec sii-sweep --reconsultar-errores [--cohort ID]`
# ---------------------------------------------------------------------------
def test_reconsultar_errores_fuerza_toda_consulta_en_error_o_colgada(
    db_session, make_cohort, sii, modo_sii, monkeypatch,
):
    encoladas = []
    monkeypatch.setattr(
        "itcj2.apps.titulatec.services.eligibility_service.enqueue_check",
        lambda req_id, **kw: encoladas.append((req_id, kw)) or True)
    cohort = make_cohort(status="open")
    otra = make_cohort(status="open")
    colgada_hace = datetime.now() - _PENDING_STALE - timedelta(minutes=1)

    de_config = _make_req(db_session, cohort, control="99580100")
    _check_row(db_session, de_config, status="error", retryable=False)
    en_tope = _make_req(db_session, cohort, control="99580101")
    _check_row(db_session, en_tope, status="error", attempt=5, retryable=True)
    colgada = _make_req(db_session, cohort, control="99580102")
    _check_row(db_session, colgada, status="pending", attempt=5, started_at=colgada_hace)
    # Lo que NO se toca:
    en_curso = _make_req(db_session, cohort, control="99580103")
    _check_row(db_session, en_curso, status="pending")
    apta = _make_req(db_session, cohort, control="99580104")
    _check_row(db_session, apta, status="apt")
    sin_consulta = _make_req(db_session, cohort, control="99580105")
    resuelta = _make_req(db_session, cohort, control="99580106", status="rejected")
    _check_row(db_session, resuelta, status="error", retryable=False)
    ajena = _make_req(db_session, otra, control="99580107")
    _check_row(db_session, ajena, status="error", retryable=False)

    out = _svc().recheck_errors(db_session, cohort_id=cohort.id)

    assert out == {"queued": 3, "failed": 0}
    assert sorted(encoladas) == sorted((r.id, {"force": True})
                                       for r in (de_config, en_tope, colgada))
    assert sin_consulta.id not in [r for r, _ in encoladas]


def test_reconsultar_errores_cuenta_las_que_no_se_encolaron(
    db_session, make_cohort, sii, modo_sii, monkeypatch,
):
    monkeypatch.setattr(
        "itcj2.apps.titulatec.services.eligibility_service.enqueue_check",
        lambda req_id, **kw: False)
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99580108")
    _check_row(db_session, req, status="error", retryable=False)

    assert _svc().recheck_errors(db_session, cohort_id=cohort.id) == {"queued": 0,
                                                                       "failed": 1}


def test_reconsultar_errores_fuera_del_modo_sii_no_hace_nada(
    db_session, make_cohort, sii, _sin_celery,
):
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99580109")
    _check_row(db_session, req, status="error", retryable=False)

    assert _svc().recheck_errors(db_session, cohort_id=cohort.id) == {"queued": 0,
                                                                       "failed": 0}
    assert _sin_celery == []


def test_una_solicitud_que_revienta_no_detiene_el_barrido(
    db_session, make_cohort, sii, modo_sii, monkeypatch, caplog,
):
    cohort = make_cohort(status="open")
    mala = _make_req(db_session, cohort, control="99580074")
    buena = _make_req(db_session, cohort, control="99580075")
    sii.no_apta("99580074")
    sii.no_apta("99580075")
    db_session.commit()
    check_real = _svc().check

    def _check(db, req_id, **kw):
        if req_id == mala.id:
            raise RuntimeError("PWD=secreto")
        return check_real(db, req_id, **kw)

    monkeypatch.setattr(_svc(), "check", staticmethod(_check))

    with caplog.at_level("WARNING"):
        out = _svc().sweep(db_session, cohort_id=cohort.id)

    assert out["checked"] == 1
    assert _checks(db_session, buena) and not _checks(db_session, mala)
    assert "RuntimeError" in caplog.text and "secreto" not in caplog.text


def test_el_barrido_respeta_su_presupuesto_de_tiempo(db_session, make_cohort, sii, modo_sii):
    cohort = make_cohort(status="open")
    for control in ("99580076", "99580077"):
        _make_req(db_session, cohort, control=control)
        sii.no_apta(control)

    out = _svc().sweep(db_session, cohort_id=cohort.id, max_seconds=0)

    assert out == {"checked": 0, "retried": 0}
