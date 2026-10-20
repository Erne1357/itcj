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

  // ── Portapapeles ───────────────────────────────────────────────────────────
  // La rama se elige de forma SINCRONA: dentro del iframe del shell movil y en
  // origen inseguro (http://IP-LAN:8080 en dev) navigator.clipboard no existe o
  // rechaza con NotAllowedError / "Document is not focused".
  function copyToClipboard(text) {
    if (!text) return Promise.resolve(false);
    if (window.isSecureContext && navigator.clipboard && navigator.clipboard.writeText) {
      return navigator.clipboard.writeText(text).then(
        function () { return true; },
        function () { return legacyCopy(text); }
      );
    }
    return Promise.resolve(legacyCopy(text));
  }

  function legacyCopy(text) {
    var ta = document.createElement('textarea');
    ta.value = text;
    ta.setAttribute('readonly', '');
    // Dentro del viewport a proposito: fuera de pantalla iOS no copia. font-size
    // 16px evita el zoom automatico de Safari al enfocar.
    ta.style.cssText = 'position:fixed;top:0;left:0;width:1px;height:1px;opacity:0;font-size:16px;';
    document.body.appendChild(ta);
    var ok = false;
    try {
      ta.select();
      ta.setSelectionRange(0, ta.value.length);   // rodeo iOS
      ok = document.execCommand('copy');
    } catch (e) {
      ok = false;
    }
    ta.remove();
    return ok;
  }

  window.DirectoryUtils = {
    showToast: showToast,
    confirmDialog: confirmDialog,
    copyToClipboard: copyToClipboard
  };

  // ── Delegacion global ──────────────────────────────────────────────────────
  // Todos los listeners cuelgan de document.body al nivel del IIFE: nunca guardas
  // data-*-bound dentro de lo que morphea.

  // Copiar: el dato se lee de data-dir-copy, nunca de textContent.
  document.body.addEventListener('click', function (e) {
    var btn = e.target.closest && e.target.closest('[data-dir-copy]');
    if (!btn) return;
    var value = btn.getAttribute('data-dir-copy');
    copyToClipboard(value).then(function (ok) {
      showToast(ok ? 'Copiado: ' + value : 'No se pudo copiar. Selecciónalo a mano.',
                ok ? 'success' : 'warning');
      btn.focus();
    });
  });

  // Limpiar filtros / ver todas: el boton NO puede llevar hx-include="#dir-filters"
  // (reenviaria los mismos filtros), asi que los controles se limpian aqui.
  document.body.addEventListener('click', function (e) {
    var btn = e.target.closest &&
      e.target.closest('[data-dir-action="clear-filters"], [data-dir-action="reset-source"]');
    if (!btn) return;
    var form = document.getElementById('dir-filters');
    if (!form) return;
    if (btn.getAttribute('data-dir-action') === 'clear-filters') {
      var q = form.querySelector('[name=q]');
      var dept = form.querySelector('[name=filter_dept]');
      if (q) q.value = '';
      if (dept) dept.value = '';
    }
    var source = form.querySelector('[name=source]');
    if (source) source.value = 'all';
  });

  // El servidor percent-encodea X-Dir-Error: los headers HTTP no transportan
  // acentos de forma fiable (Starlette los codifica en latin-1 y el cliente los
  // lee como UTF-8). ASCII puro en el cable, texto intacto en pantalla.
  function dirError(xhr) {
    var raw = xhr && xhr.getResponseHeader('X-Dir-Error');
    if (!raw) return null;
    try { return decodeURIComponent(raw); } catch (e) { return raw; }
  }

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
    showToast(dirError(e.detail.xhr) || 'Ocurrió un error.', 'danger');
  });
  document.body.addEventListener('htmx:afterRequest', function (e) {
    var xhr = e.detail.xhr;
    if (xhr && xhr.status >= 200 && xhr.status < 300) {
      var err = dirError(xhr);
      // Si el error viene anclado a un campo, lo pinta el handler del modal.
      if (err && !xhr.getResponseHeader('X-Dir-Field')) showToast(err, 'warning');
    }
  });

  // ── Animacion acotada ──────────────────────────────────────────────────────
  // Antes se re-animaban los 26 grupos en CADA swap: una rafaga de tecleo
  // convertia la lista en un parpadeo. Solo animan los grupos que NO estaban en
  // el DOM antes del swap.
  //
  // Se fotografian los NODOS en htmx:beforeSwap, no ids en un Set global: un Set
  // que nace vacio deja el PRIMER swap re-animando todo (los grupos del render
  // inicial nunca pasan por afterSwap). Y WeakSet de nodos porque idiomorph
  // conserva el mismo objeto DOM cuando el id sobrevive, asi que «sobrevivio al
  // morph» == «ya estaba antes del swap». Un grupo que sale del filtro y vuelve
  // es un nodo NUEVO, y debe animar.
  var preSwapGroups = new WeakSet();

  document.body.addEventListener('htmx:beforeSwap', function () {
    document.querySelectorAll('.dir-group').forEach(function (n) { preSwapGroups.add(n); });
  });

  document.body.addEventListener('htmx:afterSwap', function () {
    document.querySelectorAll('.dir-group').forEach(function (n) {
      if (preSwapGroups.has(n)) n.classList.remove('dir-anim-in');
    });
  });

  // ── Init idempotente (morph-safe) ──────────────────────────────────────────
  function init() {
    bindEntryModal();
    bindPositionModal();
  }

  function clearFieldErrors(form) {
    form.querySelectorAll('.is-invalid').forEach(function (el) {
      el.classList.remove('is-invalid');
    });
    form.querySelectorAll('.invalid-feedback').forEach(function (el) {
      el.textContent = '';
    });
  }

  /** Error anclado a un campo: marca el input y deja el modal ABIERTO. */
  function handleModalResponse(modalEl, form, e, successMessage) {
    var xhr = e.detail.xhr;
    var err = dirError(xhr);
    var field = xhr && xhr.getResponseHeader('X-Dir-Field');
    if (field) {
      var input = form.querySelector('[name=' + field + ']');
      if (input) {
        input.classList.add('is-invalid');
        var fb = input.parentElement.querySelector('.invalid-feedback');
        if (fb) fb.textContent = err || '';
        input.focus();
      } else {
        showToast(err || 'Ocurrió un error.', 'warning');
      }
      return;
    }
    if (e.detail.successful && !err) {
      bootstrap.Modal.getInstance(modalEl).hide();
      showToast(successMessage, 'success');
    }
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
      clearFieldErrors(form);
      form.removeAttribute('hx-post');
      form.removeAttribute('hx-patch');
      if (action === 'edit-entry') {
        title.textContent = 'Editar extensión';
        form.setAttribute('hx-patch', '/directory/entries/' + t.getAttribute('data-dir-id'));
        form.querySelector('[name=department_id]').value = t.getAttribute('data-dir-dept') || '';
        form.querySelector('[name=label]').value = t.getAttribute('data-dir-label') || '';
        form.querySelector('[name=holder_name]').value = t.getAttribute('data-dir-holder') || '';
        form.querySelector('[name=extension]').value = t.getAttribute('data-dir-ext') || '';
        form.querySelector('[name=email]').value = t.getAttribute('data-dir-email') || '';
        form.querySelector('[name=notes]').value = t.getAttribute('data-dir-notes') || '';
      } else {
        title.textContent = 'Agregar extensión';
        form.setAttribute('hx-post', '/directory/entries');
        form.reset();
        // Alta desde el hueco de un grupo vacio: preselecciona ese departamento.
        var preDept = t && t.getAttribute('data-dir-dept');
        if (preDept) form.querySelector('[name=department_id]').value = preDept;
      }
      if (window.htmx) window.htmx.process(form);
    });

    form.addEventListener('htmx:afterRequest', function (e) {
      handleModalResponse(modalEl, form, e, 'Guardado.');
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
      clearFieldErrors(form);
      title.textContent = 'Contacto · ' + (t.getAttribute('data-dir-title') || '');
      form.setAttribute('hx-patch', '/directory/positions/' + t.getAttribute('data-dir-pos') + '/extension');
      form.querySelector('[name=extension]').value = t.getAttribute('data-dir-ext') || '';
      form.querySelector('[name=email]').value = t.getAttribute('data-dir-email') || '';
      form.querySelector('[name=notes]').value = t.getAttribute('data-dir-notes') || '';
      if (window.htmx) window.htmx.process(form);
    });

    form.addEventListener('htmx:afterRequest', function (e) {
      handleModalResponse(modalEl, form, e, 'Contacto actualizado.');
    });
  }

  document.addEventListener('DOMContentLoaded', init);
  document.body.addEventListener('htmx:afterSettle', init);
})();
