/**
 * VisteTec - Formulario de registro/edición de prendas
 */
(function () {
    'use strict';

    const API_BASE = '/api/vistetec/v1/garments';
    const form = document.getElementById('garmentForm');
    const imageInput = document.getElementById('imageInput');
    const imagePreview = document.getElementById('imagePreview');
    const imagePlaceholder = document.getElementById('imagePlaceholder');
    const btnSubmit = document.getElementById('btnSubmit');
    const btnSubmitText = document.getElementById('btnSubmitText');
    const btnSubmitLoading = document.getElementById('btnSubmitLoading');

    const isEdit = GARMENT_ID !== null;

    // Preview de imagen
    imageInput.addEventListener('change', (e) => {
        const file = e.target.files[0];
        if (!file) return;

        // Validar tamaño (3 MB)
        if (file.size > 3 * 1024 * 1024) {
            showToast('El archivo excede 3 MB', 'danger');
            imageInput.value = '';
            return;
        }

        const reader = new FileReader();
        reader.onload = (ev) => {
            imagePreview.src = ev.target.result;
            imagePreview.classList.remove('d-none');
            imagePlaceholder.classList.add('d-none');
        };
        reader.readAsDataURL(file);
    });

    // Cargar datos si es edición
    if (isEdit) {
        btnSubmitText.textContent = 'Guardar Cambios';
        loadGarmentData();
    }

    async function loadGarmentData() {
        try {
            const res = await fetch(`/api/vistetec/v1/catalog/${GARMENT_ID}`);
            if (!res.ok) return;
            const g = await res.json();

            document.getElementById('name').value = g.name || '';
            document.getElementById('description').value = g.description || '';
            document.getElementById('category').value = g.category || '';
            document.getElementById('condition').value = g.condition || '';
            document.getElementById('gender').value = g.gender || '';
            document.getElementById('size').value = g.size || '';
            document.getElementById('color').value = g.color || '';
            document.getElementById('brand').value = g.brand || '';
            document.getElementById('material').value = g.material || '';

            if (g.image_path) {
                imagePreview.src = `/api/vistetec/v1/garments/image/${g.image_path}`;
                imagePreview.classList.remove('d-none');
                imagePlaceholder.classList.add('d-none');
            }
        } catch (e) {
            console.error('Error cargando prenda:', e);
        }
    }

    // Submit
    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        setLoading(true);

        const formData = new FormData(form);

        try {
            const url = isEdit ? `${API_BASE}/${GARMENT_ID}` : API_BASE;
            const method = isEdit ? 'PUT' : 'POST';

            const res = await fetch(url, {
                method,
                body: formData,
            });

            const data = await res.json();

            if (!res.ok) {
                showToast(data.error || 'Error al guardar', 'danger');
                return;
            }

            showToast(isEdit ? 'Prenda actualizada' : `Prenda registrada: ${data.code}`, 'success');

            if (!isEdit) {
                // Redirigir al dashboard después de crear
                setTimeout(() => {
                    window.location.href = '/vistetec/volunteer/dashboard';
                }, 1500);
            }
        } catch (e) {
            console.error(e);
            showToast('Error de conexión', 'danger');
        } finally {
            setLoading(false);
        }
    });

    function setLoading(loading) {
        btnSubmit.disabled = loading;
        btnSubmitText.classList.toggle('d-none', loading);
        btnSubmitLoading.classList.toggle('d-none', !loading);
    }

    function showToast(message, type = 'info') {
        const container = document.getElementById('toastContainer');
        if (!container) return;

        const toast = document.createElement('div');
        toast.className = `toast align-items-center text-bg-${type} border-0 show`;
        toast.setAttribute('role', 'alert');
        toast.innerHTML = `
            <div class="d-flex">
                <div class="toast-body">${message}</div>
                <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button>
            </div>`;

        container.appendChild(toast);
        setTimeout(() => toast.remove(), 4000);
    }
})();
