/**
 * boot.js — arranque del escritorio (último script `defer`).
 *
 * En DOMContentLoaded instancia registro, gestor de ventanas, barra y
 * cuadrícula; restaura la sesión (Task 3) e inicia menú inicio (Task 4) y
 * tutorial (Task 6) si existen; expone `window.desktop` (API pública que usan
 * el widget de notificaciones, el perfil, el tutorial y la presencia) y marca
 * `html.desktop-ready` cuando las imágenes de los tiles y el fondo están
 * decodificados (tope 3.5 s). Cada paso va aislado: si uno falla, el
 * escritorio igual queda listo y usable.
 */
(function () {
  'use strict';

  const D = window.ItcjDesktop = window.ItcjDesktop || {};
  const READY_CAP_MS = 3500;

  function step(name, fn) {
    try {
      return fn();
    } catch (err) {
      console.error('[ItcjDesktop] falló ' + name + ':', err);
      return undefined;
    }
  }

  /** Solo http(s) sale a una pestaña nueva; `javascript:`, `data:`, etc. no. */
  function isWebUrl(url) {
    try {
      const u = new URL(url, window.location.origin + '/');
      return u.protocol === 'http:' || u.protocol === 'https:';
    } catch (err) {
      return false;
    }
  }

  // === API PÚBLICA (compatibilidad con el `window.desktop` de antes) ===
  function buildPublicApi() {
    const registry = () => D.registry;
    const wm = () => D.wm;

    const api = {
      openApplication(key, opts) {
        if (!key || key === 'papelera' || !registry() || !registry().get(key) || !wm()) return null;
        return wm().open(key, opts || {});
      },

      /** URL de una app del escritorio → abre/enfoca su ventana ahí; otra → pestaña nueva. */
      openUrl(url) {
        const hit = registry() ? registry().resolve(url) : null;
        if (hit && wm()) return wm().open(hit.key, { url: hit.url });
        if (typeof url === 'string' && isWebUrl(url)) {
          window.open(url, '_blank', 'noopener');
        } else {
          console.warn('[ItcjDesktop] URL ignorada:', url);
        }
        return null;
      },

      openProfile(tab) {
        const url = tab ? '/itcj/profile?tab=' + encodeURIComponent(String(tab)) : '/itcj/profile';
        return api.openUrl(url);
      },

      getAppConfig(key) {
        const app = registry() ? registry().get(key) : null;
        if (!app) return null;
        return { name: app.name, url: app.url, iframeSrc: app.url, icon: app.icon };
      },

      closeAllWindows() {
        if (wm()) wm().closeAll();
      },

      focusApp(key) {
        if (!wm()) return false;
        if (wm().isOpen(key)) return wm().focus(key);
        return !!api.openApplication(key);
      }
    };
    return api;
  }

  // === LISTO: tiles + fondo decodificados (o tope) ===
  function decodeImg(img) {
    if (typeof img.decode === 'function') return img.decode().catch(() => undefined);
    if (img.complete) return Promise.resolve();
    return new Promise((resolve) => {
      img.addEventListener('load', resolve, { once: true });
      img.addEventListener('error', resolve, { once: true });
    });
  }

  function loadBackground() {
    const layer = document.querySelector('.desktop-background');
    const src = layer && layer.getAttribute('data-src');
    if (!src) return Promise.resolve();
    const img = new Image();
    img.src = src;
    return decodeImg(img).then(() => {
      if (img.naturalWidth > 0) {
        layer.classList.add('is-loaded');
        const desktop = document.getElementById('desktop');
        if (desktop) desktop.classList.add('is-bg-loaded');
      }
    });
  }

  function whenReady() {
    let done = false;
    const finish = () => {
      if (done) return;
      done = true;
      document.documentElement.classList.add('desktop-ready');
      document.dispatchEvent(new CustomEvent('desktop:ready'));
    };
    const tiles = Array.from(document.querySelectorAll('#desktop-grid img')).map(decodeImg);
    Promise.all(tiles.concat([loadBackground()])).then(finish, finish);
    setTimeout(finish, READY_CAP_MS);
  }

  function boot() {
    step('registro', () => { D.registry = D.registry || D.createRegistry(); });
    step('ventanas', () => { D.wm = new D.WindowManager({ registry: D.registry }); });
    step('barra', () => { D.taskbar = new D.Taskbar({ registry: D.registry, wm: D.wm }); });
    step('escritorio', () => { D.grid = new D.DesktopGrid({ wm: D.wm }); });
    window.desktop = buildPublicApi();

    step('sesión', () => { if (D.session && typeof D.session.restore === 'function') D.session.restore(); });
    step('menú inicio', () => { if (D.startMenu && typeof D.startMenu.init === 'function') D.startMenu.init(); });
    step('tutorial', () => { if (D.tutorial && typeof D.tutorial.init === 'function') D.tutorial.init(); });

    whenReady();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot, { once: true });
  } else {
    boot();
  }
})();
