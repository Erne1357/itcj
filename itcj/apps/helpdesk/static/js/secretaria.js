// Datos de ejemplo para secretaría
const secretaryTickets = [
  {
    id: 1,
    title: "Computadora no enciende en Aula 201",
    type: "Apoyo técnico",
    status: "creado",
    priority: "alta",
    created: "2024-01-16T10:30:00Z",
    user: "Ana García",
    department: "Sistemas Computacionales",
    location: "Aula 201",
    category: "computadoras",
    urgency: true,
    description: "La computadora del profesor no enciende desde esta mañana. Hay clase en 2 horas.",
  },
  {
    id: 2,
    title: "Error al acceder al SIISAE",
    type: "Software",
    status: "creado",
    priority: "media",
    created: "2024-01-16T09:15:00Z",
    user: "Carlos López",
    department: "Administración",
    location: "Oficina Administrativa",
    software: "SIISAE",
    description: "No puedo acceder al sistema para capturar calificaciones.",
  },
  {
    id: 3,
    title: "Proyector sin imagen en Laboratorio",
    type: "Apoyo técnico",
    status: "leido",
    priority: "media",
    created: "2024-01-16T08:45:00Z",
    user: "María Rodríguez",
    department: "Electrónica",
    location: "Laboratorio de Electrónica",
    assignedTo: "Ernesto",
  },
]

const technicians = [
  { id: "ernesto", name: "Ernesto", area: "Apoyo Técnico", status: "disponible", activeTickets: 3 },
  { id: "javier", name: "Javier", area: "Desarrollo", status: "ocupado", activeTickets: 5 },
  { id: "hector", name: "Héctor", area: "Desarrollo", status: "disponible", activeTickets: 2 },
  { id: "desarrollo", name: "Equipo Desarrollo", area: "Desarrollo", status: "disponible", activeTickets: 8 },
]

const residents = [
  { id: "resident1", name: "Andrea Sánchez", supervisor: "Ernesto", activeTickets: 2 },
  { id: "resident2", name: "Miguel Torres", supervisor: "Ernesto", activeTickets: 1 },
]

let selectedTicketForAssignment = null

// Inicializar página
document.addEventListener("DOMContentLoaded", () => {
  updateDashboardCounts()
  loadTicketsList()
  loadTechniciansList()
  loadResidentsList()
  checkUrgentTickets()
})

function updateDashboardCounts() {
  const urgentTickets = secretaryTickets.filter((t) => t.urgency || t.priority === "urgente")
  const unassignedTickets = secretaryTickets.filter((t) => !t.assignedTo)
  const inProgressTickets = secretaryTickets.filter((t) => t.status === "en-revision")

  document.getElementById("urgentTicketsCount").textContent = urgentTickets.length
  document.getElementById("unassignedCount").textContent = unassignedTickets.length
  document.getElementById("inProgressCount").textContent = inProgressTickets.length
  document.getElementById("totalTodayCount").textContent = secretaryTickets.length

  // Mostrar badge de urgentes si hay tickets urgentes
  const urgentBadge = document.getElementById("urgentBadge")
  if (urgentTickets.length > 0) {
    urgentBadge.style.display = "inline-block"
    document.getElementById("urgentCount").textContent = urgentTickets.length
  }
}

function checkUrgentTickets() {
  const urgentTickets = secretaryTickets.filter((t) => t.urgency || t.priority === "urgente")
  const urgentAlert = document.getElementById("urgentAlert")
  const urgentTicketsList = document.getElementById("urgentTicketsList")

  if (urgentTickets.length > 0) {
    urgentAlert.classList.remove("d-none")
    urgentTicketsList.innerHTML = urgentTickets
      .map(
        (ticket) => `
            <div class="d-flex justify-content-between align-items-center p-3 bg-white rounded border mb-2">
                <div class="flex-grow-1">
                    <h6 class="mb-1">${ticket.title}</h6>
                    <small class="text-muted">
                        ${ticket.user} • ${ticket.location} • ${new Date(ticket.created).toLocaleTimeString()}
                    </small>
                </div>
                <div class="d-flex align-items-center gap-2">
                    ${getStatusBadge(ticket.status)}
                    <button class="btn btn-danger btn-sm" onclick="openAssignmentModal(${ticket.id})">
                        Asignar Ahora
                    </button>
                </div>
            </div>
        `,
      )
      .join("")
  }
}

function loadTicketsList() {
  const ticketsList = document.getElementById("ticketsList")
  ticketsList.innerHTML = secretaryTickets
    .map(
      (ticket) => `
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
                        ${ticket.assignedTo ? `<br><small class="text-success"><i class="fas fa-user-check me-1"></i>Asignado a: ${ticket.assignedTo}</small>` : ""}
                    </div>
                    <div class="d-flex flex-column align-items-end gap-2">
                        ${getStatusBadge(ticket.status)}
                        ${
                          !ticket.assignedTo
                            ? `<button class="btn btn-primary btn-sm" onclick="openAssignmentModal(${ticket.id})">
                            <i class="fas fa-user-plus me-1"></i>Asignar
                        </button>`
                            : ""
                        }
                    </div>
                </div>
            </div>
        </div>
    `,
    )
    .join("")
}

function loadTechniciansList() {
  const techniciansList = document.getElementById("techniciansList")
  techniciansList.innerHTML = technicians
    .map(
      (tech) => `
        <div class="d-flex justify-content-between align-items-center p-3 border rounded mb-3">
            <div class="d-flex align-items-center gap-3">
                <div class="bg-primary bg-opacity-10 rounded-circle p-2">
                    <i class="fas fa-user text-primary"></i>
                </div>
                <div>
                    <div class="fw-bold">${tech.name}</div>
                    <small class="text-muted">${tech.area}</small>
                </div>
            </div>
            <div class="d-flex align-items-center gap-2">
                <span class="badge ${tech.status === "disponible" ? "bg-success" : "bg-secondary"}">${tech.status}</span>
                <span class="badge bg-outline-primary">${tech.activeTickets} tickets</span>
            </div>
        </div>
    `,
    )
    .join("")
}

function loadResidentsList() {
  const residentsList = document.getElementById("residentsList")
  residentsList.innerHTML = residents
    .map(
      (resident) => `
        <div class="d-flex justify-content-between align-items-center p-3 border rounded mb-3">
            <div class="d-flex align-items-center gap-3">
                <div class="bg-info bg-opacity-10 rounded-circle p-2">
                    <i class="fas fa-user-graduate text-info"></i>
                </div>
                <div>
                    <div class="fw-bold">${resident.name}</div>
                    <small class="text-muted">Supervisor: ${resident.supervisor}</small>
                </div>
            </div>
            <div class="d-flex align-items-center gap-2">
                <span class="badge bg-outline-info">${resident.activeTickets} tickets</span>
                <button class="btn btn-outline-secondary btn-sm">Ver Detalle</button>
            </div>
        </div>
    `,
    )
    .join("")
}

function openAssignmentModal(ticketId) {
  selectedTicketForAssignment = secretaryTickets.find((t) => t.id === ticketId)
  if (selectedTicketForAssignment) {
    document.getElementById("selectedTicketInfo").innerHTML = `
            <h6 class="mb-2">${selectedTicketForAssignment.title}</h6>
            <p class="mb-2">${selectedTicketForAssignment.user} • ${selectedTicketForAssignment.location}</p>
            <div class="d-flex gap-2">
                <span class="badge bg-outline-secondary">${selectedTicketForAssignment.type}</span>
                <span class="badge ${getPriorityBadgeClass(selectedTicketForAssignment.priority)}">${selectedTicketForAssignment.priority}</span>
            </div>
        `

    const modal = window.bootstrap.Modal(document.getElementById("assignmentModal"))
    modal.show()
  }
}

function assignTicket() {
  const assignee = document.getElementById("assigneeSelect").value
  const notes = document.getElementById("assignmentNotes").value

  if (assignee && selectedTicketForAssignment) {
    // Actualizar el ticket
    selectedTicketForAssignment.assignedTo = assignee
    selectedTicketForAssignment.status = "leido"
    selectedTicketForAssignment.assignmentNotes = notes

    // Actualizar la interfaz
    updateDashboardCounts()
    loadTicketsList()
    checkUrgentTickets()

    // Cerrar modal
    const modal = window.bootstrap.Modal.getInstance(document.getElementById("assignmentModal"))
    modal.hide()

    // Limpiar formulario
    document.getElementById("assigneeSelect").value = ""
    document.getElementById("assignmentNotes").value = ""
    selectedTicketForAssignment = null

    // Mostrar notificación
    showNotification("Ticket asignado exitosamente", "success")
  }
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

function showNotification(message, type = "info") {
  // Crear notificación temporal
  const notification = document.createElement("div")
  notification.className = `alert alert-${type} alert-dismissible fade show position-fixed`
  notification.style.cssText = "top: 20px; right: 20px; z-index: 9999; min-width: 300px;"
  notification.innerHTML = `
        ${message}
        <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
    `

  document.body.appendChild(notification)

  // Auto-remover después de 3 segundos
  setTimeout(() => {
    if (notification.parentNode) {
      notification.parentNode.removeChild(notification)
    }
  }, 3000)
}
