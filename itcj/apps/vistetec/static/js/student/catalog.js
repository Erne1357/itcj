/**
 * VisteTec - Catálogo de prendas
 */
(function () {
    'use strict';

    const API_BASE = '/api/vistetec/v1/catalog';
    let currentPage = 1;
    const PER_PAGE = 12;

    // Elementos DOM
    const grid = document.getElementById('garmentGrid');
    const emptyState = document.getElementById('emptyState');
    const loadingState = document.getElementById('loadingState');
    const paginationNav = document.getElementById('paginationNav');
    const pagination = document.getElementById('pagination');
    const searchInput = document.getElementById('searchInput');
    const filterCategory = document.getElementById('filterCategory');
    const filterGender = document.getElementById('filterGender');
    const filterSize = document.getElementById('filterSize');
    const btnClearFilters = document.getElementById('btnClearFilters');
    const availableCount = document.getElementById('availableCount');

    // Condición a texto legible
    const conditionLabels = {
        nuevo: 'Nuevo',
        como_nuevo: 'Como nuevo',
        buen_estado: 'Buen estado',
        usado: 'Usado',
    };

    const conditionColors = {
        nuevo: 'success',
        como_nuevo: 'info',
        buen_estado: 'warning',
        usado: 'secondary',
    };

    async function loadCatalog(page = 1) {
        currentPage = page;
        showLoading(true);

        const params = new URLSearchParams({ page, per_page: PER_PAGE });
        const search = searchInput.value.trim();
        const category = filterCategory.value;
        const gender = filterGender.value;
        const size = filterSize.value;

        if (search) params.set('search', search);
        if (category) params.set('category', category);
        if (gender) params.set('gender', gender);
        if (size) params.set('size', size);

        try {
            const res = await fetch(`${API_BASE}?${params}`);
            if (!res.ok) throw new Error('Error al cargar catálogo');
            const data = await res.json();

            renderGarments(data.items);
            renderPagination(data);
            availableCount.textContent = `${data.total} disponible${data.total !== 1 ? 's' : ''}`;
        } catch (e) {
            console.error(e);
            grid.innerHTML = '';
            showEmpty(true);
        } finally {
            showLoading(false);
        }
    }

    function renderGarments(items) {
        if (!items.length) {
            grid.innerHTML = '';
            showEmpty(true);
            return;
        }

        showEmpty(false);
        grid.innerHTML = items.map(g => {
            const imageHtml = g.image_path
                ? `<img src="/api/vistetec/v1/garments/image/${g.image_path}" class="card-img-top" alt="${g.name}" loading="lazy">`
                : `<div class="card-img-placeholder"><i class="bi bi-image"></i></div>`;

            const condLabel = conditionLabels[g.condition] || g.condition;
            const condColor = conditionColors[g.condition] || 'secondary';

            return `
            <div class="col-6 col-md-4 col-lg-3">
                <a href="/vistetec/student/catalog/${g.id}" class="text-decoration-none">
                    <div class="card garment-card shadow-sm h-100">
                        ${imageHtml}
                        <div class="card-body p-3">
                            <h6 class="card-title fw-bold text-dark mb-1 text-truncate">${g.name}</h6>
                            <div class="d-flex gap-1 flex-wrap mb-2">
                                ${g.size ? `<span class="badge bg-light text-dark border">${g.size}</span>` : ''}
                                ${g.gender ? `<span class="badge bg-light text-dark border">${g.gender}</span>` : ''}
                            </div>
                            <div class="d-flex justify-content-between align-items-center">
                                <span class="badge bg-${condColor}-subtle text-${condColor} badge-condition">${condLabel}</span>
                                ${g.brand ? `<small class="text-muted">${g.brand}</small>` : ''}
                            </div>
                        </div>
                    </div>
                </a>
            </div>`;
        }).join('');
    }

    function renderPagination(data) {
        if (data.pages <= 1) {
            paginationNav.classList.add('d-none');
            return;
        }
        paginationNav.classList.remove('d-none');

        let html = '';
        // Anterior
        html += `<li class="page-item ${data.has_prev ? '' : 'disabled'}">
                    <a class="page-link" href="#" data-page="${data.page - 1}">&laquo;</a>
                 </li>`;

        // Páginas
        for (let i = 1; i <= data.pages; i++) {
            if (data.pages > 7 && i > 2 && i < data.pages - 1 && Math.abs(i - data.page) > 1) {
                if (i === 3 || i === data.pages - 2) html += `<li class="page-item disabled"><span class="page-link">...</span></li>`;
                continue;
            }
            html += `<li class="page-item ${i === data.page ? 'active' : ''}">
                        <a class="page-link" href="#" data-page="${i}">${i}</a>
                     </li>`;
        }

        // Siguiente
        html += `<li class="page-item ${data.has_next ? '' : 'disabled'}">
                    <a class="page-link" href="#" data-page="${data.page + 1}">&raquo;</a>
                 </li>`;

        pagination.innerHTML = html;
    }

    async function loadFilters() {
        try {
            const [catRes, sizeRes] = await Promise.all([
                fetch(`${API_BASE}/categories`),
                fetch(`${API_BASE}/sizes`),
            ]);

            if (catRes.ok) {
                const cats = await catRes.json();
                cats.forEach(c => {
                    const opt = document.createElement('option');
                    opt.value = c.name;
                    opt.textContent = `${c.name} (${c.count})`;
                    filterCategory.appendChild(opt);
                });
            }

            if (sizeRes.ok) {
                const sizes = await sizeRes.json();
                sizes.forEach(s => {
                    const opt = document.createElement('option');
                    opt.value = s.name;
                    opt.textContent = `${s.name} (${s.count})`;
                    filterSize.appendChild(opt);
                });
            }
        } catch (e) {
            console.error('Error cargando filtros:', e);
        }
    }

    function showLoading(show) {
        loadingState.classList.toggle('d-none', !show);
        if (show) {
            grid.innerHTML = '';
            emptyState.classList.add('d-none');
            paginationNav.classList.add('d-none');
        }
    }

    function showEmpty(show) {
        emptyState.classList.toggle('d-none', !show);
    }

    // Event listeners
    let searchTimeout;
    searchInput.addEventListener('input', () => {
        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(() => loadCatalog(1), 400);
    });

    filterCategory.addEventListener('change', () => loadCatalog(1));
    filterGender.addEventListener('change', () => loadCatalog(1));
    filterSize.addEventListener('change', () => loadCatalog(1));

    btnClearFilters.addEventListener('click', () => {
        searchInput.value = '';
        filterCategory.value = '';
        filterGender.value = '';
        filterSize.value = '';
        loadCatalog(1);
    });

    pagination.addEventListener('click', (e) => {
        e.preventDefault();
        const page = e.target.closest('[data-page]')?.dataset.page;
        if (page) loadCatalog(parseInt(page));
    });

    // Init
    loadFilters();
    loadCatalog(1);
})();
