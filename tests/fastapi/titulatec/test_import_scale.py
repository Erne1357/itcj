"""El asistente de importacion CSV tiene que aguantar una convocatoria real.

BLOQUEADOR: `partials/import_preview.html` emitia SEIS inputs con `name` por
fila (`row-{i}-include|control_number|full_name|email|program_id|modality_id`) y
tanto el commit como cada cambio de mapeo mandaban `hx-include="closest form"`,
es decir TODO el preview. `pages/admin.py` lo lee con `await request.form()` sin
argumentos, y el `FormParser` de Starlette corta en `max_fields=1000`
(`starlette/formparsers.py:96`): pasada la fila 165 el wizard responde 500 con
`MultiPartException: Too many fields`. Medido antes del arreglo: 160 filas OK
(960 campos), 167 revienta. Afectaba por igual a `/import/revalidate`, asi que
un CSV grande ni siquiera se podia remapear.

Contrato que fijan estos tests: **el payload del wizard es O(1) en filas**. El
CSV temporal ya vive en disco identificado por `token`, asi que el navegador
manda solo `token` + los 5 `map_*` + `excluded` + `overrides`, y el servidor
relee el archivo. Una convocatoria de 400, 1000 o 5000 filas manda los mismos
~8 campos.
"""
from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from urllib.parse import urlencode

import pytest

from itcj2.apps.titulatec.services.import_service import ImportService

# Encabezados del CSV del Forms (los mismos que ya trae el mapeo guardado en
# dev, para que la auto-deteccion tome el camino real).
CSV_HEADERS = [
    "Número de control", "Nombre completo", "Correo electrónico",
    "Carrera", "Modalidad de titulación",
]

PROGRAM_NAME = "Ingenieria Ficticia de Importacion"
MODALITY_NAME = "Modalidad Ficticia de Importacion"

# Numeros de control sinteticos: `99xxxxxx` es la convencion del harness y el
# rango 992xxxxx esta libre en la BD de dev (verificado).
_CONTROL_BASE = 99200000


def csv_bytes(n: int, *, start: int = _CONTROL_BASE) -> bytes:
    """CSV sintetico de `n` filas, todas validas."""
    lines = [",".join(CSV_HEADERS)]
    for i in range(n):
        control = str(start + i)
        lines.append(",".join([
            control,
            "ALUMNO{:04d} FICTICIO".format(i),
            "tt.import.{:04d}@example.invalid".format(i),
            PROGRAM_NAME,
            MODALITY_NAME,
        ]))
    return ("\n".join(lines) + "\n").encode("utf-8")


# ---------------------------------------------------------------------------
# Serializacion del <form> tal como lo haria el navegador
# ---------------------------------------------------------------------------
class _FormScraper(HTMLParser):
    """Recoge los pares (name, value) que un navegador enviaria del parcial.

    Emula lo justo: un checkbox solo viaja si esta `checked`, un `select` manda
    la `<option selected>` (o la primera si ninguna lo esta) y todo lo que no
    tiene `name` no existe para el formulario — que es justo la palanca del
    arreglo.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.fields: list[tuple[str, str]] = []
        self._select: dict | None = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "input":
            name = a.get("name")
            if not name or (a.get("type") or "").lower() == "file":
                return
            kind = (a.get("type") or "text").lower()
            if kind in ("checkbox", "radio"):
                if "checked" in a:
                    self.fields.append((name, a.get("value") or "on"))
            else:
                self.fields.append((name, a.get("value") or ""))
        elif tag == "select":
            self._select = {"name": a.get("name"), "chosen": None, "first": None}
        elif tag == "option" and self._select is not None:
            value = a.get("value") or ""
            if self._select["first"] is None:
                self._select["first"] = value
            if "selected" in a:
                self._select["chosen"] = value

    def handle_endtag(self, tag):
        if tag == "select" and self._select is not None:
            sel = self._select
            if sel["name"]:
                chosen = sel["chosen"] if sel["chosen"] is not None else (sel["first"] or "")
                self.fields.append((sel["name"], chosen))
            self._select = None


def serialize_form(html: str) -> list[tuple[str, str]]:
    parser = _FormScraper()
    parser.feed(html)
    return parser.fields


def field(payload, name, default=None):
    for k, v in payload:
        if k == name:
            return v
    return default


def total_detectado(html: str) -> int | None:
    """Lee el contador 'Filas detectadas' del encabezado del preview."""
    m = re.search(r"Filas detectadas.*?>\s*(\d+)\s*<", html, re.S)
    return int(m.group(1)) if m else None


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture()
def preserve_imports_dir():
    """Snapshot de `_imports/` (mapeo global + CSV temporales) y restauracion.

    `import_service` escribe en `instance/apps/titulatec/_imports/`, que es un
    directorio REAL del contenedor y no entra en el rollback de la transaccion:
    el commit guarda el mapeo global (`_mapping.json`) y los CSV que no llegan a
    commitearse quedan huerfanos. Sin esto la suite ensucia el entorno de dev.
    """
    from itcj2.apps.titulatec.services import import_service as mod

    dirpath = mod._imports_dir()
    mapping_file = mod._mapping_store()
    backup = mapping_file.read_bytes() if mapping_file.exists() else None
    before = {p.name for p in dirpath.glob("*.csv")}
    try:
        yield dirpath
    finally:
        for p in dirpath.glob("*.csv"):
            if p.name not in before:
                p.unlink(missing_ok=True)
        if backup is None:
            mapping_file.unlink(missing_ok=True)
        else:
            mapping_file.write_bytes(backup)


@pytest.fixture()
def import_ctx(db_session, titulatec_app, seed_phase_defs, make_program,
               make_modality, make_cohort, make_head, preserve_imports_dir):
    """Convocatoria + catalogos + jefa con `cohort.api.import_csv`."""
    seed_phase_defs()
    program = make_program(PROGRAM_NAME)
    modality = make_modality(name=MODALITY_NAME)
    cohort = make_cohort()
    head = make_head()
    return {"cohort": cohort, "head": head, "program": program, "modality": modality}


def _upload(client, cohort_id, raw):
    return client.post(
        "/titulatec/admin/cohorts/{}/import/upload".format(cohort_id),
        files={"archivo": ("alumnos.csv", raw, "text/csv")},
    )


def post_form(client, url, payload):
    """POST urlencoded de una lista de pares, como el navegador.

    `data=[(k, v), ...]` NO sirve: httpx solo urlencodea `Mapping`, y una lista
    la trata como stream de bytes — el servidor recibe el cuerpo vacio y todo
    responde 409. Hay que codificar a mano para poder repetir claves.
    """
    return client.post(
        url,
        content=urlencode(payload).encode("utf-8"),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )


# ---------------------------------------------------------------------------
# El techo de ~165 filas
# ---------------------------------------------------------------------------
def test_el_payload_del_wizard_no_crece_con_las_filas(client_as, import_ctx):
    """400 filas -> el <form> sigue teniendo un punado de campos, no 2400.

    Es el corazon del bloqueador: con 6 inputs por fila el navegador mandaba
    2406 campos y Starlette corta en 1000.
    """
    client = client_as(import_ctx["head"])
    resp = _upload(client, import_ctx["cohort"].id, csv_bytes(400))
    assert resp.status_code == 200

    payload = serialize_form(resp.text)
    assert total_detectado(resp.text) == 400, "el preview no leyo las 400 filas"
    assert len(payload) < 100, (
        "el form manda {} campos para 400 filas; Starlette corta en 1000 "
        "(max_fields), asi que el wizard revienta pasada la fila 165"
        .format(len(payload))
    )


def test_commit_importa_una_convocatoria_de_400_filas(
    client_as, db_session, import_ctx,
):
    """Punta a punta: subir 400 filas y confirmar crea los 400 procesos."""
    from itcj2.apps.titulatec.models import TitulationProcess

    cohort = import_ctx["cohort"]
    client = client_as(import_ctx["head"])

    resp = _upload(client, cohort.id, csv_bytes(400))
    assert resp.status_code == 200
    payload = serialize_form(resp.text)

    resp = post_form(
        client, "/titulatec/admin/cohorts/{}/import/commit".format(cohort.id), payload,
    )
    assert resp.status_code == 200, resp.text[:400]

    creados = db_session.query(TitulationProcess).filter_by(cohort_id=cohort.id).count()
    assert creados == 400, "se importaron {} de 400 filas".format(creados)


def test_revalidate_permite_remapear_una_convocatoria_de_400_filas(
    client_as, import_ctx,
):
    """Cambiar un select de mapeo con 400 filas cargadas no puede tumbar el wizard."""
    cohort = import_ctx["cohort"]
    client = client_as(import_ctx["head"])

    resp = _upload(client, cohort.id, csv_bytes(400))
    assert resp.status_code == 200
    payload = serialize_form(resp.text)

    # El admin pone la columna de correo en "— ninguna —".
    payload = [(k, "" if k == "map_email" else v) for k, v in payload]

    resp = post_form(
        client, "/titulatec/admin/cohorts/{}/import/revalidate".format(cohort.id), payload,
    )
    assert resp.status_code == 200, resp.text[:400]
    assert total_detectado(resp.text) == 400
    # Sin columna de correo, las 400 filas quedan con la advertencia "Sin correo".
    assert "Sin correo" in resp.text


# ---------------------------------------------------------------------------
# Contrato del payload nuevo: excluded + overrides
# ---------------------------------------------------------------------------
def test_commit_respeta_excluded_y_overrides(client_as, db_session, import_ctx):
    """El estado editable del preview viaja como dos campos, no como 6 por fila."""
    from itcj2.core.models.user import User
    from itcj2.apps.titulatec.models import TitulationProcess

    cohort = import_ctx["cohort"]
    client = client_as(import_ctx["head"])

    resp = _upload(client, cohort.id, csv_bytes(5))
    assert resp.status_code == 200
    payload = [(k, v) for k, v in serialize_form(resp.text)
               if k not in ("excluded", "overrides")]
    payload.append(("excluded", "1,3"))
    payload.append(("overrides", json.dumps({
        "0": {"full_name": "NOMBRE CORREGIDO", "email": "corregido@example.invalid"},
    })))

    resp = post_form(
        client, "/titulatec/admin/cohorts/{}/import/commit".format(cohort.id), payload,
    )
    assert resp.status_code == 200, resp.text[:400]

    controles = {
        c for (c,) in db_session.query(User.control_number)
        .join(TitulationProcess, TitulationProcess.student_id == User.id)
        .filter(TitulationProcess.cohort_id == cohort.id).all()
    }
    assert controles == {"99200000", "99200002", "99200004"}, (
        "las filas 1 y 3 venian en `excluded` y no debieron importarse"
    )
    corregido = db_session.query(User).filter_by(control_number="99200000").one()
    assert corregido.first_name + " " + corregido.last_name == "NOMBRE CORREGIDO"
    assert corregido.email == "corregido@example.invalid"


def test_revalidate_conserva_las_correcciones_del_admin(client_as, import_ctx):
    """Un remapeo no puede tirar a la basura lo que el admin ya corrigio a mano."""
    cohort = import_ctx["cohort"]
    client = client_as(import_ctx["head"])

    resp = _upload(client, cohort.id, csv_bytes(3))
    payload = [(k, v) for k, v in serialize_form(resp.text) if k != "overrides"]
    payload.append(("overrides", json.dumps({"1": {"control_number": "99299999"}})))

    resp = post_form(
        client, "/titulatec/admin/cohorts/{}/import/revalidate".format(cohort.id), payload,
    )
    assert resp.status_code == 200
    assert "99299999" in resp.text, "el override se perdio al revalidar"


def test_revalidate_conserva_las_filas_desmarcadas(client_as, import_ctx):
    """Lo que el admin desmarco sigue desmarcado despues de cambiar el mapeo."""
    cohort = import_ctx["cohort"]
    client = client_as(import_ctx["head"])

    resp = _upload(client, cohort.id, csv_bytes(3))
    payload = [(k, v) for k, v in serialize_form(resp.text) if k != "excluded"]
    payload.append(("excluded", "2"))

    resp = post_form(
        client, "/titulatec/admin/cohorts/{}/import/revalidate".format(cohort.id), payload,
    )
    assert resp.status_code == 200
    assert field(serialize_form(resp.text), "excluded") == "2"


# ---------------------------------------------------------------------------
# Atomicidad
# ---------------------------------------------------------------------------
class _CountingSession:
    """Proxy que cuenta los `commit()` que hace el service."""

    def __init__(self, inner):
        self._inner = inner
        self.commits = 0

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def commit(self):
        self.commits += 1
        self._inner.commit()


def test_import_rows_commitea_una_sola_vez(db_session, titulatec_app,
                                           seed_phase_defs, make_cohort):
    """`grant_role` commiteaba DENTRO del bucle: un lote a medias quedaba escrito."""
    seed_phase_defs()
    cohort = make_cohort()
    spy = _CountingSession(db_session)
    rows = [{"control_number": "9930000{}".format(i),
             "full_name": "ALUMNO{} FICTICIO".format(i),
             "email": None, "program_id": None, "modality_id": None}
            for i in range(3)]

    summary = ImportService.import_rows(spy, cohort, rows)

    assert summary["processes_created"] == 3
    assert spy.commits == 1, (
        "import_rows commiteo {} veces: el lote no es atomico".format(spy.commits)
    )


def test_el_folio_continua_desde_el_ultimo_y_no_desde_el_conteo(
    db_session, titulatec_app, seed_phase_defs, make_cohort, make_student,
    make_process,
):
    """El folio salia de `count()`: borrar un proceso lo hacia colisionar.

    `folio` es UNIQUE global (`models/process.py:15`), asi que reusar una
    secuencia ya emitida revienta la importacion a media pasada.
    """
    from itcj2.apps.titulatec.models import TitulationProcess

    seed_phase_defs()
    cohort = make_cohort()
    period_code = cohort.period_code or str(cohort.period_id)

    # Dos procesos previos (0001 y 0002) y se borra el primero: count()==1 -> el
    # importador volveria a emitir 0002.
    viejo = make_process(make_student(), cohort=cohort, phases=False,
                         folio="TT-{}-0001".format(period_code))
    make_process(make_student(), cohort=cohort, phases=False,
                 folio="TT-{}-0002".format(period_code))
    db_session.query(TitulationProcess).filter_by(id=viejo.id).delete()
    db_session.flush()

    ImportService.import_rows(db_session, cohort, [{
        "control_number": "99310001", "full_name": "ALUMNA FICTICIA",
        "email": None, "program_id": None, "modality_id": None,
    }])

    folios = {f for (f,) in db_session.query(TitulationProcess.folio)
              .filter_by(cohort_id=cohort.id).all()}
    assert "TT-{}-0003".format(period_code) in folios, (
        "folios emitidos: {}".format(sorted(folios))
    )
