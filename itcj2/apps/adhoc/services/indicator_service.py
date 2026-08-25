"""Indicadores anuales del SGC: años, fichas y tablero de seguimiento.

Reemplaza ``routes/api/api_indicators.py`` del legacy, cuyos cinco endpoints
compartían tres defectos: tragaban toda excepción con un ``except Exception``
que convertía un 404 en un redirect "exitoso", indexaban listas paralelas del
formulario sin guarda (``p_rojo[i]`` reventaba con ``IndexError`` en silencio) y
empaquetaban los cuatro umbrales en un solo string ``"b-r-a-v"``.

Contrato de errores del módulo (lo traduce la capa API):

* :class:`LookupError` — la entidad no existe → **404**.
* :class:`ValueError`  — el dato es inválido → **400**.

Nunca se devuelve ``None`` "de éxito": si no hay fila, hay excepción.
El commit vive aquí, no en el endpoint.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Sequence

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session, selectinload

from itcj2.apps.adhoc.utils.constants import (
    TRACKING_COLOR_DEFAULT,
    TRACKING_COLORS,
    TRACKING_PERIODS_BY_FREQUENCY,
)

logger = logging.getLogger(__name__)

#: Kind del almacén de adjuntos (ver ``upload_service.UPLOAD_KINDS``).
UPLOAD_KIND = "indicators"

#: Columnas que ``bulk_create`` / ``update_indicator`` aceptan escribir.
#: ``document_url`` NO está: lo fija el upload, nunca el cliente (si el cliente
#: pudiera escribirlo, apuntaría la evidencia de un indicador a la de otro).
WRITABLE_FIELDS: tuple[str, ...] = (
    "process_id",
    "objective",
    "prev_results",
    "unit_calc",
    "responsible",
    "facilitator",
    "source",
    "strategic_rel",
    "criteria",
    "plan_b",
    "frequency",
    "planned_white",
    "planned_red",
    "planned_yellow",
    "planned_green",
)

#: Cota de ``period_index`` cuando el indicador no declara frecuencia.
_MAX_PERIODS = max(TRACKING_PERIODS_BY_FREQUENCY.values())


def _periods_for(frequency: Optional[str]) -> int:
    """Cuántos periodos tiene el tablero de un indicador.

    Sin frecuencia capturada se usa la cota máxima (52, 'Semanal') en vez de
    rechazar: el legacy dejaba ``frequency`` vacía en la mayoría de las filas y
    el seguimiento igual se capturaba.
    """
    return TRACKING_PERIODS_BY_FREQUENCY.get(frequency or "", _MAX_PERIODS)


def _has_file(upload: Any) -> bool:
    """``True`` si el slot del multipart trae un archivo de verdad.

    Un ``<input type="file">`` sin selección se envía igual, como una parte con
    ``filename=""``. Es lo que mantiene alineados los índices de las listas
    paralelas, así que se salta en silencio (no es un error).
    """
    if upload is None:
        return False
    name = getattr(upload, "filename", None)
    return bool(name and str(name).strip())


class IndicatorService:
    """Fachada del dominio de indicadores. Todos los métodos son estáticos."""

    # ======================================================================
    # Años
    # ======================================================================

    @staticmethod
    def get_year(db: Session, year_id: int):
        """El año, o ``None``. Único método del módulo que devuelve ``None``."""
        from itcj2.apps.adhoc.models import AdhocIndicatorYear

        return db.get(AdhocIndicatorYear, year_id)

    @staticmethod
    def list_years(db: Session) -> list[tuple[Any, int]]:
        """``[(AdhocIndicatorYear, nº de indicadores)]``, del año más nuevo al
        más viejo.

        El conteo va en la misma consulta (``LEFT JOIN`` + ``GROUP BY``): el
        legacy pintaba la lista de años y luego tocaba ``anio.indicators`` en la
        plantilla, un N+1 por tarjeta.
        """
        from itcj2.apps.adhoc.models import AdhocIndicator, AdhocIndicatorYear

        rows = (
            db.query(AdhocIndicatorYear, func.count(AdhocIndicator.id))
            .outerjoin(AdhocIndicator, AdhocIndicator.year_id == AdhocIndicatorYear.id)
            .group_by(AdhocIndicatorYear.id)
            .order_by(AdhocIndicatorYear.year.desc())
            .all()
        )
        return [(year, int(count or 0)) for year, count in rows]

    @staticmethod
    def create_years(db: Session, years: Sequence[int]) -> dict:
        """Alta idempotente de años.

        Devuelve ``{"created": [AdhocIndicatorYear], "skipped": [int]}``. Los
        años repetidos no son un error: ``adhoc_indicator_years.year`` es
        ``UNIQUE`` y el ``ON CONFLICT DO NOTHING`` absorbe tanto los duplicados
        del propio lote como los que ya estaban en la BD, sin la carrera del
        ``SELECT ... first()`` + ``INSERT`` del legacy.
        """
        from itcj2.apps.adhoc.models import AdhocIndicatorYear

        wanted: list[int] = []
        for raw in years or []:
            try:
                value = int(raw)
            except (TypeError, ValueError):
                raise ValueError(f"Año inválido: {raw!r}")
            if value not in wanted:
                wanted.append(value)

        if not wanted:
            raise ValueError("No se recibió ningún año")

        stmt = (
            pg_insert(AdhocIndicatorYear)
            .values([{"year": y} for y in wanted])
            .on_conflict_do_nothing(index_elements=["year"])
            .returning(AdhocIndicatorYear.id)
        )
        created_ids = [row[0] for row in db.execute(stmt).all()]
        db.commit()

        created = (
            db.query(AdhocIndicatorYear)
            .filter(AdhocIndicatorYear.id.in_(created_ids))
            .order_by(AdhocIndicatorYear.year.asc())
            .all()
            if created_ids else []
        )
        created_years = {y.year for y in created}
        skipped = [y for y in wanted if y not in created_years]

        logger.info("[adhoc] Años de indicadores: %d creados, %d omitidos",
                    len(created), len(skipped))
        return {"created": created, "skipped": skipped}

    @staticmethod
    def delete_year(db: Session, year_id: int) -> None:
        """Borra el año. El ``ON DELETE CASCADE`` se lleva indicadores y
        trackings; los archivos de evidencia se borran aquí (best-effort),
        porque la BD no sabe del disco."""
        from itcj2.apps.adhoc.models import AdhocIndicator, AdhocIndicatorYear
        from itcj2.apps.adhoc.services import upload_service

        year = db.get(AdhocIndicatorYear, year_id)
        if year is None:
            raise LookupError(f"El año de indicadores {year_id} no existe")

        stored = [
            path for (path,) in db.query(AdhocIndicator.document_url)
            .filter(AdhocIndicator.year_id == year_id, AdhocIndicator.document_url.isnot(None))
            .all()
        ]

        db.delete(year)
        db.commit()

        for path in stored:
            upload_service.delete_file(UPLOAD_KIND, path)
        logger.info("[adhoc] Año de indicadores %s eliminado (%d evidencias)",
                    year_id, len(stored))

    # ======================================================================
    # Indicadores
    # ======================================================================

    @staticmethod
    def get_indicator(db: Session, indicator_id: int):
        """El indicador con proceso y trackings ya cargados, o ``None``."""
        from itcj2.apps.adhoc.models import AdhocIndicator

        return (
            db.query(AdhocIndicator)
            .options(selectinload(AdhocIndicator.process),
                     selectinload(AdhocIndicator.trackings))
            .filter(AdhocIndicator.id == indicator_id)
            .one_or_none()
        )

    @staticmethod
    def list_indicators(db: Session, year_id: int) -> list:
        """Indicadores de un año, con proceso y seguimiento en dos consultas.

        El tablero del legacy disparaba un N+1 por indicador (``ind.process`` y
        ``ind.trackings`` lazy dentro del ``{% for %}``).
        """
        from itcj2.apps.adhoc.models import AdhocIndicator, AdhocIndicatorYear

        if db.get(AdhocIndicatorYear, year_id) is None:
            raise LookupError(f"El año de indicadores {year_id} no existe")

        return (
            db.query(AdhocIndicator)
            .options(selectinload(AdhocIndicator.process),
                     selectinload(AdhocIndicator.trackings))
            .filter(AdhocIndicator.year_id == year_id)
            .order_by(AdhocIndicator.id.asc())
            .all()
        )

    @staticmethod
    def _clean_row(db: Session, data: Mapping[str, Any], *, require_process: bool) -> dict:
        """Filtra a :data:`WRITABLE_FIELDS` y valida el proceso."""
        from itcj2.apps.adhoc.models import AdhocProcess

        payload = {k: v for k, v in dict(data).items() if k in WRITABLE_FIELDS}

        if require_process or "process_id" in payload:
            process_id = payload.get("process_id")
            if process_id in (None, ""):
                raise ValueError("El proceso es obligatorio")
            try:
                process_id = int(process_id)
            except (TypeError, ValueError):
                raise ValueError(f"Proceso inválido: {process_id!r}")
            if db.get(AdhocProcess, process_id) is None:
                raise ValueError(f"El proceso {process_id} no existe")
            payload["process_id"] = process_id

        return payload

    @staticmethod
    def bulk_create(
        db: Session,
        year_id: int,
        rows: Sequence[Mapping[str, Any]],
        uploads: Optional[Iterable[Any]] = None,
    ) -> list:
        """Alta masiva del tablero de un año.

        ``uploads`` va **alineado por índice** con ``rows`` (un slot por fila,
        vacío incluido). Los ids se obtienen con un ``flush()`` antes de tocar
        el disco, porque la evidencia se guarda en ``indicators/{id}/``.

        Si un archivo es rechazado (extensión fuera de whitelist, tamaño, nombre
        con traversal) se revierte **todo el lote** y se borran los archivos ya
        escritos: el legacy dejaba indicadores creados apuntando a archivos que
        nunca llegaron, y respondía con un redirect de éxito.
        """
        from itcj2.apps.adhoc.models import AdhocIndicator, AdhocIndicatorYear
        from itcj2.apps.adhoc.services import upload_service

        if db.get(AdhocIndicatorYear, year_id) is None:
            raise LookupError(f"El año de indicadores {year_id} no existe")

        rows = list(rows or [])
        if not rows:
            raise ValueError("No se recibió ningún indicador")

        upload_list = list(uploads or [])
        cleaned = [
            IndicatorService._clean_row(db, row, require_process=True) for row in rows
        ]

        created = []
        for payload in cleaned:
            indicator = AdhocIndicator(year_id=year_id, **payload)
            db.add(indicator)
            created.append(indicator)
        db.flush()   # ids para el subdirectorio de adjuntos

        saved_paths: list[str] = []
        try:
            for index, indicator in enumerate(created):
                upload = upload_list[index] if index < len(upload_list) else None
                if not _has_file(upload):
                    continue
                meta = upload_service.save_upload(UPLOAD_KIND, indicator.id, upload)
                indicator.document_url = meta["file_path"]
                saved_paths.append(meta["file_path"])
            db.commit()
        except Exception:
            db.rollback()
            for path in saved_paths:
                upload_service.delete_file(UPLOAD_KIND, path)
            raise

        for indicator in created:
            db.refresh(indicator)
        logger.info("[adhoc] %d indicadores creados en el año %s", len(created), year_id)
        return created

    @staticmethod
    def update_indicator(
        db: Session,
        indicator_id: int,
        data: Mapping[str, Any],
        upload: Any = None,
    ):
        """Edición parcial. Solo se escriben las claves presentes en ``data``.

        El archivo anterior se borra **después** del commit: si el commit
        falla, la evidencia vieja sigue ahí y la fila sigue apuntándole.
        """
        from itcj2.apps.adhoc.models import AdhocIndicator
        from itcj2.apps.adhoc.services import upload_service

        indicator = db.get(AdhocIndicator, indicator_id)
        if indicator is None:
            raise LookupError(f"El indicador {indicator_id} no existe")

        payload = IndicatorService._clean_row(db, data, require_process=False)
        for field, value in payload.items():
            setattr(indicator, field, value)

        previous = indicator.document_url
        new_path: Optional[str] = None
        if _has_file(upload):
            meta = upload_service.save_upload(UPLOAD_KIND, indicator.id, upload)
            new_path = meta["file_path"]
            indicator.document_url = new_path

        try:
            db.commit()
        except Exception:
            db.rollback()
            if new_path:
                upload_service.delete_file(UPLOAD_KIND, new_path)
            raise

        if new_path and previous and previous != new_path:
            upload_service.delete_file(UPLOAD_KIND, previous)

        db.refresh(indicator)
        return indicator

    @staticmethod
    def delete_indicator(db: Session, indicator_id: int) -> None:
        """Borra el indicador, sus trackings (cascade) y su evidencia."""
        from itcj2.apps.adhoc.models import AdhocIndicator
        from itcj2.apps.adhoc.services import upload_service

        indicator = db.get(AdhocIndicator, indicator_id)
        if indicator is None:
            raise LookupError(f"El indicador {indicator_id} no existe")

        stored = indicator.document_url
        db.delete(indicator)
        db.commit()

        if stored:
            upload_service.delete_file(UPLOAD_KIND, stored)
        logger.info("[adhoc] Indicador %s eliminado", indicator_id)

    @staticmethod
    def document_path(db: Session, indicator_id: int) -> Path:
        """Ruta absoluta y verificada de la evidencia del indicador.

        Endpoint **nuevo**: el legacy subía el documento y no ofrecía ninguna
        forma de recuperarlo. ``open_stored`` vuelve a pasar por ``safe_join``
        aunque el valor venga de la BD (una fila envenenada no debe poder leer
        fuera de la raíz de uploads).
        """
        from itcj2.apps.adhoc.models import AdhocIndicator
        from itcj2.apps.adhoc.services import upload_service

        indicator = db.get(AdhocIndicator, indicator_id)
        if indicator is None:
            raise LookupError(f"El indicador {indicator_id} no existe")
        if not indicator.document_url:
            raise LookupError(f"El indicador {indicator_id} no tiene evidencia adjunta")

        try:
            return upload_service.open_stored(UPLOAD_KIND, indicator.document_url)
        except ValueError as exc:
            # El registro apunta a algo que ya no está en disco.
            raise LookupError(str(exc)) from exc

    # ======================================================================
    # Seguimiento
    # ======================================================================

    @staticmethod
    def upsert_tracking(
        db: Session,
        indicator_id: int,
        period_index: int,
        real_value: Optional[str] = None,
        color: Optional[str] = None,
    ):
        """Escribe la celda ``(indicador, periodo)`` del renglón REAL.

        Un solo ``INSERT ... ON CONFLICT DO UPDATE`` sobre
        ``uq_adhoc_indicator_trackings_indicator_period``: atómico, sin la
        carrera del ``filter_by(...).first()`` + ``add()`` del legacy, que con
        dos guardados simultáneos del mismo periodo dejaba dos filas.

        ``color`` es ``NOT NULL``: ``None`` se resuelve a ``'blanco'``.
        """
        from itcj2.apps.adhoc.models import AdhocIndicator, AdhocIndicatorTracking

        indicator = db.get(AdhocIndicator, indicator_id)
        if indicator is None:
            raise LookupError(f"El indicador {indicator_id} no existe")

        try:
            period_index = int(period_index)
        except (TypeError, ValueError):
            raise ValueError(f"Periodo inválido: {period_index!r}")

        limit = _periods_for(indicator.frequency)
        # Se acepta 0..limit para no casarse con una convención: el tablero del
        # legacy numera 1..N (``range(1, periodos + 1)`` en la plantilla) y el
        # 0-based es el natural en la API. Fuera de ese rango es basura.
        if period_index < 0 or period_index > limit:
            raise ValueError(
                f"Periodo {period_index} fuera de rango para la frecuencia "
                f"{indicator.frequency or 'sin definir'} (0-{limit})"
            )

        color = (color or TRACKING_COLOR_DEFAULT)
        if color not in TRACKING_COLORS:
            raise ValueError(
                f"Color inválido: {color!r}. Válidos: {', '.join(TRACKING_COLORS)}"
            )

        stmt = (
            pg_insert(AdhocIndicatorTracking)
            .values(
                indicator_id=indicator_id,
                period_index=period_index,
                real_value=real_value,
                color=color,
            )
            .on_conflict_do_update(
                constraint="uq_adhoc_indicator_trackings_indicator_period",
                set_={
                    "real_value": real_value,
                    "color": color,
                    "updated_at": func.now(),
                },
            )
            .returning(AdhocIndicatorTracking.id)
        )
        tracking_id = db.execute(stmt).scalar_one()
        db.commit()

        # ``populate_existing`` es obligatorio: el INSERT ... ON CONFLICT va por
        # Core, así que el identity map de la sesión conserva la versión previa
        # de la fila y un SELECT normal devolvería los valores viejos.
        return db.execute(
            select(AdhocIndicatorTracking)
            .where(AdhocIndicatorTracking.id == tracking_id)
            .execution_options(populate_existing=True)
        ).scalar_one()
