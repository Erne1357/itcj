/**
 * _daterange.js
 * Componente de selector de rango de fechas para las páginas de admin de Maint.
 * Expone: window.MaintDateRange
 *
 * API pública:
 *   MaintDateRange.init(containerSelector, { onChange })
 *   MaintDateRange.getRange() → { from: 'YYYY-MM-DD', to: 'YYYY-MM-DD' }
 */
'use strict';

(function () {

    var PRESETS = [
        { label: 'Hoy',              key: 'today'    },
        { label: 'Últimos 7 días',   key: 'last7'    },
        { label: 'Últimos 30 días',  key: 'last30'   },
        { label: 'Este mes',         key: 'thismonth'},
        { label: 'Mes anterior',     key: 'lastmonth'},
        { label: 'Personalizado',    key: 'custom'   },
    ];

    var DEFAULT_PRESET = 'last30';

    // ── Estado por instancia (soporte para múltiples instancias en una misma página) ──

    var _instances = [];

    function _today() {
        return new Date();
    }

    function _fmt(d) {
        var y = d.getFullYear();
        var m = String(d.getMonth() + 1).padStart(2, '0');
        var day = String(d.getDate()).padStart(2, '0');
        return y + '-' + m + '-' + day;
    }

    function _addDays(d, n) {
        var r = new Date(d.getTime());
        r.setDate(r.getDate() + n);
        return r;
    }

    function _startOfMonth(d) {
        return new Date(d.getFullYear(), d.getMonth(), 1);
    }

    function _endOfMonth(d) {
        return new Date(d.getFullYear(), d.getMonth() + 1, 0);
    }

    function _startOfPrevMonth(d) {
        return new Date(d.getFullYear(), d.getMonth() - 1, 1);
    }

    function _endOfPrevMonth(d) {
        return new Date(d.getFullYear(), d.getMonth(), 0);
    }

    function _rangeForPreset(key) {
        var now = _today();
        switch (key) {
            case 'today':
                return { from: _fmt(now), to: _fmt(now) };
            case 'last7':
                return { from: _fmt(_addDays(now, -6)), to: _fmt(now) };
            case 'last30':
                return { from: _fmt(_addDays(now, -29)), to: _fmt(now) };
            case 'thismonth':
                return { from: _fmt(_startOfMonth(now)), to: _fmt(_endOfMonth(now)) };
            case 'lastmonth':
                return { from: _fmt(_startOfPrevMonth(now)), to: _fmt(_endOfPrevMonth(now)) };
            default:
                return null; // custom
        }
    }

    // ── Renderizado ──────────────────────────────────────────────────────────

    function _render(container, instance) {
        container.innerHTML = '';
        container.className = 'maint-daterange-bar card border-0 shadow-sm p-3 mb-4';

        var wrapper = document.createElement('div');
        wrapper.className = 'd-flex align-items-center flex-wrap gap-2';

        // Label
        var lbl = document.createElement('span');
        lbl.className = 'small fw-semibold text-muted me-1';
        lbl.textContent = 'Período:';
        wrapper.appendChild(lbl);

        // Preset buttons
        PRESETS.forEach(function (p) {
            var btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'btn btn-sm btn-outline-secondary' + (instance.activePreset === p.key ? ' active' : '');
            btn.style.cssText = 'font-size:0.8rem;padding:0.2rem 0.6rem;';
            btn.textContent = p.label;
            btn.dataset.preset = p.key;
            if (instance.activePreset === p.key && p.key !== 'custom') {
                btn.classList.add('active');
                btn.style.background = 'var(--maint-primary)';
                btn.style.borderColor = 'var(--maint-primary)';
                btn.style.color = '#fff';
            }
            btn.addEventListener('click', function () {
                _selectPreset(container, instance, p.key);
            });
            wrapper.appendChild(btn);
        });

        // Custom date inputs (hidden unless custom)
        var customDiv = document.createElement('div');
        customDiv.className = 'd-flex align-items-center gap-2' + (instance.activePreset === 'custom' ? '' : ' d-none');
        customDiv.id = instance.id + '-custom';

        var fromInput = document.createElement('input');
        fromInput.type = 'date';
        fromInput.className = 'form-control form-control-sm';
        fromInput.style.width = '140px';
        fromInput.value = instance.from;
        fromInput.addEventListener('change', function () {
            instance.from = this.value;
            _notifyChange(instance);
        });

        var sep = document.createElement('span');
        sep.className = 'text-muted small';
        sep.textContent = '→';

        var toInput = document.createElement('input');
        toInput.type = 'date';
        toInput.className = 'form-control form-control-sm';
        toInput.style.width = '140px';
        toInput.value = instance.to;
        toInput.addEventListener('change', function () {
            instance.to = this.value;
            _notifyChange(instance);
        });

        customDiv.appendChild(fromInput);
        customDiv.appendChild(sep);
        customDiv.appendChild(toInput);
        wrapper.appendChild(customDiv);

        container.appendChild(wrapper);

        instance._fromInput = fromInput;
        instance._toInput   = toInput;
        instance._customDiv = customDiv;
        instance._btns      = wrapper.querySelectorAll('[data-preset]');
    }

    function _selectPreset(container, instance, key) {
        instance.activePreset = key;

        // Update button styles
        instance._btns.forEach(function (btn) {
            var active = btn.dataset.preset === key;
            btn.classList.toggle('active', active);
            btn.style.background   = active ? 'var(--maint-primary)' : '';
            btn.style.borderColor  = active ? 'var(--maint-primary)' : '';
            btn.style.color        = active ? '#fff' : '';
        });

        if (key === 'custom') {
            instance._customDiv.classList.remove('d-none');
            // No notify yet — wait for date input change
            return;
        }

        instance._customDiv.classList.add('d-none');

        var range = _rangeForPreset(key);
        if (range) {
            instance.from = range.from;
            instance.to   = range.to;
            if (instance._fromInput) instance._fromInput.value = range.from;
            if (instance._toInput)   instance._toInput.value   = range.to;
        }

        _notifyChange(instance);
    }

    function _notifyChange(instance) {
        if (typeof instance.onChange === 'function') {
            instance.onChange({ from: instance.from, to: instance.to });
        }
    }

    // ── API pública ──────────────────────────────────────────────────────────

    function init(containerSelector, options) {
        options = options || {};
        var container = document.querySelector(containerSelector);
        if (!container) {
            console.warn('[MaintDateRange] Container not found:', containerSelector);
            return null;
        }

        var defaultRange = _rangeForPreset(DEFAULT_PRESET);

        var instance = {
            id:           'mdr-' + _instances.length,
            activePreset: DEFAULT_PRESET,
            from:         defaultRange.from,
            to:           defaultRange.to,
            onChange:     options.onChange || null,
            _fromInput:   null,
            _toInput:     null,
            _customDiv:   null,
            _btns:        null,
        };

        _instances.push(instance);
        _render(container, instance);

        return {
            getRange: function () { return { from: instance.from, to: instance.to }; },
        };
    }

    window.MaintDateRange = { init: init };

})();
