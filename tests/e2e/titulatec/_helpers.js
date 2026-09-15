// @ts-check
/**
 * Helpers de la suite E2E de TitulaTec.
 *
 * POR QUÉ ESTA SUITE NO PUEDE USAR EL storageState GLOBAL
 * ------------------------------------------------------
 * `tests/e2e/global-setup.js` acuña un token de un ADMIN DE HELPDESK. TitulaTec
 * gatea sus 67 rutas con `require_page_app`, que **no tiene bypass de admin
 * global** (`itcj2/dependencies.py:104-139`): ese usuario recibe
 * `PageForbidden` en cualquier página de titulatec. Cada spec de esta carpeta
 * declara `test.use({ storageState: { cookies: [], origins: [] } })` —
 * NUNCA `storageState: undefined`: en Playwright 1.61 un valor `undefined` es
 * un no-op (`_combinedContextOptions` en node_modules/playwright/lib/index.js
 * solo copia `storageState` cuando es distinto de `undefined`), así que el
 * contexto heredaría la cookie del admin de helpdesk en vez de quedar sin
 * sesión — y, si necesita sesión, usa `stateFor('student' | 'head')`.
 *
 * Todo lo que crea esta suite lleva el marcador E2E_TITULATEC para poder
 * borrarlo con precisión al terminar, igual que hace `agendatec/_helpers.js`.
 */
const { execFileSync } = require('child_process');

const BACKEND_CONTAINER = process.env.E2E_BACKEND_CONTAINER || 'itcj-backend-1';
const E2E_TAG = 'E2E_TITULATEC';
const E2E_NIP = '4321'; // NIP del alumno sembrado; el login lo pide en #nip

/** Corre Python dentro del contenedor y devuelve su stdout. */
function runInContainer(py, { timeout = 120_000 } = {}) {
  return execFileSync(
    'docker',
    ['exec', '-i', BACKEND_CONTAINER, 'python', '-c', py],
    { stdio: ['ignore', 'pipe', 'inherit'], encoding: 'utf8', timeout }
  );
}

/**
 * Acuña un JWT para un user_id concreto DENTRO del contenedor, con `role: ''`
 * para que apliquen los permisos reales de BD y no el bypass de admin.
 */
function mintTokenFor(userId) {
  const id = parseInt(userId, 10);
  const py = [
    'from itcj2.database import SessionLocal',
    'from itcj2.middleware import _encode_jwt',
    'from itcj2.core.models.user import User',
    'db = SessionLocal()',
    'try:',
    `    u = db.get(User, ${id})`,
    "    name = ' '.join(p for p in [u.first_name or '', u.last_name or ''] if p).strip() or (u.username or 'user')",
    `    print(_encode_jwt({'sub': str(${id}), 'role': '', 'name': name, 'cn': u.control_number or ''}, 12))`,
    'finally:',
    '    db.close()',
  ].join('\n');
  const out = runInContainer(py, { timeout: 60_000 }).trim();
  if (!out || out.split('.').length !== 3) {
    throw new Error(`mintTokenFor(${userId}) no devolvió un JWT`);
  }
  return out;
}

// Tarea 6: la v1 del DML ya NO es un maniquí de dos preguntas -es el
// instrumento real (63 campos, 7 secciones)-, así que este escenario deja de
// perseguir "repetir sus dos primeras preguntas" (`public-survey`/`responsive`
// ya no dependen de este seed: usan sesión propia o el instrumento real
// directamente). Lo que este SUPERSET sí necesita seguir siendo es un
// formulario SINTÉTICO pequeño para probar el MECANISMO de pasos sin la
// fragilidad de recorrer 63 campos en un navegador:
//   - TRES secciones (no dos): la mínima forma de distinguir "Atrás" (paso
//     adyacente) de un salto NO adyacente en el indicador de progreso -saltar
//     de la 3a a la 1a sin pasar por la 2a-, que es justo el mecanismo nuevo
//     de la Tarea 3 (ronda 2).
//   - `nombre_completo` es NUEVO en "empleo": es el campo que
//     `pages/public.py:survey()` prellena desde `User.full_name` para
//     CUALQUIER formulario que lo declare (Tarea 4), así que con sesión llega
//     siempre contestado -nunca bloquea el paso 0- y sirve para probar
//     "sección 1 prellenada y editable" sin arrastrar los 63 campos reales.
//   - "detalle" y sus tres campos (`empresa`/`puesto`/`comentarios`) se
//     conservan EXACTOS -mismas llaves, mismo `required: False`-: son la
//     superficie de la que ya dependen `survey-draft.spec.js` y
//     `survey-draft-budget.spec.js`.
//   - "seguimiento" es NUEVA y OPCIONAL a propósito: solo existe para que haya
//     un tercer paso al que saltar; un campo obligatorio ahí cambiaría a qué
//     paso "reanuda" `_start_step` en los otros dos specs (que SÍ recargan la
//     página) y eso no es lo que esta tarea vino a tocar.
//   - Fix B1 (2026-09-14): `relacion_carrera` pasa su `visible_when` de
//     escalar ("empleado") a LISTA (["empleado", "otro"]), y
//     `situacion_laboral` gana la opcion "otro" que esa lista necesita para
//     tener un SEGUNDO valor real que probar (no un arreglo de uno solo).
//     Ningun spec existente selecciona "empleado" ni "otro" -"buscando" y
//     "estudiando" son las unicas respuestas que usan public-survey,
//     survey-draft y survey-draft-budget, y ambas siguen fuera de la lista-,
//     asi que este cambio no les mueve el piso: `relacion_carrera` sigue
//     invisible en los tres. `survey-visible-when-list.spec.js` es el unico
//     consumidor nuevo de "otro".
// `validation.maxLength` sigue siendo OBLIGATORIO en todo campo de texto
// (spec §4.1).
const SEED_PY = `
import json, sys
from datetime import date, timedelta

from itcj2.database import SessionLocal
from itcj2.core.models.academic_period import AcademicPeriod
from itcj2.core.models.app import App
from itcj2.core.models.permission import Permission
from itcj2.core.models.program import Program
from itcj2.core.models.role import Role
from itcj2.core.models.role_permission import RolePermission
from itcj2.core.models.user import User
from itcj2.core.models.user_app_role import UserAppRole
from itcj2.core.utils.security import hash_nip
from itcj2.apps.titulatec.models import (
    Cohort, CotejoRequirement, ProcessPhase, SurveyForm, TitulationProcess,
)
from itcj2.middleware import _encode_jwt

TAG = "${E2E_TAG}"
NIP = "${E2E_NIP}"
CONTROL = "29990101"

HEAD_PERMS = [
    "titulatec.dashboard.school_services",
    "titulatec.process.page.list",
    "titulatec.process.page.detail",
    "titulatec.process.api.read.all",
    "titulatec.process.api.requirement.mark",
    "titulatec.cohort.page.list",
    "titulatec.cohort.api.update",
    "titulatec.cohort.api.cotejo_reqs",
    "titulatec.survey.page.list",
    "titulatec.survey.api.read",
    "titulatec.survey.api.export",
    "titulatec.enrollment_request.page.list",
    "titulatec.enrollment_request.api.approve",
    "titulatec.enrollment_request.api.reject",
]
STUDENT_PERMS = [
    "titulatec.dashboard.student",
    "titulatec.process.page.my",
    "titulatec.process.api.read.own",
    "titulatec.appointment.page.my",
]

SCHEMA = {
    "enabled": True,
    "sections": [
        {"key": "empleo", "title": "Situación laboral"},
        {"key": "detalle", "title": "Detalle de tu empleo"},
        {"key": "seguimiento", "title": "Seguimiento"},
    ],
    "fields": [
        {"key": "nombre_completo", "section": "empleo", "type": "text",
         "label": "Nombre completo", "required": True,
         "validation": {"maxLength": 200}},
        {"key": "situacion_laboral", "section": "empleo", "type": "radio",
         "label": "¿Cuál es tu situación laboral actual?", "required": True,
         "options": [{"value": "empleado", "label": "Trabajando"},
                     {"value": "buscando", "label": "Buscando empleo"},
                     {"value": "estudiando", "label": "Estudiando"},
                     {"value": "otro", "label": "Otra situación"}]},
        {"key": "relacion_carrera", "section": "empleo", "type": "scale",
         "label": "¿Qué tanto se relaciona tu empleo con tu carrera?",
         "required": True,
         "scale": {"min": 1, "max": 5, "min_label": "Nada relacionado",
                   "max_label": "Totalmente relacionado"},
         # Lista, no escalar (fix B1): pertenencia, no igualdad. "otro" es el
         # SEGUNDO elemento a proposito -detecta una implementacion que solo
         # mirara el primero-.
         "visible_when": {"situacion_laboral": ["empleado", "otro"]}},
        {"key": "empresa", "section": "detalle", "type": "text",
         "label": "¿En qué empresa trabajas?", "required": False,
         "validation": {"maxLength": 120}},
        {"key": "puesto", "section": "detalle", "type": "text",
         "label": "¿Cuál es tu puesto?", "required": False,
         "validation": {"maxLength": 120}},
        {"key": "comentarios", "section": "detalle", "type": "textarea",
         "label": "Comentarios adicionales", "required": False,
         "validation": {"maxLength": 2000}},
        {"key": "interes_bolsa_trabajo", "section": "seguimiento", "type": "radio",
         "label": "¿Te interesa recibir vacantes de la bolsa de trabajo?",
         "required": False,
         "options": [{"value": "si", "label": "Sí"},
                     {"value": "no", "label": "No"}]},
    ],
}

db = SessionLocal()
try:
    app = db.query(App).filter_by(key="titulatec").one()

    def _role(nombre, codigos):
        r = db.query(Role).filter_by(name=nombre).first()
        if r is None:
            r = Role(name=nombre); db.add(r); db.flush()
        for code in codigos:
            p = db.query(Permission).filter_by(app_id=app.id, code=code).first()
            if p is None:
                p = Permission(app_id=app.id, code=code, name=code)
                db.add(p); db.flush()
            if db.query(RolePermission).filter_by(role_id=r.id, perm_id=p.id).first() is None:
                db.add(RolePermission(role_id=r.id, perm_id=p.id))
        db.flush()
        return r

    rol_head = _role(TAG + "_head", HEAD_PERMS)
    rol_alumno = _role(TAG + "_student", STUDENT_PERMS)

    program = db.query(Program).filter_by(name=TAG + " Sistemas").first()
    if program is None:
        program = Program(name=TAG + " Sistemas"); db.add(program); db.flush()

    # Cierra TODA convocatoria abierta: public_enrollment_cohort FALLA CERRADO
    # con >1 abierta (503) y en dev suelen quedar varias, porque hasta este
    # trabajo toda convocatoria nacía status='open' con fechas NULL.
    prev_open = [c.id for c in db.query(Cohort).filter_by(status="open").all()]
    db.query(Cohort).filter(Cohort.status == "open").update(
        {"status": "closed"}, synchronize_session=False)

    period = AcademicPeriod(code="29991", name=TAG + " periodo",
                            start_date=date(2029, 1, 1), end_date=date(2029, 6, 30),
                            status="INACTIVE")
    db.add(period); db.flush()

    cohort = Cohort(period_id=period.id, name=TAG + " convocatoria", status="open",
                    opens_at=date.today() - timedelta(days=1),
                    closes_at=date.today() + timedelta(days=30))
    db.add(cohort); db.flush()

    req = CotejoRequirement(cohort_id=cohort.id, icon="clipboard-check",
                            label="Encuesta de egresados",
                            hint="Comprobante de haberla contestado.",
                            order_index=0, code="graduate_survey",
                            auto_source="graduate_survey")
    db.add(req); db.flush()

    student = User(first_name=TAG, last_name="ALUMNO", control_number=CONTROL,
                   username=CONTROL, password_hash=hash_nip(NIP), is_active=True)
    db.add(student); db.flush()
    db.add(UserAppRole(user_id=student.id, app_id=app.id, role_id=rol_alumno.id))

    head = User(first_name=TAG, last_name="JEFATURA", username=TAG + "_head",
                is_active=True)
    db.add(head); db.flush()
    db.add(UserAppRole(user_id=head.id, app_id=app.id, role_id=rol_head.id))

    proc = TitulationProcess(folio="TT-29991-9001", student_id=student.id,
                             cohort_id=cohort.id, program_id=program.id,
                             current_phase=1, status="active")
    db.add(proc); db.flush()
    for n in range(9):
        st = "approved" if n < 1 else "in_progress" if n == 1 else "pending"
        db.add(ProcessPhase(process_id=proc.id, phase_number=n, status=st))

    # El índice parcial uq_titulatec_survey_forms_open tolera UNA sola versión
    # abierta por code: se cierra la del DML y se restaura en el cleanup.
    prev_form = db.query(SurveyForm).filter_by(code="egresados", status="open").first()
    prev_form_id = prev_form.id if prev_form else None
    if prev_form is not None:
        prev_form.status = "closed"
    db.flush()
    max_v = max([f.version for f in db.query(SurveyForm).filter_by(code="egresados").all()] or [0])
    form = SurveyForm(code="egresados", title=TAG + " encuesta de egresados",
                      description="Escenario E2E.", schema=SCHEMA,
                      version=max_v + 1, status="open", is_anonymous=False)
    db.add(form); db.flush()

    db.commit()

    sys.stdout.write(json.dumps({
        "tag": TAG,
        "studentId": student.id,
        "studentControl": CONTROL,
        "studentToken": _encode_jwt({"sub": str(student.id), "role": "",
                                     "name": TAG + " ALUMNO", "cn": CONTROL}, 12),
        "headId": head.id,
        "headToken": _encode_jwt({"sub": str(head.id), "role": "",
                                  "name": TAG + " JEFATURA", "cn": ""}, 12),
        "cohortId": cohort.id,
        "periodId": period.id,
        "programId": program.id,
        "processId": proc.id,
        "requirementId": req.id,
        "formId": form.id,
        "formVersion": form.version,
        "prevOpenCohorts": prev_open,
        "prevOpenFormId": prev_form_id,
    }))
finally:
    db.close()
`;

// Task 25 ronda 1, hallazgo CRÍTICO de revisión: la restauración de abajo
// (`restorePy`) vive en su PROPIO script/sesión/transacción, separada de los
// ~15 DELETE de `deletePy`. Antes ambas cosas compartían una sola transacción
// con la restauración al final: si CUALQUIER DELETE fallaba (p.ej. una FK
// desde una tabla que esta lista todavía no contempla, conforme las Tareas 26
// y 27 ejerzan más superficie de la app), nada de esa transacción se
// comprometía —ni siquiera la restauración— y la convocatoria o la encuesta
// pública ('egresados') que `seedScenario()` cerró se quedaba cerrada para
// TODO dev hasta que alguien lo notara. `cleanupScenario` llama a
// `restorePy` desde un `finally`, así que corre siempre, incluso si
// `runInContainer(deletePy(...))` lanza.
function deletePy(ctx) {
  return `
from itcj2.database import SessionLocal
from sqlalchemy import text

TAG = "${E2E_TAG}"

db = SessionLocal()
try:
    # Hijos -> padres. Todo cuelga del proceso, la convocatoria o el formulario.
    db.execute(text("DELETE FROM titulatec_survey_answers WHERE response_id IN "
                    "(SELECT id FROM titulatec_survey_responses WHERE form_id = :f)"),
               {"f": ${ctx.formId}})
    db.execute(text("DELETE FROM titulatec_survey_responses WHERE form_id = :f"),
               {"f": ${ctx.formId}})
    db.execute(text("DELETE FROM titulatec_survey_drafts WHERE form_id = :f"),
               {"f": ${ctx.formId}})
    db.execute(text("DELETE FROM titulatec_survey_forms WHERE id = :f"), {"f": ${ctx.formId}})

    db.execute(text("DELETE FROM titulatec_requirement_fulfillments WHERE process_id IN "
                    "(SELECT id FROM titulatec_processes WHERE cohort_id = :c)"),
               {"c": ${ctx.cohortId}})
    db.execute(text("DELETE FROM titulatec_process_events WHERE process_id IN "
                    "(SELECT id FROM titulatec_processes WHERE cohort_id = :c)"),
               {"c": ${ctx.cohortId}})
    db.execute(text("DELETE FROM titulatec_process_phases WHERE process_id IN "
                    "(SELECT id FROM titulatec_processes WHERE cohort_id = :c)"),
               {"c": ${ctx.cohortId}})
    db.execute(text("DELETE FROM titulatec_enrollment_requests WHERE cohort_id = :c"),
               {"c": ${ctx.cohortId}})
    db.execute(text("DELETE FROM titulatec_processes WHERE cohort_id = :c"),
               {"c": ${ctx.cohortId}})
    db.execute(text("DELETE FROM titulatec_cotejo_requirements WHERE cohort_id = :c"),
               {"c": ${ctx.cohortId}})
    db.execute(text("DELETE FROM titulatec_cohorts WHERE id = :c"), {"c": ${ctx.cohortId}})
    db.execute(text("DELETE FROM core_academic_periods WHERE id = :p"), {"p": ${ctx.periodId}})

    # Usuarios del escenario, incluidos los que crea una aprobación de solicitud
    # (username = número de control que empieza con 2999).
    db.execute(text("DELETE FROM core_student_profile WHERE user_id IN "
                    "(SELECT id FROM core_users WHERE first_name = :t OR username LIKE '2999%')"),
               {"t": TAG})
    db.execute(text("DELETE FROM core_notifications WHERE user_id IN "
                    "(SELECT id FROM core_users WHERE first_name = :t OR username LIKE '2999%')"),
               {"t": TAG})
    db.execute(text("DELETE FROM core_user_app_roles WHERE user_id IN "
                    "(SELECT id FROM core_users WHERE first_name = :t OR username LIKE '2999%')"),
               {"t": TAG})
    db.execute(text("DELETE FROM core_users WHERE first_name = :t OR username LIKE '2999%'"),
               {"t": TAG})

    db.execute(text("DELETE FROM core_role_permissions WHERE role_id IN "
                    "(SELECT id FROM core_roles WHERE name LIKE :t)"), {"t": TAG + "%"})
    db.execute(text("DELETE FROM core_roles WHERE name LIKE :t"), {"t": TAG + "%"})
    db.execute(text("DELETE FROM core_programs WHERE name LIKE :t"), {"t": TAG + "%"})

    db.commit()
    print("E2E titulatec cleanup OK (deletes)")
finally:
    db.close()
`;
}

/**
 * Restaura lo que `seedScenario()` cerró (la convocatoria previa y/o la
 * versión del DML) para tener un escenario determinista. INDEPENDIENTE de
 * `deletePy`: proceso, sesión y transacción propios, y su propio `db.commit()`
 * — ver la nota arriba de `deletePy`. Sin `PREV_COHORTS`/`PREV_FORM` que
 * restaurar, los `if` de abajo simplemente no ejecutan ningún UPDATE.
 *
 * Cierra PRIMERO la convocatoria y el formulario DEL PROPIO escenario
 * (`SCENARIO_COHORT` / `SCENARIO_FORM`) antes de reabrir los previos. Esto no
 * es cosmético: se descubrió al PROBAR el hallazgo crítico de revisión
 * (Task 25 ronda 1) forzando un fallo en `deletePy` a propósito. Si
 * `deletePy` falla ANTES de borrar el formulario del escenario, esa fila
 * sigue 'open' cuando `restorePy` corre, y el `UPDATE ... SET status='open'`
 * sobre `PREV_FORM` viola `uq_titulatec_survey_forms_open` (a lo sumo UNA
 * fila 'open' por `code`) — la restauración misma lanzaba, dejando la
 * encuesta pública real cerrada Y la del escenario abierta, que es PEOR que
 * el problema original. El UPDATE condicionado a `status='open'` es
 * idempotente: si `deletePy` sí alcanzó a borrar esas filas, no afecta a
 * ninguna. Ídem para la convocatoria (sin índice único, pero
 * `public_enrollment_cohort` FALLA CERRADO con 503 si hay más de una
 * abierta).
 */
function restorePy(ctx) {
  return `
from itcj2.database import SessionLocal
from sqlalchemy import text

PREV_COHORTS = ${JSON.stringify(ctx.prevOpenCohorts || [])}
PREV_FORM = ${ctx.prevOpenFormId === null || ctx.prevOpenFormId === undefined ? 'None' : ctx.prevOpenFormId}
SCENARIO_COHORT = ${ctx.cohortId}
SCENARIO_FORM = ${ctx.formId}

db = SessionLocal()
try:
    # Idempotente y primero: si deletePy ya borró estas filas, 0 filas
    # afectadas; si deletePy falló antes de llegar a ellas, las cierra para
    # que reabrir PREV_COHORTS/PREV_FORM abajo no choque con ellas.
    db.execute(text("UPDATE titulatec_cohorts SET status='closed' "
                    "WHERE id = :c AND status='open'"), {"c": SCENARIO_COHORT})
    db.execute(text("UPDATE titulatec_survey_forms SET status='closed' "
                    "WHERE id = :f AND status='open'"), {"f": SCENARIO_FORM})

    if PREV_COHORTS:
        db.execute(text("UPDATE titulatec_cohorts SET status='open' WHERE id = ANY(:ids)"),
                   {"ids": PREV_COHORTS})
    if PREV_FORM is not None:
        db.execute(text("UPDATE titulatec_survey_forms SET status='open' WHERE id = :f"),
                   {"f": PREV_FORM})
    db.commit()
    print("E2E titulatec cleanup OK (restore)")
finally:
    db.close()
`;
}

let _ctx = null;

/** Siembra el escenario y lo memoriza para `stateFor(role)`. */
function seedScenario() {
  _ctx = JSON.parse(runInContainer(SEED_PY).trim());
  return _ctx;
}

/**
 * Borra el escenario sembrado y SIEMPRE restaura lo que `seedScenario()`
 * cerró, incluso si el borrado de datos falla a medias (hallazgo crítico de
 * revisión, Task 25 ronda 1: ver la nota junto a `deletePy`). Si
 * `runInContainer(deletePy(c))` lanza, el `finally` corre `restorePy` de
 * todos modos y luego el error original se re-lanza (JS no lo traga: un
 * `throw` dentro de `try` sobrevive a un `finally` que no lanza ni retorna).
 */
function cleanupScenario(ctx) {
  const c = ctx || _ctx;
  if (!c || !c.cohortId) return;
  _ctx = null;
  try {
    runInContainer(deletePy(c));
  } finally {
    runInContainer(restorePy(c));
  }
}

/**
 * storageState de Playwright para un ROL del escenario sembrado.
 * `stateFor('anon')` devuelve un estado vacío (sin cookie).
 */
function stateFor(role) {
  const url = new URL(process.env.E2E_BASE_URL || 'http://localhost:8080');
  if (role === 'anon') return { cookies: [], origins: [] };
  if (!_ctx) throw new Error('stateFor() antes de seedScenario()');
  const token = role === 'head' ? _ctx.headToken : _ctx.studentToken;
  if (!token) throw new Error(`stateFor("${role}"): rol desconocido`);
  return {
    cookies: [{
      name: 'itcj_token',
      value: token,
      domain: url.hostname,
      path: '/',
      httpOnly: true,
      secure: false,
      sameSite: 'Lax',
      expires: Math.floor(Date.now() / 1000) + 11 * 3600,
    }],
    origins: [],
  };
}

/** Abre o cierra la convocatoria del escenario (ventana pública, spec §6.6). */
function setCohortStatus(ctx, status) {
  runInContainer(`
from itcj2.database import SessionLocal
from sqlalchemy import text
db = SessionLocal()
try:
    db.execute(text("UPDATE titulatec_cohorts SET status = :s WHERE id = :c"),
               {"s": "${status}", "c": ${ctx.cohortId}})
    db.commit()
    print("cohort ${ctx.cohortId} -> ${status}")
finally:
    db.close()
`);
}

/**
 * Cambia `is_anonymous` del formulario del escenario (Tarea 6, añadido).
 *
 * `_requiere_sesion` (`pages/public.py`) es el único lector de esta columna:
 * con `False` (como siembra `SEED_PY`) un visitante SIN sesión rebota al
 * login antes de ver nada, que es lo que necesita `public-survey.spec.js`
 * para probar el redirect. El camino anónimo -banner persistente + borrador
 * SOLO en `localStorage`- sigue existiendo en el código para un formulario
 * que sí declare `is_anonymous=True`, y `survey-draft.spec.js` sigue
 * necesitando probarlo: sin este toggle, un anónimo contra el escenario de
 * `SEED_PY` rebotaría al login igual que uno autenticado a medias, y esa
 * spec nunca llegaría a ver el banner ni a escribir en `localStorage`.
 * Ninguna otra spec depende de `is_anonymous`: para un visitante CON sesión
 * (`stateFor('student')`/`stateFor('head')`) el valor de esta columna es
 * indiferente -`_requiere_sesion(form) and user is None` nunca es cierto si
 * `user` no es `None`-, así que este toggle no le mueve el piso a nadie más.
 */
function setFormAnonymous(ctx, isAnonymous) {
  runInContainer(`
from itcj2.database import SessionLocal
from sqlalchemy import text
db = SessionLocal()
try:
    db.execute(text("UPDATE titulatec_survey_forms SET is_anonymous = :a WHERE id = :f"),
               {"a": ${isAnonymous ? 'True' : 'False'}, "f": ${ctx.formId}})
    db.commit()
    print("form ${ctx.formId} is_anonymous -> ${isAnonymous ? 'True' : 'False'}")
finally:
    db.close()
`);
}

/**
 * Crea una solicitud en revisión, tal como la deja el formulario público.
 * Devuelve su id.
 *
 * Sin opciones (lo que ya usaban los specs): el número de control 29990777 NO
 * tiene cuenta, así que la bandeja pide NIP para crear el acceso.
 * `{ withAccount: true }`: crea antes una cuenta con contraseña para 29990778,
 * así que la bandeja la aprueba emitiendo la liga de activación, sin NIP. Las
 * dos filas caen en el borrado del escenario (`first_name = E2E_TAG` y
 * `username LIKE '2999%'`).
 */
function seedPendingRequest(ctx, { withAccount = false } = {}) {
  const control = withAccount ? '29990778' : '29990777';
  const out = runInContainer(`
from itcj2.database import SessionLocal
from itcj2.core.models.user import User
from itcj2.core.utils.security import hash_nip
from itcj2.apps.titulatec.models import EnrollmentRequest
db = SessionLocal()
try:
    if ${withAccount ? 'True' : 'False'}:
        db.add(User(first_name="${E2E_TAG}", last_name="CON CUENTA",
                    username="${control}", control_number="${control}",
                    password_hash=hash_nip("${E2E_NIP}"), is_active=True))
        db.flush()
    req = EnrollmentRequest(
        cohort_id=${ctx.cohortId}, control_number="${control}",
        first_name="EGRESADO", last_name="${E2E_TAG}",
        program_text="Ingeniería en Sistemas", phone="6560000000",
        contact_email="e2e.titulatec@example.com", has_efirma=False,
        kind="${withAccount ? 'known' : 'unknown'}", status="pending_review")
    db.add(req); db.flush()
    rid = req.id
    db.commit()
    print(rid)
finally:
    db.close()
`).trim();
  return parseInt(out, 10);
}

/** Folio del proceso de un número de control, o cadena vacía si no hay. */
function processFolioFor(ctx, controlNumber) {
  return runInContainer(`
from itcj2.database import SessionLocal
from sqlalchemy import text
db = SessionLocal()
try:
    row = db.execute(text(
        "SELECT p.folio FROM titulatec_processes p "
        "JOIN core_users u ON u.id = p.student_id "
        "WHERE u.control_number = :cn AND p.cohort_id = :c"),
        {"cn": "${controlNumber}", "c": ${ctx.cohortId}}).first()
    print(row[0] if row else "")
finally:
    db.close()
`).trim();
}

module.exports = {
  mintTokenFor,
  seedScenario,
  cleanupScenario,
  stateFor,
  setCohortStatus,
  setFormAnonymous,
  seedPendingRequest,
  processFolioFor,
  E2E_TAG,
  E2E_NIP,
};
