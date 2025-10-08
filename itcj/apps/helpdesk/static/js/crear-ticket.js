// JavaScript para el formulario de crear ticket

let pasoActual = 1
const totalPasos = 3

// Categorías por tipo
const categorias = {
  tecnico: [
    "Computadoras",
    "Proyectores",
    "Impresoras",
    "Internet/Red",
    "Cableado",
    "Monitores",
    "Teclados/Mouse",
    "Audio/Sonido",
    "Otros equipos",
  ],
  software: [
    "SII",
    "SIISAE",
    "SIILE",
    "Office (Word, Excel, PowerPoint)",
    "AutoCAD",
    "Moodle",
    "Navegadores web",
    "Antivirus",
    "Otros programas",
  ],
}

function seleccionarTipo(tipo) {
  // Remover selección anterior
  document.querySelectorAll(".tipo-ticket-card .card").forEach((card) => {
    card.classList.remove("border-primary", "bg-primary", "text-white")
    card.classList.add("border-2")
  })

  // Seleccionar nuevo tipo
  const card = event.currentTarget.querySelector(".card")
  card.classList.add("border-primary", "bg-primary", "text-white")

  // Guardar tipo seleccionado
  document.getElementById("tipoTicket").value = tipo

  // Actualizar categorías
  actualizarCategorias(tipo)

  // Habilitar botón siguiente
  document.getElementById("btnSiguiente").disabled = false
}

function actualizarCategorias(tipo) {
  const selectCategoria = document.getElementById("categoria")
  selectCategoria.innerHTML = '<option value="">Selecciona una opción...</option>'

  categorias[tipo].forEach((categoria) => {
    const option = document.createElement("option")
    option.value = categoria
    option.textContent = categoria
    selectCategoria.appendChild(option)
  })
}

function siguientePaso() {
  if (validarPasoActual()) {
    if (pasoActual < totalPasos) {
      pasoActual++
      mostrarPaso(pasoActual)

      if (pasoActual === 3) {
        mostrarResumen()
      }
    }
  }
}

function anteriorPaso() {
  if (pasoActual > 1) {
    pasoActual--
    mostrarPaso(pasoActual)
  }
}

function mostrarPaso(paso) {
  // Ocultar todos los pasos
  document.querySelectorAll(".step-content").forEach((content) => {
    content.classList.add("d-none")
  })

  // Mostrar paso actual
  document.getElementById(`step${paso}`).classList.remove("d-none")

  // Actualizar indicadores
  document.querySelectorAll(".step-indicator").forEach((indicator, index) => {
    if (index < paso) {
      indicator.classList.add("active")
    } else {
      indicator.classList.remove("active")
    }
  })

  // Actualizar botones
  const btnAnterior = document.getElementById("btnAnterior")
  const btnSiguiente = document.getElementById("btnSiguiente")
  const btnEnviar = document.getElementById("btnEnviar")

  btnAnterior.style.display = paso > 1 ? "block" : "none"
  btnSiguiente.style.display = paso < totalPasos ? "block" : "none"
  btnEnviar.style.display = paso === totalPasos ? "block" : "none"
}

function validarPasoActual() {
  switch (pasoActual) {
    case 1:
      const tipo = document.getElementById("tipoTicket").value
      if (!tipo) {
        mostrarNotificacion("Por favor selecciona el tipo de problema", "warning")
        return false
      }
      return true

    case 2:
      const categoria = document.getElementById("categoria").value
      const titulo = document.getElementById("titulo").value.trim()
      const descripcion = document.getElementById("descripcion").value.trim()

      if (!categoria) {
        mostrarNotificacion("Por favor selecciona una categoría", "warning")
        return false
      }
      if (!titulo) {
        mostrarNotificacion("Por favor escribe un título para el problema", "warning")
        return false
      }
      if (!descripcion) {
        mostrarNotificacion("Por favor describe el problema", "warning")
        return false
      }
      return true

    default:
      return true
  }
}

function mostrarResumen() {
  const tipo = document.getElementById("tipoTicket").value
  const categoria = document.getElementById("categoria").value
  const titulo = document.getElementById("titulo").value
  const descripcion = document.getElementById("descripcion").value
  const prioridad = document.querySelector('input[name="prioridad"]:checked').value
  const ubicacion = document.getElementById("ubicacion").value

  const tipoTexto = tipo === "tecnico" ? "Apoyo Técnico" : "Software"

  const resumen = `
        <h5 class="mb-3"><i class="fas fa-clipboard-list me-2"></i>Resumen del Ticket</h5>
        <div class="row g-3">
            <div class="col-md-6">
                <strong>Tipo:</strong><br>
                <span class="badge bg-primary">${tipoTexto}</span>
            </div>
            <div class="col-md-6">
                <strong>Categoría:</strong><br>
                <span class="badge bg-secondary">${categoria}</span>
            </div>
            <div class="col-12">
                <strong>Título:</strong><br>
                ${titulo}
            </div>
            <div class="col-12">
                <strong>Descripción:</strong><br>
                ${descripcion}
            </div>
            <div class="col-md-6">
                <strong>Prioridad:</strong><br>
                <span class="badge priority-${prioridad.toLowerCase()}">${prioridad}</span>
            </div>
            ${
              ubicacion
                ? `
            <div class="col-md-6">
                <strong>Ubicación:</strong><br>
                ${ubicacion}
            </div>
            `
                : ""
            }
        </div>
    `

  document.getElementById("resumenTicket").innerHTML = resumen
}

function mostrarNotificacion(mensaje, tipo) {
  // Implementación de mostrarNotificacion
  console.log(`Notificación (${tipo}): ${mensaje}`)
}

// Manejar envío del formulario
document.getElementById("ticketForm").addEventListener("submit", (e) => {
  e.preventDefault()

  // Animación de envío
  const ticketPreview = document.getElementById("ticketPreview")
  ticketPreview.classList.add("ticket-send-animation")

  // Deshabilitar botón
  const btnEnviar = document.getElementById("btnEnviar")
  btnEnviar.disabled = true
  btnEnviar.innerHTML = '<i class="fas fa-spinner fa-spin me-2"></i>Enviando...'

  // Simular envío (aquí iría la lógica de Flask)
  setTimeout(() => {
    mostrarNotificacion("¡Ticket enviado exitosamente! Te notificaremos cuando sea asignado.", "success")

    // Redirigir después de un momento
    setTimeout(() => {
      window.location.href = "/SITEC/user/mis-tickets"
    }, 2000)
  }, 1500)
})

// Agregar estilos CSS adicionales
const estilosAdicionales = `
<style>
.step-indicator {
    position: relative;
}

.step-number {
    width: 40px;
    height: 40px;
    border-radius: 50%;
    background: #e9ecef;
    color: #6c757d;
    display: flex;
    align-items: center;
    justify-content: center;
    font-weight: bold;
    margin: 0 auto 8px;
    transition: all 0.3s ease;
}

.step-indicator.active .step-number {
    background: var(--sitec-primary);
    color: white;
}

.step-text {
    color: #6c757d;
    font-weight: 500;
}

.step-indicator.active .step-text {
    color: var(--sitec-primary);
    font-weight: 600;
}

.tipo-ticket-card .card {
    cursor: pointer;
    transition: all 0.3s ease;
}

.tipo-ticket-card .card:hover {
    transform: translateY(-5px);
    box-shadow: 0 8px 25px rgba(0,0,0,0.1);
}

.tipo-icon {
    transition: transform 0.3s ease;
}

.tipo-ticket-card:hover .tipo-icon {
    transform: scale(1.1);
}

.ejemplos-tipo {
    background: rgba(0,0,0,0.05);
    padding: 10px;
    border-radius: 8px;
    margin-top: 10px;
}

.ticket-preview {
    transition: all 0.3s ease;
}

.ticket-preview:hover {
    transform: scale(1.05);
}
</style>
`

document.head.insertAdjacentHTML("beforeend", estilosAdicionales)

// Inicialización
document.addEventListener("DOMContentLoaded", () => {
  mostrarPaso(1)
  document.getElementById("btnSiguiente").disabled = true
})
