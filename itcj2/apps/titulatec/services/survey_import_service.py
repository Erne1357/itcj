"""Importación de la encuesta de egresados desde el Excel de Microsoft Forms
(spec `2026-10-05-titulatec-import-encuesta-xlsx-design.md` §4.2/§4.3).

Tres pasos, cada uno su método:

* `read_xlsx(raw, sheet="Sheet1")` -- lee la hoja con `openpyxl`, liga cada
  columna a su `field_key` por el TEXTO normalizado del encabezado (tabla
  `_HEADER_MAP`, nunca por letra: R2) y aborta con `ValueError` ANTES de
  escribir nada si hay un encabezado desconocido, uno faltante o uno repetido.
  `paper_pending` sale del relleno de la celda A (`FFFFC000` o el color de
  tema accent4): la constancia en papel ya expedida que el egresado no ha
  recogido (D3).
* `normalize(field, raw)` -- valor de una celda contra el `schema` del
  formulario abierto `egresados`. NUNCA rechaza (D1): lo que no encaja se
  guarda con su texto original y `is_raw=True`.
* `import_rows(db, rows, *, source, dry_run)` -- deduplica por número de
  control (R3: gana la más reciente), salta las ya importadas (R6:
  `import_ref = "msforms:{Id}:{Completion time ISO}"`), guarda cada
  `SurveyResponse` (`identity_source='import'`) con sus `SurveyAnswer` y
  libera SIEMPRE por `PriorClearanceService.import_rows` (no reimplementa la
  clasificación): con proceso abierto -> `register_prior` ligado a la
  respuesta; sin proceso -> `PriorClearance` diferida con `response_id`/
  `paper_pending` (R7); ya liberada por una previa SIN respuesta (p. ej. del
  CSV) -> se le adjunta (`PriorClearanceService.attach_imported_response`).
  UN commit al final; `dry_run` no escribe nada.

Cuando una respuesta queda ligada a un proceso -aquí o después, en
`PriorClearanceService.apply_pending` al inscribirse- `link_response_to_process`
llena su `user_id`/`process_id`/`cohort_id`.

`survey_validator` NO se usa en este camino (D1): sin validación todo-o-nada,
solo las opciones/formatos del schema para normalizar.
"""
from __future__ import annotations

import io
import logging
import re
import unicodedata
from datetime import date, datetime
from typing import Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

DEFAULT_SHEET = "Sheet1"
ORANGE_RGB = "FFFFC000"
# Índice de tema de «accent4» en el tema de Office (0 lt1, 1 dk1, 2 lt2, 3 dk2,
# 4..9 accent1..accent6): el naranja de la paleta de Excel.
THEME_ACCENT4 = 7

# Llaves del resultado de `import_rows`, en el orden en que la CLI las imprime.
# `invalid` = fila NO guardada: sin «Completion time» legible no hay fecha de
# envío, ni de constancia, ni `import_ref` estable (fix round 1).
IMPORT_BUCKETS = ("released", "deferred", "already_released", "conflicts",
                  "saved_unreleased", "duplicates", "already_imported", "invalid")

# Bote de `PriorClearanceService.import_rows` -> bote de esta importación.
_PRIOR_TO_BUCKET = {
    "applied": "released",
    "deferred": "deferred",
    "already": "already_released",
    "conflicts": "conflicts",
    "expired": "saved_unreleased",
    "invalid": "saved_unreleased",
}

# Columnas de metadatos de Forms (A..E).
_META_ID = "__ms_id"
_META_COMPLETED = "__completed_at"
_META_IGNORED = "__ignored"

# Respuesta sin pregunta en el formulario (R9): 10.º renglón de «Aspecto que
# valora la empresa» (col. BK). Se guarda como texto.
EXTRA_FIELDS = {"extra_aspecto_no_trabajo": {"key": "extra_aspecto_no_trabajo",
                                             "type": "text"}}

_ASPECTO = "aspecto que valora la empresa u organismo para la contratacion de egresados."

# (encabezado NORMALIZADO, destino, exacto). `exacto=False` = prefijo
# suficiente (el texto de Forms trae instrucciones largas detrás). Si varios
# prefijos calzan, gana el más largo.
_HEADER_MAP: tuple[tuple[str, str, bool], ...] = (
    ("id", _META_ID, True),
    ("start time", _META_IGNORED, True),
    ("completion time", _META_COMPLETED, True),
    ("email", _META_IGNORED, True),
    ("name", _META_IGNORED, True),
    ("nombre (s) y apellidos completos", "nombre_completo", False),
    ("no. control", "no_control", False),
    ("fecha de nacimiento", "fecha_nacimiento", False),
    ("sexo", "sexo", False),
    ("estado civil", "estado_civil", False),
    ("correo personal", "correo_personal", False),
    ("numero telefonico", "telefono", False),
    ("carrera de egreso", "carrera_egreso", False),
    ("especialidad", "especialidad", False),
    ("periodo de ingreso", "periodo_ingreso", False),
    ("ano de ingreso", "anio_ingreso", False),
    ("periodo de egreso", "periodo_egreso", False),
    ("ano de egreso", "anio_egreso", False),
    ("promedio final", "promedio_final", False),
    ("en que ano realizo las residencias", "anio_residencias", False),
    ("le interesaria recibir correos", "recibir_correos", False),
    ("calidad de los docentes", "calidad_docentes", False),
    ("plan de estudios", "plan_estudios", False),
    ("oportunidad de participar en proyectos", "oportunidad_investigacion", False),
    ("enfasis que se le prestaba a la investigacion", "enfasis_investigacion", False),
    ("satisfaccion con las condiciones de estudio", "satisfaccion_infraestructura", False),
    ("experiencia obtenida a traves de la residencia", "experiencia_residencia", False),
    ("como acredito el requisito del segundo idioma", "acreditacion_idioma", False),
    ("domina algun idioma distinto", "domina_otro_idioma", False),
    ("que idioma", "que_idioma", False),
    ("actividad a la que se dedica", "actividad_actual", False),
    ("si se encuentra estudiando", "tipo_estudio", False),
    ("nombre de la institucion", "institucion_estudio", False),
    ("en caso de trabajar, tiempo transcurrido", "tiempo_primer_empleo", False),
    ("medios para obtener el empleo", "medio_obtencion_empleo", False),
    ("requisito de contratacion", "requisito_contratacion", False),
    ("idioma que mas utiliza en su trabajo", "idioma_uso_trabajo", False),
    ("que habilidad del idioma extranjero", "habilidad_idioma_trabajo", False),
    ("nivel jerarquico", "nivel_jerarquico", False),
    ("condicion de trabajo", "condicion_trabajo", False),
    ("las actividades que realiza en su trabajo", "relacion_actividad_carrera", False),
    ("funciones que realiza en la empresa", "funciones_empresa", False),
    ("si trabaja, escriba el nombre de la empresa", "nombre_empresa", False),
    ("la empresa u organismo donde labora", "tipo_organismo", False),
    ("la empresa donde labora pertenece al sector", "sector_empresa", False),
    ("nombre completo del encargado de recursos humanos", "nombre_encargado_rh", False),
    ("telefono de contacto del encargado", "telefono_encargado_rh", False),
    ("tamano de la empresa", "tamano_empresa", False),
    ("antiguedad en el empleo", "antiguedad_empleo", False),
    ("cuenta con alguna empresa propia", "empresa_propia", False),
    ("nombre de la empresa:", "nombre_empresa_propia", False),
    ("como califica su formacion academica", "calif_formacion_academica", False),
    ("utilidad de las residencias", "utilidad_residencias", False),
    (_ASPECTO + "area o campo de estudio", "scale_area_estudio", False),
    (_ASPECTO + "titulado", "scale_titulado", False),
    (_ASPECTO + "experiencia laboral", "scale_experiencia_laboral", False),
    (_ASPECTO + "competencia laboral", "scale_competencia_laboral", False),
    (_ASPECTO + "institucion de egreso", "scale_institucion_egreso", False),
    (_ASPECTO + "dominio de otro idioma", "scale_dominio_idioma", False),
    (_ASPECTO + "recomendacion", "scale_recomendacion", False),
    (_ASPECTO + "personalidad", "scale_personalidad_actitud", False),
    (_ASPECTO + "capacidad de liderazgo", "scale_capacidad_liderazgo", False),
    (_ASPECTO + "no trabajo", "extra_aspecto_no_trabajo", False),
    ("pertenece a organizaciones sociales", "pertenece_org_social", False),
    ("nombre de la organizacion social", "nombre_org_social", False),
    ("pertenece a alguna asociacion de egresados", "pertenece_asoc_egresados", False),
    ("nombre de la asociacion de egresados", "nombre_asoc_egresados", False),
    ("le interesaria pertenecer a la asociacion", "interes_asoc_egresados", False),
    ("comentario, queja y/o sugerencia", "comentario_sugerencia", False),
)

_FECHA_FORMATOS = ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S",
                   "%d/%m/%Y", "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M")
_SI = {"si", "s", "true", "1"}
_NO = {"no", "n", "false", "0"}

# Respuestas «centinela» que el formulario de Forms obligaba a escribir o
# escoger aunque la pregunta no aplicara («No trabajo», «No estudio»,
# «Desempleado (a)», «Ninguno», «N0»...), ya en forma `_option_key`. En un
# campo OCULTO por `visible_when` equivalen a «sin respuesta» (la plataforma
# descarta los ocultos); un valor REAL en un campo oculto se guarda raw (D1),
# y en uno visible, un radio centinela también se guarda raw.
_SENTINELS = frozenset({
    "no trabajo", "no estudio", "desempleado a", "desempleado", "desempleada",
    "ninguno", "ninguna", "n0", "no", "na", "n a", "no aplica",
})

# Sinónimos POR PALABRA en la forma comparable de una opción: Forms y el
# formulario de la plataforma pueden conjugar distinto «Aprobó»/«Aprobé».
_OPTION_SYNONYMS = {"aprobe": "aprobo"}


def normalize_text(value) -> str:
    """Encabezado/opción -> forma comparable: `\\xa0` a espacio, sin acentos,
    sin `¿`/`¡`, minúsculas, espacios colapsados."""
    texto = str(value).replace("\xa0", " ")
    texto = "".join(c for c in unicodedata.normalize("NFKD", texto)
                    if not unicodedata.combining(c))
    texto = texto.replace("¿", "").replace("¡", "").lower()
    return re.sub(r"\s+", " ", texto).strip()


def _header_target(header) -> Optional[str]:
    h = normalize_text(header or "")
    mejor, largo = None, -1
    for patron, destino, exacto in _HEADER_MAP:
        if (h == patron) if exacto else h.startswith(patron):
            if len(patron) > largo:
                mejor, largo = destino, len(patron)
    return mejor


def _as_text(raw) -> str:
    """Celda -> texto: enteros sin `.0`, `\\xa0` a espacio, recortado."""
    if isinstance(raw, bool):
        return "Si" if raw else "No"
    if isinstance(raw, float) and raw.is_integer():
        return str(int(raw))
    if isinstance(raw, datetime):
        return raw.isoformat(sep=" ")
    return str(raw).replace("\xa0", " ").strip()


def _option_values(field: dict) -> list[tuple[str, str]]:
    """`[(valor canónico, etiqueta)]` de un radio/select/multiselect."""
    salida = []
    for opcion in field.get("options") or []:
        if isinstance(opcion, dict):
            valor = opcion.get("value")
            salida.append((str(valor), str(opcion.get("label") or valor)))
        else:
            salida.append((str(opcion), str(opcion)))
    return salida


def _option_key(texto) -> str:
    """Forma comparable de una OPCIÓN: además de `normalize_text`, la
    puntuación cuenta como espacio («AGOSTO-DICIEMBRE» == «AGOSTO DICIEMBRE»,
    «Supervisor/ Jefe» == «Supervisor / Jefe»)."""
    palabras = re.sub(r"[^a-z0-9]+", " ", normalize_text(texto)).split()
    return " ".join(_OPTION_SYNONYMS.get(p, p) for p in palabras)


def _match_option(field: dict, texto: str) -> Optional[str]:
    buscado = _option_key(texto)
    for valor, etiqueta in _option_values(field):
        if buscado in (_option_key(valor), _option_key(etiqueta)):
            return valor
    return None


def _parse_date_text(texto: str) -> Optional[date]:
    for formato in _FECHA_FORMATOS:
        try:
            return datetime.strptime(texto, formato).date()
        except ValueError:
            continue
    return None


def _is_orange(cell) -> bool:
    fill = getattr(cell, "fill", None)
    if fill is None or not fill.fill_type:
        return False
    for color in (fill.fgColor, fill.start_color):
        if color is None:
            continue
        if color.type == "rgb" and str(color.rgb).upper() == ORANGE_RGB:
            return True
        if color.type == "theme" and color.theme == THEME_ACCENT4:
            return True
    return False


class SurveyImportService:
    """Excel de Microsoft Forms -> respuestas importadas + liberación previa."""

    # ------------------------------------------------------------------
    # Lectura
    # ------------------------------------------------------------------
    @staticmethod
    def read_xlsx(raw: bytes, *, sheet: str = DEFAULT_SHEET) -> list[dict]:
        """Filas de la hoja `sheet` como dicts `{ms_id, paper_pending,
        completed_at, full_name, control_raw, answers_raw}` (`answers_raw`
        por `field_key`, incluidos `nombre_completo` y `no_control`).

        `ValueError` -sin leer ninguna fila- si la hoja no existe (el
        mensaje lista las que hay), si un encabezado no está en la tabla de
        mapeo, si falta uno esperado o si dos columnas van a la misma
        pregunta. Las filas totalmente vacías se ignoran; una fila con datos
        pero sin `Id` también es error (sin `Id` no hay idempotencia, R6)."""
        import openpyxl

        wb = openpyxl.load_workbook(io.BytesIO(raw), data_only=True)
        if sheet not in wb.sheetnames:
            raise ValueError(
                f"La hoja {sheet!r} no existe en el archivo. Hojas disponibles: "
                + ", ".join(repr(n) for n in wb.sheetnames) + ".")
        ws = wb[sheet]

        filas = ws.iter_rows(min_row=1)
        try:
            encabezados = next(filas)
        except StopIteration:
            raise ValueError(f"La hoja {sheet!r} está vacía.") from None

        columnas: dict[int, str] = {}
        desconocidos, repetidos = [], []
        vistos: dict[str, int] = {}
        for idx, celda in enumerate(encabezados):
            if celda.value is None or not str(celda.value).strip():
                continue
            destino = _header_target(celda.value)
            if destino is None:
                desconocidos.append(str(celda.value).strip())
                continue
            if destino != _META_IGNORED and destino in vistos:
                repetidos.append(str(celda.value).strip())
                continue
            vistos[destino] = idx
            columnas[idx] = destino
        esperados = {d for _, d, _ in _HEADER_MAP if d != _META_IGNORED}
        faltantes = sorted(esperados - set(vistos))
        problemas = []
        if desconocidos:
            problemas.append("encabezado(s) desconocido(s): "
                             + "; ".join(repr(h) for h in desconocidos))
        if repetidos:
            problemas.append("encabezado(s) repetido(s): "
                             + "; ".join(repr(h) for h in repetidos))
        if faltantes:
            problemas.append("falta(n) la(s) columna(s) de: " + ", ".join(faltantes))
        if problemas:
            raise ValueError("No se importó nada. " + " | ".join(problemas))

        col_id = vistos[_META_ID]
        salida: list[dict] = []
        for numero, fila in enumerate(filas, start=2):
            valores = {columnas[i]: c.value for i, c in enumerate(fila) if i in columnas}
            if all(v is None or (isinstance(v, str) and not v.strip())
                   for v in valores.values()):
                continue
            ms_id = valores.get(_META_ID)
            if ms_id is None or (isinstance(ms_id, str) and not ms_id.strip()):
                raise ValueError(f"La fila {numero} trae datos pero no tiene Id.")
            if isinstance(ms_id, float) and ms_id.is_integer():
                ms_id = int(ms_id)
            completado = valores.get(_META_COMPLETED)
            completado_crudo = completado
            if isinstance(completado, str):
                texto = completado.strip()
                for formato in _FECHA_FORMATOS:
                    try:
                        completado = datetime.strptime(texto, formato)
                        break
                    except ValueError:
                        continue
                else:
                    completado = None
            elif isinstance(completado, date) and not isinstance(completado, datetime):
                completado = datetime.combine(completado, datetime.min.time())
            elif not isinstance(completado, datetime):
                completado = None
            respuestas = {k: v for k, v in valores.items() if not k.startswith("__")}
            # El naranja se lee en la columna del Id hallada POR ENCABEZADO
            # (R2), no en una letra fija.
            celda_id = fila[col_id] if col_id < len(fila) else None
            salida.append({
                "ms_id": ms_id,
                "paper_pending": _is_orange(celda_id),
                "completed_at": completado,
                "completed_raw": (None if completado is not None or completado_crudo is None
                                  else str(completado_crudo)),
                "full_name": respuestas.get("nombre_completo"),
                "control_raw": respuestas.get("no_control"),
                "answers_raw": respuestas,
            })
        return salida

    # ------------------------------------------------------------------
    # Normalización
    # ------------------------------------------------------------------
    @staticmethod
    def normalize(field: dict, raw) -> tuple[object, bool]:
        """`(valor, is_raw)` de una celda contra su campo del schema. `(None,
        False)` = vacío (no se guarda). Nunca lanza (D1): un schema mal formado
        (p. ej. `scale.min` no numérico) deja el valor raw en vez de reventar."""
        try:
            return SurveyImportService._normalize(field or {}, raw)
        except Exception:
            logger.warning("normalize: schema inesperado en %r; valor guardado raw",
                           (field or {}).get("key") if isinstance(field, dict) else None,
                           exc_info=True)
            return (None, False) if raw is None else (_as_text(raw), True)

    @staticmethod
    def _normalize(field: dict, raw) -> tuple[object, bool]:
        from itcj2.apps.titulatec.services.import_service import CONTROL_NUMBER_RE

        if raw is None:
            return None, False
        if isinstance(raw, str) and not raw.replace("\xa0", " ").strip():
            return None, False
        tipo = field.get("type") or "text"
        key = field.get("key")
        validacion = field.get("validation") or {}

        if key == "no_control":
            texto = _as_text(raw).upper().replace(" ", "")
            return texto, not bool(CONTROL_NUMBER_RE.fullmatch(texto))

        if tipo in ("radio", "select"):
            texto = _as_text(raw)
            valor = _match_option(field, texto)
            return (valor, False) if valor is not None else (texto, True)

        if tipo == "multiselect":
            texto = _as_text(raw)
            partes = [p.strip() for p in texto.split(";") if p.strip()]
            valores = [_match_option(field, p) for p in partes]
            if partes and all(v is not None for v in valores):
                return valores, False
            return texto, True

        if tipo in ("yesno", "checkbox"):
            if isinstance(raw, bool):
                return raw, False
            texto = normalize_text(_as_text(raw))
            if texto in _SI:
                return True, False
            if texto in _NO:
                return False, False
            return _as_text(raw), True

        if tipo == "date":
            if isinstance(raw, datetime):
                return raw.date().isoformat(), False
            if isinstance(raw, date):
                return raw.isoformat(), False
            texto = _as_text(raw)
            fecha = _parse_date_text(texto)
            return (fecha.isoformat(), False) if fecha else (texto, True)

        if tipo == "scale":
            escala = field.get("scale") or {}
            minimo, maximo = int(escala.get("min", 1)), int(escala.get("max", 5))
            # Regla general: el ENTERO dentro del texto, si es uno solo y cae
            # en min..max («Mucho 5» -> 5, «Poco 1» -> 1, «3» -> 3).
            numero = None
            if isinstance(raw, bool):
                numero = None
            elif isinstance(raw, int):
                numero = raw
            elif isinstance(raw, float) and raw.is_integer():
                numero = int(raw)
            elif isinstance(raw, str):
                enteros = re.findall(r"\d+", raw)
                if len(enteros) == 1:
                    numero = int(enteros[0])
            if numero is not None and minimo <= numero <= maximo:
                return numero, False
            return _as_text(raw), True

        # text / textarea (y cualquier tipo desconocido).
        formato = validacion.get("format")
        texto = _as_text(raw)
        if formato == "year":
            if not re.fullmatch(r"\d{4}", texto):
                return texto, True
        elif formato == "decimal":
            candidato = texto.replace(",", ".")
            try:
                numero = float(candidato)
            except ValueError:
                return texto, True
            texto = str(int(numero)) if numero.is_integer() else candidato
        tope = validacion.get("maxLength")
        if tope and len(texto) > int(tope):
            return texto, True
        return texto, False

    @staticmethod
    def normalize_answers(campos: dict, answers_raw: dict,
                          stats: Optional[dict] = None) -> dict[str, tuple[object, bool]]:
        """Fila completa -> `{key: (valor, is_raw)}` sin los vacíos, aplicando
        `visible_when` como la plataforma (`survey_validator.is_visible`, el
        MISMO evaluador; contra los valores YA normalizados de la fila):

        * campo OCULTO cuyo texto original es un centinela (`_SENTINELS`:
          «No trabajo», «No estudio», «Desempleado (a)», «Ninguno», «N0»/«NO»)
          -> no se guarda: es el «no aplica» que Forms obligaba a escribir;
        * campo OCULTO con un valor REAL (no centinela), de cualquier tipo ->
          se conserva con su texto ORIGINAL y `is_raw=True` (ruling de la
          revisión final, D1 «ninguna respuesta se pierde»: la plataforma
          descarta los ocultos, pero el egresado sí contestó algo);
        * si alguna llave de la condición quedó raw, la visibilidad no se
          puede evaluar y el campo se trata como visible (no se pierde nada).

        `stats` (opcional, se acumula): `cells` (celdas guardadas), `raw`
        (de ellas, `is_raw`) y `hidden_kept` (ocultas con valor real,
        guardadas como originales).
        """
        from itcj2.apps.titulatec.utils.survey_validator import is_visible

        norm: dict[str, tuple[object, bool]] = {}
        originales: dict[str, object] = {}
        for key, crudo in (answers_raw or {}).items():
            campo = campos.get(key) or {"key": key, "type": "text"}
            valor, es_raw = SurveyImportService.normalize(campo, crudo)
            if valor is not None:
                norm[key] = (valor, es_raw)
                originales[key] = crudo

        canonicos = {k: v for k, (v, r) in norm.items() if not r}
        crudos = {k for k, (_, r) in norm.items() if r}
        ocultas_reales = 0
        for key in list(norm):
            campo = campos.get(key) or {}
            condicion = campo.get("visible_when")
            if not isinstance(condicion, dict) or not condicion:
                continue
            if any(fuente in crudos for fuente in condicion):
                continue
            try:
                visible = is_visible(campo, canonicos)
            except Exception:
                visible = True
            if visible:
                continue
            original = _as_text(originales[key])
            if _option_key(original) in _SENTINELS:
                del norm[key]
                continue
            norm[key] = (original, True)
            ocultas_reales += 1

        if stats is not None:
            stats["cells"] = stats.get("cells", 0) + len(norm)
            stats["raw"] = stats.get("raw", 0) + sum(1 for _, r in norm.values() if r)
            stats["hidden_kept"] = stats.get("hidden_kept", 0) + ocultas_reales
        return norm

    # ------------------------------------------------------------------
    # Encuesta pública: ¿ya contestó en Forms?
    # ------------------------------------------------------------------
    @staticmethod
    def pending_import_for_user(db: Session, user_id: Optional[int]) -> Optional[dict]:
        """Respuesta de Forms IMPORTADA que espera la inscripción del egresado
        (decisión del usuario tras la revisión final): `{"response_id",
        "submitted_at"}` o `None`.

        Solo cuenta si su liberación quedó DIFERIDA y todavía puede aplicarse:
        `PriorClearance(kind='survey')` del control del usuario, sin aplicar
        (`applied_process_id IS NULL`), vigente (`issued_on >= hoy -
        PRIOR_VALIDITY_DAYS`) y ligada a una respuesta `identity_source=
        'import'` de un formulario `egresados` (cualquier versión). Así el
        aviso «se liberará cuando completes tu inscripción» siempre es cierto:
        una importada que no liberará nada (vencida, sin control válido) no
        congela la encuesta y el egresado puede contestarla aquí.

        La consultan `pages/public.py::_solicitud_existente` (tarjeta de
        estatus en lugar del formulario) y `SurveyService.submit` (rechazo del
        envío, del lado del servidor). Solo lectura."""
        from datetime import timedelta

        from itcj2.apps.titulatec.models import PriorClearance, SurveyForm, SurveyResponse
        from itcj2.apps.titulatec.services.library_clearance_service import (
            PRIOR_VALIDITY_DAYS,
        )
        from itcj2.apps.titulatec.services.survey_service import SURVEY_CODE
        from itcj2.core.models.user import User
        from itcj2.core.utils.timezone import db_now

        if user_id is None:
            return None
        user = db.get(User, int(user_id))
        control = ((getattr(user, "control_number", None) or "").strip().upper()
                   if user is not None else "")
        if not control:
            return None
        limite = db_now().date() - timedelta(days=PRIOR_VALIDITY_DAYS)
        fila = (db.query(SurveyResponse.id, SurveyResponse.submitted_at)
                .join(PriorClearance, PriorClearance.response_id == SurveyResponse.id)
                .join(SurveyForm, SurveyForm.id == SurveyResponse.form_id)
                .filter(PriorClearance.kind == "survey",
                        PriorClearance.control_number == control,
                        PriorClearance.applied_process_id.is_(None),
                        PriorClearance.issued_on >= limite,
                        SurveyResponse.identity_source == "import",
                        SurveyForm.code == SURVEY_CODE)
                .first())
        if fila is None:
            return None
        return {"response_id": fila[0], "submitted_at": fila[1]}

    # ------------------------------------------------------------------
    # Liga respuesta <-> proceso
    # ------------------------------------------------------------------
    @staticmethod
    def link_response_to_process(db: Session, response_id: Optional[int], process) -> None:
        """Llena `user_id`/`process_id`/`cohort_id` de una respuesta IMPORTADA
        cuando queda ligada a la liberación de `process` (aquí, o después en
        `PriorClearanceService.apply_pending`). Solo toca filas
        `identity_source='import'`; sin commit."""
        from itcj2.apps.titulatec.models import SurveyResponse

        if response_id is None or process is None:
            return
        response = db.get(SurveyResponse, response_id)
        if response is None or response.identity_source != "import":
            return
        response.user_id = process.student_id
        response.process_id = process.id
        response.cohort_id = process.cohort_id
        db.flush()

    # ------------------------------------------------------------------
    # Escritura + liberación
    # ------------------------------------------------------------------
    @staticmethod
    def import_rows(db: Session, rows: list[dict], *, source: str,
                    dry_run: bool = False,
                    stats: Optional[dict] = None) -> dict[str, list[dict]]:
        """Importa las filas de `read_xlsx`. Devuelve los 7 botes de
        `IMPORT_BUCKETS`; cada item `{"control_number", "reason", "ms_id"}`.

        `ValueError` si no hay formulario `egresados` abierto. `dry_run`
        clasifica todo (incluida la liberación, en `dry_run` también del
        lado de `PriorClearanceService`) sin escribir nada; si no, UN commit
        al final.

        `stats` (opcional): se llena con `cells`/`raw`/`hidden_kept` de las
        respuestas que se guardan (o se guardarían, en `dry_run`); ver
        `normalize_answers`."""
        from itcj2.apps.titulatec.models import SurveyResponse
        from itcj2.apps.titulatec.services.import_service import CONTROL_NUMBER_RE
        from itcj2.apps.titulatec.services.prior_clearance_service import (
            PriorClearanceService,
        )
        from itcj2.apps.titulatec.models import SurveyForm
        from itcj2.apps.titulatec.services.survey_service import SURVEY_CODE, SurveyService

        form = SurveyService.open_form(db, SURVEY_CODE)
        if form is None:
            raise ValueError(
                f"No hay un formulario {SURVEY_CODE!r} abierto: no hay a qué ligar "
                "las respuestas.")
        campos = {f.get("key"): f for f in ((form.schema or {}).get("fields") or [])
                  if isinstance(f, dict) and f.get("key")}
        campos.update({k: v for k, v in EXTRA_FIELDS.items() if k not in campos})

        out: dict[str, list[dict]] = {bote: [] for bote in IMPORT_BUCKETS}

        def _add(bote, control, motivo, ms_id):
            out[bote].append({"control_number": control or "(vacío)", "reason": motivo,
                              "ms_id": ms_id})

        # 1. Normalizar el control de cada fila.
        preparadas = []
        for row in rows:
            control, control_raw = SurveyImportService.normalize(
                {"key": "no_control", "type": "text"}, row.get("control_raw"))
            valido = control is not None and not control_raw
            preparadas.append({**row, "control": control, "control_ok": valido})

        # 2. R3: duplicados por control -> gana la más reciente (empate: la
        #    última del archivo). Las filas sin control no se agrupan.
        minimo = datetime.min
        ganadoras: dict[str, dict] = {}
        for row in preparadas:
            if not row["control"]:
                continue
            actual = ganadoras.get(row["control"])
            if actual is None or (row["completed_at"] or minimo) >= (
                    actual["completed_at"] or minimo):
                ganadoras[row["control"]] = row
        conservadas = []
        for row in preparadas:
            ganadora = ganadoras.get(row["control"]) if row["control"] else row
            if ganadora is not row:
                _add("duplicates", row["control"],
                     f"repetido: se importa la respuesta más reciente (Id {ganadora['ms_id']})",
                     row["ms_id"])
                continue
            conservadas.append(row)

        # 3. Por fila: idempotencia (R6), escritura de la respuesta y armado
        #    de la fila de liberación.
        liberar: list[dict] = []
        por_control: dict[str, dict] = {}
        guardadas: list[tuple[dict, Optional[int]]] = []
        for row in conservadas:
            completado = row["completed_at"]
            if completado is None:
                _add("invalid", row["control"],
                     "«Completion time» vacío o ilegible: no se guarda (sin fecha de "
                     "envío no hay constancia ni referencia estable)", row["ms_id"])
                continue
            import_ref = f"msforms:{row['ms_id']}:{completado.isoformat()}"[:120]
            # Ruling: idempotencia por CÓDIGO de formulario, no por versión --
            # abrir una v2 de `egresados` no debe reimportar el archivo.
            existe = (db.query(SurveyResponse.id)
                      .join(SurveyForm, SurveyForm.id == SurveyResponse.form_id)
                      .filter(SurveyForm.code == SURVEY_CODE,
                              SurveyResponse.import_ref == import_ref)
                      .first())
            if existe is not None:
                _add("already_imported", row["control"],
                     "esta respuesta ya se había importado", row["ms_id"])
                continue

            normalizadas = SurveyImportService.normalize_answers(
                campos, row.get("answers_raw") or {}, stats=stats)
            response_id = None
            if not dry_run:
                response_id = SurveyImportService._write_response(
                    db, form, campos, row, import_ref=import_ref,
                    normalizadas=normalizadas)
            guardadas.append((row, response_id))

            if row["control_ok"]:
                liberar.append({"control_number": row["control"],
                                "issued_on": completado.date(),
                                "response_id": response_id,
                                "paper_pending": row["paper_pending"] is True})
                por_control[row["control"]] = {"row": row, "response_id": response_id}
            else:
                _add("saved_unreleased", row["control"],
                     "número de control inválido o vacío; se guarda sin liberar",
                     row["ms_id"])

        # 4. Liberación: SIEMPRE por la maquinaria de constancias previas.
        if liberar:
            resultado = PriorClearanceService.import_rows(
                db, kind="survey", rows=liberar, source=source[:120], dry_run=dry_run,
                commit=False)
            for bote_prev, items in resultado.items():
                bote = _PRIOR_TO_BUCKET[bote_prev]
                for item in items:
                    info = por_control.get(item["control_number"], {})
                    row = info.get("row") or {}
                    motivo = item["reason"]
                    if bote_prev == "already" and not dry_run:
                        proceso = PriorClearanceService.attach_imported_response(
                            db, control_number=item["control_number"],
                            response_id=info.get("response_id"),
                            paper_pending=row.get("paper_pending") is True)
                        if proceso is not None:
                            SurveyImportService.link_response_to_process(
                                db, info.get("response_id"), proceso)
                            motivo += "; se le ligó esta respuesta"
                    _add(bote, item["control_number"], motivo, row.get("ms_id"))

        # 5. Las liberadas YA (register_prior) quedan ligadas a su proceso.
        if not dry_run:
            SurveyImportService._link_released(db, [rid for _, rid in guardadas if rid])
            db.commit()
        logger.info(
            "import-survey-xlsx %s (%s): %s", source, "dry-run" if dry_run else "real",
            {bote: len(items) for bote, items in out.items()})
        return out

    @staticmethod
    def _write_response(db: Session, form, campos: dict, row: dict, *,
                        import_ref: str, normalizadas: Optional[dict] = None) -> int:
        """`SurveyResponse` importada + sus `SurveyAnswer`. Devuelve el id.

        Ruling (fix round 1): `user_id` siempre que exista el User del control
        y `cohort_id` si ese User tiene un proceso (el más reciente), aunque la
        respuesta no quede ligada a una liberación; `process_id` SOLO al
        ligarse (`link_response_to_process`)."""
        from itcj2.apps.titulatec.models import (
            SurveyAnswer, SurveyResponse, TitulationProcess,
        )
        from itcj2.core.models.user import User

        control = row["control"] if row["control_ok"] else None
        user = (db.query(User).filter_by(control_number=control).first()
                if control else None)
        proceso = (db.query(TitulationProcess)
                   .filter(TitulationProcess.student_id == user.id)
                   .order_by(TitulationProcess.id.desc()).first()
                   if user is not None else None)

        if normalizadas is None:
            normalizadas = SurveyImportService.normalize_answers(
                campos, row.get("answers_raw") or {})

        response = SurveyResponse(
            form_id=form.id, form_version=form.version,
            user_id=(user.id if user is not None else None),
            cohort_id=(proceso.cohort_id if proceso is not None else None),
            identity_source="import", control_number=control,
            answers={k: v for k, (v, _) in normalizadas.items()},
            import_ref=import_ref,
        )
        if row.get("completed_at") is not None:
            response.submitted_at = row["completed_at"]
        db.add(response)
        db.flush()

        for key, (valor, es_raw) in normalizadas.items():
            tipo = (campos.get(key) or {}).get("type") or "text"
            base = {"response_id": response.id, "field_key": key, "field_type": tipo,
                    "is_raw": es_raw}
            if es_raw:
                db.add(SurveyAnswer(**base, value_text=str(valor)))
            elif tipo == "multiselect":
                for opcion in valor:
                    db.add(SurveyAnswer(**base, value_text=str(opcion), value_bool=True))
            elif tipo == "scale":
                db.add(SurveyAnswer(**base, value_num=valor))
            elif tipo in ("yesno", "checkbox"):
                db.add(SurveyAnswer(**base, value_bool=bool(valor)))
            else:
                db.add(SurveyAnswer(**base, value_text=str(valor)))
        db.flush()
        return response.id

    @staticmethod
    def _link_released(db: Session, response_ids: list[int]) -> None:
        """Las respuestas que `register_prior` ligó a una solicitud (lectura
        de `SurveyReview.response_id`, nunca de su estado) -> su proceso."""
        from itcj2.apps.titulatec.models import SurveyReview, TitulationProcess

        if not response_ids:
            return
        pares = (db.query(SurveyReview.response_id, SurveyReview.process_id)
                 .filter(SurveyReview.response_id.in_(response_ids)).all())
        for response_id, process_id in pares:
            proceso = db.get(TitulationProcess, process_id)
            SurveyImportService.link_response_to_process(db, response_id, proceso)
