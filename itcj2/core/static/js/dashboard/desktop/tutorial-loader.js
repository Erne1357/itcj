/**
 * tutorial-loader.js — carga bajo demanda del tutorial (`ItcjDesktop.tutorial`).
 *
 * Shepherd 11.2.0 (CSS + JS del CDN) y dashboard_tutorial.js (URL versionada en
 * `#dashboardTutorialButton[data-tutorial-src]`) NO viajan con la página: se
 * descargan una sola vez (promesa cacheada) cuando el usuario pulsa "Tutorial"
 * o, en la primera visita, tras `load` + un respiro de inactividad.
 *
 * API: `ItcjDesktop.tutorial = { init(), start() }`.
 *  - init():  boot.js lo llama; enlaza el botón y programa el auto-inicio si
 *             `localStorage['dashboard_tutorial_completed'] !== 'true'`.
 *  - start(): carga lo necesario y abre el modal de confirmación del tour.
 */
(function () {
  'use strict';

  const D = window.ItcjDesktop = window.ItcjDesktop || {};

  const STORAGE_KEY = 'dashboard_tutorial_completed';
  const SHEPHERD_CSS = 'https://cdn.jsdelivr.net/npm/shepherd.js@11.2.0/dist/css/shepherd.css';
  const SHEPHERD_JS = 'https://cdn.jsdelivr.net/npm/shepherd.js@11.2.0/dist/js/shepherd.min.js';
  const AUTO_DELAY_MS = 1500;

  let loadPromise = null;
  let bound = false;

  function isCompleted() {
    try {
      return localStorage.getItem(STORAGE_KEY) === 'true';
    } catch (err) {
      return false;
    }
  }

  function buttonEl() {
    return document.getElementById('dashboardTutorialButton');
  }

  function loadScript(src) {
    return new Promise((resolve, reject) => {
      const el = document.createElement('script');
      el.src = src;
      el.async = true;
      el.onload = () => resolve();
      el.onerror = () => reject(new Error('No se pudo cargar ' + src));
      document.head.appendChild(el);
    });
  }

  /** El CSS de Shepherd va ANTES de dashboard_tutorial.css para que éste conserve la última palabra. */
  function loadShepherdCss() {
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = SHEPHERD_CSS;
    const own = document.querySelector('link[href*="dashboard_tutorial.css"]');
    if (own && own.parentNode) own.parentNode.insertBefore(link, own);
    else document.head.appendChild(link);
  }

  /** Descarga única: Shepherd (CSS+JS) y luego dashboard_tutorial.js. */
  function load() {
    if (loadPromise) return loadPromise;
    const btn = buttonEl();
    const tutorialSrc = btn && btn.getAttribute('data-tutorial-src');
    if (!tutorialSrc) return Promise.reject(new Error('Falta data-tutorial-src en el botón de tutorial'));

    loadShepherdCss();
    loadPromise = loadScript(SHEPHERD_JS)
      .then(() => loadScript(tutorialSrc))
      .then(() => {
        if (!window.DashboardTutorialEntry) throw new Error('dashboard_tutorial.js no expuso DashboardTutorialEntry');
        return window.DashboardTutorialEntry;
      })
      .catch((err) => {
        loadPromise = null; // permite reintentar
        throw err;
      });
    return loadPromise;
  }

  function start() {
    return load().then((entry) => entry.start()).catch((err) => {
      console.error('[ItcjDesktop] tutorial:', err);
    });
  }

  function autoStartWhenIdle() {
    const run = () => {
      load().then((entry) => entry.autoStart()).catch((err) => {
        console.error('[ItcjDesktop] tutorial (auto):', err);
      });
    };
    const schedule = () => {
      setTimeout(() => {
        if ('requestIdleCallback' in window) window.requestIdleCallback(run, { timeout: 3000 });
        else run();
      }, AUTO_DELAY_MS);
    };
    if (document.readyState === 'complete') schedule();
    else window.addEventListener('load', schedule, { once: true });
  }

  function init() {
    if (bound) return;
    bound = true;
    const btn = buttonEl();
    if (btn) btn.addEventListener('click', () => { start(); });
    if (!isCompleted()) autoStartWhenIdle();
  }

  D.tutorial = { init: init, start: start };
})();
