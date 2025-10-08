// Datos de ejemplo para mis tickets
const userTickets = [
  {
    id: 1,
    title: "Computadora no enciende en Aula 201",
    type: "Apoyo técnico",
    status: "liberado",
    priority: "alta",
    created: "2024-01-16T10:30:00Z",
    completedAt: "2024-01-16T14:30:00Z",
    assignedTo: "Ernesto",
    description: "La computadora del profesor no enciende desde esta mañana.",
    resolution: "Se reemplazó la fuente de poder defectuosa.",
  },
  {
    id: 2,
    title: "Error al acceder al SIISAE",
    type: "Software",
    status: "en-revision",
    priority: "media",
    created: "2024-01-16T09:15:00Z",
    assignedTo: "Desarrollo",
    description: "No puedo acceder al sistema para capturar calificaciones.",
  },
  {
    id: 3,
    title: "Proyector sin imagen",
    type: "Apoyo técnico",
    status: "cerrado",
    priority: "media",
    created: "2024-01-15T08:45:00Z",
    completedAt: "2024-01-15T11:20:00Z",
    assignedTo: "Ernesto",
    feedback: {
      rating: 5,
      resolved: "yes",
      comments: "Excelente servicio, muy rápido y eficiente.",
    },
  },
]

let selectedTicketForFeedback = null
let currentRating = 0
const bootstrap = window.bootstrap // Declare the bootstrap variable

// Inicializar página
document.addEventListener("DOMContentLoaded", () => {
  updateSummaryCards()
  loadMyTickets()
  setupFeedbackHandlers()
})

function updateSummaryCards() {
  const totalTickets = userTickets.length
  const activeTickets = userTickets.filter((t) => !["cerrado", "liberado"].includes(t.status)).length
  const resolvedTickets = userTickets.filter((t) => ["cerrado", "atendido"].includes(t.status)).length
  const feedbackPending = userTickets.filter((t) => t.status === "liberado").length

  document.getElementById("totalTickets").textContent = totalTickets
  document.getElementById("activeTickets").textContent = activeTickets
  document.getElementById("resolvedTickets").textContent = resolvedTickets
  document.getElementById("feedbackPending").textContent = feedbackPending
}

function loadMyTickets() {
  const container = document.getElementById("myTicketsList")
  container.innerHTML = userTickets.map((ticket) => createTicketCard(ticket)).join("")
}

function createTicketCard(ticket) {
  const canGiveFeedback = ticket.status === "liberado"
  const hasFeedback = ticket.feedback

  return `
        <div class="card mb-3">
            <div class="card-body">
                <div class="d-flex justify-content-between align-items-start">
                    <div class="flex-grow-1">
                        <div class="d-flex align-items-center gap-2 mb-2">
                            <h6 class="mb-0">${ticket.title}</h6>
                            <span class="badge bg-outline-secondary">${ticket.type}</span>
                            <span class="badge ${getPriorityBadgeClass(ticket.priority)}">${ticket.priority}</span>
                        </div>
                        <p class="text-muted mb-2">${ticket.description}</p>
                        ${ticket.resolution ? `<p class="text-success mb-2"><i class="fas fa-check-circle me-1"></i><strong>Solución:</strong> ${ticket.resolution}</p>` : ""}
                        <small class="text-muted">
                            <i class="fas fa-clock me-1"></i>Creado: ${new Date(ticket.created).toLocaleString()}
                            ${ticket.completedAt ? `<br><i class="fas fa-check me-1"></i>Completado: ${new Date(ticket.completedAt).toLocaleString()}` : ""}
                            ${ticket.assignedTo ? `<br><i class="fas fa-user-check me-1"></i>Atendido por: ${ticket.assignedTo}` : ""}
                        </small>
                        ${
                          hasFeedback
                            ? `
                            <div class="mt-2 p-2 bg-light rounded">
                                <small class="text-success">
                                    <i class="fas fa-star me-1"></i>Calificación: ${generateStars(ticket.feedback.rating)}
                                    ${ticket.feedback.comments ? `<br><i class="fas fa-comment me-1"></i>"${ticket.feedback.comments}"` : ""}
                                </small>
                            </div>
                        `
                            : ""
                        }
                    </div>
                    <div class="d-flex flex-column align-items-end gap-2">
                        ${getStatusBadge(ticket.status)}
                        ${
                          canGiveFeedback
                            ? `
                            <button class="btn btn-warning btn-sm" onclick="openFeedbackModal(${ticket.id})">
                                <i class="fas fa-star me-1"></i>Calificar
                            </button>
                        `
                            : ""
                        }
                    </div>
                </div>
            </div>
        </div>
    `
}

function openFeedbackModal(ticketId) {
  selectedTicketForFeedback = userTickets.find((t) => t.id === ticketId)
  if (selectedTicketForFeedback) {
    document.getElementById("ticketSummary").innerHTML = `
            <h6 class="mb-2">${selectedTicketForFeedback.title}</h6>
            <p class="mb-2">${selectedTicketForFeedback.description}</p>
            <div class="d-flex gap-2">
                <span class="badge bg-outline-secondary">${selectedTicketForFeedback.type}</span>
                <span class="badge bg-success">Completado</span>
            </div>
            ${selectedTicketForFeedback.resolution ? `<p class="mt-2 mb-0"><strong>Solución:</strong> ${selectedTicketForFeedback.resolution}</p>` : ""}
        `

    // Resetear formulario
    currentRating = 0
    updateStarButtons()
    document.querySelectorAll('input[name="resolved"]').forEach((input) => (input.checked = false))
    document.getElementById("feedbackComments").value = ""
    document.getElementById("submitFeedbackBtn").disabled = true

    const modal = new bootstrap.Modal(document.getElementById("feedbackModal"))
    modal.show()
  }
}

function setupFeedbackHandlers() {
  // Manejar clicks en estrellas
  document.querySelectorAll(".star-btn").forEach((btn) => {
    btn.addEventListener("click", function () {
      currentRating = Number.parseInt(this.dataset.rating)
      updateStarButtons()
      checkFormValidity()
    })
  })

  // Manejar cambios en radio buttons
  document.querySelectorAll('input[name="resolved"]').forEach((input) => {
    input.addEventListener("change", checkFormValidity)
  })
}

function updateStarButtons() {
  document.querySelectorAll(".star-btn").forEach((btn, index) => {
    const rating = index + 1
    if (rating <= currentRating) {
      btn.classList.remove("btn-outline-warning")
      btn.classList.add("btn-warning")
    } else {
      btn.classList.remove("btn-warning")
      btn.classList.add("btn-outline-warning")
    }
  })
}

function checkFormValidity() {
  const hasRating = currentRating > 0
  const hasResolutionAnswer = document.querySelector('input[name="resolved"]:checked')
  const submitBtn = document.getElementById("submitFeedbackBtn")

  submitBtn.disabled = !(hasRating && hasResolutionAnswer)
}

function submitFeedback() {
  if (selectedTicketForFeedback && currentRating > 0) {
    const resolved = document.querySelector('input[name="resolved"]:checked').value
    const comments = document.getElementById("feedbackComments").value

    // Actualizar ticket con feedback
    selectedTicketForFeedback.feedback = {
      rating: currentRating,
      resolved: resolved,
      comments: comments,
      submittedAt: new Date().toISOString(),
    }
    selectedTicketForFeedback.status = "cerrado"

    // Actualizar interfaz
    updateSummaryCards()
    loadMyTickets()

    // Cerrar modal
    const modal = bootstrap.Modal.getInstance(document.getElementById("feedbackModal"))
    modal.hide()

    showNotification("¡Gracias por tu retroalimentación!", "success")
    selectedTicketForFeedback = null
  }
}

function generateStars(rating) {
  let stars = ""
  for (let i = 1; i <= 5; i++) {
    if (i <= rating) {
      stars += '<i class="fas fa-star text-warning"></i>'
    } else {
      stars += '<i class="far fa-star text-muted"></i>'
    }
  }
  return stars
}

function getPriorityBadgeClass(priority) {
  switch (priority) {
    case "baja":
      return "bg-success"
    case "media":
      return "bg-warning"
    case "alta":
      return "bg-danger"
    case "urgente":
      return "bg-dark"
    default:
      return "bg-secondary"
  }
}

function getStatusBadge(status) {
  const statusConfig = {
    creado: { class: "bg-secondary", icon: "fas fa-plus", text: "Creado" },
    leido: { class: "bg-info", icon: "fas fa-eye", text: "Leído" },
    "en-revision": { class: "bg-warning", icon: "fas fa-cog", text: "En Revisión" },
    atendido: { class: "bg-success", icon: "fas fa-check", text: "Atendido" },
    liberado: { class: "bg-primary", icon: "fas fa-paper-plane", text: "Listo para Calificar" },
    cerrado: { class: "bg-dark", icon: "fas fa-check-circle", text: "Cerrado" },
  }

  const config = statusConfig[status] || statusConfig["creado"]
  return `<span class="badge ${config.class}">
        <i class="${config.icon} me-1"></i>${config.text}
    </span>`
}

function showNotification(message, type = "info") {
  const notification = document.createElement("div")
  notification.className = `alert alert-${type} alert-dismissible fade show position-fixed`
  notification.style.cssText = "top: 20px; right: 20px; z-index: 9999; min-width: 300px;"
  notification.innerHTML = `
        ${message}
        <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
    `

  document.body.appendChild(notification)

  setTimeout(() => {
    if (notification.parentNode) {
      notification.parentNode.removeChild(notification)
    }
  }, 3000)
}
