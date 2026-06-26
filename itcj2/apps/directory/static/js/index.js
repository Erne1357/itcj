(function () {
  'use strict';

  // ── Toast ────────────────────────────────────────────────────────────────
  function ensureToastHost() {
    var host = document.getElementById('dir-toast-host');
    if (!host) {
      host = document.createElement('div');
      host.id = 'dir-toast-host';
      host.className = 'toast-container position-fixed bottom-0 end-0 p-3';
      host.style.zIndex = '1090';
      document.body.appendChild(host);
    }
    return host;
  }

  function showToast(message, type) {
    var host = ensureToastHost();
    var el = document.createElement('div');
    el.className = 'toast align-items-center text-bg-' + (type || 'secondary') + ' border-0';
    el.setAttribute('role', 'alert');
    el.innerHTML = '<div class="d-flex"><div class="toast-body"></div>' +
      '<button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button></div>';
    el.querySelector('.toast-body').textContent = message;
    host.appendChild(el);
    var t = new bootstrap.Toast(el, { delay: 4000 });
    t.show();
    el.addEventListener('hidden.bs.toast', function () { el.remove(); });
  }

  // ── Confirm modal (reemplaza confirm() nativo) ─────────────────────────────
  function confirmDialog(title, message, confirmText, cancelText) {
    return new Promise(function (resolve) {
      var modalEl = document.getElementById('dirConfirmModal');
      if (!modalEl) { resolve(false); return; }
      modalEl.querySelector('[data-dir-confirm-title]').textContent = title || 'Confirmar';
      modalEl.querySelector('[data-dir-confirm-body]').textContent = message || '';
      var okBtn = modalEl.querySelector('[data-dir-confirm-ok]');
      okBtn.textContent = confirmText || 'Confirmar';
      modalEl.querySelector('[data-dir-confirm-cancel]').textContent = cancelText || 'Cancelar';
      var modal = bootstrap.Modal.getOrCreateInstance(modalEl);
      var settled = false;
      function onOk() { settled = true; modal.hide(); cleanup(); resolve(true); }
      function onHidden() { if (!settled) { cleanup(); resolve(false); } }
      function cleanup() {
        okBtn.removeEventListener('click', onOk);
        modalEl.removeEventListener('hidden.bs.modal', onHidden);
      }
      okBtn.addEventListener('click', onOk);
      modalEl.addEventListener('hidden.bs.modal', onHidden);
      modal.show();
    });
  }

  window.DirectoryUtils = { showToast: showToast, confirmDialog: confirmDialog };

  // ── hx-confirm → modal Bootstrap (no confirm nativo) ───────────────────────
  document.body.addEventListener('htmx:confirm', function (e) {
    if (!e.detail.question) return;            // sin hx-confirm → request normal
    e.preventDefault();
    confirmDialog('Confirmar', e.detail.question, 'Eliminar', 'Cancelar').then(function (ok) {
      if (ok) e.detail.issueRequest(true);
    });
  });

  // ── Errores HTMX → toast (header X-Dir-Error) ──────────────────────────────
  document.body.addEventListener('htmx:responseError', function (e) {
    var msg = (e.detail.xhr && e.detail.xhr.getResponseHeader('X-Dir-Error')) || 'Ocurrió un error.';
    showToast(msg, 'danger');
  });
  document.body.addEventListener('htmx:afterRequest', function (e) {
    var xhr = e.detail.xhr;
    if (xhr && xhr.status >= 200 && xhr.status < 300) {
      var err = xhr.getResponseHeader('X-Dir-Error');
      if (err) showToast(err, 'warning');
    }
  });

  // ── Re-disparo de animación de entrada en cada swap ────────────────────────
  document.body.addEventListener('htmx:afterSwap', function (e) {
    var scope = e.target || document;
    scope.querySelectorAll('.dir-anim-in').forEach(function (n) {
      n.classList.remove('dir-anim-in');
      void n.offsetWidth;                       // reflow para reiniciar
      n.classList.add('dir-anim-in');
    });
  });

  // ── Init idempotente (morph-safe) ──────────────────────────────────────────
  function init() {
    bindEntryModal();
    bindPositionModal();
  }

  function bindEntryModal() {
    var modalEl = document.getElementById('dirEntryModal');
    if (!modalEl || modalEl.dataset.dirBound) return;
    modalEl.dataset.dirBound = '1';
    var form = document.getElementById('dirEntryForm');
    var title = document.getElementById('dirEntryTitle');

    modalEl.addEventListener('show.bs.modal', function (ev) {
      var t = ev.relatedTarget;
      var action = t ? t.getAttribute('data-dir-action') : 'new-entry';
      form.removeAttribute('hx-post');
      form.removeAttribute('hx-patch');
      if (action === 'edit-entry') {
        title.textContent = 'Editar extensión';
        form.setAttribute('hx-patch', '/directory/entries/' + t.getAttribute('data-dir-id'));
        form.querySelector('[name=department_id]').value = t.getAttribute('data-dir-dept') || '';
        form.querySelector('[name=label]').value = t.getAttribute('data-dir-label') || '';
        form.querySelector('[name=holder_name]').value = t.getAttribute('data-dir-holder') || '';
        form.querySelector('[name=extension]').value = t.getAttribute('data-dir-ext') || '';
        form.querySelector('[name=notes]').value = t.getAttribute('data-dir-notes') || '';
      } else {
        title.textContent = 'Agregar extensión';
        form.setAttribute('hx-post', '/directory/entries');
        form.reset();
      }
      if (window.htmx) window.htmx.process(form);
    });

    form.addEventListener('htmx:afterRequest', function (e) {
      var xhr = e.detail.xhr;
      if (e.detail.successful && !(xhr && xhr.getResponseHeader('X-Dir-Error'))) {
        bootstrap.Modal.getInstance(modalEl).hide();
        showToast('Guardado.', 'success');
      }
    });
  }

  function bindPositionModal() {
    var modalEl = document.getElementById('dirPosModal');
    if (!modalEl || modalEl.dataset.dirBound) return;
    modalEl.dataset.dirBound = '1';
    var form = document.getElementById('dirPosForm');
    var title = document.getElementById('dirPosTitle');

    modalEl.addEventListener('show.bs.modal', function (ev) {
      var t = ev.relatedTarget;
      if (!t) return;
      title.textContent = 'Extensión · ' + (t.getAttribute('data-dir-title') || '');
      form.setAttribute('hx-patch', '/directory/positions/' + t.getAttribute('data-dir-pos') + '/extension');
      form.querySelector('[name=extension]').value = t.getAttribute('data-dir-ext') || '';
      form.querySelector('[name=notes]').value = t.getAttribute('data-dir-notes') || '';
      if (window.htmx) window.htmx.process(form);
    });

    form.addEventListener('htmx:afterRequest', function (e) {
      var xhr = e.detail.xhr;
      if (e.detail.successful && !(xhr && xhr.getResponseHeader('X-Dir-Error'))) {
        bootstrap.Modal.getInstance(modalEl).hide();
        showToast('Extensión actualizada.', 'success');
      }
    });
  }

  document.addEventListener('DOMContentLoaded', init);
  document.body.addEventListener('htmx:afterSettle', init);
})();
