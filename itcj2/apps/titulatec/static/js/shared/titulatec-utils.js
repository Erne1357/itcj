/* ===========================================================================
   TitulaTec — utils compartidos (toast + confirmDialog).
   PROHIBIDO confirm()/alert()/prompt() nativos. Usar estos helpers.
   Expone window.TitulaTecUtils.
   =========================================================================== */
(function () {
  'use strict';

  function escapeHtml(str) {
    if (str == null) return '';
    return String(str)
      .replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;').replaceAll("'", '&#039;');
  }

  function _toastContainer() {
    let c = document.getElementById('tt-toast-container');
    if (!c) {
      c = document.createElement('div');
      c.id = 'tt-toast-container';
      c.className = 'toast-container position-fixed top-0 end-0 p-3';
      c.style.zIndex = '1090';
      document.body.appendChild(c);
    }
    return c;
  }

  // type: success | danger | warning | info
  function showToast(message, type = 'info') {
    const tones = {
      success: 'tt-pill--success', danger: 'tt-pill--danger',
      warning: 'tt-pill--amber', info: 'tt-pill--navy',
    };
    const icons = {
      success: 'check-circle', danger: 'exclamation-octagon',
      warning: 'exclamation-triangle', info: 'info-circle',
    };
    const el = document.createElement('div');
    el.className = 'toast align-items-center border-0 mb-2';
    el.setAttribute('role', 'alert');
    el.innerHTML =
      '<div class="d-flex align-items-center tt-card p-2">' +
      '<span class="tt-pill ' + (tones[type] || tones.info) + ' me-2">' +
      '<i class="bi bi-' + (icons[type] || icons.info) + '"></i></span>' +
      '<div class="flex-grow-1" style="font-size:.85rem">' + escapeHtml(message) + '</div>' +
      '<button type="button" class="btn-close ms-2" data-bs-dismiss="toast"></button></div>';
    _toastContainer().appendChild(el);
    const t = new bootstrap.Toast(el, { delay: 4000 });
    t.show();
    el.addEventListener('hidden.bs.toast', () => el.remove());
  }

  // Devuelve Promise<boolean>. Reemplazo de confirm().
  function confirmDialog(title, message, confirmText = 'Confirmar', cancelText = 'Cancelar') {
    return new Promise((resolve) => {
      const id = 'tt-confirm-' + Date.now();
      const wrap = document.createElement('div');
      wrap.innerHTML =
        '<div class="modal fade" id="' + id + '" tabindex="-1">' +
        '<div class="modal-dialog modal-dialog-centered"><div class="modal-content tt-card">' +
        '<div class="modal-header border-0"><h5 class="modal-title tt-display">' + escapeHtml(title) + '</h5>' +
        '<button type="button" class="btn-close" data-bs-dismiss="modal"></button></div>' +
        '<div class="modal-body" style="font-size:.9rem">' + escapeHtml(message) + '</div>' +
        '<div class="modal-footer border-0">' +
        '<button type="button" class="btn tt-btn-ghost" data-tt-action="cancel">' + escapeHtml(cancelText) + '</button>' +
        '<button type="button" class="btn tt-btn-ink" data-tt-action="confirm">' + escapeHtml(confirmText) + '</button>' +
        '</div></div></div></div>';
      document.body.appendChild(wrap);
      const modalEl = wrap.querySelector('.modal');
      const modal = new bootstrap.Modal(modalEl);
      let result = false;
      modalEl.querySelector('[data-tt-action="confirm"]').addEventListener('click', () => { result = true; modal.hide(); });
      modalEl.querySelector('[data-tt-action="cancel"]').addEventListener('click', () => { result = false; modal.hide(); });
      modalEl.addEventListener('hidden.bs.modal', () => { wrap.remove(); resolve(result); });
      modal.show();
    });
  }

  // — Animación de entrada para contenido insertado por HTMX —
  // El emisor recibe .htmx-request automáticamente (spinner en botones vía CSS).
  // Aquí re-disparamos la animación de entrada en el destino del swap.
  document.body.addEventListener('htmx:afterSwap', function (e) {
    var t = e.detail && e.detail.target;
    if (t && t.classList) {
      t.classList.remove('tt-anim-in');
      void t.offsetWidth;            // reinicia la animación
      t.classList.add('tt-anim-in');
    }
  });

  window.TitulaTecUtils = { showToast, confirmDialog, escapeHtml };
})();
