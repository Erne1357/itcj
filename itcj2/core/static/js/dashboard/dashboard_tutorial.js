/**
 * dashboard_tutorial.js — tutorial guiado del escritorio (/itcj/dashboard).
 *
 * Lo carga bajo demanda desktop/tutorial-loader.js después de Shepherd 11.2.0
 * y solo expone `window.DashboardTutorialEntry = { autoStart(), start() }`.
 *
 * 14 pasos con ids estables (spec «Temas y tutorial» §C). Los pasivos solo
 * señalan (`canClickTarget: false`); los interactivos avanzan con la acción
 * real (`advanceOn`): doble clic en una app, minimizar, restaurar desde la
 * barra, cerrar, botón de inicio y campana. Cada interactivo trae además
 * «Hazlo por mí», que hace esa misma acción sobre el mismo elemento (salida
 * para teclado y pantallas táctiles). Cada paso prepara lo que necesita
 * (abre/cierra la ventana demo, el menú o el panel) y espera a que su elemento
 * exista, con tope, antes de mostrarse: así funcionan igual «Atrás» y reanudar.
 *
 * Salir (X, Esc u «Omitir») pide confirmación; «Continuar» reanuda en el paso
 * que vuelve a abrir lo que se cerró. Al completar u omitir se guarda
 * `localStorage['dashboard_tutorial_completed'] = 'true'`;
 * `dashboard_tutorial_mode_active` vale 'true' solo mientras corre.
 */
(function () {
  'use strict';

  // === CONFIGURACIÓN ===
  const STORAGE_KEY = 'dashboard_tutorial_completed';
  const MODE_KEY = 'dashboard_tutorial_mode_active';
  const WAIT_MS = 8000;          // tope de espera por el elemento de un paso
  const SETTLE_MS = 600;         // tope de espera por animaciones de entrada
  const OFFSET = 12;             // separación popover-objetivo (px)
  const EDGE = 8;                // margen mínimo con el borde de la pantalla (px)
  const HIT_PAD = 4;             // = modalOverlayOpeningPadding

  /** Al reanudar, los pasos que dependen de algo que la salida cerró vuelven al paso que lo abre. */
  const RESUME_TO = {
    'window-move': 'open-app',
    'window-controls': 'open-app',
    'minimize': 'open-app',
    'taskbar-restore': 'open-app',
    'close-window': 'open-app',
    'start-menu': 'start-open',
    'notifications-panel': 'notifications'
  };

  const D = () => window.ItcjDesktop || {};

  // === UTILIDADES ===
  const storage = {
    get(key) {
      try { return localStorage.getItem(key); } catch (err) { return null; }
    },
    set(key, value) {
      try { localStorage.setItem(key, value); } catch (err) { /* sin storage */ }
    },
    remove(key) {
      try { localStorage.removeItem(key); } catch (err) { /* sin storage */ }
    }
  };

  function escapeHtml(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  /** Icono del sprite del escritorio, en línea con el texto. */
  function ico(name) {
    const icon = D().icon;
    return typeof icon === 'function' ? icon(name, 'tutorial-ico') : '';
  }

  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const q = (selector) => document.querySelector(selector);
  const has = (selector) => !!q(selector);

  function attr(value) {
    return window.CSS && typeof CSS.escape === 'function' ? CSS.escape(value) : String(value).replace(/"/g, '\\"');
  }

  function isShown(el) {
    if (!el || !el.isConnected) return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== 'hidden';
  }

  /** Espera a que `probe()` devuelva un elemento (tope `ms`); null si no aparece. */
  function waitFor(probe, ms) {
    return new Promise((resolve) => {
      const started = Date.now();
      const check = () => {
        let el = null;
        try { el = probe(); } catch (err) { el = null; }
        if (el) return resolve(el);
        if (Date.now() - started >= ms) return resolve(null);
        setTimeout(check, 50);
      };
      check();
    });
  }

  /** Espera a que terminen las animaciones finitas (entrada, minimizar…) del elemento y su contenedor. */
  async function settle(el) {
    if (!el) return;
    const hosts = new Set([el, el.closest('.app-window, #startMenu, #notification-panel')]);
    const pending = [];
    hosts.forEach((host) => {
      if (!host || typeof host.getAnimations !== 'function') return;
      host.getAnimations().forEach((a) => {
        try {
          const end = a.effect && a.effect.getComputedTiming().endTime;
          if (Number.isFinite(end)) pending.push(a.finished.catch(() => undefined));
        } catch (err) { /* animación ya cancelada */ }
      });
    });
    if (pending.length) await Promise.race([Promise.all(pending), sleep(SETTLE_MS)]);
  }

  // === POSICIONAMIENTO (middleware de Floating UI dentro de Shepherd) ===
  /**
   * Elige el primer lado de `prefs` donde el popover cabe completo sin tapar
   * el objetivo; si ninguno, el que deja más espacio. Corre una vez por cálculo
   * (los `reset` de flip/shift no lo repiten) y deja a shift ajustar el resto.
   */
  function preferPlacement(prefs) {
    return {
      name: 'itcjPlacement',
      fn(state) {
        const prev = state.middlewareData.itcjPlacement;
        if (prev && prev.done) return {};
        const ref = state.rects.reference;
        const fl = state.rects.floating;
        const vw = document.documentElement.clientWidth;
        const vh = document.documentElement.clientHeight;
        const gap = OFFSET + EDGE;
        const room = {
          top: ref.y - gap,
          bottom: vh - (ref.y + ref.height) - gap,
          left: ref.x - gap,
          right: vw - (ref.x + ref.width) - gap
        };
        const need = (side) => (side === 'top' || side === 'bottom' ? fl.height : fl.width);
        const sideOf = (p) => p.split('-')[0];
        let best = prefs.find((p) => room[sideOf(p)] >= need(sideOf(p)));
        if (!best) {
          best = prefs.slice().sort((a, b) => (room[sideOf(b)] - need(sideOf(b))) - (room[sideOf(a)] - need(sideOf(a))))[0];
        }
        const data = { done: true };
        return best && best !== state.placement ? { data, reset: { placement: best } } : { data };
      }
    };
  }

  /** Separa el popover del objetivo (la flecha apunta al hueco). */
  const offsetMiddleware = {
    name: 'itcjOffset',
    fn({ x, y, placement }) {
      const side = placement.split('-')[0];
      if (side === 'top') return { y: y - OFFSET };
      if (side === 'bottom') return { y: y + OFFSET };
      if (side === 'left') return { x: x - OFFSET };
      return { x: x + OFFSET };
    }
  };

  // === CLASE PRINCIPAL ===
  class DashboardTutorial {
    constructor() {
      this.tour = null;
      this.isRunning = false;
      this.lastStepId = null;
      this.resumeTarget = null;
      this.demoKey = null;
      this.available = [];
      this.listeners = null;
      this.mundialWasOpen = false;
      this.panelLoading = null;
      this.iconsArea = null;
    }

    // === ESTADO PERSISTENTE ===
    hasCompleted() {
      return storage.get(STORAGE_KEY) === 'true';
    }

    markComplete() {
      storage.set(STORAGE_KEY, 'true');
      storage.remove(MODE_KEY);
    }

    setMode(on) {
      if (on) storage.set(MODE_KEY, 'true');
      else storage.remove(MODE_KEY);
    }

    setButtonBusy(busy) {
      const btn = document.getElementById('dashboardTutorialButton');
      if (btn) btn.disabled = !!busy;
    }

    // === ENTORNO DEL ESCRITORIO ===
    wm() {
      return D().wm || null;
    }

    demoWindow() {
      return this.demoKey ? q('.app-window[data-app-id="' + attr(this.demoKey) + '"]') : null;
    }

    demoState() {
      const wm = this.wm();
      return wm && this.demoKey ? wm.getState(this.demoKey) : null;
    }

    demoName() {
      const reg = D().registry;
      const app = reg && this.demoKey ? reg.get(this.demoKey) : null;
      return app && app.name ? app.name : 'la aplicación';
    }

    /** Help Desk si está en el escritorio; si no, la primera app (para no atascar a quien no la tiene). */
    pickDemoKey() {
      const reg = D().registry;
      const usable = (key) => !!(key && reg && reg.get(key));
      if (has('.desktop-icon[data-app="helpdesk"]') && usable('helpdesk')) return 'helpdesk';
      const tiles = Array.from(document.querySelectorAll('.desktop-icon[data-app]:not(.is-decorative)'));
      const tile = tiles.find((t) => usable(t.getAttribute('data-app')));
      return tile ? tile.getAttribute('data-app') : null;
    }

    closeWindows() {
      if (window.desktop && typeof window.desktop.closeAllWindows === 'function') window.desktop.closeAllWindows();
    }

    /** La ventana demo abierta, al frente y sin minimizar. */
    showDemo() {
      const wm = this.wm();
      if (!wm || !this.demoKey) return;
      if (!wm.isOpen(this.demoKey)) {
        if (window.desktop && typeof window.desktop.openApplication === 'function') window.desktop.openApplication(this.demoKey);
      } else if (wm.getState(this.demoKey) === 'minimized') {
        wm.restore(this.demoKey);
      } else {
        wm.focus(this.demoKey);
      }
    }

    /** La ventana demo abierta pero minimizada. */
    minimizeDemo() {
      const wm = this.wm();
      if (!wm || !this.demoKey) return;
      if (!wm.isOpen(this.demoKey)) this.showDemo();
      if (wm.isOpen(this.demoKey) && wm.getState(this.demoKey) !== 'minimized') wm.minimize(this.demoKey);
    }

    openStartMenu() {
      const menu = D().startMenu;
      if (menu && typeof menu.open === 'function') menu.open('menu');
    }

    closeStartMenu() {
      const menu = D().startMenu;
      if (menu && typeof menu.close === 'function') menu.close();
    }

    /** ¿La barra solo muestra la lupa y la búsqueda se escribe en el menú de inicio? */
    searchInMenu() {
      const menu = D().startMenu;
      return !!(menu && typeof menu.searchInMenu === 'function' && menu.searchInMenu());
    }

    closeDemo() {
      const wm = this.wm();
      if (wm && this.demoKey && wm.isOpen(this.demoKey)) wm.close(this.demoKey);
    }

    widget() {
      return window.dashboardNotificationWidget || null;
    }

    /** Abre el panel REAL de notificaciones (el widget carga las recientes). */
    openPanel() {
      const w = this.widget();
      if (!w || typeof w.togglePanel !== 'function') return;
      if (!w.panelOpen) this.panelLoading = Promise.resolve(w.togglePanel()).catch(() => undefined);
    }

    closePanel() {
      const w = this.widget();
      if (w && typeof w.closePanel === 'function') w.closePanel();
    }

    mundialWidgetOpen() {
      const m = window.mundialTheme;
      return !!(m && m.widget && !m.widget.classList.contains('hidden'));
    }

    /** Estado inicial: sin ventanas, menú, panel ni widget del Mundial. */
    prepareEnvironment() {
      this.closeWindows();
      this.closeStartMenu();
      this.closePanel();
      if (this.mundialWidgetOpen()) {
        this.mundialWasOpen = true;
        try { window.mundialTheme.toggleWidget(false); } catch (err) { /* el tema no debe frenar el tutorial */ }
      }
    }

    /** Recuadro (invisible) que abarca todos los iconos: objetivo del paso «desktop-apps». */
    buildIconsArea() {
      const icons = Array.from(document.querySelectorAll('#desktop-grid .desktop-icon')).filter(isShown);
      if (!icons.length) return null;
      const box = icons.reduce((acc, el) => {
        const r = el.getBoundingClientRect();
        return {
          l: Math.min(acc.l, r.left), t: Math.min(acc.t, r.top),
          r: Math.max(acc.r, r.right), b: Math.max(acc.b, r.bottom)
        };
      }, { l: Infinity, t: Infinity, r: -Infinity, b: -Infinity });
      let el = this.iconsArea;
      if (!el || !el.isConnected) {
        el = this.iconsArea = document.createElement('div');
        el.id = 'tutorialIconsArea';
        el.className = 'dashboard-tutorial-area';
        el.setAttribute('aria-hidden', 'true');
        document.body.appendChild(el);
      }
      Object.assign(el.style, {
        left: box.l + 'px', top: box.t + 'px',
        width: (box.r - box.l) + 'px', height: (box.b - box.t) + 'px'
      });
      return el;
    }

    removeIconsArea() {
      if (this.iconsArea) this.iconsArea.remove();
      this.iconsArea = null;
    }

    // === GUARDAS DE INTERACCIÓN ===
    /**
     * Mientras corre el tour:
     *  - un toque en el popover no cierra el menú inicio (cierra con pointerdown
     *    fuera) ni el panel (cierra con click fuera; ese click se corta en el popover);
     *  - la zona atenuada no hace nada;
     *  - en los pasos pasivos el objetivo señalado no se puede usar;
     *  - Esc pide confirmar la salida; ni Ctrl+K ni teclear con el foco en la barra
     *    o el menú (búsqueda al teclear de start-menu.js) abren el buscador bajo el
     *    atenuado;
     *  - abrir la app demo con Enter también avanza «open-app».
     */
    installGuards() {
      if (this.listeners) return;
      const typesIntoSearch = (e) => {
        const t = e.target;
        return typeof e.key === 'string' && e.key.length === 1 && e.key !== ' ' && !e.ctrlKey && !e.metaKey && !e.altKey &&
          !!(t && t.closest && !t.closest('.shepherd-element') && t.closest('.taskbar, #startMenu'));
      };
      const onPointer = (e) => {
        if (!this.isRunning) return;
        const t = e.target;
        const inside = (sel) => !!(t && t.closest && t.closest(sel));
        if (inside('.shepherd-element')) {
          if (e.type === 'pointerdown' || e.type === 'mousedown') e.stopPropagation();
          return;
        }
        if (inside('.shepherd-modal-overlay-container') || this.hitsPassiveTarget(e)) {
          e.stopPropagation();
          if (e.cancelable && e.type !== 'pointerdown') e.preventDefault();
        }
      };
      const onKey = (e) => {
        if (!this.isRunning || !this.tour || q('.modal.show')) return;
        if (e.key === 'Escape') {
          e.preventDefault();
          e.stopPropagation();
          this.tour.cancel();
        } else if (((e.ctrlKey || e.metaKey) && String(e.key).toLowerCase() === 'k') || typesIntoSearch(e)) {
          // Abrirían el buscador debajo del atenuado: durante el tour solo se explica.
          e.preventDefault();
          e.stopPropagation();
        }
      };
      const onResize = () => {
        if (this.iconsArea && this.lastStepId === 'desktop-apps') this.buildIconsArea();
      };
      const onWindowOpened = (e) => {
        const step = this.tour && this.tour.getCurrentStep();
        if (step && step.id === 'open-app' && step.isOpen() && e.detail && e.detail.key === this.demoKey) this.tour.next();
      };
      const pointerTypes = ['pointerdown', 'mousedown', 'click', 'dblclick', 'contextmenu'];
      pointerTypes.forEach((type) => window.addEventListener(type, onPointer, true));
      window.addEventListener('keydown', onKey, true);
      window.addEventListener('resize', onResize);
      document.addEventListener('desktop:window-opened', onWindowOpened);
      this.listeners = () => {
        pointerTypes.forEach((type) => window.removeEventListener(type, onPointer, true));
        window.removeEventListener('keydown', onKey, true);
        window.removeEventListener('resize', onResize);
        document.removeEventListener('desktop:window-opened', onWindowOpened);
      };
    }

    removeGuards() {
      if (this.listeners) this.listeners();
      this.listeners = null;
    }

    /** ¿El evento cae sobre el objetivo de un paso pasivo? (un clic de teclado no cuenta) */
    hitsPassiveTarget(e) {
      if (e.type === 'click' && e.detail === 0) return false;
      const step = this.tour && this.tour.getCurrentStep();
      if (!step || !step.isOpen() || step.options.canClickTarget !== false) return false;
      const target = step.target;
      if (!target || target === document.body || !target.getBoundingClientRect) return false;
      const r = target.getBoundingClientRect();
      return e.clientX >= r.left - HIT_PAD && e.clientX <= r.right + HIT_PAD &&
        e.clientY >= r.top - HIT_PAD && e.clientY <= r.bottom + HIT_PAD;
    }

    // === PASOS ===
    buttons(kind, label) {
      const tour = () => this.tour;
      const back = { text: 'Atrás', secondary: true, action: () => tour().back() };
      if (kind === 'back') return [back];
      if (kind === 'welcome') {
        return [
          { text: 'Omitir', secondary: true, action: () => tour().cancel() },
          { text: 'Comenzar', action: () => tour().next() }
        ];
      }
      if (kind === 'done') return [back, { text: 'Finalizar', action: () => tour().complete() }];
      return [back, { text: label || 'Siguiente', action: () => tour().next() }];
    }

    stepDefs() {
      const self = this;
      const narrow = () => window.innerWidth < 900;
      const demo = () => escapeHtml(self.demoName());
      const win = (sel) => () => {
        const el = self.demoWindow();
        const part = el && self.demoState() !== 'minimized' ? el.querySelector(sel) : null;
        return isShown(part) ? part : null;
      };
      const taskbarBtn = () => (self.demoKey ? q('.taskbar-app[data-app="' + attr(self.demoKey) + '"]') : null);

      return [
        {
          id: 'welcome',
          title: 'Bienvenido a la Plataforma Digital ITCJ',
          text: () => '<p>Este es tu escritorio: aquí abres las aplicaciones del Tecnológico en ventanas, como en Windows.</p>' +
            '<p>En un par de minutos te mostramos cómo abrir y acomodar ventanas, la barra de tareas, el buscador, el menú de inicio y las notificaciones.</p>' +
            '<p class="tutorial-note">Puedes salir cuando quieras con la X o la tecla <kbd>Esc</kbd>.</p>',
          buttons: 'welcome'
        },
        {
          id: 'desktop-apps',
          title: 'Tus aplicaciones',
          text: () => '<p>Cada icono del escritorio es una aplicación a la que tienes acceso; las que ves dependen de tus permisos.</p>' +
            '<p>Para abrir una haz <strong>doble clic</strong> en su icono, o selecciónala y presiona <kbd>Enter</kbd>.</p>',
          passive: true,
          place: ['bottom', 'right', 'top'],
          prepare: () => self.closeWindows(),
          target: () => self.buildIconsArea(),
          onHide: () => self.removeIconsArea(),
          available: () => has('#desktop-grid .desktop-icon')
        },
        {
          id: 'open-app',
          title: 'Abre una aplicación',
          text: () => '<p>Haz <strong>doble clic</strong> en <strong>' + demo() + '</strong> para abrirla.</p>',
          place: ['right', 'bottom', 'left', 'top'],
          prepare: () => { self.closeWindows(); self.closeStartMenu(); },
          target: () => {
            const el = self.demoKey ? q('.desktop-icon[data-app="' + attr(self.demoKey) + '"]') : null;
            return isShown(el) ? el : null;
          },
          advanceOn: () => ({ selector: '.desktop-icon[data-app="' + attr(self.demoKey) + '"]', event: 'dblclick' }),
          doIt: () => self.showDemo(),
          buttons: 'back',
          demo: true
        },
        {
          id: 'window-move',
          title: 'Mueve y acomoda la ventana',
          text: () => (narrow()
            ? '<p>La aplicación se abrió en una ventana. En una pantalla angosta como esta, las ventanas ocupan todo el escritorio.</p>' +
              '<p>En una pantalla más ancha puedes arrastrarlas por la <strong>barra de título</strong> y acoplarlas a una mitad de la pantalla.</p>'
            : '<p>La aplicación se abrió en una ventana. Arrastra su <strong>barra de título</strong> para moverla.</p>' +
              '<ul><li>Llévala al borde izquierdo o derecho para acoplarla a esa mitad, o arriba para maximizarla.</li>' +
              '<li>Doble clic en la barra la maximiza o la restaura.</li>' +
              '<li>Arrastra sus bordes para cambiar el tamaño.</li></ul>') +
            '<p>Si recargas la página, tus ventanas vuelven donde las dejaste.</p>',
          passive: true,
          place: ['bottom', 'top'],
          prepare: () => self.showDemo(),
          target: win('.window-titlebar'),
          demo: true
        },
        {
          id: 'window-controls',
          title: 'Botones de la ventana',
          text: () => '<ul class="tutorial-list">' +
            '<li>' + ico('refresh') + '<span><strong>Recargar</strong> la aplicación.</span></li>' +
            '<li>' + ico('external') + '<span><strong>Abrir en una pestaña</strong> nueva del navegador.</span></li>' +
            '<li>' + ico('minus') + '<span><strong>Minimizar</strong>: la esconde en la barra de tareas.</span></li>' +
            '<li>' + ico('square') + '<span><strong>Maximizar</strong> o restaurar.</span></li>' +
            '<li>' + ico('x') + '<span><strong>Cerrar</strong> la aplicación.</span></li></ul>',
          passive: true,
          place: ['bottom', 'left'],
          prepare: () => self.showDemo(),
          target: win('.window-controls'),
          demo: true
        },
        {
          id: 'minimize',
          title: 'Minimiza la ventana',
          text: () => '<p>Haz clic en <strong>Minimizar</strong> ' + ico('minus') + '. La ventana se esconde, pero la aplicación sigue abierta.</p>',
          place: ['bottom', 'left'],
          prepare: () => self.showDemo(),
          target: win('.window-control.minimize'),
          advanceOn: () => ({ selector: '.app-window[data-app-id="' + attr(self.demoKey) + '"] .window-control.minimize', event: 'click' }),
          doIt: () => self.minimizeDemo(),
          buttons: 'back',
          demo: true
        },
        {
          id: 'taskbar-restore',
          title: 'Tráela de vuelta',
          text: () => '<p>La rayita bajo el icono de <strong>' + demo() + '</strong> en la barra de tareas indica que sigue abierta.</p>' +
            '<p>Haz clic en el icono para volver a mostrar la ventana. Si ya está al frente, ese mismo clic la minimiza.</p>',
          place: ['top'],
          prepare: () => self.minimizeDemo(),
          target: () => {
            const btn = taskbarBtn();
            return self.demoState() === 'minimized' && isShown(btn) ? btn : null;
          },
          advanceOn: () => ({ selector: '.taskbar-app[data-app="' + attr(self.demoKey) + '"]', event: 'click' }),
          doIt: () => self.showDemo(),
          buttons: 'back',
          demo: true
        },
        {
          id: 'close-window',
          title: 'Cierra la ventana',
          text: () => '<p>Haz clic en <strong>Cerrar</strong> ' + ico('x') + '. Cuando la necesites, vuelves a abrirla desde su icono.</p>',
          place: ['bottom', 'left'],
          prepare: () => self.showDemo(),
          target: win('.window-control.close'),
          advanceOn: () => ({ selector: '.app-window[data-app-id="' + attr(self.demoKey) + '"] .window-control.close', event: 'click' }),
          doIt: () => self.closeDemo(),
          buttons: 'back',
          demo: true
        },
        {
          id: 'search',
          title: 'Busca una aplicación',
          // Con la barra estrecha el campo se colapsa a la lupa y la búsqueda se escribe en el menú de inicio.
          text: () => (self.searchInMenu()
            ? '<p>Con la lupa ' + ico('search') + ' de la barra de tareas encuentras cualquier aplicación por su nombre: haz clic en ella, o pulsa <kbd>Ctrl</kbd> + <kbd>K</kbd>, y escribe. La búsqueda se abre en el menú de inicio.</p>' +
              '<p><kbd>Enter</kbd> abre la primera de la lista.</p>'
            : '<p>Con el buscador de la barra de tareas encuentras cualquier aplicación por su nombre; <kbd>Enter</kbd> abre la primera de la lista.</p>' +
              '<p>Desde cualquier parte del escritorio, <kbd>Ctrl</kbd> + <kbd>K</kbd> te lleva directo al buscador.</p>'),
          passive: true,
          place: ['top'],
          prepare: () => { self.closeStartMenu(); self.closePanel(); },
          target: () => { const el = q('.taskbar-search'); return isShown(el) ? el : null; },
          available: () => has('.taskbar-search')
        },
        {
          id: 'start-open',
          title: 'Menú de inicio',
          text: () => '<p>Haz clic en el botón de <strong>Inicio</strong> ' + ico('menu') + ' para abrir el menú.</p>',
          place: ['top', 'right'],
          prepare: () => { self.closeStartMenu(); self.closePanel(); },
          target: () => { const el = q('.start-button'); return isShown(el) ? el : null; },
          advanceOn: () => ({ selector: '.start-button', event: 'click' }),
          doIt: () => self.openStartMenu(),
          buttons: 'back',
          available: () => has('.start-button') && has('#startMenu') && !!D().startMenu
        },
        {
          id: 'start-menu',
          title: 'Dentro del menú de inicio',
          text: () => '<ul class="tutorial-list">' +
            '<li>' + ico('grid') + '<span><strong>Aplicaciones:</strong> aquí basta un clic para abrirlas.</span></li>' +
            '<li>' + ico('user') + '<span><strong>Tu tarjeta</strong>, con tu nombre y puesto, abre tu perfil.</span></li>' +
            '<li>' + ico('settings') + '<span>El engrane abre la <strong>Configuración</strong>, si tienes permiso.</span></li>' +
            '<li>' + ico('log-out') + '<span><strong>Cerrar sesión</strong>.</span></li></ul>',
          passive: true,
          place: ['right', 'left', 'top'],
          prepare: () => { self.closePanel(); self.openStartMenu(); },
          target: () => { const el = q('#startMenu'); return el && !el.hidden && isShown(el) ? el : null; },
          available: () => has('.start-button') && has('#startMenu') && !!D().startMenu
        },
        {
          id: 'notifications',
          title: 'Notificaciones',
          text: () => '<p>La campana reúne los avisos de todas tus aplicaciones. El número rojo indica cuántos no has leído; los iconos de cada aplicación muestran también los suyos.</p>' +
            '<p>Haz clic en la campana o en <strong>Ver notificaciones</strong>.</p>',
          place: ['top', 'left'],
          prepare: () => { self.closeStartMenu(); self.closePanel(); },
          target: () => { const el = q('#notificationBell'); return isShown(el) ? el : null; },
          advanceOn: () => ({ selector: '#notificationBell', event: 'click' }),
          buttons: 'notifications',
          available: () => has('#notificationBell') && !!self.widget()
        },
        {
          id: 'notifications-panel',
          title: 'Tus avisos recientes',
          text: () => '<p>Un clic en un aviso te lleva a donde corresponde; <strong>Marcar todas</strong> los da por leídos.</p>' +
            '<p><strong>Ver todas las notificaciones</strong> abre la pestaña Notificaciones de tu perfil, con el historial completo.</p>',
          passive: true,
          place: ['left', 'top'],
          prepare: () => { self.closeStartMenu(); self.openPanel(); },
          target: () => { const el = q('#notification-panel'); return el && !el.hidden && isShown(el) ? el : null; },
          afterWait: () => Promise.race([self.panelLoading || Promise.resolve(), sleep(3000)]),
          available: () => has('#notificationBell') && !!self.widget()
        },
        {
          id: 'done',
          title: '¡Listo!',
          text: () => '<p>Ya conoces lo esencial del escritorio.</p>' +
            '<p>Para repasarlo cuando quieras, usa el botón <strong>Tutorial</strong> ' + ico('help') + ' de la barra de tareas.</p>',
          prepare: () => { self.closePanel(); self.closeStartMenu(); self.closeWindows(); },
          buttons: 'done'
        }
      ];
    }

    isAvailable(def) {
      if (def.demo && !(this.demoKey && this.wm() && window.desktop)) return false;
      return typeof def.available === 'function' ? !!def.available() : true;
    }

    /** Opciones de Shepherd para un paso. */
    buildStep(def) {
      const self = this;
      const interactive = typeof def.advanceOn === 'function';
      const kind = def.buttons || 'next';
      // «Ver notificaciones» abre el panel real y avanza (igual que un clic en la campana).
      let regular = kind === 'notifications'
        ? this.buttons('back').concat([{ text: 'Ver notificaciones', action: () => { self.openPanel(); self.tour.next(); } }])
        : this.buttons(kind);
      if (interactive && typeof def.doIt === 'function') {
        regular = regular.concat([{
          text: 'Hazlo por mí',
          secondary: true,
          classes: 'dashboard-tutorial-doit',
          action: () => self.doItForMe(def)
        }]);
      }
      const fallback = this.buttons('next');
      const opts = {
        id: def.id,
        title: def.title,
        text: def.text,
        buttons: regular,
        canClickTarget: !def.passive,
        showOn: () => {
          if (!self.available.includes(def.id)) return false;
          if (self.resumeTarget) {
            if (self.resumeTarget !== def.id) return false;
            self.resumeTarget = null;
          }
          return true;
        },
        when: {
          show() { self.onStepShown(this, def); },
          hide() { self.onStepHidden(def); }
        }
      };
      if (def.target) {
        opts.attachTo = { element: () => def.target(), on: (def.place && def.place[0]) || 'bottom' };
        opts.floatingUIOptions = { middleware: [preferPlacement(def.place || ['bottom']), offsetMiddleware] };
      }
      if (interactive) opts.advanceOn = def.advanceOn();
      if (def.prepare || def.target) {
        opts.beforeShowPromise = () => self.prepareStep(def, { interactive, regular, fallback });
      }
      return opts;
    }

    /**
     * Antes de mostrar un paso: deja que termine el evento que lo disparó, prepara
     * el escritorio, espera su elemento (tope WAIT_MS) y sus animaciones. Si el
     * elemento no aparece, el paso se muestra centrado y con «Siguiente». Si
     * mientras tanto el tour terminó o cambió de paso, nunca se muestra.
     */
    async prepareStep(def, cfg) {
      const tour = this.tour;
      const step = tour && tour.getById(def.id);
      await sleep(0);
      if (def.prepare) {
        try { def.prepare(); } catch (err) { console.warn('[DashboardTutorial] preparar', def.id, err); }
      }
      let el = null;
      if (def.target) {
        el = await waitFor(def.target, WAIT_MS);
        if (el) await settle(el);
        if (!el) console.warn('[DashboardTutorial] no apareció el elemento del paso', def.id);
      }
      if (def.afterWait) await def.afterWait();
      if (!step || tour !== this.tour || !this.isRunning || !tour.isActive() || tour.getCurrentStep() !== step) {
        return new Promise(() => {});
      }
      if (cfg.interactive) {
        step.options.advanceOn = el ? def.advanceOn() : undefined;
        step.options.buttons = el ? cfg.regular : cfg.fallback;
      }
      return undefined;
    }

    /**
     * «Hazlo por mí» (pasos interactivos): dispara sobre el mismo elemento el
     * mismo evento que escucha `advanceOn` (doble clic en el icono, clic en
     * minimizar, en la barra, en cerrar o en Inicio). Corren los manejadores
     * reales del escritorio y el avance de Shepherd: mismo paso siguiente y mismo
     * estado que si lo hubiera hecho el usuario. Red por si el evento no avanzó
     * (elemento cambiado): la acción por la API del escritorio y `next()`.
     */
    doItForMe(def) {
      const tour = this.tour;
      const step = tour && tour.getCurrentStep();
      if (!step || step.id !== def.id || !step.isOpen()) return;
      const stillHere = () => this.tour === tour && tour.isActive() && tour.getCurrentStep() === step && step.isOpen();
      const how = def.advanceOn();
      let el = null;
      try { el = q(how.selector); } catch (err) { el = null; }
      if (el) {
        if (how.event === 'click' && typeof el.click === 'function') el.click();
        else el.dispatchEvent(new MouseEvent(how.event, { bubbles: true, cancelable: true, view: window, detail: 2 }));
      }
      if (!stillHere()) return;
      try { def.doIt(); } catch (err) { console.warn('[DashboardTutorial] Hazlo por mí', def.id, err); }
      if (stillHere()) tour.next();
    }

    onStepShown(step, def) {
      this.lastStepId = def.id;
      const el = step.getElement();
      if (!el) return;
      // El click de un botón del popover no debe llegar al documento (cerraría el panel).
      el.addEventListener('click', (e) => e.stopPropagation());
      const n = this.available.indexOf(def.id) + 1;
      if (n > 0) {
        const footer = el.querySelector('.shepherd-footer');
        const progress = document.createElement('span');
        progress.className = 'dashboard-tutorial-progress';
        progress.textContent = 'Paso ' + n + ' de ' + this.available.length;
        if (footer) footer.insertBefore(progress, footer.firstChild);
        else {
          const content = el.querySelector('.shepherd-content');
          if (content) content.appendChild(progress);
        }
      }
    }

    onStepHidden(def) {
      if (def.onHide) {
        try { def.onHide(); } catch (err) { /* nada */ }
      }
      // Entre un paso y el siguiente (que puede esperar a una ventana) el
      // atenuado se queda: sin parpadeo y sin clics sueltos al escritorio.
      if (this.isRunning && this.tour && this.tour.modal && typeof this.tour.modal.show === 'function') {
        this.tour.modal.show();
      }
    }

    // === CICLO DE VIDA ===
    createTour() {
      const tour = new window.Shepherd.Tour({
        useModalOverlay: true,
        exitOnEsc: false,           // Esc lo maneja installGuards (pide confirmación)
        keyboardNavigation: false,  // las flechas no saltan pasos interactivos
        defaultStepOptions: {
          classes: 'dashboard-tutorial-step',
          cancelIcon: { enabled: true, label: 'Salir del tutorial' },
          scrollTo: false,
          arrow: true,
          modalOverlayOpeningPadding: HIT_PAD,
          modalOverlayOpeningRadius: 8
        }
      });
      this.tour = tour;
      this.demoKey = this.pickDemoKey();
      const defs = this.stepDefs();
      this.available = defs.filter((d) => this.isAvailable(d)).map((d) => d.id);
      defs.forEach((def) => tour.addStep(this.buildStep(def)));
      tour.on('cancel', () => { if (this.tour === tour) this.onCancel(); });
      tour.on('complete', () => { if (this.tour === tour) this.onComplete(); });
      return tour;
    }

    /** Arranca el tour; con `resumeId`, directo en ese paso (sin pasar por los anteriores). */
    startTutorial(resumeId) {
      if (this.isRunning) return;
      if (!window.Shepherd || typeof window.Shepherd.Tour !== 'function') {
        console.error('[DashboardTutorial] Shepherd no está disponible');
        return;
      }
      this.isRunning = true;
      this.setMode(true);
      this.setButtonBusy(true);
      const tour = this.createTour();
      this.resumeTarget = resumeId && resumeId !== this.available[0] && this.available.includes(resumeId) ? resumeId : null;
      this.installGuards();
      tour.start();
    }

    resumeTour() {
      const id = RESUME_TO[this.lastStepId] || this.lastStepId;
      this.startTutorial(id);
    }

    /** Deshace todo lo que el tour abrió (ventanas, menú, panel, recuadro, guardas, modo). */
    teardown() {
      this.isRunning = false;
      this.removeGuards();
      this.removeIconsArea();
      this.closeWindows();
      this.closeStartMenu();
      this.closePanel();
      this.setMode(false);
    }

    /** Cierre definitivo (completado u omitido): clave guardada y botón Tutorial de vuelta. */
    finish() {
      this.markComplete();
      this.setButtonBusy(false);
      this.lastStepId = null;
      if (this.mundialWasOpen) {
        this.mundialWasOpen = false;
        try { window.mundialTheme.toggleWidget(true); } catch (err) { /* el tema no debe frenar el tutorial */ }
      }
    }

    onComplete() {
      this.teardown();
      this.finish();
    }

    onCancel() {
      this.teardown();
      this.showCancelConfirmation();
    }

    // === MODALES (inicio y salida) ===
    ensureModal(id, html) {
      let modal = document.getElementById(id);
      if (!modal) {
        modal = document.createElement('div');
        modal.id = id;
        modal.className = 'modal fade dashboard-tutorial-modal';
        modal.tabIndex = -1;
        modal.setAttribute('aria-labelledby', id + 'Title');
        modal.setAttribute('aria-hidden', 'true');
        modal.innerHTML = html;
        // Bootstrap ignora hide() mientras el diálogo aún está entrando: se lleva
        // la cuenta para no perder un clic rápido (ver hideModal).
        modal.addEventListener('shown.bs.modal', () => { modal.dataset.ready = '1'; });
        modal.addEventListener('hide.bs.modal', () => { modal.dataset.ready = '0'; });
        document.body.appendChild(modal);
      }
      return modal;
    }

    modalApi(modal) {
      const bs = window.bootstrap;
      return bs && bs.Modal ? bs.Modal.getOrCreateInstance(modal) : null;
    }

    showModal(modal, api) {
      modal.dataset.ready = '0';
      api.show();
    }

    /** Cierra el diálogo; si todavía está entrando, en cuanto termine de entrar. */
    hideModal(modal, api) {
      if (modal.dataset.ready === '1') api.hide();
      else modal.addEventListener('shown.bs.modal', () => api.hide(), { once: true });
    }

    /** Botón «Tutorial»: confirma antes de cerrar ventanas e iniciar. */
    showStartConfirmation() {
      if (this.isRunning) return;
      const modal = this.ensureModal('dashboardTutorialStartModal', `
        <div class="modal-dialog modal-dialog-centered">
          <div class="modal-content">
            <div class="modal-body">
              <h2 class="dashboard-tutorial-modal-title" id="dashboardTutorialStartModalTitle">¿Iniciar el tutorial del escritorio?</h2>
              <p>Es un recorrido guiado y corto por el escritorio.</p>
              <p class="mb-0">Antes de empezar se cerrarán las ventanas abiertas, el menú de inicio y el panel de notificaciones.</p>
            </div>
            <div class="modal-footer">
              <button type="button" class="dashboard-tutorial-btn" id="dashboardTutorialStartCancel">Cancelar</button>
              <button type="button" class="dashboard-tutorial-btn is-primary" id="dashboardTutorialStartConfirm">Iniciar</button>
            </div>
          </div>
        </div>`);
      if (modal.classList.contains('show')) return;
      const api = this.modalApi(modal);
      if (!api) {
        this.prepareEnvironment();
        this.startTutorial();
        return;
      }
      this.setButtonBusy(true);
      let confirmed = false;
      modal.querySelector('#dashboardTutorialStartCancel').onclick = () => this.hideModal(modal, api);
      modal.querySelector('#dashboardTutorialStartConfirm').onclick = () => {
        confirmed = true;
        this.hideModal(modal, api);
      };
      modal.addEventListener('hidden.bs.modal', () => {
        if (confirmed) {
          this.prepareEnvironment();
          this.startTutorial();
        } else if (!this.isRunning) {
          this.setButtonBusy(false);
        }
      }, { once: true });
      this.showModal(modal, api);
    }

    /** X, Esc u «Omitir»: confirmar la salida; «Continuar» (o cerrar el diálogo) reanuda. */
    showCancelConfirmation() {
      const modal = this.ensureModal('dashboardTutorialCancelModal', `
        <div class="modal-dialog modal-dialog-centered">
          <div class="modal-content">
            <div class="modal-body">
              <h2 class="dashboard-tutorial-modal-title" id="dashboardTutorialCancelModalTitle">¿Salir del tutorial?</h2>
              <p class="mb-0">Puedes volver a verlo cuando quieras con el botón <strong>Tutorial</strong> de la barra de tareas.</p>
            </div>
            <div class="modal-footer">
              <button type="button" class="dashboard-tutorial-btn" id="dashboardTutorialCancelConfirm">Salir del tutorial</button>
              <button type="button" class="dashboard-tutorial-btn is-primary" id="dashboardTutorialCancelResume">Continuar</button>
            </div>
          </div>
        </div>`);
      const api = this.modalApi(modal);
      if (!api) {
        this.finish();
        return;
      }
      let exited = false;
      modal.querySelector('#dashboardTutorialCancelResume').onclick = () => this.hideModal(modal, api);
      modal.querySelector('#dashboardTutorialCancelConfirm').onclick = () => {
        if (!exited) {
          exited = true;
          this.finish();
        }
        this.hideModal(modal, api);
      };
      modal.addEventListener('hidden.bs.modal', () => {
        if (!exited) this.resumeTour();
      }, { once: true });
      this.showModal(modal, api);
    }

    // === AUTO-INICIO ===
    /**
     * Espera a que el escritorio esté listo y a que el modal de cambio de
     * contraseña (must_change.js) no esté a la vista.
     */
    waitUntilClear() {
      return new Promise((resolve) => {
        const started = Date.now();
        const check = () => {
          const ready = document.documentElement.classList.contains('desktop-ready');
          const pwModal = document.getElementById('forcePwModal');
          const pwVisible = !!(pwModal && pwModal.classList.contains('show'));
          // must_change.js decide de forma asíncrona: hasta que no expone
          // passwordModalWasShown no sabemos si el modal va a aparecer (tope 6 s).
          const gateKnown = typeof window.passwordModalWasShown === 'function' || Date.now() - started > 6000;
          if (ready && gateKnown && !pwVisible) resolve();
          else setTimeout(check, 250);
        };
        check();
      });
    }

    /** Primera visita: arranca solo (sin confirmación). */
    async autoStartTutorial() {
      if (this.hasCompleted()) return;
      await this.waitUntilClear();
      // Mientras esperábamos pudo completarse o iniciarse a mano.
      if (this.hasCompleted() || this.isRunning || q('.modal.show')) return;
      // Un modal de contraseña recién cerrado necesita un instante para desbloquear la interfaz.
      if (typeof window.passwordModalWasShown === 'function' && window.passwordModalWasShown()) await sleep(1000);
      if (this.hasCompleted() || this.isRunning) return;
      this.prepareEnvironment();
      this.startTutorial();
    }
  }

  // === PUNTO DE ENTRADA ===
  // El cargador (desktop/tutorial-loader.js) inyecta este archivo bajo demanda:
  // no se auto-ejecuta, expone un punto de entrada con instancia perezosa.
  function instance() {
    if (!window.dashboardTutorial) window.dashboardTutorial = new DashboardTutorial();
    return window.dashboardTutorial;
  }

  window.DashboardTutorial = DashboardTutorial;
  window.DashboardTutorialEntry = {
    /** Auto-inicio de la primera visita (respeta #forcePwModal y desktop-ready). */
    autoStart() {
      return instance().autoStartTutorial();
    },
    /** Botón «Tutorial»: pide confirmación y arranca el tour. */
    start() {
      instance().showStartConfirmation();
    }
  };
})();
