/* ===========================================================================
   survey-report.js — constructor del reporte Excel de la encuesta (2026-10-28)
   ---------------------------------------------------------------------------
   Spec docs/superpowers/specs/2026-10-28-titulatec-reporte-encuestas-design.md.
   Se carga UNA vez en `admin/base_admin.html`. Morph-safe: los listeners se
   enlazan por delegación en `document` una sola vez (`window.__ttSrBound`);
   `init()` corre en DOMContentLoaded + htmx:afterSettle y aborta sin
   `#tt-report-root`.

   Qué hace (el estado inicial lo pinta SIEMPRE el servidor):
   - Mantiene los ocultos `cols` (lista «En el reporte») y `orden` (3 selects).
   - Reordena columnas: arrastrar (HTML5), botones subir/bajar/quitar.
   - Buscador, «Todas/Ninguna» por sección, atajos de semestre, cambio de
     formulario, «Copiar liga» (portapapeles + toast).
   - localStorage `tt.surveyReport.v1`: último query; al entrar sin `cols` lo
     restaura con location.replace. Todo acceso va en try/catch.
   =========================================================================== */
(function () {
  'use strict';

  var STORE = 'tt.surveyReport.v1';
  var dragLi = null;

  function $(id) { return document.getElementById(id); }
  function root() { return $('tt-report-root'); }
  function inRoot(el) { var r = root(); return !!(r && el && r.contains(el)); }
  function toast(msg, kind) {
    if (window.TitulaTecUtils) window.TitulaTecUtils.showToast(msg, kind || 'info');
  }
  function refresh() {
    document.body.dispatchEvent(new CustomEvent('tt-report-refresh'));
  }

  // === ALMACÉN LOCAL =========================================================
  function saveQuery(q) {
    try { if (q) window.localStorage.setItem(STORE, q); } catch (_) { /* sin storage */ }
  }
  function loadQuery() {
    try { return window.localStorage.getItem(STORE) || ''; } catch (_) { return ''; }
  }
  function formQuery() {
    var f = $('tt-report-form');
    var sp = new URLSearchParams();
    new FormData(f).forEach(function (v, k) { if (String(v) !== '') sp.append(k, String(v)); });
    return sp.toString();
  }

  // Sin `cols` en la URL: restaura la última configuración del mismo formulario.
  function restore() {
    var cur = new URLSearchParams(window.location.search);
    if (cur.has('cols')) return;
    var saved = loadQuery();
    if (!saved) return;
    var sp = new URLSearchParams(saved);
    if (cur.get('form_id') && sp.get('form_id') !== cur.get('form_id')) return;
    if (!cur.get('form_id') && !sp.has('form_id')) return;
    window.location.replace(window.location.pathname + '?' + sp.toString());
  }

  // === COLUMNAS ==============================================================
  function list() { return $('tt-sr-cols-list'); }
  function items() { return Array.prototype.slice.call(list().querySelectorAll('li[data-key]')); }

  function syncCols() {
    var keys = items().map(function (li) { return li.getAttribute('data-key'); });
    $('tt-sr-cols').value = keys.join(',');
    var empty = $('tt-sr-cols-empty');
    if (empty) empty.hidden = keys.length > 0;
  }

  function btn(attr, icon, label) {
    var b = document.createElement('button');
    b.type = 'button';
    b.className = 'btn btn-sm tt-btn-ghost';
    b.setAttribute(attr, '');
    b.setAttribute('aria-label', label);
    var i = document.createElement('i');
    i.className = 'bi ' + icon;
    b.appendChild(i);
    return b;
  }

  function addCol(key, label) {
    if (items().some(function (li) { return li.getAttribute('data-key') === key; })) return;
    var li = document.createElement('li');
    li.id = 'tt-sr-col-' + key;
    li.draggable = true;
    li.className = 'tt-sr__item';
    li.setAttribute('data-key', key);
    var grip = document.createElement('i');
    grip.className = 'bi bi-grip-vertical tt-sr__grip';
    grip.setAttribute('aria-hidden', 'true');
    var name = document.createElement('span');
    name.className = 'tt-sr__name';
    name.textContent = label || key;
    li.appendChild(grip);
    li.appendChild(name);
    li.appendChild(btn('data-tt-sr-up', 'bi-arrow-up', 'Subir'));
    li.appendChild(btn('data-tt-sr-down', 'bi-arrow-down', 'Bajar'));
    li.appendChild(btn('data-tt-sr-remove', 'bi-x-lg', 'Quitar'));
    list().appendChild(li);
  }

  function removeCol(key) {
    var li = $('tt-sr-col-' + key);
    if (li) li.remove();
    var cb = document.querySelector('#tt-report-root input[data-tt-sr-col][value="' + key + '"]');
    if (cb) cb.checked = false;
  }

  function colChecks(sec) {
    var box = $('tt-sr-sec-' + sec);
    return box ? Array.prototype.slice.call(box.querySelectorAll('input[data-tt-sr-col]')) : [];
  }

  function setSection(sec, on) {
    colChecks(sec).forEach(function (cb) {
      if (cb.closest('label').hidden) return;     // respeta el buscador
      cb.checked = on;
      if (on) addCol(cb.value, cb.getAttribute('data-label')); else removeCol(cb.value);
    });
    syncCols();
    refresh();
  }

  function move(li, dir) {
    var ref = dir < 0 ? li.previousElementSibling : li.nextElementSibling;
    if (!ref) return;
    if (dir < 0) list().insertBefore(li, ref); else list().insertBefore(ref, li);
    syncCols();
    refresh();
  }

  // === ORDEN =================================================================
  function syncOrden() {
    var cols = document.querySelectorAll('#tt-report-root [data-tt-sr-ord-col]');
    var dirs = document.querySelectorAll('#tt-report-root [data-tt-sr-ord-dir]');
    var out = [];
    cols.forEach(function (c, i) { if (c.value) out.push(c.value + ':' + dirs[i].value); });
    $('tt-sr-orden').value = out.join(',');
  }

  // === LIGA ==================================================================
  function copyLink() {
    var url = window.location.origin + window.location.pathname + '?' + formQuery();
    saveQuery(formQuery());
    function fallback() {
      var ta = document.createElement('textarea');
      ta.value = url;
      ta.setAttribute('readonly', '');
      ta.style.position = 'fixed';
      ta.style.opacity = '0';
      document.body.appendChild(ta);
      ta.select();
      var ok = false;
      try { ok = document.execCommand('copy'); } catch (_) { ok = false; }
      ta.remove();
      toast(ok ? 'Liga copiada.' : 'No se pudo copiar la liga.', ok ? 'success' : 'danger');
    }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(url).then(
        function () { toast('Liga copiada.', 'success'); }, fallback);
    } else {
      fallback();
    }
  }

  // === EVENTOS (delegados, una sola vez) =====================================
  function bind() {
    if (window.__ttSrBound) return;
    window.__ttSrBound = true;

    document.addEventListener('click', function (e) {
      var t = e.target.closest && e.target.closest(
        '[data-tt-sr-up],[data-tt-sr-down],[data-tt-sr-remove],[data-tt-sr-sec-all],' +
        '[data-tt-sr-sec-none],[data-tt-sr-sem],[data-tt-sr-copy],[data-tt-sr-download]');
      if (!t || !inRoot(t)) return;
      var li = t.closest('li[data-key]');
      if (t.hasAttribute('data-tt-sr-up')) move(li, -1);
      else if (t.hasAttribute('data-tt-sr-down')) move(li, 1);
      else if (t.hasAttribute('data-tt-sr-remove')) {
        removeCol(li.getAttribute('data-key'));
        syncCols();
        refresh();
      } else if (t.hasAttribute('data-tt-sr-sec-all')) setSection(t.getAttribute('data-tt-sr-sec-all'), true);
      else if (t.hasAttribute('data-tt-sr-sec-none')) setSection(t.getAttribute('data-tt-sr-sec-none'), false);
      else if (t.hasAttribute('data-tt-sr-sem')) {
        var f = document.querySelector('#tt-report-form');
        f.elements['desde'].value = t.getAttribute('data-desde') || '';
        f.elements['hasta'].value = t.getAttribute('data-hasta') || '';
        refresh();
      } else if (t.hasAttribute('data-tt-sr-copy')) copyLink();
      else if (t.hasAttribute('data-tt-sr-download')) saveQuery(formQuery());
    });

    document.addEventListener('change', function (e) {
      var t = e.target;
      if (!inRoot(t)) return;
      if (t.matches('input[data-tt-sr-col]')) {
        if (t.checked) addCol(t.value, t.getAttribute('data-label')); else removeCol(t.value);
        syncCols();
      } else if (t.matches('[data-tt-sr-ord-col],[data-tt-sr-ord-dir]')) {
        syncOrden();
      } else if (t.id === 'tt-sr-form-select') {
        window.location.assign(t.getAttribute('data-tt-sr-base') + '?form_id=' + encodeURIComponent(t.value));
      }
    });

    document.addEventListener('input', function (e) {
      var t = e.target;
      if (!inRoot(t) || !t.matches('[data-tt-sr-search]')) return;
      var q = t.value.trim().toLowerCase();
      document.querySelectorAll('#tt-report-root [data-tt-sr-label]').forEach(function (l) {
        l.hidden = !!q && l.getAttribute('data-tt-sr-label').indexOf(q) === -1;
      });
    });

    // Enter en un campo no debe descargar el libro por accidente.
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && inRoot(e.target) && e.target.tagName === 'INPUT') e.preventDefault();
    });

    // Arrastrar para reordenar.
    document.addEventListener('dragstart', function (e) {
      var li = e.target.closest && e.target.closest('li.tt-sr__item');
      if (!li || !inRoot(li)) return;
      dragLi = li;
      li.classList.add('is-drag');
      if (e.dataTransfer) { e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/plain', li.id); }
    });
    document.addEventListener('dragover', function (e) {
      var li = e.target.closest && e.target.closest('li.tt-sr__item');
      if (!dragLi || !li || li === dragLi || !inRoot(li)) return;
      e.preventDefault();
    });
    document.addEventListener('drop', function (e) {
      var li = e.target.closest && e.target.closest('li.tt-sr__item');
      if (!dragLi || !li || li === dragLi || !inRoot(li)) return;
      e.preventDefault();
      var after = dragLi.compareDocumentPosition(li) & Node.DOCUMENT_POSITION_FOLLOWING;
      list().insertBefore(dragLi, after ? li.nextSibling : li);
      syncCols();
      refresh();
    });
    document.addEventListener('dragend', function () {
      if (dragLi) dragLi.classList.remove('is-drag');
      dragLi = null;
    });

    // Cada vista previa lista guarda su query normalizado.
    document.body.addEventListener('htmx:afterSettle', function () {
      var pv = $('tt-report-preview');
      if (pv && inRoot(pv) && pv.getAttribute('data-tt-sr-query')) {
        saveQuery(pv.getAttribute('data-tt-sr-query'));
      }
    });
  }

  function init() {
    var r = root();
    if (!r) return;
    bind();
    if (r.getAttribute('data-tt-bound')) return;
    r.setAttribute('data-tt-bound', '1');
    restore();
  }

  document.addEventListener('DOMContentLoaded', init);
  document.body && document.body.addEventListener('htmx:afterSettle', init);
  if (document.readyState !== 'loading') init();
})();
