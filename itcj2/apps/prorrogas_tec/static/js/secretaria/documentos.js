// Prórrogas · Documentos (vista de secretaría).
// Lista por año las plantillas de los 6 formatos. Clic en una tarjeta abre el modal con
// el PDF de ejemplo, Reemplazar y Descargar; la tarjeta solo trae Descargar.
// API: /api/prorrogas/v2/templates
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
  const $doc = document.getElementById("docDialog");
  const $pdf = document.getElementById("docPdf");
  const $pdfMsg = document.getElementById("docPdfMsg");
  const $skel = document.getElementById("docSkel");

  const TINTS = ["rgba(103,153,224,.22)", "rgba(242,115,64,.22)", "rgba(101,47,42,.16)", "rgba(26,19,14,.08)"];
  const MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];
  const DL_ICON = '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M12 4v11M7 10l5 5 5-5M5 20h14"/></svg>';
  const PLUS_ICON = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg>';

  let data = null;
  let year = null;
  let toastTimer = null;
  let abierto = null;  // formato abierto en el modal
  let pdfUrl = null;   // blob de la vista previa; se libera al cerrar
  let pdfSeq = 0;      // descarta la respuesta de una vista previa anterior
  const pdfs = new Map();  // "año:formato" → promesa del PDF; se calienta al abrir la página

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
    warm();
  }

  function getPdf(tipo, y) {
    const k = `${y}:${tipo}`;
    if (!pdfs.has(k)) {
      const p = fetch(`${API}/vista-previa/${tipo}.pdf?anio=${y}`, { credentials: "include" })
        .then((r) => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.blob(); });
      p.catch(() => pdfs.delete(k));  // un error no se queda guardado
      pdfs.set(k, p);
    }
    return pdfs.get(k);
  }

  // Pide los PDF del año uno a uno (cada uno puede ser un LibreOffice) para que el clic los encuentre listos.
  async function warm() {
    const y = year;
    for (const p of plantillas()) {
      if (y !== year) return;
      await getPdf(p.doc_type, y).catch(() => {});
    }
  }

  function render() {
    $years.innerHTML = data.anios.map((a) => {
      const subidas = a.plantillas.filter((p) => p.origen === "subida").length;
      const active = a.anio === year;
      return `<button type="button" role="tab" aria-selected="${active}" class="docs-year${active ? " is-active" : ""}"
                data-year="${a.anio}">${a.anio}<small>${subidas}</small></button>`;
    }).join("");
    $yearLabel.textContent = year;
    const $vac = document.getElementById("docsVacantes");
    $vac.textContent = data.vacantes.length
      ? `Core no tiene titular activo de: ${data.vacantes.join(", ")}. Asígnalo en Puestos; mientras, las cartas salen sin ese nombre.`
      : "";
    $vac.hidden = !data.vacantes.length;

    const cards = plantillas().map((p, i) => `
        <article class="doc-card">
          <div class="doc-thumb" style="background:${TINTS[i % TINTS.length]}">
            <div class="doc-thumb-page"><i></i><i style="width:90%"></i><i style="width:80%"></i><i style="width:85%"></i></div>
          </div>
          <div class="doc-body">
            <div class="doc-text">
              <button type="button" class="doc-open" data-open="${p.doc_type}" title="Ver documento">${esc(p.label)}</button>
              <div class="doc-meta">DOCX · ${esc(enUso(p).origen)}</div>
            </div>
            <a class="doc-dl" href="${descarga(p)}">${DL_ICON}Descargar</a>
          </div>
        </article>`).join("");
    $grid.innerHTML = cards + `
      <button type="button" class="doc-add" data-upload="">
        <span class="doc-add-icon">${PLUS_ICON}</span>
        Subir plantilla para ${year}
        <small>Solo Word (.docx)</small>
      </button>`;
  }

  const plantillas = () => data.anios.find((a) => a.anio === year).plantillas;
  const descarga = (p) => (p.plantilla ? `${API}/${p.plantilla.id}/archivo` : `${API}/sistema/${p.doc_type}/archivo`);

  // De dónde sale el archivo que se usa este año (tarjeta y modal).
  function enUso(p) {
    const t = p.plantilla;
    if (p.origen === "subida") return { origen: fmtDate(t.uploaded_at), detalle: `Subida el ${fmtDate(t.uploaded_at)}`, archivo: t.original_name };
    if (p.origen === "heredada") return { origen: `Heredada de ${t.anio}`, detalle: `Heredada de ${t.anio}`, archivo: t.original_name };
    return { origen: "Del sistema", detalle: "Plantilla del sistema", archivo: `${p.doc_type}.docx` };
  }

  // ── Modal de un documento ─────────────────────────────────────────────
  function openDoc(tipo) {
    const p = plantillas().find((x) => x.doc_type === tipo);
    if (!p) return;
    abierto = tipo;
    const u = enUso(p);
    document.getElementById("docAnio").textContent = year;
    document.getElementById("docNombre").textContent = p.label;
    document.getElementById("docArchivo").textContent = u.archivo;
    document.getElementById("docOrigen").textContent = u.detalle;
    document.getElementById("docDescargar").href = descarga(p);
    if (!$doc.open) $doc.showModal();
    loadPreview(tipo);
  }

  function clearPreview() {
    $pdf.hidden = true;
    $skel.hidden = true;
    $pdf.removeAttribute("src");
    if (pdfUrl) URL.revokeObjectURL(pdfUrl);
    pdfUrl = null;
  }

  // Blob (no src directo) para mostrar el esqueleto y el 503 de LibreOffice en vez de un JSON en el iframe.
  async function loadPreview(tipo) {
    const seq = ++pdfSeq;
    clearPreview();
    $pdfMsg.hidden = true;
    const espera = setTimeout(() => { if (seq === pdfSeq) $skel.hidden = false; }, 300);  // solo si tarda
    try {
      const blob = await getPdf(tipo, year);
      if (seq !== pdfSeq) return;
      pdfUrl = URL.createObjectURL(blob);
      $pdf.src = `${pdfUrl}#navpanes=0&view=Fit`;  // sin miniaturas, la hoja completa
      $pdf.hidden = false;
    } catch (e) {
      if (seq !== pdfSeq) return;
      $pdfMsg.textContent = "No se pudo generar la vista previa. Descarga el archivo para revisarlo.";
      $pdfMsg.hidden = false;
    } finally {
      clearTimeout(espera);
      if (seq === pdfSeq) $skel.hidden = true;
    }
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
    $type.disabled = Boolean(docType);  // al reemplazar desde el modal, el formato ya está decidido
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
      pdfs.clear();  // la plantilla nueva cambia su PDF (y el de los años que la heredan)
      toast("Plantilla subida. Ya es la que se usa para este año.");
      await load();
      if ($doc.open) openDoc(abierto);  // reemplazo desde el modal: mostrar ya el archivo nuevo
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
    warm();
  });
  $grid.addEventListener("click", (ev) => {
    const b = ev.target.closest("[data-upload]");
    if (b) openUpload(b.dataset.upload);
    const o = ev.target.closest("[data-open]");
    if (o) openDoc(o.dataset.open);
  });
  $doc.addEventListener("close", () => { pdfSeq++; clearPreview(); abierto = null; });
  $doc.addEventListener("click", (ev) => { if (ev.target === $doc) $doc.close(); });  // clic en el fondo
  document.getElementById("docClose").addEventListener("click", () => $doc.close());
  document.getElementById("docReemplazar").addEventListener("click", () => openUpload(abierto));
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
