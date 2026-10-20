/**
 * registry.js — registro de apps del escritorio (fuente única: el servidor).
 *
 * Lee el JSON de `#desktop-apps-data` (desktop_service.build_apps_payload) y
 * resuelve a qué app pertenece una URL. Si el JSON no se puede leer, el
 * registro queda vacío: los tiles siguen visibles (los pintó el servidor) y
 * abrir una app simplemente no hace nada.
 */
(function () {
  'use strict';

  const D = window.ItcjDesktop = window.ItcjDesktop || {};

  function readApps() {
    const el = document.getElementById('desktop-apps-data');
    if (!el) {
      console.error('[ItcjDesktop] falta #desktop-apps-data');
      return [];
    }
    try {
      const data = JSON.parse(el.textContent || '[]');
      return Array.isArray(data) ? data.filter((a) => a && typeof a.key === 'string') : [];
    } catch (err) {
      console.error('[ItcjDesktop] registro de apps ilegible:', err);
      return [];
    }
  }

  /**
   * URL → {key, url} con la app dueña (prefijo más largo) y la URL relativa al
   * origen. Solo rutas relativas o del mismo origen, esquema http/https; todo lo
   * demás (otro origen, `//host`, `javascript:`, `data:`) → null.
   */
  function makeResolver(apps) {
    const prefixes = [];
    apps.forEach((app) => {
      (Array.isArray(app.prefixes) ? app.prefixes : []).forEach((p) => {
        if (typeof p === 'string' && p.startsWith('/')) prefixes.push({ key: app.key, prefix: p.replace(/\/+$/, '') });
      });
    });
    prefixes.sort((a, b) => b.prefix.length - a.prefix.length);

    return function resolve(url) {
      if (typeof url !== 'string') return null;
      const raw = url.trim();
      if (!raw) return null;
      let u;
      try {
        u = new URL(raw, window.location.origin + '/');
      } catch (err) {
        return null;
      }
      if (u.protocol !== 'http:' && u.protocol !== 'https:') return null;
      if (u.origin !== window.location.origin) return null;
      const path = u.pathname;
      const hit = prefixes.find((p) => path === p.prefix || path.startsWith(p.prefix + '/'));
      if (!hit) return null;
      return { key: hit.key, url: u.pathname + u.search + u.hash };
    };
  }

  D.createRegistry = function createRegistry() {
    const apps = readApps();
    const byKey = new Map(apps.map((a) => [a.key, a]));
    return {
      all: () => apps.slice(),
      get: (key) => byKey.get(key) || null,
      resolve: makeResolver(apps)
    };
  };

  // El JSON ya está en el DOM cuando corren los scripts `defer`: el registro
  // existe desde aquí para cualquier módulo que lo pida antes de boot.js.
  D.registry = D.createRegistry();
})();
