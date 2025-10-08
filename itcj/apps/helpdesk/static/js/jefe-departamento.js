// Datos de ejemplo para jefe de departamento
const departmentUsers = [
  { id: 1, name: "Ana García", email: "ana.garcia@itcj.edu.mx", role: "Docente", active: true },
  { id: 2, name: "Carlos López", email: "carlos.lopez@itcj.edu.mx", role: "Coordinador", active: true },
  { id: 3, name: "María Rodríguez", email: "maria.rodriguez@itcj.edu.mx", role: "Docente", active: false },
]

const departmentTickets = [
  {
    id: 1,
    title: "Problema con proyector Aula 201",
    type: "Apoyo técnico",
    status: "en-revision",
    created: "2024-01-15",
    user: "Ana García",
  },
  {
    id: 2,
    title: "Acceso al SIISAE",
    type: "Software",
    status: "atendido",
    created: "2024-01-14",
    user: "Carlos López",
  },
  {
    id: 3,
    title: "Internet lento en laboratorio",
    type: "Apoyo técnico",
    status: "creado",
    created: "2024-01-16",
    user: "María Rodríguez",
  },
]

// Importar Bootstrap
const bootstrap = window.bootstrap

// Inicializar página
document.addEventListener("DOMContentLoaded", () => {
  loadDepartmentUsers()
  loadDepartmentTickets()
  setupFormHandlers()
})

function loadDepartmentUsers() {
  const container = document.getElementById("departmentUsersList")
  container.innerHTML = departmentUsers
    .map(
      (user) => `
        <div class="d-flex justify-content-between align-items-center p-3 border rounded mb-3">
            <div class="d-flex align-items-center gap-3">
                <div class="bg-primary bg-opacity-10 rounded-circle p-2">
                    <i class="fas fa-user text-primary"></i>
                </div>
                <div>
                    <div class="fw-bold">${user.name}</div>
                    <small class="text-muted">${user.email}</small>
                </div>
            </div>
            <div class="d-flex align-items-center gap-2">
                <span class="badge bg-outline-secondary">${user.role}</span>
                <span class="badge ${user.active ? "bg-success" : "bg-secondary"}">
                    ${user.active ? "Activo" : "Inactivo"}
                </span>
            </div>
        </div>
    `,
    )
    .join("")
}

function loadDepartmentTickets() {
  const container = document.getElementById("departmentTicketsList")
  container.innerHTML = departmentTickets
    .map(
      (ticket) => `
        <div class="d-flex justify-content-between align-items-center p-3 border rounded mb-3">
            <div class="flex-grow-1">
                <div class="d-flex align-items-center gap-2 mb-2">
                    <h6 class="mb-0">${ticket.title}</h6>
                    <span class="badge bg-outline-secondary">${ticket.type}</span>
                </div>
                <small class="text-muted">
                    Por ${ticket.user} • ${ticket.created}
                </small>
            </div>
            ${getStatusBadge(ticket.status)}
        </div>
    `,
    )
    .join("")
}

function setupFormHandlers() {
  // Manejar cambio de tipo de ticket
  const ticketTypeSelect = document.getElementById("ticketType")
  const softwareSelect = document.getElementById("softwareSelect")

  if (ticketTypeSelect) {
    ticketTypeSelect.addEventListener("change", function () {
      if (this.value === "Software") {
        softwareSelect.style.display = "block"
      } else {
        softwareSelect.style.display = "none"
      }
    })
  }
}

function createUser() {
  const name = document.getElementById("userName").value
  const email = document.getElementById("userEmail").value
  const role = document.getElementById("userRole").value

  if (name && email && role) {
    const newUser = {
      id: departmentUsers.length + 1,
      name: name,
      email: email,
      role: role,
      active: true,
    }

    departmentUsers.push(newUser)
    loadDepartmentUsers()

    // Cerrar modal y limpiar formulario
    const modal = bootstrap.Modal.getInstance(document.getElementById("createUserModal"))
    modal.hide()
    document.getElementById("createUserForm").reset()

    showNotification("Usuario creado exitosamente", "success")
  }
}

function createTicket() {
  const title = document.getElementById("ticketTitle").value
  const type = document.getElementById("ticketType").value
  const priority = document.getElementById("ticketPriority").value
  const description = document.getElementById("ticketDescription").value
  const software = document.getElementById("ticketSoftware").value

  if (title && type && priority && description) {
    const newTicket = {
      id: departmentTickets.length + 1,
      title: title,
      type: type,
      status: "creado",
      priority: priority,
      created: new Date().toISOString().split("T")[0],
      user: "Jefe de Departamento", // En una app real, sería el usuario actual
      description: description,
      software: software,
    }

    departmentTickets.push(newTicket)
    loadDepartmentTickets()

    // Cerrar modal y limpiar formulario
    const modal = bootstrap.Modal.getInstance(document.getElementById("createTicketModal"))
    modal.hide()
    document.getElementById("createTicketForm").reset()
    document.getElementById("softwareSelect").style.display = "none"

    showNotification("Ticket creado exitosamente", "success")
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
