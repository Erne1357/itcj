# VisteTec — Reciclaje de Ropa y Gestion de Despensa

## Descripcion

**VisteTec** es el sistema de economia circular del ITCJ. Facilita la donacion, distribucion y reciclaje de prendas de vestir entre la comunidad estudiantil, con un sistema adicional de gestion de despensa mediante campanas de recoleccion. El objetivo es promover la sustentabilidad y el apoyo comunitario dentro del instituto.

---

## Roles

| Rol | Descripcion |
|---|---|
| `student` | Navega el catalogo, agenda citas, registra sus donaciones |
| `volunteer` | Gestiona prendas, atiende citas, registra donaciones, administra despensa |
| `admin` | Control completo: catalogo, citas, donaciones, despensa, reportes, campanas |

---

## Caracteristicas Principales

### Catalogo de Prendas

- Galeria publica de prendas disponibles con filtros por categoria, talla y condicion
- Compresion automatica de imagenes en cliente (Canvas API) y servidor (Pillow, JPEG 85%, max 1920px)
- Tamano maximo por imagen: 3 MB (antes de compresion)
- Extensiones permitidas: `jpg`, `jpeg`, `png`, `webp`

### Sistema de Citas

- Estudiante selecciona una prenda disponible y elige un slot de tiempo
- Slots organizados por dia con acordeones colapsables
- Opcion de declarar si traeran una donacion al recoger
- Gestion de citas por voluntarios: confirmar asistencia, registrar recepcion

### Donaciones

- Registro de donaciones de ropa: por cita o de forma independiente
- Registro de donaciones de despensa: vinculadas a una campana
- Busqueda de donantes (estudiantes) en tiempo real con debounce
- Historial de donaciones por usuario

### Despensa

- Inventario de articulos de despensa con unidad de medida
- Entradas y salidas de stock
- Campanas de recoleccion con meta y progreso en tiempo real (auto-incremento de `collected_quantity`)

### Reportes Administrativos

- Dashboard con metricas: prendas disponibles, citas del dia, donaciones recientes
- Actividad reciente del sistema
- Exportacion de datos

---

## Estado de Desarrollo

| Fase | Descripcion | Estado |
|---|---|---|
| Fase 1 | Infraestructura y autenticacion | Completa |
| Fase 2 | Catalogo de prendas | Completa |
| Fase 3 | Sistema de citas | Completa |
| Fase 4 | CRUD de prendas (volunteer/admin) | Completa |
| Fase 5 | Donaciones de ropa | Completa |
| Fase 6 | Despensa y campanas | Completa |
| Fase 7 | Slots de tiempo | Completa |
| Fase 8 | Dashboard admin y reportes | Completa |
| Fase 9 | Pagina publica de reconocimiento a donadores | **Pendiente** |

---

## URLs

| Tipo | Prefijo |
|---|---|
| API REST | `/api/vistetec/v2/` |
| Paginas HTML | `/vistetec/` |

### Modulos API

| Sub-ruta | Descripcion |
|---|---|
| `/catalog` | Consulta del catalogo publico de prendas |
| `/garments` | CRUD de prendas (volunteer/admin) |
| `/appointments` | Gestion de citas |
| `/slots` | Administracion de slots de tiempo |
| `/donations` | Registro y consulta de donaciones |
| `/pantry` | Gestion de despensa y campanas |
| `/reports` | Metricas y reportes administrativos |

### Paginas HTML

| Ruta | Descripcion |
|---|---|
| `/vistetec/` | Landing publica |
| `/vistetec/student/` | Portal del estudiante |
| `/vistetec/volunteer/` | Panel del voluntario |
| `/vistetec/admin/` | Panel de administracion |

---

## Estructura de Directorios

```
vistetec/
├── router.py                  # APIRouter principal (/api/vistetec/v2)
├── models/                    # Modelos SQLAlchemy
│   ├── garment.py             # Prendas de vestir
│   ├── appointment.py         # Citas para probarse ropa
│   ├── time_slot.py           # Horarios de atencion
│   ├── donation.py            # Donaciones de ropa
│   ├── pantry_item.py         # Articulos de despensa
│   ├── pantry_campaign.py     # Campanas de recoleccion
│   └── location.py            # Ubicaciones fisicas
├── api/
│   ├── catalog.py             # Catalogo publico
│   ├── garments.py            # CRUD de prendas
│   ├── appointments.py        # Citas
│   ├── time_slots.py          # Slots de tiempo
│   ├── donations.py           # Donaciones
│   ├── pantry.py              # Despensa y campanas
│   └── reports.py             # Reportes
├── pages/
│   ├── router.py              # APIRouter de paginas HTML
│   ├── student.py
│   ├── volunteer.py
│   └── admin.py
├── schemas/                   # Pydantic validators
├── services/                  # Logica de negocio
├── utils/                     # Helpers especificos
├── templates/vistetec/        # Templates Jinja2
└── static/                    # CSS, JS, imagenes (servidos por Nginx)
    ├── css/
    │   ├── student/
    │   ├── volunteer/
    │   └── admin/
    └── js/
        ├── shared/
        ├── student/
        ├── volunteer/
        └── admin/
```

---

## Modelos de Base de Datos

Todas las tablas usan el prefijo `vistetec_`.

| Tabla | Descripcion |
|---|---|
| `vistetec_garments` | Prendas de vestir del catalogo |
| `vistetec_appointments` | Citas para probarse ropa |
| `vistetec_time_slots` | Horarios de atencion por dia |
| `vistetec_donations` | Registro de donaciones de ropa |
| `vistetec_pantry_items` | Articulos de despensa con stock |
| `vistetec_pantry_campaigns` | Campanas de recoleccion |
| `vistetec_pantry_donations` | Donaciones vinculadas a una campana |
| `vistetec_locations` | Ubicaciones fisicas del servicio |

---

## Compresion de Imagenes

VisteTec aplica compresion en dos etapas para optimizar el almacenamiento:

### Lado del Cliente (JavaScript)

- Se usa la API Canvas del navegador para redimensionar antes de subir
- Limita la resolucion y convierte a formato comprimido

### Lado del Servidor (Python / Pillow)

- Calidad JPEG: 85%
- Resolucion maxima: 1920 px en el lado mas largo
- Tamano maximo de entrada: 3 MB
- Si la imagen ya esta dentro del limite, se guarda sin recomprimir

Las imagenes se almacenan en `instance/apps/vistetec/garments/{año}/{mes}/`.

---

## Flujo de una Cita

```
Estudiante selecciona prenda disponible
        │
        └── Elige slot disponible
              │
              └── Confirma (declara si trae donacion)
                        │
                        └── Voluntario atiende la cita
                                  │
                                  ├── COMPLETED (prenda entregada)
                                  ├── NO_SHOW  (estudiante no llego)
                                  └── CANCELED  (cancelada por el estudiante)
```

---

## Campanas de Despensa

Las campanas permiten organizar recolecciones de articulos especificos:

- Cada campana tiene una meta en cantidad (`goal_quantity`)
- Al registrar una donacion vinculada a la campana, `collected_quantity` se incrementa automaticamente
- El progreso es visible en tiempo real para todos los usuarios

---

## CLI — Comandos Disponibles

```bash
# Ejecuta todos los scripts SQL de database/DML/vistetec/ en orden
# Carga permisos, roles y datos base del modulo
python -m itcj2.cli.main vistetec init-vistetec
```

---

## Inicializacion

Los datos base se cargan en dos pasos:

```bash
# 1. Datos core (roles globales, departamentos)
python -m itcj2.cli.main core init-db

# 2. Datos especificos de VisteTec (permisos, roles del modulo, ubicaciones)
python -m itcj2.cli.main vistetec init-vistetec
```

Los scripts DML estan en `database/DML/vistetec/`.

---

## Permisos

Los permisos siguen el formato `vistetec.recurso.accion`.

Ejemplos:

| Permiso | Descripcion |
|---|---|
| `vistetec.catalog.view` | Ver el catalogo de prendas |
| `vistetec.appointment.create` | Crear citas |
| `vistetec.appointment.manage` | Gestionar citas (volunteer/admin) |
| `vistetec.garment.manage` | Crear, editar y publicar prendas |
| `vistetec.donation.create` | Registrar donaciones |
| `vistetec.pantry.manage` | Gestionar despensa y campanas |
| `vistetec.reports.view` | Ver reportes administrativos |

---

## Convenciones de JavaScript

- Todos los archivos JS usan patron IIFE con `'use strict'`
- Utilidades compartidas disponibles en `window.VisteTecUtils`:
  - `showToast(message, type)` — Notificacion tipo toast
  - `confirmModal(message)` — Modal de confirmacion (reemplaza `confirm()`)
  - `compressImage(file, maxSizeMB)` — Compresion de imagen en cliente
- Sin uso de `alert()` ni `confirm()` nativos del navegador
- Color de marca: `#8B1538`
