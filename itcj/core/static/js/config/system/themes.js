/**
 * themes.js - Manager para gestion de tematicas del sistema
 */
class ThemesManager {
    constructor() {
        this.apiBase = '/api/core/v1/themes';
        this.themes = [];
        this.editingThemeId = null;
        this.deleteThemeId = null;
        this.decorationCounter = 0;

        // Plantillas de decoraciones predefinidas para sugerir
        this.decorationPresets = {
            snowflakes: { label: 'Copos de nieve', icon: 'bi-snow' },
            lights: { label: 'Luces decorativas', icon: 'bi-lightbulb' },
            snowman: { label: 'Muneco de nieve', icon: 'bi-emoji-smile' },
            hearts: { label: 'Corazones flotantes', icon: 'bi-heart-fill' },
            garland: { label: 'Guirnalda', icon: 'bi-flower1' },
            cupid: { label: 'Cupido', icon: 'bi-balloon-heart-fill' },
            confetti: { label: 'Confetti', icon: 'bi-stars' },
            pumpkins: { label: 'Calabazas', icon: 'bi-emoji-laughing' },
            bats: { label: 'Murcielagos', icon: 'bi-bug' },
            skulls: { label: 'Calaveras', icon: 'bi-flower3' },
            fireworks: { label: 'Fuegos artificiales', icon: 'bi-brightness-high' },
            stars: { label: 'Estrellas', icon: 'bi-star-fill' },
        };

        this.init();
    }

    async init() {
        this.cacheElements();
        this.bindEvents();
        this.initModals();
        await this.loadThemes();
        await this.loadActiveTheme();
    }

    cacheElements() {
        this.themesContainer = document.getElementById('themesContainer');
        this.activeThemeContent = document.getElementById('activeThemeContent');
        this.activeThemeStatus = document.getElementById('activeThemeStatus');
        this.themeForm = document.getElementById('themeForm');
        this.themeModalTitle = document.getElementById('themeModalTitle');
        this.decorationsList = document.getElementById('decorationsList');
    }

    bindEvents() {
        // Form submit
        this.themeForm.addEventListener('submit', (e) => this.handleSaveTheme(e));

        // Delete confirmation
        document.getElementById('confirmDeleteTheme').addEventListener('click', () => this.handleDeleteTheme());

        // Color picker sync
        this.setupColorSync('colorPrimary', 'colorPrimaryHex');
        this.setupColorSync('colorSecondary', 'colorSecondaryHex');
        this.setupColorSync('colorAccent', 'colorAccentHex');
    }

    setupColorSync(colorId, hexId) {
        const colorInput = document.getElementById(colorId);
        const hexInput = document.getElementById(hexId);

        colorInput.addEventListener('input', () => {
            hexInput.value = colorInput.value.toUpperCase();
        });

        hexInput.addEventListener('input', () => {
            const value = hexInput.value;
            if (/^#[0-9A-Fa-f]{6}$/.test(value)) {
                colorInput.value = value;
            }
        });
    }

    initModals() {
        this.themeModal = new bootstrap.Modal(document.getElementById('themeModal'));
        this.deleteModal = new bootstrap.Modal(document.getElementById('deleteThemeModal'));

        // Reset form when modal closes
        document.getElementById('themeModal').addEventListener('hidden.bs.modal', () => {
            this.resetForm();
        });
    }

    // ==================== API Calls ====================

    async loadThemes() {
        try {
            const response = await fetch(this.apiBase);
            const result = await response.json();

            if (response.ok && result.data) {
                this.themes = result.data;
                this.renderThemes();
            } else {
                throw new Error(result.error || 'Error loading themes');
            }
        } catch (error) {
            console.error('Error loading themes:', error);
            showError('Error al cargar las tematicas');
            this.renderEmptyState();
        }
    }

    async loadActiveTheme() {
        try {
            const response = await fetch(`${this.apiBase}/active`);
            const result = await response.json();

            if (response.ok) {
                this.renderActiveTheme(result.data);
            }
        } catch (error) {
            console.error('Error loading active theme:', error);
            this.renderActiveTheme(null);
        }
    }

    async toggleTheme(themeId, active) {
        try {
            const response = await fetch(`${this.apiBase}/${themeId}/toggle`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ active })
            });

            if (response.ok) {
                showSuccess(active ? 'Tematica activada manualmente' : 'Activacion manual desactivada');
                await this.loadThemes();
                await this.loadActiveTheme();
            } else {
                const result = await response.json();
                throw new Error(result.error || 'Error');
            }
        } catch (error) {
            console.error('Error toggling theme:', error);
            showError('Error al cambiar estado de la tematica');
            // Reload to restore correct state
            await this.loadThemes();
        }
    }

    async handleSaveTheme(e) {
        e.preventDefault();

        const data = this.collectFormData();

        if (!data.name) {
            showError('El nombre es requerido');
            return;
        }

        const url = this.editingThemeId ? `${this.apiBase}/${this.editingThemeId}` : this.apiBase;
        const method = this.editingThemeId ? 'PATCH' : 'POST';

        try {
            document.getElementById('saveThemeBtn').disabled = true;

            const response = await fetch(url, {
                method,
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data)
            });

            const result = await response.json();

            if (response.ok) {
                showSuccess(this.editingThemeId ? 'Tematica actualizada correctamente' : 'Tematica creada correctamente');
                this.themeModal.hide();
                await this.loadThemes();
                await this.loadActiveTheme();
            } else {
                throw new Error(result.error || 'Error al guardar');
            }
        } catch (error) {
            console.error('Error saving theme:', error);
            showError(error.message || 'Error al guardar la tematica');
        } finally {
            document.getElementById('saveThemeBtn').disabled = false;
        }
    }

    async handleDeleteTheme() {
        if (!this.deleteThemeId) return;

        try {
            document.getElementById('confirmDeleteTheme').disabled = true;

            const response = await fetch(`${this.apiBase}/${this.deleteThemeId}`, {
                method: 'DELETE'
            });

            if (response.ok) {
                showSuccess('Tematica eliminada correctamente');
                this.deleteModal.hide();
                await this.loadThemes();
                await this.loadActiveTheme();
            } else {
                const result = await response.json();
                throw new Error(result.error || 'Error al eliminar');
            }
        } catch (error) {
            console.error('Error deleting theme:', error);
            showError(error.message || 'Error al eliminar la tematica');
        } finally {
            document.getElementById('confirmDeleteTheme').disabled = false;
        }
    }

    // ==================== Rendering ====================

    renderThemes() {
        if (this.themes.length === 0) {
            this.renderEmptyState();
            return;
        }

        this.themesContainer.innerHTML = this.themes.map(theme => this.createThemeCard(theme)).join('');
    }

    renderEmptyState() {
        this.themesContainer.innerHTML = `
            <div class="col-12">
                <div class="empty-themes">
                    <i class="bi bi-palette"></i>
                    <h5>No hay tematicas configuradas</h5>
                    <p>Crea tu primera tematica para personalizar la apariencia del sistema segun diferentes ocasiones o temporadas.</p>
                    <button class="btn btn-primary mt-3" data-bs-toggle="modal" data-bs-target="#themeModal" onclick="themesManager.openCreateModal()">
                        <i class="bi bi-plus-lg me-1"></i>Crear Primera Tematica
                    </button>
                </div>
            </div>
        `;
    }

    createThemeCard(theme) {
        const isActive = theme.is_active;
        const colors = theme.colors || {};

        const statusBadge = isActive
            ? '<span class="badge bg-success theme-status-badge"><i class="bi bi-check-circle me-1"></i>Activa</span>'
            : theme.is_enabled
                ? '<span class="badge bg-secondary theme-status-badge">Inactiva</span>'
                : '<span class="badge bg-dark theme-status-badge">Deshabilitada</span>';

        const previewGradient = colors.primary && colors.secondary
            ? `linear-gradient(135deg, ${colors.primary} 0%, ${colors.secondary} 100%)`
            : 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)';

        return `
            <div class="col-12 col-md-6 col-lg-4">
                <div class="card theme-card h-100 ${isActive ? 'is-active' : ''} position-relative">
                    <div class="theme-preview" style="background: ${previewGradient}">
                        ${statusBadge}
                        <div class="preview-colors">
                            <div class="preview-color-dot" style="background: ${colors.primary || '#0d6efd'}" title="Color primario"></div>
                            <div class="preview-color-dot" style="background: ${colors.secondary || '#6c757d'}" title="Color secundario"></div>
                            <div class="preview-color-dot" style="background: ${colors.accent || '#ffc107'}" title="Color acento"></div>
                        </div>
                    </div>
                    <div class="theme-info">
                        <h5>${this.escapeHtml(theme.name)}</h5>
                        <p class="theme-description">${this.escapeHtml(theme.description) || 'Sin descripcion'}</p>
                        ${theme.date_range_display ? `
                            <div class="theme-dates mt-2">
                                <i class="bi bi-calendar-event me-1"></i>
                                ${theme.date_range_display}
                            </div>
                        ` : ''}
                        ${this.renderDecorationBadges(theme.decorations)}
                    </div>
                    <div class="theme-actions">
                        <div class="form-check form-switch mb-0">
                            <input class="form-check-input" type="checkbox"
                                   id="toggle_${theme.id}"
                                   ${theme.is_manually_active ? 'checked' : ''}
                                   onchange="themesManager.toggleTheme(${theme.id}, this.checked)"
                                   ${!theme.is_enabled ? 'disabled' : ''}>
                            <label class="form-check-label small" for="toggle_${theme.id}">
                                Activar manual
                            </label>
                        </div>
                        <div class="btn-group btn-group-sm">
                            <button class="btn btn-outline-primary" onclick="themesManager.editTheme(${theme.id})" title="Editar">
                                <i class="bi bi-pencil"></i>
                            </button>
                            <button class="btn btn-outline-danger" onclick="themesManager.confirmDelete(${theme.id}, '${this.escapeHtml(theme.name)}')" title="Eliminar">
                                <i class="bi bi-trash"></i>
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        `;
    }

    renderActiveTheme(theme) {
        if (!theme) {
            this.activeThemeStatus.textContent = 'Ninguna';
            this.activeThemeContent.innerHTML = `
                <div class="no-active-theme">
                    <i class="bi bi-palette d-block"></i>
                    <p class="mb-0">No hay tematica activa actualmente</p>
                    <small class="text-muted">Las tematicas se activan automaticamente por fechas o manualmente</small>
                </div>
            `;
            return;
        }

        const colors = theme.colors || {};
        this.activeThemeStatus.textContent = theme.is_manually_active ? 'Activada Manualmente' : 'Activada por Fechas';

        const previewGradient = colors.primary && colors.secondary
            ? `linear-gradient(135deg, ${colors.primary} 0%, ${colors.secondary} 100%)`
            : 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)';

        this.activeThemeContent.innerHTML = `
            <div class="active-theme-info">
                <div class="active-theme-preview" style="background: ${previewGradient}">
                    <div class="preview-colors">
                        <div class="preview-color-dot" style="background: ${colors.primary || '#0d6efd'}"></div>
                        <div class="preview-color-dot" style="background: ${colors.secondary || '#6c757d'}"></div>
                        <div class="preview-color-dot" style="background: ${colors.accent || '#ffc107'}"></div>
                    </div>
                </div>
                <div class="active-theme-details">
                    <h5>${this.escapeHtml(theme.name)}</h5>
                    <p>${this.escapeHtml(theme.description) || 'Sin descripcion'}</p>
                    <div class="active-theme-badges">
                        ${theme.date_range_display ? `
                            <span class="badge bg-info">
                                <i class="bi bi-calendar me-1"></i>${theme.date_range_display}
                            </span>
                        ` : ''}
                        <span class="badge bg-secondary">Prioridad: ${theme.priority}</span>
                        ${this.renderDecorationBadges(theme.decorations)}
                    </div>
                </div>
                <div class="active-theme-action">
                    <button class="btn btn-outline-primary btn-sm" onclick="themesManager.editTheme(${theme.id})">
                        <i class="bi bi-pencil me-1"></i>Editar
                    </button>
                </div>
            </div>
        `;
    }

    renderDecorationBadges(decorations) {
        if (!decorations) return '';

        const badges = [];
        for (const [key, config] of Object.entries(decorations)) {
            if (config?.enabled) {
                const preset = this.decorationPresets[key];
                const icon = preset ? preset.icon : 'bi-star';
                const label = preset ? preset.label : key;
                badges.push(`<span class="badge bg-light text-dark ms-1" title="${this.escapeHtml(label)}"><i class="bi ${icon}"></i></span>`);
            }
        }

        return badges.join('');
    }

    // ==================== Decorations Dynamic Editor ====================

    addDecoration(key = '', config = {}) {
        this.decorationCounter++;
        const id = this.decorationCounter;
        const isEnabled = config.enabled !== undefined ? config.enabled : true;
        const count = config.count || '';
        const interval = config.interval || '';

        // Generar opciones del select de presets
        const presetOptions = Object.entries(this.decorationPresets).map(([presetKey, preset]) => {
            const selected = presetKey === key ? 'selected' : '';
            return `<option value="${presetKey}" ${selected}>${preset.label}</option>`;
        }).join('');

        const isCustom = key && !this.decorationPresets[key];

        const html = `
            <div class="decoration-entry card card-body p-2 mb-2" data-deco-id="${id}">
                <div class="d-flex align-items-center gap-2">
                    <div class="form-check form-switch mb-0 flex-shrink-0">
                        <input class="form-check-input deco-enabled" type="checkbox" ${isEnabled ? 'checked' : ''}>
                    </div>
                    <div class="flex-grow-1">
                        <div class="d-flex gap-2 align-items-center">
                            <select class="form-select form-select-sm deco-preset" onchange="themesManager.onPresetChange(${id})">
                                <option value="">-- Personalizado --</option>
                                ${presetOptions}
                            </select>
                            <input type="text" class="form-control form-control-sm deco-key"
                                   value="${this.escapeHtml(key)}" placeholder="clave"
                                   style="${isCustom ? '' : 'display:none'}"
                                   title="Clave unica de la decoracion">
                        </div>
                    </div>
                    <div class="d-flex gap-1 flex-shrink-0 align-items-center">
                        <input type="number" class="form-control form-control-sm deco-count"
                               value="${count}" placeholder="Cant."
                               style="width: 70px;" title="Cantidad (opcional)">
                        <input type="number" class="form-control form-control-sm deco-interval"
                               value="${interval}" placeholder="Intervalo ms"
                               style="width: 100px;" title="Intervalo en ms (opcional)">
                        <button type="button" class="btn btn-sm btn-outline-danger" onclick="themesManager.removeDecoration(${id})" title="Quitar">
                            <i class="bi bi-x-lg"></i>
                        </button>
                    </div>
                </div>
            </div>
        `;

        this.decorationsList.insertAdjacentHTML('beforeend', html);

        // Si es custom, mostrar el input de clave
        if (isCustom) {
            const entry = this.decorationsList.querySelector(`[data-deco-id="${id}"]`);
            entry.querySelector('.deco-key').style.display = '';
        }
    }

    onPresetChange(id) {
        const entry = this.decorationsList.querySelector(`[data-deco-id="${id}"]`);
        if (!entry) return;

        const select = entry.querySelector('.deco-preset');
        const keyInput = entry.querySelector('.deco-key');

        if (select.value) {
            // Preset seleccionado: ocultar input de clave, usar valor del preset
            keyInput.style.display = 'none';
            keyInput.value = select.value;
        } else {
            // Personalizado: mostrar input de clave
            keyInput.style.display = '';
            keyInput.value = '';
            keyInput.focus();
        }
    }

    removeDecoration(id) {
        const entry = this.decorationsList.querySelector(`[data-deco-id="${id}"]`);
        if (entry) entry.remove();
    }

    collectDecorations() {
        const entries = this.decorationsList.querySelectorAll('.decoration-entry');
        const decorations = {};

        entries.forEach(entry => {
            const preset = entry.querySelector('.deco-preset').value;
            const customKey = entry.querySelector('.deco-key').value.trim();
            const key = preset || customKey;

            if (!key) return;

            const enabled = entry.querySelector('.deco-enabled').checked;
            const count = parseInt(entry.querySelector('.deco-count').value);
            const interval = parseInt(entry.querySelector('.deco-interval').value);

            const config = { enabled };
            if (!isNaN(count) && count > 0) config.count = count;
            if (!isNaN(interval) && interval > 0) config.interval = interval;

            decorations[key] = config;
        });

        return decorations;
    }

    populateDecorations(decorations) {
        this.decorationsList.innerHTML = '';
        this.decorationCounter = 0;

        if (!decorations || Object.keys(decorations).length === 0) return;

        for (const [key, config] of Object.entries(decorations)) {
            this.addDecoration(key, config);
        }
    }

    // ==================== Form Handling ====================

    openCreateModal() {
        this.editingThemeId = null;
        this.themeModalTitle.innerHTML = '<i class="bi bi-plus-lg me-2"></i>Nueva Tematica';
        this.resetForm();
    }

    async editTheme(themeId) {
        try {
            const response = await fetch(`${this.apiBase}/${themeId}`);
            const result = await response.json();

            if (!response.ok || !result.data) {
                throw new Error('Theme not found');
            }

            const theme = result.data;
            this.editingThemeId = themeId;
            this.themeModalTitle.innerHTML = '<i class="bi bi-pencil me-2"></i>Editar Tematica';

            // Populate form
            this.populateForm(theme);
            this.themeModal.show();

        } catch (error) {
            console.error('Error loading theme:', error);
            showError('Error al cargar la tematica');
        }
    }

    populateForm(theme) {
        document.getElementById('themeName').value = theme.name || '';
        document.getElementById('themeDescription').value = theme.description || '';
        document.getElementById('themePriority').value = theme.priority || 100;

        // Dates
        document.getElementById('startDay').value = theme.start_day || '';
        document.getElementById('startMonth').value = theme.start_month || '';
        document.getElementById('endDay').value = theme.end_day || '';
        document.getElementById('endMonth').value = theme.end_month || '';

        // Colors
        const colors = theme.colors || {};
        this.setColorValue('colorPrimary', 'colorPrimaryHex', colors.primary || '#0d6efd');
        this.setColorValue('colorSecondary', 'colorSecondaryHex', colors.secondary || '#6c757d');
        this.setColorValue('colorAccent', 'colorAccentHex', colors.accent || '#ffc107');

        // Decorations - dynamic
        this.populateDecorations(theme.decorations);

        // Files
        document.getElementById('cssFile').value = theme.css_file || '';
        document.getElementById('jsFile').value = theme.js_file || '';

        // Custom CSS
        document.getElementById('customCss').value = theme.custom_css || '';
    }

    setColorValue(colorId, hexId, value) {
        document.getElementById(colorId).value = value;
        document.getElementById(hexId).value = value.toUpperCase();
    }

    collectFormData() {
        return {
            name: document.getElementById('themeName').value.trim(),
            description: document.getElementById('themeDescription').value.trim() || null,
            priority: parseInt(document.getElementById('themePriority').value) || 100,
            start_day: parseInt(document.getElementById('startDay').value) || null,
            start_month: parseInt(document.getElementById('startMonth').value) || null,
            end_day: parseInt(document.getElementById('endDay').value) || null,
            end_month: parseInt(document.getElementById('endMonth').value) || null,
            colors: {
                primary: document.getElementById('colorPrimary').value,
                secondary: document.getElementById('colorSecondary').value,
                accent: document.getElementById('colorAccent').value
            },
            decorations: this.collectDecorations(),
            css_file: document.getElementById('cssFile').value.trim() || null,
            js_file: document.getElementById('jsFile').value.trim() || null,
            custom_css: document.getElementById('customCss').value || ''
        };
    }

    resetForm() {
        this.editingThemeId = null;
        this.themeForm.reset();

        // Reset colors to defaults
        this.setColorValue('colorPrimary', 'colorPrimaryHex', '#0d6efd');
        this.setColorValue('colorSecondary', 'colorSecondaryHex', '#6c757d');
        this.setColorValue('colorAccent', 'colorAccentHex', '#ffc107');

        // Reset priority
        document.getElementById('themePriority').value = 100;

        // Clear decorations
        this.decorationsList.innerHTML = '';
        this.decorationCounter = 0;
    }

    confirmDelete(themeId, themeName) {
        this.deleteThemeId = themeId;
        document.getElementById('deleteThemeName').textContent = themeName;
        this.deleteModal.show();
    }

    // ==================== Utilities ====================

    escapeHtml(text) {
        if (!text) return '';
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
}

// Initialize
let themesManager;
document.addEventListener('DOMContentLoaded', () => {
    themesManager = new ThemesManager();
});
