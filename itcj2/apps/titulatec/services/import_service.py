"""Importación de alumnos de una convocatoria desde CSV (formato del Forms, flexible).

No hardcodea encabezados: detecta columnas por heurística y permite ajuste manual.
Flujo: parse → autodetect mapping → validate (preview) → import.
"""
from __future__ import annotations

import csv
import io
import json
import re
import unicodedata
from pathlib import Path

from sqlalchemy.orm import Session

from itcj2.config import get_settings
from itcj2.core.utils.security import hash_nip

# Campos destino (semánticos). El admin mapea cada uno a un encabezado del CSV.
TARGET_FIELDS = ["control_number", "full_name", "email", "career", "modality"]

# Palabras clave para auto-detección por encabezado normalizado.
_FIELD_KEYWORDS = {
    "control_number": ["control", "matricula", "no control", "numero de control", "num control"],
    "full_name": ["nombre", "alumno", "estudiante"],
    "email": ["correo", "email", "e mail", "mail"],
    "career": ["carrera", "programa", "plan"],
    "modality": ["modalidad", "opcion de titulacion", "tipo de titulacion", "titulacion"],
}

_INSTITUTIONAL_DOMAIN = "@cdjuarez.tecnm.mx"

# Celdas que el admin puede corregir a mano en el preview. Son las únicas que
# `parse_overrides` acepta: nada más del CSV es editable.
_OVERRIDABLE_TEXT = ("control_number", "full_name", "email")
_OVERRIDABLE_ID = ("program_id", "modality_id")

# Secuencia final del folio `TT-{period_code}-{NNNN}`.
_FOLIO_SEQ_RE = re.compile(r"(\d+)$")

# Namespace del advisory lock que serializa la emisión de folios por
# convocatoria. Arbitrario pero fijo: cambiarlo deja de excluir a las
# importaciones que ya estén corriendo con el valor viejo.
_FOLIO_LOCK_NS = 0x7454  # "tT"


def set_initial_credential(user) -> None:
    """Credencial inicial del alumno: la contraseña ES su número de control.

    Política única de alta de alumnos, compartida con el alta manual
    (`pages/admin.py::_add_student`). El dato es público a propósito: el alumno
    no tiene otro canal para recibirla, y `must_change_password` lo obliga a
    cambiarla en el primer login.

    No se llama nunca sobre un `password_hash` existente: sobrescribirlo dejaría
    fuera al alumno que ya cambió la suya. NULL, en cambio, no es una contraseña
    —`auth_service.authenticate` (`core/services/auth_service.py:25`) lo rechaza
    sin siquiera comparar— así que ponerle la inicial solo puede desbloquear.
    """
    user.password_hash = hash_nip(user.control_number)
    user.must_change_password = True


# — Rol del alumno de titulación (2026-09-15) —
#
# El alumno dejó de reciclar el rol global `student`: ese es el que AgendaTec
# exige LITERALMENTE (`apps/agendatec/pages/student.py:27`) y el `role_id` de
# miles de cuentas, así que "alumno de AgendaTec" y "se está titulando" eran lo
# mismo para la autorización. `import_rows` es el ÚNICO punto de alta de roles de
# esta app (CSV, alta manual, aprobación de bandeja y liga de activación): el
# cambio vive aquí y no en cada llamador. Se leen en cada llamada, no al importar.
GRADUATE_ROLE = "graduate"
LEGACY_STUDENT_ROLE = "student"
# Dónde se asegura `graduate`: la plataforma (shell móvil y `role_home`) y la app.
GRADUATE_APP_KEYS = ("itcj", "titulatec")
# Dónde se revoca `student`. Una app que no exista en la BD se salta en silencio.
STUDENT_REVOKE_APP_KEYS = ("itcj", "titulatec", "agendatec")


def _sync_graduate_roles(db, user, *, graduate_role, student_role, app_ids) -> set[str]:
    """Deja a `user` como egresado. Devuelve las claves de las apps cuyas filas cambió.

    - `graduate` en cada app de `GRADUATE_APP_KEYS` (el llamador ya comprobó que
      existen);
    - fuera `student` en cada app de `STUDENT_REVOKE_APP_KEYS` que exista;
    - el alias legado `core_users.role_id` pasa a `graduate` SOLO desde `student`
      o NULL: pisar otro rol global (`staff`) le cambiaría el `role` del JWT en
      el siguiente refresco de sesión.

    Una consulta por usuario y `flush()` solo si algo cambió; nunca `commit()`
    (ver ATOMICIDAD en `import_rows`). `role_id` no cuenta como cambio para el
    caché: el de authz sale de `core_user_app_roles` y de los puestos.
    """
    from itcj2.core.models.user_app_role import UserAppRole

    grant_ids = {app_ids[k] for k in GRADUATE_APP_KEYS}
    revoke_ids = {app_ids[k] for k in STUDENT_REVOKE_APP_KEYS if k in app_ids}
    role_ids = [graduate_role.id] + ([student_role.id] if student_role is not None else [])

    filas = (db.query(UserAppRole)
             .filter(UserAppRole.user_id == user.id,
                     UserAppRole.app_id.in_(grant_ids | revoke_ids),
                     UserAppRole.role_id.in_(role_ids))
             .all())
    tocadas: set[int] = set()
    ya_graduate = {f.app_id for f in filas if f.role_id == graduate_role.id}
    for fila in filas:
        if (student_role is not None and fila.role_id == student_role.id
                and fila.app_id in revoke_ids):
            db.delete(fila)
            tocadas.add(fila.app_id)
    for app_id in sorted(grant_ids - ya_graduate):
        db.add(UserAppRole(user_id=user.id, app_id=app_id, role_id=graduate_role.id))
        tocadas.add(app_id)
    if tocadas:
        db.flush()

    if user.role_id is None or (student_role is not None and user.role_id == student_role.id):
        user.role_id = graduate_role.id

    clave = {app_id: key for key, app_id in app_ids.items()}
    return {clave[app_id] for app_id in tocadas}


def _norm(s: str) -> str:
    """Normaliza: minúsculas, sin acentos, sin puntuación, espacios colapsados."""
    s = (s or "").strip().lower()
    s = "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


# Formato de número de control: 8 dígitos, o una letra + 8 dígitos para quien
# viene de traslado (ej. B21221523). Copia deliberada del regex de
# itcj2/core/api/users_admin.py:23 — importarlo en top-level desde un módulo de
# core/api crea ciclo de imports (gotcha #2 del CLAUDE.md). Mantener en sync
# (`.pattern` idéntico; test_path_traversal_regression.py lo exige, y
# enrollment_request_service.py importa ESTE objeto, no una copia propia). La
# letra se normaliza a MAYÚSCULA en cada punto de entrada (import_rows,
# build_preview, alta manual de pages/admin.py) antes de validar/buscar: los
# lookups son filter_by(control_number=...) exactos.
CONTROL_NUMBER_RE = re.compile(r"^[A-Za-z]?\d{8}$")


def _imports_dir() -> Path:
    d = Path(get_settings().TITULATEC_UPLOAD_PATH) / "_imports"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _mapping_store() -> Path:
    return _imports_dir() / "_mapping.json"


# El token del CSV temporal lo genera el servidor con secrets.token_hex(8)
# (pages/admin.py:464) pero VUELVE del formulario en revalidate/commit, así que es
# entrada del usuario al usarse como componente de ruta: un token con "../" leía y
# borraba cualquier *.csv del contenedor. Se exige exactamente el formato emitido.
_TOKEN_RE = re.compile(r"^[0-9a-f]{16}$")


def _temp_csv_path(token: str) -> Path | None:
    """Ruta del CSV temporal de un token, o None si el token no tiene el formato."""
    if not isinstance(token, str) or not _TOKEN_RE.fullmatch(token):
        return None
    return _imports_dir() / f"{token}.csv"


class ImportService:
    # ---------- persistencia del token (CSV temporal) ----------
    @staticmethod
    def save_temp(raw: bytes, token: str) -> None:
        p = _temp_csv_path(token)
        if p is None:
            raise ValueError(f"token de importación inválido: {token!r}")
        p.write_bytes(raw)

    @staticmethod
    def read_temp(token: str) -> bytes | None:
        p = _temp_csv_path(token)
        if p is None:
            return None
        return p.read_bytes() if p.exists() else None

    @staticmethod
    def delete_temp(token: str) -> None:
        p = _temp_csv_path(token)
        if p is None:
            return
        p.unlink(missing_ok=True)

    # ---------- mapeo reusable ----------
    @staticmethod
    def load_saved_mapping() -> dict:
        p = _mapping_store()
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass
        return {}

    @staticmethod
    def save_mapping(mapping: dict) -> None:
        try:
            _mapping_store().write_text(json.dumps(mapping, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass

    # ---------- parsing ----------
    @staticmethod
    def parse(raw: bytes) -> tuple[list[str], list[dict]]:
        """Devuelve (headers, rows). Detecta delimitador (',' o ';')."""
        text = raw.decode("utf-8-sig", errors="replace")
        sample = text[:2048]
        delim = ";" if sample.count(";") > sample.count(",") else ","
        reader = csv.DictReader(io.StringIO(text), delimiter=delim)
        headers = reader.fieldnames or []
        rows = [dict(r) for r in reader]
        return headers, rows

    @staticmethod
    def autodetect_mapping(headers: list[str]) -> dict:
        """Mapea cada target field al encabezado más probable (o '')."""
        saved = ImportService.load_saved_mapping()
        mapping: dict[str, str] = {}
        norm_headers = {h: _norm(h) for h in headers}
        for field in TARGET_FIELDS:
            # 1) si el mapeo guardado apunta a un encabezado presente, úsalo
            if saved.get(field) in headers:
                mapping[field] = saved[field]
                continue
            # 2) heurística por keywords
            chosen = ""
            for h in headers:
                nh = norm_headers[h]
                if any(kw in nh for kw in _FIELD_KEYWORDS[field]):
                    chosen = h
                    break
            mapping[field] = chosen
        return mapping

    # ---------- estado editable del preview (viaja en 2 campos, no 6 por fila) ----------
    @staticmethod
    def parse_excluded(raw) -> set[int]:
        """`"3,17,42"` → `{3, 17, 42}`. Índices de fila que el admin desmarcó."""
        out: set[int] = set()
        for token in (raw or "").split(","):
            token = token.strip()
            if token.isdigit():
                out.add(int(token))
        return out

    @staticmethod
    def parse_overrides(raw) -> dict[int, dict]:
        """JSON `{"<idx>": {campo: valor}}` → `{idx: {campo: valor}}`, saneado.

        Solo viajan las celdas que el admin REALMENTE editó (el navegador las
        compara contra el valor que salió del CSV), así que en el caso normal
        esto llega vacío. Entrada del usuario: se ignora en silencio todo lo que
        no encaje en la forma esperada, igual que hacía el `int(form[...])` del
        endpoint viejo con un id vacío.
        """
        if not raw:
            return {}
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError, ValueError):
            return {}
        if not isinstance(data, dict):
            return {}
        out: dict[int, dict] = {}
        for key, patch in data.items():
            try:
                idx = int(key)
            except (TypeError, ValueError):
                continue
            if not isinstance(patch, dict):
                continue
            clean: dict = {}
            for f in _OVERRIDABLE_TEXT:
                if f in patch:
                    clean[f] = str(patch[f] if patch[f] is not None else "").strip()
            for f in _OVERRIDABLE_ID:
                if f in patch:
                    value = str(patch[f] if patch[f] is not None else "").strip()
                    clean[f] = int(value) if value.isdigit() else None
            if clean:
                out[idx] = clean
        return out

    # ---------- matching de catálogos ----------
    @staticmethod
    def _match_program(db: Session, value: str, programs=None):
        from itcj2.core.models.program import Program
        if not value:
            return None
        nv = _norm(value)
        # `programs` se pasa desde build_preview: releerlo por fila eran 400
        # consultas por preview, y ahora el preview se reconstruye entero en
        # cada revalidación.
        if programs is None:
            programs = db.query(Program).all()
        # match exacto normalizado, luego contains
        for p in programs:
            if _norm(p.name) == nv:
                return p
        for p in programs:
            np = _norm(p.name)
            if nv and (nv in np or np in nv):
                return p
        return None

    @staticmethod
    def _match_modality(db: Session, value: str, mods=None):
        from itcj2.apps.titulatec.models import Modality
        if not value:
            return None
        nv = _norm(value)
        if mods is None:
            mods = db.query(Modality).filter_by(is_active=True).all()
        for m in mods:
            if _norm(m.code) == nv or _norm(m.name) == nv:
                return m
        for m in mods:
            if nv in _norm(m.name) or any(tok in nv for tok in _norm(m.code).split("_")):
                return m
        return None

    # ---------- validación / preview ----------
    @staticmethod
    def build_preview(db: Session, rows: list[dict], mapping: dict, *,
                      overrides: dict[int, dict] | None = None,
                      excluded: set[int] | None = None) -> list[dict]:
        """Para cada fila devuelve datos normalizados + matches + issues + status.

        Es la ÚNICA fuente de las filas del wizard: el navegador ya no reenvía el
        preview (6 inputs por fila reventaban el `max_fields=1000` de Starlette
        pasada la fila 165), solo el token del CSV, el mapeo y estos dos campos:

        - ``overrides``: celdas corregidas a mano, aplicadas ANTES de validar —
          si el admin arregla un número de control, la fila deja de ser `error`.
        - ``excluded``: filas desmarcadas. `None` = primera carga, y ahí el
          default es el de siempre: entra todo salvo lo que tenga `error`.

        Cada fila trae además ``base``: el valor que sale del CSV con el mapeo
        vigente, antes de aplicar el override. El navegador lo usa como línea de
        comparación para volver a derivar el override en la siguiente petición,
        así que el ciclo editar → revalidar → editar es estable.
        """
        from itcj2.core.models.program import Program
        from itcj2.apps.titulatec.models import Modality

        overrides = overrides or {}
        programs = db.query(Program).all()
        modalities = db.query(Modality).filter_by(is_active=True).all()
        programs_by_id = {p.id: p for p in programs}
        modalities_by_id = {m.id: m for m in modalities}
        # Memo por texto crudo: un CSV de 400 filas suele traer 10 carreras.
        program_memo: dict[str, object] = {}
        modality_memo: dict[str, object] = {}

        out = []
        for i, row in enumerate(rows):
            def cell(field):
                h = mapping.get(field)
                return (row.get(h) or "").strip() if h else ""

            control = cell("control_number")
            full_name = cell("full_name")
            email = cell("email")
            career_raw = cell("career")
            modality_raw = cell("modality")

            if career_raw not in program_memo:
                program_memo[career_raw] = ImportService._match_program(
                    db, career_raw, programs)
            program = program_memo[career_raw]
            if modality_raw not in modality_memo:
                modality_memo[modality_raw] = ImportService._match_modality(
                    db, modality_raw, modalities)
            modality = modality_memo[modality_raw]

            base = {
                "control_number": control, "full_name": full_name, "email": email,
                "program_id": program.id if program else None,
                "modality_id": modality.id if modality else None,
            }

            patch = overrides.get(i)
            if patch:
                control = patch.get("control_number", control)
                full_name = patch.get("full_name", full_name)
                email = patch.get("email", email)
                if "program_id" in patch:
                    program = programs_by_id.get(patch["program_id"])
                if "modality_id" in patch:
                    modality = modalities_by_id.get(patch["modality_id"])

            # MAYÚSCULA antes de validar/mostrar/importar, venga del CSV o de
            # un override del admin. `base` (abajo) NO se toca: sigue siendo
            # el valor crudo del CSV, que es la línea de comparación para
            # volver a derivar `overrides` en el próximo POST (docstring de
            # build_preview).
            control = control.strip().upper()

            issues = []
            if not control:
                issues.append(("error", "Sin número de control"))
            elif not CONTROL_NUMBER_RE.fullmatch(control):
                # import_rows descarta estas filas; sin esto el preview decía "ok"
                # y el conteo final no cuadraba.
                issues.append(("error", f"Número de control inválido: {control}"))
            if not full_name:
                issues.append(("error", "Sin nombre"))
            if email and not email.lower().endswith(_INSTITUTIONAL_DOMAIN):
                issues.append(("warning", "Correo no institucional"))
            if not email:
                issues.append(("warning", "Sin correo"))
            if career_raw and not program:
                issues.append(("warning", f"Carrera no reconocida: {career_raw}"))
            if modality_raw and not modality:
                issues.append(("warning", f"Modalidad no reconocida: {modality_raw}"))

            status = "ok"
            if any(t == "error" for t, _ in issues):
                status = "error"
            elif issues:
                status = "warning"

            out.append({
                "idx": i,
                "control_number": control,
                "full_name": full_name,
                "email": email,
                "career_raw": career_raw,
                "modality_raw": modality_raw,
                "program_id": program.id if program else None,
                "program_name": program.name if program else None,
                "modality_id": modality.id if modality else None,
                "modality_name": modality.name if modality else None,
                "issues": issues,
                "status": status,
                # Primera carga: entra todo salvo los `error`. Después manda lo
                # que el admin dejó marcado.
                "include": (status != "error") if excluded is None else (i not in excluded),
                "base": base,
            })
        return out

    @staticmethod
    def rows_to_import(preview: list[dict]) -> list[dict]:
        """Filas marcadas del preview, en la forma que espera `import_rows`."""
        return [
            {
                "control_number": r["control_number"],
                "full_name": r["full_name"],
                "email": r["email"],
                "program_id": r["program_id"],
                "modality_id": r["modality_id"],
            }
            for r in preview if r["include"]
        ]

    # ---------- importación ----------
    @staticmethod
    def import_rows(db: Session, cohort, rows: list[dict], *,
                    actor_id: int | None = None, source: str = "csv",
                    commit: bool = True, repair_credentials: bool = True) -> dict:
        """Crea User (merge por control_number) + Process + phases + rol `graduate`.

        `rows` = lista de dicts ya resueltos (del preview/override del admin):
        {control_number, full_name, email, program_id, modality_id}.

        Credencial: todo alumno sale de aquí pudiendo entrar — al nuevo se le
        asigna la inicial y al que venía con `password_hash` NULL se le repara
        (ver `set_initial_credential`). Nunca se sobrescribe una existente.

        ROL (2026-09-15): todo alumno del lote queda como egresado —`graduate`
        en `itcj` y `titulatec`, fuera `student` en `itcj`/`titulatec`/
        `agendatec`, y el alias legado `core_users.role_id` en `graduate` si era
        `student` o NULL (ver `_sync_graduate_roles`). Si falta el rol `graduate`
        o la app `itcj`, 400 con el motivo: un alta sin rol es un alumno que no
        puede entrar.

        ATOMICIDAD: un solo `commit()`, al final. Antes `grant_role` commiteaba
        DENTRO del bucle (`core/services/authz_service.py:81`) sobre esta misma
        sesión, así que cada vuelta persistía lo pendiente de las anteriores: un
        lote que reventaba a media pasada dejaba medio alta escrita y sin
        rollback posible. Por eso los roles de app se escriben aquí a mano (mismo
        efecto, sin commit).

        CACHÉ DE AUTHZ, SIEMPRE DESPUÉS DEL COMMIT: si se tirara antes, una
        lectura concurrente lo repoblaría con el estado viejo y esa entrada
        viviría el TTL completo. Con `commit=True` lo tira esta función tras su
        commit. Con `commit=False` todavía no hay nada commiteado: los pares
        `(user_id, app_key)` que cambiaron viajan en `summary["authz_touched"]` y
        el llamador llama a `ImportService.invalidate_authz` DESPUÉS de su propio
        commit (`EnrollmentRequestService.approve`, `.grant_access` y `.verify`
        lo hacen).

        `repair_credentials=False` apaga `set_initial_credential` en LOS DOS
        caminos (alta nueva y reparación del que venía con `password_hash` NULL).
        La credencial inicial ES el número de control, que es dato público: la
        auto-inscripción fija la contraseña con el NIP que captura quien da el
        acceso —Centro de Cómputo en `grant_access`, o quien aprueba en el modo
        alterno (D15, D9 del spec 2026-09-24)— y por eso apaga esto. El
        llamador que lo apague es dueño de la credencial.

        `commit=False` deja la transacción en manos del llamador: se hace
        `flush()` en vez de `commit()`, así que el `pg_advisory_xact_lock` de la
        emisión de folios sigue tomado hasta que el llamador cierre. Ambos
        parámetros nacen con el valor del comportamiento de hoy, para no tocar a
        `pages/admin.py:139` ni a `pages/admin.py:587`.

        Devuelve summary con created_users / matched_users / repaired_users /
        processes_created / skipped / authz_touched.
        """
        from fastapi import HTTPException
        from sqlalchemy import text
        from itcj2.core.models.app import App
        from itcj2.core.models.user import User
        from itcj2.core.models.role import Role
        from itcj2.apps.titulatec.models import TitulationProcess, ProcessPhase, ProcessEvent
        from itcj2.apps.titulatec.services.phase_service import PhaseService
        from itcj2.core.services.authz_service import get_or_404_app

        get_or_404_app(db, "titulatec")
        graduate_role = db.query(Role).filter_by(name=GRADUATE_ROLE).first()
        student_role = db.query(Role).filter_by(name=LEGACY_STUDENT_ROLE).first()
        # Las apps de los roles en UNA consulta y sin filtrar `is_active`: una app
        # desactivada conserva filas que igual hay que limpiar.
        app_ids = dict(
            db.query(App.key, App.id)
            .filter(App.key.in_(set(GRADUATE_APP_KEYS) | set(STUDENT_REVOKE_APP_KEYS)))
            .all())
        period_code = cohort.period_code or str(cohort.period_id)

        # Serializa la emisión de folios de ESTA convocatoria. `folio` es UNIQUE
        # global (`models/process.py:15`) y la secuencia se derivaba de un
        # `count()` sin lock: dos importaciones simultáneas calculaban la misma y
        # la segunda moría por integridad a media pasada. El lock es de
        # TRANSACCIÓN (`_xact_`), lo único compatible con PgBouncer en modo
        # transaction, y se suelta en el commit de abajo.
        db.execute(text("SELECT pg_advisory_xact_lock(:ns, :key)"),
                   {"ns": _FOLIO_LOCK_NS, "key": int(cohort.id)})

        # Continúa desde el ÚLTIMO folio emitido, no desde el conteo: con un
        # proceso borrado, `count()` reemitía una secuencia ya usada.
        seq = 0
        for (folio,) in db.query(TitulationProcess.folio).filter_by(cohort_id=cohort.id).all():
            m = _FOLIO_SEQ_RE.search(folio or "")
            if m:
                seq = max(seq, int(m.group(1)))

        # El catálogo de fases no cambia a media importación: leerlo por proceso
        # eran 400 consultas en una convocatoria real.
        phase_numbers = PhaseService.phase_numbers(db)

        created_users = matched_users = processes_created = skipped = 0
        repaired_users = 0
        touched: set[tuple[int, str]] = set()

        for r in rows:
            # MAYÚSCULA antes del merge: el punto de entrada real de la
            # importación (CSV y alta manual pasan los dos por aquí). Sin
            # esto, "b21221523" y "B21221523" son DOS filter_by distintos y
            # el segundo alta crea una cuenta duplicada en vez de encontrar
            # la primera.
            control = (r.get("control_number") or "").strip().upper()
            full_name = (r.get("full_name") or "").strip()
            if not control or not full_name:
                skipped += 1
                continue

            # Mismo regex que core/api/users_admin.py (CONTROL_NUMBER_RE): este
            # importador lo omitía, y control_number termina siendo componente de
            # ruta en instance/apps/titulatec/{period}/{control}/documents/.
            if not CONTROL_NUMBER_RE.fullmatch(control):
                skipped += 1
                continue

            # Antes de tocar la cuenta. Un lote sin filas válidas no llega aquí.
            if graduate_role is None:
                raise HTTPException(status_code=400,
                                    detail=f"Rol '{GRADUATE_ROLE}' no existe.")
            faltan = [k for k in GRADUATE_APP_KEYS if k not in app_ids]
            if faltan:
                raise HTTPException(status_code=400,
                                    detail=f"App '{faltan[0]}' no existe.")

            user = db.query(User).filter_by(control_number=control).first()
            if user:
                matched_users += 1
                if r.get("email") and not user.email:
                    user.email = r["email"]
                # Auto-reparación: hasta 2026-09 esta función creaba usuarios sin
                # `password_hash`, y el reset del core está prohibido para quien
                # tiene `control_number` (`core/api/users_admin.py:427`) — el
                # alumno quedaba sin ninguna forma de entrar. Re-importarlo lo
                # desbloquea. Los que ya no se re-importan: comando CLI
                # `titulatec fix-missing-credentials`.
                if repair_credentials and not user.password_hash:
                    set_initial_credential(user)
                    repaired_users += 1
            else:
                # split simple: último token = apellido, resto = nombres
                parts = full_name.split()
                last = parts[-1] if len(parts) > 1 else full_name
                first = " ".join(parts[:-1]) if len(parts) > 1 else full_name
                user = User(
                    username=control, control_number=control,
                    first_name=first, last_name=last,
                    email=r.get("email") or None,
                    role_id=graduate_role.id,
                    is_active=True, must_change_password=True,
                )
                if repair_credentials:
                    set_initial_credential(user)
                db.add(user)
                db.flush()
                created_users += 1

            # Roles de egresado. Equivalente a `grant_role`/`revoke_role` de
            # `authz_service`, pero con `flush()` en vez de `commit()`: ver
            # ATOMICIDAD arriba.
            for app_key in _sync_graduate_roles(db, user, graduate_role=graduate_role,
                                                student_role=student_role,
                                                app_ids=app_ids):
                touched.add((user.id, app_key))

            proc = db.query(TitulationProcess).filter_by(student_id=user.id, cohort_id=cohort.id).first()
            if not proc:
                seq += 1
                proc = TitulationProcess(
                    folio=f"TT-{period_code}-{seq:04d}",
                    student_id=user.id, cohort_id=cohort.id,
                    program_id=r.get("program_id"), modality_id=r.get("modality_id"),
                    current_phase=1, status="active", is_app_active=True,
                )
                db.add(proc)
                db.flush()
                # fase 0 aprobada (intake), fase 1 en curso, resto pendiente.
                # Las fases salen del catálogo, no de un `range(9)`: es la misma fuente
                # que usa la guarda de `PhaseService`, así que no pueden desincronizarse.
                for n in phase_numbers:
                    st = ("approved" if n < proc.current_phase
                          else "in_progress" if n == proc.current_phase else "pending")
                    db.add(ProcessPhase(process_id=proc.id, phase_number=n, status=st))
                processes_created += 1

                # Alta del alumno = el unico suceso de la fase 0. Sin el, el
                # expediente empieza en blanco y no dice ni como entro.
                db.add(ProcessEvent(
                    process_id=proc.id, actor_id=actor_id,
                    event_type="process_created", phase_number=0,
                    payload={"source": source, "folio": proc.folio},
                ))

                from itcj2.apps.titulatec.services.notify import notify_student
                notify_student(db, user.id, type="PROCESS_CREATED",
                               title="Tu proceso de titulación está activo",
                               body="Servicios Escolares te dio de alta. Empieza subiendo tus documentos iniciales.",
                               process_id=proc.id, phase_number=1)

        authz_touched = sorted(touched)
        if commit:
            db.commit()
            # Después del commit (ver CACHÉ DE AUTHZ en el docstring). Con
            # `commit=False` ese momento es del llamador.
            ImportService.invalidate_authz(authz_touched)
        else:
            db.flush()

        return {
            "created_users": created_users,
            "matched_users": matched_users,
            "repaired_users": repaired_users,
            "processes_created": processes_created,
            "skipped": skipped,
            "authz_touched": authz_touched,
        }

    @staticmethod
    def invalidate_authz(touched) -> None:
        """Tira el caché de authz de los pares `(user_id, app_key)` de un summary.

        Llamar SOLO después del commit que persiste esos cambios: antes, una
        lectura concurrente repoblaría el caché con el estado viejo y esa entrada
        viviría el TTL completo. Best-effort, igual que el `_bust_user_app` de
        `grant_role`: un Redis caído nunca tumba un alta ya commiteada.

        `None` o vacío no hace nada: los dobles de `import_rows` de las pruebas
        devuelven summaries sin la llave.
        """
        if not touched:
            return
        try:
            from itcj2.core.services.authz_cache import invalidate_user_app
        except Exception:  # pragma: no cover - sin el módulo no hay caché que tirar
            return
        for user_id, app_key in touched:
            try:
                invalidate_user_app(user_id, app_key)
            except Exception:  # nunca romper el alta por el caché
                pass

    # ---------- remediación ----------
    @staticmethod
    def repair_missing_credentials(db: Session, *, cohort_id: int | None = None) -> int:
        """Le pone la credencial inicial a los alumnos que quedaron sin `password_hash`.

        Existe porque la auto-reparación de `import_rows` solo alcanza a quien se
        vuelve a importar, y re-importar no es una remediación viable: exige tener
        a mano el CSV original de la convocatoria. Este barrido es idempotente y no
        crea procesos, folios ni notificaciones.

        Acotado a usuarios CON proceso en titulatec y CON `control_number`: el
        staff autentica por `username` y una cuenta suya sin hash puede ser
        deliberada (SSO), no un alumno bloqueado.

        Devuelve cuántos reparó.
        """
        from itcj2.core.models.user import User
        from itcj2.apps.titulatec.models import TitulationProcess

        q = (db.query(User)
             .join(TitulationProcess, TitulationProcess.student_id == User.id)
             .filter(User.password_hash.is_(None),
                     User.control_number.isnot(None)))
        if cohort_id is not None:
            q = q.filter(TitulationProcess.cohort_id == cohort_id)

        users = q.distinct().all()
        for user in users:
            set_initial_credential(user)
        if users:
            db.commit()
        return len(users)
