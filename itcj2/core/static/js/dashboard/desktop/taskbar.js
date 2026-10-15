/**
 * taskbar.js — barra de tareas estilo Windows 11.
 *
 * - Botones anclados (del servidor) + abiertas no ancladas al final
 *   (`data-dynamic="1"`, p. ej. Perfil y Configuración).
 * - Clic: cerrada → abre; abierta y no al frente (o minimizada) → la trae;
 *   al frente → la minimiza.
 * - Rayita: `is-open` (corta) / `is-active` (larga, acento). Los badges
 *   (`[data-badge-for]`) los pinta el widget de notificaciones.
 * - Reloj es-MX alineado al minuto e indicador de conexión (navigator.onLine +
 *   socket /notify compartido en `window.__notifySocket`).
 */
(function () {
  'use strict';

  const D = window.ItcjDesktop = window.ItcjDesktop || {};

  class Taskbar {
    constructor(opts) {
      this.registry = (opts && opts.registry) || D.registry;
      this.wm = (opts && opts.wm) || D.wm;
      this.apps = document.getElementById('taskbarApps');
      this.clockTimer = 0;
      this.socketState = 'unknown';   // unknown | up | down
      this.socketBound = false;

      this._bindApps();
      this._bindWindowEvents();
      this._startClock();
      this._bindConnection();
      this.refresh();
    }

    // === APPS ===
    _bindApps() {
      if (!this.apps) return;
      // Delegación: un solo listener aunque se agreguen botones dinámicos.
      this.apps.addEventListener('click', (e) => {
        const btn = e.target.closest('.taskbar-app[data-app]');
        if (btn && this.apps.contains(btn)) this.activate(btn.dataset.app);
      });
    }

    /** Comportamiento Win11 del clic en un botón de app. */
    activate(key) {
      const wm = this.wm;
      if (!wm) return;
      if (!wm.isOpen(key)) {
        wm.open(key);
      } else if (wm.getState(key) === 'minimized' || wm.activeKey() !== key) {
        wm.focus(key);
      } else {
        wm.minimize(key);
      }
    }

    _bindWindowEvents() {
      const sync = () => this.refresh();
      ['opened', 'closed', 'focused', 'minimized', 'restored'].forEach((n) => {
        document.addEventListener('desktop:window-' + n, sync);
      });
      document.addEventListener('desktop:active-changed', sync);
    }

    _button(key) {
      if (!this.apps) return null;
      return Array.from(this.apps.querySelectorAll('.taskbar-app[data-app]')).find((b) => b.dataset.app === key) || null;
    }

    _buildDynamic(app) {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'taskbar-app';
      btn.dataset.app = app.key;
      btn.dataset.dynamic = '1';
      btn.title = app.name;
      btn.setAttribute('aria-label', app.name);
      btn.innerHTML = D.appIcon(app, 24) +
        (app.badge_key ? '<span class="taskbar-badge" data-badge-for="' + D.escapeHtml(app.badge_key) + '" hidden>0</span>' : '') +
        '<span class="taskbar-app-indicator" aria-hidden="true"></span>';
      return btn;
    }

    /** Sincroniza botones dinámicos e indicadores con el gestor de ventanas. */
    refresh() {
      const wm = this.wm;
      if (!this.apps || !wm) return;
      const open = new Set(wm.list().map((w) => w.key));
      const active = wm.activeKey();

      // Abiertas no ancladas: agregar al final las que falten, quitar las cerradas.
      open.forEach((key) => {
        if (this._button(key)) return;
        const app = this.registry ? this.registry.get(key) : null;
        if (app) this.apps.appendChild(this._buildDynamic(app));
      });
      this.apps.querySelectorAll('.taskbar-app[data-dynamic="1"]').forEach((btn) => {
        if (!open.has(btn.dataset.app)) btn.remove();
      });

      this.apps.querySelectorAll('.taskbar-app[data-app]').forEach((btn) => {
        const key = btn.dataset.app;
        const isOpen = open.has(key);
        btn.classList.toggle('is-open', isOpen);
        btn.classList.toggle('is-active', isOpen && key === active);
        if (isOpen && key === active) btn.setAttribute('aria-current', 'true');
        else btn.removeAttribute('aria-current');
      });
    }

    // === RELOJ ===
    _startClock() {
      const time = document.getElementById('time');
      const date = document.getElementById('date');
      const box = document.getElementById('trayClock');
      if (!time && !date) return;
      const paint = () => {
        const now = new Date();
        if (time) time.textContent = now.toLocaleTimeString('es-MX', { hour: '2-digit', minute: '2-digit' });
        if (date) date.textContent = now.toLocaleDateString('es-MX', { day: '2-digit', month: '2-digit', year: 'numeric' });
        if (box) box.title = now.toLocaleDateString('es-MX', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' });
      };
      // Alineado al minuto: un solo temporizador que se reprograma en cada cambio.
      const schedule = () => {
        clearTimeout(this.clockTimer);
        const now = new Date();
        const wait = 60000 - (now.getSeconds() * 1000 + now.getMilliseconds()) + 50;
        this.clockTimer = setTimeout(() => { paint(); schedule(); }, wait);
      };
      paint();
      schedule();
      // Las pestañas de fondo retrasan los temporizadores: al volver, repintar.
      document.addEventListener('visibilitychange', () => {
        if (!document.hidden) { paint(); schedule(); }
      });
    }

    // === CONEXIÓN ===
    _bindConnection() {
      this.conn = document.getElementById('trayConnection');
      if (!this.conn) return;
      window.addEventListener('online', () => this._paintConnection());
      window.addEventListener('offline', () => this._paintConnection());
      // El socket lo abre el widget de notificaciones tras cargar socket.io:
      // puede no existir aún. Se reintenta al `load` y un par de veces más.
      this._attachSocket();
      window.addEventListener('load', () => this._attachSocket(), { once: true });
      [2000, 6000].forEach((ms) => setTimeout(() => this._attachSocket(), ms));
      this._paintConnection();
    }

    _attachSocket() {
      const socket = window.__notifySocket;
      if (this.socketBound || !socket || typeof socket.on !== 'function') return;
      this.socketBound = true;
      this.socketState = socket.connected ? 'up' : 'unknown';
      socket.on('connect', () => { this.socketState = 'up'; this._paintConnection(); });
      socket.on('disconnect', () => { this.socketState = 'down'; this._paintConnection(); });
      socket.on('connect_error', () => { this.socketState = 'down'; this._paintConnection(); });
      this._paintConnection();
    }

    _paintConnection() {
      if (!this.conn) return;
      const online = navigator.onLine !== false;
      const live = this.socketState !== 'down';
      const ok = online && live;
      const label = !online ? 'Sin conexión a internet'
        : !live ? 'Sin conexión con el servidor (reintentando)'
          : 'Conectado';
      this.conn.classList.toggle('is-online', ok);
      this.conn.classList.toggle('is-offline', !ok);
      this.conn.title = label;
      this.conn.setAttribute('aria-label', label);
    }
  }

  D.Taskbar = Taskbar;
})();
