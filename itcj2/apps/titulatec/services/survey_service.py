"""Motor de la encuesta de egresados: formulario abierto, borradores, envio y export.

Contrato de escritura (seccion 4.4 del diseno): validar -> `SurveyResponse` ->
filas de `SurveyAnswer` -> borrar el borrador -> acreditar el requisito -> UN
SOLO `commit` al final. Si la validacion falla no se escribe NADA.

Mapeo tipo -> columna de `titulatec_survey_answers`, exhaustivo:

    scale                          -> 1 fila, `value_num`
    yesno, checkbox                -> 1 fila, `value_bool`
    text, textarea, select, radio  -> 1 fila, `value_text`
    multiselect                    -> N filas, `value_text` = valor de la opcion
                                      y `value_bool = True`

`multiselect` es un tipo APARTE de `checkbox` justamente por esto: si compartieran
tipo, las filas de `survey_answers` serian indistinguibles y esa tabla existe
para poder promediar la pregunta 3 sobre 400 respuestas.
"""
from __future__ import annotations

import hashlib
import json
import logging

from sqlalchemy.orm import Session

from itcj2.core.utils.timezone import db_now

logger = logging.getLogger("itcj2.apps.titulatec.services.survey")

# — Constantes compartidas (seccion 5 del contrato de interfaces) —
SURVEY_CODE = "egresados"
AUTO_SOURCE_SURVEY = "graduate_survey"
MAX_PUBLIC_BODY_BYTES = 256 * 1024
MAX_ANSWERS_JSON_BYTES = 128 * 1024
DRAFT_DEBOUNCE_MS = 5000
DRAFT_MIN_INTERVAL_MS = 30000

# Primer caracter que Excel y LibreOffice interpretan como formula.
_FORMULA_LEADERS = ("=", "+", "-", "@", "\t", "\r")


def _answers_size(answers) -> int:
    """Bytes UTF-8 de la proyeccion serializada. Es la cota real de la columna JSON."""
    return len(json.dumps(answers, ensure_ascii=False, default=str).encode("utf-8"))


def _hash(value: str | None) -> str | None:
    """`sha256(valor + SECRET_KEY)`. Nunca se guarda la IP en claro (seccion 3.3)."""
    if not value:
        return None
    from itcj2.config import get_settings
    return hashlib.sha256(
        (str(value) + str(get_settings().SECRET_KEY)).encode("utf-8")).hexdigest()


def escape_formula(cell) -> str:
    """Prefija con `'` toda celda que una hoja de calculo leeria como formula.

    Incondicional y para TODA columna, no solo las respuestas (seccion 8.2). Las
    celdas de `answers` las escribe un anonimo —la encuesta se promueve en
    publico y no exige sesion—, pero el escapado no se limita a ellas: en cuanto
    el export gane una columna mas, esa columna nace protegida sin que nadie
    tenga que acordarse. Es la primera vez que el repo exporta contenido de autor
    no confiable, y el destinatario lo abre en Excel en una maquina con acceso
    admin a titulatec.
    """
    text = "" if cell is None else str(cell)
    if text[:1] in _FORMULA_LEADERS:
        return "'" + text
    return text


def form_to_dict(schema: dict, form_data) -> dict:
    """`FormData` de `await request.form()` -> dict apto para `submit`.

    Existe por una sola razon, medida y no obvia: **`FormData` no colapsa las
    llaves repetidas a lista**. Un grupo de casillas de un `multiselect` manda la
    misma llave N veces, y tanto `.get("idiomas")` como `dict(form_data)`
    devuelven SOLO LA ULTIMA (`'fr'` de `[("idiomas","en"),("idiomas","fr")]`).
    Un escalar donde el validador espera lista hace fallar TODO multiselect con
    "se esperaba una lista de opciones" —o "selecciona al menos una opcion" si es
    obligatorio—. Falla cerrado, asi que no es un agujero de seguridad; es peor
    en otro sentido: rompe la funcion en silencio y culpando al campo equivocado.

    El puente vive en este modulo, y no en la pagina, porque quien sabe que
    llaves son `multiselect` es el `schema` — y este modulo ya es el que lo
    interpreta (`submit` construye el mismo `by_key` para mapear tipo -> columna).
    Dejarselo a cada llamador obliga a repetir esa lectura en la pagina publica,
    en un futuro import y en cualquier otro consumidor, y basta que uno lo olvide
    para reintroducir el fallo silencioso.

    `submit` NO recibe el `FormData` directamente a proposito: mantiene su
    contrato de dict plano, que es lo que lo hace probable sin Starlette.
    """
    getlist = getattr(form_data, "getlist", None)
    submitted = dict(form_data or {})
    if getlist is None:                     # ya es un dict plano: nada que hacer
        return submitted
    for field in ((schema or {}).get("fields") or []):
        if isinstance(field, dict) and field.get("type") == "multiselect" and field.get("key"):
            key = str(field["key"])
            submitted[key] = getlist(key)   # ausente -> [], que es "no contestado"
    return submitted


def _cell(value) -> str:
    """Valor de `answers` -> texto de celda. `multiselect` se une con '; '."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "si" if value else "no"
    if isinstance(value, list):
        return "; ".join(str(v) for v in value)
    return str(value)


class SurveyService:
    # -----------------------------------------------------------------
    # Formulario
    # -----------------------------------------------------------------
    @staticmethod
    def open_form(db: Session, code: str):
        """Resolver canonico: `code` + `status='open'`, la version mas alta.

        El indice parcial `uq_titulatec_survey_forms_open` garantiza que a lo
        mas hay una; el ORDER BY es el cinturon por si el indice no existiera
        (la CI de base vacia corre `create_all`, que no lo crea).
        """
        from itcj2.apps.titulatec.models import SurveyForm
        return (db.query(SurveyForm)
                .filter(SurveyForm.code == code, SurveyForm.status == "open")
                .order_by(SurveyForm.version.desc())
                .first())

    # -----------------------------------------------------------------
    # Borradores (solo con sesion)
    # -----------------------------------------------------------------
    @staticmethod
    def get_draft(db: Session, form_id: int, user_id: int):
        from itcj2.apps.titulatec.models import SurveyDraft
        return db.query(SurveyDraft).filter_by(form_id=form_id, user_id=user_id).first()

    @staticmethod
    def save_draft(db: Session, form_id: int, user_id: int, answers: dict):
        """Upsert de UNA fila `(form_id, user_id)`. Sin historial. Commitea.

        RECHAZA por encima de `MAX_ANSWERS_JSON_BYTES` en vez de truncar
        (seccion 8.2): truncar deja al alumno con un borrador silenciosamente
        mutilado y creyendo que se guardo entero.
        """
        from itcj2.apps.titulatec.models import SurveyDraft

        if not isinstance(answers, dict):
            raise ValueError("El borrador debe ser un objeto de respuestas.")
        if _answers_size(answers) > MAX_ANSWERS_JSON_BYTES:
            raise ValueError("El borrador excede el tamano maximo permitido.")

        row = db.query(SurveyDraft).filter_by(form_id=form_id, user_id=user_id).first()
        if row is None:
            row = SurveyDraft(form_id=form_id, user_id=user_id, answers=answers,
                              updated_at=db_now())
            db.add(row)
        else:
            row.answers = answers
            row.updated_at = db_now()
        db.commit()
        db.refresh(row)
        return row

    # -----------------------------------------------------------------
    # Envio
    # -----------------------------------------------------------------
    @staticmethod
    def submit(db: Session, form, submitted: dict, *,
               user_id: int | None, client_ip: str | None, user_agent: str | None
               ) -> tuple[object | None, dict[str, str], str]:
        """Escribe una respuesta completa. Devuelve `(response, errors, credit_status)`.

        `credit_status` en {'credited','no_process','no_requirement','already',
        'anonymous'}. En la rama de error `response` es None y `credit_status`
        vale 'anonymous': el llamador no debe leerlo cuando no hay respuesta.

        UN SOLO `commit`, al final (seccion 4.4 paso 7). Por eso el cumplimiento
        se escribe con `commit=False`.
        """
        from itcj2.apps.titulatec.models import SurveyAnswer, SurveyDraft, SurveyResponse
        from itcj2.apps.titulatec.utils.survey_validator import validate_answers

        ok, errors, cleaned = validate_answers(form.schema or {}, submitted or {})
        if not ok:
            return None, errors, "anonymous"

        if _answers_size(cleaned) > MAX_ANSWERS_JSON_BYTES:
            # Se RECHAZA, no se trunca: una respuesta a medias es peor que un no.
            return None, {"__form__": "Tu respuesta es demasiado larga. "
                                      "Acortala e intentalo de nuevo."}, "anonymous"

        process = None
        control_number = None
        if user_id is not None:
            from itcj2.core.models import User
            from itcj2.apps.titulatec.services.process_service import ProcessService
            # Mismo selector que renderiza el checklist del alumno (seccion 5.3):
            # si los dos lados no llaman a este helper, el cumplimiento aterriza
            # en un proceso distinto del que el alumno ve.
            process = ProcessService.creditable_process(db, user_id)
            user = db.get(User, user_id)
            control_number = getattr(user, "control_number", None)

        response = SurveyResponse(
            form_id=form.id,
            form_version=form.version,                 # SNAPSHOT
            user_id=user_id,
            process_id=(process.id if process is not None else None),
            cohort_id=(process.cohort_id if process is not None else None),
            identity_source=("session" if user_id is not None else "anonymous"),
            control_number=control_number,
            answers=cleaned,                           # la proyeccion VALIDADA
            client_ip_hash=_hash(client_ip),
            user_agent_hash=_hash(user_agent),
        )
        db.add(response)
        db.flush()                                     # necesitamos `response.id`

        by_key = {f.get("key"): f
                  for f in ((form.schema or {}).get("fields") or [])
                  if isinstance(f, dict)}

        for key, value in cleaned.items():
            field_type = (by_key.get(key) or {}).get("type") or "text"
            if field_type == "multiselect":
                for option in value:
                    db.add(SurveyAnswer(response_id=response.id, field_key=key,
                                        field_type=field_type,
                                        value_text=str(option), value_bool=True))
            elif field_type == "scale":
                db.add(SurveyAnswer(response_id=response.id, field_key=key,
                                    field_type=field_type, value_num=value))
            elif field_type in ("yesno", "checkbox"):
                db.add(SurveyAnswer(response_id=response.id, field_key=key,
                                    field_type=field_type, value_bool=bool(value)))
            else:
                db.add(SurveyAnswer(response_id=response.id, field_key=key,
                                    field_type=field_type, value_text=str(value)))

        credit_status = "anonymous"
        if user_id is not None:
            db.query(SurveyDraft).filter_by(
                form_id=form.id, user_id=user_id).delete(synchronize_session=False)
            credit_status = SurveyService._credit(db, process, response)

        db.commit()
        db.refresh(response)
        return response, {}, credit_status

    @staticmethod
    def _credit(db: Session, process, response) -> str:
        """Reglas 2-4 de la seccion 6.3. NO commitea: lo hace `submit`."""
        from itcj2.apps.titulatec.models import RequirementFulfillment
        from itcj2.apps.titulatec.services.requirement_service import RequirementService

        if process is None:
            return "no_process"

        requirement = RequirementService.auto_requirement(
            db, process.cohort_id, AUTO_SOURCE_SURVEY)
        if requirement is None:
            return "no_requirement"

        ya = (db.query(RequirementFulfillment)
              .filter_by(process_id=process.id, requirement_id=requirement.id)
              .first())
        if ya is not None:
            return "already"

        RequirementService.fulfill(
            db, process.id, requirement.id,
            source="system",
            external_ref=f"survey_response:{response.id}",
            commit=False,
        )
        return "credited"

    # -----------------------------------------------------------------
    # Export
    # -----------------------------------------------------------------
    @staticmethod
    def export_rows(db: Session, form_id: int) -> tuple[list[str], list[list[str]]]:
        """`(encabezados, filas)` ya escapadas contra inyeccion de formulas.

        Las columnas variables salen del `schema` del formulario, en su orden,
        asi que dos versiones distintas producen dos exports distintos — que es
        lo correcto: la seccion 3.3 congela `form_version` justo para eso.
        """
        from itcj2.apps.titulatec.models import SurveyForm, SurveyResponse

        form = db.get(SurveyForm, form_id)
        fields = [f for f in ((getattr(form, "schema", None) or {}).get("fields") or [])
                  if isinstance(f, dict)] if form is not None else []
        keys = [str(f.get("key")) for f in fields]

        headers = ["id", "enviada_en", "identidad", "numero_control",
                   "proceso_id", "convocatoria_id", "version"] + keys

        rows: list[list[str]] = []
        for r in (db.query(SurveyResponse)
                  .filter(SurveyResponse.form_id == form_id)
                  .order_by(SurveyResponse.id)
                  .all()):
            answers = r.answers or {}
            crudas = [
                r.id,
                r.submitted_at.isoformat(sep=" ", timespec="seconds") if r.submitted_at else "",
                r.identity_source or "",
                r.control_number or "",
                r.process_id or "",
                r.cohort_id or "",
                r.form_version,
            ] + [_cell(answers.get(k)) for k in keys]
            # Escapado INCONDICIONAL y para TODA columna (seccion 8.2).
            rows.append([escape_formula(c) for c in crudas])

        return headers, rows
