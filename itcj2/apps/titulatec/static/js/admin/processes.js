/* ===========================================================================
   TitulaTec · Admin — Procesos (tabla: buscar/ordenar/filtrar + tablero kanban).
   Cargado una vez por base_admin; se auto-inicializa en cada htmx:afterSettle
   y aborta si su DOM no está presente. A prueba de morph: los handlers releen
   el DOM en vivo (sin capturas obsoletas) y se enlazan una sola vez por elemento
   (guarda data-tt-bound), por lo que la navegación del menú no duplica listeners.
   =========================================================================== */
(function () {
  'use strict';

  // -------------------------- Tabla --------------------------
  function tableRows(table) {
    return Array.prototype.slice.call(table.tBodies[0].rows)
      .filter(function (r) { return r.dataset.search !== undefined; });
  }

  function applyFilters(table) {
    var search  = document.getElementById('proc-search');
    var counter = document.getElementById('proc-count');
    var funnel  = document.getElementById('proc-funnel');
    var phaseFilter = (funnel && funnel.dataset.ttPhase) || '';
    var q = ((search && search.value) || '').trim().toLowerCase();
    var rows = tableRows(table), total = rows.length, shown = 0;
    rows.forEach(function (r) {
      var okText  = !q || (r.dataset.search || '').indexOf(q) !== -1;
      var okPhase = !phaseFilter || r.dataset.phase === phaseFilter;
      var on = okText && okPhase;
      r.style.display = on ? '' : 'none';
      if (on) shown++;
    });
    if (counter) counter.textContent = (shown === total && !q && !phaseFilter)
      ? total + ' proceso(s)'
      : shown + ' de ' + total + ' proceso(s)';
  }

  function initTable(table) {
    var search = document.getElementById('proc-search');
    if (search && !search.dataset.ttBound) {
      search.dataset.ttBound = '1';
      search.addEventListener('input', function () { applyFilters(table); });
    }

    // Ordenar (primer click: desc)
    Array.prototype.forEach.call(table.querySelectorAll('th.sortable'), function (th) {
      if (th.dataset.ttBound) return;
      th.dataset.ttBound = '1';
      th.addEventListener('click', function () {
        var key = th.dataset.sort;
        var dir = parseInt(table.dataset.ttSortDir || '-1', 10);
        dir = (table.dataset.ttSortKey === key) ? -dir : -1;
        table.dataset.ttSortKey = key;
        table.dataset.ttSortDir = String(dir);
        var tbody = table.tBodies[0];
        tableRows(table).slice().sort(function (a, b) {
          var av = parseFloat(a.getAttribute('data-' + key)) || 0;
          var bv = parseFloat(b.getAttribute('data-' + key)) || 0;
          return (av - bv) * dir;
        }).forEach(function (r) { tbody.appendChild(r); });
        Array.prototype.forEach.call(table.querySelectorAll('th.sortable'), function (h) {
          h.classList.toggle('is-sorted', h === th);
          var ic = h.querySelector('.bi');
          if (ic) ic.className = 'bi ' + (h === th ? (dir > 0 ? 'bi-sort-up' : 'bi-sort-down') : 'bi-arrow-down-up');
        });
      });
    });

    // Funnel: filtrar por fase
    var funnel = document.getElementById('proc-funnel');
    if (funnel) {
      Array.prototype.forEach.call(funnel.querySelectorAll('.seg'), function (seg) {
        if (seg.classList.contains('is-empty') || seg.dataset.ttBound) return;
        seg.dataset.ttBound = '1';
        seg.addEventListener('click', function () {
          var ph = seg.dataset.phase;
          funnel.dataset.ttPhase = (funnel.dataset.ttPhase === ph) ? '' : ph;
          var active = funnel.dataset.ttPhase;
          Array.prototype.forEach.call(funnel.querySelectorAll('.seg'), function (s) {
            s.classList.toggle('is-sel', !!active && s === seg);
            s.classList.toggle('is-dim', !!active && s !== seg);
          });
          applyFilters(table);
        });
      });
    }

    applyFilters(table);
  }

  // -------------------------- Tablero (kanban) --------------------------
  var BOTTOM_GAP = 22;

  function updateFade(scroll) {
    var body = scroll.querySelector('.body');
    if (!body) return;
    var more = body.scrollHeight - body.clientHeight;
    scroll.classList.toggle('show-top', body.scrollTop > 2);
    scroll.classList.toggle('show-bottom', more > 2 && body.scrollTop < more - 2);
  }

  function recalcBoard() {
    var board = document.querySelector('.tt-kanban');
    if (!board) return;
    var top = board.getBoundingClientRect().top;
    board.style.height = Math.max(260, window.innerHeight - top - BOTTOM_GAP) + 'px';
    Array.prototype.forEach.call(board.querySelectorAll('.col-scroll'), updateFade);
  }

  function initBoard() {
    var board = document.querySelector('.tt-kanban');
    if (!board) return;
    Array.prototype.forEach.call(board.querySelectorAll('.col-scroll .body'), function (body) {
      if (body.dataset.ttBound) return;
      body.dataset.ttBound = '1';
      body.addEventListener('scroll', function () { updateFade(body.parentNode); }, { passive: true });
    });
    recalcBoard();
    requestAnimationFrame(recalcBoard);   // segundo paso tras layout/fuentes
  }

  // resize: una sola vez (window persiste entre swaps)
  window.addEventListener('resize', recalcBoard);

  function init() {
    var table = document.getElementById('proc-table');
    if (table) initTable(table);
    initBoard();
  }
  document.body.addEventListener('htmx:afterSettle', init);
  if (document.readyState !== 'loading') init();
  else document.addEventListener('DOMContentLoaded', init);
})();
