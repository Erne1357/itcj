/**
 * start-menu.js — menú inicio y buscador de la barra.
 *
 * `ItcjDesktop.startMenu = {init(), open(mode?), close(), toggle(), searchInMenu()}`.
 * Modo 'menu' muestra la cuadrícula de apps; modo 'search' filtra (sin acentos)
 * las apps del registro con `state.query`, la única consulta. La escriben dos
 * campos con el mismo comportamiento (↑/↓/Enter/Esc): `#taskbarSearch`, en la
 * barra, y `#startMenuSearchInput`, arriba del menú. Este último solo aparece
 * cuando el de la barra está colapsado (dashboard.css lo deja en la lupa a
 * ≤ 960 px; aquí se mide, el número vive en un solo lugar): como en Windows 11,
 * abrir la búsqueda (lupa, foco del campo, tecla imprimible con la barra o el
 * menú enfocados, Ctrl+K) lleva el foco al campo visible del menú. Ctrl+K vale
 * solo en el documento del escritorio, no dentro de los iframes.
 */
(function () {
  'use strict';

  const D = window.ItcjDesktop = window.ItcjDesktop || {};

  const state = { ready: false, isOpen: false, mode: 'menu', query: '', results: [], active: -1 };
  let els = {};
  let resizeFrame = 0;

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

  // === CAMPOS DE BÚSQUEDA ===
  function fields() {
    return [els.search, els.menuSearch].filter(Boolean);
  }

  /** ¿El campo de la barra está colapsado (solo se ve la lupa)? Lo decide el CSS. */
  function barCollapsed() {
    if (!els.search) return true;
    if (els.search.getBoundingClientRect().width < 40) return true;
    const cs = getComputedStyle(els.search);
    return cs.visibility === 'hidden' || Number(cs.opacity) === 0;
  }

  /** ¿La búsqueda se escribe en el campo del menú (barra colapsada)? */
  function searchInMenu() {
    return !!els.menuSearch && barCollapsed();
  }

  /** El campo donde se escribe ahora. */
  function activeField() {
    return searchInMenu() ? els.menuSearch : els.search;
  }

  /** Única fuente de la consulta: ambos campos reflejan `state.query`. */
  function setQuery(value) {
    state.query = String(value == null ? '' : value);
    fields().forEach((f) => { if (f.value !== state.query) f.value = state.query; });
  }

  function focusField(field, select) {
    field.focus({ preventScroll: true });
    try {
      if (select) field.select();
      else field.setSelectionRange(field.value.length, field.value.length);
    } catch (err) { /* el tipo de campo no admite selección */ }
  }

  /** Campo del menú visible solo en modo búsqueda con la barra colapsada; el foco sigue al campo visible. */
  function syncSearchBox() {
    if (!els.searchBox) return;
    const hadFocus = fields().includes(document.activeElement);
    const searching = state.isOpen && state.mode === 'search';
    els.searchBox.hidden = !(searching && searchInMenu());
    if (searching && hadFocus) {
      const field = activeField();
      if (field && document.activeElement !== field) focusField(field, false);
    }
  }

  // === RENDER ===
  function renderResults() {
    state.results = filterApps(state.query);
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
    fields().forEach((f) => {
      if (cur) f.setAttribute('aria-activedescendant', cur.id);
      else f.removeAttribute('aria-activedescendant');
    });
    if (cur && cur.scrollIntoView) cur.scrollIntoView({ block: 'nearest' });
  }

  function showMode(mode) {
    state.mode = mode;
    els.home.hidden = mode === 'search';
    els.searchSection.hidden = mode !== 'search';
    syncSearchBox();
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

  /** Abre la búsqueda y lleva el foco al campo visible (`select`: selecciona lo escrito). */
  function openSearch(select) {
    if (!state.ready) return null;
    if (!state.isOpen || state.mode !== 'search') open('search');
    const field = activeField();
    if (!field) return null;
    if (document.activeElement !== field) focusField(field, select);
    else if (select) field.select();
    return field;
  }

  function close() {
    if (!state.ready || !state.isOpen) return;
    state.isOpen = false;
    els.menu.hidden = true;
    els.menu.classList.remove('is-open');
    els.button.setAttribute('aria-expanded', 'false');
    setQuery('');
    fields().forEach((f) => f.removeAttribute('aria-activedescendant'));
    showMode('menu');
  }

  function toggle() {
    if (state.isOpen) close();
    else open('menu');
  }

  function openApp(key) {
    close();
    fields().forEach((f) => f.blur());
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
  /** Una letra, número o signo sin modificadores (el espacio activa botones: no cuenta). */
  function isPrintable(e) {
    return typeof e.key === 'string' && e.key.length === 1 && e.key !== ' ' &&
      !e.ctrlKey && !e.metaKey && !e.altKey && !e.isComposing;
  }

  /** ¿Teclear con el foco aquí empieza una búsqueda? Botón de inicio o un botón del menú abierto. */
  function typesIntoSearch(target) {
    if (!target || !target.closest || fields().includes(target)) return false;
    if (target.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName)) return false;
    return els.button.contains(target) || (state.isOpen && els.menu.contains(target));
  }

  /** Abre la búsqueda y escribe `ch` en el campo visible, donde está el cursor. */
  function typeIntoSearch(ch) {
    const field = openSearch(false);
    if (!field) return;
    const end = field.value.length;
    let from = end;
    let to = end;
    try {
      if (field.selectionStart != null) { from = field.selectionStart; to = field.selectionEnd; }
    } catch (err) { /* sin selección */ }
    field.setRangeText(ch, from, to, 'end');
    onFieldInput(field);
  }

  function onFieldInput(field) {
    setQuery(field.value);
    if (!state.isOpen || state.mode !== 'search') openSearch(false);
    else { state.active = 0; renderResults(); }
  }

  function onSearchKey(e) {
    // Foco en el campo colapsado de la barra (p. ej. tras achicar la ventana): lo tecleado va al del menú.
    if (e.currentTarget === els.search && isPrintable(e) && searchInMenu()) {
      e.preventDefault();
      typeIntoSearch(e.key);
      return;
    }
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      if (!state.isOpen || state.mode !== 'search') openSearch(false);
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

  function onDocKey(e) {
    if ((e.ctrlKey || e.metaKey) && !e.altKey && !e.shiftKey && String(e.key).toLowerCase() === 'k') {
      if (!fields().length) return;
      e.preventDefault();
      openSearch(true);
    } else if (e.key === 'Escape' && state.isOpen) {
      const fromSearch = fields().includes(document.activeElement);
      close();
      if (fromSearch) fields().forEach((f) => f.blur());
      els.button.focus();
    } else if (!e.defaultPrevented && isPrintable(e) && typesIntoSearch(e.target)) {
      e.preventDefault();
      typeIntoSearch(e.key);
    }
  }

  function bind() {
    els.button.addEventListener('click', toggle);

    if (els.search) {
      // Con la barra colapsada, el foco pasa al campo del menú (openSearch).
      els.search.addEventListener('focus', () => openSearch(false));
      els.search.addEventListener('click', () => { if (!state.isOpen || state.mode !== 'search') openSearch(false); });
    }
    fields().forEach((field) => {
      field.addEventListener('input', () => onFieldInput(field));
      field.addEventListener('keydown', onSearchKey);
    });

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
    document.addEventListener('keydown', onDocKey);
    // Cruzar el quiebre con la búsqueda abierta: aparece/desaparece el campo del menú.
    window.addEventListener('resize', () => {
      if (!state.isOpen || state.mode !== 'search') return;
      cancelAnimationFrame(resizeFrame);
      resizeFrame = requestAnimationFrame(syncSearchBox);
    });
  }

  function init() {
    if (state.ready) return;
    els = {
      menu: document.getElementById('startMenu'),
      button: document.querySelector('.start-button'),
      search: document.getElementById('taskbarSearch'),
      searchBox: document.getElementById('startMenuSearchBox'),
      menuSearch: document.getElementById('startMenuSearchInput'),
      home: document.getElementById('startMenuHome'),
      apps: document.getElementById('startMenuApps'),
      searchSection: document.getElementById('startMenuSearch'),
      results: document.getElementById('startMenuResults'),
      empty: document.getElementById('startMenuEmpty'),
      user: document.getElementById('startMenuUser'),
      settings: document.getElementById('startMenuSettings'),
      logout: document.getElementById('startMenuLogout')
    };
    const optional = ['search', 'searchBox', 'menuSearch'];
    if (Object.keys(els).some((k) => !optional.includes(k) && !els[k])) {
      console.error('[ItcjDesktop] menú inicio incompleto en la plantilla');
      return;
    }
    if (!els.searchBox) els.menuSearch = null;
    state.ready = true;
    bind();
  }

  D.startMenu = {
    init: init,
    open: open,
    close: close,
    toggle: toggle,
    /** true si la búsqueda se escribe en el campo del menú (la barra solo muestra la lupa). */
    searchInMenu: () => state.ready && searchInMenu()
  };
})();
