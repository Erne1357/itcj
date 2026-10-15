/**
 * session.js — STUB de la Task 2. La Task 3 implementa la persistencia real:
 * geometría por app (localStorage `itcj.desktop.geom.v1`), sesión de ventanas
 * (sessionStorage `itcj.desktop.session.v1:{uid}`) y `restore()`, que boot.js
 * llama con `ItcjDesktop.session.restore?.()` si existe.
 *
 * Mientras tanto la API del contrato existe y no hace nada: nada se recuerda.
 */
(function () {
  'use strict';

  const D = window.ItcjDesktop = window.ItcjDesktop || {};

  D.session = {
    loadGeometry: function () { return null; },
    saveGeometry: function () {},
    loadSession: function () { return []; },
    saveSession: function () {},
    clear: function () {}
  };
})();
