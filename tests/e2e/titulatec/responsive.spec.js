// @ts-check
/**
 * Invariante responsive de la página pública de la encuesta — Tarea 6:
 * reescrito para el asistente por pasos, contra el INSTRUMENTO REAL.
 *
 * Dos aserciones distintas, porque una sola no basta:
 *
 *  1. `document.documentElement.scrollWidth <= window.innerWidth` en los SEIS
 *     viewports de la matriz del proyecto (`itcj2/apps/titulatec/docs/design/
 *     responsive.md`). Detecta desbordamiento horizontal.
 *  2. A 1440 y 1920, el ancho del TEXTO de la primera pregunta del paso. El
 *     invariante de (1) no detecta el estiramiento; `.tt-public-main.tt-prose`
 *     (Tarea 11) es lo que lo evita.
 *
 * QUÉ CAMBIÓ (Tarea 6) y POR QUÉ ESTE ARCHIVO YA NO USA `seedScenario()`.
 * Antes la encuesta era una sola pantalla y esta prueba corría sin sesión
 * contra lo que hubiera abierto en dev. Ahora: (a) el formulario real
 * (`egresados` v1) exige sesión -`is_anonymous=False`-, y (b) se recorre por
 * PASOS, así que "no desborda" hay que medirlo EN CADA PASO, no en una sola
 * pantalla (brief de la Tarea 6). `seedScenario()` sirve para probar el
 * MECANISMO (así lo usan `public-survey.spec.js`/`survey-draft*.spec.js`),
 * pero **cierra el formulario real del DML y abre su propio sintético en su
 * lugar** (`_helpers.js`): usarlo aquí dejaría esta prueba midiendo un
 * formulario de juguete de 3 secciones, justo cuando esta es la ÚNICA spec
 * de las cuatro para la que el tamaño REAL importa (63 campos, 7 secciones,
 * una de ellas -`especialidad`- con 48 opciones). Por eso este archivo:
 *   - NO llama a `seedScenario()`: el 'egresados' real se queda abierto todo
 *     el tiempo. Solo siembra un usuario mínimo y propio (con sesión, porque
 *     el real ya no admite nada sin ella) y un borrador de servidor para ESE
 *     usuario -nunca toca `titulatec_survey_forms` ni ninguna otra tabla
 *     compartida-.
 *   - Recorre los 7 pasos sembrando el BORRADOR directo en BD (vía
 *     `SurveyService.save_draft`, el mismo camino que ya usa el autosave)
 *     en vez de rellenar 63 campos en el navegador: `_start_step`
 *     (`pages/public.py`) reanuda en el primer paso con un obligatorio
 *     VISIBLE sin contestar, así que sembrar "ya contestado hasta antes del
 *     paso K" aterriza el GET exactamente en el paso K, sin un solo click.
 *     Rápido y determinista; recorrer 63 campos por click no lo sería
 *     (frágil ante cualquier reordenamiento del DML) y no mide nada que este
 *     enfoque no mida ya -lo que aquí importa es el LAYOUT renderizado de
 *     cada sección, no si el mecanismo de avance funciona (eso ya lo cubren
 *     las otras tres specs contra el escenario sintético).
 *   - Las respuestas "de relleno" evitan a propósito activar ninguna sección
 *     condicional extra (`actividad_actual` -> "No estudia, ni trabaja",
 *     `domina_otro_idioma`/`empresa_propia` -> "No"): la MERA PRESENCIA de
 *     esos campos condicionales ya se ejerce en el paso donde viven
 *     (`ubicacion_laboral`), y activarlos en cascada no aportaría otra cosa
 *     que más campos que rellenar con el mismo valor de relleno.
 *
 * Sin `seedScenario()`/`cleanupScenario()`: nada que restaurar en
 * `titulatec_survey_forms` ni `titulatec_cohorts`. El `afterAll` borra
 * exactamente las tres filas propias (el borrador, el perfil de alumno que
 * `StudentProfileService.get_or_create` crea de paso en el primer GET, y el
 * usuario), por id -no por búsqueda de patrón-, así que no hay nada que
 * pueda dejar al 'egresados' real en un estado distinto al que tenía.
 *
 * `storageState: { cookies: [], origins: [] } }`, NUNCA `storageState:
 * undefined` (ver `_helpers.js`/`public-survey.spec.js`): en Playwright 1.61
 * un `undefined` es un no-op y heredaría el storageState global del proyecto
 * (admin de helpdesk). Aquí la cookie real se agrega por test con
 * `context.addCookies(...)`, así que este `test.use` es la línea base
 * defensiva, igual que en el resto de la carpeta.
 */
const { test, expect } = require('@playwright/test');
const { execFileSync } = require('child_process');
const { mintTokenFor } = require('./_helpers');

test.use({ storageState: { cookies: [], origins: [] } });

const BACKEND_CONTAINER = process.env.E2E_BACKEND_CONTAINER || 'itcj-backend-1';
const SURVEY_URL = '/titulatec/encuesta-egresados';
const TAG = 'E2E_TITULATEC_RESPONSIVE';

/** Corre Python dentro del contenedor y devuelve su stdout (idéntico a `_helpers.js`). */
function runInContainer(py, { timeout = 60_000 } = {}) {
  return execFileSync(
    'docker',
    ['exec', '-i', BACKEND_CONTAINER, 'python', '-c', py],
    { stdio: ['ignore', 'pipe', 'inherit'], encoding: 'utf8', timeout }
  );
}

// Matriz del proyecto. No inventar otra.
const MATRIZ = [
  { w: 360, h: 740, perfil: 'móvil chico' },
  { w: 390, h: 844, perfil: 'móvil de referencia' },
  { w: 768, h: 1024, perfil: 'tablet vertical' },
  { w: 1280, h: 800, perfil: 'laptop' },
  { w: 1440, h: 900, perfil: 'escritorio común' },
  { w: 1920, h: 1080, perfil: 'monitor grande' },
];

// El tope real es 60ch (`.tt-public-main.tt-prose`, public.css), que con la
// tipografía de la app ronda 600 px. 800 deja holgura y sigue reprobando
// cualquier caja full-bleed (>=1300).
const MAX_PROSA_PX = 800;

// ---------------------------------------------------------------------------
// Deriva, del ESQUEMA REAL, una respuesta "de relleno" válida y mínima por
// campo obligatorio, evitando a propósito disparar secciones condicionales
// extra (ver el encabezado). Puro cálculo en JS sobre el JSON del esquema:
// nada de esto escribe en la base todavía.
// ---------------------------------------------------------------------------
function elegirValor(field, avoid) {
  const t = field.type;
  if (t === 'radio' || t === 'select') {
    const opciones = (field.options || []).map((o) => String(o.value));
    const evitar = avoid.get(field.key) || new Set();
    const buena = opciones.find((v) => !evitar.has(v));
    return buena !== undefined ? buena : opciones[0];
  }
  if (t === 'scale') {
    const bloque = field.scale || {};
    return String(bloque.min != null ? bloque.min : 1);
  }
  if (t === 'text' || t === 'textarea') {
    const maxLen = (field.validation && field.validation.maxLength) || 50;
    return 'E2E prueba responsive'.slice(0, maxLen);
  }
  if (t === 'yesno') return 'si';
  if (t === 'checkbox') return true;
  if (t === 'multiselect') {
    const opciones = (field.options || []).map((o) => String(o.value));
    return opciones.length ? [opciones[0]] : [];
  }
  return '';
}

function esVisible(field, respuestas) {
  const vw = field.visible_when;
  if (!vw) return true;
  return Object.keys(vw).every((k) => {
    const esperado = vw[k];
    const valor = respuestas[k];
    return Array.isArray(esperado) ? esperado.includes(valor) : valor === esperado;
  });
}

/**
 * Agrupa `fields` por sección preservando el orden de `schema.sections`,
 * igual que `_sections()` en `pages/public.py` (una `_` suelta al final para
 * campos sin sección declarada -no debería ocurrir en el esquema real, pero
 * replicarlo evita que este cálculo divergiera en silencio si algún día sí
 * ocurriera). Devuelve `{ pasos, cum }`:
 *   - `pasos[k]`: `{ key, title, fields }` del paso k.
 *   - `cum[k]`: respuestas acumuladas de TODAS las secciones ANTERIORES al
 *     paso k -sembrar esto es lo que hace que `_start_step` aterrice justo
 *     en el paso k-.
 */
function derivarPasosYAcumulados(schema) {
  const secciones = (schema.sections || []).filter((s) => s && s.key);
  const porClave = new Map(secciones.map((s) => [s.key, []]));
  const sueltos = [];
  for (const f of schema.fields || []) {
    if (!f || !f.key) continue;
    if (porClave.has(f.section)) porClave.get(f.section).push(f);
    else sueltos.push(f);
  }
  const pasos = secciones
    .map((s) => ({ key: s.key, title: s.title || s.key, fields: porClave.get(s.key) }))
    .filter((p) => p.fields.length);
  if (sueltos.length) pasos.push({ key: '_', title: '', fields: sueltos });

  // avoid.get(key) = valores que ALGÚN OTRO campo usa como gatillo de
  // `visible_when` contra `key`: elegir cualquier otro valor mantiene esa
  // sección condicional cerrada.
  const avoid = new Map();
  for (const f of schema.fields || []) {
    if (!f.visible_when) continue;
    for (const [src, esperado] of Object.entries(f.visible_when)) {
      const vals = Array.isArray(esperado) ? esperado : [esperado];
      if (!avoid.has(src)) avoid.set(src, new Set());
      vals.forEach((v) => avoid.get(src).add(String(v)));
    }
  }

  const cum = [];
  const respuestas = {};
  for (const paso of pasos) {
    cum.push({ ...respuestas });
    for (const f of paso.fields) {
      if (!f.required || !esVisible(f, respuestas)) continue;
      respuestas[f.key] = elegirValor(f, avoid);
    }
  }
  return { pasos, cum };
}

// Esquema del 'egresados' REAL abierto en dev, leído UNA vez al cargar este
// archivo (síncrono, de solo lectura -no siembra nada todavía-): de aquí
// sale cuántos `test()` generar, uno por paso. Igual de determinista que la
// `MATRIZ` de arriba; solo que en vez de un literal se lee del esquema real,
// que es justo lo que esta spec existe para ejercer.
const _esquema = JSON.parse(runInContainer(`
import json
from itcj2.database import SessionLocal
from itcj2.apps.titulatec.models import SurveyForm
db = SessionLocal()
try:
    f = db.query(SurveyForm).filter_by(code="egresados", status="open").order_by(SurveyForm.version.desc()).first()
    if f is None:
        raise SystemExit("no hay un formulario 'egresados' abierto en dev")
    print(json.dumps({"formId": f.id, "schema": f.schema or {}}))
finally:
    db.close()
`).trim());

const FORM_ID = _esquema.formId;
const { pasos: PASOS, cum: CUM } = derivarPasosYAcumulados(_esquema.schema);

let userId;
let token;

test.beforeAll(() => {
  // Usuario mínimo, sin puesto ni rol de ninguna app: esta ruta no lleva
  // `require_page_app` (es la única de toda la app que no lo lleva -ver
  // `pages/public.py`-), así que lo único que hace falta para verla es
  // sesión, no permisos.
  userId = parseInt(runInContainer(`
from itcj2.database import SessionLocal
from itcj2.core.models.user import User
db = SessionLocal()
try:
    u = User(first_name="${TAG}", last_name="RESPONSIVE",
             username="${TAG.toLowerCase()}", is_active=True)
    db.add(u); db.commit()
    print(u.id)
finally:
    db.close()
`).trim(), 10);
  token = mintTokenFor(userId);
});

test.afterAll(() => {
  if (!userId) return;
  runInContainer(`
from itcj2.database import SessionLocal
from sqlalchemy import text
db = SessionLocal()
try:
    db.execute(text("DELETE FROM titulatec_survey_drafts WHERE form_id = :f AND user_id = :u"),
               {"f": ${FORM_ID}, "u": ${userId}})
    db.execute(text("DELETE FROM core_student_profile WHERE user_id = :u"), {"u": ${userId}})
    db.execute(text("DELETE FROM core_notifications WHERE user_id = :u"), {"u": ${userId}})
    db.execute(text("DELETE FROM core_users WHERE id = :u"), {"u": ${userId}})
    db.commit()
    print("responsive.spec.js afterAll OK (usuario ${userId} y su borrador borrados)")
finally:
    db.close()
`);
});

/** Siembra, vía `SurveyService.save_draft` (el mismo camino que el autosave real), las respuestas acumuladas hasta ANTES del paso `k`. */
function sembrarBorrador(k) {
  runInContainer(`
from itcj2.database import SessionLocal
from itcj2.apps.titulatec.services.survey_service import SurveyService
db = SessionLocal()
try:
    SurveyService.save_draft(db, ${FORM_ID}, ${userId}, ${JSON.stringify(CUM[k])})
finally:
    db.close()
`);
}

async function conSesion(page) {
  const url = new URL(process.env.E2E_BASE_URL || 'http://localhost:8080');
  await page.context().addCookies([{
    name: 'itcj_token', value: token, domain: url.hostname, path: '/',
    httpOnly: true, secure: false, sameSite: 'Lax',
    expires: Math.floor(Date.now() / 1000) + 3600,
  }]);
}

PASOS.forEach((paso, k) => {
  test(`la encuesta no desborda en el paso ${k + 1} de ${PASOS.length} (${paso.title})`, async ({ page }) => {
    sembrarBorrador(k);
    await conSesion(page);

    for (const { w, h, perfil } of MATRIZ) {
      await page.setViewportSize({ width: w, height: h });
      await page.goto(SURVEY_URL, { waitUntil: 'domcontentloaded' });
      await expect(page.locator('main[data-tt-page="public_survey"]')).toBeVisible();
      // Confirma que de verdad aterrizamos en el paso sembrado, no en otro:
      // si `_start_step` cambiara de criterio, mejor que la spec lo grite
      // aquí en vez de medir el layout de un paso distinto en silencio.
      await expect(page.getByText(`Paso ${k + 1} de ${PASOS.length}`)).toBeVisible();

      const medida = await page.evaluate(() => ({
        scrollWidth: document.documentElement.scrollWidth,
        innerWidth: window.innerWidth,
      }));
      expect(
        medida.scrollWidth,
        `desborde horizontal a ${w}px (paso "${paso.title}", ${perfil}): ` +
          `scrollWidth ${medida.scrollWidth} > innerWidth ${medida.innerWidth}`
      ).toBeLessThanOrEqual(medida.innerWidth);
    }
  });

  test(`el texto de las preguntas del paso ${k + 1} (${paso.title}) está acotado en pantallas grandes (no se estira)`, async ({ page }) => {
    sembrarBorrador(k);
    await conSesion(page);

    // La primera VISIBLE, no la primera declarada: alguna sección real tiene
    // su primer campo condicionado (p.ej. "desempeno": `calif_formacion_
    // academica` solo aparece si `actividad_actual` es Trabaja/Estudia y
    // trabaja, y las respuestas de relleno de este archivo evitan a propósito
    // esas ramas -ver el encabezado-, así que ese campo nunca se pinta aquí).
    const visible = paso.fields.find((f) => esVisible(f, CUM[k]));
    expect(visible, `el paso "${paso.title}" no tiene ningún campo visible con el relleno sembrado`).toBeTruthy();
    const primeraPregunta = visible.label;
    for (const { w, h } of MATRIZ.filter((v) => v.w >= 1440)) {
      await page.setViewportSize({ width: w, height: h });
      await page.goto(SURVEY_URL, { waitUntil: 'domcontentloaded' });
      await expect(page.getByText(`Paso ${k + 1} de ${PASOS.length}`)).toBeVisible();

      // Sin `exact: true`: un campo obligatorio pinta el `*` de `.tt-req`
      // como un <span> HERMANO dentro del mismo `.tt-label` (`tt_field` en
      // `survey_form.html`), así que el texto normalizado del bloque es
      // "<label> *", no el label a secas -y con `exact` nunca casaría-.
      const caja = await page.getByText(primeraPregunta).first().boundingBox();
      expect(caja, `no se encontró "${primeraPregunta}" en el paso "${paso.title}"`).not.toBeNull();
      expect(
        Math.round(caja.width),
        `la pregunta mide ${Math.round(caja.width)}px a ${w}px de ventana (paso "${paso.title}"): ` +
          'la base pública no está optando por .tt-prose (max-width: 48ch)'
      ).toBeLessThanOrEqual(MAX_PROSA_PX);
    }
  });
});
