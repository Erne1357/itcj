// SITEC - Sistema Integral de Tickets del Centro de Cómputo ITCJ

// Función principal para pedir ayuda
function pedirAyuda() {
  // Esta función será manejada por Flask para redirigir según el rol del usuario
  // Por ejemplo: window.location.href = '/SITEC/user/crear-ticket';

  // Animación del botón
  const btn = event.target
  btn.classList.add("loading")
  btn.innerHTML = '<i class="fas fa-spinner fa-spin me-2"></i>Cargando...'

  // Simular redirección (esto lo manejarás con Flask)
  setTimeout(() => {
    // window.location.href = '/SITEC/user/crear-ticket';
    console.log("Redirigiendo a crear ticket...")
    btn.classList.remove("loading")
    btn.innerHTML = '<i class="fas fa-plus me-2"></i>Pedir Ayuda'
  }, 1000)
}

// Datos de ejemplo para tickets (para usar con Jinja2)
const ticketsEjemplo = [
  {
    id: "TK-2024-001",
    titulo: "Computadora no enciende en Aula 101",
    tipo: "Apoyo Técnico",
    categoria: "Computadoras",
    descripcion:
      "La computadora del escritorio del profesor no enciende, se escucha un pitido cuando se presiona el botón de encendido.",
    prioridad: "Alta",
    estado: "Creado",
    solicitante: "María González",
    departamento: "Sistemas Computacionales",
    fecha_creacion: "2024-01-15 09:30:00",
    fecha_lectura: null,
    fecha_asignacion: null,
    fecha_atencion: null,
    fecha_cierre: null,
    asignado_a: null,
    tecnico_asignado: null,
    tiempo_respuesta: null,
    tiempo_resolucion: null,
    comentarios: [],
    archivos_adjuntos: [],
  },
  {
    id: "TK-2024-002",
    titulo: "No puedo acceder al SII",
    tipo: "Software",
    categoria: "SII",
    descripcion:
      "Al intentar ingresar al Sistema Integral de Información me aparece error de conexión. He intentado desde diferentes navegadores.",
    prioridad: "Media",
    estado: "En Revisión",
    solicitante: "Carlos Ramírez",
    departamento: "Administración",
    fecha_creacion: "2024-01-14 14:20:00",
    fecha_lectura: "2024-01-14 14:25:00",
    fecha_asignacion: "2024-01-14 15:00:00",
    fecha_atencion: "2024-01-15 08:00:00",
    fecha_cierre: null,
    asignado_a: "Desarrollo",
    tecnico_asignado: "Ernesto López",
    tiempo_respuesta: "5 minutos",
    tiempo_resolucion: null,
    comentarios: [
      {
        autor: "Secretaría",
        fecha: "2024-01-14 15:00:00",
        mensaje: "Ticket asignado al equipo de Desarrollo para revisión del SII.",
      },
      {
        autor: "Ernesto López",
        fecha: "2024-01-15 08:00:00",
        mensaje: "Revisando conectividad con la base de datos del SII.",
      },
    ],
    archivos_adjuntos: ["screenshot_error_sii.png"],
  },
  {
    id: "TK-2024-003",
    titulo: "Proyector no funciona en Aula Magna",
    tipo: "Apoyo Técnico",
    categoria: "Proyectores",
    descripcion:
      "El proyector del Aula Magna no muestra imagen, solo se ve una pantalla azul. El cable HDMI está conectado correctamente.",
    prioridad: "Urgente",
    estado: "Atendido",
    solicitante: "Ana Martínez",
    departamento: "Dirección Académica",
    fecha_creacion: "2024-01-13 10:15:00",
    fecha_lectura: "2024-01-13 10:18:00",
    fecha_asignacion: "2024-01-13 10:30:00",
    fecha_atencion: "2024-01-13 11:00:00",
    fecha_cierre: "2024-01-13 12:30:00",
    asignado_a: "Javier Hernández",
    tecnico_asignado: "Javier Hernández",
    tiempo_respuesta: "3 minutos",
    tiempo_resolucion: "2 horas 15 minutos",
    comentarios: [
      {
        autor: "Secretaría",
        fecha: "2024-01-13 10:30:00",
        mensaje: "Ticket asignado a Javier por ser urgente.",
      },
      {
        autor: "Javier Hernández",
        fecha: "2024-01-13 11:00:00",
        mensaje: "Revisando conexiones y configuración del proyector.",
      },
      {
        autor: "Javier Hernández",
        fecha: "2024-01-13 12:30:00",
        mensaje: "Problema resuelto. Era un cable HDMI defectuoso. Se reemplazó el cable.",
      },
    ],
    archivos_adjuntos: [],
    solucion: "Se reemplazó el cable HDMI defectuoso por uno nuevo. El proyector ahora funciona correctamente.",
    materiales_utilizados: ["Cable HDMI nuevo"],
    tiempo_trabajo: "1 hora 30 minutos",
  },
]

// Datos de ejemplo para usuarios
const usuariosEjemplo = [
  {
    id: 1,
    nombre: "María González",
    email: "maria.gonzalez@itcj.edu.mx",
    departamento: "Sistemas Computacionales",
    rol: "Docente",
    activo: true,
    fecha_registro: "2024-01-10",
  },
  {
    id: 2,
    nombre: "Carlos Ramírez",
    email: "carlos.ramirez@itcj.edu.mx",
    departamento: "Administración",
    rol: "Administrativo",
    activo: true,
    fecha_registro: "2024-01-08",
  },
  {
    id: 3,
    nombre: "Ana Martínez",
    email: "ana.martinez@itcj.edu.mx",
    departamento: "Dirección Académica",
    rol: "Directivo",
    activo: true,
    fecha_registro: "2024-01-05",
  },
]

// Datos de ejemplo para técnicos
const tecnicosEjemplo = [
  {
    id: 1,
    nombre: "Ernesto López",
    email: "ernesto.lopez@itcj.edu.mx",
    area: "Desarrollo",
    especialidad: "Software",
    activo: true,
    tickets_asignados: 5,
    tickets_resueltos: 23,
    tiempo_promedio_resolucion: "4.2 horas",
  },
  {
    id: 2,
    nombre: "Javier Hernández",
    email: "javier.hernandez@itcj.edu.mx",
    area: "Apoyo Técnico",
    especialidad: "Hardware",
    activo: true,
    tickets_asignados: 3,
    tickets_resueltos: 18,
    tiempo_promedio_resolucion: "2.8 horas",
  },
  {
    id: 3,
    nombre: "Héctor Morales",
    email: "hector.morales@itcj.edu.mx",
    area: "Apoyo Técnico",
    especialidad: "Redes",
    activo: true,
    tickets_asignados: 2,
    tickets_resueltos: 15,
    tiempo_promedio_resolucion: "3.5 horas",
  },
]

// Datos de ejemplo para estadísticas
const estadisticasEjemplo = {
  tickets_totales: 156,
  tickets_abiertos: 23,
  tickets_en_proceso: 8,
  tickets_cerrados: 125,
  tiempo_promedio_respuesta: "15 minutos",
  tiempo_promedio_resolucion: "3.2 horas",
  satisfaccion_promedio: 4.6,
  tickets_por_tipo: {
    "Apoyo Técnico": 89,
    Software: 67,
  },
  tickets_por_prioridad: {
    Baja: 45,
    Media: 78,
    Alta: 28,
    Urgente: 5,
  },
  tickets_por_departamento: {
    "Sistemas Computacionales": 34,
    Administración: 28,
    "Dirección Académica": 22,
    "Recursos Humanos": 18,
    Otros: 54,
  },
  rendimiento_tecnicos: [
    {
      nombre: "Ernesto López",
      tickets_resueltos: 23,
      tiempo_promedio: "4.2 horas",
      satisfaccion: 4.8,
    },
    {
      nombre: "Javier Hernández",
      tickets_resueltos: 18,
      tiempo_promedio: "2.8 horas",
      satisfaccion: 4.5,
    },
    {
      nombre: "Héctor Morales",
      tickets_resueltos: 15,
      tiempo_promedio: "3.5 horas",
      satisfaccion: 4.4,
    },
  ],
}

// Funciones utilitarias
function formatearFecha(fecha) {
  if (!fecha) return "N/A"
  const date = new Date(fecha)
  return date.toLocaleDateString("es-MX", {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  })
}

function calcularTiempoTranscurrido(fechaInicio) {
  if (!fechaInicio) return "N/A"
  const inicio = new Date(fechaInicio)
  const ahora = new Date()
  const diferencia = ahora - inicio

  const horas = Math.floor(diferencia / (1000 * 60 * 60))
  const minutos = Math.floor((diferencia % (1000 * 60 * 60)) / (1000 * 60))

  if (horas > 24) {
    const dias = Math.floor(horas / 24)
    return `${dias} día${dias > 1 ? "s" : ""}`
  } else if (horas > 0) {
    return `${horas}h ${minutos}m`
  } else {
    return `${minutos}m`
  }
}

function obtenerClaseEstado(estado) {
  const clases = {
    Creado: "status-creado",
    Leído: "status-leido",
    "En Revisión": "status-en-revision",
    Atendido: "status-atendido",
    Liberado: "status-liberado",
    Cerrado: "status-cerrado",
  }
  return clases[estado] || "status-creado"
}

function obtenerClasePrioridad(prioridad) {
  const clases = {
    Baja: "priority-baja",
    Media: "priority-media",
    Alta: "priority-alta",
    Urgente: "priority-urgente",
  }
  return clases[prioridad] || "priority-media"
}

// Animaciones
function animarEnvioTicket(elemento) {
  elemento.classList.add("ticket-send-animation")
  setTimeout(() => {
    elemento.style.display = "none"
  }, 1200)
}

function mostrarNotificacion(mensaje, tipo = "success") {
  // Crear elemento de notificación
  const notificacion = document.createElement("div")
  notificacion.className = `alert alert-${tipo} alert-dismissible fade show position-fixed`
  notificacion.style.cssText = "top: 20px; right: 20px; z-index: 9999; min-width: 300px;"
  notificacion.innerHTML = `
        ${mensaje}
        <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
    `

  document.body.appendChild(notificacion)

  // Auto-remover después de 5 segundos
  setTimeout(() => {
    if (notificacion.parentNode) {
      notificacion.remove()
    }
  }, 5000)
}

// Inicialización
document.addEventListener("DOMContentLoaded", () => {
  // Agregar animaciones de entrada
  const elementos = document.querySelectorAll(".sitec-help-card, .sitec-service-card")
  elementos.forEach((elemento, index) => {
    setTimeout(() => {
      elemento.classList.add("slide-in-up")
    }, index * 200)
  })
})

// Exportar datos para uso con Jinja2
window.SITEC_DATA = {
  tickets: ticketsEjemplo,
  usuarios: usuariosEjemplo,
  tecnicos: tecnicosEjemplo,
  estadisticas: estadisticasEjemplo,
}
