/**
 * session.js — persistencia del escritorio (`ItcjDesktop.session`).
 *
 * - Geometría por app (localStorage `itcj.desktop.geom.v1`, no sensible):
 *   `{key: {x, y, w, h}}` en % del área útil, así sobrevive a cambios de
 *   resolución. La escribe el gestor de ventanas al terminar un arrastre o una
 *   redimensión en estado normal; `open()` sin estado la usa.
 * - Sesión de ventanas (sessionStorage `itcj.desktop.session.v1:{uid}`):
 *   `[{key, url, state, base, z, rect}]` (rect en %), guardada en cada evento
 *   `desktop:window-*` y al salir de la página. `restore()` la reabre al
 *   arrancar (boot.js la llama antes de quitar el splash) en orden de z, sin
 *   animación y con su estado (minimizada incluida).
 * - `clear()` (logout) borra la sesión y deja de escribirla en esta página.
 *
 * Sin uid no se guarda ni se restaura. Storage bloqueado o JSON roto → el
 * escritorio arranca normal, sin persistencia. La sesión es entrada no
 * confiable: solo se reabren apps del registro con una URL que el registro
 * resuelve a esa misma app (mismo origen, http/https); el resto se ignora.
 */
(function () {
  'use strict';

  const D = window.ItcjDesktop = window.ItcjDesktop || {};

  const GEOM_KEY = 'itcj.desktop.geom.v1';
  const SESSION_PREFIX = 'itcj.desktop.session.v1:';
  const MAX_WINDOWS = 20;
  const STATES = ['normal', 'maximized', 'snap-left', 'snap-right'];
  const SAVE_ON = ['opened', 'closed', 'navigated', 'state', 'focused', 'minimized', 'restored', 'moved'];

  let restoring = false;   // durante restore() no se guarda a medias
  let restored = false;    // restore() corre una sola vez
  let disabled = false;    // tras clear() (logout) no se vuelve a escribir
  let pending = false;

  // === STORAGE (todo en try/catch: modo privado, cookies bloqueadas, cuota) ===

  function storage(kind) {
    try {
      return kind === 'local' ? window.localStorage : window.sessionStorage;
    } catch (err) {
      return null;
    }
  }

  /** JSON guardado; null si no hay o no hay storage; undefined si está roto. */
  function readJson(store, key) {
    if (!store) return null;
    let raw;
    try { raw = store.getItem(key); } catch (err) { return null; }
    if (!raw) return null;
    try { return JSON.parse(raw); } catch (err) { return undefined; }
  }

  function writeJson(store, key, value) {
    if (!store) return;
    try { store.setItem(key, JSON.stringify(value)); } catch (err) { /* cuota o bloqueado */ }
  }

  function remove(store, key) {
    if (!store || !key) return;
    try { store.removeItem(key); } catch (err) { /* bloqueado */ }
  }

  const isPlainObject = (v) => !!v && typeof v === 'object' && !Array.isArray(v);

  function sessionKey() {
    const id = D.user && D.user.id != null ? String(D.user.id).trim() : '';
    return id ? SESSION_PREFIX + id : null;
  }

  /** Rect en % validado: números finitos, tamaño positivo y razonable; si no, null. */
  function cleanPct(rect) {
    if (!isPlainObject(rect)) return null;
    const out = {};
    for (const k of ['x', 'y', 'w', 'h']) {
      if (typeof rect[k] !== 'number' || !Number.isFinite(rect[k])) return null;
      out[k] = Math.round(rect[k] * 100) / 100;
    }
    const ok = out.w > 0 && out.w <= 101 && out.h > 0 && out.h <= 101 &&
      Math.abs(out.x) <= 200 && Math.abs(out.y) <= 200;
    return ok ? out : null;
  }

  // === GEOMETRÍA POR APP ===

  function loadGeometry(key) {
    if (typeof key !== 'string' || !key) return null;
    const map = readJson(storage('local'), GEOM_KEY);
    if (!isPlainObject(map) || !Object.prototype.hasOwnProperty.call(map, key)) return null;
    return cleanPct(map[key]);
  }

  function saveGeometry(key, rect) {
    const pct = cleanPct(rect);
    if (typeof key !== 'string' || !key || !pct) return;
    const store = storage('local');
    const map = readJson(store, GEOM_KEY);
    const next = isPlainObject(map) ? map : {};
    next[key] = pct;
    writeJson(store, GEOM_KEY, next);
  }

  // === SESIÓN DE VENTANAS ===

  function loadSession() {
    const key = sessionKey();
    if (!key) return [];
    const data = readJson(storage('session'), key);
    return Array.isArray(data) ? data : [];
  }

  function saveSession(list) {
    const key = sessionKey();
    if (disabled || !key) return;
    const store = storage('session');
    if (!Array.isArray(list) || !list.length) {
      remove(store, key);
      return;
    }
    writeJson(store, key, list.slice(0, MAX_WINDOWS));
  }

  function clear() {
    disabled = true;
    remove(storage('session'), sessionKey());
  }

  /** Foto de las ventanas abiertas (rect en % del área útil). */
  function snapshot() {
    const wm = D.wm;
    if (!wm || typeof wm.list !== 'function') return null;
    return wm.list().map((w) => ({
      key: w.key,
      url: w.url,
      state: w.state,
      base: w.base,
      z: w.z,
      rect: typeof wm.toPct === 'function' ? wm.toPct(w.rect) : null
    }));
  }

  function saveNow() {
    if (restoring || disabled || !sessionKey()) return;
    try {
      const list = snapshot();
      if (list) saveSession(list);
    } catch (err) { /* sin persistencia, el escritorio sigue */ }
  }

  /** Varios eventos seguidos (abrir = opened + focused + …) → una sola escritura. */
  function scheduleSave() {
    if (pending || restoring || disabled) return;
    pending = true;
    Promise.resolve().then(() => {
      pending = false;
      saveNow();
    });
  }

  /**
   * Entradas válidas, en orden de z ascendente: app del registro (sistema
   * incluido: perfil y configuración), sin repetir, y URL que el registro
   * resuelve a esa MISMA app. Sin URL → la de inicio de la app. URL de otro
   * origen, `javascript:`, de otra app o que ya no resuelve → se ignora la entrada.
   */
  function validEntries(data, registry) {
    const seen = new Set();
    const out = [];
    data.forEach((raw, i) => {
      if (!isPlainObject(raw) || typeof raw.key !== 'string' || seen.has(raw.key)) return;
      const app = registry.get(raw.key);
      if (!app) return;
      let url = app.url;
      if (raw.url != null && raw.url !== '') {
        const hit = typeof raw.url === 'string' ? registry.resolve(raw.url) : null;
        if (!hit || hit.key !== app.key) return;
        url = hit.url;
      }
      const minimized = raw.state === 'minimized';
      const wanted = minimized ? raw.base : raw.state;
      seen.add(raw.key);
      out.push({
        key: app.key,
        url,
        minimized,
        state: STATES.includes(wanted) ? wanted : 'maximized',
        rect: cleanPct(raw.rect),
        z: typeof raw.z === 'number' && Number.isFinite(raw.z) ? raw.z : i,
        i
      });
    });
    out.sort((a, b) => (a.z - b.z) || (a.i - b.i));
    return out.slice(0, MAX_WINDOWS);
  }

  /** Reabre la sesión guardada. Devuelve cuántas ventanas abrió. */
  function restore() {
    const wm = D.wm;
    const registry = D.registry;
    const key = sessionKey();
    if (restored || !wm || !registry || !key) return 0;
    restored = true;

    const store = storage('session');
    const data = readJson(store, key);
    if (data === undefined) {   // JSON roto: se descarta y se arranca limpio
      remove(store, key);
      return 0;
    }
    if (!Array.isArray(data) || !data.length) return 0;

    let opened = 0;
    restoring = true;
    try {
      validEntries(data, registry).forEach((e) => {
        try {
          const rect = e.rect ? wm.fromPct(e.rect) : null;
          const el = wm.open(e.key, { url: e.url, state: e.state, rect: rect || undefined, focus: false, animate: false });
          if (!el) return;
          opened += 1;
          if (e.minimized) wm.open(e.key, { state: 'minimized', focus: false });   // sin animación
        } catch (err) {
          console.warn('[ItcjDesktop] no se pudo restaurar la ventana', e.key, err);
        }
      });
      // La de mayor z no minimizada queda al frente (abrir en orden ya la deja ahí).
      const top = wm.list().filter((w) => w.state !== 'minimized').pop();
      if (top && wm.activeKey() !== top.key) wm.focus(top.key);
    } finally {
      restoring = false;
    }
    saveNow();
    return opened;
  }

  // === ESCUCHAS ===
  SAVE_ON.forEach((n) => document.addEventListener('desktop:window-' + n, scheduleSave));
  // Al salir (recargar incluido) se guarda la foto final: posiciones reacomodadas, etc.
  window.addEventListener('pagehide', saveNow);

  D.session = { loadGeometry, saveGeometry, loadSession, saveSession, clear, restore };
})();
