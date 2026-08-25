"""CRUD genérico de los **seis catálogos simples** de Adhoc (Calidad).

Cubre ``adhoc_areas``, ``adhoc_processes``, ``adhoc_document_categories``,
``adhoc_document_classifications``, ``adhoc_incident_categories`` y
``adhoc_program_categories``. Los seis comparten forma (``id`` + ``name``
UNIQUE + timestamps) y difieren solo en las columnas extra de área
(``color``, ``is_active``) y proceso (``color``, ``description``), así que
viven en un único service parametrizado por modelo en vez de en seis copias
del mismo bucle — que es justo lo que tenía el legacy repartido en
``api_areas.py``, ``api_processes.py``, ``api_docs.py``, ``api_incidents.py``
y ``api_programs.py``.

Qué arregla respecto del legacy (``docs/adhoc/analysis/src_api.md`` §1.1, §1.2,
§2.4, §4 y el plan §7):

``name`` es ``UNIQUE`` en los seis y el alta masiva insertaba sin deduplicar:
    un solo duplicado disparaba ``IntegrityError`` en el ``commit()`` → **el
    lote entero se revertía** y la vista redirigía como si todo hubiera salido
    bien. :meth:`AdhocCatalogService.bulk_create` **deduplica antes de
    insertar** (contra la BD y dentro del propio payload, sin distinguir
    mayúsculas) y devuelve la lista de nombres omitidos para que la UI lo diga.

``except Exception`` tragaba el ``get_or_404``:
    un id inexistente terminaba en un 302 "exitoso". Aquí un id que no existe
    es :class:`CatalogNotFound` → 404 de verdad.

``delete`` sin comprobar FKs:
    ``adhoc_documents.{area_id,process_id,category_id,classification_id}``,
    ``adhoc_incidents.{area_id,process_id,category_id}`` y
    ``adhoc_program_events.{area_id,process_id,category_id}`` son FK **sin
    ``ondelete``** (RESTRICT): borrar un catálogo en uso reventaba con
    ``IntegrityError`` tragado. :meth:`AdhocCatalogService.delete` cuenta los
    dependientes primero y lanza :class:`CatalogInUse` con el desglose.
    (``adhoc_user_areas.area_id`` sí es ``ON DELETE CASCADE`` por diseño (D2),
    así que no bloquea el borrado: las asignaciones de usuario se limpian.)

``Process(name=..., description=color)``:
    el color se guardaba en la columna ``description``. Ahora ``color`` es
    columna real y ``description`` vuelve a ser una descripción.

``Area.is_active``:
    el legacy filtraba por esa columna pero nunca dio UI para togglearla, y las
    filas metidas por SQL quedaban ``NULL`` → invisibles. La columna es
    ``NOT NULL DEFAULT true`` y el toggle es un campo actualizable más;
    :meth:`list_items` expone el filtro explícitamente.

**Contrato de errores:** todo fallo previsible es un ``ValueError``
(:class:`CatalogError` hereda de ``ValueError``, igual que ``upload_service``),
con mensaje en español listo para
``raise HTTPException(status_code=..., detail=str(exc))``. Las subclases
existen solo para que el endpoint elija el status correcto: 404 / 409 / 400.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

__all__ = [
    "CatalogError",
    "CatalogNotFound",
    "CatalogDuplicate",
    "CatalogInUse",
    "CatalogValidationError",
    "BulkCreateResult",
    "AdhocCatalogService",
    "CATALOG_FIELDS",
    "CATALOG_DEFAULTS",
    "CATALOG_DEPENDENTS",
    "CATALOG_LABELS",
]


# ==========================================================================
# Errores
# ==========================================================================

class CatalogError(ValueError):
    """Base de los fallos previsibles del CRUD de catálogos."""


class CatalogNotFound(CatalogError):
    """El id no existe → 404."""


class CatalogDuplicate(CatalogError):
    """El ``name`` choca con el ``UNIQUE`` → 409."""


class CatalogInUse(CatalogError):
    """Hay filas que referencian el catálogo → 409."""


class CatalogValidationError(CatalogError):
    """Payload inválido (vacío, campo desconocido, modelo no soportado) → 400."""


# ==========================================================================
# Registro de los seis catálogos
# ==========================================================================

#: Campos que el service acepta escribir, por tabla. Cualquier otra clave del
#: payload es :class:`CatalogValidationError` — el endpoint no puede colar un
#: ``id`` ni un ``created_at``.
CATALOG_FIELDS: dict[str, tuple[str, ...]] = {
    "adhoc_areas": ("name", "color", "is_active"),
    "adhoc_processes": ("name", "color", "description"),
    "adhoc_document_categories": ("name",),
    "adhoc_document_classifications": ("name",),
    "adhoc_incident_categories": ("name",),
    "adhoc_program_categories": ("name",),
}

#: Defaults del alta cuando el payload no trae el campo. Coinciden con el
#: ``server_default`` de la columna; se aplican en Python para que el objeto
#: recién creado ya los tenga sin depender de un ``refresh``.
CATALOG_DEFAULTS: dict[str, dict[str, Any]] = {
    "adhoc_areas": {"color": "#4834d4", "is_active": True},
    "adhoc_processes": {"color": "#b2bec3"},
    "adhoc_document_categories": {},
    "adhoc_document_classifications": {},
    "adhoc_incident_categories": {},
    "adhoc_program_categories": {},
}

#: Campos que NO admiten ``None`` en un ``PATCH`` (columnas ``NOT NULL``).
CATALOG_NOT_NULL: dict[str, tuple[str, ...]] = {
    "adhoc_areas": ("name", "color", "is_active"),
    "adhoc_processes": ("name", "color"),
    "adhoc_document_categories": ("name",),
    "adhoc_document_classifications": ("name",),
    "adhoc_incident_categories": ("name",),
    "adhoc_program_categories": ("name",),
}

#: Artículos para los mensajes de error: ``(determinado, indeterminado)``.
CATALOG_LABELS: dict[str, tuple[str, str]] = {
    "adhoc_areas": ("el área", "un área"),
    "adhoc_processes": ("el proceso", "un proceso"),
    "adhoc_document_categories": ("la categoría de documento", "una categoría de documento"),
    "adhoc_document_classifications": (
        "la clasificación de documento", "una clasificación de documento",
    ),
    "adhoc_incident_categories": ("la categoría de incidencia", "una categoría de incidencia"),
    "adhoc_program_categories": ("la categoría de programa", "una categoría de programa"),
}

#: Quién referencia a quién: ``(clase del modelo, columna FK, singular, plural)``.
#: Son exactamente las FK **sin ``ondelete``** (RESTRICT) que apuntan a cada
#: catálogo; ``adhoc_user_areas`` queda fuera a propósito porque es CASCADE.
CATALOG_DEPENDENTS: dict[str, tuple[tuple[str, str, str, str], ...]] = {
    "adhoc_areas": (
        ("AdhocDocument", "area_id", "documento", "documentos"),
        ("AdhocIncident", "area_id", "incidencia", "incidencias"),
        ("AdhocProgramEvent", "area_id", "evento de programa", "eventos de programa"),
    ),
    "adhoc_processes": (
        ("AdhocDocument", "process_id", "documento", "documentos"),
        ("AdhocIncident", "process_id", "incidencia", "incidencias"),
        ("AdhocProgramEvent", "process_id", "evento de programa", "eventos de programa"),
    ),
    "adhoc_document_categories": (
        ("AdhocDocument", "category_id", "documento", "documentos"),
    ),
    "adhoc_document_classifications": (
        ("AdhocDocument", "classification_id", "documento", "documentos"),
    ),
    "adhoc_incident_categories": (
        ("AdhocIncident", "category_id", "incidencia", "incidencias"),
    ),
    "adhoc_program_categories": (
        ("AdhocProgramEvent", "category_id", "evento de programa", "eventos de programa"),
    ),
}


# ==========================================================================
# Helpers internos
# ==========================================================================

def _table(model) -> str:
    """Nombre de tabla del modelo, validando que sea uno de los seis catálogos."""
    table = getattr(model, "__tablename__", None)
    if table not in CATALOG_FIELDS:
        raise CatalogValidationError(
            f"{getattr(model, '__name__', model)!r} no es un catálogo simple de Calidad"
        )
    return table


def _the(table: str) -> str:
    return CATALOG_LABELS[table][0]


def _a(table: str) -> str:
    return CATALOG_LABELS[table][1]


def _clean_name(raw: Any) -> str:
    """Normaliza y valida el ``name``. Recorta espacios (bug de ``save_processes``)."""
    if not isinstance(raw, str) or not raw.strip():
        raise CatalogValidationError("El nombre es obligatorio")
    return raw.strip()


def _check_fields(table: str, payload: Mapping[str, Any]) -> None:
    unknown = sorted(set(payload) - set(CATALOG_FIELDS[table]))
    if unknown:
        raise CatalogValidationError(
            f"Campo no permitido para {_the(table)}: {', '.join(unknown)}"
        )


def _dependent_model(name: str):
    """Resuelve la clase del modelo dependiente. Import local: los modelos de
    adhoc importan ``User`` y este service lo importa un endpoint, así que un
    import de nivel de módulo invitaría a un ciclo (CLAUDE.md §5, gotcha 2)."""
    from itcj2.apps.adhoc import models as adhoc_models

    return getattr(adhoc_models, name)


def _humanize(counts: Mapping[str, int], table: str) -> str:
    """``{'documento': 3, 'incidencia': 1}`` → ``"3 documentos y 1 incidencia"``."""
    plurals = {sing: plur for _, _, sing, plur in CATALOG_DEPENDENTS[table]}
    parts = [
        f"{n} {sing if n == 1 else plurals.get(sing, sing)}"
        for sing, n in counts.items()
    ]
    if len(parts) == 1:
        return parts[0]
    return ", ".join(parts[:-1]) + " y " + parts[-1]


# ==========================================================================
# Resultado del alta masiva
# ==========================================================================

@dataclass(frozen=True)
class BulkCreateResult:
    """Qué se creó y qué se omitió en un alta masiva.

    ``skipped`` lleva los nombres **tal como llegaron** (ya recortados), para
    que la UI pueda decir "«Auditoría» ya existía" en vez de un conteo mudo.
    """

    created: list
    skipped: list[str]

    @property
    def created_count(self) -> int:
        return len(self.created)

    @property
    def skipped_count(self) -> int:
        return len(self.skipped)

    @property
    def message(self) -> str:
        creados = f"{self.created_count} registro(s) creado(s)"
        if not self.skipped:
            return creados
        return f"{creados}; {self.skipped_count} omitido(s) por nombre duplicado"


# ==========================================================================
# Service
# ==========================================================================

class AdhocCatalogService:
    """CRUD de los seis catálogos simples. Métodos estáticos, ``db`` primero,
    commit dentro del service."""

    # ---------------------------------------------------------------- read
    @staticmethod
    def list_items(
        db: Session,
        model,
        *,
        is_active: Optional[bool] = None,
        search: Optional[str] = None,
    ) -> list:
        """Lista el catálogo completo ordenado por ``name``.

        ``is_active`` solo aplica a ``adhoc_areas`` (es el único catálogo con
        esa columna); en el resto se ignora, para que el endpoint genérico
        pueda pasarlo sin ramificar. ``None`` = sin filtrar (activos **e**
        inactivos), que es lo contrario del legacy: ahí el filtro estaba
        cableado y las filas con ``is_active NULL`` desaparecían sin aviso.
        """
        table = _table(model)

        query = db.query(model)

        if is_active is not None and "is_active" in CATALOG_FIELDS[table]:
            query = query.filter(model.is_active.is_(bool(is_active)))

        if search and search.strip():
            query = query.filter(model.name.ilike(f"%{search.strip()}%"))

        return query.order_by(model.name.asc()).all()

    @staticmethod
    def get(db: Session, model, item_id: int):
        """Devuelve la fila o lanza :class:`CatalogNotFound`."""
        table = _table(model)
        item = db.get(model, item_id)
        if item is None:
            raise CatalogNotFound(f"No se encontró {_the(table)} con id {item_id}")
        return item

    # --------------------------------------------------------------- create
    @staticmethod
    def bulk_create(db: Session, model, items: Sequence[Mapping[str, Any]]) -> BulkCreateResult:
        """Alta masiva **deduplicada**.

        El legacy mandaba listas paralelas (``nombres[]`` / ``colores[]``) y las
        insertaba a pelo; aquí llega una lista de dicts ya validada por Pydantic.
        Se omite —sin abortar el lote— todo nombre que ya exista en la tabla o
        que se repita dentro del propio payload, comparando **sin distinguir
        mayúsculas ni acentos de caja**: el ``UNIQUE`` de la BD es
        case-sensitive, así que "Calidad" y "calidad" cabrían las dos, pero en
        un catálogo eso es un duplicado a efectos humanos.

        El ``IntegrityError`` sigue capturado como red de seguridad por si dos
        peticiones concurrentes insertan el mismo nombre entre el chequeo y el
        commit; en ese caso se revierte y se responde 409 en vez de un 500.
        """
        table = _table(model)

        if not items:
            raise CatalogValidationError("No se recibió ningún elemento para crear")

        # 1. Normaliza y valida cada elemento antes de tocar la BD.
        normalized: list[dict[str, Any]] = []
        for raw in items:
            payload = dict(raw)
            _check_fields(table, payload)
            data = dict(CATALOG_DEFAULTS[table])
            data.update({k: v for k, v in payload.items() if v is not None})
            data["name"] = _clean_name(payload.get("name"))
            normalized.append(data)

        # 2. Nombres ya tomados en la tabla (case-insensitive).
        lowered = [d["name"].lower() for d in normalized]
        taken = {
            row[0]
            for row in db.query(func.lower(model.name))
            .filter(func.lower(model.name).in_(lowered))
            .all()
        }

        # 3. Filtra duplicados (de BD y del propio payload) conservando el orden.
        to_create: list[dict[str, Any]] = []
        skipped: list[str] = []
        seen: set[str] = set()
        for data in normalized:
            key = data["name"].lower()
            if key in taken or key in seen:
                skipped.append(data["name"])
                continue
            seen.add(key)
            to_create.append(data)

        if not to_create:
            logger.info(
                "Alta masiva en %s sin altas: %d nombre(s) duplicado(s)", table, len(skipped)
            )
            return BulkCreateResult(created=[], skipped=skipped)

        objects = [model(**data) for data in to_create]
        db.add_all(objects)

        try:
            db.flush()
            # Los ids se capturan ANTES del commit: tras commitear los objetos
            # quedan expirados y leerlos dispararía un SELECT por fila (N+1).
            new_ids = [obj.id for obj in objects]
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            logger.warning("Alta masiva en %s abortada por IntegrityError: %s", table, exc)
            raise CatalogDuplicate(
                f"Ya existe {_a(table)} con uno de esos nombres; vuelve a intentarlo"
            ) from exc

        created = (
            db.query(model)
            .filter(model.id.in_(new_ids))
            .order_by(model.name.asc())
            .all()
        )
        # Se respeta el orden en el que llegaron, no el alfabético del re-fetch.
        by_id = {obj.id: obj for obj in created}
        created = [by_id[i] for i in new_ids if i in by_id]

        logger.info(
            "Alta masiva en %s: %d creado(s), %d omitido(s)", table, len(created), len(skipped)
        )
        return BulkCreateResult(created=created, skipped=skipped)

    # --------------------------------------------------------------- update
    @staticmethod
    def update(db: Session, model, item_id: int, changes: Mapping[str, Any]):
        """Actualización parcial. ``changes`` ya viene de ``model_dump(exclude_unset=True)``."""
        table = _table(model)
        item = AdhocCatalogService.get(db, model, item_id)

        changes = dict(changes)
        if not changes:
            raise CatalogValidationError("No se recibió ningún campo para actualizar")
        _check_fields(table, changes)

        for field in CATALOG_NOT_NULL[table]:
            if field in changes and changes[field] is None:
                raise CatalogValidationError(
                    f"El campo «{field}» no puede quedar vacío"
                )

        if "name" in changes:
            new_name = _clean_name(changes["name"])
            changes["name"] = new_name
            clash = (
                db.query(model.id)
                .filter(func.lower(model.name) == new_name.lower())
                .filter(model.id != item_id)
                .first()
            )
            if clash is not None:
                raise CatalogDuplicate(f"Ya existe {_a(table)} con el nombre «{new_name}»")

        for field, value in changes.items():
            setattr(item, field, value)

        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            logger.warning("Update de %s#%s abortado por IntegrityError: %s", table, item_id, exc)
            raise CatalogDuplicate(f"Ya existe {_a(table)} con ese nombre") from exc

        db.refresh(item)
        return item

    # --------------------------------------------------------------- delete
    @staticmethod
    def count_dependents(db: Session, model, item_id: int) -> dict[str, int]:
        """Cuántas filas referencian el catálogo, por tipo. Solo entradas > 0."""
        table = _table(model)
        counts: dict[str, int] = {}
        for model_name, fk, singular, _plural in CATALOG_DEPENDENTS[table]:
            dependent = _dependent_model(model_name)
            n = db.query(func.count(dependent.id)).filter(
                getattr(dependent, fk) == item_id
            ).scalar() or 0
            if n:
                counts[singular] = int(n)
        return counts

    @staticmethod
    def delete(db: Session, model, item_id: int) -> None:
        """Borra el catálogo, o lanza :class:`CatalogInUse` si algo lo referencia.

        El legacy hacía ``db.session.delete()`` a ciegas y el ``IntegrityError``
        resultante se lo tragaba un ``except Exception`` → el usuario veía un
        redirect "exitoso" y el registro seguía ahí.
        """
        table = _table(model)
        item = AdhocCatalogService.get(db, model, item_id)
        name = item.name

        counts = AdhocCatalogService.count_dependents(db, model, item_id)
        if counts:
            raise CatalogInUse(
                f"No se puede eliminar {_the(table)} «{name}»: "
                f"está en uso por {_humanize(counts, table)}."
            )

        db.delete(item)
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            logger.warning("Delete de %s#%s abortado por IntegrityError: %s", table, item_id, exc)
            raise CatalogInUse(
                f"No se puede eliminar {_the(table)} «{name}»: hay registros que la referencian."
            ) from exc

        logger.info("Catálogo %s#%s («%s») eliminado", table, item_id, name)
