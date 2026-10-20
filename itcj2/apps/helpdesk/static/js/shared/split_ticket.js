// itcj2/apps/helpdesk/static/js/shared/split_ticket.js
//
// Modal compartido "Partir ticket" (POST /tickets/{id}/split): la parte 1 es el
// ticket original, que se edita para acotarlo; las partes 2..N se crean como
// tickets nuevos del mismo solicitante. Las tarjetas se re-renderizan desde
// `splitParts`, así que antes de cada re-render se copia al arreglo lo escrito
// en el DOM (syncSplitPartsFromDom). Los valores del usuario entran a los
// inputs por propiedad (.value), nunca interpolados en innerHTML.
//
// Requiere que la página incluya el partial
// helpdesk/_components/split_ticket_modal.html y que helpdesk-utils.js ya esté
// cargado (siempre lo está: base_helpdesk.html lo incluye en TODAS las páginas
// de helpdesk).
//
// Se carga vía HD_PAGE_MODULES (pages/nav.py) solo en las páginas que lo usan;
// el controller HelpdeskPage (shared/base.js) dedup por src, así que este IIFE
// corre UNA sola vez por sesión: el estado es del módulo y lo reinicia
// `teardown()`, que llama el destroy() de cada página.
//
// API pública:
//   HelpdeskSplit.open(ticketId, { onSplit })
//       Abre el modal con datos frescos del servidor. `onSplit(data)` se llama
//       DESPUÉS de que el módulo mostró el toast y cerró el modal, y solo si la
//       página sigue viva; `data` es el `data` del endpoint ({original, tickets})
//       o null si el 2xx llegó con cuerpo ilegible (la división SÍ se aplicó:
//       la página debe refrescar igual). Su única tarea es refrescar lo que esa
//       página muestra — el módulo no sabe en qué página está.
//   HelpdeskSplit.teardown()
//       Libera modal, listeners y estado. Idempotente: se puede llamar aunque
//       el modal nunca se haya abierto.
(function () {
    'use strict';

    if (!window.HelpdeskUtils) {
        console.error('[HelpdeskSplit] HelpdeskUtils no está cargado — helpdesk-utils.js debe cargar antes.');
        return;
    }

    // ==================== CONSTANTES ====================
    const SPLIT_MAX_TOTAL_PARTS = 5;   // original + 4 nuevas (MAX_TOTAL_PARTS del servicio)
    const SPLIT_TITLE_MIN = 5;
    const SPLIT_TITLE_MAX = 200;
    const SPLIT_DESCRIPTION_MIN = 20;
    const SPLITTABLE_STATUSES = ['PENDING', 'ASSIGNED', 'IN_PROGRESS'];
    const SPLIT_AREA_OPTIONS = [['DESARROLLO', 'Desarrollo'], ['SOPORTE', 'Soporte']];
    const SPLIT_PRIORITY_OPTIONS = [['URGENTE', 'Urgente'], ['ALTA', 'Alta'], ['MEDIA', 'Media'], ['BAJA', 'Baja']];
    const SPLIT_STATUS_LABELS = {
        RESOLVED_SUCCESS: 'resuelto',
        RESOLVED_FAILED: 'no resuelto',
        CLOSED: 'cerrado',
        CANCELED: 'cancelado'
    };

    // ==================== ESTADO DEL MÓDULO ====================
    // splitParts[0] es el original.
    let ticketToSplit = null;
    let splitParts = [];
    let splitAttachmentsCount = 0;
    let categoriesCache = { DESARROLLO: [], SOPORTE: [] };
    let _splitSubmitting = false;
    let _onSplit = null;
    let _splitTicketModalInstance = null;
    let _wiredModalEl = null;
    // Contadores monótonos (nunca se reinician): _splitSeq cambia al abrir o
    // cerrar el modal y en teardown, e invalida la carga o el envío en vuelo de
    // la sesión anterior; _splitPageToken solo cambia en teardown (la página se
    // fue: no hay nada que refrescar).
    let _splitSeq = 0;
    let _splitPageToken = 0;

    // ==================== WIRING ====================
    // Referencias estables (funciones del módulo, no closures creados en cada
    // apertura): si el modal sobrevive a un morph con sus listeners puestos,
    // addEventListener descarta el duplicado y cada clic sigue disparando una
    // sola vez.
    function wireSplitModal(modalEl) {
        if (_wiredModalEl === modalEl) return;
        unwireSplitModal();
        document.getElementById('btnAddSplitPart').addEventListener('click', addSplitPart);
        document.getElementById('btnConfirmSplit').addEventListener('click', confirmSplitTicket);
        const list = document.getElementById('splitPartsList');
        list.addEventListener('click', onSplitPartsClick);
        list.addEventListener('change', onSplitPartsChange);
        list.addEventListener('input', onSplitPartsInput);
        modalEl.addEventListener('hidden.bs.modal', onSplitModalHidden);
        _wiredModalEl = modalEl;
    }

    function unwireSplitModal() {
        if (!_wiredModalEl) return;
        // Dentro del modal que se cableó, no por document: si un morph ya lo
        // reemplazó, hay que soltar el viejo (aunque esté desprendido), no el
        // nuevo — y las querys sobre un subárbol desprendido siguen funcionando.
        const addBtn = _wiredModalEl.querySelector('#btnAddSplitPart');
        if (addBtn) addBtn.removeEventListener('click', addSplitPart);
        const confirmBtn = _wiredModalEl.querySelector('#btnConfirmSplit');
        if (confirmBtn) confirmBtn.removeEventListener('click', confirmSplitTicket);
        const list = _wiredModalEl.querySelector('#splitPartsList');
        if (list) {
            list.removeEventListener('click', onSplitPartsClick);
            list.removeEventListener('change', onSplitPartsChange);
            list.removeEventListener('input', onSplitPartsInput);
        }
        _wiredModalEl.removeEventListener('hidden.bs.modal', onSplitModalHidden);
        _wiredModalEl = null;
    }

    // ==================== API PÚBLICA ====================
    async function open(ticketId, options) {
        const modalEl = document.getElementById('splitTicketModal');
        if (!modalEl) return;   // sin el permiso de partir la página no trae el modal
        if (_splitSubmitting) {
            HelpdeskUtils.showToast('Espera a que termine la división en curso', 'warning');
            return;
        }
        wireSplitModal(modalEl);

        const seq = ++_splitSeq;
        _onSplit = (options && typeof options.onSplit === 'function') ? options.onSplit : null;
        ticketToSplit = null;
        splitParts = [];
        splitAttachmentsCount = 0;
        renderSplitLoading();

        _splitTicketModalInstance = bootstrap.Modal.getOrCreateInstance(modalEl);
        _splitTicketModalInstance.show();

        let ticket = null;
        let attachmentsResp = null;
        try {
            // Datos frescos del servidor, no los arreglos de la página: el de
            // activos tiene tope de 100 y la tarjeta pudo quedar vieja.
            const [ticketResp, attResp] = await Promise.all([
                HelpdeskUtils.api.getTicket(ticketId),
                // Sin la lista de adjuntos solo se pierde el aviso de copias.
                HelpdeskUtils.api.request(`/attachments/ticket/${ticketId}`).catch(() => null),
                ensureSplitCategoriesLoaded()
            ]);
            ticket = ticketResp && ticketResp.ticket;
            attachmentsResp = attResp;
            if (!ticket) throw new Error('respuesta sin ticket');
        } catch (error) {
            if (seq !== _splitSeq) return;
            console.error('Error al cargar el ticket a partir:', error);
            renderSplitLoadError(`No se pudo cargar el ticket (${error.message || 'error desconocido'}).`);
            return;
        }
        if (seq !== _splitSeq) return;   // se cerró el modal o se fue la página

        if (!SPLITTABLE_STATUSES.includes(ticket.status)) {
            const label = SPLIT_STATUS_LABELS[ticket.status] || ticket.status;
            renderSplitLoadError(
                `El ticket ${ticket.ticket_number} ya no se puede partir: está ${label}. ` +
                'Solo se parten tickets pendientes, asignados o en proceso.'
            );
            return;
        }

        ticketToSplit = ticket;
        splitAttachmentsCount = ((attachmentsResp && attachmentsResp.attachments) || [])
            .filter(a => a.attachment_type === 'ticket').length;
        splitParts = [originalSplitPart(ticket), newSplitPartFromOriginal()];

        renderSplitOriginalInfo();
        renderSplitParts();
        setSplitFormEnabled(true);
    }

    function teardown() {
        if (_splitTicketModalInstance) {
            try { _splitTicketModalInstance.dispose(); } catch (e) { /* noop */ }
            _splitTicketModalInstance = null;
        }
        unwireSplitModal();

        // Invalida la carga/envío que siga en vuelo: al resolver ya no
        // encontrará su página (ni su modal) y no tocará el DOM de la nueva.
        _splitSeq++;
        _splitPageToken++;

        ticketToSplit = null;
        splitParts = [];
        splitAttachmentsCount = 0;
        categoriesCache = { DESARROLLO: [], SOPORTE: [] };
        _splitSubmitting = false;
        _onSplit = null;
    }

    // ==================== CATEGORÍAS ====================
    async function ensureSplitCategoriesLoaded() {
        if (categoriesCache.DESARROLLO.length || categoriesCache.SOPORTE.length) return;
        await loadSplitCategories();
    }

    // Se traga el error: sin categorías el modal abre igual (los selects salen
    // vacíos y la validación pide elegir una), en vez de no abrir.
    async function loadSplitCategories() {
        try {
            const [desarrollo, soporte] = await Promise.all([
                HelpdeskUtils.api.request('/categories?area=DESARROLLO&active=true'),
                HelpdeskUtils.api.request('/categories?area=SOPORTE&active=true')
            ]);
            categoriesCache.DESARROLLO = desarrollo.categories || [];
            categoriesCache.SOPORTE = soporte.categories || [];
        } catch (error) {
            console.error('Error cargando categorias:', error);
        }
    }

    // ==================== RENDER ====================
    function onSplitModalHidden() {
        // Cerrar invalida la carga en vuelo y vacía el modal: la siguiente
        // apertura arranca de cero y el snapshot de historial de htmx no guarda
        // un formulario a medias.
        _splitSeq++;
        ticketToSplit = null;
        splitParts = [];
        splitAttachmentsCount = 0;
        _onSplit = null;
        clearSplitModal();
    }

    function clearSplitModal() {
        ['splitOriginalInfo', 'splitPartsList', 'splitSummary'].forEach(id => {
            const el = document.getElementById(id);
            if (el) el.innerHTML = '';
        });
        const limit = document.getElementById('splitPartsLimit');
        if (limit) limit.textContent = '';
    }

    function renderSplitLoading() {
        clearSplitModal();
        document.getElementById('splitOriginalInfo').innerHTML = `
            <div class="d-flex align-items-center justify-content-center gap-2 py-3 text-muted small">
                <span class="spinner-border spinner-border-sm text-primary" aria-hidden="true"></span>
                Cargando ticket...
            </div>
        `;
        setSplitFormEnabled(false);
    }

    function renderSplitLoadError(message) {
        document.getElementById('splitOriginalInfo').innerHTML = `
            <div class="text-danger small" role="alert">
                <i class="fas fa-exclamation-circle me-1"></i>${escapeHtml(message)}
            </div>
        `;
        setSplitFormEnabled(false);
    }

    function setSplitFormEnabled(enabled) {
        // El fieldset deshabilita de una vez todos los campos, "Quitar" y
        // "Agregar parte"; al rehabilitarlo, los que ya tenían su propio
        // `disabled` (área bloqueada, tope de partes) lo conservan.
        const fieldset = document.getElementById('splitPartsFieldset');
        const confirmBtn = document.getElementById('btnConfirmSplit');
        if (fieldset) fieldset.disabled = !enabled;
        if (confirmBtn) confirmBtn.disabled = !enabled;
    }

    function originalSplitPart(ticket) {
        return {
            area: ticket.area || '',
            category_id: ticket.category ? String(ticket.category.id) : '',
            priority: ticket.priority || '',
            title: ticket.title || '',
            description: ticket.description || ''
        };
    }

    function newSplitPartFromOriginal() {
        // Toda parte nueva arranca con los valores del original. Necesita una
        // categoría ACTIVA: si la del original ya no lo está, queda sin elegir.
        const part = originalSplitPart(ticketToSplit);
        const active = (categoriesCache[part.area] || []).some(c => String(c.id) === part.category_id);
        if (!active) part.category_id = '';
        return part;
    }

    function renderSplitOriginalInfo() {
        const t = ticketToSplit;
        let assignee = '<span class="fst-italic">Sin asignar</span>';
        if (t.assigned_to) {
            assignee = escapeHtml(t.assigned_to.name);
        } else if (t.assigned_to_team) {
            assignee = `Equipo ${escapeHtml(t.assigned_to_team)}`;
        }

        const n = splitAttachmentsCount;
        const attachments = n === 0
            ? 'Sin adjuntos iniciales'
            : `${n} adjunto${n === 1 ? '' : 's'} inicial${n === 1 ? '' : 'es'}`;

        document.getElementById('splitOriginalInfo').innerHTML = `
            <div class="d-flex flex-wrap align-items-center gap-2 mb-2">
                <span class="fw-bold text-primary">${escapeHtml(t.ticket_number)}</span>
                ${HelpdeskUtils.getStatusBadge(t.status)}
                ${HelpdeskUtils.getAreaBadge(t.area)}
                ${t.category ? `<span class="badge bg-secondary">${escapeHtml(t.category.name)}</span>` : ''}
                ${HelpdeskUtils.getPriorityBadge(escapeHtml(t.priority))}
            </div>
            <div class="fw-semibold mb-1">${escapeHtml(t.title)}</div>
            <div class="hd-split-original__desc small">${escapeHtml(t.description)}</div>
            <div class="d-flex flex-wrap column-gap-3 row-gap-1 small text-muted mt-2">
                <span><i class="fas fa-user-circle me-1"></i>Solicitante: ${escapeHtml(t.requester?.name || 'N/A')}</span>
                <span><i class="fas fa-user-check me-1"></i>Asignado a: ${assignee}</span>
                <span><i class="fas fa-paperclip me-1"></i>${attachments}</span>
            </div>
        `;
    }

    function renderSplitParts() {
        const list = document.getElementById('splitPartsList');
        list.innerHTML = splitParts.map((_, index) => splitPartCardHtml(index)).join('');
        splitParts.forEach((part, index) => fillSplitPartCard(index, part));

        const atMax = splitParts.length >= SPLIT_MAX_TOTAL_PARTS;
        document.getElementById('btnAddSplitPart').disabled = atMax;
        document.getElementById('splitPartsLimit').textContent = atMax
            ? `Llegaste al máximo de ${SPLIT_MAX_TOTAL_PARTS} partes.`
            : `${splitParts.length} de ${SPLIT_MAX_TOTAL_PARTS} partes como máximo.`;
        updateSplitSummary();
    }

    /** Esqueleto de una tarjeta de parte: solo texto fijo, números y el folio
     *  escapado. Los valores se ponen después por propiedad (fillSplitPartCard). */
    function splitPartCardHtml(index) {
        const isOriginal = index === 0;
        const n = index + 1;
        const id = `splitPart${index}`;
        const areaLocked = isOriginal && ticketToSplit.status !== 'PENDING';
        const header = isOriginal
            ? `Parte 1 · ${escapeHtml(ticketToSplit.ticket_number)} (original)`
            : `Parte ${n} · ticket nuevo`;
        // Con una sola parte nueva no queda nada que partir: no se puede quitar.
        const removeBtn = isOriginal ? '' : `
            <button type="button" class="btn btn-outline-danger btn-sm flex-shrink-0" data-split-remove="${index}"
                    title="Quitar parte ${n}" aria-label="Quitar parte ${n}"${splitParts.length <= 2 ? ' disabled' : ''}>
                <i class="fas fa-times"></i><span class="d-none d-sm-inline ms-1">Quitar</span>
            </button>`;
        // El técnico asignado es de esa área: fuera de PENDING el servidor la rechaza.
        const lockHint = areaLocked ? `
            <div class="form-text" id="${id}AreaHelp">
                El ticket ya está ${ticketToSplit.status === 'IN_PROGRESS' ? 'en proceso' : 'asignado'}: su área no puede cambiar.
            </div>` : '';
        const optionsHtml = options => options
            .map(([value, label]) => `<option value="${value}">${label}</option>`)
            .join('');

        return `
            <div class="card hd-split-part${isOriginal ? ' hd-split-part--original' : ''}" data-split-index="${index}">
                <div class="card-header d-flex align-items-center justify-content-between gap-2 py-2">
                    <span class="fw-semibold small">${header}</span>
                    ${removeBtn}
                </div>
                <div class="card-body">
                    <div class="row g-2">
                        <div class="col-12 col-md-3">
                            <label class="form-label small fw-semibold mb-1" for="${id}Area">Área</label>
                            <select class="form-select" id="${id}Area" data-split-field="area"${areaLocked ? ` disabled aria-describedby="${id}AreaHelp"` : ''}>
                                ${optionsHtml(SPLIT_AREA_OPTIONS)}
                            </select>
                            ${lockHint}
                        </div>
                        <div class="col-12 col-md-6">
                            <label class="form-label small fw-semibold mb-1" for="${id}Category">Categoría</label>
                            <select class="form-select" id="${id}Category" data-split-field="category_id"></select>
                        </div>
                        <div class="col-12 col-md-3">
                            <label class="form-label small fw-semibold mb-1" for="${id}Priority">Prioridad</label>
                            <select class="form-select" id="${id}Priority" data-split-field="priority">
                                ${optionsHtml(SPLIT_PRIORITY_OPTIONS)}
                            </select>
                        </div>
                        <div class="col-12">
                            <label class="form-label small fw-semibold mb-1" for="${id}Title">Título</label>
                            <input type="text" class="form-control" id="${id}Title" data-split-field="title"
                                   maxlength="${SPLIT_TITLE_MAX}" placeholder="Mínimo ${SPLIT_TITLE_MIN} caracteres"
                                   aria-describedby="${id}TitleHelp">
                            <div class="form-text" id="${id}TitleHelp">
                                <span data-split-count="title">0</span>/${SPLIT_TITLE_MAX} caracteres
                            </div>
                        </div>
                        <div class="col-12">
                            <label class="form-label small fw-semibold mb-1" for="${id}Description">Descripción</label>
                            <textarea class="form-control" id="${id}Description" data-split-field="description" rows="3"
                                      placeholder="Mínimo ${SPLIT_DESCRIPTION_MIN} caracteres"
                                      aria-describedby="${id}DescriptionHelp"></textarea>
                            <div class="form-text" id="${id}DescriptionHelp">
                                <span data-split-count="description">0</span> caracteres (mínimo ${SPLIT_DESCRIPTION_MIN})
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        `;
    }

    function getSplitCard(index) {
        return document.querySelector(`#splitPartsList .hd-split-part[data-split-index="${index}"]`);
    }

    function fillSplitPartCard(index, part) {
        const card = getSplitCard(index);
        if (!card) return;
        setSplitSelectValue(card.querySelector('[data-split-field="area"]'), part.area);
        fillSplitCategorySelect(card, part.area, part.category_id);
        setSplitSelectValue(card.querySelector('[data-split-field="priority"]'), part.priority);
        card.querySelector('[data-split-field="title"]').value = part.title;
        card.querySelector('[data-split-field="description"]').value = part.description;
        updateSplitCounters(card);
    }

    // Un valor fuera de las opciones fijas (un área o prioridad nueva del
    // catálogo) se agrega, en vez de dejar que el select caiga en silencio a la
    // primera opción y el envío cambie el ticket sin que nadie lo pidiera.
    function setSplitSelectValue(select, value) {
        if (value && !Array.from(select.options).some(o => o.value === value)) {
            select.add(new Option(value, value));
        }
        select.value = value;
    }

    function fillSplitCategorySelect(card, area, selectedId) {
        const select = card.querySelector('[data-split-field="category_id"]');
        const categories = (categoriesCache[area] || []).map(c => ({ id: String(c.id), name: c.name }));

        // El original puede tener una categoría ya inactiva: su tarjeta la ofrece
        // (conservarla no la vuelve a validar el servidor); las partes nuevas no.
        const originalCategory = ticketToSplit && ticketToSplit.category;
        if (card.dataset.splitIndex === '0' && originalCategory && originalCategory.area === area &&
                !categories.some(c => c.id === String(originalCategory.id))) {
            categories.push({ id: String(originalCategory.id), name: `${originalCategory.name} (inactiva)` });
        }

        if (!categories.length) {
            select.innerHTML = '<option value="">No hay categorías disponibles</option>';
            return;
        }
        select.innerHTML = '<option value="">Selecciona una categoría</option>' + categories
            .map(c => `<option value="${escapeHtml(c.id)}">${escapeHtml(c.name)}</option>`)
            .join('');
        select.value = categories.some(c => c.id === selectedId) ? selectedId : '';
    }

    function updateSplitCounters(card) {
        if (!card) return;
        // El título cuenta tal cual (lo topa maxlength); la descripción sin los
        // espacios de los extremos, que es como la mide el servidor.
        const title = card.querySelector('[data-split-field="title"]');
        const description = card.querySelector('[data-split-field="description"]');
        card.querySelector('[data-split-count="title"]').textContent = title.value.length;
        card.querySelector('[data-split-count="description"]').textContent = description.value.trim().length;
    }

    // ==================== EVENTOS DEL FORMULARIO ====================
    function onSplitPartsClick(e) {
        const btn = e.target.closest('[data-split-remove]');
        if (btn) removeSplitPart(Number(btn.dataset.splitRemove));
    }

    function onSplitPartsChange(e) {
        const field = e.target.dataset.splitField;
        if (!field) return;
        clearSplitInvalid(e.target);
        if (field === 'area') {
            // Otra área = otras categorías: se obliga a elegir una de verdad.
            fillSplitCategorySelect(e.target.closest('.hd-split-part'), e.target.value, '');
        }
    }

    function onSplitPartsInput(e) {
        const field = e.target.dataset.splitField;
        if (field !== 'title' && field !== 'description') return;
        clearSplitInvalid(e.target);
        updateSplitCounters(e.target.closest('.hd-split-part'));
    }

    function syncSplitPartsFromDom() {
        splitParts = splitParts.map((part, index) => {
            const card = getSplitCard(index);
            if (!card) return part;
            const value = field => card.querySelector(`[data-split-field="${field}"]`).value;
            return {
                area: value('area'),
                category_id: value('category_id'),
                priority: value('priority'),
                title: value('title'),
                description: value('description')
            };
        });
    }

    function addSplitPart() {
        if (!ticketToSplit || splitParts.length >= SPLIT_MAX_TOTAL_PARTS) return;
        syncSplitPartsFromDom();
        splitParts.push(newSplitPartFromOriginal());
        renderSplitParts();

        const card = getSplitCard(splitParts.length - 1);
        if (card) {
            card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
            card.querySelector('[data-split-field="title"]').focus({ preventScroll: true });
        }
    }

    function removeSplitPart(index) {
        // La parte 1 es el original y siempre queda al menos una parte nueva.
        if (index < 1 || index >= splitParts.length || splitParts.length <= 2) return;
        syncSplitPartsFromDom();
        splitParts.splice(index, 1);
        renderSplitParts();
        // El botón pulsado ya no existe: el foco pasa a "Agregar parte".
        document.getElementById('btnAddSplitPart').focus();
    }

    function updateSplitSummary() {
        const summary = document.getElementById('splitSummary');
        if (!ticketToSplit) {
            summary.innerHTML = '';
            return;
        }
        const newCount = splitParts.length - 1;
        const requester = `<strong>${escapeHtml(ticketToSplit.requester?.name || 'el solicitante')}</strong>`;
        let text = newCount === 1
            ? `Se creará <strong>1</strong> ticket nuevo a nombre de ${requester}`
            : `Se crearán <strong>${newCount}</strong> tickets nuevos a nombre de ${requester}`;

        const k = splitAttachmentsCount;
        if (k > 0) {
            const verb = k === 1 ? 'copiará' : 'copiarán';
            const what = k === 1 ? '1 adjunto' : `${k} adjuntos`;
            text += newCount === 1 ? ` · se le ${verb} ${what}` : ` · se ${verb} ${what} a cada uno`;
        }
        summary.innerHTML = `<i class="fas fa-info-circle text-primary me-1"></i>${text}`;
    }

    // ==================== VALIDACIÓN ====================
    /**
     * Espejo de las reglas del servidor (ticket_split_service), para no gastar
     * un viaje en lo evidente: en las partes nuevas se valida todo; en el
     * original, título y descripción solo si cambiaron (un ticket viejo con
     * descripción corta no debe bloquear la división). El área bloqueada y la
     * categoría del área los garantizan los propios selects.
     */
    function validateSplitParts() {
        for (let index = 0; index < splitParts.length; index++) {
            const part = splitParts[index];
            const isOriginal = index === 0;
            const label = isOriginal ? 'Ticket original' : `Parte ${index + 1}`;
            const title = part.title.trim();
            const description = part.description.trim();

            if (!part.category_id) {
                return { index, field: 'category_id', message: `${label}: Selecciona una categoría` };
            }
            if (title.length > SPLIT_TITLE_MAX) {
                return { index, field: 'title', message: `${label}: El título no debe exceder ${SPLIT_TITLE_MAX} caracteres` };
            }
            if ((!isOriginal || !sameSplitText(title, ticketToSplit.title)) && title.length < SPLIT_TITLE_MIN) {
                return { index, field: 'title', message: `${label}: El título debe tener al menos ${SPLIT_TITLE_MIN} caracteres` };
            }
            if ((!isOriginal || !sameSplitText(description, ticketToSplit.description)) &&
                    description.length < SPLIT_DESCRIPTION_MIN) {
                return {
                    index,
                    field: 'description',
                    message: `${label}: La descripción debe tener al menos ${SPLIT_DESCRIPTION_MIN} caracteres`
                };
            }
        }
        return null;
    }

    // El <textarea> normaliza los saltos de línea a "\n" al leer .value, pero hay
    // descripciones guardadas con "\r\n": sin normalizar, un original intacto
    // viajaría "cambiado" y el servidor le dejaría una edición fantasma.
    function sameSplitText(value, stored) {
        const normalize = s => String(s || '').replace(/\r\n?/g, '\n').trim();
        return normalize(value) === normalize(stored);
    }

    function markSplitInvalid(problem) {
        const card = getSplitCard(problem.index);
        const field = card && card.querySelector(`[data-split-field="${problem.field}"]`);
        if (field) {
            field.classList.add('is-invalid');
            field.setAttribute('aria-invalid', 'true');
            field.focus();
        }
        HelpdeskUtils.showToast(problem.message, 'warning');
    }

    function clearSplitInvalid(field) {
        field.classList.remove('is-invalid');
        field.removeAttribute('aria-invalid');
    }

    // ==================== ENVÍO ====================
    async function confirmSplitTicket() {
        if (!ticketToSplit || _splitSubmitting) return;
        syncSplitPartsFromDom();
        const problem = validateSplitParts();
        if (problem) {
            markSplitInvalid(problem);
            return;
        }

        const toPayload = part => ({
            area: part.area,
            category_id: parseInt(part.category_id, 10),
            priority: part.priority,
            title: part.title.trim(),
            description: part.description.trim()
        });
        // Lo que el usuario no tocó del original viaja tal como está guardado
        // (ver sameSplitText): el servidor solo registra lo que cambió.
        const original = toPayload(splitParts[0]);
        if (sameSplitText(original.title, ticketToSplit.title)) original.title = ticketToSplit.title;
        if (sameSplitText(original.description, ticketToSplit.description)) {
            original.description = ticketToSplit.description;
        }
        const ticketId = ticketToSplit.id;
        const payload = {
            original,
            parts: splitParts.slice(1).map(toPayload)
        };

        const seq = _splitSeq;
        const pageToken = _splitPageToken;
        const onSplit = _onSplit;   // capturado: cerrar el modal lo limpia
        const btn = document.getElementById('btnConfirmSplit');
        const btnHtml = btn.innerHTML;
        _splitSubmitting = true;
        setSplitFormEnabled(false);
        btn.innerHTML = '<i class="fas fa-spinner fa-spin me-2"></i>Partiendo...';

        // `applied`: el servidor respondió 2xx, así que la división YA ocurrió —
        // aunque el cuerpo venga ilegible. Se separa de `result` porque el
        // servidor no es idempotente: reintentar partiría el ticket otra vez
        // (N-1 tickets más, otra tanda de copias físicas de adjuntos y de avisos).
        let applied = false;
        let result = null;
        try {
            // fetch directo y no HelpdeskUtils.api.request: ese cliente lee
            // `data.message` y descarta el `{"error": ...}` del servidor, así que
            // un 400 con "Parte 3: ..." le llegaría al usuario como "HTTP 400".
            const response = await fetch(`/api/help-desk/v2/tickets/${ticketId}/split`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            if (response.ok) {
                applied = true;
                // El parseo va en su PROPIO try: si un 2xx trae cuerpo ilegible
                // (proxy que corta, HTML de error interpuesto) y la excepción
                // cayera en el catch de red, el usuario vería "Error de conexión",
                // el formulario se rehabilitaría y el siguiente clic partiría el
                // ticket por segunda vez.
                try {
                    result = await response.json();
                } catch (parseError) {
                    console.error('Respuesta 2xx ilegible al partir ticket:', parseError);
                }
            } else {
                const message = await fetchApiError(response, 'No se pudo partir el ticket');
                HelpdeskUtils.showToast(escapeHtml(message), 'error');
            }
        } catch (error) {
            console.error('Error al partir ticket:', error);
            HelpdeskUtils.showToast('Error de conexión al partir el ticket', 'error');
        } finally {
            _splitSubmitting = false;
            btn.innerHTML = btnHtml;
        }

        // Mismo modal abierto con el mismo ticket (no se cerró ni se fue la página).
        const sameSession = seq === _splitSeq;
        if (!applied) {
            if (sameSession) setSplitFormEnabled(true);   // corregir y reintentar
            return;
        }

        // Aplicado: el formulario queda deshabilitado hasta que el modal termine
        // de cerrarse, para que un segundo clic no vuelva a partir.
        if (result) {
            const folios = ((result.data && result.data.tickets) || []).map(t => t.ticket_number).join(', ');
            const message = `${result.message || 'Ticket partido'}${folios ? `. Nuevos: ${folios}` : ''}`;
            HelpdeskUtils.showToast(escapeHtml(message), 'success');
        } else {
            HelpdeskUtils.showToast(
                'El servidor respondió con un formato inesperado: la división pudo haberse aplicado. Recargando las listas para confirmar.',
                'warning'
            );
        }

        if (pageToken !== _splitPageToken) return;   // se navegó a otra página
        if (sameSession && _splitTicketModalInstance) _splitTicketModalInstance.hide();

        // La página refresca lo suyo. Va con `data` del endpoint, o null si el
        // 2xx no se pudo leer: la división se aplicó igual y hay que refrescar.
        if (!onSplit) return;
        try {
            await onSplit((result && result.data) || null);
        } catch (callbackError) {
            console.error('[HelpdeskSplit] el callback onSplit falló:', callbackError);
        }
    }

    // ==================== ERROR HELPERS ====================
    // La API responde {"error": "<texto>", "status": N} (HTTPException) o, en un
    // 422, {"error": "validation_error", "detail": [{msg, ...}]}.
    function extractErrorMessage(data, fallback = 'Error desconocido') {
        if (typeof data === 'string') return data || fallback;
        if (!data || typeof data !== 'object') return fallback;
        if (Array.isArray(data.detail)) {
            return data.detail
                .map(e => (e && typeof e === 'object' && e.msg) ? e.msg : String(e))
                .join('; ') || fallback;
        }
        const val = data.error || data.message || data.detail;
        if (typeof val === 'string') return (val && val !== 'internal_error') ? val : fallback;
        if (val && typeof val === 'object') return extractErrorMessage(val, fallback);
        return fallback;
    }

    async function fetchApiError(response, fallback) {
        try {
            const data = await response.json();
            return extractErrorMessage(data, fallback);
        } catch (_) {
            return `${fallback} (HTTP ${response.status})`;
        }
    }

    // ==================== HELPERS ====================
    function escapeHtml(str) {
        if (str === null || str === undefined) return '';
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    window.HelpdeskSplit = { open, teardown };
}());
