"""Reporte Excel de la encuesta de egresados: parametros, filtrado y libro `.xlsx`.

Spec `docs/superpowers/specs/2026-10-28-titulatec-reporte-encuestas-design.md`.
SOLO LECTURA: nada de este modulo escribe ni hace commit, y las lecturas no se
auditan (CLAUDE.md de la app, seccion 20). El CSV crudo de
`SurveyService.export_rows` NO pasa por aqui y no cambia.

Piezas:

    parse_params / to_query  query string <-> `ReportParams` (ida y vuelta exacta)
    catalog / semesters      lo que la UI necesita para pintar el constructor
    collect                  filas ya filtradas, deduplicadas y ordenadas
    preview                  las primeras filas como texto para la vista previa
    build_xlsx / filename    el libro

Proteccion contra inyeccion de formulas (seccion 8.2 del diseno de la encuesta):
el CSV prefija con `'` (`escape_formula`) porque un CSV no tiene tipos de celda.
Un `.xlsx` si: aqui TODO texto se escribe con `write_string`, que guarda la
celda como cadena (`t="s"`) y Excel nunca la evalua, aunque empiece con `=`,
`+`, `-` o `@`. Es la misma garantia que `escape_formula` sin el `'` visible; ademas
el libro se abre con `strings_to_formulas/urls/numbers = False`, de modo que ni
siquiera un `write()` descuidado futuro convertiria texto en formula. Los
numeros y fechas se escriben con `write_number`/`write_datetime` y SOLO para
columnas tipadas (la respuesta de un anonimo nunca llega ahi como texto).

Las respuestas importadas del Excel de Forms (`identity_source='import'`) traen
llaves `extra_*` que el `schema` no pregunta: salen como columnas opcionales
en la seccion «Otros datos importados».
"""
from __future__ import annotations

import io
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from urllib.parse import urlencode

from sqlalchemy.orm import Session

logger = logging.getLogger("itcj2.apps.titulatec.services.survey_report")

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------
CHOICE_TYPES = ("radio", "select", "multiselect", "scale")
HOJAS = ("respuestas", "resumen", "distribucion", "cruce", "parametros")
HOJA_NOMBRES = {
    "respuestas": "Respuestas", "resumen": "Resumen", "distribucion": "Distribución",
    "cruce": "Cruce", "parametros": "Parámetros",
}
ENCABEZADOS = ("corto", "pregunta", "clave")
VACIO = "__vacio__"
SIN_RESPUESTA = "Sin respuesta"
MAX_ORDEN = 3
MAX_GRAFICAS = 60
SHORT_MAX = 60
_CELDA_MAX = 32000          # xlsx admite 32767 caracteres por celda

META = (                    # (llave, etiqueta, tipo)
    ("_id", "Folio de respuesta", "number"),
    ("_fecha", "Fecha de respuesta", "datetime"),
    ("_origen", "Origen", "text"),
    ("_control", "No. de control", "text"),
    ("_nombre", "Nombre", "text"),
    ("_correo_cuenta", "Correo de la cuenta", "text"),
    ("_convocatoria", "Convocatoria", "text"),
    ("_folio_proceso", "Folio del proceso", "text"),
    ("_version", "Versión del formulario", "number"),
)
META_KEYS = tuple(k for k, _, _ in META)
_META_TIPO = {k: t for k, _, t in META}
_META_ETIQUETA = {k: e for k, e, _ in META}

# Rotulos cortos curados del formulario `egresados`. `scale_*` y lo no listado
# usan `_corto` (corte heuristico en el primer «(» o «:»).
SHORT_LABELS = {
    "nombre_completo": "Nombre completo",
    "no_control": "No. de control (declarado)",
    "fecha_nacimiento": "Fecha de nacimiento",
    "correo_personal": "Correo personal",
    "telefono": "Teléfono",
    "carrera_egreso": "Carrera",
    "especialidad": "Especialidad",
    "periodo_ingreso": "Periodo de ingreso",
    "anio_ingreso": "Año de ingreso",
    "periodo_egreso": "Periodo de egreso",
    "anio_egreso": "Año de egreso",
    "promedio_final": "Promedio final",
    "anio_residencias": "Año de residencias",
    "recibir_correos": "Acepta recibir correos",
    "calidad_docentes": "Calidad de los docentes",
    "plan_estudios": "Plan de estudios",
    "oportunidad_investigacion": "Oportunidad de investigación",
    "enfasis_investigacion": "Énfasis en investigación",
    "satisfaccion_infraestructura": "Satisfacción con infraestructura",
    "experiencia_residencia": "Experiencia en residencia",
    "acreditacion_idioma": "Acreditación del segundo idioma",
    "domina_otro_idioma": "Domina otro idioma",
    "que_idioma": "Idioma",
    "actividad_actual": "Actividad actual",
    "tipo_estudio": "Tipo de estudio actual",
    "institucion_estudio": "Institución donde estudia",
    "tiempo_primer_empleo": "Tiempo al primer empleo",
    "medio_obtencion_empleo": "Medio para obtener empleo",
    "requisito_contratacion": "Requisito de contratación",
    "nivel_jerarquico": "Nivel jerárquico",
    "condicion_trabajo": "Condición de trabajo",
    "relacion_actividad_carrera": "Relación trabajo-carrera",
    "funciones_empresa": "Funciones en la empresa",
    "nombre_empresa": "Empresa donde trabaja",
    "tipo_organismo": "Tipo de organismo",
    "sector_empresa": "Sector de la empresa",
    "nombre_encargado_rh": "Encargado de RH",
    "telefono_encargado_rh": "Teléfono de RH",
    "tamano_empresa": "Tamaño de la empresa",
    "antiguedad_empleo": "Antigüedad en el empleo",
    "empresa_propia": "Tiene empresa propia",
    "nombre_empresa_propia": "Empresa propia",
    "calif_formacion_academica": "Calificación de su formación",
    "utilidad_residencias": "Utilidad de residencias",
    "pertenece_org_social": "Pertenece a org. social",
    "nombre_org_social": "Organización social",
    "pertenece_asoc_egresados": "Pertenece a asoc. de egresados",
    "nombre_asoc_egresados": "Asociación de egresados",
    "interes_asoc_egresados": "Interés en asoc. de egresados",
    "comentario_sugerencia": "Comentarios y sugerencias",
}

# Plantillas fijas. `cols` admite llaves y `@seccion` (todas sus preguntas) o
# `@todo` (meta + preguntas). Lo que el schema no tenga se descarta al adaptar.
PRESETS = {
    "seguimiento": {
        "title": "Seguimiento de egresados (bolsa de trabajo)",
        "description": "Quién es, su carrera y si acepta correos; solo los que "
                       "aceptan, un registro por egresado.",
        "cols": ["_control", "_nombre", "carrera_egreso", "especialidad",
                 "periodo_egreso", "anio_egreso", "correo_personal", "telefono",
                 "recibir_correos", "actividad_actual", "nombre_empresa", "_fecha"],
        "filtros": {"recibir_correos": ["Si"]},
        "unico": True,
        "orden": [("carrera_egreso", "asc"), ("_nombre", "asc")],
    },
    "perfil": {
        "title": "Perfil del egresado",
        "description": "Datos de identificación y de egreso.",
        "cols": ["_control", "_nombre", "_fecha", "@perfil"],
        "filtros": {}, "unico": False, "orden": [("_fecha", "asc")],
    },
    "laboral": {
        "title": "Situación laboral",
        "description": "Dónde trabajan y en qué condiciones.",
        "cols": ["_control", "_nombre", "carrera_egreso", "@ubicacion_laboral"],
        "filtros": {}, "unico": False, "orden": [("carrera_egreso", "asc")],
    },
    "satisfaccion": {
        "title": "Satisfacción y desempeño",
        "description": "Pertinencia del plan de estudios y valoración de aspectos.",
        "cols": ["carrera_egreso", "@pertinencia", "@desempeno"],
        "filtros": {}, "unico": False, "orden": [("carrera_egreso", "asc")],
    },
    "completo": {
        "title": "Reporte completo",
        "description": "Todas las columnas.",
        "cols": ["@todo"],
        "filtros": {}, "unico": False, "orden": [("_fecha", "asc")],
    },
}
_COLS_RESPALDO = ("_id", "_fecha", "_control", "_nombre")


# ---------------------------------------------------------------------------
# Parametros
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ReportParams:
    """Parametros YA validados contra el formulario. `warnings` lista (en
    español) lo que se ignoro; no cuenta para la igualdad."""
    form_id: int | None = None
    cols: tuple = ()
    orden: tuple = (("_fecha", "asc"),)
    desde: date | None = None
    hasta: date | None = None
    egreso_desde: int | None = None
    egreso_hasta: int | None = None
    origen: str = ""
    filtros: tuple = ()                 # ((llave, (valores...)), ...)
    unico: bool = False
    encabezado: str = "corto"
    hojas: tuple = HOJAS
    cruce_filas: str | None = None
    cruce_cols: str | None = None
    warnings: list = field(default_factory=list, compare=False)


def _fields(form) -> list[dict]:
    return [f for f in ((getattr(form, "schema", None) or {}).get("fields") or [])
            if isinstance(f, dict) and f.get("key")]


def _plano(texto) -> str:
    """Minusculas sin acentos: llave de orden y comparacion de textos."""
    nfkd = unicodedata.normalize("NFKD", str(texto))
    return "".join(c for c in nfkd if not unicodedata.combining(c)).casefold()


def _lista(query, nombre: str) -> list:
    """Valores de `nombre` en un `QueryParams` (getlist) o en un dict."""
    if query is None:
        return []
    getlist = getattr(query, "getlist", None)
    if getlist is not None:
        return list(getlist(nombre))
    v = query.get(nombre)
    if v is None:
        return []
    return list(v) if isinstance(v, (list, tuple)) else [v]


def _uno(query, nombre: str) -> str:
    vals = _lista(query, nombre)
    return str(vals[-1]).strip() if vals else ""


def _csv(query, nombre: str) -> list[str]:
    out: list[str] = []
    for v in _lista(query, nombre):
        out.extend(p.strip() for p in str(v).split(",") if p.strip())
    return out


def _fecha_iso(txt: str, nombre: str, avisos: list) -> date | None:
    if not txt:
        return None
    try:
        return date.fromisoformat(txt)
    except ValueError:
        avisos.append(f"Se ignoró «{nombre}»: «{txt}» no es una fecha AAAA-MM-DD.")
        return None


def _anio(txt: str, nombre: str, avisos: list) -> int | None:
    if not txt:
        return None
    try:
        n = int(txt)
        if 1900 <= n <= 2200:
            return n
    except ValueError:
        pass
    avisos.append(f"Se ignoró «{nombre}»: «{txt}» no es un año.")
    return None


def _claves(form, extras=()) -> tuple[set, set]:
    """(llaves conocidas, llaves de opcion)."""
    campos = _fields(form)
    conocidas = set(META_KEYS) | {str(f["key"]) for f in campos} | set(extras)
    opcion = {str(f["key"]) for f in campos if f.get("type") in CHOICE_TYPES}
    return conocidas, opcion


def _valida(llave: str, conocidas: set) -> bool:
    return llave in conocidas or llave.startswith("extra_")


def _expandir_cols(form, tokens) -> list[str]:
    """Plantilla -> llaves existentes (descarta lo que el schema no tenga)."""
    campos = _fields(form)
    conocidas, _ = _claves(form)
    out: list[str] = []
    for t in tokens:
        if t == "@todo":
            out.extend(META_KEYS + tuple(str(f["key"]) for f in campos))
        elif t.startswith("@"):
            out.extend(str(f["key"]) for f in campos if f.get("section") == t[1:])
        elif t in conocidas:
            out.append(t)
    return list(dict.fromkeys(out))


class SurveyReportService:
    """Todo `@staticmethod`; ninguna funcion escribe en la BD."""

    # -----------------------------------------------------------------
    # Parametros
    # -----------------------------------------------------------------
    @staticmethod
    def preset_params(form, key: str) -> ReportParams:
        """`ReportParams` de una plantilla, adaptada al schema del formulario."""
        p = PRESETS[key]
        conocidas, opcion = _claves(form)
        cols = _expandir_cols(form, p["cols"]) or _expandir_cols(form, _COLS_RESPALDO)
        filtros = tuple(
            (k, tuple(v)) for k, v in p["filtros"].items() if k in opcion)
        orden = tuple((k, d) for k, d in p["orden"] if k in conocidas) \
            or (("_fecha", "asc"),)
        cf = "carrera_egreso" if "carrera_egreso" in opcion else None
        cc = "recibir_correos" if "recibir_correos" in opcion else None
        return ReportParams(
            form_id=getattr(form, "id", None), cols=tuple(cols), orden=orden,
            filtros=filtros, unico=bool(p["unico"]), cruce_filas=cf, cruce_cols=cc)

    @staticmethod
    def parse_params(query, form) -> ReportParams:
        """Query string, `QueryParams` o dict -> `ReportParams` validado. Nunca lanza."""
        if isinstance(query, (str, bytes)):
            from starlette.datastructures import QueryParams
            query = QueryParams(query)
        avisos: list[str] = []
        campos = _fields(form)
        orden_campos = [str(f["key"]) for f in campos]
        conocidas, opcion = _claves(form)

        cols = [c for c in dict.fromkeys(_csv(query, "cols"))]
        validas = [c for c in cols if _valida(c, conocidas)]
        for c in cols:
            if c not in validas:
                avisos.append(f"Columna desconocida omitida: «{c}».")
        if not validas:
            validas = SurveyReportService.preset_params(form, "seguimiento").cols

        orden: list = []
        for tok in _csv(query, "orden"):
            llave, _, d = tok.partition(":")
            llave, d = llave.strip(), d.strip().lower()
            if not _valida(llave, conocidas):
                avisos.append(f"Orden omitido: columna desconocida «{llave}».")
                continue
            if any(llave == o[0] for o in orden):
                continue
            orden.append((llave, "desc" if d == "desc" else "asc"))
        orden = orden[:MAX_ORDEN] or [("_fecha", "asc")]

        desde = _fecha_iso(_uno(query, "desde"), "desde", avisos)
        hasta = _fecha_iso(_uno(query, "hasta"), "hasta", avisos)
        if desde and hasta and desde > hasta:
            avisos.append("«Desde» es posterior a «hasta»: se intercambiaron.")
            desde, hasta = hasta, desde

        ed = _anio(_uno(query, "egreso_desde"), "egreso_desde", avisos)
        eh = _anio(_uno(query, "egreso_hasta"), "egreso_hasta", avisos)
        if (ed or eh) and "anio_egreso" not in orden_campos:
            avisos.append("Se ignoró el rango de egreso: el formulario no tiene «anio_egreso».")
            ed = eh = None
        if ed and eh and ed > eh:
            ed, eh = eh, ed

        origen = _uno(query, "origen").lower()
        if origen not in ("", "plataforma", "importada"):
            avisos.append(f"Origen «{origen}» desconocido: se ignoró.")
            origen = ""

        pedidos: dict[str, list[str]] = {}
        for nombre in list(getattr(query, "keys", lambda: [])()):
            if not str(nombre).startswith("f_"):
                continue
            llave = str(nombre)[2:]
            if llave not in opcion:
                avisos.append(f"Filtro omitido: «{llave}» no es una pregunta de opción.")
                continue
            vals = [str(v) for v in _lista(query, nombre) if str(v) != ""]
            if vals:
                pedidos.setdefault(llave, [])
                pedidos[llave].extend(v for v in vals if v not in pedidos[llave])
        filtros = tuple((k, tuple(pedidos[k])) for k in orden_campos if k in pedidos)

        unico = _uno(query, "unico").lower() in ("1", "true", "on", "si", "sí")

        enc = _uno(query, "encabezado").lower()
        if enc not in ENCABEZADOS:
            enc = "corto"

        pedidas = _csv(query, "hojas")
        if _lista(query, "hojas"):
            sel = {h for h in pedidas if h in HOJAS} | {"respuestas"}
            hojas = tuple(h for h in HOJAS if h in sel)
        else:
            hojas = HOJAS

        def _cruce(nombre, defecto):
            v = _uno(query, nombre)
            if v and v in opcion:
                return v
            if v:
                avisos.append(f"Cruce omitido: «{v}» no es una pregunta de opción.")
            return defecto if defecto in opcion else None

        return ReportParams(
            form_id=getattr(form, "id", None), cols=tuple(validas), orden=tuple(orden),
            desde=desde, hasta=hasta, egreso_desde=ed, egreso_hasta=eh, origen=origen,
            filtros=filtros, unico=unico, encabezado=enc, hojas=hojas,
            cruce_filas=_cruce("cruce_filas", "carrera_egreso"),
            cruce_cols=_cruce("cruce_cols", "recibir_correos"), warnings=avisos)

    @staticmethod
    def to_query(params: ReportParams) -> str:
        """Inverso de `parse_params`: `parse_params(to_query(p)) == p`."""
        pares: list[tuple[str, str]] = []
        if params.form_id:
            pares.append(("form_id", str(params.form_id)))
        pares.append(("cols", ",".join(params.cols)))
        pares.append(("orden", ",".join(f"{k}:{d}" for k, d in params.orden)))
        for nombre, v in (("desde", params.desde), ("hasta", params.hasta)):
            if v:
                pares.append((nombre, v.isoformat()))
        for nombre, v in (("egreso_desde", params.egreso_desde),
                          ("egreso_hasta", params.egreso_hasta)):
            if v:
                pares.append((nombre, str(v)))
        if params.origen:
            pares.append(("origen", params.origen))
        for llave, vals in params.filtros:
            pares.extend((f"f_{llave}", v) for v in vals)
        if params.unico:
            pares.append(("unico", "1"))
        pares.append(("encabezado", params.encabezado))
        pares.append(("hojas", ",".join(params.hojas)))
        if params.cruce_filas:
            pares.append(("cruce_filas", params.cruce_filas))
        if params.cruce_cols:
            pares.append(("cruce_cols", params.cruce_cols))
        return urlencode(pares)

    # -----------------------------------------------------------------
    # Catalogo
    # -----------------------------------------------------------------
    @staticmethod
    def quien(response, user) -> str:
        """Nombre a mostrar (regla unica; `pages/surveys_admin._who` delega aqui):
        el de la cuenta; si no hay cuenta y la respuesta se importo, el
        `nombre_completo` que trae; si no, «Anónimo»."""
        if user is not None:
            return user.full_name
        if response.identity_source == "import":
            nombre = str((response.answers or {}).get("nombre_completo") or "").strip()
            if nombre:
                return nombre
        return "Anónimo"

    @staticmethod
    def _corto(campo: dict) -> str:
        key = str(campo.get("key"))
        if key in SHORT_LABELS:
            return SHORT_LABELS[key]
        etiqueta = str(campo.get("label") or key)
        corto = re.split(r"[(:]", etiqueta, maxsplit=1)[0].strip() or etiqueta.strip()
        corto = corto[:SHORT_MAX].strip()
        return f"Valora: {corto}" if key.startswith("scale_") else corto

    @staticmethod
    def _opciones(campo: dict) -> list[dict]:
        if campo.get("type") == "scale":
            cfg = campo.get("scale") or {}
            try:
                lo, hi = int(cfg.get("min", 1)), int(cfg.get("max", 5))
            except (TypeError, ValueError):
                lo, hi = 1, 5
            return [{"value": str(n), "label": str(n)} for n in range(lo, hi + 1)]
        return [{"value": str(o.get("value")),
                 "label": str(o.get("label") or o.get("value"))}
                for o in (campo.get("options") or [])
                if isinstance(o, dict) and o.get("value") is not None]

    @staticmethod
    def _columnas(form, extras=()) -> dict:
        """llave -> definicion, en orden: meta, preguntas, extras."""
        cols: dict[str, dict] = {}
        for k, etiqueta, tipo in META:
            cols[k] = {"key": k, "label": etiqueta, "short": etiqueta, "type": tipo,
                       "choice": False, "options": [], "section": None}
        for f in _fields(form):
            tipo = f.get("type") or "text"
            es_op = tipo in CHOICE_TYPES
            cols[str(f["key"])] = {
                "key": str(f["key"]), "label": str(f.get("label") or f["key"]),
                "short": SurveyReportService._corto(f), "type": tipo, "choice": es_op,
                "options": SurveyReportService._opciones(f) if es_op else [],
                "section": f.get("section"),
                "min": (f.get("scale") or {}).get("min"),
                "max": (f.get("scale") or {}).get("max"),
            }
        for k in extras:
            if k not in cols:
                cols[k] = {"key": k, "label": k, "short": k, "type": "text",
                           "choice": False, "options": [], "section": "__extras__"}
        return cols

    @staticmethod
    def catalog(form, extras=()) -> dict:
        """Lo que la UI pinta: `sections`, `meta`, `presets`, `choice_keys`.

        `extras` (opcional): llaves `extra_*` de `extra_keys(db, form)`; sin
        ellas no hay seccion «Otros datos importados»."""
        cols = SurveyReportService._columnas(form, extras)
        secciones = []
        vistas: set = set()
        for s in ((getattr(form, "schema", None) or {}).get("sections") or []):
            k = s.get("key")
            items = [c for c in cols.values() if c["section"] == k]
            vistas.add(k)
            secciones.append({"key": k, "title": s.get("title") or k,
                              "description": s.get("description") or "", "columns": items})
        resto = [c for c in cols.values()
                 if c["section"] not in vistas and c["section"] not in (None, "__extras__")]
        if resto:
            secciones.append({"key": "otras", "title": "Otras preguntas",
                              "description": "", "columns": resto})
        ex = [c for c in cols.values() if c["section"] == "__extras__"]
        if ex:
            secciones.append({"key": "extras", "title": "Otros datos importados",
                              "description": "", "columns": ex})
        presets = []
        for k, p in PRESETS.items():
            pp = SurveyReportService.preset_params(form, k)
            presets.append({"key": k, "title": p["title"], "description": p["description"],
                            "cols": list(pp.cols), "query": SurveyReportService.to_query(pp)})
        return {"sections": secciones,
                "meta": [cols[k] for k in META_KEYS],
                "presets": presets,
                "choice_keys": [k for k, c in cols.items() if c["choice"]]}

    @staticmethod
    def extra_keys(db: Session, form) -> list[str]:
        """Llaves `extra_*` presentes en las respuestas del formulario (orden alfabetico)."""
        from itcj2.apps.titulatec.models import SurveyResponse

        conocidas = {str(f["key"]) for f in _fields(form)}
        out: set = set()
        q = db.query(SurveyResponse.answers).filter(
            SurveyResponse.form_id == form.id, SurveyResponse.identity_source == "import")
        for (resp,) in q:
            out.update(str(k) for k in (resp or {})
                       if str(k).startswith("extra_") and str(k) not in conocidas)
        return sorted(out)

    @staticmethod
    def semesters(db: Session, form) -> list[dict]:
        """Semestres con respuestas, del mas reciente al mas viejo.
        A = 1 ene-30 jun, B = 1 jul-31 dic."""
        from sqlalchemy import extract

        from itcj2.apps.titulatec.models import SurveyResponse

        a = extract("year", SurveyResponse.submitted_at)
        m = extract("month", SurveyResponse.submitted_at)
        pares = (db.query(a, m).filter(SurveyResponse.form_id == form.id)
                 .distinct().all())
        vistos = {(int(y), 1 if int(mo) <= 6 else 2) for y, mo in pares}
        out = []
        for y, h in sorted(vistos, reverse=True):
            if h == 1:
                d, hh, rot = date(y, 1, 1), date(y, 6, 30), f"{y}A · ene–jun"
            else:
                d, hh, rot = date(y, 7, 1), date(y, 12, 31), f"{y}B · jul–dic"
            out.append({"code": f"{y}{'A' if h == 1 else 'B'}", "label": rot,
                        "desde": d, "hasta": hh})
        return out

    # -----------------------------------------------------------------
    # Datos
    # -----------------------------------------------------------------
    @staticmethod
    def _tipar(campo: dict | None, key: str, valor):
        """Valor crudo de `answers` -> valor tipado (None si esta vacio)."""
        if valor is None or valor == "" or valor == []:
            return None
        if isinstance(valor, list):
            return [str(v) for v in valor]
        if isinstance(valor, bool):
            return "Sí" if valor else "No"
        tipo = (campo or {}).get("type")
        if tipo == "date":
            try:
                return date.fromisoformat(str(valor)[:10])
            except ValueError:
                return str(valor)
        numerico = tipo == "scale" or (
            tipo in (None, "text") and (key.startswith("anio_") or key == "promedio_final"))
        if numerico:
            try:
                n = float(str(valor).replace(",", ".").strip())
                if n != n or n in (float("inf"), float("-inf")):
                    return str(valor)
                return int(n) if n == int(n) else n
            except (TypeError, ValueError):
                return str(valor)
        if isinstance(valor, (int, float)):
            return valor
        return str(valor)

    @staticmethod
    def _claves_necesarias(form, params: ReportParams) -> set:
        conocidas, opcion = _claves(form)
        need = set(params.cols) | {k for k, _ in params.filtros} | {k for k, _ in params.orden}
        if "cruce" in params.hojas:
            need |= {params.cruce_filas, params.cruce_cols}
        if "resumen" in params.hojas:
            need |= {"carrera_egreso", "recibir_correos"} & conocidas
        if params.egreso_desde or params.egreso_hasta:
            need.add("anio_egreso")
        return {k for k in need if k and k not in META_KEYS}

    @staticmethod
    def collect(db: Session, form, params: ReportParams) -> list[dict]:
        """Filas filtradas, deduplicadas y ordenadas, con valores tipados.

        Fechas y origen se filtran en SQL; el resto en Python. Orden de las
        etapas: SQL -> `unico` (la respuesta MAS RECIENTE de cada egresado entre
        las que pasaron fecha/origen; asi quien dijo «Si» y luego «No» no se
        cuela en «Acepta correos = Si») -> egreso -> filtros de opcion -> orden.
        Usuarios, convocatorias y procesos se leen en lote (sin N+1).
        """
        from sqlalchemy.orm import joinedload

        from itcj2.apps.titulatec.models import (
            Cohort, SurveyResponse, TitulationProcess)
        from itcj2.core.models.user import User

        q = db.query(SurveyResponse).filter(SurveyResponse.form_id == form.id)
        if params.desde:
            q = q.filter(SurveyResponse.submitted_at >= datetime.combine(params.desde, time.min))
        if params.hasta:
            q = q.filter(SurveyResponse.submitted_at
                         < datetime.combine(params.hasta + timedelta(days=1), time.min))
        if params.origen == "importada":
            q = q.filter(SurveyResponse.identity_source == "import")
        elif params.origen == "plataforma":
            q = q.filter(SurveyResponse.identity_source != "import")
        respuestas = q.order_by(SurveyResponse.submitted_at.asc(), SurveyResponse.id.asc()).all()

        uids = {r.user_id for r in respuestas if r.user_id}
        pids = {r.process_id for r in respuestas if r.process_id}
        cids = {r.cohort_id for r in respuestas if r.cohort_id}
        users = ({u.id: u for u in db.query(User).filter(User.id.in_(uids)).all()}
                 if uids else {})
        procs = ({p.id: p for p in db.query(TitulationProcess)
                  .filter(TitulationProcess.id.in_(pids)).all()} if pids else {})
        cohorts = ({c.id: c for c in db.query(Cohort).options(joinedload(Cohort.academic_period))
                    .filter(Cohort.id.in_(cids)).all()} if cids else {})

        por_key = {str(f["key"]): f for f in _fields(form)}
        need = SurveyReportService._claves_necesarias(form, params)
        filas: list[dict] = []
        for r in respuestas:
            u = users.get(r.user_id)
            c = cohorts.get(r.cohort_id)
            p = procs.get(r.process_id)
            resp = r.answers or {}
            fila = {
                "_id": r.id, "_fecha": r.submitted_at,
                "_origen": "Importada" if r.identity_source == "import" else "Plataforma",
                "_control": r.control_number or (u.control_number if u else "") or "",
                "_nombre": SurveyReportService.quien(r, u),
                "_correo_cuenta": (u.email if u else "") or "",
                "_convocatoria": (c.period_code if c else "") or "",
                "_folio_proceso": (p.folio if p else "") or "",
                "_version": r.form_version,
            }
            for k in need:
                fila[k] = SurveyReportService._tipar(por_key.get(k), k, resp.get(k))
            filas.append(fila)

        if params.unico:
            ultimo: dict = {}
            for f in filas:                       # ya vienen por (fecha, id) ascendente
                if f["_control"]:
                    ultimo[f["_control"]] = f
            filas = [f for f in filas if not f["_control"] or ultimo[f["_control"]] is f]

        if params.egreso_desde or params.egreso_hasta:
            def _ok(f):
                a = f.get("anio_egreso")
                if not isinstance(a, (int, float)):
                    return False
                return ((not params.egreso_desde or a >= params.egreso_desde)
                        and (not params.egreso_hasta or a <= params.egreso_hasta))
            filas = [f for f in filas if _ok(f)]

        for llave, vals in params.filtros:
            conj = set(vals)

            def _pasa(f, llave=llave, conj=conj):
                v = f.get(llave)
                if _vacio(v):
                    return VACIO in conj
                items = v if isinstance(v, list) else [v]
                return any(_texto_opcion(x) in conj for x in items)
            filas = [f for f in filas if _pasa(f)]

        for llave, direccion in reversed(params.orden):
            llenos = [f for f in filas if not _vacio(f.get(llave))]
            vacios = [f for f in filas if _vacio(f.get(llave))]
            llenos.sort(key=lambda f, k=llave: _llave_orden(f.get(k)),
                        reverse=(direccion == "desc"))
            filas = llenos + vacios            # vacios al final SIEMPRE
        return filas

    @staticmethod
    def _unicos(filas: list[dict]) -> int:
        """Egresados distintos: controles distintos + filas sin control."""
        return (len({f["_control"] for f in filas if f["_control"]})
                + sum(1 for f in filas if not f["_control"]))

    @staticmethod
    def _encabezado(col: dict, modo: str) -> str:
        return {"clave": col["key"], "pregunta": col["label"]}.get(modo, col["short"])

    @staticmethod
    def preview(db: Session, form, params: ReportParams, limit: int = 10) -> dict:
        """`{total, unique, columns:[{key,header,full}], rows:[[str]], warnings, query}`."""
        extras = [c for c in params.cols if c.startswith("extra_")]
        cols = SurveyReportService._columnas(form, extras)
        filas = SurveyReportService.collect(db, form, params)
        return {
            "total": len(filas),
            "unique": SurveyReportService._unicos(filas),
            "columns": [{"key": k, "header": SurveyReportService._encabezado(cols[k], params.encabezado),
                         "full": cols[k]["label"]} for k in params.cols if k in cols],
            "rows": [[_texto(f.get(k)) for k in params.cols if k in cols]
                     for f in filas[:max(0, limit)]],
            "warnings": list(params.warnings),
            "query": SurveyReportService.to_query(params),
        }

    @staticmethod
    def filename(form, generated_at: datetime) -> str:
        return (f"reporte-encuesta-{form.code}-v{form.version}-"
                f"{generated_at.strftime('%Y%m%d-%H%M')}.xlsx")

    @staticmethod
    def describir_filtros(params: ReportParams, cols: dict) -> list[str]:
        """Filtros activos en lenguaje llano (hoja Respuestas y Parámetros)."""
        out = []
        if params.desde or params.hasta:
            out.append("Respondió " + " ".join(
                x for x in (f"desde {params.desde:%d/%m/%Y}" if params.desde else "",
                            f"hasta {params.hasta:%d/%m/%Y}" if params.hasta else "") if x))
        if params.egreso_desde or params.egreso_hasta:
            out.append(f"Año de egreso {params.egreso_desde or '…'}–{params.egreso_hasta or '…'}")
        if params.origen:
            out.append(f"Origen: {params.origen}")
        for llave, vals in params.filtros:
            nombre = cols[llave]["short"] if llave in cols else llave
            etiquetas = {o["value"]: o["label"] for o in cols.get(llave, {}).get("options", [])}
            out.append(f"{nombre}: " + ", ".join(
                SIN_RESPUESTA if v == VACIO else etiquetas.get(v, v) for v in vals))
        if params.unico:
            out.append("Un registro por egresado (el más reciente)")
        return out

    # -----------------------------------------------------------------
    # Libro
    # -----------------------------------------------------------------
    @staticmethod
    def build_xlsx(db: Session, form, params: ReportParams, *,
                   generated_by: str, generated_at: datetime) -> bytes:
        """Libro `.xlsx` en memoria. Hojas: Respuestas (siempre) y, segun
        `params.hojas`, Resumen, Distribución, Cruce y Parámetros."""
        import xlsxwriter

        extras = [c for c in params.cols if c.startswith("extra_")]
        cols = SurveyReportService._columnas(form, extras)
        filas = SurveyReportService.collect(db, form, params)
        buf = io.BytesIO()
        wb = xlsxwriter.Workbook(buf, {
            "in_memory": True, "strings_to_formulas": False,
            "strings_to_urls": False, "strings_to_numbers": False})
        wb.set_properties({"title": f"{form.title} — Reporte", "author": generated_by,
                           "comments": "Contiene datos personales."})
        fm = _formatos(wb)
        ctx = {"wb": wb, "fm": fm, "form": form, "params": params, "cols": cols,
               "filas": filas, "por": generated_by, "cuando": generated_at}
        _hoja_respuestas(ctx)
        if "resumen" in params.hojas:
            _hoja_resumen(ctx)
        if "distribucion" in params.hojas:
            _hoja_distribucion(ctx)
        if "cruce" in params.hojas:
            _hoja_cruce(ctx)
        if "parametros" in params.hojas:
            _hoja_parametros(ctx)
        wb.close()
        return buf.getvalue()


# ---------------------------------------------------------------------------
# Helpers de valores
# ---------------------------------------------------------------------------
def _vacio(v) -> bool:
    return v is None or v == "" or v == []


def _texto_opcion(v) -> str:
    if isinstance(v, float) and v == int(v):
        v = int(v)
    return str(v)


def _texto(v) -> str:
    """Valor tipado -> texto de la vista previa."""
    if v is None:
        return ""
    if isinstance(v, datetime):
        return v.strftime("%d/%m/%Y %H:%M")
    if isinstance(v, date):
        return v.strftime("%d/%m/%Y")
    if isinstance(v, list):
        return "; ".join(str(x) for x in v)
    return _texto_opcion(v)


def _llave_orden(v):
    if isinstance(v, datetime):
        return (0, v.timestamp())
    if isinstance(v, date):
        return (0, datetime.combine(v, time.min).timestamp())
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return (0, float(v))
    if isinstance(v, list):
        v = "; ".join(v)
    return (1, _plano(v))


def _etiquetas_de(v) -> list[str]:
    """Valor tipado -> etiquetas que cuenta una distribucion (vacio = «Sin respuesta»)."""
    if _vacio(v):
        return [SIN_RESPUESTA]
    return [_texto_opcion(x) for x in (v if isinstance(v, list) else [v])]


def _conteo(filas, llave: str, col: dict) -> tuple[list[tuple[str, str]], dict]:
    """(orden de filas [(valor, etiqueta)], conteos). Opciones del schema en su
    orden, luego valores fuera de catalogo (importados crudos), luego «Sin respuesta»."""
    conteos: dict[str, int] = {}
    for f in filas:
        for e in _etiquetas_de(f.get(llave)):
            conteos[e] = conteos.get(e, 0) + 1
    orden = [(o["value"], o["label"]) for o in col["options"]]
    conocidos = {v for v, _ in orden}
    fuera = sorted((e for e in conteos if e not in conocidos and e != SIN_RESPUESTA),
                   key=lambda e: (-conteos[e], _plano(e)))
    orden += [(e, e) for e in fuera] + [(SIN_RESPUESTA, SIN_RESPUESTA)]
    return orden, conteos


# ---------------------------------------------------------------------------
# Libro: formatos y hojas
# ---------------------------------------------------------------------------
TINTA, AMBAR, GRIS = "#0F172A", "#F59E0B", "#F1F5F9"


def _formatos(wb) -> dict:
    base = {"font_name": "Calibri", "font_size": 10, "valign": "top"}

    def f(**kw):
        return wb.add_format({**base, **kw})
    return {
        "titulo": f(bold=True, font_size=16, font_color=TINTA),
        "sub": f(font_color="#475569"),
        "enc": f(bold=True, font_color="#FFFFFF", bg_color=TINTA, text_wrap=True,
                 border=1, border_color="#334155"),
        "texto": f(), "wrap": f(text_wrap=True),
        "num": f(num_format="0.##"), "int": f(num_format="0"),
        "fecha": f(num_format="dd/mm/yyyy", align="left"),
        "fechahora": f(num_format="dd/mm/yyyy hh:mm", align="left"),
        "pct": f(num_format="0.0%"),
        "seccion": f(bold=True, font_size=12, font_color=TINTA, bottom=2, bottom_color=AMBAR),
        "th": f(bold=True, font_color="#FFFFFF", bg_color=TINTA, border=1, border_color="#334155"),
        "td": f(border=1, border_color="#CBD5E1"),
        "tdn": f(border=1, border_color="#CBD5E1", num_format="0"),
        "tdp": f(border=1, border_color="#CBD5E1", num_format="0.0%"),
        "tdd": f(border=1, border_color="#CBD5E1", num_format="0.00"),
        "tot": f(bold=True, bg_color=GRIS, border=1, border_color="#CBD5E1"),
        "totn": f(bold=True, bg_color=GRIS, border=1, border_color="#CBD5E1", num_format="0"),
        "totp": f(bold=True, bg_color=GRIS, border=1, border_color="#CBD5E1", num_format="0.0%"),
        "kpi_t": f(font_size=9, font_color="#64748B", bg_color=GRIS, align="center"),
        "kpi_v": f(bold=True, font_size=18, font_color="#B45309", bg_color=GRIS,
                   align="center", valign="vcenter"),
        "nota": f(italic=True, font_color="#64748B", text_wrap=True),
        "aviso": f(bold=True, font_color="#B45309", text_wrap=True),
    }


def _s(ws, r, c, texto, fmt=None):
    """Texto -> SIEMPRE `write_string` (jamas formula; ver docstring del modulo)."""
    ws.write_string(r, c, str(texto)[:_CELDA_MAX], fmt)


def _valor(ws, r, c, v, fm, tipo_col=None, wrap=False):
    if _vacio(v):
        ws.write_blank(r, c, None, fm["wrap" if wrap else "texto"])
    elif isinstance(v, datetime):
        ws.write_datetime(r, c, v, fm["fechahora"])
    elif isinstance(v, date):
        ws.write_datetime(r, c, datetime.combine(v, time.min), fm["fecha"])
    elif isinstance(v, (int, float)) and not isinstance(v, bool):
        ws.write_number(r, c, v, fm["num"] if isinstance(v, float) else fm["int"])
    elif isinstance(v, list):
        _s(ws, r, c, "; ".join(v), fm["wrap" if wrap else "texto"])
    else:
        _s(ws, r, c, v, fm["wrap" if wrap else "texto"])


def _unicos_encabezados(headers: list[str]) -> list[str]:
    vistos: dict[str, int] = {}
    out = []
    for h in headers:
        base = (h or "Columna")[:250]
        n = vistos.get(base.casefold(), 0)
        vistos[base.casefold()] = n + 1
        out.append(base if n == 0 else f"{base} ({n + 1})")
    return out


def _hoja_respuestas(ctx):
    wb, fm, params, cols, filas = ctx["wb"], ctx["fm"], ctx["params"], ctx["cols"], ctx["filas"]
    ws = wb.add_worksheet(HOJA_NOMBRES["respuestas"])
    claves = [k for k in params.cols if k in cols]
    n = len(claves)
    _s(ws, 0, 0, f"{ctx['form'].title} — Reporte", fm["titulo"])
    filtros = SurveyReportService.describir_filtros(params, cols)
    _s(ws, 1, 0, f"{len(filas)} respuestas · filtros: "
                 f"{'; '.join(filtros) if filtros else 'ninguno'}", fm["sub"])
    _s(ws, 2, 0, f"Generado el {ctx['cuando']:%d/%m/%Y %H:%M} por {ctx['por']}", fm["sub"])

    heads = _unicos_encabezados(
        [SurveyReportService._encabezado(cols[k], params.encabezado) for k in claves])
    top = 4
    ultima = top + max(len(filas), 1)
    if n:
        ws.add_table(top, 0, ultima, n - 1, {
            "columns": [{"header": h, "header_format": fm["enc"]} for h in heads],
            "style": "Table Style Light 1", "autofilter": True})
    ws.set_row(top, 48)
    anchos = []
    for c, k in enumerate(claves):
        col = cols[k]
        largo = max((len(_texto(f.get(k))) for f in filas[:300]), default=0)
        ancho = max(8, min(50, max(largo, min(len(heads[c]), 22)) + 2))
        envolver = largo > 50 or col["type"] == "textarea"
        anchos.append(ancho)
        ws.set_column(c, c, ancho)
        if params.encabezado != "pregunta" and col["label"] != heads[c]:
            ws.write_comment(top, c, col["label"][:1500], {"x_scale": 2.5, "y_scale": 1.5})
        for i, f in enumerate(filas):
            _valor(ws, top + 1 + i, c, f.get(k), fm, col["type"], wrap=envolver)
    if not filas and n:
        _s(ws, top + 1, 0, "Sin respuestas con estos filtros", fm["nota"])
    libres = 0
    for k in claves[:2]:
        if k in ("_control", "_nombre"):
            libres += 1
        else:
            break
    ws.freeze_panes(top + 1, libres)
    ws.set_landscape()
    ws.fit_to_pages(1, 0)
    ws.repeat_rows(top)
    ws.set_paper(9)


def _conteo_carrera(filas):
    out: dict[str, list] = {}
    for f in filas:
        k = f.get("carrera_egreso")
        k = _texto_opcion(k) if not _vacio(k) else SIN_RESPUESTA
        d = out.setdefault(k, [0, 0])
        d[0] += 1
        if _es_si(f.get("recibir_correos")):
            d[1] += 1
    return out


def _es_si(v) -> bool:
    return not _vacio(v) and _plano(v if not isinstance(v, list) else v[0]) in ("si", "s")


def _tabla(ws, fm, r0, c0, headers, rows, fmts, total=None):
    """Escribe una tabla; devuelve la fila siguiente a la ultima escrita."""
    for j, h in enumerate(headers):
        _s(ws, r0, c0 + j, h, fm["th"])
    r = r0 + 1
    for fila in rows:
        for j, v in enumerate(fila):
            if isinstance(v, str):
                _s(ws, r, c0 + j, v, fm["td"])
            else:
                ws.write_number(r, c0 + j, v, fm[fmts[j]])
        r += 1
    if total:
        for j, v in enumerate(total):
            if isinstance(v, str):
                _s(ws, r, c0 + j, v, fm["tot"])
            else:
                ws.write_number(r, c0 + j, v, fm["totp" if fmts[j] == "tdp" else "totn"])
        r += 1
    return r


def _chart(wb, tipo, subtipo, nombre, hoja, cats, vals, titulo, color=AMBAR, w=520, h=300):
    ch = wb.add_chart({"type": tipo, **({"subtype": subtipo} if subtipo else {})})
    serie = {"name": nombre, "categories": cats, "values": vals}
    if tipo != "pie":
        serie["fill"] = {"color": color}
        serie["data_labels"] = {"value": True}
    ch.add_series(serie)
    ch.set_title({"name": titulo[:100], "name_font": {"size": 11}})
    ch.set_legend({"none": True} if tipo != "pie" else {"position": "right"})
    ch.set_size({"width": w, "height": h})
    return ch


def _hoja_resumen(ctx):
    wb, fm, cols, filas = ctx["wb"], ctx["fm"], ctx["cols"], ctx["filas"]
    ws = wb.add_worksheet(HOJA_NOMBRES["resumen"])
    ws.hide_gridlines(2)
    ws.set_column(0, 0, 38)
    ws.set_column(1, 4, 16)
    ws.set_column(5, 5, 3)
    ws.set_column(6, 16, 10)
    nombre = HOJA_NOMBRES["resumen"]
    _s(ws, 0, 0, "Resumen", fm["titulo"])
    n = len(filas)
    kpis = [("Respuestas", n), ("Egresados únicos", SurveyReportService._unicos(filas))]
    if "recibir_correos" in cols:
        si = sum(1 for f in filas if _es_si(f.get("recibir_correos")))
        kpis.append(("% acepta recibir correos", f"{(si / n * 100) if n else 0:.1f}%"))
    fechas = [f["_fecha"] for f in filas if f.get("_fecha")]
    kpis.append(("Periodo cubierto", f"{min(fechas):%d/%m/%Y} – {max(fechas):%d/%m/%Y}"
                 if fechas else "—"))
    pos = [(0, 0), (1, 2), (3, 4), (6, 9)]
    for (t, v), (c0, c1) in zip(kpis, pos):
        if c0 == c1:
            _s(ws, 2, c0, t, fm["kpi_t"])
        else:
            ws.merge_range(2, c0, 2, c1, "", fm["kpi_t"])
            _s(ws, 2, c0, t, fm["kpi_t"])
            ws.merge_range(3, c0, 3, c1, "", fm["kpi_v"])
        if isinstance(v, int):
            ws.write_number(3, c0, v, fm["kpi_v"])
        else:
            _s(ws, 3, c0, v, fm["kpi_v"])
    ws.set_row(3, 30)
    r = 6

    if "carrera_egreso" in cols:
        _s(ws, r, 0, "Por carrera", fm["seccion"])
        datos = sorted(_conteo_carrera(filas).items(), key=lambda kv: (-kv[1][0], _plano(kv[0])))
        con_correo = "recibir_correos" in cols
        heads = ["Carrera", "Respuestas", "% del total"] + (
            ["Aceptan correos", "% aceptan"] if con_correo else [])
        rows = []
        for k, (tot, si) in datos:
            fila = [k, tot, tot / n if n else 0]
            if con_correo:
                fila += [si, si / tot if tot else 0]
            rows.append(fila)
        fmts = ["td", "tdn", "tdp", "tdn", "tdp"]
        ts = sum(t for _, (t, _) in datos)
        ss = sum(s for _, (_, s) in datos)
        total = ["Total", ts, 1.0 if ts else 0] + ([ss, ss / ts if ts else 0] if con_correo else [])
        fin = _tabla(ws, fm, r + 1, 0, heads, rows, fmts, total)
        if rows:
            ch = _chart(wb, "column", None, "Respuestas", nombre,
                        [nombre, r + 2, 0, r + 1 + len(rows), 0],
                        [nombre, r + 2, 1, r + 1 + len(rows), 1], "Respuestas por carrera")
            ws.insert_chart(r, 6, ch)
        r = max(fin, r + 17) + 1

    if "recibir_correos" in cols:
        _s(ws, r, 0, "¿Acepta recibir correos?", fm["seccion"])
        orden, cnt = _conteo(filas, "recibir_correos", cols["recibir_correos"])
        rows = [[lab, cnt.get(v, 0)] for v, lab in orden if cnt.get(v, 0)]
        fin = _tabla(ws, fm, r + 1, 0, ["Respuesta", "Respuestas"], rows, ["td", "tdn"])
        if rows:
            ch = _chart(wb, "pie", None, "Acepta correos", nombre,
                        [nombre, r + 2, 0, r + 1 + len(rows), 0],
                        [nombre, r + 2, 1, r + 1 + len(rows), 1], "Acepta recibir correos",
                        h=260)
            ws.insert_chart(r, 6, ch)
        r = max(fin, r + 14) + 1

    _s(ws, r, 0, "Por mes de respuesta", fm["seccion"])
    meses: dict[str, int] = {}
    for f in filas:
        if f.get("_fecha"):
            k = f["_fecha"].strftime("%Y-%m")
            meses[k] = meses.get(k, 0) + 1
    rows = [[k, v] for k, v in sorted(meses.items())]
    fin = _tabla(ws, fm, r + 1, 0, ["Mes", "Respuestas"], rows, ["td", "tdn"])
    if rows:
        ch = _chart(wb, "column", None, "Respuestas", nombre,
                    [nombre, r + 2, 0, r + 1 + len(rows), 0],
                    [nombre, r + 2, 1, r + 1 + len(rows), 1], "Respuestas por mes", h=260)
        ws.insert_chart(r, 6, ch)
    r = max(fin, r + 14) + 1

    _s(ws, r, 0, "Por origen", fm["seccion"])
    por_origen: dict[str, int] = {}
    for f in filas:
        por_origen[f["_origen"]] = por_origen.get(f["_origen"], 0) + 1
    _tabla(ws, fm, r + 1, 0, ["Origen", "Respuestas"],
           [[k, v] for k, v in sorted(por_origen.items())], ["td", "tdn"])


def _hoja_distribucion(ctx):
    wb, fm, params, cols, filas = ctx["wb"], ctx["fm"], ctx["params"], ctx["cols"], ctx["filas"]
    ws = wb.add_worksheet(HOJA_NOMBRES["distribucion"])
    ws.hide_gridlines(2)
    nombre = HOJA_NOMBRES["distribucion"]
    ws.set_column(0, 0, 46)
    ws.set_column(1, 2, 13)
    ws.set_column(3, 3, 3)
    _s(ws, 0, 0, "Distribución de respuestas", fm["titulo"])
    _s(ws, 1, 0, "Porcentajes sobre el total de respuestas del reporte.", fm["sub"])
    r, graficas = 3, 0
    base = len(filas)
    elegidas = [k for k in params.cols if k in cols and cols[k]["choice"]]
    if not elegidas:
        _s(ws, r, 0, "Ninguna de las columnas elegidas es una pregunta de opción.", fm["aviso"])
        return
    for k in elegidas:
        col = cols[k]
        ws.merge_range(r, 0, r, 2, "", fm["seccion"])
        _s(ws, r, 0, col["label"], fm["seccion"])
        ws.set_row(r, 30 if len(col["label"]) > 60 else 18)
        orden, cnt = _conteo(filas, k, col)
        rows = [[lab, cnt.get(v, 0), (cnt.get(v, 0) / base) if base else 0]
                for v, lab in orden]
        fin = _tabla(ws, fm, r + 1, 0, ["Opción", "Respuestas", "%"], rows,
                     ["td", "tdn", "tdp"])
        if rows:
            ws.conditional_format(r + 2, 2, r + 1 + len(rows), 2,
                                  {"type": "data_bar", "bar_color": AMBAR,
                                   "bar_solid": True, "min_type": "num", "min_value": 0,
                                   "max_type": "num", "max_value": 1})
        if col["type"] == "scale":
            vals = [float(f[k]) for f in filas if isinstance(f.get(k), (int, float))]
            _s(ws, fin, 0, "Promedio", fm["tot"])
            if vals:
                ws.write_number(fin, 1, sum(vals) / len(vals), wb.add_format(
                    {"bold": True, "num_format": "0.00", "bg_color": GRIS}))
            else:
                _s(ws, fin, 1, "—", fm["tot"])
            fin += 1
        if col["type"] == "multiselect":
            ws.merge_range(fin, 0, fin, 2, "Se puede marcar más de una opción: los % "
                           "pueden sumar más de 100.", fm["nota"])
            fin += 1
        alto = fin
        if len(rows) <= 20 and graficas < MAX_GRAFICAS and rows:
            ch = _chart(wb, "bar", None, col["short"], nombre,
                        [nombre, r + 2, 0, r + 1 + len(rows), 0],
                        [nombre, r + 2, 1, r + 1 + len(rows), 1], col["short"],
                        w=480, h=max(200, 22 * len(rows) + 60))
            ws.insert_chart(r + 1, 4, ch)
            graficas += 1
            alto = max(fin, r + 1 + (max(200, 22 * len(rows) + 60) // 20) + 1)
        r = alto + 2


def _hoja_cruce(ctx):
    wb, fm, params, cols, filas = ctx["wb"], ctx["fm"], ctx["params"], ctx["cols"], ctx["filas"]
    ws = wb.add_worksheet(HOJA_NOMBRES["cruce"])
    ws.hide_gridlines(2)
    nombre = HOJA_NOMBRES["cruce"]
    _s(ws, 0, 0, "Cruce de dos preguntas", fm["titulo"])
    a, b = params.cruce_filas, params.cruce_cols
    if not (a in cols and b in cols and cols[a]["choice"] and cols[b]["choice"]):
        ws.set_column(0, 0, 90)
        _s(ws, 2, 0, "No se pudo armar el cruce: las dos llaves deben ser preguntas de "
                     "opción del formulario.", fm["aviso"])
        return
    ca, cb = cols[a], cols[b]
    _s(ws, 1, 0, f"Filas: {ca['short']} · Columnas: {cb['short']}", fm["sub"])
    fa, _ = _conteo(filas, a, ca)
    fb, _ = _conteo(filas, b, cb)
    matriz: dict = {}
    for f in filas:
        for x in _etiquetas_de(f.get(a)):
            for y in _etiquetas_de(f.get(b)):
                matriz[(x, y)] = matriz.get((x, y), 0) + 1
    # Solo filas/columnas con datos (el schema puede traer 90 opciones en cero).
    fa = [(v, lab) for v, lab in fa if any((v, y) in matriz for y, _ in fb)]
    fb = [(v, lab) for v, lab in fb if any((x, v) in matriz for x, _ in fa)]
    if not fa or not fb:
        _s(ws, 3, 0, "Sin respuestas con estos filtros", fm["nota"])
        return
    ws.set_column(0, 0, 40)
    ws.set_column(1, len(fb) + 1, 14)
    ncol = len(fb)

    def _matriz(r0, titulo, pct):
        _s(ws, r0, 0, titulo, fm["seccion"])
        _s(ws, r0 + 1, 0, ca["short"], fm["th"])
        for j, (_, lab) in enumerate(fb):
            _s(ws, r0 + 1, 1 + j, lab, fm["th"])
        _s(ws, r0 + 1, 1 + ncol, "Total", fm["th"])
        ws.set_row(r0 + 1, 32)
        tot_col = [0] * ncol
        for i, (x, lab) in enumerate(fa):
            rr = r0 + 2 + i
            _s(ws, rr, 0, lab, fm["td"])
            tot_f = sum(matriz.get((x, y), 0) for y, _ in fb)
            for j, (y, _) in enumerate(fb):
                n = matriz.get((x, y), 0)
                tot_col[j] += n
                if pct:
                    ws.write_number(rr, 1 + j, (n / tot_f) if tot_f else 0, fm["tdp"])
                else:
                    ws.write_number(rr, 1 + j, n, fm["tdn"])
            ws.write_number(rr, 1 + ncol, 1 if pct and tot_f else tot_f,
                            fm["tdp" if pct else "tdn"])
        rt = r0 + 2 + len(fa)
        if not pct:
            _s(ws, rt, 0, "Total", fm["tot"])
            for j in range(ncol):
                ws.write_number(rt, 1 + j, tot_col[j], fm["totn"])
            ws.write_number(rt, 1 + ncol, sum(tot_col), fm["totn"])
        ws.conditional_format(r0 + 2, 1, r0 + 1 + len(fa), ncol, {
            "type": "2_color_scale", "min_color": "#FFFFFF", "max_color": AMBAR})
        return rt + (0 if pct else 1)

    fin = _matriz(3, "Conteo de respuestas", False)
    if len(fa) <= 25:
        ch = wb.add_chart({"type": "bar", "subtype": "stacked"})
        for j, (_, lab) in enumerate(fb):
            ch.add_series({"name": lab, "categories": [nombre, 5, 0, 4 + len(fa), 0],
                           "values": [nombre, 5, 1 + j, 4 + len(fa), 1 + j]})
        ch.set_title({"name": f"{ca['short']} × {cb['short']}"[:100], "name_font": {"size": 11}})
        ch.set_size({"width": 720, "height": max(260, 24 * len(fa) + 90)})
        ch.set_legend({"position": "bottom"})
        ws.insert_chart(fin + 1, 0, ch)
        fin += 2 + max(260, 24 * len(fa) + 90) // 20
    _matriz(fin + 1, "Porcentaje por fila", True)


def _hoja_parametros(ctx):
    fm, params, cols, form = ctx["fm"], ctx["params"], ctx["cols"], ctx["form"]
    ws = ctx["wb"].add_worksheet(HOJA_NOMBRES["parametros"])
    ws.hide_gridlines(2)
    ws.set_column(0, 0, 30)
    ws.set_column(1, 1, 70)
    ws.set_column(2, 2, 40)
    _s(ws, 0, 0, "Parámetros del reporte", fm["titulo"])
    filas = [
        ("Formulario", f"{form.code} · v{form.version} · {form.title}"),
        ("Generado por", ctx["por"]),
        ("Generado el", f"{ctx['cuando']:%d/%m/%Y %H:%M}"),
        ("Respuestas en el reporte", str(len(ctx["filas"]))),
        ("Encabezados", params.encabezado),
        ("Hojas", ", ".join(HOJA_NOMBRES[h] for h in params.hojas)),
        ("Orden", ", ".join(f"{cols[k]['short'] if k in cols else k} ({d})"
                            for k, d in params.orden)),
    ]
    filtros = SurveyReportService.describir_filtros(params, cols)
    filas.append(("Filtros", "; ".join(filtros) if filtros else "ninguno"))
    filas.append(("Configuración (liga)", SurveyReportService.to_query(params)))
    r = 2
    for k, v in filas:
        _s(ws, r, 0, k, fm["tot"])
        _s(ws, r, 1, v, fm["wrap"])
        r += 1
    r += 1
    _s(ws, r, 0, "Columnas", fm["seccion"])
    r += 1
    for j, h in enumerate(("Encabezado", "Pregunta completa", "Clave")):
        _s(ws, r, j, h, fm["th"])
    for k in params.cols:
        if k not in cols:
            continue
        r += 1
        _s(ws, r, 0, SurveyReportService._encabezado(cols[k], params.encabezado), fm["td"])
        _s(ws, r, 1, cols[k]["label"], fm["wrap"])
        _s(ws, r, 2, k, fm["td"])
    r += 2
    ws.merge_range(r, 0, r, 2, "Contiene datos personales. Uso exclusivo para el "
                   "seguimiento de egresados del ITCJ.", fm["aviso"])
