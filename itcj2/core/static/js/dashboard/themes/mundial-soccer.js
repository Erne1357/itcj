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
      this.buildFab();
      this.buildWidget();
      this.buildTrayButton();
      this.buildModal();
      this.loadMatches('today');
      window.addEventListener('beforeunload', () => this.cleanup());
    }

    // FAB (mobile / sin system-tray): abajo-izquierda con el balón, abre el widget.
    buildFab() {
      const fab = document.createElement('button');
      fab.id = 'mundial-fab';
      fab.type = 'button';
      fab.title = 'Partidos del Mundial';
      fab.innerHTML = '⚽<span class="mundial-fab-badge" id="mundial-fab-badge" style="display:none">0</span>';
      fab.addEventListener('click', () => this.toggleWidget());
      document.body.appendChild(fab);
      this.fab = fab;
      this.fabBadge = fab.querySelector('#mundial-fab-badge');
    }

    // ---------- Decoraciones ----------
    buildDecorations() {
      const d = this.deco;
      if (d.flags?.enabled || d.bunting?.enabled) this.buildFlagGarland();
      if (d.mexico_flag?.enabled) this.buildMexicoFlag();
      if (d.lights?.enabled) document.body.classList.add('mundial-lights');
      if (d.floating_flags?.enabled) {
        this.spawnFloatingFlag();
        this.timers.push(setInterval(() => this.spawnFloatingFlag(), this.isMobile ? 3500 : 2200));
      }
      if (d.ball?.enabled && !this.isMobile) {
        this.spawnBall();
        this.timers.push(setInterval(() => this.spawnBall(), d.ball.interval || 120000));
      }
      if (d.confetti?.enabled) {
        this.timers.push(setInterval(() => this.burstConfetti(this.isMobile ? 12 : 26), 60000));
      }
    }

    // Gradientes de banderas (CSS) para la guirnalda; México va resaltado cada 3.
    buildFlagGarland() {
      const MEX = 'linear-gradient(90deg,#006847 0 33.33%,#fff 33.33% 66.66%,#ce1126 66.66%)';
      const OTHERS = [
        'linear-gradient(180deg,#009b3a 62%,#fedf00 62%)',                 // Brasil
        'linear-gradient(180deg,#75aadb 33%,#fff 33% 66%,#75aadb 66%)',    // Argentina
        'linear-gradient(90deg,#0055A4 33%,#fff 33% 66%,#EF4135 66%)',     // Francia
        'linear-gradient(180deg,#000 33%,#D00 33% 66%,#FFCE00 66%)',       // Alemania
        'linear-gradient(180deg,#AA151B 25%,#F1BF00 25% 75%,#AA151B 75%)', // España
        'linear-gradient(180deg,#C8102E 50%,#fff 50%)',                    // genérica
      ];
      const wrap = document.createElement('div');
      wrap.className = 'mundial-garland';
      const n = this.isMobile ? 16 : 30;
      for (let i = 0; i < n; i++) {
        const f = document.createElement('div');
        const isMex = (i % 3 === 0);
        f.className = 'mundial-gflag' + (isMex ? ' mex' : '');
        f.style.background = isMex ? MEX : OTHERS[i % OTHERS.length];
        f.style.animationDelay = (i * 0.08) + 's';
        wrap.appendChild(f);
      }
      document.body.appendChild(wrap);
      this.garland = wrap;
    }

    buildMexicoFlag() {
      const flag = document.createElement('div');
      flag.className = 'mundial-mexico';
      flag.innerHTML = '<span class="mundial-mexico-label">MÉXICO</span>';
      document.body.appendChild(flag);
      this.mexicoFlag = flag;
    }

    spawnFloatingFlag() {
      // Mayoría México (🇲🇽 repetido), más otras selecciones.
      const FLAGS = ['🇲🇽', '🇲🇽', '🇲🇽', '🇧🇷', '🇦🇷', '🇫🇷', '🇩🇪', '🇪🇸', '🇵🇹', '🇺🇸', '🇨🇦', '🇯🇵'];
      const el = document.createElement('div');
      el.className = 'mundial-float-flag';
      el.textContent = FLAGS[Math.floor(Math.random() * FLAGS.length)];
      el.style.left = (Math.random() * 96) + 'vw';
      el.style.fontSize = (24 + Math.random() * 18) + 'px';
      const dur = 7 + Math.random() * 5;
      el.style.animationDuration = dur + 's';
      document.body.appendChild(el);
      setTimeout(() => el.remove(), dur * 1000 + 300);
    }

    spawnBall() {
      const b = document.createElement('div');
      b.className = 'mundial-ball';
      b.textContent = '⚽';
      document.body.appendChild(b);
      setTimeout(() => b.remove(), 7200);
    }

    burstConfetti(count) {
      const colors = ['#006847', '#ffffff', '#ce1126', '#FFD23F']; // verde, blanco, rojo (México) + dorado
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
      // En mobile el FAB y la tarjeta comparten esquina: oculta el FAB mientras está abierto.
      if (this.fab && this.isMobile) this.fab.style.display = open ? 'none' : '';
    }

    // ---------- Botón en system-tray (escritorio) ----------
    buildTrayButton() {
      const tray = document.querySelector('.system-tray');
      if (!tray) { if (this.fab) this.fab.classList.add('show'); return; }  // sin tray -> usa el FAB
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
      const setBadge = (el) => {
        if (!el) return;
        el.textContent = matches.length;
        el.style.display = matches.length ? '' : 'none';
      };
      setBadge(this.trayBadge);
      setBadge(this.fabBadge);
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

    // ---------- Modal con 3 vistas: Partidos / Grupos / Bracket ----------
    buildModal() {
      const m = document.createElement('div');
      m.className = 'modal fade';
      m.id = 'mundial-results-modal';
      m.tabIndex = -1;
      m.innerHTML =
        '<div class="modal-dialog modal-xl modal-dialog-scrollable modal-fullscreen-md-down">' +
          '<div class="modal-content">' +
            '<div class="modal-header" style="background:var(--mundial-primary);color:#fff">' +
              '<h5 class="modal-title">🏆 Mundial 2026</h5>' +
              '<button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button>' +
            '</div>' +
            '<ul class="nav nav-tabs mundial-tabs px-2 pt-2" id="mundial-tabs">' +
              '<li class="nav-item"><button class="nav-link active" data-tab="list">Partidos</button></li>' +
              '<li class="nav-item"><button class="nav-link" data-tab="groups">Grupos</button></li>' +
              '<li class="nav-item"><button class="nav-link" data-tab="bracket">Bracket</button></li>' +
            '</ul>' +
            '<div class="modal-body" id="mundial-modal-body"><div class="mundial-empty">Cargando...</div></div>' +
          '</div>' +
        '</div>';
      document.body.appendChild(m);
      this.modalEl = m;
      this._allMatches = null;
      this._standings = null;
      m.querySelectorAll('#mundial-tabs .nav-link').forEach((btn) => {
        btn.addEventListener('click', () => {
          m.querySelectorAll('#mundial-tabs .nav-link').forEach((b) => b.classList.remove('active'));
          btn.classList.add('active');
          this.loadTab(btn.getAttribute('data-tab'));
        });
      });
    }

    openModal() {
      const modal = bootstrap.Modal.getOrCreateInstance(this.modalEl);
      this._allMatches = null;   // refrescar datos en cada apertura (marcadores cambian)
      this._standings = null;
      this._pastShown = null;    // reinicia el "cargar más"
      this.modalEl.querySelectorAll('#mundial-tabs .nav-link')
        .forEach((b, i) => b.classList.toggle('active', i === 0));
      modal.show();
      this.loadTab('list');
    }

    _body() { return this.modalEl.querySelector('#mundial-modal-body'); }

    loadTab(tab) {
      const body = this._body();
      body.innerHTML = '<div class="mundial-empty">Cargando...</div>';
      if (tab === 'groups') {
        this._fetchStandings()
          .then((st) => this.renderGroups(body, st))
          .catch(() => { body.innerHTML = '<div class="mundial-empty">No se pudieron cargar los grupos.</div>'; });
      } else {
        this._fetchAll()
          .then((ms) => { tab === 'bracket' ? this.renderBracket(body, ms) : this.renderList(body, ms); })
          .catch(() => { body.innerHTML = '<div class="mundial-empty">No se pudieron cargar los partidos.</div>'; });
      }
    }

    _fetchAll() {
      if (this._allMatches) return Promise.resolve(this._allMatches);
      return fetch(API + '?scope=all', { credentials: 'same-origin' })
        .then((r) => r.json())
        .then((j) => { this._allMatches = ((j && j.data) || {}).matches || []; return this._allMatches; });
    }

    _fetchStandings() {
      if (this._standings) return Promise.resolve(this._standings);
      return fetch('/api/core/v2/mundial/standings', { credentials: 'same-origin' })
        .then((r) => r.json())
        .then((j) => { this._standings = ((j && j.data) || {}).standings || []; return this._standings; });
    }

    renderList(body, matches) {
      if (!matches.length) { body.innerHTML = '<div class="mundial-empty">Sin partidos.</div>'; return; }
      const all = matches.slice().sort((a, b) => (a.kickoff_utc || '').localeCompare(b.kickoff_utc || ''));
      const past = all.filter((m) => m.status === 'finished');
      const rest = all.filter((m) => m.status !== 'finished');   // hoy + en vivo + próximos
      if (this._pastShown == null) this._pastShown = 12;          // historial inicial
      const shownPast = past.slice(Math.max(0, past.length - this._pastShown));
      const hasMore = shownPast.length < past.length;
      const visible = shownPast.concat(rest);                    // cronológico ascendente

      const groups = {};
      visible.forEach((m) => {
        const day = (m.kickoff_label || '').split(' ')[0] || (m.kickoff_utc || '').slice(0, 10) || '?';
        (groups[day] = groups[day] || []).push(m);
      });
      const loadMore = hasMore
        ? '<div class="mundial-loadmore-wrap"><button class="mundial-loadmore" id="mundial-loadmore" type="button">' +
          '⬆️ Cargar partidos anteriores (' + (past.length - shownPast.length) + ')</button></div>'
        : '';
      body.innerHTML = loadMore + Object.keys(groups).map((day) =>
        '<h6 class="mundial-day">' + escapeHtml(day) + '</h6>' +
        groups[day].map((m) => this.matchRow(m)).join('')
      ).join('');

      const btn = body.querySelector('#mundial-loadmore');
      if (btn) btn.addEventListener('click', () => {
        const scrollY = body.scrollTop;
        this._pastShown += 12;
        this.renderList(body, matches);
        body.scrollTop = scrollY;   // mantén la posición tras cargar más arriba
      });
    }

    renderGroups(body, standings) {
      if (!standings.length) {
        body.innerHTML = '<div class="mundial-empty">Tablas de grupos no disponibles todavía.</div>';
        return;
      }
      body.innerHTML = '<div class="mundial-groups">' + standings.map((g) => {
        const rows = (g.table || []).map((row) => {
          const t = row.team || {};
          const mex = t.code === 'MEX' ? ' class="mex"' : '';
          return '<tr' + mex + '>' +
            '<td>' + escapeHtml(row.position) + '</td>' +
            '<td class="t">' + escapeHtml(t.flag) + ' ' + escapeHtml(t.name) + '</td>' +
            '<td>' + escapeHtml(row.played) + '</td>' +
            '<td>' + escapeHtml(row.won) + '</td>' +
            '<td>' + escapeHtml(row.draw) + '</td>' +
            '<td>' + escapeHtml(row.lost) + '</td>' +
            '<td>' + escapeHtml(row.gd) + '</td>' +
            '<td class="pts">' + escapeHtml(row.points) + '</td>' +
          '</tr>';
        }).join('');
        return '<div class="mundial-group">' +
          '<div class="mundial-group-h">Grupo ' + escapeHtml(g.group) + '</div>' +
          '<table class="mundial-table"><thead><tr>' +
            '<th>#</th><th class="t">Equipo</th><th>PJ</th><th>G</th><th>E</th><th>P</th><th>DG</th><th>Pts</th>' +
          '</tr></thead><tbody>' + rows + '</tbody></table>' +
        '</div>';
      }).join('') + '</div>';
    }

    renderBracket(body, matches) {
      const STAGES = [
        ['round32', 'Dieciseisavos'], ['round16', 'Octavos'], ['quarter', 'Cuartos'],
        ['semi', 'Semifinales'], ['final', 'Final'],
      ];
      const byStage = {};
      matches.forEach((m) => { (byStage[m.stage] = byStage[m.stage] || []).push(m); });
      const hasKnockout = STAGES.some(([k]) => (byStage[k] || []).length);
      if (!hasKnockout) {
        body.innerHTML = '<div class="mundial-empty">El bracket aparece cuando inicie la fase de eliminación.</div>';
        return;
      }
      const cols = STAGES.map(([key, label]) => {
        const ms = (byStage[key] || []).slice().sort((a, b) =>
          (a.kickoff_utc || '').localeCompare(b.kickoff_utc || ''));
        const cards = ms.map((m) => this.bracketCard(m)).join('') || '<div class="mundial-bk-empty">—</div>';
        return '<div class="mundial-bk-col"><div class="mundial-bk-h">' + escapeHtml(label) + '</div>' + cards + '</div>';
      }).join('');
      const third = (byStage['third'] || [])[0];
      const thirdHtml = third
        ? '<div class="mundial-bk-third"><div class="mundial-bk-h">3er lugar</div>' + this.bracketCard(third) + '</div>'
        : '';
      body.innerHTML = '<div class="mundial-bracket">' + cols + '</div>' + thirdHtml;
    }

    bracketCard(m) {
      const isMex = (m.home?.code === 'MEX' || m.away?.code === 'MEX');
      const sc = m.score;
      const line = (team, goals) =>
        '<div class="mundial-bk-team">' +
          '<span>' + escapeHtml(team?.flag) + ' ' + escapeHtml(team?.code || team?.name || '—') + '</span>' +
          '<b>' + (goals == null ? '' : escapeHtml(goals)) + '</b>' +
        '</div>';
      const tag = m.status === 'live'
        ? '<span class="mundial-bk-live">🔴 EN VIVO</span>'
        : (m.status === 'finished' ? '' : '<span class="mundial-bk-time">' + escapeHtml(m.kickoff_label) + '</span>');
      return '<div class="mundial-bk-match' + (isMex ? ' mex' : '') + '">' +
        line(m.home, sc ? sc.home : null) + line(m.away, sc ? sc.away : null) + tag + '</div>';
    }

    cleanup() {
      this.timers.forEach(clearInterval);
      if (this.pollTimer) clearInterval(this.pollTimer);
      if (this._onDragMove) window.removeEventListener('mousemove', this._onDragMove);
      if (this._onDragUp) window.removeEventListener('mouseup', this._onDragUp);
      if (this.garland) this.garland.remove();
      if (this.mexicoFlag) this.mexicoFlag.remove();
      if (this.fab) this.fab.remove();
      document.body.classList.remove('mundial-lights');
      document.querySelectorAll('.mundial-float-flag, .mundial-ball, .mundial-confetti')
        .forEach((el) => el.remove());
    }
  }

  document.addEventListener('DOMContentLoaded', () => {
    if (window.activeTheme && window.activeTheme.name === 'Mundial 2026') {
      window.mundialTheme = new MundialTheme(window.activeTheme.decorations);
    }
  });
})();
