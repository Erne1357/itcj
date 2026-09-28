"""`titulatec rename-documents [--dry-run]` (brief 2026-09-28, nombres
`{control}_{TIPO}.{ext}`).

Por cada fila `Document` calcula el nombre esperado en la MISMA carpeta:

* ya coincide                          -> `ya_bien`
* el viejo existe y el destino no      -> renombra en disco + `file_path` -> `renombrados`
* el destino ya existe                 -> `conflictos` (no toca nada)
* el viejo no existe                   -> `faltantes`  (no toca la fila)

`--dry-run` no escribe NADA (ni disco ni BD). Idempotente. Imprime conteos e
ids, nunca contenido. Ante una excepcion: rollback, deshace los renombres del
lote sin commitear y sale con 1.

La sesion del comando es la del test (`patched_session_local`): el comando
abre `SessionLocal()` con import local, igual que las rutas.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from click.testing import CliRunner

from itcj2.cli.titulatec import titulatec_cli


@pytest.fixture()
def esc(patched_session_local, db_session, seed_phase_defs, seed_document_types,
        make_cohort, make_student, make_process, make_document, tmp_path, monkeypatch):
    """Un alumno con sus 3 documentos iniciales con NOMBRE VIEJO en disco."""
    monkeypatch.setattr("itcj2.apps.titulatec.utils.storage._base", lambda: tmp_path)

    def _build(control=None, docs=("birth_certificate", "high_school_cert", "curp"),
               write=True):
        seed_phase_defs()
        seed_document_types()
        student = make_student(control_number=control)
        proc = make_process(student, cohort=make_cohort(), current_phase=1)
        carpeta = f"{proc.cohort.period_code}/{student.control_number}/documents"
        rows = {}
        for code in docs:
            rows[code] = make_document(proc, type_code=code,
                                       file_path=f"{carpeta}/{code}.pdf")
            if write:
                dest = tmp_path / rows[code].file_path
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(f"%PDF-1.4 {code}".encode())
        return SimpleNamespace(student=student, process=proc, docs=rows, base=tmp_path,
                               carpeta=carpeta, control=student.control_number)
    return _build


def _run(*args):
    return CliRunner().invoke(titulatec_cli, ["rename-documents", *args])


def _paths(db, docs) -> dict:
    from itcj2.apps.titulatec.models import Document
    db.expire_all()
    return {code: db.get(Document, d.id).file_path for code, d in docs.items()}


def _disk(base, carpeta) -> list:
    return sorted(p.name for p in (base / carpeta).iterdir())


def _conteo(output: str, clave: str) -> int:
    for line in output.splitlines():
        line = line.strip()
        if line.startswith(clave + ":"):
            return int(line.split(":", 1)[1].split()[0])
    raise AssertionError(f"sin la linea «{clave}:» en:\n{output}")


def _ids(output: str, clave: str) -> set[int]:
    for line in output.splitlines():
        line = line.strip()
        if line.startswith(clave + ":") and "ids:" in line:
            return {int(x) for x in line.split("ids:", 1)[1].split(",")}
    return set()


class TestDryRun:
    def test_reporta_y_no_toca_ni_disco_ni_bd(self, esc, db_session):
        e = esc()
        antes_bd = _paths(db_session, e.docs)
        antes_disco = _disk(e.base, e.carpeta)

        res = _run("--dry-run")

        assert res.exit_code == 0, res.output
        assert _conteo(res.output, "renombrados") == 3
        assert "dry-run" in res.output.lower()
        assert _paths(db_session, e.docs) == antes_bd
        assert _disk(e.base, e.carpeta) == antes_disco


class TestCorridaReal:
    def test_renombra_en_disco_y_actualiza_file_path(self, esc, db_session):
        e = esc()

        res = _run()

        assert res.exit_code == 0, res.output
        assert _disk(e.base, e.carpeta) == sorted([
            f"{e.control}_ACTA.pdf", f"{e.control}_CERTIFICADO.pdf", f"{e.control}_CURP.pdf",
        ])
        assert _paths(db_session, e.docs) == {
            "birth_certificate": f"{e.carpeta}/{e.control}_ACTA.pdf",
            "high_school_cert": f"{e.carpeta}/{e.control}_CERTIFICADO.pdf",
            "curp": f"{e.carpeta}/{e.control}_CURP.pdf",
        }
        assert (e.base / e.carpeta / f"{e.control}_CURP.pdf").read_bytes() == b"%PDF-1.4 curp"

    def test_la_segunda_corrida_es_todo_ya_bien(self, esc, db_session):
        e = esc()
        primera = _run()
        assert primera.exit_code == 0, primera.output

        segunda = _run()

        assert segunda.exit_code == 0, segunda.output
        assert _conteo(segunda.output, "renombrados") == 0
        assert _conteo(segunda.output, "conflictos") == 0
        assert _conteo(segunda.output, "ya_bien") >= 3
        # La BD de dev trae documentos REALES cuyo archivo no esta en `tmp_path`
        # (salen como faltantes, sin tocarse); los del test NO pueden estar ahi.
        faltantes = _ids(segunda.output, "faltantes")
        assert not faltantes & {d.id for d in e.docs.values()}
        assert _paths(db_session, e.docs) == {
            code: f"{e.carpeta}/{e.control}_{label}.pdf"
            for code, label in (("birth_certificate", "ACTA"),
                                ("high_school_cert", "CERTIFICADO"), ("curp", "CURP"))
        }

    def test_otro_tipo_usa_el_codigo_en_mayusculas(self, esc, db_session):
        e = esc(docs=("ine",))

        res = _run()

        assert res.exit_code == 0, res.output
        assert _disk(e.base, e.carpeta) == [f"{e.control}_INE.pdf"]


class TestFaltanteYConflicto:
    def test_faltante_se_cuenta_con_su_id_y_no_se_toca(self, esc, db_session):
        e = esc(docs=("curp",), write=False)
        antes = _paths(db_session, e.docs)

        res = _run()

        assert res.exit_code == 0, res.output
        assert e.docs["curp"].id in _ids(res.output, "faltantes")
        assert _paths(db_session, e.docs) == antes

    def test_conflicto_se_cuenta_con_su_id_y_no_se_toca(self, esc, db_session):
        e = esc(docs=("curp",))
        destino = e.base / e.carpeta / f"{e.control}_CURP.pdf"
        destino.write_bytes(b"%PDF-1.4 el que ya estaba")
        antes = _paths(db_session, e.docs)

        res = _run()

        assert res.exit_code == 0, res.output
        assert _ids(res.output, "conflictos") == {e.docs["curp"].id}
        assert _paths(db_session, e.docs) == antes
        assert (e.base / e.carpeta / "curp.pdf").read_bytes() == b"%PDF-1.4 curp"
        assert destino.read_bytes() == b"%PDF-1.4 el que ya estaba"

    def test_nunca_imprime_contenido(self, esc, db_session):
        e = esc(docs=("curp",))

        res = _run()

        assert "%PDF" not in res.output


class TestExcepcion:
    def test_rollback_deshace_los_renombres_del_lote_y_sale_con_1(self, esc, db_session,
                                                                  monkeypatch):
        e = esc()
        antes = _disk(e.base, e.carpeta)

        def _falla():
            raise RuntimeError("se cayo la BD")
        monkeypatch.setattr(db_session, "commit", _falla)

        res = _run()

        assert res.exit_code == 1, res.output
        assert _disk(e.base, e.carpeta) == antes
