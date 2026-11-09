# Secretaría · Configuración (periodo de Prórrogas)

> **Objetivo:** que la secretaria defina, para cada semestre, cuándo pueden solicitar prórroga los alumnos y las dos fechas comunes de pago que llenan los planes.

| | |
|---|---|
| **Actores** | Secretaria (rol `secretaria`), admin de la app (rol `admin`) |
| **Permisos** | Página: `prorrogas_tec.secretaria.page.configuracion` · API: `prorrogas_tec.requests.api.read.all` (ver), `prorrogas_tec.plans.api.manage` (guardar) |
| **Disparador** | Empieza un semestre o se acerca la reinscripción |
| **Precondiciones** | El semestre ya existe en core (lo dan de alta los administradores; aquí no se crea) |
| **Estado final** | Una fila en `prorrogas_periods` para ese semestre |

## Ruta en la app (UI)

Escritorio → Prórrogas → `/prorrogas/secretaria` → pestaña **Configuración**.

## Pasos

| # | Actor | UI | Acción | Endpoint | Service · método | Efecto en BD |
|---|---|---|---|---|---|---|
| 1 | Secretaria | Configuración | Ver los semestres no archivados: primero el actual (o el próximo), luego del más nuevo al más viejo | `GET /api/prorrogas/v2/configuracion/periodos` | `periods.configuracion` | — |
| 2 | Secretaria | Formulario | Capturar abre, cierra, pago 1 y pago 2; los errores salen junto a cada campo mientras se captura | — | — | — |
| 3 | Secretaria | **Guardar** | Crear o corregir el periodo del semestre | `POST /api/prorrogas/v2/configuracion/periodos/{period_id}` | `periods.guardar` | Fila en `prorrogas_periods` (una por semestre) |

## Estados de la vista

| Estado | Cuándo | Para el alumno |
|---|---|---|
| Sin configurar | El semestre no tiene fila | No puede solicitar |
| Por abrir | Hoy < abre | No puede solicitar |
| Abierto | abre ≤ hoy ≤ cierra | Puede solicitar (si se unió por QR o invitación dentro del periodo) |
| Cerrado | Hoy > cierra | No puede solicitar; lo que ya tiene sigue su curso |

Un periodo cerrado se puede corregir: los planes ya creados conservan sus fechas.

## Reglas

- La apertura puede ser antes de que empiece el semestre, por la reinscripción. La solicitud queda en el semestre del periodo abierto, no en el que corre por fecha.
- Cierra > abre; pago 1 > abre; pago 2 > pago 1; pago 2 < fin del semestre. El servidor las repite; la vista solo avisa antes.
- Dos periodos no pueden compartir ni un día (`EXCLUDE` sobre el rango de solicitudes, ambos extremos incluidos).
- Un plan nuevo arranca con estas fechas (`plan.fechas_sugeridas` del expediente): 1 pago usa el pago 1; 2 pagos, las dos. Una fecha que ya pasó queda vacía y la secretaria elige otra. También puede moverlas por alumno.

## Errores

| Código | Cuándo | HTTP |
|---|---|---|
| `fechas_invalidas` | No se cumple el orden de las fechas | 400 |
| `no_encontrado` | El semestre no existe o está archivado | 404 |
| `periodo_encimado` | La ventana se encima con la de otro semestre | 409 |
