"""Tests de TrackService — perfil de titulación (licenciatura | posgrado).

`TrackService` es el ÚNICO lugar que traduce `Program.level` a perfil de
TitulaTec (spec 2026-09-30 §4.3, invariante 2): nadie más debe comparar
`Program.level` ni nombres de carrera. Estas pruebas fijan:

1. Las 4 combinaciones de `for_level` (los 2 niveles de posgrado, licenciatura
   y `None`).
2. `for_process` con carrera de licenciatura, de posgrado y sin carrera
   (`program_id` `None` -> licenciatura, nunca una excepción).
3. `for_process_id` cuando el proceso no existe -> licenciatura (nunca 404 ni
   excepción: quien llama esto es codigo de lote/visor, no una ruta).
4. El contrato de lote de `for_processes`: UNA sola consulta sin importar la
   mezcla de perfiles, y CERO consultas con la lista vacía -- el mismo
   regresor N+1 que ya cubre `test_documents_inbox.py` para la bandeja de
   Documentos, aplicado aquí al resolvedor del que esa bandeja (y las demás
   tareas del plan) dependerán.
"""
from __future__ import annotations

import pytest
from sqlalchemy import event

from itcj2.apps.titulatec.services.track_service import (
    TRACK_LICENCIATURA,
    TRACK_POSGRADO,
    TrackService,
)


class _Contador:
    """Cuenta las sentencias SQL reales que pasan por la conexion del test.

    Copiado de `test_documents_inbox.py:49-71` (mismo patron: no hay fixture
    compartida para esto en el repo).
    """

    def __init__(self, conexion):
        self.conexion = conexion
        self.sentencias = []

    def __enter__(self):
        event.listen(self.conexion, "before_cursor_execute", self._ver)
        return self

    def __exit__(self, *exc):
        event.remove(self.conexion, "before_cursor_execute", self._ver)
        return False

    def _ver(self, conn, cursor, statement, params, context, executemany):
        self.sentencias.append(" ".join(statement.split()))

    def __len__(self):
        return len(self.sentencias)

    def tocan(self, tabla):
        return [s for s in self.sentencias if tabla in s]


# ---------------------------------------------------------------------------
# for_level — pura, sin BD
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("level, esperado", [
    ("licenciatura", TRACK_LICENCIATURA),
    ("maestria", TRACK_POSGRADO),
    ("doctorado", TRACK_POSGRADO),
    (None, TRACK_LICENCIATURA),
])
def test_for_level(level, esperado):
    assert TrackService.for_level(level) == esperado


# ---------------------------------------------------------------------------
# for_process
# ---------------------------------------------------------------------------
def test_for_process_con_carrera_de_licenciatura(db_session, make_program, make_user,
                                                  make_process):
    programa = make_program("Ingenieria Ficticia Track Licenciatura")
    proceso = make_process(make_user(), program=programa)

    assert TrackService.for_process(db_session, proceso) == TRACK_LICENCIATURA


def test_for_process_con_carrera_de_posgrado(db_session, make_program, make_user,
                                              make_process):
    programa = make_program("Maestria Ficticia Track Posgrado", level="maestria")
    proceso = make_process(make_user(), program=programa)

    assert TrackService.for_process(db_session, proceso) == TRACK_POSGRADO


def test_for_process_sin_carrera(db_session, make_user, make_process):
    proceso = make_process(make_user(), program=None)

    assert TrackService.for_process(db_session, proceso) == TRACK_LICENCIATURA


# ---------------------------------------------------------------------------
# for_process_id
# ---------------------------------------------------------------------------
def test_for_process_id_inexistente_es_licenciatura(db_session):
    assert TrackService.for_process_id(db_session, 999999999) == TRACK_LICENCIATURA


def test_for_process_id_resuelve_el_proceso_existente(db_session, make_program,
                                                        make_user, make_process):
    """No solo el caso borde: el id tambien debe resolver bien el feliz."""
    programa = make_program("Doctorado Ficticio Track Id", level="doctorado")
    proceso = make_process(make_user(), program=programa)

    assert TrackService.for_process_id(db_session, proceso.id) == TRACK_POSGRADO


# ---------------------------------------------------------------------------
# for_processes — el contrato de lote
# ---------------------------------------------------------------------------
def test_for_processes_mezclado_en_una_sola_consulta(db_session, make_program,
                                                       make_user, make_process):
    licenciatura = make_program("Ingenieria Ficticia Track Lote")
    posgrado = make_program("Maestria Ficticia Track Lote", level="maestria")

    proc_lic = make_process(make_user(), program=licenciatura)
    proc_pos = make_process(make_user(), program=posgrado)
    proc_sin = make_process(make_user(), program=None)

    with _Contador(db_session.get_bind()) as c:
        resultado = TrackService.for_processes(
            db_session, [proc_lic, proc_pos, proc_sin])

    assert resultado == {
        proc_lic.id: TRACK_LICENCIATURA,
        proc_pos.id: TRACK_POSGRADO,
        proc_sin.id: TRACK_LICENCIATURA,
    }
    assert len(c) == 1, "debe resolver el lote en UNA sola consulta:\n%s" % (
        "\n".join(c.sentencias))
    assert len(c.tocan("core_programs")) == 1


def test_for_processes_lista_vacia_no_consulta(db_session):
    with _Contador(db_session.get_bind()) as c:
        assert TrackService.for_processes(db_session, []) == {}
    assert len(c) == 0
