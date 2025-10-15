// itcj/apps/helpdesk/static/js/user/create_ticket.js

let currentStep = 1;
const totalSteps = 3;
let selectedArea = null;
let categories = [];

// ==================== INITIALIZATION ====================
document.addEventListener('DOMContentLoaded', () => {
    setupAreaSelection();
    setupFormValidation();
    setupNavigation();
    setupDescriptionCounter();
});

// ==================== AREA SELECTION ====================
function setupAreaSelection() {
    document.querySelectorAll('.area-card').forEach(card => {
        card.addEventListener('click', async function() {
            const area = this.dataset.area;
            await selectArea(area);
        });
    });
}

async function selectArea(area) {
    // Visual feedback
    document.querySelectorAll('.area-card .card').forEach(card => {
        card.classList.remove('selected');
    });
    
    const selectedCard = document.querySelector(`[data-area="${area}"] .card`);
    selectedCard.classList.add('selected');
    
    selectedArea = area;
    document.getElementById('area').value = area;
    
    // Load categories for this area
    try {
        HelpdeskUtils.showLoading('category_id');
        const response = await HelpdeskUtils.api.getCategories(area);
        categories = response.categories || [];
        
        const categorySelect = document.getElementById('category_id');
        categorySelect.innerHTML = '<option value="">Selecciona una categoría...</option>';
        
        categories.forEach(cat => {
            const option = document.createElement('option');
            option.value = cat.id;
            option.textContent = cat.name;
            categorySelect.appendChild(option);
        });
        
    } catch (error) {
        console.error('Error loading categories:', error);
        HelpdeskUtils.showToast('Error al cargar categorías', 'error');
    }
    
    // Enable next button
    document.getElementById('btnNext').disabled = false;
}

// ==================== FORM VALIDATION ====================
function setupFormValidation() {
    const form = document.getElementById('ticketForm');
    
    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        
        if (currentStep !== totalSteps) return;
        
        if (!form.checkValidity()) {
            e.stopPropagation();
            form.classList.add('was-validated');
            return;
        }
        
        await submitTicket();
    });
    
    // Real-time validation
    ['title', 'description', 'category_id'].forEach(fieldId => {
        const field = document.getElementById(fieldId);
        field?.addEventListener('blur', () => {
            field.classList.add('was-validated');
        });
    });
}

function setupDescriptionCounter() {
    const textarea = document.getElementById('description');
    const counter = document.getElementById('descCharCount');
    
    textarea.addEventListener('input', () => {
        const length = textarea.value.length;
        counter.textContent = `${length} / 20 caracteres mínimo`;
        
        if (length >= 20) {
            counter.classList.remove('text-danger');
            counter.classList.add('text-success');
        } else {
            counter.classList.remove('text-success');
            counter.classList.add('text-danger');
        }
    });
}

// ==================== NAVIGATION ====================
function setupNavigation() {
    document.getElementById('btnNext').addEventListener('click', nextStep);
    document.getElementById('btnPrevious').addEventListener('click', previousStep);
}

function nextStep() {
    if (!validateCurrentStep()) return;
    
    if (currentStep < totalSteps) {
        currentStep++;
        showStep(currentStep);
        
        if (currentStep === totalSteps) {
            showSummary();
        }
    }
}

function previousStep() {
    if (currentStep > 1) {
        currentStep--;
        showStep(currentStep);
    }
}

function showStep(step) {
    // Hide all steps
    document.querySelectorAll('.step-content').forEach(content => {
        content.classList.add('d-none');
    });
    
    // Show current step
    document.getElementById(`step${step}`).classList.remove('d-none');
    
    // Update indicators
    for (let i = 1; i <= totalSteps; i++) {
        const indicator = document.getElementById(`step-indicator-${i}`);
        if (i <= step) {
            indicator.classList.add('active');
        } else {
            indicator.classList.remove('active');
        }
    }
    
    // Update buttons
    const btnPrevious = document.getElementById('btnPrevious');
    const btnNext = document.getElementById('btnNext');
    const btnSubmit = document.getElementById('btnSubmit');
    
    btnPrevious.style.display = step > 1 ? 'block' : 'none';
    btnNext.style.display = step < totalSteps ? 'block' : 'none';
    btnSubmit.style.display = step === totalSteps ? 'block' : 'none';
    
    // Scroll to top
    window.scrollTo({ top: 0, behavior: 'smooth' });
}

function validateCurrentStep() {
    switch (currentStep) {
        case 1:
            if (!selectedArea) {
                HelpdeskUtils.showToast('Por favor selecciona el tipo de problema', 'warning');
                return false;
            }
            return true;
            
        case 2:
            const categoryId = document.getElementById('category_id').value;
            const title = document.getElementById('title').value.trim();
            const description = document.getElementById('description').value.trim();
            
            if (!categoryId) {
                HelpdeskUtils.showToast('Por favor selecciona una categoría', 'warning');
                document.getElementById('category_id').focus();
                return false;
            }
            
            if (title.length < 5) {
                HelpdeskUtils.showToast('El título debe tener al menos 5 caracteres', 'warning');
                document.getElementById('title').focus();
                return false;
            }
            
            if (description.length < 20) {
                HelpdeskUtils.showToast('La descripción debe tener al menos 20 caracteres', 'warning');
                document.getElementById('description').focus();
                return false;
            }
            
            return true;
            
        default:
            return true;
    }
}

// ==================== SUMMARY ====================
function showSummary() {
    const formData = getFormData();
    const category = categories.find(c => c.id === parseInt(formData.category_id));
    
    const summary = `
        <h5 class="mb-3">
            <i class="fas fa-clipboard-check me-2 text-primary"></i>
            Resumen de tu Ticket
        </h5>
        
        <div class="row g-3">
            <div class="col-md-6">
                <strong><i class="fas fa-layer-group me-2 text-muted"></i>Área:</strong><br>
                ${HelpdeskUtils.getAreaBadge(formData.area)}
            </div>
            <div class="col-md-6">
                <strong><i class="fas fa-tag me-2 text-muted"></i>Categoría:</strong><br>
                <span class="badge bg-secondary">${category?.name || 'N/A'}</span>
            </div>
            <div class="col-12">
                <strong><i class="fas fa-heading me-2 text-muted"></i>Título:</strong><br>
                ${formData.title}
            </div>
            <div class="col-12">
                <strong><i class="fas fa-align-left me-2 text-muted"></i>Descripción:</strong><br>
                <p class="mb-0">${formData.description}</p>
            </div>
            <div class="col-md-6">
                <strong><i class="fas fa-exclamation-circle me-2 text-muted"></i>Prioridad:</strong><br>
                ${HelpdeskUtils.getPriorityBadge(formData.priority)}
            </div>
            ${formData.location ? `
            <div class="col-md-6">
                <strong><i class="fas fa-map-marker-alt me-2 text-muted"></i>Ubicación:</strong><br>
                ${formData.location}
            </div>
            ` : ''}
            ${formData.office_folio ? `
            <div class="col-md-6">
                <strong><i class="fas fa-file-alt me-2 text-muted"></i>Folio de Oficio:</strong><br>
                ${formData.office_folio}
            </div>
            ` : ''}
        </div>
    `;
    
    document.getElementById('ticketSummary').innerHTML = summary;
}

// ==================== SUBMIT ====================
function getFormData() {
    return {
        area: document.getElementById('area').value,
        category_id: parseInt(document.getElementById('category_id').value),
        title: document.getElementById('title').value.trim(),
        description: document.getElementById('description').value.trim(),
        priority: document.querySelector('input[name="priority"]:checked').value,
        location: document.getElementById('location').value.trim() || null,
        office_folio: document.getElementById('office_folio').value.trim() || null
    };
}

async function submitTicket() {
    const submitBtn = document.getElementById('btnSubmit');
    const originalText = submitBtn.innerHTML;
    
    // Disable button and show loading
    submitBtn.disabled = true;
    submitBtn.innerHTML = '<i class="fas fa-spinner fa-spin me-2"></i>Enviando...';
    
    // Animate ticket preview
    const preview = document.getElementById('ticketPreview');
    preview.style.animation = 'ticket-send 1.5s ease-out forwards';
    
    try {
        const formData = getFormData();
        const response = await HelpdeskUtils.api.createTicket(formData);
        
        // Success!
        HelpdeskUtils.showToast(
            '¡Ticket creado exitosamente! Serás notificado cuando sea asignado.',
            'success'
        );
        
        // Wait a bit for animation, then redirect
        setTimeout(() => {
            window.location.href = '/help-desk/user/my-tickets';
        }, 2000);
        
    } catch (error) {
        console.error('Error creating ticket:', error);
        HelpdeskUtils.showToast(
            error.message || 'Error al crear el ticket. Intenta nuevamente.',
            'error'
        );
        
        // Re-enable button
        submitBtn.disabled = false;
        submitBtn.innerHTML = originalText;
        preview.style.animation = '';
    }
}

// ==================== TICKET SEND ANIMATION ====================
const style = document.createElement('style');
style.textContent = `
@keyframes ticket-send {
    0% {
        transform: translateY(0) scale(1) rotate(0deg);
        opacity: 1;
    }
    50% {
        transform: translateY(-30px) scale(1.1) rotate(5deg);
        opacity: 0.8;
    }
    100% {
        transform: translateY(-100px) scale(0.8) rotate(10deg);
        opacity: 0;
    }
}
`;
document.head.appendChild(style);