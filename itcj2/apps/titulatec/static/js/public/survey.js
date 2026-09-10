/* ===========================================================================
   TitulaTec — encuesta pública: borrador local + autosave al servidor.
   ---------------------------------------------------------------------------
   Tres trabajos:
     1. `localStorage` en cada cambio. Coste de red: cero.
     2. Autosave al servidor SOLO con sesión: debounce de 5 s, techo duro de una
        petición cada 30 s, flush al cambiar de sección y al salir de la página.
     3. `visible_when` en cliente. El servidor lo vuelve a evaluar (§4.3.5): el
        cliente de un formulario público está bajo control de quien lo abre.

   CONTRATO DE REGISTRO — leerlo antes de tocar nada:
     · el módulo se carga UNA vez desde el bloque `scripts` de la página;
     · todos los escuchas se registran a nivel de módulo y DELEGAN en `document`;
     · `htmx:afterSettle` NO registra nada: solo llama a `hydrate()`, que lee el
       DOM. Volver a registrar ahí multiplicaría las escrituras sin romper
       ninguna prueba de servidor — por eso el presupuesto se mide en E2E;
     · PROHIBIDO `data-tt-bound`: Idiomorph sincroniza atributos y lo borraría,
       con lo que el guard dejaría de guardar nada.
   =========================================================================== */
(function () {
  'use strict';

  var DEBOUNCE_MS = 5000;       // DRAFT_DEBOUNCE_MS del contrato
  var MIN_INTERVAL_MS = 30000;  // DRAFT_MIN_INTERVAL_MS del contrato

  var debounceTimer = null;
  var ceilingTimer = null;
  var lastSentAt = 0;
  var dirty = false;
  var lastSection = null;

  function formEl() { return document.getElementById('tt-survey-form'); }
  function isAuthed(f) { return f.dataset.ttAuth === '1'; }
  function storageKey(f) {
    return 'tt.survey.' + f.dataset.ttSurvey + '.v' + f.dataset.ttVersion;
  }

  // — Instantánea del formulario ———————————————————————————————————————
  function snapshot(f) {
    var out = {};
    new FormData(f).forEach(function (value, key) {
      if (key === 'website') return;              // la trampa nunca se guarda
      if (Object.prototype.hasOwnProperty.call(out, key)) {
        if (!Array.isArray(out[key])) out[key] = [out[key]];
        out[key].push(value);
      } else {
        out[key] = value;
      }
    });
    return out;
  }

  // — localStorage ————————————————————————————————————————————————————
  // UNA marca de tiempo para TODO el borrador, no por campo: la fusión de 6.5
  // es "el más nuevo gana entero", que es lo que un humano espera al volver.
  function saveLocal(f) {
    try {
      localStorage.setItem(storageKey(f), JSON.stringify({ t: Date.now(), a: snapshot(f) }));
    } catch (e) { /* modo privado o cuota llena: el borrador local es un extra */ }
  }
  function readLocal(f) {
    try {
      var raw = localStorage.getItem(storageKey(f));
      return raw ? JSON.parse(raw) : null;
    } catch (e) { return null; }
  }
  function clearLocal(f) {
    try { localStorage.removeItem(storageKey(f)); } catch (e) {}
  }

  // — Escritura al servidor ———————————————————————————————————————————
  // `fetch(..., {keepalive:true})` con `FormData`, NUNCA `navigator.sendBeacon`
  // con un Blob JSON: el endpoint hace `await request.form()` como los otros 15
  // POST de la app y no sabría parsear `application/json`. `keepalive` sobrevive
  // a la navegación igual que sendBeacon y sí permite tipo de formulario.
  function send(f, keepalive) {
    lastSentAt = Date.now();
    dirty = false;
    var body = new FormData(f);
    body.delete('website');
    fetch(f.dataset.ttDraftUrl, {
      method: 'POST',
      body: body,
      credentials: 'same-origin',
      keepalive: !!keepalive
    }).catch(function () { dirty = true; });
  }

  function flush(f, keepalive) {
    if (!f || !isAuthed(f) || !dirty) return;
    var wait = MIN_INTERVAL_MS - (Date.now() - lastSentAt);
    if (keepalive || wait <= 0) { send(f, keepalive); return; }
    if (ceilingTimer) return;                     // ya hay una salida programada
    ceilingTimer = setTimeout(function () {
      ceilingTimer = null;
      var cur = formEl();
      if (cur && dirty) send(cur, false);
    }, wait);
  }

  function scheduleDebounced() {
    if (debounceTimer) clearTimeout(debounceTimer);
    debounceTimer = setTimeout(function () {
      debounceTimer = null;
      flush(formEl(), false);
    }, DEBOUNCE_MS);
  }

  // — visible_when en cliente ——————————————————————————————————————————
  function applyVisibility(f) {
    var values = snapshot(f);
    f.querySelectorAll('[data-tt-when]').forEach(function (box) {
      var cond;
      try { cond = JSON.parse(box.getAttribute('data-tt-when')); } catch (e) { return; }
      box.hidden = !Object.keys(cond).every(function (k) { return values[k] === cond[k]; });
    });
  }

  // — Fusión del borrador local con el del servidor (6.5) ————————————————
  function applyValues(f, values) {
    Object.keys(values).forEach(function (key) {
      var wanted = values[key];
      var list = (Array.isArray(wanted) ? wanted : [wanted]).map(String);
      var nodes = f.querySelectorAll('[name="' + CSS.escape(key) + '"]');
      nodes.forEach(function (node) {
        if (node.type === 'checkbox' || node.type === 'radio') {
          node.checked = list.indexOf(node.value) !== -1;
        } else if (nodes.length === 1) {
          node.value = list[0];
        }
      });
    });
  }

  function mergeLocalDraft(f) {
    var local = readLocal(f);
    if (!local || !local.a) return;
    var serverAt = Date.parse(f.dataset.ttDraftUpdated || '') || 0;
    if (local.t > serverAt) {
      applyValues(f, local.a);
      dirty = true;
      // El local ganó: hay que subirlo, pero SIN saltarse el techo de 30 s.
      // `send()` directo aquí (como en la primera versión de este módulo)
      // reabre exactamente el agujero que el techo existe para cerrar: cada
      // POST fallido re-renderiza `#tt-survey-form` con
      // `data-tt-draft-updated=""` (`_form_ctx` no lo hereda en la rama de
      // error), así que `serverAt` vuelve a 0 en cada `htmx:afterSettle` y
      // esta rama se dispara EN CADA intento fallido, no solo al recuperar
      // sesión una vez. Con `send()` a secas, una racha de erratas de un
      // alumno autenticado manda un POST de borrador por cada una, sin
      // importar cuán seguido — justo las "2 escrituras por minuto" que D3
      // prohíbe. `flush()` conserva el "sube ya" para el caso normal
      // (primera fusión de la sesión: `lastSentAt` sigue en 0 y el techo ya
      // está vencido) y respeta la espera en las repeticiones.
      if (isAuthed(f)) flush(f, false);
    }
    clearLocal(f);
  }

  function focusFirstInvalid(f) {
    var el = f.querySelector('[data-tt-focus]');
    if (el && typeof el.focus === 'function') el.focus();
  }

  // `hydrate` solo LEE el DOM. No registra ni un escucha: es lo que la hace
  // segura de llamar en cada `htmx:afterSettle`.
  function hydrate() {
    var f = formEl();
    if (!f) return;
    mergeLocalDraft(f);
    applyVisibility(f);
    focusFirstInvalid(f);
    lastSection = null;
  }

  // — Escuchas: se registran UNA vez, delegando en `document` ——————————
  function onEdit(e) {
    var f = formEl();
    if (!f || !f.contains(e.target)) return;
    dirty = true;
    saveLocal(f);
    applyVisibility(f);
    scheduleDebounced();
  }
  document.addEventListener('input', onEdit);
  document.addEventListener('change', onEdit);

  // Cambio de sección: flush inmediato, pero sujeto al techo de 30 s. Por eso
  // el E2E exige "al menos una" petición y no "exactamente una": si coincide
  // con el techo, la petición se agenda en vez de salir, y exigir un número
  // exacto haría la prueba inestable.
  document.addEventListener('focusin', function (e) {
    var f = formEl();
    if (!f || !f.contains(e.target)) return;
    var sec = e.target.closest('[data-tt-section]');
    var key = sec ? sec.getAttribute('data-tt-section') : null;
    if (lastSection !== null && key !== lastSection) flush(f, false);
    lastSection = key;
  });

  // Salida de la página: última oportunidad, ignora el techo.
  function onLeave() {
    var f = formEl();
    if (!f) return;
    saveLocal(f);
    flush(f, true);
  }
  document.addEventListener('visibilitychange', function () {
    if (document.visibilityState === 'hidden') onLeave();
  });
  window.addEventListener('pagehide', onLeave);

  // "Iniciar sesión y continuar": se persiste antes de navegar. El `href` ya
  // lleva `?next=/titulatec/encuesta-egresados`, que `core/pages/auth.py` honra.
  document.addEventListener('click', function (e) {
    var link = e.target.closest && e.target.closest('[data-tt-login]');
    if (!link) return;
    var f = formEl();
    if (f) saveLocal(f);
  });

  document.addEventListener('htmx:afterSettle', hydrate);
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', hydrate);
  } else {
    hydrate();
  }
})();
