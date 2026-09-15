"""Requisitos de cotejo (qué llevar a la cita) — configurables por convocatoria.

La jefa de Servicios Escolares define la lista por cohorte. Si una convocatoria
no tiene requisitos aún, se siembra con DEFAULTS al consultarlos.

Cada requisito puede llevar además «Información para el alumno» (`info_html`):
HTML con formato que llega crudo del editor visual, se guarda SANITIZADO
(`utils/rich_text.sanitize_info_html`) y el alumno abre con el botón «i» de su
cita. Las vistas lo vuelven a sanitizar al pintar.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

# Información por defecto. HTML ya CANÓNICO: `sanitize_info_html` lo devuelve
# idéntico (lo fija test_cotejo_requirements.py), así que lo sembrado y lo que ve
# el alumno —re-sanitizado al pintar— son la misma cadena.
#
# Solo acta y CURP, y a propósito: son los dos documentos que el alumno YA subió
# en la fase 1, y la duda real es si debe traer «otro». Los demás —biblioteca
# incluida— los escribe Servicios Escolares con los datos verdaderos: un
# placeholder sembrado se le mostraría al alumno como si fuera información.
INFO_BIRTH_CERTIFICATES = (
    "<p>Debe ser el <strong>mismo documento que subiste en TitulaTec</strong> "
    "(fase 1). Llévalo en original.</p>"
)
INFO_CURP = (
    "<p>Debe ser la <strong>misma CURP certificada que subiste en TitulaTec</strong> "
    "(fase 1), impresa.</p>"
)

# Lista por defecto (la que estaba hardcodeada en la vista del alumno).
#
# 6-tuplas: (icon, label, hint, code, auto_source, info_html).
#   * `code` da identidad ESTABLE al requisito: la etiqueta la reescribe
#     Servicios Escolares cuando quiere, el código no.
#   * `auto_source` marca los que acredita el SISTEMA. Es la única fuente de ese
#     valor: `create()` no puede fijarlo desde la UI a propósito, porque un
#     requisito automático borrado a media convocatoria dejaría a la encuesta sin
#     nada que acreditar y sin forma de restaurarlo.
#   * `info_html` es la información enriquecida por defecto (None = sin botón
#     «i»). `database/DML/titulatec/survey_2026_09/13_seed_cotejo_reqs_all_cohorts.sql`
#     repite estos textos y el 12 los aplica a las filas que ya existían:
#     cambiar uno obliga a cambiar los tres.
DEFAULTS = [
    ("file-earmark-text", "Actas de nacimiento", "Original + copias.",
     "birth_certificates", None, INFO_BIRTH_CERTIFICATES),
    ("card-text", "CURP certificada", "Impresión certificada (no la simple).",
     "curp", None, INFO_CURP),
    ("shield-check", "e.Firma (SAT)", "Constancia de situación fiscal con e.Firma vigente.",
     "efirma", None, None),
    ("clipboard-check", "Encuesta de egresados", "Comprobante de haberla contestado.",
     "graduate_survey", "graduate_survey", None),
    ("book", "No-adeudo de biblioteca", "Constancia de no adeudo vigente.",
     "library_clearance", None, None),
    ("camera", "12 fotografías", "Tamaño credencial, ovaladas, B/N, fondo blanco, papel mate.",
     "photos", None, None),
    ("heart-pulse", "Vigencia de derechos IMSS", "Documento que acredite vigencia.",
     "imss", None, None),
    ("cash-coin", "$1,900 en efectivo", "Pago del proceso de titulación (efectivo).",
     "payment", None, None),
]


class CotejoRequirementService:
    @staticmethod
    def list(db: Session, cohort_id: int, *, active_only: bool = True) -> list:
        from itcj2.apps.titulatec.models import CotejoRequirement
        q = db.query(CotejoRequirement).filter_by(cohort_id=cohort_id)
        if active_only:
            q = q.filter_by(is_active=True)
        return q.order_by(CotejoRequirement.order_index, CotejoRequirement.id).all()

    @staticmethod
    def seed_defaults(db: Session, cohort_id: int, *, commit: bool = True) -> int:
        """Crea los requisitos por defecto si la convocatoria no tiene ninguno.

        `commit=False` es para los llamadores que YA son dueños de su
        transacción: `RequirementService.auto_requirement` (§4.4 del diseño exige
        un solo commit al enviar la encuesta) y `cohort_create`, que siembra en
        la misma transacción en que crea la convocatoria.

        Es la ÚNICA escritura de `code`/`auto_source`.
        """
        from itcj2.apps.titulatec.models import CotejoRequirement
        exists = db.query(CotejoRequirement).filter_by(cohort_id=cohort_id).first()
        if exists:
            return 0
        for i, (icon, label, hint, code, auto_source, info_html) in enumerate(DEFAULTS):
            db.add(CotejoRequirement(cohort_id=cohort_id, icon=icon, label=label,
                                     hint=hint, code=code, auto_source=auto_source,
                                     info_html=info_html, order_index=i))
        if commit:
            db.commit()
        else:
            db.flush()
        return len(DEFAULTS)

    @staticmethod
    def list_or_seed(db: Session, cohort_id: int, *, active_only: bool = True) -> list:
        """Lista los requisitos; si no hay ninguno, siembra los defaults primero."""
        items = CotejoRequirementService.list(db, cohort_id, active_only=active_only)
        if not items:
            CotejoRequirementService.seed_defaults(db, cohort_id)
            items = CotejoRequirementService.list(db, cohort_id, active_only=active_only)
        return items

    @staticmethod
    def create(db: Session, cohort_id: int, *, label: str, hint: str | None,
               icon: str | None, is_required: bool = True,
               info_html: str | None = None):
        """Agrega un requisito al final de la lista.

        `info_html` llega CRUDO del editor y se guarda sanitizado. Si excede el
        tope, `InfoHtmlTooLong` sale ANTES de tocar la sesión: no se crea nada.
        """
        from itcj2.apps.titulatec.models import CotejoRequirement
        from itcj2.apps.titulatec.utils.rich_text import sanitize_info_html

        info = sanitize_info_html(info_html)
        last = (db.query(CotejoRequirement).filter_by(cohort_id=cohort_id)
                .order_by(CotejoRequirement.order_index.desc()).first())
        item = CotejoRequirement(
            cohort_id=cohort_id, label=label.strip(), hint=(hint or None),
            icon=(icon or "check2-square"), is_required=is_required,
            info_html=info,
            order_index=(last.order_index + 1 if last else 0),
        )
        db.add(item)
        db.commit()
        db.refresh(item)
        return item

    @staticmethod
    def update(db: Session, req_id: int, cohort_id: int, **fields):
        """Actualiza el requisito. Candado para el automático (D9).

        Un requisito con `auto_source` (hoy solo 'graduate_survey') es el que
        ACREDITA el sistema, y `RequirementService.missing_required` —la
        guarda que bloquea el dictamen de la fase 2— solo mira filas
        `is_active=True AND is_required=True`. Si el editor pudiera volverlo
        opcional o inactivo, esa guarda se desarmaría en silencio (pasó en
        dev: alguien corrió un UPDATE manual mientras la encuesta no existía
        y nunca se revirtió). Por eso aquí `is_required`/`is_active` se fuerzan
        a `True` para estos SIN importar lo que traiga `fields` — `label`,
        `hint`, `icon`, `order_index` e `info_html` sí se siguen pudiendo editar.

        `info_html` tiene semántica PROPIA: lo que cuenta es que la llave esté en
        `fields`. Ausente = no se toca; presente con `None` o vacío = se BORRA
        (vaciar el editor es quitar la información). Se sanitiza ANTES de
        cualquier `setattr`, así que `InfoHtmlTooLong` no deja cambios a medias
        en la sesión.
        """
        from itcj2.apps.titulatec.models import CotejoRequirement
        from itcj2.apps.titulatec.utils.rich_text import sanitize_info_html

        item = db.query(CotejoRequirement).filter_by(id=req_id, cohort_id=cohort_id).first()
        if not item:
            return None
        cambia_info = "info_html" in fields
        info = sanitize_info_html(fields["info_html"]) if cambia_info else None
        if item.auto_source:
            fields = {**fields, "is_required": True, "is_active": True}
        for k in ("label", "hint", "icon", "is_required", "is_active", "order_index"):
            if k in fields and fields[k] is not None:
                setattr(item, k, fields[k])
        if cambia_info:
            item.info_html = info
        db.commit()
        db.refresh(item)
        return item

    @staticmethod
    def delete(db: Session, req_id: int, cohort_id: int) -> tuple[bool, str]:
        """Borra el requisito. Devuelve `(ok, motivo)`.

        `motivo` ∈ ``"ok"`` | ``"not_found"`` | ``"fulfilled:{N}"``.

        La comprobación de cumplimientos va ANTES del `db.delete`: la FK de
        `titulatec_requirement_fulfillments.requirement_id` es `ON DELETE
        RESTRICT` (a propósito, para que borrar la lista no destruya el crédito
        de quien ya cumplió), así que sin esto Postgres contestaría con un
        `IntegrityError` crudo a mitad de un POST de la UI. La vía soportada es
        `is_active = False`, que ya existe en modelo, ruta y parcial.
        """
        from itcj2.apps.titulatec.models import CotejoRequirement, RequirementFulfillment
        item = db.query(CotejoRequirement).filter_by(id=req_id, cohort_id=cohort_id).first()
        if not item:
            return False, "not_found"
        usados = (db.query(RequirementFulfillment)
                  .filter_by(requirement_id=req_id).count())
        if usados:
            return False, f"fulfilled:{usados}"
        db.delete(item)
        db.commit()
        return True, "ok"
