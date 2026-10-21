"""Perfil de titulación (licenciatura | posgrado) de un proceso.

Único lugar que traduce `Program.level` a perfil de TitulaTec (spec
2026-09-30-titulatec-posgrado-design.md §4.3, invariante 2): nadie más debe
comparar `Program.level` ni nombres de carrera para decidir si un proceso es
de posgrado. Los consumidores (documentos de fase 1, encuesta, vistas de
admin/alumno) preguntan aquí, nunca miran `Program` directamente.
"""
from __future__ import annotations

from typing import Iterable

from sqlalchemy.orm import Session

TRACK_LICENCIATURA = "licenciatura"
TRACK_POSGRADO = "posgrado"


class TrackService:
    @staticmethod
    def for_level(level: str | None) -> str:
        """Nivel de carrera -> perfil.

        Cualquier nivel en `POSTGRADUATE_LEVELS` (maestria|doctorado) resuelve
        a posgrado; cualquier otro valor, incluido `None` (proceso sin carrera
        o carrera sin nivel reconocido), resuelve a licenciatura.
        """
        from itcj2.core.models.program import POSTGRADUATE_LEVELS

        return TRACK_POSGRADO if level in POSTGRADUATE_LEVELS else TRACK_LICENCIATURA

    @staticmethod
    def same_level(db: Session, program_id_a: int, program_id_b: int) -> bool:
        """¿Las dos carreras son del MISMO `level` (licenciatura|maestria|doctorado)?

        Lo usa la corrección del registro del Formato B (spec 2026-10-21 fase 3
        §8.5): la carrera nueva debe ser del mismo nivel que la actual, porque
        cambiar de nivel cambiaría el perfil de titulación a media marcha. Es
        más estricto que comparar perfiles (maestría ↔ doctorado también
        cambia de nivel). Vive aquí porque este módulo es el único que lee
        `Program.level` (invariante 2). Una carrera inexistente -> False. Una
        sola consulta.
        """
        from itcj2.core.models.program import Program

        ids = {program_id_a, program_id_b}
        if None in ids:
            return False
        levels = dict(db.query(Program.id, Program.level).filter(Program.id.in_(ids)).all())
        return (program_id_a in levels and program_id_b in levels
                and levels[program_id_a] == levels[program_id_b])

    @staticmethod
    def for_process(db: Session, process) -> str:
        """Perfil de UN proceso. Sin carrera (`program_id` `None`) -> licenciatura."""
        from itcj2.core.models.program import Program

        if process.program_id is None:
            return TRACK_LICENCIATURA
        program = db.get(Program, process.program_id)
        return TrackService.for_level(program.level if program else None)

    @staticmethod
    def for_process_id(db: Session, process_id: int) -> str:
        """Igual que `for_process`, buscando primero el proceso por id.

        Un proceso inexistente resuelve a licenciatura (nunca una excepción):
        quien llama esto es código de lote o de visor, no una ruta que deba
        responder 404.
        """
        from itcj2.apps.titulatec.models import TitulationProcess

        process = db.get(TitulationProcess, process_id)
        if process is None:
            return TRACK_LICENCIATURA
        return TrackService.for_process(db, process)

    @staticmethod
    def for_processes(db: Session, processes: Iterable) -> dict[int, str]:
        """`for_process` para varios procesos EN LOTE, en UNA sola consulta.

        Para bandejas y visores que listan muchos procesos a la vez: sin esto,
        resolver el perfil fila por fila dispararía una consulta por proceso.
        Lista vacía -> `{}` sin consultar; si ningún proceso tiene carrera
        tampoco se consulta (sin `IN ()` vacíos).
        """
        from itcj2.core.models.program import Program

        processes = list(processes)
        if not processes:
            return {}

        program_ids = {p.program_id for p in processes if p.program_id is not None}
        levels_by_program_id = (
            dict(db.query(Program.id, Program.level)
                 .filter(Program.id.in_(program_ids)).all())
            if program_ids else {}
        )

        return {
            p.id: TrackService.for_level(levels_by_program_id.get(p.program_id))
            for p in processes
        }

    @staticmethod
    def programs_same_level(db: Session, program_id: int | None) -> list:
        """Carreras del MISMO `level` que `program_id`, por nombre (e id).

        Las opciones del «Corregir carrera» de la pestaña Titulación (spec
        2026-10-21 fase 3 §8.5): la página no lee `Program.level` (invariante
        2); el service lo vuelve a exigir con `same_level`. Incluye la propia
        carrera. Sin carrera o una inexistente -> `[]`. Una sola consulta (el
        nivel va en una subconsulta escalar).
        """
        from itcj2.core.models.program import Program

        if program_id is None:
            return []
        nivel = (db.query(Program.level).filter(Program.id == program_id)
                 .scalar_subquery())
        return (db.query(Program).filter(Program.level == nivel)
                .order_by(Program.name, Program.id).all())
