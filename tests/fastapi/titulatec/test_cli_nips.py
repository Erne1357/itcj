"""CLI `titulatec exportar-sin-cuenta` y `titulatec cargar-nips` (spec 2026-10-13 N §5.3).

La lógica vive en `NipStashService.load_rows` (`test_nip_stash_load.py`); aquí
solo la plomería: llave, `--actor`, lectura del archivo (BOM, `;`, tabulador,
encabezados alternos, el NIP «0123» que Excel dejó en «123»), token de Graph,
`--dry-run` y que NINGUNA salida lleve un NIP. `CliRunner` +
`patched_session_local` (patrón de `test_cli_prior_clearances.py`).
"""
from __future__ import annotations

import csv
import io
import json
import re

import pytest
from click.testing import CliRunner

from itcj2.cli.titulatec import cargar_nips_command, exportar_sin_cuenta_command
from tests.fastapi.titulatec.conftest import audit_query

pytestmark = pytest.mark.usefixtures("audit_mark")

CENTINELA = "7391"
_CENTINELA_RE = re.compile(rf"(?<!\d){CENTINELA}(?!\d)")
TOKEN = "itcj2.apps.titulatec.services.email_helper._acquire_token"


def _make_req(db_session, cohort, *, control, status="pending_review", **kw):
    from itcj2.apps.titulatec.models import EnrollmentRequest

    row = EnrollmentRequest(
        cohort_id=cohort.id, control_number=control,
        first_name="EGRESADA", last_name="DELLOTE", middle_name=None,
        program_id=None, program_text="Ingenieria Ficticia",
        phone="6561234567", contact_email="lote@example.invalid",
        has_efirma=True, kind="unknown", status=status, verify_send_count=0,
    )
    for k, v in kw.items():
        setattr(row, k, v)
    db_session.add(row)
    db_session.flush()
    return row


def _cuenta(db_session, control):
    from itcj2.core.models.user import User
    from itcj2.core.utils.security import hash_nip

    user = User(username=control, control_number=control, first_name="YA",
                last_name="EXISTIA", password_hash=hash_nip("9999"), is_active=True,
                must_change_password=False)
    db_session.add(user)
    db_session.flush()
    return user


def _archivo(tmp_path, texto, *, bom=False, nombre="nips.csv"):
    ruta = tmp_path / nombre
    ruta.write_bytes((b"\xef\xbb\xbf" if bom else b"") + texto.encode("utf-8"))
    return ruta


def _hay_nip(db_session, control) -> bool:
    from itcj2.apps.titulatec.models import NipStash
    return db_session.get(NipStash, control) is not None


@pytest.fixture()
def actor(make_user):
    return make_user(username="tt_cli_actor")


def _carga(args, token="tok"):
    from unittest.mock import patch

    with patch(TOKEN, return_value=token):
        return CliRunner().invoke(cargar_nips_command, args)


# ---------------------------------------------------------------------------
# cargar-nips: llave, actor, archivo
# ---------------------------------------------------------------------------
def test_sin_llave_sale_con_1_antes_de_leer_el_archivo(
    tmp_path, db_session, patched_session_local, actor, monkeypatch,
):
    from itcj2.config import get_settings

    monkeypatch.setattr(get_settings(), "TITULATEC_NIP_STASH_KEY", None)
    # Un archivo ilegible como CSV: si se leyera, el error sería otro.
    archivo = _archivo(tmp_path, "esto no tiene encabezados validos\n")

    res = _carga([str(archivo), "--actor", actor.username])

    assert res.exit_code == 1
    assert "TITULATEC_NIP_STASH_KEY" in res.output
    assert "encabezado" not in res.output.lower()


def test_actor_inexistente_sale_con_1(tmp_path, db_session, patched_session_local, llave):
    archivo = _archivo(tmp_path, "control,nip\n99590001,1234\n")

    res = _carga([str(archivo), "--actor", "no_existe_nadie"])

    assert res.exit_code == 1
    assert "no_existe_nadie" in res.output


def test_archivo_sin_columnas_aborta_sin_escribir(
    tmp_path, db_session, patched_session_local, llave, actor, make_cohort,
):
    _make_req(db_session, make_cohort(status="open"), control="99590002")
    archivo = _archivo(tmp_path, "matricula,clave\n99590002,1234\n")

    res = _carga([str(archivo), "--actor", actor.username])

    assert res.exit_code == 1
    assert "control" in res.output and "nip" in res.output
    assert not _hay_nip(db_session, "99590002")


@pytest.mark.parametrize("texto,bom", [
    ("control,nip\n99590003,{n}\n", False),
    ("control;nip\n99590003;{n}\n", True),                # Excel es-MX
    ("control\tnip\n99590003\t{n}\n", False),
    ("no_control,NIP\n99590003,{n}\n", False),
    ("Numero_Control;Nip\n99590003;{n}\n", True),
])
def test_separadores_bom_y_encabezados_alternos(
    tmp_path, db_session, patched_session_local, llave, actor, make_cohort, texto, bom,
):
    _make_req(db_session, make_cohort(status="open"), control="99590003")
    archivo = _archivo(tmp_path, texto.format(n=CENTINELA), bom=bom)

    res = _carga([str(archivo), "--actor", actor.username])

    assert res.exit_code == 0, res.output
    assert "99590003" in res.output
    assert _hay_nip(db_session, "99590003")
    assert not _CENTINELA_RE.search(res.output)


def test_nip_sin_cero_de_excel_cae_en_invalido_con_la_pista(
    tmp_path, db_session, patched_session_local, llave, actor, make_cohort,
):
    _make_req(db_session, make_cohort(status="open"), control="99590004")
    archivo = _archivo(tmp_path, "control;nip\nL99590004;123\n", bom=True)

    res = _carga([str(archivo), "--actor", actor.username])

    # Única fila y es inválida: ahora sale con 1 (nada se pudo cargar).
    assert res.exit_code == 1, res.output
    assert "NIP inválido" in res.output
    assert "99590004" in res.output and "Excel" in res.output
    assert not _hay_nip(db_session, "99590004")


def test_reporte_con_conteos_por_grupo(
    tmp_path, db_session, patched_session_local, llave, actor, make_cohort,
):
    cohort = make_cohort(status="open")
    _make_req(db_session, cohort, control="99590005")
    _make_req(db_session, make_cohort(status="closed"), control="99590006",
              status="rejected")
    _cuenta(db_session, "99590007")
    archivo = _archivo(tmp_path, "control,nip\n99590005,1234\n99590006,1234\n"
                                 "99590007,1234\n99590008,1234\n99590009,12\n")

    res = _carga([str(archivo), "--actor", actor.username])

    assert res.exit_code == 0, res.output
    for etiqueta in ("Acceso dado ahora: 0", "Guardados para la aprobación: 1",
                     "Guardados (solicitud rechazada): 1", "Ya tienen cuenta: 1",
                     "Sin solicitud: 1", "NIP inválido: 1", "Duplicados: 0",
                     "Fallaron: 0"):
        assert etiqueta in res.output, etiqueta


# ---------------------------------------------------------------------------
# cargar-nips: dry-run, correo, NIP fuera de toda salida
# ---------------------------------------------------------------------------
def test_dry_run_no_escribe_ni_audita_ni_pide_token(
    tmp_path, db_session, patched_session_local, llave, actor, make_cohort,
):
    _make_req(db_session, make_cohort(status="open"), control="99590010")
    antes = audit_query(db_session).count()
    archivo = _archivo(tmp_path, f"control,nip\n99590010,{CENTINELA}\n")

    res = _carga([str(archivo), "--actor", actor.username, "--dry-run"], token=None)

    assert res.exit_code == 0, res.output
    assert "[dry-run]" in res.output and "99590010" in res.output
    assert not _hay_nip(db_session, "99590010")
    assert audit_query(db_session).count() == antes
    assert not _CENTINELA_RE.search(res.output)


def test_sin_token_de_graph_aborta_antes_de_escribir(
    tmp_path, db_session, patched_session_local, llave, actor, make_cohort,
):
    _make_req(db_session, make_cohort(status="open"), control="99590011")
    archivo = _archivo(tmp_path, "control,nip\n99590011,1234\n")

    res = _carga([str(archivo), "--actor", actor.username], token=None)

    assert res.exit_code == 1
    assert "correo" in res.output.lower() and "--sin-correo" in res.output
    assert not _hay_nip(db_session, "99590011")


def test_sin_correo_no_pide_token(
    tmp_path, db_session, patched_session_local, llave, actor, make_cohort,
):
    _make_req(db_session, make_cohort(status="open"), control="99590012")
    archivo = _archivo(tmp_path, "control,nip\n99590012,1234\n")

    res = _carga([str(archivo), "--actor", actor.username, "--sin-correo"], token=None)

    assert res.exit_code == 0, res.output
    assert _hay_nip(db_session, "99590012")


def test_el_acceso_dado_sale_en_el_reporte_sin_el_nip(
    tmp_path, db_session, patched_session_local, llave, actor, make_cohort, listo,
    espia_correo,
):
    _make_req(db_session, make_cohort(status="open"), control="99590013",
              status="awaiting_access", reviewed_by_id=actor.id)
    archivo = _archivo(tmp_path, f"control,nip\n99590013,{CENTINELA}\n")

    res = _carga([str(archivo), "--actor", actor.username])

    assert res.exit_code == 0, res.output
    assert "Acceso dado ahora: 1" in res.output and "99590013" in res.output
    assert not _CENTINELA_RE.search(res.output)
    assert len(espia_correo) == 1
    for f in audit_query(db_session).all():
        assert not _CENTINELA_RE.search(json.dumps(f.payload, default=str))


def test_falla_el_correo_sale_con_1_y_lo_dice(
    tmp_path, db_session, patched_session_local, llave, actor, make_cohort, listo,
    monkeypatch,
):
    from itcj2.apps.titulatec.services.email_helper import TitulaTecEmailHelper

    monkeypatch.setattr(TitulaTecEmailHelper, "send_enrollment_approved",
                        staticmethod(lambda *a, **k: False))
    _make_req(db_session, make_cohort(status="open"), control="99590014",
              status="awaiting_access", reviewed_by_id=actor.id)
    archivo = _archivo(tmp_path, f"control,nip\n99590014,{CENTINELA}\n")

    res = _carga([str(archivo), "--actor", actor.username])

    assert res.exit_code == 1
    assert "Fallaron: 1" in res.output and "99590014" in res.output
    assert not _CENTINELA_RE.search(res.output)


# ---------------------------------------------------------------------------
# exportar-sin-cuenta
# ---------------------------------------------------------------------------
def _exporta(args=()):
    return CliRunner().invoke(exportar_sin_cuenta_command, list(args))


def _filas(texto):
    return list(csv.DictReader(io.StringIO(texto.lstrip("﻿"))))


def test_exporta_solo_vivas_sin_cuenta(
    db_session, patched_session_local, llave, make_cohort,
):
    cohort = make_cohort(status="open")
    _make_req(db_session, cohort, control="99600001", status="awaiting_access")
    _make_req(db_session, cohort, control="99600002", status="pending_review")
    _make_req(db_session, cohort, control="99600003", status="rejected")
    _make_req(db_session, cohort, control="99600004", status="pending_review")
    _cuenta(db_session, "99600004")

    res = _exporta()

    assert res.exit_code == 0, res.output
    filas = [f for f in _filas(res.output) if f["control"].startswith("996000")]
    assert sorted(f["control"] for f in filas) == ["99600001", "99600002"]
    assert list(filas[0]) == ["control", "nombre", "apellidos", "carrera", "estado",
                              "convocatoria", "nip_precargado"]
    f1 = next(f for f in filas if f["control"] == "99600001")
    assert f1["nombre"] == "EGRESADA" and f1["apellidos"] == "DELLOTE"
    assert f1["carrera"] == "Ingenieria Ficticia"
    assert f1["estado"] == "awaiting_access"
    assert f1["convocatoria"] == cohort.name


def test_exporta_marca_si_hay_nip_precargado_sin_descifrarlo(
    db_session, patched_session_local, llave, make_cohort,
):
    from itcj2.apps.titulatec.services.nip_stash_service import NipStashService

    cohort = make_cohort(status="open")
    _make_req(db_session, cohort, control="99600005")
    _make_req(db_session, cohort, control="99600006")
    NipStashService.put(db_session, "99600005", CENTINELA, actor_id=None)

    res = _exporta()

    por_control = {f["control"]: f["nip_precargado"] for f in _filas(res.output)}
    assert por_control["99600005"] == "si" and por_control["99600006"] == "no"
    assert not _CENTINELA_RE.search(res.output)


def test_exporta_a_archivo_utf8_con_bom(
    tmp_path, db_session, patched_session_local, llave, make_cohort,
):
    _make_req(db_session, make_cohort(status="open"), control="99600007",
              program_text="Ingeniería Eléctrica")
    ruta = tmp_path / "sin_cuenta.csv"

    res = _exporta(["--salida", str(ruta)])

    assert res.exit_code == 0, res.output
    crudo = ruta.read_bytes()
    assert crudo.startswith(b"\xef\xbb\xbf")
    assert "Ingeniería Eléctrica" in crudo.decode("utf-8-sig")
    assert "99600007" not in res.output, "con --salida el CSV no sale por stdout"


def test_linea_por_fila_en_vivo_antes_del_resumen_y_sin_nip(
    tmp_path, db_session, patched_session_local, llave, actor, make_cohort, listo,
    espia_correo,
):
    _make_req(db_session, make_cohort(status="open"), control="99590020",
              status="awaiting_access", reviewed_by_id=actor.id)
    archivo = _archivo(tmp_path, f"control,nip\n99590020,{CENTINELA}\n")

    res = _carga([str(archivo), "--actor", actor.username])

    assert res.exit_code == 0, res.output
    en_vivo = "[Acceso dado ahora] 99590020"
    assert en_vivo in res.output
    assert res.output.index(en_vivo) < res.output.index("Acceso dado ahora: 1")
    assert not _CENTINELA_RE.search(res.output)


def test_dry_run_no_imprime_lineas_en_vivo(
    tmp_path, db_session, patched_session_local, llave, actor, make_cohort, listo,
):
    _make_req(db_session, make_cohort(status="open"), control="99590021",
              status="awaiting_access", reviewed_by_id=actor.id)
    archivo = _archivo(tmp_path, f"control,nip\n99590021,{CENTINELA}\n")

    res = _carga([str(archivo), "--actor", actor.username, "--dry-run"])

    assert "[Acceso dado ahora]" not in res.output


@pytest.mark.parametrize("extra", [[], ["--dry-run"]])
def test_archivo_donde_nada_se_puede_cargar_sale_con_1_y_titular_rojo(
    tmp_path, db_session, patched_session_local, llave, actor, extra,
):
    archivo = _archivo(tmp_path, "control,nip\n99590040,12\n99590041,abc\n")

    res = _carga([str(archivo), "--actor", actor.username, *extra])

    assert res.exit_code == 1, res.output
    assert "Ninguna fila se pudo cargar" in res.output
    assert res.output.index("Ninguna fila") < res.output.index("NIP inválido: 2")
