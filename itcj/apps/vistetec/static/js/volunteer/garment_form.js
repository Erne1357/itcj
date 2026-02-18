/**
 * VisteTec - Formulario de registro/edicion de prendas
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
    let compressedImageFile = null;

    // Preview de imagen con compresion automatica
    imageInput.addEventListener('change', async (e) => {
        const file = e.target.files[0];
        if (!file) return;

        let processedFile = file;

        // Comprimir si excede 1 MB
        if (file.size > 1 * 1024 * 1024) {
            try {
                VisteTecUtils.showToast('Comprimiendo imagen...', 'info');
                processedFile = await VisteTecUtils.compressImage(file, {
                    maxSizeMB: 3,
                    maxDimension: 1920,
                    initialQuality: 0.8,
                });
            } catch (err) {
                console.error('Error comprimiendo:', err);
                VisteTecUtils.showToast('Error al comprimir, usando original', 'warning');
            }
        }

        // Validacion final
        if (processedFile.size > 3 * 1024 * 1024) {
            VisteTecUtils.showToast('La imagen sigue excediendo 3 MB tras comprimir', 'danger');
            imageInput.value = '';
            compressedImageFile = null;
            return;
        }

        compressedImageFile = processedFile;

        const reader = new FileReader();
        reader.onload = (ev) => {
            imagePreview.src = ev.target.result;
            imagePreview.classList.remove('d-none');
            imagePlaceholder.classList.add('d-none');
        };
        reader.readAsDataURL(processedFile);
    });

    // Cargar datos si es edicion
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

        // Reemplazar imagen con version comprimida si existe
        if (compressedImageFile) {
            formData.delete('image');
            formData.append('image', compressedImageFile, compressedImageFile.name);
        }

        try {
            const url = isEdit ? `${API_BASE}/${GARMENT_ID}` : API_BASE;
            const method = isEdit ? 'PUT' : 'POST';

            const res = await fetch(url, {
                method,
                body: formData,
            });

            const data = await res.json();

            if (!res.ok) {
                VisteTecUtils.showToast(data.error || 'Error al guardar', 'danger');
                return;
            }

            VisteTecUtils.showToast(isEdit ? 'Prenda actualizada' : `Prenda registrada: ${data.code}`, 'success');

            if (!isEdit) {
                setTimeout(() => {
                    window.location.href = '/vistetec/volunteer/dashboard';
                }, 1500);
            }
        } catch (e) {
            console.error(e);
            VisteTecUtils.showToast('Error de conexion', 'danger');
        } finally {
            setLoading(false);
        }
    });

    function setLoading(loading) {
        btnSubmit.disabled = loading;
        btnSubmitText.classList.toggle('d-none', loading);
        btnSubmitLoading.classList.toggle('d-none', !loading);
    }

})();
