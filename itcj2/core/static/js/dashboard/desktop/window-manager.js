/**
 * window-manager.js — ventanas del escritorio (`ItcjDesktop.wm`).
 *
 * Una ventana por app: abrir una ya abierta la trae al frente (y la restaura si
 * estaba minimizada). Estados: normal, maximizada, acoplada (izq/der) y
 * minimizada (ortogonal: una minimizada recuerda su estado anterior).
 *
 * Geometría: el JS la pone en línea según el estado (normal en px relativos al
 * área útil; maximizada y acopladas en %, así siguen al navegador solas). El
 * CSS (desktop-windows.css) solo pinta. Redimensión por 8 manijas
 * (`.window-resize[data-dir]`, mínimo 420×300); acople estilo Aero Snap al
 * arrastrar (vista previa `#snapPreview` a ≤ 8 px del borde izq/der/arriba);
 * la geometría normal de cada app se recuerda (session.js, en % del área útil)
 * y al achicar el navegador las ventanas normales se reacomodan para que su
 * barra de título siga a la vista.
 *
 * Eventos en `document` (CustomEvent, detail {key, url, state}):
 * desktop:window-opened, -focused, -minimized, -restored, -state, -moved,
 * -navigated, -closed; y desktop:active-changed (detail {key|null}).
 *
 * Todo acceso a `contentWindow`/`contentDocument` va en try/catch: un iframe de
 * otro origen (o una página de error) no debe romper enfocar, arrastrar ni cerrar.
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
  const SNAP_EDGE = 8;            // px del borde del área útil que activan la vista previa de acople
  const SNAP_GAP = 8;             // margen de la vista previa respecto al área útil
  const STATES = ['normal', 'maximized', 'snap-left', 'snap-right'];
  const RESIZE_CURSORS = {
    n: 'ns-resize', s: 'ns-resize', e: 'ew-resize', w: 'ew-resize',
    ne: 'nesw-resize', sw: 'nesw-resize', nw: 'nwse-resize', se: 'nwse-resize'
  };

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

  const stripHash = (path) => String(path || '').split('#')[0];

  /** Lo que se muestra en la barra de título: ruta legible, sin el hash. */
  function displayUrl(path) {
    const clean = stripHash(path);
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
      this.previewEl = null;      // #snapPreview (se crea al primer arrastre)
      this.area = this.workArea();   // última área útil conocida (para reacomodar al cambiar de tamaño)
      this._bindGlobal();
    }

    // =======================================================================
    // === API PÚBLICA (contrato compartido) ===
    // =======================================================================

    /**
     * Abre (o trae al frente) la ventana de `key`. opts: {url, state, rect, focus=true, animate=true}.
     * Sin `state`: normal con la geometría recordada de la app si la hay; si no, maximizada.
     */
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

    /** Acopla a la mitad izquierda/derecha o maximiza ('max'). Bajo 900 px siempre maximiza. */
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
      // Mismo documento con otro #hash: no hay `load`, así que no hay barra de progreso
      // (si no, se quedaba colgada hasta el tope de 30 s).
      const current = this._readFrameUrl(win) || win.url || '';
      const hashOnly = hit.url.includes('#') && stripHash(hit.url) === stripHash(current);
      if (!hashOnly) this._setLoading(win, true);
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

    /** `base` (extra): estado debajo del minimizado, para restaurar la sesión tal cual. */
    list() {
      return this.stack.map((key, i) => {
        const win = this.windows.get(key);
        return { key, url: win.url, state: stateOf(win), base: win.state, z: Z_BASE + i, rect: win.rect ? { ...win.rect } : null };
      });
    }

    /** Rect en px del área útil → % del área útil (sobrevive a cambios de resolución). */
    toPct(rect) {
      if (!rect) return null;
      const a = this.workArea();
      if (!(a.w > 0 && a.h > 0)) return null;
      const r2 = (v) => Math.round(v * 100) / 100;
      return { x: r2(rect.x / a.w * 100), y: r2(rect.y / a.h * 100), w: r2(rect.w / a.w * 100), h: r2(rect.h / a.h * 100) };
    }

    /** % del área útil → px (sin acotar: `open` la acomoda dentro del área). Inválido → null. */
    fromPct(pct) {
      if (!pct || typeof pct !== 'object') return null;
      const n = ['x', 'y', 'w', 'h'].map((k) => Number(pct[k]));
      if (!n.every(Number.isFinite)) return null;
      const a = this.workArea();
      return { x: n[0] * a.w / 100, y: n[1] * a.h / 100, w: n[2] * a.w / 100, h: n[3] * a.h / 100 };
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
      const saved = this._savedRect(app.key);
      let state = STATES.includes(o.state) ? o.state : (saved ? 'normal' : 'maximized');
      if (isNarrow()) state = 'maximized';
      this.area = this.workArea();

      const win = {
        key: app.key,
        app,
        url,
        state,
        minimized: false,
        rect: this._sanitizeRect(o.rect) || saved,   // maximizada también recuerda a qué rect vuelve
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
        </div>
        ${Object.keys(RESIZE_CURSORS).map((d) => `<div class="window-resize" data-dir="${d}" aria-hidden="true"></div>`).join('')}`;
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
      win.el.querySelectorAll('.window-resize').forEach((h) => {
        h.addEventListener('pointerdown', (e) => this._startResize(win, h, e));
      });
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
        // Solo la maximizada ofrece "Restaurar"; una acoplada se maximiza con este botón.
        const label = win.state === 'maximized' ? 'Restaurar' : 'Maximizar';
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

    /** Geometría recordada de la app (session.js, en %) → rect en px dentro del área, o null. */
    _savedRect(key) {
      try {
        const s = D.session;
        const pct = s && typeof s.loadGeometry === 'function' ? s.loadGeometry(key) : null;
        return pct ? this._sanitizeRect(this.fromPct(pct)) : null;
      } catch (err) {
        return null;   // storage bloqueado o datos raros: se abre como si no hubiera
      }
    }

    /** Fin de arrastre/redimensión: avisa y, si quedó en normal, recuerda su geometría. */
    _moved(win) {
      if (this.windows.get(win.key) !== win) return;
      if (win.state === 'normal' && win.rect) {
        try {
          if (D.session && typeof D.session.saveGeometry === 'function') D.session.saveGeometry(win.key, this.toPct(win.rect));
        } catch (err) { /* sin storage: no se recuerda */ }
      }
      this._emit('window-moved', win);
    }

    /**
     * Rect tras cambiar el área útil de `prev` a `area`: se encoge si ya no cabe y se
     * recorre hacia dentro sin dejar fuera más de lo que el usuario ya había dejado
     * fuera (una ventana pegada a la derecha sigue entera a la vista).
     */
    _reflowRect(r, prev, area) {
      const w = Math.min(r.w, area.w);
      const h = Math.min(r.h, area.h);
      const offRight = Math.max(0, r.x + r.w - prev.w);
      const offBottom = Math.max(0, r.y + r.h - prev.h);
      return this._fitRect({ x: Math.min(r.x, area.w - w + offRight), y: Math.min(r.y, area.h - h + offBottom), w, h });
    }

    _onViewportResize() {
      const prev = this.area || this.workArea();
      const area = this.workArea();
      this.area = area;
      if (isNarrow()) {
        this.windows.forEach((win) => { if (win.state !== 'maximized') this._setState(win, 'maximized', false); });
        return;
      }
      // Acopladas y maximizadas van en %: se recalculan solas. Las normales (y el
      // rect al que vuelven las demás) se reacomodan; esto no se guarda como geometría.
      this.windows.forEach((win) => {
        if (!win.rect) return;
        win.rect = this._reflowRect(win.rect, prev, area);
        if (win.state === 'normal') this._applyGeometry(win, false);
      });
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
    // === ARRASTRE POR LA BARRA DE TÍTULO (con acople estilo Aero Snap) ===
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
        rectBefore: win.rect ? { ...win.rect } : null,   // a dónde vuelve si el arrastre acaba acoplado
        moved: false,
        ended: false,
        origin: null,
        side: null                                         // borde bajo el puntero ('left'|'right'|'max')
      };
      try { tb.setPointerCapture(e.pointerId); } catch (err) { /* sin captura: sigue funcionando dentro de la barra */ }

      const move = (ev) => {
        if (ev.pointerId !== drag.id || drag.ended) return;
        if (!drag.moved) {
          if (Math.abs(ev.clientX - drag.startX) < DRAG_THRESHOLD && Math.abs(ev.clientY - drag.startY) < DRAG_THRESHOLD) return;
          drag.moved = true;
          document.body.classList.add('desktop-dragging');   // escudo: los iframes no se tragan el puntero
          this._stopTransition(win);
          if (win.state !== 'normal') {
            this._detachForDrag(win, drag, ev);
            drag.origin = { x: win.rect.x, y: win.rect.y, px: ev.clientX, py: ev.clientY };
          } else {
            // Desde el punto de agarre, no desde donde se pasó el umbral: el puntero no se despega.
            drag.origin = { x: win.rect.x, y: win.rect.y, px: drag.startX, py: drag.startY };
          }
        }
        const area = this.workArea();
        const r = win.rect;
        r.x = Math.round(clamp(drag.origin.x + ev.clientX - drag.origin.px, KEEP_VISIBLE - r.w, area.w - KEEP_VISIBLE));
        r.y = Math.round(clamp(drag.origin.y + ev.clientY - drag.origin.py, 0, area.h - TITLEBAR_H));
        win.el.style.left = r.x + 'px';
        win.el.style.top = r.y + 'px';
        const side = this._snapSideAt(ev.clientX, ev.clientY, drag.areaBox);
        if (side !== drag.side) {
          drag.side = side;
          this._showSnapPreview(side, drag.areaBox);
        }
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
        if (drag.side) this._showSnapPreview(null);
        if (!drag.moved || this.windows.get(win.key) !== win) return;
        // Soltar sobre un borde acopla (solo con `pointerup`: una cancelación no acopla).
        // La ventana recuerda el rect que tenía antes del arrastre para cuando se desacople.
        if (drag.side && ev.type === 'pointerup') {
          if (drag.rectBefore) win.rect = drag.rectBefore;
          this.snap(win.key, drag.side);
        } else {
          this._moved(win);
        }
      };
      tb.addEventListener('pointermove', move);
      tb.addEventListener('pointerup', end);
      tb.addEventListener('pointercancel', end);
      tb.addEventListener('lostpointercapture', end);
    }

    /**
     * Arrastrar una maximizada/acoplada la regresa a su rect normal bajo el cursor,
     * con el cursor en la misma proporción horizontal de la barra de título (como Windows).
     */
    _detachForDrag(win, drag, ev) {
      const normal = win.rect ? this._fitRect(win.rect) : this._defaultRect();
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

    /** Borde del área útil bajo el puntero que acoplaría la ventana: 'left' | 'right' | 'max' | null. */
    _snapSideAt(x, y, box) {
      if (isNarrow()) return null;
      if (x <= box.left + SNAP_EDGE) return 'left';
      if (x >= box.right - 1 - SNAP_EDGE) return 'right';
      if (y <= box.top + SNAP_EDGE) return 'max';
      return null;
    }

    /** Vista previa translúcida del acople (`#snapPreview`: una sola, creada al primer uso). */
    _showSnapPreview(side, box) {
      let el = this.previewEl;
      if (!side) {
        if (el) el.classList.remove('is-visible');
        return;
      }
      if (!el || !el.isConnected) {
        el = this.previewEl = document.createElement('div');
        el.id = 'snapPreview';
        el.className = 'snap-preview';
        el.setAttribute('aria-hidden', 'true');
        this.container.appendChild(el);
      }
      const g = SNAP_GAP;
      const half = box.width / 2;
      const wasVisible = el.classList.contains('is-visible');
      // Si estaba oculta aparece en su sitio (crece ahí) en vez de viajar desde el borde anterior.
      if (!wasVisible) el.style.transition = 'none';
      el.style.left = (side === 'right' ? box.left + half + g / 2 : box.left + g) + 'px';
      el.style.top = (box.top + g) + 'px';
      el.style.width = Math.max(0, side === 'max' ? box.width - 2 * g : half - g * 1.5) + 'px';
      el.style.height = Math.max(0, box.height - 2 * g) + 'px';
      el.dataset.side = side;
      if (!wasVisible) {
        void el.offsetWidth;   // fija la geometría antes de devolverle la transición
        el.style.transition = '';
      }
      el.classList.add('is-visible');
    }

    /** Corta la transición de maximizar/restaurar: arrastre y redimensión siguen al puntero ya. */
    _stopTransition(win) {
      clearTimeout(win.transitionTimer);
      win.el.classList.remove('is-transitioning');
    }

    // =======================================================================
    // === REDIMENSIÓN POR MANIJAS ===
    // =======================================================================

    _startResize(win, handle, e) {
      const dir = handle.dataset.dir || '';
      if (e.button !== 0 || !RESIZE_CURSORS[dir]) return;
      if (isNarrow() || win.minimized || win.state === 'maximized') return;
      e.preventDefault();
      const body = document.body;
      const rs = { id: e.pointerId, x: e.clientX, y: e.clientY, started: false, changed: false, ended: false };
      let area = null;
      let start = null;
      let minW = MIN_W;
      let minH = MIN_H;
      try { handle.setPointerCapture(e.pointerId); } catch (err) { /* sin captura: sigue mientras el puntero esté encima */ }
      body.classList.add('desktop-dragging', 'desktop-resizing');   // mismo escudo de iframes que el arrastre
      body.style.setProperty('--resize-cursor', RESIZE_CURSORS[dir]);

      // Al primer movimiento (un clic suelto en el borde no cambia nada): una acoplada
      // pasa a normal en el lugar que ocupa ahora y desde ahí se redimensiona.
      const begin = () => {
        this._stopTransition(win);
        if (win.state !== 'normal') {
          const box = win.el.getBoundingClientRect();
          const areaBox = this.container.getBoundingClientRect();
          win.rect = { x: box.left - areaBox.left, y: box.top - areaBox.top, w: box.width, h: box.height };
          this._setState(win, 'normal', false);
        }
        area = this.workArea();
        minW = Math.min(MIN_W, area.w);
        minH = Math.min(MIN_H, area.h);
        start = { ...win.rect };
      };

      const move = (ev) => {
        if (ev.pointerId !== rs.id || rs.ended) return;
        const dx = ev.clientX - rs.x;
        const dy = ev.clientY - rs.y;
        if (!rs.started) {
          if (!dx && !dy) return;
          rs.started = true;
          begin();
        }
        const right = start.x + start.w;
        const bottom = start.y + start.h;
        let { x, y, w, h } = start;
        // El borde que se jala sigue al puntero sin salirse del área útil (ni encoger
        // del mínimo); el opuesto queda fijo. Arriba nunca pasa de 0: la barra de título no se pierde.
        if (dir.includes('e')) w = clamp(right + dx, x + minW, Math.max(area.w, right)) - x;
        if (dir.includes('s')) h = clamp(bottom + dy, y + minH, Math.max(area.h, bottom)) - y;
        if (dir.includes('w')) { x = clamp(start.x + dx, Math.min(0, start.x), right - minW); w = right - x; }
        if (dir.includes('n')) { y = clamp(start.y + dy, 0, bottom - minH); h = bottom - y; }
        const r = { x: Math.round(x), y: Math.round(y), w: Math.round(w), h: Math.round(h) };
        const cur = win.rect;
        if (cur && r.x === cur.x && r.y === cur.y && r.w === cur.w && r.h === cur.h) return;
        win.rect = r;
        rs.changed = true;
        const st = win.el.style;
        st.left = r.x + 'px'; st.top = r.y + 'px'; st.width = r.w + 'px'; st.height = r.h + 'px';
      };
      const end = (ev) => {
        if (ev.pointerId !== rs.id || rs.ended) return;
        rs.ended = true;
        handle.removeEventListener('pointermove', move);
        handle.removeEventListener('pointerup', end);
        handle.removeEventListener('pointercancel', end);
        handle.removeEventListener('lostpointercapture', end);
        try { handle.releasePointerCapture(rs.id); } catch (err) { /* ya liberada */ }
        body.classList.remove('desktop-dragging', 'desktop-resizing');
        body.style.removeProperty('--resize-cursor');
        if (rs.changed) this._moved(win);
      };
      handle.addEventListener('pointermove', move);
      handle.addEventListener('pointerup', end);
      handle.addEventListener('pointercancel', end);
      handle.addEventListener('lostpointercapture', end);
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
        win.iframe.contentWindow.addEventListener('pagehide', () => {
          // Cerrar la ventana también descarga su documento: no re-armar el tope sobre un nodo suelto.
          if (this.windows.get(win.key) !== win) return;
          this._setLoading(win, true);
        });
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

      // Cambio de tamaño del navegador: angosta → todas maximizadas; si no, las
      // normales se reacomodan (barra de título alcanzable). Una vez por cuadro.
      let raf = 0;
      window.addEventListener('resize', () => {
        if (raf) return;
        raf = requestAnimationFrame(() => {
          raf = 0;
          this._onViewportResize();
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
