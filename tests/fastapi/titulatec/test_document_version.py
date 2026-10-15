"""La versión de un documento CONTINÚA tras borrarlo y volverlo a subir (D7,
spec 2026-10-15-titulatec-reemplazo-cotejo-design.md §4.6 y §6).

EL DEFECTO. `DocumentService.delete` borra la fila, y la siguiente subida creaba
una fila NUEVA con `version=1` aunque fuera la quinta subida de ese tipo (en dev
había 120 documentos `version=1` con un `document_deleted` previo). La bandeja y
el expediente leían «v1» de un documento que ya iba en su tercer archivo.

AHORA. Al CREAR la fila, `save()` arranca en `1 + max(subidas previas de ese
(proceso, tipo), mayor payload.version de esas subidas)` -- una sola consulta a
`titulatec_process_events`, y solo en ese camino. Actualizar una fila existente
sigue siendo `version + 1`.

LOS DATOS QUE YA EXISTEN los corrige la migración `tt20261015a` con su constante
`VERSION_FIX_SQL` (`GREATEST(version, nº de document_uploaded)`). Aquí se ejecuta
ESA MISMA constante -- importada por ruta, no copiada -- sobre filas sembradas por
la prueba. La base de dev es compartida y trae datos reales: nunca se afirma un
total de la tabla, solo el valor de las filas sembradas aquí.
"""
from __future__ import annotations

import importlib.util
import inspect
from pathlib import Path

import pytest
from sqlalchemy import event, text

from tests.fastapi.titulatec._pdf_samples import small_pdf

_MIGRACION = (Path(__file__).resolve().parents[3] / "migrations" / "versions"
              / "tt20261015a_titulatec_doc_replacement.py")


def _migracion():
    """El módulo de la migración, cargado por ruta (no es un paquete importable)."""
    spec = importlib.util.spec_from_file_location("tt20261015a_titulatec_doc_replacement",
                                                  _MIGRACION)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def base(tmp_path, monkeypatch):
    """`TITULATEC_UPLOAD_PATH` -> `tmp_path` (mismo truco que test_document_storage)."""
    monkeypatch.setattr("itcj2.apps.titulatec.utils.storage._base", lambda: tmp_path)
    return tmp_path


@pytest.fixture()
def proceso(base, db_session, seed_phase_defs, seed_document_types, make_cohort,
            make_student, make_process):
    seed_phase_defs()
    seed_document_types()
    cohort = make_cohort()

    def _build(current_phase=1):
        student = make_student()
        return make_process(student, cohort=cohort, current_phase=current_phase), student

    return _build


def _subir(db, proc, student, code="curp"):
    from itcj2.apps.titulatec.services.document_service import DocumentService
    return DocumentService.save(db, proc, code, raw=small_pdf(),
                                original_name=f"{code}.pdf",
                                content_type="application/pdf",
                                uploaded_by_id=student.id)


def _borrar(db, proc, student, code="curp"):
    from itcj2.apps.titulatec.services.document_service import DocumentService
    assert DocumentService.delete(db, proc.id, code, actor_id=student.id) is True


def _version(db, process_id, code="curp"):
    from itcj2.apps.titulatec.models import Document
    db.expire_all()
    return (db.query(Document.version)
            .filter_by(process_id=process_id, type_code=code).scalar())


def _versiones_en_bitacora(db, process_id, code="curp") -> list:
    from itcj2.apps.titulatec.models import ProcessEvent
    return [(e.payload or {}).get("version") for e in
            db.query(ProcessEvent)
            .filter_by(process_id=process_id, event_type="document_uploaded")
            .order_by(ProcessEvent.id)
            if (e.payload or {}).get("type_code") == code]


def _evento(db, process_id, event_type, payload):
    from itcj2.apps.titulatec.models import ProcessEvent
    db.add(ProcessEvent(process_id=process_id, actor_id=None, event_type=event_type,
                        phase_number=1, payload=payload))
    db.flush()


# ---------------------------------------------------------------------------
# DocumentService.save
# ---------------------------------------------------------------------------
class TestVersionAlSubir:
    def test_la_primera_subida_sigue_siendo_v1(self, db_session, proceso):
        proc, student = proceso()

        doc = _subir(db_session, proc, student)

        assert doc.version == 1
        assert _versiones_en_bitacora(db_session, proc.id) == [1]

    def test_borrar_y_volver_a_subir_continua_la_numeracion(self, db_session, proceso):
        proc, student = proceso()
        _subir(db_session, proc, student)
        _subir(db_session, proc, student)
        assert _version(db_session, proc.id) == 2

        _borrar(db_session, proc, student)
        _subir(db_session, proc, student)

        assert _version(db_session, proc.id) == 3
        # El evento de la subida lleva la versión NUEVA, no un «1» repetido.
        assert _versiones_en_bitacora(db_session, proc.id) == [1, 2, 3]

    def test_borrar_varias_veces_sigue_contando(self, db_session, proceso):
        proc, student = proceso()
        for esperada in (1, 2, 3):
            _subir(db_session, proc, student)
            assert _version(db_session, proc.id) == esperada
            _borrar(db_session, proc, student)

        _subir(db_session, proc, student)

        assert _version(db_session, proc.id) == 4

    def test_solo_cuentan_las_subidas_de_ese_tipo_y_ese_proceso(self, db_session, proceso):
        proc_a, alumno_a = proceso()
        proc_b, alumno_b = proceso()
        _subir(db_session, proc_a, alumno_a)
        _subir(db_session, proc_a, alumno_a)
        _borrar(db_session, proc_a, alumno_a)

        # Otro proceso, mismo tipo: arranca en 1.
        _subir(db_session, proc_b, alumno_b)
        assert _version(db_session, proc_b.id) == 1
        # Mismo proceso, otro tipo: arranca en 1.
        _subir(db_session, proc_a, alumno_a, code="birth_certificate")
        assert _version(db_session, proc_a.id, "birth_certificate") == 1
        # Y el borrado sigue su cuenta.
        _subir(db_session, proc_a, alumno_a)
        assert _version(db_session, proc_a.id) == 3

    def test_respeta_la_mayor_version_de_la_bitacora(self, db_session, proceso):
        """Una sola subida en la bitácora, pero con `version: 7` en el payload
        (dato heredado): la siguiente es la 8, nunca la 2."""
        proc, student = proceso()
        _evento(db_session, proc.id, "document_uploaded",
                {"type_code": "curp", "original_name": "x.pdf", "version": 7})
        # Ruido que NO cuenta: otro tipo, otro evento, payload vacío o raro.
        _evento(db_session, proc.id, "document_uploaded",
                {"type_code": "birth_certificate", "version": 40})
        _evento(db_session, proc.id, "document_deleted", {"type_code": "curp"})
        _evento(db_session, proc.id, "document_uploaded", None)
        _evento(db_session, proc.id, "document_uploaded", {"type_code": "curp",
                                                           "version": "99"})

        _subir(db_session, proc, student)

        # Dos subidas de curp en la bitácora (la de 7 y la de versión ilegible):
        # max(2, 7) + 1.
        assert _version(db_session, proc.id) == 8

    def test_actualizar_una_fila_existente_sigue_siendo_mas_uno(self, db_session, proceso,
                                                                make_document):
        """El camino de actualización no mira la bitácora: `version + 1`."""
        proc, student = proceso()
        make_document(proc, type_code="curp", version=5)

        _subir(db_session, proc, student)

        assert _version(db_session, proc.id) == 6

    def test_solo_crear_la_fila_consulta_la_bitacora_y_una_sola_vez(self, db_session,
                                                                    proceso):
        proc, student = proceso()

        def _lecturas_de_eventos(fn) -> int:
            sentencias = []

            def _ver(_conn, _cursor, statement, *_a):
                sentencias.append(statement)

            conn = db_session.connection()
            event.listen(conn, "before_cursor_execute", _ver)
            try:
                fn()
            finally:
                event.remove(conn, "before_cursor_execute", _ver)
            return sum(1 for s in sentencias
                       if s.lstrip().upper().startswith("SELECT")
                       and "titulatec_process_events" in s)

        assert _lecturas_de_eventos(lambda: _subir(db_session, proc, student)) == 1
        assert _lecturas_de_eventos(lambda: _subir(db_session, proc, student)) == 0


# ---------------------------------------------------------------------------
# Migración tt20261015a: la corrección de los datos que ya existen
# ---------------------------------------------------------------------------
class TestMigracion:
    def test_encadena_tras_tt20261013b_y_ejecuta_la_correccion(self):
        mod = _migracion()

        assert mod.revision == "tt20261015a"
        assert mod.down_revision == "tt20261013b"
        assert "VERSION_FIX_SQL" in inspect.getsource(mod.upgrade)
        # La corrección de versión NO se revierte: el downgrade solo quita la columna.
        assert "VERSION_FIX_SQL" not in inspect.getsource(mod.downgrade)

    def test_version_fix_sql_sube_a_las_subidas_y_nunca_baja(
            self, db_session, proceso, make_document):
        proc_a, _ = proceso()
        proc_b, _ = proceso()
        # A/curp: v1 con 3 subidas (+ un borrado y una subida de otro tipo).
        a_curp = make_document(proc_a, type_code="curp", version=1)
        for _ in range(3):
            _evento(db_session, proc_a.id, "document_uploaded", {"type_code": "curp"})
        _evento(db_session, proc_a.id, "document_deleted", {"type_code": "curp"})
        # A/acta: v1 con su única subida -> no cambia.
        a_acta = make_document(proc_a, type_code="birth_certificate", version=1)
        _evento(db_session, proc_a.id, "document_uploaded",
                {"type_code": "birth_certificate"})
        # A/certificado: v5 con 2 subidas -> GREATEST, no baja.
        a_cert = make_document(proc_a, type_code="high_school_cert", version=5)
        for _ in range(2):
            _evento(db_session, proc_a.id, "document_uploaded",
                    {"type_code": "high_school_cert"})
        # B/curp: v1 sin bitácora -> no cambia.
        b_curp = make_document(proc_b, type_code="curp", version=1)
        # B/acta: v2 con 4 subidas -> 4.
        b_acta = make_document(proc_b, type_code="birth_certificate", version=2)
        for _ in range(4):
            _evento(db_session, proc_b.id, "document_uploaded",
                    {"type_code": "birth_certificate"})

        sql = _migracion().VERSION_FIX_SQL
        db_session.execute(text(sql))
        db_session.expire_all()

        assert (a_curp.version, a_acta.version, a_cert.version) == (3, 1, 5)
        assert (b_curp.version, b_acta.version) == (1, 4)

        # Idempotente: una segunda corrida no mueve nada.
        db_session.execute(text(sql))
        db_session.expire_all()
        assert (a_curp.version, a_acta.version, a_cert.version,
                b_curp.version, b_acta.version) == (3, 1, 5, 1, 4)
