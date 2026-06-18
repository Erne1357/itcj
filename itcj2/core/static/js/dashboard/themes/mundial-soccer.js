/* ============================================
   TEMA MUNDIAL 2026 — decoraciones + widget + modal
   Lee window.activeTheme.decorations. Self-init en DOMContentLoaded.
   ============================================ */
(function () {
  'use strict';

  const API = '/api/core/v2/mundial/matches';

  function escapeHtml(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#039;');
  }

  class MundialTheme {
    constructor(deco) {
      this.deco = deco || {};
      this.reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
      this.isMobile = window.innerWidth <= 576;
      this.timers = [];
      this.pollTimer = null;
      this.init();
    }

    init() {
      if (!this.reduced) this.buildDecorations();
      this.buildWidget();
      this.buildTrayButton();
      this.buildModal();
      this.loadMatches('today');
      window.addEventListener('beforeunload', () => this.cleanup());
    }

    // ---------- Decoraciones ----------
    buildDecorations() {
      if (this.deco.bunting?.enabled) this.buildBunting();
      if (this.deco.lights?.enabled) document.body.classList.add('mundial-lights');
      if (this.deco.ball?.enabled && !this.isMobile) {
        this.spawnBall();
        this.timers.push(setInterval(() => this.spawnBall(), this.deco.ball.interval || 150000));
      }
      if (this.deco.confetti?.enabled) {
        this.timers.push(setInterval(() => this.burstConfetti(this.isMobile ? 10 : 24), 60000));
      }
    }

    buildBunting() {
      const wrap = document.createElement('div');
      wrap.className = 'mundial-bunting';
      const n = this.isMobile ? 14 : 28;
      for (let i = 0; i < n; i++) {
        const f = document.createElement('div');
        f.className = 'mundial-flag';
        f.style.animationDelay = (i * 0.1) + 's';
        wrap.appendChild(f);
      }
      document.body.appendChild(wrap);
    }

    spawnBall() {
      const b = document.createElement('div');
      b.className = 'mundial-ball';
      b.textContent = '⚽';
      document.body.appendChild(b);
      setTimeout(() => b.remove(), 8200);
    }

    burstConfetti(count) {
      const colors = ['#0B6E4F', '#FFD23F', '#ffffff', '#1A7A3D'];
      for (let i = 0; i < count; i++) {
        const c = document.createElement('div');
        c.className = 'mundial-confetti';
        c.style.left = Math.random() * 100 + 'vw';
        c.style.background = colors[i % colors.length];
        c.style.animationDuration = (2 + Math.random() * 2) + 's';
        document.body.appendChild(c);
        setTimeout(() => c.remove(), 4200);
      }
    }

    // ---------- Widget flotante ----------
    buildWidget() {
      const w = document.createElement('div');
      w.id = 'mundial-widget';
      w.className = 'hidden';
      w.innerHTML =
        '<div class="mundial-widget-header" id="mundial-widget-header">' +
          '<strong>⚽ Partidos de hoy</strong>' +
          '<span class="mundial-widget-actions">' +
            '<button id="mundial-results-btn" title="Resultados anteriores">📅</button>' +
            '<button id="mundial-refresh-btn" title="Actualizar">⟳</button>' +
            '<button id="mundial-close-btn" title="Cerrar">✕</button>' +
          '</span>' +
        '</div>' +
        '<div class="mundial-widget-body" id="mundial-widget-body">' +
          '<div class="mundial-empty">Cargando...</div>' +
        '</div>';
      document.body.appendChild(w);
      this.widget = w;

      w.querySelector('#mundial-close-btn').addEventListener('click', () => this.toggleWidget(false));
      w.querySelector('#mundial-refresh-btn').addEventListener('click', () => this.loadMatches('today'));
      w.querySelector('#mundial-results-btn').addEventListener('click', () => this.openModal());

      if (!this.isMobile) this.makeDraggable(w, w.querySelector('#mundial-widget-header'));

      // Restaurar estado
      if (localStorage.getItem('mundialWidgetOpen') === '1') this.toggleWidget(true);
    }

    makeDraggable(el, handle) {
      let sx, sy, ox, oy, dragging = false;
      handle.addEventListener('mousedown', (e) => {
        dragging = true; sx = e.clientX; sy = e.clientY;
        const r = el.getBoundingClientRect(); ox = r.left; oy = r.top;
        el.style.right = 'auto'; document.body.style.userSelect = 'none';
      });
      this._onDragMove = (e) => {
        if (!dragging) return;
        el.style.left = (ox + e.clientX - sx) + 'px';
        el.style.top = (oy + e.clientY - sy) + 'px';
      };
      this._onDragUp = () => { dragging = false; document.body.style.userSelect = ''; };
      window.addEventListener('mousemove', this._onDragMove);
      window.addEventListener('mouseup', this._onDragUp);
    }

    toggleWidget(show) {
      const open = show == null ? this.widget.classList.contains('hidden') : show;
      this.widget.classList.toggle('hidden', !open);
      localStorage.setItem('mundialWidgetOpen', open ? '1' : '0');
    }

    // ---------- Botón en system-tray ----------
    buildTrayButton() {
      const tray = document.querySelector('.system-tray');
      if (!tray) return;
      const btn = document.createElement('button');
      btn.id = 'mundial-tray-btn';
      btn.className = 'system-icon';
      btn.title = 'Partidos del Mundial';
      btn.innerHTML = '⚽<span id="mundial-tray-badge" style="display:none">0</span>';
      btn.addEventListener('click', () => this.toggleWidget());
      tray.insertBefore(btn, tray.firstChild);
      this.trayBadge = btn.querySelector('#mundial-tray-badge');
    }

    // ---------- Carga de partidos ----------
    loadMatches(scope) {
      fetch(API + '?scope=' + encodeURIComponent(scope), { credentials: 'same-origin' })
        .then((r) => r.json())
        .then((j) => this.renderToday((j && j.data) || { matches: [] }))
        .catch(() => this.renderToday({ matches: [] }));
    }

    renderToday(data) {
      const body = this.widget.querySelector('#mundial-widget-body');
      const matches = data.matches || [];
      if (this.trayBadge) {
        this.trayBadge.textContent = matches.length;
        this.trayBadge.style.display = matches.length ? '' : 'none';
      }
      if (!matches.length) {
        const nm = data.next_match;
        body.innerHTML = '<div class="mundial-empty">Sin partidos hoy.' +
          (nm ? '<br>Próximo: ' + escapeHtml(nm.home?.name) + ' vs ' + escapeHtml(nm.away?.name) +
            ' — ' + escapeHtml(nm.kickoff_label) : '') + '</div>';
        return;
      }
      body.innerHTML = matches.map((m) => this.matchRow(m)).join('');
      // Poll si hay alguno en vivo
      const anyLive = matches.some((m) => m.status === 'live');
      this.setupPoll(anyLive);
    }

    matchRow(m) {
      const isMex = (m.home?.code === 'MEX' || m.away?.code === 'MEX');
      const mid = m.score
        ? '<span class="mundial-score">' + escapeHtml(m.score.home) + ' - ' + escapeHtml(m.score.away) + '</span>'
        : (m.status === 'finished'
            ? '<span class="mundial-score">—</span>'
            : '<span class="mundial-time">' + escapeHtml(m.kickoff_local) + '</span>');
      const live = m.status === 'live' ? '<div class="mundial-live">🔴 EN VIVO</div>' : '';
      return '<div class="mundial-match' + (isMex ? ' mex' : '') + '">' +
        '<span class="mundial-team">' + escapeHtml(m.home?.flag) + ' ' + escapeHtml(m.home?.name) + '</span>' +
        mid +
        '<span class="mundial-team away">' + escapeHtml(m.away?.name) + ' ' + escapeHtml(m.away?.flag) + '</span>' +
        '</div>' + live;
    }

    setupPoll(anyLive) {
      if (this.pollTimer) { clearInterval(this.pollTimer); this.pollTimer = null; }
      if (anyLive) this.pollTimer = setInterval(() => this.loadMatches('today'), 60000);
    }

    // ---------- Modal de resultados ----------
    buildModal() {
      const m = document.createElement('div');
      m.className = 'modal fade';
      m.id = 'mundial-results-modal';
      m.tabIndex = -1;
      m.innerHTML =
        '<div class="modal-dialog modal-dialog-scrollable modal-fullscreen-sm-down">' +
          '<div class="modal-content">' +
            '<div class="modal-header" style="background:var(--mundial-primary);color:#fff">' +
              '<h5 class="modal-title">📅 Resultados anteriores</h5>' +
              '<button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button>' +
            '</div>' +
            '<div class="modal-body" id="mundial-modal-body"><div class="mundial-empty">Cargando...</div></div>' +
          '</div>' +
        '</div>';
      document.body.appendChild(m);
      this.modalEl = m;
    }

    openModal() {
      const modal = bootstrap.Modal.getOrCreateInstance(this.modalEl);
      const body = this.modalEl.querySelector('#mundial-modal-body');
      body.innerHTML = '<div class="mundial-empty">Cargando...</div>';
      modal.show();
      fetch(API + '?scope=past', { credentials: 'same-origin' })
        .then((r) => r.json())
        .then((j) => this.renderPast(body, ((j && j.data) || {}).matches || []))
        .catch(() => { body.innerHTML = '<div class="mundial-empty">No se pudieron cargar los resultados.</div>'; });
    }

    renderPast(body, matches) {
      if (!matches.length) {
        body.innerHTML = '<div class="mundial-empty">Aún no hay partidos jugados.</div>';
        return;
      }
      // Agrupar por día (kickoff_label "dd/mm HH:MM" -> "dd/mm")
      const groups = {};
      matches.forEach((m) => {
        const day = (m.kickoff_label || '').split(' ')[0] || (m.kickoff_utc || '').slice(0, 10) || '?';
        (groups[day] = groups[day] || []).push(m);
      });
      body.innerHTML = Object.keys(groups).map((day) =>
        '<h6 class="mt-3">' + escapeHtml(day) + '</h6>' +
        groups[day].map((m) => this.matchRow(m)).join('')
      ).join('');
    }

    cleanup() {
      this.timers.forEach(clearInterval);
      if (this.pollTimer) clearInterval(this.pollTimer);
      if (this._onDragMove) window.removeEventListener('mousemove', this._onDragMove);
      if (this._onDragUp) window.removeEventListener('mouseup', this._onDragUp);
    }
  }

  document.addEventListener('DOMContentLoaded', () => {
    if (window.activeTheme && window.activeTheme.name === 'Mundial 2026') {
      window.mundialTheme = new MundialTheme(window.activeTheme.decorations);
    }
  });
})();
