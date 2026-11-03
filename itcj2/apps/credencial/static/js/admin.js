/* Panel de Servicios Escolares: ficha del alumno (subir/reemplazar/eliminar) y carga por lote. */
(function () {
  'use strict';

  const BASE = '/credencial/admin';
  const CHUNK = 10;                       // archivos por peticion
  const CHUNK_BYTES = 24 * 1024 * 1024;   // nginx corta en 30 MB: margen para el multipart
  const STATUS = {
    created: ['Nueva', 'ca-state--ok'],
    replaced: ['Reemplazada', 'ca-state--ok'],
    no_student: ['Sin alumno', 'ca-state--bad'],
    invalid: ['Rechazada', 'ca-state--bad'],
    pending: ['En espera', 'ca-state--missing'],
    sending: ['Subiendo…', 'ca-state--missing'],
  };

  // === UTILIDADES ===
  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  function extractErrorMessage(data, fallback) {
    if (typeof data === 'string') return data || fallback;
    if (!data || typeof data !== 'object') return fallback;
    const val = data.detail || data.message || data.error;
    if (typeof val === 'string') return val || fallback;
    if (Array.isArray(val)) return val.map((e) => (e && e.msg) ? e.msg : String(e)).join('; ') || fallback;
    return fallback;
  }

  async function fetchApiError(response, fallback) {
    if (response.status === 413) return 'El envío pesa demasiado para el servidor. Sube menos fotos a la vez.';
    if (response.status === 401) return 'Tu sesión venció. Recarga la página e inicia sesión.';
    try {
      return extractErrorMessage(await response.json(), fallback);
    } catch (_) {
      return `${fallback} (HTTP ${response.status})`;
    }
  }

  function showToast(message, type) {
    let host = document.getElementById('ca-toasts');
    if (!host) {
      host = document.createElement('div');
      host.id = 'ca-toasts';
      host.className = 'toast-container position-fixed bottom-0 end-0 p-3';
      host.style.zIndex = '1090';
      document.body.appendChild(host);
    }
    const el = document.createElement('div');
    el.className = `toast align-items-center text-bg-${type || 'secondary'} border-0`;
    el.setAttribute('role', 'alert');
    el.innerHTML = '<div class="d-flex"><div class="toast-body"></div>' +
      '<button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Cerrar"></button></div>';
    el.querySelector('.toast-body').textContent = message;
    host.appendChild(el);
    el.addEventListener('hidden.bs.toast', () => el.remove());
    new bootstrap.Toast(el, { delay: 5000 }).show();
  }

  async function postFile(url, formData) {
    const res = await fetch(url, { method: 'POST', body: formData, credentials: 'same-origin' });
    if (!res.ok) {
      const err = new Error(await fetchApiError(res, 'No se pudo subir la foto'));
      err.status = res.status;
      throw err;
    }
    return res.json();
  }

  // Recarga la lista en la misma pagina y con los mismos filtros; la seleccion se repone en afterSwap.
  function refreshList() {
    const form = document.getElementById('ca-search');
    const marker = document.querySelector('#ca-results [data-ca-page]');
    if (!form) return;
    const params = new URLSearchParams(new FormData(form));
    params.set('page', marker ? marker.dataset.caPage : '1');
    htmx.ajax('GET', `${BASE}/buscar?${params}`, { target: '#ca-results', swap: 'innerHTML' });
  }

  function markSelected() {
    const box = document.querySelector('[data-ca-student]');
    document.querySelectorAll('#ca-results tr.is-selected').forEach((tr) => tr.classList.remove('is-selected'));
    if (!box) return;
    const pick = document.querySelector(`#ca-results [data-ca-pick][hx-get$="/alumnos/${box.dataset.userId}"]`);
    if (pick) pick.closest('tr').classList.add('is-selected');
  }

  function openStudent(userId) {
    return htmx.ajax('GET', `${BASE}/alumnos/${userId}`, { target: '#ca-detail', swap: 'innerHTML' });
  }

  // === FICHA DEL ALUMNO ===
  function initStudentPanel(root) {
    const maxMb = Number(root.dataset.maxMb) || 10;

    document.addEventListener('click', (ev) => {
      const pick = ev.target.closest('[data-ca-pick]');
      if (pick) {
        document.querySelectorAll('#ca-results tr.is-selected').forEach((tr) => tr.classList.remove('is-selected'));
        pick.closest('tr').classList.add('is-selected');
        return;
      }
      const up = ev.target.closest('[data-ca-upload]');
      if (up) {
        document.getElementById('ca-photo-input').click();
        return;
      }
      const del = ev.target.closest('[data-ca-delete]');
      if (del) deletePhoto(del);
    });

    document.addEventListener('change', async (ev) => {
      if (ev.target.id !== 'ca-photo-input') return;
      const input = ev.target;
      const file = input.files[0];
      const box = input.closest('[data-ca-student]');
      input.value = '';
      if (!file || !box) return;
      if (file.size > maxMb * 1024 * 1024) {
        showToast(`La foto pesa más de ${maxMb} MB. Reduce su tamaño y vuelve a intentar.`, 'danger');
        return;
      }
      const buttons = box.querySelectorAll('.ca-actions button');
      buttons.forEach((b) => { b.disabled = true; });
      try {
        const fd = new FormData();
        fd.append('file', file);
        const out = await postFile(`${BASE}/alumnos/${box.dataset.userId}/foto`, fd);
        showToast(out.data.status === 'replaced' ? 'Foto reemplazada' : 'Foto subida', 'success');
        await openStudent(box.dataset.userId);
        refreshList();
      } catch (err) {
        showToast(err.message, 'danger');
        buttons.forEach((b) => { b.disabled = false; });
      }
    });
  }

  async function deletePhoto(btn) {
    const box = btn.closest('[data-ca-student]');
    const ok = await window.AppModal.confirm({
      title: 'Eliminar foto',
      message: `Se borrará la foto oficial de ${box.dataset.name}. Su credencial dejará de mostrar el QR hasta que se suba otra.`,
      confirmText: 'Eliminar foto',
      confirmVariant: 'danger',
      cancelText: 'Conservar foto',
    });
    if (!ok) return;
    box.querySelectorAll('.ca-actions button').forEach((b) => { b.disabled = true; });
    try {
      const res = await fetch(`${BASE}/alumnos/${box.dataset.userId}/foto`, { method: 'DELETE', credentials: 'same-origin' });
      if (!res.ok) throw new Error(await fetchApiError(res, 'No se pudo eliminar la foto'));
      showToast('Foto eliminada', 'success');
      await openStudent(box.dataset.userId);
      refreshList();
    } catch (err) {
      showToast(err.message, 'danger');
      box.querySelectorAll('.ca-actions button').forEach((b) => { b.disabled = false; });
    }
  }

  // === CARGA POR LOTE ===
  function initBatch(root) {
    const input = document.getElementById('ca-batch-input');
    if (!input) return;
    const maxBytes = (Number(root.dataset.maxMb) || 10) * 1024 * 1024;
    const drop = document.getElementById('ca-drop');
    const queueEl = document.getElementById('ca-queue');
    const bar = document.getElementById('ca-batch-bar');
    const progress = document.getElementById('ca-batch-progress');
    const count = document.getElementById('ca-batch-count');
    const startBtn = document.getElementById('ca-batch-start');
    const clearBtn = document.getElementById('ca-batch-clear');
    let queue = []; // { file, li, done }
    let running = false;

    function paint(item, key, detail) {
      const [label, cls] = STATUS[key];
      item.li.innerHTML = `<span class="ca-queue__name">${escapeHtml(item.file.name)}</span>` +
        `<span class="ca-state ${cls}">${label}</span>` +
        `<span class="ca-queue__detail">${escapeHtml(detail || '')}</span>`;
    }

    function setProgress() {
      const done = queue.filter((q) => q.done).length;
      const pct = queue.length ? Math.round((done / queue.length) * 100) : 0;
      progress.style.width = `${pct}%`;
      bar.querySelector('.progress').setAttribute('aria-valuenow', String(pct));
      count.textContent = `${done} de ${queue.length} procesadas`;
    }

    function add(files) {
      for (const file of files) {
        const li = document.createElement('li');
        const item = { file, li, done: false };
        paint(item, 'pending');
        queueEl.appendChild(li);
        queue.push(item);
      }
      bar.hidden = queue.length === 0;
      startBtn.disabled = false;
      setProgress();
    }

    async function run() {
      running = true;
      [startBtn, clearBtn, input].forEach((el) => { el.disabled = true; });
      let failed = 0;
      for (const it of queue) {  // lo que el servidor rechazaria por tamano ni se envia
        if (!it.done && it.file.size > maxBytes) {
          paint(it, 'invalid', `Pesa más de ${root.dataset.maxMb} MB`);
          it.done = true;
          failed += 1;
        }
      }
      setProgress();
      const todo = queue.filter((q) => !q.done);
      const chunks = [];
      let cur = [];
      let curBytes = 0;
      for (const it of todo) {
        if (cur.length && (cur.length >= CHUNK || curBytes + it.file.size > CHUNK_BYTES)) {
          chunks.push(cur);
          cur = [];
          curBytes = 0;
        }
        cur.push(it);
        curBytes += it.file.size;
      }
      if (cur.length) chunks.push(cur);
      for (const chunk of chunks) {
        chunk.forEach((it) => paint(it, 'sending'));
        try {
          const fd = new FormData();
          chunk.forEach((it) => fd.append('files', it.file, it.file.name));
          const out = await postFile(`${BASE}/fotos/lote`, fd);
          chunk.forEach((it, idx) => {
            const row = out.data[idx] || { status: 'invalid', detail: 'Sin respuesta del servidor' };
            paint(it, row.status, row.detail);
            it.done = true;
            if (row.status === 'no_student' || row.status === 'invalid') failed += 1;
          });
        } catch (err) {
          chunk.forEach((it) => paint(it, 'invalid', err.message));
          failed += chunk.length;
          showToast(err.message, 'danger');
          if (err.status !== 413) break; // un 401/403/red caída se repetiría en cada tanda
        }
        setProgress();
      }
      running = false;
      [clearBtn, input].forEach((el) => { el.disabled = false; });
      startBtn.disabled = queue.every((q) => q.done);
      showToast(failed ? `Carga terminada con ${failed} archivo(s) sin guardar. Revisa la lista.` : 'Carga terminada', failed ? 'warning' : 'success');
      refreshList();
    }

    function clear() {
      queue = [];
      queueEl.innerHTML = '';
      bar.hidden = true;
      input.value = '';
    }

    input.addEventListener('change', () => { add(Array.from(input.files)); input.value = ''; });
    startBtn.addEventListener('click', () => { if (!running) run(); });
    clearBtn.addEventListener('click', clear);
    ['dragenter', 'dragover'].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.add('is-over'); }));
    ['dragleave', 'drop'].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.remove('is-over'); }));
    drop.addEventListener('drop', (e) => { if (!running) add(Array.from(e.dataTransfer.files)); });
  }

  // === ARRANQUE ===
  document.addEventListener('DOMContentLoaded', () => {
    const root = document.getElementById('ca-root');
    if (!root) return;
    initStudentPanel(root);
    initBatch(root);
    document.body.addEventListener('htmx:afterSwap', markSelected);
    document.body.addEventListener('htmx:responseError', (ev) => {
      let msg = 'No se pudo completar la consulta';
      if (ev.detail.xhr.status === 401) msg = 'Tu sesión venció. Recarga la página e inicia sesión.';
      else if (ev.detail.xhr.status === 403) msg = 'No tienes permiso para esta acción';
      else try { msg = extractErrorMessage(JSON.parse(ev.detail.xhr.responseText), msg); } catch (_) { /* texto plano */ }
      showToast(msg, 'danger');
    });
  });
})();
