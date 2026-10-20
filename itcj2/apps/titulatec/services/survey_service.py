"""Motor de la encuesta de egresados: formulario abierto, borradores, envio y export.

Contrato de escritura (seccion 4.4 del diseno): validar -> `SurveyResponse` ->
filas de `SurveyAnswer` -> borrar el borrador -> abrir la solicitud de
liberacion -> UN SOLO `commit` al final. Si la validacion falla no se escribe
NADA.

Tarea 3 (spec `2026-09-15-titulatec-liberacion-gtv-design.md` 5.3, D6): el
envio de la encuesta YA NO acredita nada por si solo. Lo que antes hacia
`SurveyService._credit` -sembrar/leer el `CotejoRequirement` con
`auto_source='graduate_survey'` y `fulfill`-lo de una vez- desaparecio de este
modulo: ahora un envio con proceso acreditable abre una solicitud de
liberacion (`SurveyReviewService.open_for_submission`) para que Gestion
Tecnologica y Vinculacion decida despues, desde su bandeja, si libera el
requisito o deja observaciones. La encuesta queda CONGELADA tras ese primer
envio -quien ya tiene solicitud no puede volver a enviarla-.

Mapeo tipo -> columna de `titulatec_survey_answers`, exhaustivo:

    scale                          -> 1 fila, `value_num`
    yesno, checkbox                -> 1 fila, `value_bool`
    text, textarea, select, radio  -> 1 fila, `value_text`
    date                           -> 1 fila, `value_text` en ISO `AAAA-MM-DD`
                                      (2026-09-15; el export la deja igual)
    multiselect                    -> N filas, `value_text` = valor de la opcion
                                      y `value_bool = True`

Un `text` con `validation.format` guarda el valor NORMALIZADO que devuelve el
validador (el telefono en digitos, la coma decimal como punto), no el crudo.

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
# Perfil de posgrado (spec 2026-09-30-titulatec-posgrado-design.md seccion 4.5, D3):
# su contenido AUN NO EXISTE. Hasta que se publique una version 'open' con
# este `code`, posgrado contesta la de licenciatura -- ver
# `SURVEY_CODES_BY_TRACK` y `form_for_user`, junto a `open_form` mas abajo.
SURVEY_CODE_POSGRADO = "egresados_posgrado"
# Perfil (lo que devuelve `TrackService`, invariante 2) -> cadena de codigos a
# probar EN ORDEN: gana el primero con formulario `open` (`form_for_user`).
# Licenciatura es una cadena de UN solo elemento, asi que su comportamiento
# queda IDENTICO al de `SURVEY_CODE` solo (invariante 3, spec seccion 6).
SURVEY_CODES_BY_TRACK = {
    "licenciatura": (SURVEY_CODE,),
    "posgrado": (SURVEY_CODE_POSGRADO, SURVEY_CODE),
}
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

    @staticmethod
    def form_for_user(db: Session, user_id: int | None):
        """Formulario que le toca contestar a ESTE visitante, por perfil.

        Spec 2026-09-30-titulatec-posgrado-design.md seccion 4.5, invariante 5: el
        formulario se resuelve por REQUEST, nunca por una constante fija. Es
        el reemplazo directo de `open_form(db, SURVEY_CODE)` en las 4 rutas
        publicas (GET, paso, borrador, envio).

        Sin `user_id` (visitante anonimo) o sin proceso acreditable
        (`ProcessService.creditable_process` -- el MISMO selector que ya usa
        `_solicitud_existente` en `pages/public.py` para decidir "no hay nada
        que congelar"), resuelve la cadena de licenciatura: invariante 3, la
        licenciatura -y quien todavia no tiene proceso- ve exactamente lo que
        veia antes de esta tarea.

        Con proceso, `TrackService.for_process` da el perfil y
        `SURVEY_CODES_BY_TRACK` la cadena de codigos a probar EN ORDEN: gana
        el primero con `open_form(...)` no nulo. D3 (interino): mientras
        `egresados_posgrado` no tenga ninguna version en `status='open'`, un
        posgrado cae a `egresados` -exactamente como licenciatura-, y el
        cambio a su propio formulario es automatico en cuanto alguien
        publique esa version, sin tocar este metodo ni ningun llamador.

        Fallo transitorio (ronda de revision R10): si resolver el proceso o
        el perfil revienta -`ProcessService.creditable_process` o
        `TrackService.for_process`-, esto degrada a la cadena de
        licenciatura en vez de propagar la excepcion, el MISMO riesgo y el
        MISMO criterio que ya usa `_solicitud_existente` en `pages/public.py`
        para el mismo gate (BD/Redis caidos): la ley del modulo ("Ninguna
        entrada del visitante puede producir un 500") tambien aplica aqui,
        aunque este metodo viva en el service. Igual que `_solicitud_
        existente`, este primer catch NO hace `db.rollback()`: un fallo que
        nunca toco la BD (el `RuntimeError` que simulan las pruebas, o
        cualquier error puramente de Python) deja la sesion tan sana como
        estaba, y un `rollback()` a la fuerza aqui DESCARTARIA sin necesidad
        todo lo que esa misma sesion ya tenia pendiente -en un test, las filas
        que los fixtures acaban de insertar (incluido el propio `User` del
        JWT en curso): se probo agregando un rollback incondicional en esta
        rama y `test_fallo_transitorio_en_solicitud_existente_no_produce_500`
        pasaba a fallar con `ForeignKeyViolation` sobre `core_student_profile`
        -el `User` del alumno ya no estaba-, y la prueba nueva de este mismo
        archivo resolvia el `egresados` sembrado en dev (id real) en vez del
        que el propio test acababa de crear. La consulta de respaldo de abajo
        SI necesita su propio rollback si de verdad hereda una transaccion
        abortada (un `OperationalError` real no se recupera solo), pero eso
        se resuelve REACTIVAMENTE, solo si esa consulta falla -nunca antes-.
        """
        from itcj2.apps.titulatec.services.process_service import ProcessService
        from itcj2.apps.titulatec.services.track_service import TRACK_LICENCIATURA, TrackService

        track = TRACK_LICENCIATURA
        if user_id is not None:
            try:
                process = ProcessService.creditable_process(db, user_id)
                if process is not None:
                    track = TrackService.for_process(db, process)
            except Exception:
                # `exc_info=True` (Menor #5, revisión final 2026-09-30): sin
                # esto el log decía QUE algo falló pero nunca POR QUÉ -- la
                # causa real (traceback) se perdía en cuanto el `except` la
                # atrapaba.
                logger.warning(
                    "survey: fallo resolviendo el perfil del proceso (user_id=%s)", user_id,
                    exc_info=True)
                track = TRACK_LICENCIATURA

        try:
            for code in SURVEY_CODES_BY_TRACK[track]:
                form = SurveyService.open_form(db, code)
                if form is not None:
                    return form
            return None
        except Exception:
            # Solo se llega aqui si la consulta de arriba SI revento -nunca
            # por el fallo ya atrapado arriba, que jamas toco la BD-: una
            # transaccion de verdad abortada (`OperationalError`) no se
            # recupera sin rollback, asi que aqui SI hace falta antes de
            # reintentar UNA vez, con la cadena de licenciatura (el mismo
            # respaldo de siempre).
            logger.warning(
                "survey: fallo consultando el formulario abierto; reintentando tras rollback "
                "(user_id=%s)", user_id, exc_info=True)
            try:
                db.rollback()
            except Exception:      # pragma: no cover - sesion ya inservible
                logger.warning("survey: rollback fallido tras el fallo de consulta")
                return None
            return SurveyService.open_form(db, SURVEY_CODE)

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

        `credit_status` en {'in_review','already_submitted','imported',
        'no_process','anonymous'}. En cualquier rama sin respuesta escrita
        (incluidas `already_submitted` e `imported`) `response` es `None`: el
        llamador no debe leerlo. `imported` = sin solicitud, pero su respuesta
        de Microsoft Forms ya se importó y espera su inscripción
        (`SurveyImportService.pending_import_for_user`): no se escribe nada.

        Tarea 3 (spec 5.3, D6): el proceso se resuelve ANTES de validar el
        formulario. Si el alumno tiene proceso acreditable y ESE proceso ya
        tiene una solicitud de liberacion (`SurveyReviewService.
        get_for_process`), se corta ahi mismo sin escribir nada -ni siquiera
        se gasta el trabajo de validar una respuesta que de todas formas no
        se va a guardar-: la encuesta queda CONGELADA tras el primer envio.

        Sin solicitud previa, el flujo de siempre -validar, `SurveyResponse`,
        filas de `SurveyAnswer`, borrar el borrador- y al final, en vez de
        `_credit` (retirado de este modulo), `SurveyReviewService.
        open_for_submission(..., commit=False)` abre la solicitud para GTV.

        UN SOLO `commit`, al final (seccion 4.4 paso 7). Dos envios
        simultaneos del mismo proceso pueden pasar los dos la comprobacion de
        arriba (la carrera real) y manifestarse de DOS formas distintas segun
        en que momento exacto commitea el ganador, y las dos se resuelven
        igual: `rollback` de TODO lo de este envio (la respuesta recien
        escrita incluida -segun el paso 7, o se guarda junto con la
        solicitud o no se guarda nada-) y `already_submitted`, nunca un 500.

          1. El ganador ya commiteo ANTES de que el perdedor llegue a
             `open_for_submission`: esa llamada hace su PROPIA comprobacion
             de "ya existe" (defensa en profundidad, `survey_review_
             service.py`) y levanta `ValueError` -nunca llega a intentar el
             `INSERT`-.
          2. El ganador commitea justo ENTRE la comprobacion de `open_for_
             submission` y su propio `INSERT`: el `UNIQUE(process_id)` de
             `titulatec_survey_reviews` revienta con `IntegrityError` -
             inmediata en Postgres (no es DEFERRABLE), asi que puede saltar
             en el `flush()` de `open_for_submission` y no solo en el
             `db.commit()` de aqui abajo-.

        Por eso el `except` de mas abajo atrapa las dos: nada mas en este
        bloque puede levantar ninguna de las dos por su cuenta.
        """
        from sqlalchemy.exc import IntegrityError

        from itcj2.apps.titulatec.models import SurveyAnswer, SurveyDraft, SurveyResponse
        from itcj2.apps.titulatec.services.process_service import ProcessService
        from itcj2.apps.titulatec.services.survey_review_service import SurveyReviewService
        from itcj2.apps.titulatec.utils.survey_validator import validate_answers

        process = None
        control_number = None
        if user_id is not None:
            from itcj2.core.models import User
            # Mismo selector que renderiza el checklist del alumno (seccion 5.3):
            # si los dos lados no llaman a este helper, la solicitud aterriza
            # en un proceso distinto del que el alumno ve.
            process = ProcessService.creditable_process(db, user_id)
            if (process is not None
                    and SurveyReviewService.get_for_process(db, process.id) is not None):
                return None, {}, "already_submitted"
            # Decisión del usuario (revisión final del import de Forms): sin
            # solicitud, pero con su respuesta de Forms importada esperando
            # la inscripción -> la encuesta también está congelada.
            from itcj2.apps.titulatec.services.survey_import_service import (
                SurveyImportService,
            )
            if SurveyImportService.pending_import_for_user(db, user_id) is not None:
                return None, {}, "imported"
            user = db.get(User, user_id)
            control_number = getattr(user, "control_number", None)

        ok, errors, cleaned = validate_answers(form.schema or {}, submitted or {})
        if not ok:
            return None, errors, "anonymous"

        if _answers_size(cleaned) > MAX_ANSWERS_JSON_BYTES:
            # Se RECHAZA, no se trunca: una respuesta a medias es peor que un no.
            return None, {"__form__": "Tu respuesta es demasiado larga. "
                                      "Acortala e intentalo de nuevo."}, "anonymous"

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
                # text, textarea, select, radio y date (ISO `AAAA-MM-DD`).
                db.add(SurveyAnswer(response_id=response.id, field_key=key,
                                    field_type=field_type, value_text=str(value)))

        credit_status = "anonymous"
        try:
            if user_id is not None:
                db.query(SurveyDraft).filter_by(
                    form_id=form.id, user_id=user_id).delete(synchronize_session=False)
                if process is not None:
                    SurveyReviewService.open_for_submission(db, process, response,
                                                            commit=False)
                    credit_status = "in_review"
                else:
                    credit_status = "no_process"
            # Solo ids: NUNCA las respuestas del alumno. Va antes del único
            # commit; si el envío pierde la carrera, el rollback se la lleva.
            from itcj2.apps.titulatec.services.audit_service import AuditService
            AuditService.record(
                db, "survey.submitted",
                entity_type="survey_response", entity_id=response.id,
                process_id=(process.id if process is not None else None),
                actor_id=user_id,
                payload={"form_code": form.code, "form_version": form.version,
                         "credit_status": credit_status},
            )
            db.commit()
        except (IntegrityError, ValueError):
            db.rollback()
            return None, {}, "already_submitted"
        db.refresh(response)
        return response, {}, credit_status

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

        respuestas = (db.query(SurveyResponse)
                      .filter(SurveyResponse.form_id == form_id)
                      .order_by(SurveyResponse.id)
                      .all())
        # M5 (revisión final del import de Forms): las llaves `extra_*` que
        # trae una respuesta importada sin pregunta en el `schema` (R9, p. ej.
        # `extra_aspecto_no_trabajo`) también van al CSV, al final y en orden
        # alfabético; sin respuestas importadas no aparece ninguna columna.
        extras = sorted({str(k) for r in respuestas for k in (r.answers or {})
                         if str(k).startswith("extra_") and str(k) not in keys})

        # `importada` (spec 2026-10-05-titulatec-import-encuesta-xlsx §4.4):
        # «sí» para las respuestas cargadas del Excel de Forms
        # (`identity_source='import'`), «no» para las de la plataforma.
        headers = ["id", "enviada_en", "identidad", "importada", "numero_control",
                   "proceso_id", "convocatoria_id", "version"] + keys + extras

        rows: list[list[str]] = []
        for r in respuestas:
            answers = r.answers or {}
            crudas = [
                r.id,
                r.submitted_at.isoformat(sep=" ", timespec="seconds") if r.submitted_at else "",
                r.identity_source or "",
                "sí" if r.identity_source == "import" else "no",
                r.control_number or "",
                r.process_id or "",
                r.cohort_id or "",
                r.form_version,
            ] + [_cell(answers.get(k)) for k in keys + extras]
            # Escapado INCONDICIONAL y para TODA columna (seccion 8.2).
            rows.append([escape_formula(c) for c in crudas])

        return headers, rows
