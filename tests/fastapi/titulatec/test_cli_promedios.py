"""CLI `titulatec exportar-controles` y `titulatec cargar-promedios` (spec
2026-10-13-titulatec-promedios-design.md §5). La lógica vive en
`OfficialAverageService.load_rows` (`test_official_average_load.py`); aquí la
plomería: lectura del archivo (BOM, `;`, tabulador, encabezados alternos, la coma
decimal en un CSV separado por comas), `--actor`, `--dry-run` y el commit."""
from __future__ import annotations

import csv
import io
from decimal import Decimal

import pytest
from click.testing import CliRunner

from itcj2.cli.titulatec.promedios import (
    cargar_promedios_command,
    exportar_controles_command,
)

pytestmark = pytest.mark.usefixtures("audit_mark")

CABECERA = ["control", "nombre", "apellidos", "carrera", "estado", "tiene_proceso",
            "promedio_actual"]


def _req(db, cohort, *, control, status="pending_review", **kw):
    from itcj2.apps.titulatec.models import EnrollmentRequest

    row = EnrollmentRequest(
        cohort_id=cohort.id, control_number=control, first_name="EGRESADA",
        last_name="DELLOTE", middle_name="MATERNA", program_id=None,
        program_text="Ingenieria Ficticia", phone="6561234567",
        contact_email="lote@example.invalid", has_efirma=True, kind="unknown",
        status=status, verify_send_count=0)
    for k, v in kw.items():
        setattr(row, k, v)
    db.add(row)
    db.flush()
    return row


def _archivo(tmp_path, texto, *, bom=False, nombre="promedios.csv"):
    ruta = tmp_path / nombre
    ruta.write_bytes((b"\xef\xbb\xbf" if bom else b"") + texto.encode("utf-8"))
    return ruta


def _fila(db, control):
    from itcj2.apps.titulatec.models import OfficialAverage
    return db.get(OfficialAverage, control)


@pytest.fixture()
def actor(make_user):
    return make_user(username="tt_prom_cli_actor")


def _carga(args):
    return CliRunner().invoke(cargar_promedios_command, args)


# ---------------------------------------------------------------------------
# cargar-promedios
# ---------------------------------------------------------------------------
def test_actor_inexistente_sale_con_1(tmp_path, db_session, patched_session_local):
    archivo = _archivo(tmp_path, "control,promedio\n99720001,85\n")

    res = _carga([str(archivo), "--actor", "no_existe_nadie"])

    assert res.exit_code == 1
    assert "no_existe_nadie" in res.output


def test_archivo_sin_columnas_aborta_sin_escribir(
        tmp_path, db_session, patched_session_local, actor, make_cohort):
    _req(db_session, make_cohort(), control="99720002")
    archivo = _archivo(tmp_path, "matricula,nota\n99720002,85\n")

    res = _carga([str(archivo), "--actor", actor.username])

    assert res.exit_code == 1
    assert "control" in res.output and "promedio" in res.output
    assert _fila(db_session, "99720002") is None


@pytest.mark.parametrize("texto,bom", [
    ("control,promedio\n99720003,85.5\n", False),
    ("control;promedio\n99720003;85,5\n", True),               # Excel es-MX
    ("control\tpromedio\n99720003\t85,5\n", False),
    ("no_control,Promedio\n99720003,85.5\n", False),
    ("Numero_Control;Promedio Final\n99720003;85,5\n", True),
])
def test_separadores_bom_y_encabezados_alternos(
        tmp_path, db_session, patched_session_local, actor, make_cohort, texto, bom):
    _req(db_session, make_cohort(), control="99720003")
    archivo = _archivo(tmp_path, texto, bom=bom)

    res = _carga([str(archivo), "--actor", actor.username])

    assert res.exit_code == 0, res.output
    assert "99720003" in res.output
    assert _fila(db_session, "99720003").average == Decimal("85.50")


def test_coma_decimal_en_csv_separado_por_comas_es_invalido(
        tmp_path, db_session, patched_session_local, actor, make_cohort):
    """Review Focus 5: «85,5» sin comillas parte la fila en tres celdas; no se
    toma «85» ni «5»."""
    _req(db_session, make_cohort(), control="99720004")
    archivo = _archivo(tmp_path, "control,promedio\n99720004,85,5\n")

    res = _carga([str(archivo), "--actor", actor.username])

    assert res.exit_code == 1, res.output  # única fila e inválida: nada aterrizó
    assert _fila(db_session, "99720004") is None
    assert "Formato inválido" in res.output and "99720004" in res.output


def test_coma_decimal_entrecomillada_si_se_acepta(
        tmp_path, db_session, patched_session_local, actor, make_cohort):
    _req(db_session, make_cohort(), control="99720005")
    archivo = _archivo(tmp_path, 'control,promedio\n99720005,"85,5"\n')

    res = _carga([str(archivo), "--actor", actor.username])

    assert res.exit_code == 0, res.output
    assert _fila(db_session, "99720005").average == Decimal("85.50")


@pytest.mark.parametrize("extra", [[], ["--dry-run"]])
def test_archivo_donde_nada_aterriza_sale_con_1_y_titular_rojo(
        tmp_path, db_session, patched_session_local, actor, make_cohort, extra):
    _req(db_session, make_cohort(), control="99720020")
    archivo = _archivo(tmp_path, "control,promedio\n99720020,85,5\n99720021,abc\n")

    res = _carga([str(archivo), "--actor", actor.username, *extra])

    assert res.exit_code == 1, res.output
    assert "Ninguna fila requiere cambios o todas fueron rechazadas" in res.output
    assert "culpa" not in res.output and "se pudo cargar" not in res.output
    assert res.output.index("Ninguna fila") < res.output.index("Formato inválido: 2")
    assert _fila(db_session, "99720020") is None


def test_dry_run_no_escribe_nada(
        tmp_path, db_session, patched_session_local, actor, make_cohort,
        make_student, make_process):
    proc = make_process(make_student(control_number="99720006"), cohort=make_cohort())
    _req(db_session, make_cohort(), control="99720007")
    archivo = _archivo(tmp_path, "control,promedio\n99720006,85\n99720007,90\n")

    res = _carga([str(archivo), "--actor", actor.username, "--dry-run"])

    assert res.exit_code == 0, res.output
    assert "dry-run" in res.output.lower()
    assert "99720006" in res.output and "99720007" in res.output
    assert _fila(db_session, "99720006") is None and _fila(db_session, "99720007") is None
    db_session.refresh(proc)
    assert proc.final_average is None


def test_reporte_por_buckets_y_commit_al_final(
        tmp_path, db_session, patched_session_local, actor, make_cohort,
        make_student, make_process, monkeypatch):
    make_process(make_student(control_number="99720008"), cohort=make_cohort())
    _req(db_session, make_cohort(), control="99720009")
    archivo = _archivo(
        tmp_path,
        "control;promedio\n99720008;88\n99720009;91\n99720010;80\n99720011;50\n"
        "99720012;abc\n99720013;80\n99720013;81\n")
    commits = []
    real_commit = db_session.commit
    monkeypatch.setattr(db_session, "commit", lambda: (commits.append(1), real_commit())[1])

    res = _carga([str(archivo), "--actor", actor.username])

    assert res.exit_code == 0, res.output
    for etiqueta in ("Aplicados", "Guardados", "Sin solicitud", "Fuera de rango",
                     "Formato inválido", "Duplicados"):
        assert etiqueta in res.output
    assert commits == [1]


# ---------------------------------------------------------------------------
# exportar-controles
# ---------------------------------------------------------------------------
def _exporta(*args):
    res = CliRunner().invoke(exportar_controles_command, list(args))
    assert res.exit_code == 0, res.output
    return res


def _filas(texto):
    return {r["control"]: r for r in csv.DictReader(io.StringIO(texto))}


def test_exporta_controles_con_solicitud_no_rechazada_o_proceso(
        db_session, patched_session_local, make_cohort, make_student, make_process):
    from itcj2.apps.titulatec.services.official_average_service import (
        OfficialAverageService as Svc,
    )

    _req(db_session, make_cohort(), control="99730001")
    _req(db_session, make_cohort(), control="99730002", status="rejected")
    make_process(make_student(control_number="99730003"), cohort=make_cohort())
    _req(db_session, make_cohort(), control="99730004")
    _req(db_session, make_cohort(), control="99730004", status="approved")
    Svc.upsert(db_session, "99730004", Decimal("87.5"), actor_id=None)

    res = _exporta()
    filas = _filas(res.output)

    assert res.output.splitlines()[0] == ",".join(CABECERA)
    assert "99730002" not in filas                       # solo rechazada
    assert filas["99730001"]["tiene_proceso"] == "no"
    assert filas["99730001"]["promedio_actual"] == ""
    assert filas["99730001"]["apellidos"] == "DELLOTE MATERNA"
    assert filas["99730003"]["tiene_proceso"] == "si"
    assert filas["99730004"]["promedio_actual"] == "87.50"
    assert sum(1 for ln in res.output.splitlines() if "99730004" in ln) == 1


def test_salida_a_archivo_lleva_bom_y_cuenta(
        tmp_path, db_session, patched_session_local, make_cohort):
    _req(db_session, make_cohort(), control="99730005", program_text="Ingeniería Ñandú")
    destino = tmp_path / "controles.csv"

    res = _exporta("--salida", str(destino))

    assert "99730005" not in res.output                  # va al archivo, no a pantalla
    crudo = destino.read_bytes()
    assert crudo.startswith(b"\xef\xbb\xbf")
    assert "Ingeniería Ñandú" in crudo.decode("utf-8-sig")
    assert "99730005" in crudo.decode("utf-8-sig")


def test_el_export_se_puede_recargar_con_cargar_promedios(
        tmp_path, db_session, patched_session_local, actor, make_cohort):
    """El archivo exportado con una columna `promedio` agregada es entrada válida."""
    _req(db_session, make_cohort(), control="99730006")
    destino = tmp_path / "controles.csv"
    _exporta("--salida", str(destino))
    filas = list(csv.reader(io.StringIO(destino.read_text("utf-8-sig"))))
    filas[0].append("promedio")
    for f in filas[1:]:
        f.append("92,5" if f[0] == "99730006" else "")
    salida = io.StringIO()
    csv.writer(salida, delimiter=";", lineterminator="\n").writerows(filas)
    archivo = _archivo(tmp_path, salida.getvalue(), bom=True, nombre="lleno.csv")

    res = _carga([str(archivo), "--actor", actor.username])

    assert res.exit_code == 0, res.output
    assert _fila(db_session, "99730006").average == Decimal("92.50")
