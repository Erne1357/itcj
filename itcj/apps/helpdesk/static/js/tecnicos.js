// Datos de ejemplo para técnicos
const technicianTickets = [
  {
    id: 1,
    title: "Computadora no enciende en Aula 201",
    type: "Apoyo técnico",
    status: "leido",
    priority: "alta",
    created: "2024-01-16T10:30:00Z",
    user: "Ana García",
    department: "Sistemas Computacionales",
    location: "Aula 201",
    assignedTo: "Ernesto",
    description: "La computadora del profesor no enciende desde esta mañana.",
  },
  {
    id: 2,
    title: "Proyector sin imagen en Laboratorio",
    type: "Apoyo técnico",
    status: "en-revision",
    priority: "media",
    created: "2024-01-16T08:45:00Z",
    user: "María Rodríguez",
    department: "Electrónica",
    location: "Laboratorio de Electrónica",
    assignedTo: "Ernesto",
  },
  {
    id: 3,
    title: "Internet lento en área Industrial",
    type: "Apoyo técnico",
    status: "atendido",
    priority: "alta",
    created: "2024-01-15T16:20:00Z",
    user: "Roberto Martínez",
    department: "Industrial",
    location: "Edificio Industrial",
    assignedTo: "Ernesto",
    completedAt: "2024-01-16T14:30:00Z",
    timeSpent: 2.5,
    workNotes: "Se reinició el switch principal y se optimizó la configuración de red.",
  },
]

let selectedTicket = null
const bootstrap = window.bootstrap // Declare the bootstrap variable

// Inicializar página
document.addEventListener("DOMContentLoaded", () => {
  updateDashboardCounts()
  loadAssignedTickets()
  loadInProgressTickets()
  loadCompletedTickets()
})

function updateDashboardCounts() {
  const myTickets = technicianTickets.filter((t) => t.assignedTo === "Ernesto")
  const pendingTickets = myTickets.filter((t) => ["leido", "en-revision"].includes(t.status))
  const completedToday = myTickets.filter((t) => t.status === "atendido" && isToday(t.completedAt))

  document.getElementById("myTicketsCount").textContent = myTickets.length
  document.getElementById("pendingCount").textContent = pendingTickets.length
  document.getElementById("completedTodayCount").textContent = completedToday.length
}

function loadAssignedTickets() {
  const assignedTickets = technicianTickets.filter(
    (t) => t.assignedTo === "Ernesto" && ["leido", "creado"].includes(t.status),
  )

  const container = document.getElementById("assignedTicketsList")
  container.innerHTML = assignedTickets.map((ticket) => createTicketCard(ticket, true)).join("")
}

function loadInProgressTickets() {
  const inProgressTickets = technicianTickets.filter((t) => t.assignedTo === "Ernesto" && t.status === "en-revision")

  const container = document.getElementById("inProgressTicketsList")
  container.innerHTML = inProgressTickets.map((ticket) => createTicketCard(ticket, true)).join("")
}

function loadCompletedTickets() {
  const completedTickets = technicianTickets.filter(
    (t) => t.assignedTo === "Ernesto" && ["atendido", "liberado", "cerrado"].includes(t.status),
  )

  const container = document.getElementById("completedTicketsList")
  container.innerHTML = completedTickets.map((ticket) => createTicketCard(ticket, false)).join("")
}

function createTicketCard(ticket, showActions) {
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
                        <small class="text-muted">
                            <i class="fas fa-user me-1"></i>${ticket.user} • 
                            <i class="fas fa-building me-1"></i>${ticket.department} • 
                            <i class="fas fa-map-marker-alt me-1"></i>${ticket.location} • 
                            <i class="fas fa-clock me-1"></i>${new Date(ticket.created).toLocaleString()}
                        </small>
                        ${ticket.workNotes ? `<br><small class="text-success"><i class="fas fa-sticky-note me-1"></i>${ticket.workNotes}</small>` : ""}
                        ${ticket.timeSpent ? `<br><small class="text-info"><i class="fas fa-stopwatch me-1"></i>Tiempo: ${ticket.timeSpent}h</small>` : ""}
                    </div>
                    <div class="d-flex flex-column align-items-end gap-2">
                        ${getStatusBadge(ticket.status)}
                        ${
                          showActions
                            ? `<button class="btn btn-primary btn-sm" onclick="openTicketDetail(${ticket.id})">
                            <i class="fas fa-edit me-1"></i>Gestionar
                        </button>`
                            : ""
                        }
                    </div>
                </div>
            </div>
        </div>
    `
}

function openTicketDetail(ticketId) {
  selectedTicket = technicianTickets.find((t) => t.id === ticketId)
  if (selectedTicket) {
    document.getElementById("ticketDetailContent").innerHTML = `
            <div class="row">
                <div class="col-md-6">
                    <h6>Información del Ticket</h6>
                    <p><strong>Título:</strong> ${selectedTicket.title}</p>
                    <p><strong>Tipo:</strong> ${selectedTicket.type}</p>
                    <p><strong>Prioridad:</strong> ${selectedTicket.priority}</p>
                    <p><strong>Usuario:</strong> ${selectedTicket.user}</p>
                    <p><strong>Departamento:</strong> ${selectedTicket.department}</p>
                    <p><strong>Ubicación:</strong> ${selectedTicket.location}</p>
                </div>
                <div class="col-md-6">
                    <h6>Estado Actual</h6>
                    <p><strong>Estado:</strong> ${getStatusBadge(selectedTicket.status)}</p>
                    <p><strong>Creado:</strong> ${new Date(selectedTicket.created).toLocaleString()}</p>
                    ${selectedTicket.completedAt ? `<p><strong>Completado:</strong> ${new Date(selectedTicket.completedAt).toLocaleString()}</p>` : ""}
                </div>
            </div>
            <div class="mt-3">
                <h6>Descripción del Problema</h6>
                <p class="bg-light p-3 rounded">${selectedTicket.description}</p>
            </div>
        `

    // Pre-llenar campos si existen
    if (selectedTicket.workNotes) {
      document.getElementById("workNotes").value = selectedTicket.workNotes
    }
    if (selectedTicket.timeSpent) {
      document.getElementById("timeSpent").value = selectedTicket.timeSpent
    }

    const modal = new bootstrap.Modal(document.getElementById("ticketDetailModal"))
    modal.show()
  }
}

function updateTicketStatus(newStatus) {
  if (selectedTicket) {
    selectedTicket.status = newStatus

    if (newStatus === "atendido" || newStatus === "liberado") {
      selectedTicket.completedAt = new Date().toISOString()
    }

    // Actualizar interfaz
    updateDashboardCounts()
    loadAssignedTickets()
    loadInProgressTickets()
    loadCompletedTickets()

    showNotification(`Ticket marcado como: ${getStatusText(newStatus)}`, "success")
  }
}

function saveTicketUpdate() {
  if (selectedTicket) {
    const workNotes = document.getElementById("workNotes").value
    const timeSpent = Number.parseFloat(document.getElementById("timeSpent").value) || 0

    selectedTicket.workNotes = workNotes
    selectedTicket.timeSpent = timeSpent

    // Actualizar interfaz
    loadAssignedTickets()
    loadInProgressTickets()
    loadCompletedTickets()

    // Cerrar modal
    const modal = bootstrap.Modal.getInstance(document.getElementById("ticketDetailModal"))
    modal.hide()

    showNotification("Información del ticket actualizada", "success")
  }
}

function getStatusText(status) {
  const statusTexts = {
    creado: "Creado",
    leido: "Leído",
    "en-revision": "En Revisión",
    atendido: "Atendido",
    liberado: "Liberado",
    cerrado: "Cerrado",
  }
  return statusTexts[status] || status
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
    liberado: { class: "bg-primary", icon: "fas fa-paper-plane", text: "Liberado" },
    cerrado: { class: "bg-dark", icon: "fas fa-check-circle", text: "Cerrado" },
  }

  const config = statusConfig[status] || statusConfig["creado"]
  return `<span class="badge ${config.class}">
        <i class="${config.icon} me-1"></i>${config.text}
    </span>`
}

function isToday(dateString) {
  if (!dateString) return false
  const date = new Date(dateString)
  const today = new Date()
  return date.toDateString() === today.toDateString()
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
