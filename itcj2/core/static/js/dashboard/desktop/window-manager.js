/**
 * window-manager.js — ventanas del escritorio (`ItcjDesktop.wm`).
 *
 * Una ventana por app: abrir una ya abierta la trae al frente (y la restaura si
 * estaba minimizada). Estados: normal, maximizada, acoplada (izq/der) y
 * minimizada (ortogonal: una minimizada recuerda su estado anterior).
 *
 * Geometría: el JS la pone en línea según el estado (normal en px relativos al
 * área útil; maximizada y acopladas en %, así siguen al navegador solas). El
 * CSS (desktop-windows.css) solo pinta.
 *
 * Eventos en `document` (CustomEvent, detail {key, url, state}):
 * desktop:window-opened, -focused, -minimized, -restored, -state, -moved,
 * -navigated, -closed; y desktop:active-changed (detail {key|null}).
 *
 * Todo acceso a `contentWindow`/`contentDocument` va en try/catch: un iframe de
 * otro origen (o una página de error) no debe romper enfocar, arrastrar ni cerrar.
 *
 * Task 3 agrega aquí: manijas de redimensión, vista previa de acople durante el
 * arrastre, geometría recordada y ajuste al redimensionar el navegador.
 */
(function () {
  'use strict';

  const D = window.ItcjDesktop = window.ItcjDesktop || {};

  // === CONSTANTES ===
  const Z_BASE = 10;              // z-index de la ventana de más abajo (la barra vive en 1000)
  const NARROW_PX = 900;          // por debajo: todas maximizadas y sin arrastre
  const DEFAULT_RATIO = 0.7;      // ventana restaurada sin geometría: 70% del área útil
  const CASCADE_PX = 28;
  const MIN_W = 420;
  const MIN_H = 300;
  const TITLEBAR_H = 36;
  const DRAG_THRESHOLD = 4;       // px antes de considerar arrastre (no rompe el doble clic)
  const KEEP_VISIBLE = 96;        // px de barra de título que siempre quedan a la vista
  const URL_POLL_MS = 1000;
  const LOADING_CAP_MS = 30000;   // tope de la barra de progreso (una navegación cancelada no la deja colgada)
  const STATES = ['normal', 'maximized', 'snap-left', 'snap-right'];

  const esc = (v) => D.escapeHtml(v);
  const clamp = (v, lo, hi) => Math.min(Math.max(v, lo), Math.max(lo, hi));
  const isNarrow = () => window.innerWidth < NARROW_PX;
  const reducedMotion = () => !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  const stateOf = (win) => (win.minimized ? 'minimized' : win.state);

  /** Ruta relativa (path + query + hash) si `href` es del mismo origen http/https; si no, null. */
  function sameOriginPath(href) {
    if (typeof href !== 'string' || !href) return null;
    try {
      const u = new URL(href, window.location.origin + '/');
      if ((u.protocol !== 'http:' && u.protocol !== 'https:') || u.origin !== window.location.origin) return null;
      return u.pathname + u.search + u.hash;
    } catch (err) {
      return null;
    }
  }

  /** Lo que se muestra en la barra de título: ruta legible, sin el hash. */
  function displayUrl(path) {
    const clean = String(path || '').split('#')[0];
    try { return decodeURI(clean); } catch (err) { return clean; }
  }

  function isLogoutPath(path) {
    const p = String(path || '').split(/[?#]/)[0];
    return p.endsWith('/logout') || p === '/itcj/login';
  }

  class WindowManager {
    constructor(opts) {
      this.registry = (opts && opts.registry) || D.registry;
      this.container = document.getElementById('windows-container');
      this.windows = new Map();   // key → estado interno de la ventana
      this.stack = [];            // keys de abajo hacia arriba (z-order)
      this.active = null;         // key de la ventana visible de más arriba
      this._bindGlobal();
    }

    // =======================================================================
    // === API PÚBLICA (contrato compartido) ===
    // =======================================================================

    /** Abre (o trae al frente) la ventana de `key`. opts: {url, state, rect, focus=true, animate=true}. */
    open(key, opts) {
      const o = opts || {};
      const app = this.registry ? this.registry.get(key) : null;
      if (!app || !this.container) {
        console.warn('[ItcjDesktop] no se puede abrir la app:', key);
        return null;
      }
      const existing = this.windows.get(key);
      if (existing) {
        if (o.url) this.navigate(key, o.url);
        if (o.state) this._applyRequestedState(existing, o.state);
        if (o.focus !== false && o.state !== 'minimized') this.focus(key);
        return existing.el;
      }
      return this._create(app, o).el;
    }

    focus(key) {
      const win = this.windows.get(key);
      if (!win) return false;
      if (win.minimized) return this.restore(key);
      const wasTop = this.stack[this.stack.length - 1] === key;
      if (!wasTop) this._raise(key);
      const changed = this._refreshActive();
      if (!wasTop || changed) this._emit('window-focused', win);
      return true;
    }

    minimize(key) {
      const win = this.windows.get(key);
      if (!win || win.minimized) return false;
      this._minimize(win, !reducedMotion());
      return true;
    }

    /** Desminimiza y enfoca. Sobre una ventana no minimizada equivale a `focus`. */
    restore(key) {
      const win = this.windows.get(key);
      if (!win) return false;
      if (!win.minimized) return this.focus(key);
      win.minimized = false;
      this._cancelAnim(win);
      win.el.classList.remove('is-minimized');
      this._raise(key);
      if (!reducedMotion() && win.el.animate) {
        const t = this._taskbarTarget(win);
        win.anim = win.el.animate([
          { transform: `translate(${t.dx}px, ${t.dy}px) scale(${t.s})`, opacity: 0 },
          { transform: 'none', opacity: 1 }
        ], { duration: 200, easing: 'cubic-bezier(.2, .8, .2, 1)' });
        win.anim.onfinish = win.anim.oncancel = () => { win.anim = null; };
      }
      this._emit('window-restored', win);
      this._refreshActive();
      return true;
    }

    /** Maximizada ⇄ normal (una acoplada pasa a maximizada). Bajo 900 px no cambia. */
    toggleMaximize(key) {
      const win = this.windows.get(key);
      if (!win) return false;
      if (win.minimized) this.restore(key);
      if (isNarrow()) return false;
      this._setState(win, win.state === 'maximized' ? 'normal' : 'maximized', true);
      return true;
    }

    /** Acople básico por API (la vista previa al arrastrar es de la Task 3). */
    snap(key, side) {
      const win = this.windows.get(key);
      if (!win) return false;
      const state = side === 'left' ? 'snap-left' : side === 'right' ? 'snap-right' : side === 'max' ? 'maximized' : null;
      if (!state) return false;
      if (win.minimized) this.restore(key);
      this._setState(win, isNarrow() ? 'maximized' : state, true);
      return true;
    }

    close(key, opts) {
      const win = this.windows.get(key);
      if (!win) return false;
      const animate = !(opts && opts.animate === false) && !win.minimized && !reducedMotion();
      this.windows.delete(key);
      this.stack = this.stack.filter((k) => k !== key);
      clearTimeout(win.loadingTimer);
      clearTimeout(win.transitionTimer);
      this._cancelAnim(win);

      const el = win.el;
      el.removeAttribute('data-app-id');   // ya no cuenta como ventana abierta
      el.style.pointerEvents = 'none';
      if (el.contains(document.activeElement)) this._blurActive();
      if (animate && el.animate) {
        const a = el.animate([{ opacity: 1, transform: 'none' }, { opacity: 0, transform: 'scale(.97)' }],
          { duration: 120, easing: 'ease-in' });
        a.onfinish = a.oncancel = () => el.remove();
      } else {
        el.remove();
      }

      this._applyZ();
      this._emit('window-closed', win);
      this._refreshActive();
      return true;
    }

    closeAll() {
      this.stack.slice().forEach((key) => this.close(key, { animate: false }));
    }

    /** Navega el iframe de `key` a `url` (debe ser de la misma app, según el registro). */
    navigate(key, url) {
      const win = this.windows.get(key);
      if (!win) return false;
      const hit = this.registry.resolve(url);
      if (!hit || hit.key !== key) {
        console.warn('[ItcjDesktop] URL fuera de la app', key, url);
        return false;
      }
      this._setLoading(win, true);
      try {
        win.iframe.contentWindow.location.assign(hit.url);
      } catch (err) {
        win.iframe.src = hit.url;
      }
      this._setUrl(win, hit.url);
      return true;
    }

    reload(key) {
      const win = this.windows.get(key);
      if (!win) return false;
      this._setLoading(win, true);
      try {
        win.iframe.contentWindow.location.reload();
      } catch (err) {
        win.iframe.src = win.url || win.app.url;
      }
      return true;
    }

    popout(key) {
      const win = this.windows.get(key);
      if (!win) return false;
      window.open(win.url || win.app.url, '_blank', 'noopener');
      return true;
    }

    isOpen(key) { return this.windows.has(key); }

    getState(key) {
      const win = this.windows.get(key);
      return win ? stateOf(win) : null;
    }

    activeKey() { return this.active; }

    list() {
      return this.stack.map((key, i) => {
        const win = this.windows.get(key);
        return { key, url: win.url, state: stateOf(win), z: Z_BASE + i, rect: win.rect ? { ...win.rect } : null };
      });
    }

    /** Área útil (escritorio menos barra) en px. */
    workArea() {
      const c = this.container;
      const w = (c && c.clientWidth) || window.innerWidth;
      const h = (c && c.clientHeight) || Math.max(0, window.innerHeight - 48);
      return { w, h };
    }

    handleLogout() {
      this.closeAll();
      try { if (D.session && typeof D.session.clear === 'function') D.session.clear(); } catch (err) { /* sin storage */ }
      window.location.href = '/itcj/login';
    }

    handleSessionExpired() {
      this.closeAll();
      window.location.href = '/itcj/login?session_expired=true';
    }

    // =======================================================================
    // === CREACIÓN ===
    // =======================================================================

    _create(app, o) {
      const url = this._initialUrl(app, o.url);
      let state = STATES.includes(o.state) ? o.state : 'maximized';
      if (isNarrow()) state = 'maximized';

      const win = {
        key: app.key,
        app,
        url,
        state,
        minimized: false,
        rect: this._sanitizeRect(o.rect),
        el: null,
        iframe: null,
        anim: null,
        loadingTimer: 0,
        transitionTimer: 0
      };
      if (state === 'normal' && !win.rect) win.rect = this._defaultRect();

      win.el = this._buildElement(app, url);
      win.titlebar = win.el.querySelector('.window-titlebar');
      win.urlEl = win.el.querySelector('.window-url');
      win.maxBtn = win.el.querySelector('.window-control.maximize');
      win.iframe = win.el.querySelector('iframe');

      this.windows.set(app.key, win);
      this.stack.push(app.key);
      this._applyGeometry(win, false);
      this._applyClasses(win);
      this._wire(win);
      this._setLoading(win, true);
      this.container.appendChild(win.el);
      this._applyZ();

      this._emit('window-opened', win);
      if (o.state === 'minimized') {
        this._minimize(win, false);
      } else {
        if (o.animate !== false && !reducedMotion() && win.el.animate) {
          win.el.animate([{ opacity: 0, transform: 'scale(.98)' }, { opacity: 1, transform: 'none' }],
            { duration: 160, easing: 'cubic-bezier(.2, .8, .2, 1)' });
        }
        this._refreshActive();
        if (o.focus !== false) this._emit('window-focused', win);
      }
      return win;
    }

    _initialUrl(app, url) {
      if (url) {
        const hit = this.registry.resolve(url);
        if (hit && hit.key === app.key) return hit.url;
      }
      return app.url;
    }

    _buildElement(app, url) {
      // Sandbox solo si el iframe es cross-origin (p. ej. una app en otro puerto).
      // Same-origin: scripts+same-origin lo vuelve evadible (el hijo puede quitarse
      // el atributo), y Chromium bloquea el visor PDF en documentos con sandbox,
      // asi que ahi no se pone. Cross-origin: el hijo NO puede levantar su propio
      // sandbox, es una frontera real; los permisos conservan scripts, cookies,
      // forms, popups y descargas, pero sin navegar el top ni modales.
      let iframeIsCrossOrigin = false
      try {
        iframeIsCrossOrigin = new URL(url, globalThis.location.href).origin !== globalThis.location.origin
      } catch (e) { /* URL invalida: se trata como same-origin */ }
      const iframeSandbox = iframeIsCrossOrigin
        ? 'sandbox="allow-scripts allow-same-origin allow-forms allow-popups allow-popups-to-escape-sandbox allow-downloads"'
        : ""

      const el = document.createElement('section');
      el.className = 'app-window';
      el.dataset.appId = app.key;
      el.setAttribute('aria-label', app.name);
      el.innerHTML = `
        <header class="window-titlebar">
          <span class="window-app-icon">${D.appIcon(app, 18)}</span>
          <div class="window-title">
            <span class="window-title-text">${esc(app.name)}</span>
            <span class="window-url">${esc(displayUrl(url))}</span>
          </div>
          <div class="window-controls">
            <button type="button" class="window-control reload" title="Recargar" aria-label="Recargar">${D.icon('refresh')}</button>
            <button type="button" class="window-control popout" title="Abrir en una pestaña nueva" aria-label="Abrir en una pestaña nueva">${D.icon('external')}</button>
            <button type="button" class="window-control minimize" title="Minimizar" aria-label="Minimizar">${D.icon('minus')}</button>
            <button type="button" class="window-control maximize" title="Maximizar" aria-label="Maximizar">${D.icon('square', 'ico-square')}${D.icon('restore', 'ico-restore')}</button>
            <button type="button" class="window-control close" title="Cerrar" aria-label="Cerrar">${D.icon('x')}</button>
          </div>
          <div class="window-progress" aria-hidden="true"></div>
        </header>
        <div class="window-content">
          <iframe class="window-iframe" src="${esc(url)}" ${iframeSandbox} title="${esc(app.name)}" allow="fullscreen" referrerpolicy="same-origin"></iframe>
        </div>`;
      return el;
    }

    _wire(win) {
      const key = win.key;
      // Cualquier clic en la ventana (fuera del iframe) la trae al frente.
      win.el.addEventListener('pointerdown', () => this.focus(key), true);

      win.titlebar.addEventListener('click', (e) => {
        const btn = e.target.closest('.window-control');
        if (!btn) return;
        if (btn.classList.contains('close')) this.close(key);
        else if (btn.classList.contains('minimize')) this.minimize(key);
        else if (btn.classList.contains('maximize')) this.toggleMaximize(key);
        else if (btn.classList.contains('reload')) this.reload(key);
        else if (btn.classList.contains('popout')) this.popout(key);
      });
      win.titlebar.addEventListener('dblclick', (e) => {
        if (e.target.closest('.window-controls')) return;
        this.toggleMaximize(key);
      });
      win.titlebar.addEventListener('pointerdown', (e) => this._startDrag(win, e));
      win.iframe.addEventListener('load', () => this._onFrameLoad(win));
    }

    // =======================================================================
    // === ESTADO, GEOMETRÍA Y Z-ORDER ===
    // =======================================================================

    _applyRequestedState(win, state) {
      if (state === 'minimized') {
        if (!win.minimized) this._minimize(win, false);
      } else if (STATES.includes(state)) {
        this._setState(win, isNarrow() ? 'maximized' : state, false);
      }
    }

    _setState(win, state, animate) {
      if (!STATES.includes(state) || win.state === state) return;
      if (state === 'normal') {
        if (!win.rect) win.rect = this._defaultRect();
        else win.rect = this._fitRect(win.rect);
      }
      win.state = state;
      this._applyGeometry(win, animate);
      this._applyClasses(win);
      this._emit('window-state', win);
    }

    _applyGeometry(win, animate) {
      const s = win.el.style;
      if (animate && !reducedMotion()) {
        win.el.classList.add('is-transitioning');
        clearTimeout(win.transitionTimer);
        win.transitionTimer = setTimeout(() => win.el.classList.remove('is-transitioning'), 200);
      }
      if (win.state === 'maximized') {
        s.left = '0'; s.top = '0'; s.width = '100%'; s.height = '100%';
      } else if (win.state === 'snap-left') {
        s.left = '0'; s.top = '0'; s.width = '50%'; s.height = '100%';
      } else if (win.state === 'snap-right') {
        s.left = '50%'; s.top = '0'; s.width = '50%'; s.height = '100%';
      } else {
        const r = win.rect;
        s.left = r.x + 'px'; s.top = r.y + 'px'; s.width = r.w + 'px'; s.height = r.h + 'px';
      }
    }

    _applyClasses(win) {
      const cl = win.el.classList;
      cl.toggle('is-maximized', win.state === 'maximized');
      cl.toggle('is-snap-left', win.state === 'snap-left');
      cl.toggle('is-snap-right', win.state === 'snap-right');
      if (win.maxBtn) {
        const label = win.state === 'normal' ? 'Maximizar' : 'Restaurar';
        win.maxBtn.title = label;
        win.maxBtn.setAttribute('aria-label', label);
      }
    }

    /** 70% del área útil, centrado, con cascada de 28 px por ventana normal visible. */
    _defaultRect() {
      const area = this.workArea();
      const w = Math.min(area.w, Math.max(MIN_W, Math.round(area.w * DEFAULT_RATIO)));
      const h = Math.min(area.h, Math.max(MIN_H, Math.round(area.h * DEFAULT_RATIO)));
      let n = 0;
      this.windows.forEach((win) => { if (win.state === 'normal' && !win.minimized) n += 1; });
      let x = Math.round((area.w - w) / 2) + n * CASCADE_PX;
      let y = Math.round((area.h - h) / 2) + n * CASCADE_PX;
      if (x + w > area.w || y + h > area.h) {
        x = Math.round((area.w - w) / 2);
        y = Math.round((area.h - h) / 2);
      }
      return { x: Math.max(0, x), y: Math.max(0, y), w, h };
    }

    /** Rect de entrada (opts.rect) → números finitos o null. */
    _sanitizeRect(rect) {
      if (!rect || typeof rect !== 'object') return null;
      const n = ['x', 'y', 'w', 'h'].map((k) => Number(rect[k]));
      if (!n.every(Number.isFinite) || n[2] <= 0 || n[3] <= 0) return null;
      return this._fitRect({ x: n[0], y: n[1], w: n[2], h: n[3] });
    }

    /** Mantiene el rect dentro del área útil con la barra de título alcanzable. */
    _fitRect(rect) {
      const area = this.workArea();
      const w = Math.round(clamp(rect.w, Math.min(MIN_W, area.w), area.w));
      const h = Math.round(clamp(rect.h, Math.min(MIN_H, area.h), area.h));
      const x = Math.round(clamp(rect.x, KEEP_VISIBLE - w, area.w - KEEP_VISIBLE));
      const y = Math.round(clamp(rect.y, 0, area.h - TITLEBAR_H));
      return { x, y, w, h };
    }

    _raise(key) {
      this.stack = this.stack.filter((k) => k !== key);
      this.stack.push(key);
      this._applyZ();
    }

    _applyZ() {
      this.stack.forEach((key, i) => {
        const win = this.windows.get(key);
        if (win) win.el.style.zIndex = String(Z_BASE + i);
      });
    }

    _topVisibleKey() {
      for (let i = this.stack.length - 1; i >= 0; i -= 1) {
        const win = this.windows.get(this.stack[i]);
        if (win && !win.minimized) return win.key;
      }
      return null;
    }

    /** `is-active` en la de más arriba no minimizada; avisa si cambió. */
    _refreshActive() {
      const next = this._topVisibleKey();
      this.windows.forEach((win) => win.el.classList.toggle('is-active', win.key === next));
      if (next === this.active) return false;
      this.active = next;
      document.dispatchEvent(new CustomEvent('desktop:active-changed', { detail: { key: next } }));
      return true;
    }

    // =======================================================================
    // === MINIMIZAR (animación hacia su botón de la barra) ===
    // =======================================================================

    _minimize(win, animate) {
      win.minimized = true;
      this._cancelAnim(win);
      if (win.el.contains(document.activeElement)) this._blurActive();
      // La clase va de inmediato (estado coherente, sin clics); la animación
      // fuerza `visibility: visible` mientras se encoge hacia la barra.
      win.el.classList.add('is-minimized');
      if (animate && win.el.animate) {
        const t = this._taskbarTarget(win);
        win.anim = win.el.animate([
          { visibility: 'visible', transform: 'none', opacity: 1 },
          { visibility: 'visible', transform: `translate(${t.dx}px, ${t.dy}px) scale(${t.s})`, opacity: 0 }
        ], { duration: 200, easing: 'cubic-bezier(.4, 0, .2, 1)' });
        win.anim.onfinish = win.anim.oncancel = () => { win.anim = null; };
      }
      this._emit('window-minimized', win);
      this._refreshActive();
    }

    /** Desplazamiento y escala para llevar la ventana al centro de su botón. */
    _taskbarTarget(win) {
      const from = win.el.getBoundingClientRect();
      let btn = null;
      try {
        btn = document.querySelector('.taskbar-app[data-app="' + CSS.escape(win.key) + '"]');
      } catch (err) { btn = null; }
      const to = btn ? btn.getBoundingClientRect()
        : { left: window.innerWidth / 2 - 20, top: window.innerHeight - 44, width: 40, height: 40 };
      const dx = Math.round((to.left + to.width / 2) - (from.left + from.width / 2));
      const dy = Math.round((to.top + to.height / 2) - (from.top + from.height / 2));
      const s = Math.max(0.04, Math.min(0.3, (to.width * 3) / Math.max(1, from.width)));
      return { dx, dy, s: s.toFixed(3) };
    }

    _cancelAnim(win) {
      if (win.anim) {
        try { win.anim.cancel(); } catch (err) { /* ya terminó */ }
        win.anim = null;
      }
    }

    _blurActive() {
      try { if (document.activeElement && document.activeElement.blur) document.activeElement.blur(); } catch (err) { /* nada */ }
    }

    // =======================================================================
    // === ARRASTRE POR LA BARRA DE TÍTULO ===
    // =======================================================================

    _startDrag(win, e) {
      if (e.button !== 0 || e.target.closest('.window-controls')) return;
      if (isNarrow()) return;
      const tb = win.titlebar;
      const drag = {
        id: e.pointerId,
        startX: e.clientX,
        startY: e.clientY,
        box: win.el.getBoundingClientRect(),
        areaBox: this.container.getBoundingClientRect(),
        moved: false,
        ended: false,
        origin: null
      };
      try { tb.setPointerCapture(e.pointerId); } catch (err) { /* sin captura: sigue funcionando dentro de la barra */ }

      const move = (ev) => {
        if (ev.pointerId !== drag.id || drag.ended) return;
        if (!drag.moved) {
          if (Math.abs(ev.clientX - drag.startX) < DRAG_THRESHOLD && Math.abs(ev.clientY - drag.startY) < DRAG_THRESHOLD) return;
          drag.moved = true;
          document.body.classList.add('desktop-dragging');   // escudo: los iframes no se tragan el puntero
          if (win.state !== 'normal') this._detachForDrag(win, drag, ev);
          drag.origin = { x: win.rect.x, y: win.rect.y, px: ev.clientX, py: ev.clientY };
        }
        const area = this.workArea();
        const r = win.rect;
        r.x = Math.round(clamp(drag.origin.x + ev.clientX - drag.origin.px, KEEP_VISIBLE - r.w, area.w - KEEP_VISIBLE));
        r.y = Math.round(clamp(drag.origin.y + ev.clientY - drag.origin.py, 0, area.h - TITLEBAR_H));
        win.el.style.left = r.x + 'px';
        win.el.style.top = r.y + 'px';
      };
      const end = (ev) => {
        if (ev.pointerId !== drag.id || drag.ended) return;
        drag.ended = true;
        tb.removeEventListener('pointermove', move);
        tb.removeEventListener('pointerup', end);
        tb.removeEventListener('pointercancel', end);
        tb.removeEventListener('lostpointercapture', end);
        try { tb.releasePointerCapture(drag.id); } catch (err) { /* ya liberada */ }
        document.body.classList.remove('desktop-dragging');
        if (drag.moved && this.windows.get(win.key) === win) this._emit('window-moved', win);
      };
      tb.addEventListener('pointermove', move);
      tb.addEventListener('pointerup', end);
      tb.addEventListener('pointercancel', end);
      tb.addEventListener('lostpointercapture', end);
    }

    /** Arrastrar una maximizada/acoplada la restaura a su tamaño normal bajo el cursor. */
    _detachForDrag(win, drag, ev) {
      const normal = win.rect || this._defaultRect();
      const box = drag.box;
      const ratio = box.width > 0 ? (drag.startX - box.left) / box.width : 0.5;
      const offsetY = clamp(drag.startY - box.top, 0, TITLEBAR_H);
      win.rect = {
        x: Math.round(ev.clientX - drag.areaBox.left - normal.w * ratio),
        y: Math.round(ev.clientY - drag.areaBox.top - offsetY),
        w: normal.w,
        h: normal.h
      };
      this._setState(win, 'normal', false);
    }

    // =======================================================================
    // === CARGA Y URL ACTUAL ===
    // =======================================================================

    _setLoading(win, on) {
      clearTimeout(win.loadingTimer);
      win.el.classList.toggle('is-loading', !!on);
      if (on) win.loadingTimer = setTimeout(() => win.el.classList.remove('is-loading'), LOADING_CAP_MS);
    }

    _onFrameLoad(win) {
      if (this.windows.get(win.key) !== win) return;   // ventana ya cerrada
      this._setLoading(win, false);
      this._syncUrl(win);
      // Mismo origen: clic dentro de la app → enfocar; salida del documento → progreso.
      // Otro origen: ambas cosas lanzan y se ignoran (queda el respaldo de `blur`).
      // `pagehide` y no `beforeunload`: este último también salta en navegaciones
      // que terminan en descarga (el documento se queda y no habría `load`).
      try {
        const doc = win.iframe.contentDocument;
        if (doc) doc.addEventListener('pointerdown', () => this.focus(win.key), true);
      } catch (err) { /* cross-origin */ }
      try {
        win.iframe.contentWindow.addEventListener('pagehide', () => this._setLoading(win, true));
      } catch (err) { /* cross-origin */ }
    }

    _readFrameUrl(win) {
      try {
        const loc = win.iframe.contentWindow.location;
        if (loc.protocol !== 'http:' && loc.protocol !== 'https:') return null;
        if (loc.origin !== window.location.origin) return null;
        return loc.pathname + loc.search + loc.hash;
      } catch (err) {
        return null;   // cross-origin: se conserva la última URL conocida
      }
    }

    _syncUrl(win) {
      const path = this._readFrameUrl(win);
      if (path && path !== win.url) this._setUrl(win, path);
    }

    _setUrl(win, path) {
      win.url = path;
      if (win.urlEl) win.urlEl.textContent = displayUrl(path);
      this._emit('window-navigated', win);
      if (isLogoutPath(path)) this.handleLogout();
    }

    _winBySource(source) {
      if (!source) return null;
      for (const win of this.windows.values()) {
        try {
          if (win.iframe.contentWindow === source) return win;
        } catch (err) { /* nada */ }
      }
      return null;
    }

    // =======================================================================
    // === ESCUCHAS GLOBALES ===
    // =======================================================================

    _bindGlobal() {
      // Mensajes de las apps embebidas (iframe_bridge.js y páginas propias).
      window.addEventListener('message', (event) => {
        if (event.origin !== window.location.origin) return;
        const data = event.data;
        if (!data || typeof data !== 'object' || typeof data.type !== 'string') return;
        switch (data.type) {
          case 'LOGOUT':
            this.handleLogout();
            break;
          case 'SESSION_EXPIRED':
            this.handleSessionExpired();
            break;
          case 'NAVIGATION': {
            const win = this._winBySource(event.source);
            const path = sameOriginPath(typeof data.fullUrl === 'string' ? data.fullUrl : data.url);
            if (win && path && path !== win.url) this._setUrl(win, path);
            break;
          }
          case 'CLOSE_APP':
          case 'GO_TO_DASHBOARD': {
            // La app pide salir (p. ej. 403 sin acceso): se cierra solo SU ventana.
            const win = this._winBySource(event.source);
            if (win) this.close(win.key);
            break;
          }
          case 'OPEN_URL':
            if (typeof data.url === 'string' && window.desktop && typeof window.desktop.openUrl === 'function') {
              window.desktop.openUrl(data.url);
            }
            break;
          default:
            break;
        }
      });

      // Clic dentro de un iframe: la página pierde el foco y el iframe queda como
      // elemento activo → enfocar su ventana (vale también para otro origen).
      window.addEventListener('blur', () => {
        setTimeout(() => {
          const ae = document.activeElement;
          const winEl = ae && ae.tagName === 'IFRAME' ? ae.closest('.app-window') : null;
          if (winEl && winEl.dataset.appId) this.focus(winEl.dataset.appId);
        }, 0);
      });

      // URL actual: hx-boost cambia la ruta con pushState sin `load`. Se sondea
      // solo lo visible y solo con la pestaña al frente.
      setInterval(() => {
        if (document.hidden) return;
        this.windows.forEach((win) => { if (!win.minimized) this._syncUrl(win); });
      }, URL_POLL_MS);

      // Ventana del navegador angosta: todas maximizadas.
      let raf = 0;
      window.addEventListener('resize', () => {
        if (raf) return;
        raf = requestAnimationFrame(() => {
          raf = 0;
          if (!isNarrow()) return;
          this.windows.forEach((win) => { if (win.state !== 'maximized') this._setState(win, 'maximized', false); });
        });
      });

      // Presencia en vivo: la app al frente es la que el usuario está mirando.
      document.addEventListener('desktop:active-changed', (e) => {
        try {
          if (window.CorePresenceHeartbeat) window.CorePresenceHeartbeat.reportApp(e.detail ? e.detail.key : null);
        } catch (err) { /* el latido no debe tumbar al escritorio */ }
      });
    }

    _emit(name, win) {
      document.dispatchEvent(new CustomEvent('desktop:' + name, {
        detail: { key: win.key, url: win.url, state: stateOf(win) }
      }));
    }
  }

  D.WindowManager = WindowManager;
})();
