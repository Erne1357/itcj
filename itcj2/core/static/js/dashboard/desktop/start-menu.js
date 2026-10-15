/**
 * start-menu.js — menú inicio y buscador de la barra.
 *
 * `ItcjDesktop.startMenu = {init(), open(mode?), close(), toggle()}`. Modo
 * 'menu' muestra la cuadrícula de apps; modo 'search' filtra (sin acentos) las
 * apps del registro con lo escrito en `#taskbarSearch`. Ctrl+K enfoca el
 * buscador (solo en el documento del escritorio, no dentro de los iframes).
 */
(function () {
  'use strict';

  const D = window.ItcjDesktop = window.ItcjDesktop || {};

  const state = { ready: false, isOpen: false, mode: 'menu', results: [], active: -1 };
  let els = {};

  function esc(v) {
    return D.escapeHtml ? D.escapeHtml(v) : String(v == null ? '' : v);
  }

  /** Minúsculas y sin diacríticos para comparar. */
  function norm(text) {
    return String(text || '').toLowerCase().normalize('NFD').replace(/\p{Diacritic}/gu, '').trim();
  }

  // === DATOS ===
  function filterApps(query) {
    const q = norm(query);
    const apps = D.registry ? D.registry.all() : [];
    return apps.filter((app) => !q || norm(app.name).includes(q));
  }

  // === RENDER ===
  function renderResults() {
    state.results = filterApps(els.search ? els.search.value : '');
    if (state.active >= state.results.length) state.active = state.results.length - 1;
    if (state.active < 0 && state.results.length) state.active = 0;

    els.results.innerHTML = state.results.map((app, i) => (
      '<li class="start-result" role="option" id="startResult-' + esc(app.key) + '" data-app="' + esc(app.key) +
      '" aria-selected="' + (i === state.active) + '">' +
      '<span class="start-result-img">' + (D.appIcon ? D.appIcon(app, 28) : '') + '</span>' +
      '<span class="start-result-name">' + esc(app.name) + '</span></li>'
    )).join('');
    els.empty.hidden = state.results.length > 0;
    syncActive();
  }

  function syncActive() {
    const items = els.results.querySelectorAll('.start-result');
    items.forEach((li, i) => li.setAttribute('aria-selected', String(i === state.active)));
    const cur = items[state.active];
    if (els.search) {
      if (cur) els.search.setAttribute('aria-activedescendant', cur.id);
      else els.search.removeAttribute('aria-activedescendant');
    }
    if (cur && cur.scrollIntoView) cur.scrollIntoView({ block: 'nearest' });
  }

  function showMode(mode) {
    state.mode = mode;
    els.home.hidden = mode === 'search';
    els.searchSection.hidden = mode !== 'search';
    if (mode === 'search') {
      state.active = 0;
      renderResults();
    }
  }

  // === ABRIR / CERRAR ===
  function open(mode) {
    if (!state.ready) return;
    mode = mode === 'search' ? 'search' : 'menu';
    const wasOpen = state.isOpen;
    state.isOpen = true;
    els.menu.hidden = false;
    els.button.setAttribute('aria-expanded', 'true');
    if (!wasOpen) {
      els.menu.classList.remove('is-open');
      void els.menu.offsetWidth; // reinicia la animación de entrada
      els.menu.classList.add('is-open');
    }
    showMode(mode);
  }

  function close() {
    if (!state.ready || !state.isOpen) return;
    state.isOpen = false;
    els.menu.hidden = true;
    els.menu.classList.remove('is-open');
    els.button.setAttribute('aria-expanded', 'false');
    if (els.search) {
      els.search.value = '';
      els.search.removeAttribute('aria-activedescendant');
    }
    showMode('menu');
  }

  function toggle() {
    if (state.isOpen) close();
    else open('menu');
  }

  function openApp(key) {
    close();
    if (els.search) els.search.blur();
    if (window.desktop && key) window.desktop.openApplication(key);
  }

  // === ACCIONES ===
  async function logout() {
    els.logout.disabled = true;
    try {
      await fetch('/api/core/v2/auth/logout', { method: 'POST', credentials: 'include' });
    } catch (err) {
      console.error('[ItcjDesktop] error al cerrar sesión:', err);
    }
    if (D.session && typeof D.session.clear === 'function') D.session.clear();
    if (window.desktop) window.desktop.closeAllWindows();
    window.location.href = '/itcj/login';
  }

  // === EVENTOS ===
  function onSearchKey(e) {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      if (!state.isOpen || state.mode !== 'search') open('search');
      e.preventDefault();
      const n = state.results.length;
      if (!n) return;
      const step = e.key === 'ArrowDown' ? 1 : -1;
      state.active = (state.active + step + n) % n;
      syncActive();
      return;
    }
    if (e.key === 'Enter') {
      const hit = state.results[state.active] || state.results[0];
      if (state.isOpen && hit) { e.preventDefault(); openApp(hit.key); }
    }
  }

  function onDocPointerDown(e) {
    if (!state.isOpen) return;
    const t = e.target;
    if (els.menu.contains(t) || els.button.contains(t)) return;
    if (els.search && els.search.closest('.taskbar-search').contains(t)) return;
    close();
  }

  function bind() {
    els.button.addEventListener('click', toggle);

    if (els.search) {
      els.search.addEventListener('focus', () => open('search'));
      els.search.addEventListener('click', () => { if (!state.isOpen || state.mode !== 'search') open('search'); });
      els.search.addEventListener('input', () => {
        if (!state.isOpen || state.mode !== 'search') open('search');
        else { state.active = 0; renderResults(); }
      });
      els.search.addEventListener('keydown', onSearchKey);
    }

    els.apps.addEventListener('click', (e) => {
      const btn = e.target.closest('.start-app');
      if (btn) openApp(btn.getAttribute('data-app'));
    });
    els.results.addEventListener('click', (e) => {
      const li = e.target.closest('.start-result');
      if (li) openApp(li.getAttribute('data-app'));
    });
    els.results.addEventListener('pointermove', (e) => {
      const li = e.target.closest('.start-result');
      if (!li) return;
      const idx = Array.from(els.results.children).indexOf(li);
      if (idx !== state.active) { state.active = idx; syncActive(); }
    });

    els.user.addEventListener('click', () => { close(); if (window.desktop) window.desktop.openProfile(); });
    els.settings.addEventListener('click', () => openApp('settings'));
    els.logout.addEventListener('click', logout);

    document.addEventListener('pointerdown', onDocPointerDown, true);
    // Un clic dentro de un iframe no llega al documento: el foco pasa al iframe.
    window.addEventListener('blur', () => {
      if (state.isOpen && document.activeElement && document.activeElement.tagName === 'IFRAME') close();
    });
    document.addEventListener('keydown', (e) => {
      if ((e.ctrlKey || e.metaKey) && !e.altKey && !e.shiftKey && String(e.key).toLowerCase() === 'k') {
        if (!els.search) return;
        e.preventDefault();
        els.search.focus();
        els.search.select();
        open('search');
      } else if (e.key === 'Escape' && state.isOpen) {
        const fromSearch = document.activeElement === els.search;
        close();
        if (fromSearch) els.search.blur();
        els.button.focus();
      }
    });
  }

  function init() {
    if (state.ready) return;
    els = {
      menu: document.getElementById('startMenu'),
      button: document.querySelector('.start-button'),
      search: document.getElementById('taskbarSearch'),
      home: document.getElementById('startMenuHome'),
      apps: document.getElementById('startMenuApps'),
      searchSection: document.getElementById('startMenuSearch'),
      results: document.getElementById('startMenuResults'),
      empty: document.getElementById('startMenuEmpty'),
      user: document.getElementById('startMenuUser'),
      settings: document.getElementById('startMenuSettings'),
      logout: document.getElementById('startMenuLogout')
    };
    if (Object.keys(els).some((k) => k !== 'search' && !els[k])) {
      console.error('[ItcjDesktop] menú inicio incompleto en la plantilla');
      return;
    }
    state.ready = true;
    bind();
  }

  D.startMenu = { init: init, open: open, close: close, toggle: toggle };
})();
