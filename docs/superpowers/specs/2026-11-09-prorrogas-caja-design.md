# Prórrogas · Caja (puntos 22 a 26)

Cierra los puntos 22 a 26 de la auditoría (`reports/Faltantes del módulo de prórrogas.md`): rol de Caja, cobro del pago más próximo, anular solo el último, sacar a la secretaria del cobro y recibo escaneado del alumno. Se construye sobre el Plan 5.

Diseño: canvas "Caja · búsqueda y cobro" y "Caja · celular" (mismo componente a 390 px). Copia local, solo con datos inventados: `.superpowers/sdd/caja/Caja.dc.html`, `TopNav.dc.html`. Se porta a las plantillas reales. El selector "Ver estado" y los datos de muestra son del prototipo y no van al producto.

## Decisiones del usuario

- Caja es el único rol que marca pagos. Pago completo, sin abonos, en orden, con el folio de su recibo, obligatorio y único. Solo se anula el último, con motivo.
- Rol propio dentro de Prórrogas, solo con la pestaña Estudiantes. No toca TitulaTec.
- La búsqueda abarca todos los semestres por omisión; hay filtro por semestre.
- Las solicitudes históricas del Excel **sin semestre** quedan fuera de Caja: no aparecen en Por cobrar ni en la búsqueda. Las históricas **con semestre** aparecen y se cobran.
- Caja cobra aunque el alumno no haya firmado su carta compromiso.
- Recibo escaneado del alumno: subirlo es obligatorio, validarlo no. Solo PDF, hasta 5 MB. La secretaria ve cuándo se subió y lo abre, y tiene un botón opcional para avisarle al alumno de una inconsistencia, con motivo, por correo y notificación.
- Caja también ve la referencia bancaria, solo lectura.
- El rol Jefe sigue pospuesto (H22): no se crea ni se menciona en pantallas.

## Decisiones por omisión, ya avisadas al usuario

- En Caja solo aparecen solicitudes `aceptada`. Una pendiente, rechazada, cancelada o cerrada sin plan no aparece.
- Si un pago quedó cubierto a medias por recibos anteriores o del Excel, Caja cobra solo lo que falta de ese pago.
- El modal de la secretaria pierde el cobro y gana el estado del recibo y el botón de avisar inconsistencia, con su estilo actual.

## Quién entra a qué

| Rol | Pestañas | Puede |
|---|---|---|
| `caja` | Estudiantes (la de Caja) | Buscar, ver detalle y referencia, saldar, anular el último, ver recibo escaneado |
| `secretaria` | Las suyas, sin la de Caja | Ya no registra ni anula recibos. Ve pagos y recibos; avisa inconsistencia |
| `admin` de la app | Sus cuatro de lectura | Solo lectura. No entra a la de Caja |
| Admin global | Todas | Puede cobrar y anular, por emergencia, desde la pestaña de Caja |

- La página de Caja es una pestaña más de `/prorrogas/secretaria` (`/prorrogas/secretaria/caja`), con `require_tab`. La barra usa el `_base.html` de secretaría y muestra solo lo permitido.
- La pestaña se rotula "Estudiantes" para quien no tiene también la pestaña Estudiantes de la secretaria, y "Caja" para quien tiene ambas (el admin global).
- Al entrar, un usuario `caja` va directo a su pestaña: `_ROLE_HOME` y el orden de `secretaria_home` suman `caja`.

## Lista y búsqueda

Universo: `status = 'aceptada'` y `period_id IS NOT NULL`.

**Sin texto de búsqueda: "Por cobrar".** Universo con plan y saldo mayor que 0.
- Pestañas con conteo: `Todos`, `Con adeudo` (la próxima parcialidad sin cubrir ya venció), `Al corriente`.
- Orden: `Más urgente` (vencidos primero, luego por fecha del próximo pago, luego nombre; por omisión), `Próximo pago`, `Saldo mayor`, `Nombre (A–Z)`.
- 8 por página. Encabezado "Por cobrar" y "N alumnos con pagos pendientes".

**Con texto.** Busca en todo el universo, incluidas Sin plan y Liquidada, por número de control o nombre, sin distinguir acentos ni mayúsculas; respeta el semestre elegido. Sin paginar. Máximo 50 resultados.

Semestre: `Todos los semestres` (por omisión) y uno por cada semestre con solicitudes en el universo.

Columnas en escritorio: No. de control, Nombre, Semestre, Folio de prórroga, Siguiente pago (fecha y "$monto · faltan N pagos"), Situación. En celular, tarjetas.

Situación: `Sin plan`, `Liquidada`, `Con adeudo`, `Al corriente` (de `account.situacion`).

Estados vacíos, con la copia del canvas: "No hay alumnos en este filtro." y "No encontramos a ese alumno. Si no está en el sistema, debe acudir a Centro de Cómputo."

## Detalle

Modal con nombre, situación, control, carrera, semestre, folio de prórroga con botón copiar, Total / Pagado / Saldo, lista de pagos y tarjeta de referencia ("Abrir PDF" o "Sin referencia"). Sin plan: aviso "Aún no se puede cobrar".

Por pago: `Pago i/n`, fecha límite, monto y pastilla `Pagado`, `Pendiente` o `Vencido · N días`.

- Pagado: folio de Caja, fecha, estado del recibo escaneado ("Recibo subido el …" o "Falta subir recibo"), y `Anular` solo en el último.
- El próximo sin cubrir: botón `Saldar pago`. Si está vencido, nota "Se cobra igual, sin recargo."
- Los demás sin cubrir: "Se cobra después de Pago k/n."
- Sin cubrir con recibo escaneado (quedó tras una anulación): "El alumno ya subió un recibo el … Ver recibo".
- Si un pago está cubierto a medias, el monto a cobrar es lo que falta y así se muestra.

Formulario Saldar: monto fijo ("Pago completo, sin abonos."), folio, fecha de pago (hoy por omisión, no futura), `Cancelar`, `Confirmar pago`. Errores junto a su campo: "Captura el folio del recibo de Caja.", "Ese folio ya está registrado.", "Elige la fecha de pago.", "La fecha no puede ser futura." Al terminar, aviso "Pago i/n saldado con el folio X." y, si liquida, " La prórroga quedó liquidada."

Formulario Anular: "Anular recibo X", "Pago i/n vuelve a quedar sin cubrir y se podrá saldar de nuevo.", y si hay recibo del alumno "El recibo que subió el alumno se conserva: sirve para verificar el folio correcto." con botón "Ver recibo del alumno para comparar". Motivo obligatorio: "Escribe el motivo de la anulación." Al terminar, "Recibo X anulado. Pago i/n vuelve a estar pendiente|vencido."

## Datos

Migración aditiva `pr20261109b` (down `pr20261109a`), en `prorrogas_installments`: `receipt_path` (Text) y `receipt_uploaded_at` (DateTime). El recibo escaneado cuelga de la parcialidad, no del recibo de Caja: por eso sobrevive a una anulación.

## Reglas de cobro (servidor)

- `PaymentService.settle_next(db, request_id, actor_id, *, numero, folio, paid_on, now=None)`. Con candado de la solicitud, recalcula la cuenta. Si `numero` no es la próxima parcialidad sin cubrir: `pago_cambio` (409). El monto lo calcula el servidor: lo que falta de esa parcialidad. Sin plan: `sin_plan`. Reutiliza las validaciones de `record`.
- Folio: sin espacios a los lados y en mayúsculas; la comprobación de duplicado no distingue mayúsculas.
- `void` solo anula el último recibo vigente de la solicitud (mayor `paid_on`, luego mayor `id`): si no, `no_es_el_ultimo` (409).
- Las rutas de la secretaria `POST /estudiantes/{id}/recibos` y `.../anular` desaparecen, con su formulario. El registro libre con monto arbitrario deja de existir como API.

## Permisos y semilla

Archivo `database/DML/prorrogas_tec/09_insert_caja.sql` (fuera de git), al final de `_DML_FILES`, idempotente:
- Rol `caja`. Permisos nuevos `prorrogas_tec.secretaria.page.caja` y `prorrogas_tec.caja.api.read`.
- `caja` recibe esos dos, `prorrogas_tec.payments.api.record` y `prorrogas_tec.payments.api.void`.
- `secretaria` pierde `payments.api.record` y `payments.api.void`: el DELETE se limita a ese rol y esos dos códigos de la app `prorrogas_tec`.
- `admin` no recibe nada: 08 ya le deja solo sus seis códigos en cada corrida.

Caja usa `prorrogas_tec.caja.api.read`, no `requests.api.read.all`.

## Recibo escaneado

- Alumno, en Mi prórroga, por cada parcialidad cubierta: si falta, aviso "Falta subir recibo" con selector de archivo; si existe, "Recibo subido el …" con enlace y opción de reemplazar. No bloquea nada.
- `POST /estudiante/solicitudes/{id}/parcialidades/{numero}/recibo` y `GET .../recibo.pdf`, solo la dueña; ajena: 404. Solo si la parcialidad está cubierta: si no, `recibo_no_aplica` (409). La lectura sigue disponible tras una anulación.
- Validación: la misma de la referencia (`%PDF-` al inicio, 5 MB), reutilizada. Ruta `recibos/{period_id}/{request_id}-{numero}-{sha12}.pdf`, nunca con el nombre del archivo. Evento `recibo_subido`.
- Secretaria: en el modal, por pago, el estado y `Ver recibo`; si hay recibo, `Avisar inconsistencia` con motivo de 10 a 500 caracteres. Aviso `recibo_inconsistente` con correo y notificación, y evento en el historial. Permiso `students.api.remind`.
- Caja: `GET /caja/{id}/referencia.pdf` y `GET /caja/{id}/parcialidades/{numero}/recibo.pdf`, con `caja.api.read`.

## Fuera de alcance

Rol Jefe; recordatorios del recibo escaneado; validar el recibo; re-planear con pagos; que Caja edite planes.
