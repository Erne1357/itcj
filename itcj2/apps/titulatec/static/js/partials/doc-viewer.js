/* ===========================================================================
   TitulaTec · Visor de documentos (PDF.js → canvas, inmune al bloqueo del
   visor PDF del navegador). Lo usan la bandeja de Documentos y la agenda de
   Citas. El parcial titulatec/partials/_doc_viewer.html renderiza el markup;
   este módulo lo controla.

   Cargado una vez por base_admin; se re-inicializa en cada htmx:afterSettle.
   El markup de #tt-doc-review entra/sale con los swaps (re-enlazar sus botones
   es seguro). El modal #tt-doc-modal se reubica a <body> y PERSISTE: sus
   listeners se enlazan una sola vez (guarda data-tt-bound) para no duplicar.
   =========================================================================== */
(function () {
  'use strict';

  function pdfjs() {
    if (window.pdfjsLib) return Promise.resolve(window.pdfjsLib);
    if (window._ttPdfjsP) return window._ttPdfjsP;
    window._ttPdfjsP = new Promise(function (res, rej) {
      var s = document.createElement('script');
      s.src = 'https://cdn.jsdelivr.net/npm/pdfjs-dist@3.11.174/build/pdf.min.js';
      s.onload = function () {
        try { window.pdfjsLib.GlobalWorkerOptions.workerSrc = 'https://cdn.jsdelivr.net/npm/pdfjs-dist@3.11.174/build/pdf.worker.min.js'; } catch (e) {}
        res(window.pdfjsLib);
      };
      s.onerror = function () { rej(new Error('pdfjs load failed')); };
      document.head.appendChild(s);
    });
    return window._ttPdfjsP;
  }

  function fallback(el, url) {
    el.innerHTML = '<div class="tt-doc-empty">No se pudo previsualizar aquí. '
      + '<a href="' + url + '" target="_blank" rel="noopener">Abrir</a> · '
      + '<a href="' + url + '?download=1">Descargar</a></div>';
  }

  function renderInto(el, url, mime) {
    el.innerHTML = '<div class="tt-doc-loading"><span class="tt-spinner"></span> Cargando…</div>';
    if (mime && mime.indexOf('pdf') === -1) {
      el.innerHTML = '';
      var img = document.createElement('img');
      img.src = url; img.alt = 'Documento'; img.className = 'tt-doc-img';
      img.onerror = function () { fallback(el, url); };
      el.appendChild(img);
      return;
    }
    pdfjs().then(function (lib) {
      return lib.getDocument(url).promise.then(function (pdf) {
        el.innerHTML = '';
        var width = el.clientWidth || 600;
        var dpr = window.devicePixelRatio || 1;
        var chain = Promise.resolve();
        for (var n = 1; n <= pdf.numPages; n++) {
          (function (pageNum) {
            chain = chain.then(function () {
              return pdf.getPage(pageNum).then(function (page) {
                var vp = page.getViewport({ scale: 1 });
                var scale = width / vp.width;
                var svp = page.getViewport({ scale: scale * dpr });
                var canvas = document.createElement('canvas');
                canvas.className = 'tt-pdf-page';
                canvas.width = svp.width; canvas.height = svp.height;
                canvas.style.width = '100%';
                el.appendChild(canvas);
                return page.render({ canvasContext: canvas.getContext('2d'), viewport: svp }).promise;
              });
            });
          })(n);
        }
        return chain;
      });
    }).catch(function () { fallback(el, url); });
  }

  function init() {
    var root = document.getElementById('tt-doc-review');
    if (!root) return;
    var picks = Array.prototype.slice.call(root.querySelectorAll('.tt-docpick'));
    if (!picks.length) return;

    var stage = document.getElementById('tt-doc-stage');
    var nameEl = document.getElementById('tt-review-name');
    var statusEl = document.getElementById('tt-review-status');
    var typeInput = document.getElementById('tt-review-type');
    var noteWrap = document.getElementById('tt-doc-note');
    var noteText = document.getElementById('tt-doc-note-text');
    var openLink = document.getElementById('tt-doc-open');
    var dlLink = document.getElementById('tt-doc-download');
    var activeBtn = null;

    function setActive(btn) {
      activeBtn = btn;
      picks.forEach(function (p) { p.classList.toggle('tt-btn-ink', p === btn); p.classList.toggle('tt-btn-ghost', p !== btn); });
      if (typeInput) typeInput.value = btn.dataset.type;
      if (nameEl) nameEl.textContent = btn.dataset.name;
      if (statusEl) statusEl.innerHTML = btn.querySelector('.tt-pill') ? btn.querySelector('.tt-pill').outerHTML : '';
      if (openLink) openLink.href = btn.dataset.url;
      if (dlLink) dlLink.href = btn.dataset.url + '?download=1';
      if (noteWrap) {
        if (btn.dataset.status === 'rejected' && btn.dataset.note) { noteText.textContent = btn.dataset.note; noteWrap.style.display = ''; }
        else { noteWrap.style.display = 'none'; }
      }
      renderInto(stage, btn.dataset.url, btn.dataset.mime);
    }
    picks.forEach(function (p) { p.addEventListener('click', function () { setActive(p); }); });

    // ---- Modal compartido ----
    // El modal viaja dentro del contenido (para que el morph del menú lo traiga),
    // pero debe colgar de <body> (fuera de .tt-admin, que usa transforms). Lo
    // reubicamos y deduplicamos en cada init.
    var modals = document.querySelectorAll('#tt-doc-modal');
    var modalEl = modals.length ? modals[modals.length - 1] : null;
    for (var mi = 0; mi < modals.length - 1; mi++) modals[mi].remove();
    if (modalEl && modalEl.parentNode !== document.body) document.body.appendChild(modalEl);
    var modalStage = modalEl ? modalEl.querySelector('#tt-modal-stage') : null;
    var modalPicks = document.getElementById('tt-modal-picks');
    var modalOpen = document.getElementById('tt-modal-open');
    var modalNote = document.getElementById('tt-modal-note');
    var modalName = document.getElementById('tt-modal-name');
    var modalApprove = document.getElementById('tt-modal-approve');
    var modalReject = document.getElementById('tt-modal-reject');
    var noteBox = document.getElementById('tt-review-note');
    var inlineApprove = document.getElementById('tt-inline-approve');
    var inlineReject = document.getElementById('tt-inline-reject');
    var modalActive = null;

    function renderModal(btn) {
      if (!modalStage) return;
      modalActive = btn;
      if (modalOpen) modalOpen.href = btn.dataset.url;
      if (modalName) modalName.textContent = btn.dataset.name;
      if (modalPicks) Array.prototype.forEach.call(modalPicks.children, function (mb) {
        var on = mb.dataset.type === btn.dataset.type;
        mb.classList.toggle('tt-btn-ink', on); mb.classList.toggle('tt-btn-ghost', !on);
      });
      renderInto(modalStage, btn.dataset.url, btn.dataset.mime);
    }

    function syncNoteToInline() { if (modalNote && noteBox) noteBox.value = modalNote.value; }

    function actFromModal(action) {
      if (!modalActive) return;
      if (action === 'reject' && modalNote && !modalNote.value.trim()) {
        if (window.TitulaTecUtils) TitulaTecUtils.showToast('Indica el motivo del rechazo.', 'danger');
        modalNote.focus(); return;
      }
      if (typeInput) typeInput.value = modalActive.dataset.type;
      syncNoteToInline();
      var btn = action === 'approve' ? inlineApprove : inlineReject;
      if (modalEl && window.bootstrap) window.bootstrap.Modal.getOrCreateInstance(modalEl).hide();
      if (btn) btn.click();
    }

    // Listeners del modal persistente: enlazar UNA sola vez.
    if (modalNote && !modalNote.dataset.ttBound) {
      modalNote.dataset.ttBound = '1';
      modalNote.addEventListener('input', syncNoteToInline);
    }
    if (modalApprove && !modalApprove.dataset.ttBound) {
      modalApprove.dataset.ttBound = '1';
      modalApprove.addEventListener('click', function () { actFromModal('approve'); });
    }
    if (modalReject && !modalReject.dataset.ttBound) {
      modalReject.dataset.ttBound = '1';
      modalReject.addEventListener('click', function () { actFromModal('reject'); });
    }
    if (modalEl && !modalEl.dataset.ttHiddenBound) {
      modalEl.dataset.ttHiddenBound = '1';
      modalEl.addEventListener('hidden.bs.modal', syncNoteToInline);
    }

    // El botón "Expandir" está dentro del contenido swappeado → re-enlazar es seguro.
    var expandBtn = document.getElementById('tt-doc-expand');
    if (expandBtn && modalEl) {
      expandBtn.addEventListener('click', function () {
        if (!window.bootstrap) return;
        if (modalPicks) {
          modalPicks.innerHTML = '';
          picks.forEach(function (p) {
            var mb = document.createElement('button');
            mb.type = 'button'; mb.className = 'btn btn-sm tt-btn-ghost';
            mb.dataset.type = p.dataset.type; mb.dataset.url = p.dataset.url; mb.dataset.mime = p.dataset.mime;
            mb.dataset.name = p.dataset.name;
            mb.innerHTML = p.innerHTML;
            mb.addEventListener('click', function () { renderModal(mb); });
            modalPicks.appendChild(mb);
          });
        }
        if (modalNote && noteBox) modalNote.value = noteBox.value;
        window.bootstrap.Modal.getOrCreateInstance(modalEl).show();
        setTimeout(function () { if (activeBtn) renderModal(activeBtn); }, 180);
      });
    }

    setActive(picks[0]);
  }

  document.body.addEventListener('htmx:afterSettle', init);
  if (document.readyState !== 'loading') init();
  else document.addEventListener('DOMContentLoaded', init);
})();
