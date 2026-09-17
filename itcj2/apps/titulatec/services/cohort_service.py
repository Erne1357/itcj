"""Ventana pública de la convocatoria: predicado, resolución y pausa/reanudación.

Por qué existe
--------------
`titulatec_cohorts` trae `opens_at`, `closes_at` y `status` desde su primera
migración y NADIE los escribía ni los leía: `pages/admin.py:387` clavaba
`status="open"` al crear y las fechas quedaban NULL para siempre. Este servicio
es el ÚNICO escritor de la ventana y el único que sabe traducirla a "¿puede
alguien auto-inscribirse ahora mismo?".

Fallo cerrado, a propósito
--------------------------
`public_enrollment_cohort` NUNCA desempata. Como toda convocatoria existente es
`status='open'` con fechas NULL, el predicado es verdadero para todas: un
desempate por `id desc` mandaría al solicitante —y con él su folio y su carpeta
en disco, que llevan el periodo dentro— a la convocatoria equivocada, en
silencio y sin vuelta atrás. Con >1 devuelve `(None, 'ambiguous')` y la ruta
pública contesta 503 nombrando el choque para que un humano lo resuelva.

El personal NUNCA queda bloqueado por la ventana: importación CSV y alta manual
siguen funcionando con la convocatoria cerrada. Esto solo gatea el formulario
público.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

_STATUSES = ("draft", "open", "closed")


class CohortService:

    @staticmethod
    def is_public_enrollment_open(cohort) -> bool:
        """`status='open'` y hoy dentro de `[opens_at, closes_at]` (NULL = sin tope)."""
        if cohort is None or cohort.status != "open":
            return False
        hoy = date.today()
        if cohort.opens_at is not None and hoy < cohort.opens_at:
            return False
        if cohort.closes_at is not None and hoy > cohort.closes_at:
            return False
        return True

    @staticmethod
    def public_enrollment_cohort(db: Session):
        """Devuelve `(cohort|None, error)`. `error` ∈ `None` | `'closed'` | `'ambiguous'`.

        0 abiertas → la GET muestra la tarjeta de cierre y la POST no escribe.
        >1 abiertas → falla cerrado; ver el docstring del módulo.
        """
        from itcj2.apps.titulatec.models import Cohort

        abiertas = [
            c for c in db.query(Cohort).filter(Cohort.status == "open")
                                       .order_by(Cohort.id).all()
            if CohortService.is_public_enrollment_open(c)
        ]
        if not abiertas:
            return None, "closed"
        if len(abiertas) > 1:
            return None, "ambiguous"
        return abiertas[0], None

    @staticmethod
    def next_public_enrollment_window(db: Session):
        """La convocatoria que ABRIRÁ el formulario público, o `None`.

        Sirve para que la tarjeta de cierre diga *cuándo volver* en vez de
        mandar al egresado a preguntar. El caso real: `status='open'` con
        `opens_at` en el futuro es "cerrada" para `is_public_enrollment_open`
        —y debe serlo, el formulario no se abre antes de tiempo— pero la fecha
        ya está decidida y publicada.

        Solo `status='open'`. Una `draft` es un borrador cuyas fechas todavía se
        mueven: anunciarla es prometer un día al que el egresado vendría en
        balde. Una `closed` con `opens_at` futuro es una ventana que la jefatura
        cerró a mano; tampoco se anuncia.

        Se ordena por `opens_at` y se desempata por `id`: aquí SÍ se desempata,
        al revés que `public_enrollment_cohort`, porque lo único que se expone
        es una fecha. Si dos convocatorias abren el mismo día, la fecha es la
        misma y el desempate no cambia lo que lee el egresado.
        """
        from itcj2.apps.titulatec.models import Cohort

        return (db.query(Cohort)
                  .filter(Cohort.status == "open",
                          Cohort.opens_at.isnot(None),
                          Cohort.opens_at > date.today())
                  .order_by(Cohort.opens_at, Cohort.id)
                  .first())

    @staticmethod
    def set_window(db: Session, cohort_id: int, *, opens_at, closes_at,
                   status: str, actor_id: int) -> dict:
        """Escribe la ventana y aplica la tabla de transiciones de D5.

        | De → A                     | Efecto sobre procesos                       |
        |----------------------------|---------------------------------------------|
        | `draft→open`, `closed→open`| Reanudar: todo proceso `on_hold` cuya        |
        |                            | convocatoria estuviera `closed` vuelve a     |
        |                            | `active`, SIN cambiar de convocatoria.       |
        | `open→closed`,`draft→closed`| Pausar: los `active` de ESA convocatoria    |
        |                            | pasan a `on_hold`. Nunca `completed` ni      |
        |                            | `cancelled`.                                 |
        | cualquiera → `draft`, no-op| Nada.                                        |

        El conjunto de convocatorias cerradas se calcula **antes** de escribir el
        nuevo `status`: en `closed→open` esta misma convocatoria está dentro, y
        sus propios procesos pausados deben volver. Calculado después ya sería
        `'open'` y quedarían congelados en `on_hold` para siempre.

        El predicado de reanudación es global ("todo `on_hold` de convocatoria
        cerrada") y no "los de la que se abre": un proceso reanudado conserva su
        `cohort_id`, así que con el segundo predicado no volvería a reanudarse
        jamás tras la siguiente pausa.

        Un solo `commit` al final: la ventana y el flip viajan juntos.
        Devuelve `{'paused': N, 'resumed': M}`. Lanza `ValueError` con texto para
        el usuario si el estado es desconocido, la convocatoria no existe o el
        cierre es anterior a la apertura.
        """
        from itcj2.apps.titulatec.models import Cohort, ProcessEvent, TitulationProcess

        if status not in _STATUSES:
            raise ValueError("El estado debe ser borrador, abierta o cerrada.")
        cohort = db.get(Cohort, cohort_id)
        if cohort is None:
            raise ValueError("La convocatoria no existe.")
        if opens_at and closes_at and closes_at < opens_at:
            raise ValueError("El cierre no puede ser anterior a la apertura.")

        anterior = cohort.status
        cerradas = [row.id for row in
                    db.query(Cohort.id).filter(Cohort.status == "closed").all()]

        cohort.opens_at = opens_at
        cohort.closes_at = closes_at
        cohort.status = status
        db.flush()

        paused = 0
        resumed = 0

        if status == "open" and anterior in ("draft", "closed") and cerradas:
            for proc in (db.query(TitulationProcess)
                         .filter(TitulationProcess.status == "on_hold",
                                 TitulationProcess.cohort_id.in_(cerradas)).all()):
                proc.status = "active"
                db.add(ProcessEvent(
                    process_id=proc.id, actor_id=actor_id,
                    event_type="process_resumed", phase_number=proc.current_phase,
                    payload={"cohort_id": proc.cohort_id,
                             "opened_cohort_id": cohort.id},
                ))
                resumed += 1

        elif status == "closed" and anterior in ("draft", "open"):
            for proc in (db.query(TitulationProcess)
                         .filter(TitulationProcess.status == "active",
                                 TitulationProcess.cohort_id == cohort.id).all()):
                proc.status = "on_hold"
                db.add(ProcessEvent(
                    process_id=proc.id, actor_id=actor_id,
                    event_type="process_paused", phase_number=proc.current_phase,
                    payload={"cohort_id": cohort.id},
                ))
                paused += 1

        db.commit()
        return {"paused": paused, "resumed": resumed}
