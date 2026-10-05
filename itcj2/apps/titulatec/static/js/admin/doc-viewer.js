/* ===========================================================================
   TitulaTec · Admin — Visor de Documentos (bandeja de revisión, fase 1).

   PDF.js → canvas (inmune al bloqueo del visor PDF del navegador), selector de
   documento activo, nota de rechazo, «Abrir en pestaña»/«Descargar», modal
   grande (`#tt-doc-modal`) con su propio selector y dictamen, y el estado de
   dictamen de 2026-10-04 (`applyReviewState`).

   Antes vivía INLINE al final de `partials/documents_body.html`: corría antes
   de `bootstrap.bundle` y antes de que existiera el modal, y al llegar por el
   menú lateral (morph de `#tt-admin-content`) el modal ni se traía, así que
   «Expandir» nunca enganchaba.

   Contrato, igual que `admin/appointments.js` y `admin/expediente.js`:
     - se carga UNA vez desde `admin/base_admin.html` (el bloque `scripts` no
       entra al morph), con guarda de doble carga;
     - los clics van por delegación en `document.body` y leen el DOM VIGENTE
       en cada clic (nada de nodos capturados de un render anterior);
     - `#docs-body` se re-pinta con innerHTML (pager, filtros, dictamen,
       elegir alumno): `init(root)` recalcula el estado desde el DOM nuevo en
       cada `htmx:afterSettle`;
     - el modal vive en `{% block modals %}` de `base_admin.html`, FUERA de
       todo swap: sus listeners propios (input de la nota, `hidden.bs.modal`)
       se enlazan una sola vez con la guarda `data-tt-bound` sobre el modal.
       Ahí sí es seguro escribirla: Idiomorph nunca toca ese nodo (en el
       contenido morpheado la borraría, por eso los demás módulos no la usan).

   Expone solo `window.TitulaTecDocViewer = { init(root) }`.
   =========================================================================== */
(function () {
  'use strict';

  if (window.TitulaTecDocViewer) return;   // doble carga del <script>

  function $(id) { return document.getElementById(id); }

  // ————————————————————————————————— PDF.js (carga perezosa)
  var PDFJS_SRC = 'https://cdn.jsdelivr.net/npm/pdfjs-dist@3.11.174/build/pdf.min.js';
  var PDFJS_WORKER = 'https://cdn.jsdelivr.net/npm/pdfjs-dist@3.11.174/build/pdf.worker.min.js';
  var pdfjsP = null;

  function pdfjs() {
    if (window.pdfjsLib) return Promise.resolve(window.pdfjsLib);
    if (pdfjsP) return pdfjsP;
    pdfjsP = new Promise(function (res, rej) {
      var s = document.createElement('script');
      s.src = PDFJS_SRC;
      s.onload = function () {
        try { window.pdfjsLib.GlobalWorkerOptions.workerSrc = PDFJS_WORKER; } catch (e) {}
        res(window.pdfjsLib);
      };
      s.onerror = function () { rej(new Error('pdfjs load failed')); };
      document.head.appendChild(s);
    });
    return pdfjsP;
  }

  function escAttr(s) {
    return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/"/g, '&quot;')
      .replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  function fallback(el, url) {
    var u = escAttr(url);
    el.innerHTML = '<div class="tt-doc-empty">No se pudo previsualizar aquí. '
      + '<a href="' + u + '" target="_blank" rel="noopener">Abrir</a> · '
      + '<a href="' + u + '?download=1">Descargar</a></div>';
  }

  function renderInto(el, url, mime) {
    if (!el) return;
    el.innerHTML = '<div class="tt-doc-loading"><span class="tt-spinner"></span> Cargando…</div>';
    if (mime && mime.indexOf('pdf') === -1) {           // imagen
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

  // ————————————————————————————————— estado (se recalcula en cada init)
  var S = {
    root: null,          // #tt-doc-review vigente
    picks: [],           // .tt-docpick del root vigente
    phaseClosed: false,  // data-phase-closed="1" del root
    activeBtn: null,     // pick activo en el panel inline
    modalActive: null,   // pick mostrado en el modal
    acting: false        // actFromModal ya volcó la nota: el hidden no la re-vuelca
  };

  function setActive(btn, intoModal) {
    S.activeBtn = btn;
    S.picks.forEach(function (p) {
      p.classList.toggle('tt-btn-ink', p === btn);
      p.classList.toggle('tt-btn-ghost', p !== btn);
    });
    var typeInput = $('tt-review-type');
    var nameEl = $('tt-review-name');
    var statusEl = $('tt-review-status');
    var openLink = $('tt-doc-open');
    var dlLink = $('tt-doc-download');
    var noteWrap = $('tt-doc-note');
    var noteText = $('tt-doc-note-text');
    if (typeInput) typeInput.value = btn.dataset.type;
    if (nameEl) nameEl.textContent = btn.dataset.name;
    if (statusEl) statusEl.innerHTML = btn.querySelector('.tt-pill') ? btn.querySelector('.tt-pill').outerHTML : '';
    if (openLink) openLink.href = btn.dataset.url;
    if (dlLink) dlLink.href = btn.dataset.url + '?download=1';
    if (noteWrap) {
      if (btn.dataset.status === 'rejected' && btn.dataset.note) {
        if (noteText) noteText.textContent = btn.dataset.note;
        noteWrap.style.display = '';
      } else {
        noteWrap.style.display = 'none';
      }
    }
    applyReviewState(btn);
    renderInto($('tt-doc-stage'), btn.dataset.url, btn.dataset.mime);
    if (intoModal) renderModal(btn);
  }

  // ————————————————————————————————— fase cerrada y re-confirmación (2026-10-04)
  // `data-phase-closed` (fase 1 ya aprobada): sin Rechazar, y sin Aprobar sobre
  // uno ya aprobado -- el servidor lo rechaza igual (`DocumentService.review`).
  // `data-closes` (aprobar ESTE cierra la fase): el botón inline lleva
  // `hx-confirm`, que el puente de `titulatec-utils.js` convierte en
  // `confirmDialog`. El modal reusa ese mismo botón, así que hereda el aviso.
  //
  // Además (el modal ya no es de la página sino de la base): sus botones solo
  // se muestran si existe el botón inline al que delegan. El form inline se
  // pinta solo con `can_review_docs` (arreglo A2), así que sin permiso el
  // modal tampoco ofrece dictamen aunque se haya pintado en otra vista.
  var CLOSE_CONFIRM = 'Aprobar y avanzar de fase|Es el último documento por aprobar. '
    + 'Al aprobarlo, el estatus de los documentos ya no se podrá cambiar '
    + 'y el alumno pasará a la siguiente fase.';

  function applyReviewState(pick) {
    var inline = $('tt-inline-approve');
    var inlineRej = $('tt-inline-reject');
    var hideApprove = S.phaseClosed && pick.dataset.status === 'approved';
    if (inline) inline.hidden = hideApprove;
    var modalApprove = $('tt-modal-approve');
    if (modalApprove) modalApprove.hidden = hideApprove || !inline;
    var modalRej = $('tt-modal-reject');
    if (modalRej) modalRej.hidden = S.phaseClosed || !inlineRej;
    var actions = $('tt-modal-actions');
    if (actions) actions.hidden = !inline && !inlineRej;
    if (!inline) return;
    if (pick.dataset.closes === '1') {
      inline.setAttribute('hx-confirm', CLOSE_CONFIRM);
      inline.setAttribute('data-tt-confirm-ok', 'Aprobar y avanzar');
    } else {
      inline.removeAttribute('hx-confirm');
      inline.removeAttribute('data-tt-confirm-ok');
    }
  }

  // ————————————————————————————————— modal (visor grande + dictamen)
  function renderModal(btn) {
    var modalStage = $('tt-modal-stage');
    if (!modalStage) return;
    S.modalActive = btn;
    var modalOpen = $('tt-modal-open');
    var modalName = $('tt-modal-name');
    var modalPicks = $('tt-modal-picks');
    if (modalOpen) modalOpen.href = btn.dataset.url;
    if (modalName) modalName.textContent = btn.dataset.name;
    applyReviewState(btn);
    if (modalPicks) Array.prototype.forEach.call(modalPicks.children, function (mb) {
      var on = mb.dataset.type === btn.dataset.type;
      mb.classList.toggle('tt-btn-ink', on); mb.classList.toggle('tt-btn-ghost', !on);
    });
    renderInto(modalStage, btn.dataset.url, btn.dataset.mime);
  }

  // Sincroniza la nota del modal hacia el form inline (fuente de verdad de HTMX).
  function syncNoteToInline() {
    var modalNote = $('tt-modal-note');
    var noteBox = $('tt-review-note');
    if (modalNote && noteBox) noteBox.value = modalNote.value;
  }

  // Acción desde el modal: copia nota + fija el tipo activo del modal en el form
  // inline y dispara su botón HTMX (reusa el mismo POST). Luego cierra el modal.
  function actFromModal(action) {
    if (!S.modalActive) return;
    var modalNote = $('tt-modal-note');
    if (action === 'reject' && modalNote && !modalNote.value.trim()) {
      if (window.TitulaTecUtils) window.TitulaTecUtils.showToast('Indica el motivo del rechazo.', 'danger');
      modalNote.focus();
      return;
    }
    var typeInput = $('tt-review-type');
    if (typeInput) typeInput.value = S.modalActive.dataset.type;  // el doc activo es el del modal
    syncNoteToInline();
    var btn = action === 'approve' ? $('tt-inline-approve') : $('tt-inline-reject');
    var modalEl = $('tt-doc-modal');
    if (modalEl && window.bootstrap) {
      // La nota ya se volcó: el `hidden.bs.modal` (que llega tras la animación,
      // quizá con #docs-body ya re-pintado) no debe volcarla al form NUEVO.
      S.acting = true;
      window.bootstrap.Modal.getOrCreateInstance(modalEl).hide();
    }
    // Al cerrar el modal el panel inline sigue en SU doc: el aviso de cierre
    // tiene que ser el del doc del modal, que es el que se va a dictaminar.
    applyReviewState(S.modalActive);
    if (btn) btn.click();
  }

  function expand() {
    var modalEl = $('tt-doc-modal');
    if (!modalEl || !window.bootstrap || !S.picks.length) return;
    // (re)construye los picks del modal a partir de los actuales
    var modalPicks = $('tt-modal-picks');
    if (modalPicks) {
      modalPicks.innerHTML = '';
      S.picks.forEach(function (p) {
        var mb = document.createElement('button');
        mb.type = 'button'; mb.className = 'btn btn-sm tt-btn-ghost';
        mb.dataset.type = p.dataset.type; mb.dataset.url = p.dataset.url; mb.dataset.mime = p.dataset.mime;
        mb.dataset.name = p.dataset.name;
        mb.dataset.status = p.dataset.status; mb.dataset.closes = p.dataset.closes;
        mb.innerHTML = p.innerHTML;
        modalPicks.appendChild(mb);
      });
    }
    // arranca el modal en el mismo doc que el visor inline y con la misma nota
    var modalNote = $('tt-modal-note');
    var noteBox = $('tt-review-note');
    if (modalNote && noteBox) modalNote.value = noteBox.value;
    S.acting = false;
    window.bootstrap.Modal.getOrCreateInstance(modalEl).show();
    setTimeout(function () { if (S.activeBtn) renderModal(S.activeBtn); }, 180);
  }

  // Listeners propios del modal: UNA vez (vive fuera de todo swap).
  function bindModal() {
    var modalEl = $('tt-doc-modal');
    if (!modalEl || modalEl.hasAttribute('data-tt-bound')) return;
    modalEl.setAttribute('data-tt-bound', '1');
    modalEl.addEventListener('input', function (e) {
      if (e.target && e.target.id === 'tt-modal-note') syncNoteToInline();
    });
    // Al cerrar el modal, vuelca la nota del modal al panel normal.
    modalEl.addEventListener('hidden.bs.modal', function () {
      if (S.acting) { S.acting = false; return; }
      syncNoteToInline();
    });
  }

  // ————————————————————————————————— delegación (una sola vez)
  document.body.addEventListener('click', function (e) {
    var t = e.target;
    if (!t || !t.closest) return;

    var mb = t.closest('#tt-modal-picks button');
    if (mb) { renderModal(mb); return; }

    if (t.closest('#tt-modal-approve')) { actFromModal('approve'); return; }
    if (t.closest('#tt-modal-reject')) { actFromModal('reject'); return; }

    var root = t.closest('#tt-doc-review');
    if (!root) return;
    if (root !== S.root) init(root);      // clic antes del afterSettle: estado al día

    if (t.closest('#tt-doc-expand')) { expand(); return; }

    var pick = t.closest('.tt-docpick');
    if (pick && S.picks.indexOf(pick) !== -1) setActive(pick, false);
  });

  // ————————————————————————————————— init
  function init(root) {
    bindModal();
    root = root || $('tt-doc-review');
    S.root = null; S.picks = []; S.phaseClosed = false;
    S.activeBtn = null; S.modalActive = null;
    if (!root) return;
    S.root = root;
    S.picks = Array.prototype.slice.call(root.querySelectorAll('.tt-docpick'));
    S.phaseClosed = root.dataset.phaseClosed === '1';
    if (!S.picks.length) return;
    setActive(S.picks[0], false);         // init: primer doc
  }

  // Tras cada swap: re-inicia solo si el swap trajo (o tocó) el detalle; un
  // swap ajeno a la bandeja no debe devolver el visor al primer documento.
  document.body.addEventListener('htmx:afterSettle', function (e) {
    var root = $('tt-doc-review');
    if (!root) { if (S.root) init(null); else bindModal(); return; }
    var t = e.target;
    if (root === S.root && !(t && t.contains && t.contains(root))) return;
    init(root);
  });

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () { init(); });
  } else {
    init();
  }

  window.TitulaTecDocViewer = { init: init };
})();
