/**
 * icons.js — base del escritorio: iconos del sprite, escape de HTML y usuario.
 *
 * Primer módulo de `window.ItcjDesktop` (los demás lo extienden). El sprite vive
 * inline en la página (core/dashboard/_icons.html) y reemplaza a lucide.
 */
(function () {
  'use strict';

  const D = window.ItcjDesktop = window.ItcjDesktop || {};

  function escapeHtml(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  /** `<svg class="ico {cls}"><use href="#i-{name}"/></svg>` (nombre y clase escapados). */
  function icon(name, cls) {
    const klass = ('ico ' + (cls || '')).trim();
    return '<svg class="' + escapeHtml(klass) + '" aria-hidden="true"><use href="#i-' +
      escapeHtml(name) + '"/></svg>';
  }

  /** Icono de una app del registro: su imagen optimizada o, si no tiene, el glifo. */
  function appIcon(app, size, cls) {
    if (!app) return icon('grid', cls);
    if (app.image) {
      const px = parseInt(size, 10) || 24;
      return '<img src="' + escapeHtml(app.image) + '" alt="" width="' + px + '" height="' + px +
        '" decoding="async" draggable="false"' + (cls ? ' class="' + escapeHtml(cls) + '"' : '') + '>';
    }
    return icon(app.icon || 'grid', cls);
  }

  D.escapeHtml = escapeHtml;
  D.icon = icon;
  D.appIcon = appIcon;

  // Usuario de la sesión (lo pone el servidor en <body>).
  const body = document.body;
  D.user = {
    id: body ? (body.getAttribute('data-user-id') || '') : '',
    name: body ? (body.getAttribute('data-user-name') || '') : ''
  };
})();
