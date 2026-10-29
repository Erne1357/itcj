// Prórrogas · Documentos (vista de secretaría).
// Lista por año las plantillas de los 6 formatos, permite verlas en PDF con datos
// de ejemplo, descargarlas y subir una nueva .docx. API: /api/prorrogas/v2/templates
(function () {
  "use strict";

  const root = document.querySelector(".docs");
  if (!root) return;
  const API = root.dataset.api;

  const $years = document.getElementById("docsYears");
  const $yearLabel = document.getElementById("docsYearLabel");
  const $grid = document.getElementById("docsGrid");
  const $dialog = document.getElementById("uploadDialog");
  const $form = document.getElementById("uploadForm");
  const $type = document.getElementById("uploadType");
  const $file = document.getElementById("uploadFile");
  const $markers = document.getElementById("uploadMarkers");
  const $error = document.getElementById("uploadError");
  const $submit = document.getElementById("uploadSubmit");
  const $toast = document.getElementById("secToast");

  const TINTS = ["rgba(103,153,224,.22)", "rgba(242,115,64,.22)", "rgba(101,47,42,.16)", "rgba(26,19,14,.08)"];
  const MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];

  let data = null;
  let year = null;
  let toastTimer = null;

  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  function fmtDate(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    return `${d.getDate()} ${MESES[d.getMonth()]} ${d.getFullYear()}`;
  }

  function toast(msg) {
    $toast.textContent = msg;
    $toast.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { $toast.hidden = true; }, 2600);
  }

  async function load() {
    const r = await fetch(API, { credentials: "include" });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    data = await r.json();
    if (year === null || !data.anios.some((a) => a.anio === year)) year = data.anios[0].anio;
    render();
  }

  function render() {
    $years.innerHTML = data.anios.map((a) => {
      const subidas = a.plantillas.filter((p) => p.origen === "subida").length;
      const active = a.anio === year;
      return `<button type="button" role="tab" aria-selected="${active}" class="docs-year${active ? " is-active" : ""}"
                data-year="${a.anio}">${a.anio}<small>${subidas}</small></button>`;
    }).join("");
    $yearLabel.textContent = year;

    const anio = data.anios.find((a) => a.anio === year);
    const cards = anio.plantillas.map((p, i) => {
      const t = p.plantilla;
      let badge;
      let meta;
      if (p.origen === "subida") {
        badge = `<span class="doc-badge doc-badge-subida">Subida · ${esc(fmtDate(t.uploaded_at))}</span>`;
        meta = esc(t.original_name);
      } else if (p.origen === "heredada") {
        badge = `<span class="doc-badge doc-badge-heredada">Heredada de ${t.anio}</span>`;
        meta = esc(t.original_name);
      } else {
        badge = `<span class="doc-badge doc-badge-sistema">Plantilla del sistema</span>`;
        meta = "DOCX";
      }
      const download = t ? `${API}/${t.id}/archivo` : `${API}/sistema/${p.doc_type}/archivo`;
      const preview = `${API}/vista-previa/${p.doc_type}.pdf?anio=${year}`;
      return `
        <article class="doc-card">
          <div class="doc-thumb" style="background:${TINTS[i % TINTS.length]}">
            <div class="doc-thumb-page"><i></i><i style="width:90%"></i><i style="width:80%"></i><i style="width:85%"></i></div>
          </div>
          <div class="doc-body">
            <div><div class="doc-name">${esc(p.label)}</div><div class="doc-meta">${meta}</div></div>
            <div>${badge}</div>
            <div class="doc-actions">
              <a class="doc-action" href="${preview}" target="_blank" rel="noopener">Vista previa</a>
              <a class="doc-action" href="${download}">Descargar</a>
              <button type="button" class="doc-action" data-upload="${p.doc_type}">Subir nueva</button>
            </div>
          </div>
        </article>`;
    }).join("");
    $grid.innerHTML = cards + `
      <button type="button" class="doc-add" data-upload="">
        <span class="doc-add-icon" aria-hidden="true">+</span>
        Subir plantilla para ${year}
        <small>Solo Word (.docx)</small>
      </button>`;
  }

  function renderMarkers() {
    const tipo = data.tipos.find((t) => t.code === $type.value);
    if (!tipo) { $markers.innerHTML = ""; return; }
    const req = new Set(tipo.obligatorios);
    $markers.innerHTML = tipo.permitidos.map((m) =>
      `<code class="${req.has(m) ? "is-required" : ""}" title="Copiar">{{${esc(m)}}}</code>`).join("");
  }

  function openUpload(docType) {
    $type.innerHTML = data.tipos.map((t) => `<option value="${t.code}">${esc(t.label)}</option>`).join("");
    if (docType) $type.value = docType;
    document.getElementById("uploadYear").textContent = year;
    $file.value = "";
    $error.hidden = true;
    renderMarkers();
    $dialog.showModal();
  }

  async function submitUpload(ev) {
    ev.preventDefault();
    if (!$file.files.length) return;
    const fd = new FormData();
    fd.append("doc_type", $type.value);
    fd.append("anio", String(year));
    fd.append("archivo", $file.files[0]);
    $submit.disabled = true;
    $error.hidden = true;
    try {
      const r = await fetch(API, { method: "POST", body: fd, credentials: "include" });
      const body = await r.json().catch(() => ({}));
      if (!r.ok) {
        const names = body.desconocidos || body.faltantes;
        // `mal_escritos` trae el texto tal cual (ya con sus llaves); los otros, solo el nombre.
        const items = body.mal_escritos || (names || []).map((m) => `{{${m}}}`);
        $error.innerHTML = esc(body.message || `No se pudo subir la plantilla (HTTP ${r.status}).`) +
          (items.length ? `<br>${items.map((m) => `<code>${esc(m)}</code>`).join(" ")}` : "");
        $error.hidden = false;
        return;
      }
      $dialog.close();
      toast("Plantilla subida. Ya es la que se usa para este año.");
      await load();
    } catch (e) {
      $error.textContent = "No se pudo subir la plantilla. Revisa tu conexión e inténtalo de nuevo.";
      $error.hidden = false;
    } finally {
      $submit.disabled = false;
    }
  }

  $years.addEventListener("click", (ev) => {
    const b = ev.target.closest("[data-year]");
    if (!b) return;
    year = Number(b.dataset.year);
    render();
  });
  $grid.addEventListener("click", (ev) => {
    const b = ev.target.closest("[data-upload]");
    if (b) openUpload(b.dataset.upload);
  });
  $type.addEventListener("change", renderMarkers);
  $markers.addEventListener("click", (ev) => {
    const c = ev.target.closest("code");
    if (c && navigator.clipboard) navigator.clipboard.writeText(c.textContent).then(() => toast(`Copiado ${c.textContent}`));
  });
  document.getElementById("uploadCancel").addEventListener("click", () => $dialog.close());
  $form.addEventListener("submit", submitUpload);

  load().catch(() => {
    $grid.innerHTML = '<div class="docs-error">No se pudieron cargar las plantillas. Recarga la página.</div>';
  });
})();
