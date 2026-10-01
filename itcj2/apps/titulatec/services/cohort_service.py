"""Ventana pública de la convocatoria: predicado, resolución y pausa/reanudación.

Por qué existe
--------------
`titulatec_cohorts` trae `opens_at`, `closes_at` y `status` desde su primera
migración y NADIE los escribía ni los leía: `pages/admin.py:387` clavaba
`status="open"` al crear y las fechas quedaban NULL para siempre. Este servicio
es el ÚNICO escritor de la ventana y el único que sabe traducirla a "¿puede
alguien auto-inscribirse ahora mismo?".

Ventana con hora (spec 2026-09-27 §B)
-------------------------------------
Desde `tt20260927b` las dos columnas son `DateTime` NOT NULL (hora local naive,
APP_TZ) y los predicados comparan AL MINUTO contra `db_now()`, nunca contra el
reloj del proceso: el contenedor puede correr en UTC y la ventana se abriría o
cerraría seis horas corrida, en silencio. El cierre por omisión es 23:59:59.

«Al minuto» de verdad (revisión final F10): `now` se trunca a su minuto
(`_al_minuto`) antes de comparar. La hora tecleada se guarda HH:MM:00, así que
sin truncar un cierre escrito «23:59» perdía su último minuto (23:59:30 ya
contaba como cerrado) mientras el de omisión (23:59:59, que también se lee
«23:59») lo conservaba. Truncado, los dos se comportan igual: abierto hasta
las 23:59:59.999, cerrado a las 00:00:00 del día siguiente; y una apertura a
las 09:00 abre en cuanto empieza ese minuto.

Fallo cerrado, a propósito
--------------------------
`public_enrollment_cohort` NUNCA desempata. Cuando las fechas podían ser NULL,
toda convocatoria existente era `status='open'` sin tope y el predicado era
verdadero para todas; y aun con fechas, dos ventanas pueden solaparse. Un
desempate por `id desc` mandaría al solicitante —y con él su folio y su carpeta
en disco, que llevan el periodo dentro— a la convocatoria equivocada, en
silencio y sin vuelta atrás. Con >1 devuelve `(None, 'ambiguous')` y la ruta
pública contesta 503 nombrando el choque para que un humano lo resuelva.

El personal NUNCA queda bloqueado por la ventana: importación CSV y alta manual
siguen funcionando con la convocatoria cerrada. Esto solo gatea el formulario
público.

Dos predicados, a propósito (D5, spec 2026-09-24)
-------------------------------------------------
- `is_public_enrollment_open`: `status='open'` Y `db_now()` dentro de
  `[opens_at, closes_at]`. Es SOLO para el formulario público (¿se puede
  enviar una solicitud nueva?).
- `accepts_enrollment_followup`: solo `status='open'`. Es para lo que sigue a
  una solicitud que ya entró a tiempo: aprobarla, darle acceso, abrir su liga y
  reenviarla. La liga dura `TITULATEC_ENROLLMENT_LINK_TTL_DAYS` (21 por
  omisión; `EnrollmentRequestService.link_ttl_days()`) y la revisión puede
  tardar; cortarlas en `closes_at` dejaría varadas solicitudes legítimas.
  `closed` sí las detiene: es la pausa de la convocatoria (`set_window`).
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from itcj2.core.utils.timezone import db_now

_STATUSES = ("draft", "open", "closed")


def _al_minuto(now: datetime) -> datetime:
    """`now` truncado a su minuto: la ventana se compara AL MINUTO (F10)."""
    return now.replace(second=0, microsecond=0)


class CohortService:

    @staticmethod
    def is_public_enrollment_open(cohort, *, now: datetime | None = None) -> bool:
        """`status='open'` y `opens_at <= now <= closes_at`, AL MINUTO.

        `now` por omisión es `db_now()`, y se trunca a su minuto antes de
        comparar (`_al_minuto`): los dos extremos cuentan con su minuto entero.
        Un cierre tecleado «23:59» (guardado 23:59:00) y el de omisión
        (23:59:59) siguen abiertos a las 23:59:30 del último día y cerrados a
        las 00:00:00 del siguiente; una apertura a las 09:00 está cerrada a las
        08:59:59 y abierta a las 09:00:30.
        """
        if cohort is None or cohort.status != "open":
            return False
        now = _al_minuto(now or db_now())
        return cohort.opens_at <= now <= cohort.closes_at

    @staticmethod
    def accepts_enrollment_followup(cohort) -> bool:
        """`status='open'`, sin mirar fechas: ver "Dos predicados" en el módulo."""
        return cohort is not None and cohort.status == "open"

    @staticmethod
    def public_enrollment_cohort(db: Session):
        """Devuelve `(cohort|None, error)`. `error` ∈ `None` | `'closed'` | `'ambiguous'`.

        0 abiertas → la GET muestra la tarjeta de cierre y la POST no escribe.
        >1 abiertas → falla cerrado; ver el docstring del módulo.
        """
        from itcj2.apps.titulatec.models import Cohort

        ahora = db_now()        # un solo instante para todas las candidatas
        abiertas = [
            c for c in db.query(Cohort).filter(Cohort.status == "open")
                                       .order_by(Cohort.id).all()
            if CohortService.is_public_enrollment_open(c, now=ahora)
        ]
        if not abiertas:
            return None, "closed"
        if len(abiertas) > 1:
            return None, "ambiguous"
        return abiertas[0], None

    @staticmethod
    def next_public_enrollment_window(db: Session, *, now: datetime | None = None):
        """La convocatoria que ABRIRÁ el formulario público, o `None`.

        Sirve para que la tarjeta de cierre diga *cuándo volver* en vez de
        mandar al egresado a preguntar. El caso real: `status='open'` con
        `opens_at > now` (`db_now()` por omisión, truncado al minuto igual que
        en `is_public_enrollment_open`, para que los dos nunca se
        contradigan) es "cerrada" para `is_public_enrollment_open`
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

        now = _al_minuto(now or db_now())
        return (db.query(Cohort)
                  .filter(Cohort.status == "open", Cohort.opens_at > now)
                  .order_by(Cohort.opens_at, Cohort.id)
                  .first())

    @staticmethod
    def set_window(db: Session, cohort_id: int, *, opens_at: datetime,
                   closes_at: datetime, status: str, actor_id: int) -> dict:
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

        Los procesos que se mueven se leen con `FOR UPDATE`: una revocación
        (`ProcessService.cancel`, `FOR NO KEY UPDATE`) que hace commit mientras
        tanto no se pisa, porque tras la espera Postgres re-evalúa el filtro de
        estado y la revocada queda fuera.

        Un solo `commit` al final: la ventana y el flip viajan juntos.
        Devuelve `{'paused': N, 'resumed': M}`. Lanza `ValueError` con texto para
        el usuario —siempre ANTES de la primera escritura— si el estado es
        desconocido, la convocatoria no existe, falta la apertura o el cierre
        (las dos columnas son NOT NULL: vacío ya no significa «sin tope») o el
        cierre no es POSTERIOR a la apertura (la igualdad se rechaza).
        """
        from itcj2.apps.titulatec.models import Cohort, ProcessEvent, TitulationProcess

        if status not in _STATUSES:
            raise ValueError("El estado debe ser borrador, abierta o cerrada.")
        cohort = db.get(Cohort, cohort_id)
        if cohort is None:
            raise ValueError("La convocatoria no existe.")
        if opens_at is None or closes_at is None:
            raise ValueError("La apertura y el cierre son obligatorios.")
        if closes_at <= opens_at:
            raise ValueError("El cierre tiene que ser posterior a la apertura.")

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
                                 TitulationProcess.cohort_id.in_(cerradas))
                         .with_for_update(key_share=True).all()):
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
                                 TitulationProcess.cohort_id == cohort.id)
                         .with_for_update(key_share=True).all()):
                proc.status = "on_hold"
                db.add(ProcessEvent(
                    process_id=proc.id, actor_id=actor_id,
                    event_type="process_paused", phase_number=proc.current_phase,
                    payload={"cohort_id": cohort.id},
                ))
                paused += 1

        db.commit()
        return {"paused": paused, "resumed": resumed}

    @staticmethod
    def set_book_donation(db: Session, cohort_id: int, *, amount: Decimal) -> dict:
        """Escribe la donación voluntaria de libro de la convocatoria (D5,
        D19 de spec 2026-10-01-titulatec-biblioteca-caja-design.md §4.9).

        Servicios Escolares la edita en el panel Resumen
        (`titulatec.cohort.api.update`); `amount` ya viene validado por la
        ruta (`LibraryClearanceService.parse_amount`: 0 <= monto <=
        $100,000). Este service NO toca ningún `LibraryClearance`: Biblioteca
        congela la donación VIGENTE de la convocatoria al Registrar o
        Corregir (`LibraryClearanceService._prepare_registration`), así que
        cambiarla aquí nunca pisa un monto ya congelado (Review Focus #2,
        D16) -- lo que ya pasó a Caja se queda con el valor de ese momento;
        Corregir es lo único que lo vuelve a congelar con el vigente.

        Devuelve `{"affected": N}`: cuántos `LibraryClearance` de esta
        convocatoria YA tienen un monto congelado
        (`donation_amount IS NOT NULL`: toda fila que pasó por Registrar y
        no volvió a `pending` -- `awaiting_payment`, `cleared` vía pago o sin
        cargo, y también `cleared/prior` si la constancia previa se registró
        DESDE `awaiting_payment`, que conserva los montos como historia).
        Nunca `pending` (volver ahí borra los montos) ni una previa
        registrada desde `pending` (no tiene montos). La ruta usa el número
        para el aviso «N egresados ya tienen monto asignado; no cambia para
        ellos».

        `ValueError` si la convocatoria no existe. UN commit.
        """
        from itcj2.apps.titulatec.models import Cohort, LibraryClearance, TitulationProcess

        cohort = db.get(Cohort, cohort_id)
        if cohort is None:
            raise ValueError("La convocatoria no existe.")
        cohort.book_donation_amount = amount

        afectados = (
            db.query(func.count(LibraryClearance.id))
            .join(TitulationProcess, TitulationProcess.id == LibraryClearance.process_id)
            .filter(TitulationProcess.cohort_id == cohort_id,
                    LibraryClearance.donation_amount.isnot(None))
            .scalar()) or 0

        db.commit()
        return {"affected": int(afectados)}
