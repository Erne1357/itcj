-- ============================================
-- TITULATEC - Permisos granulares
-- ============================================
-- Nomenclatura: titulatec.{modulo}.{tipo}.{accion}[.scope]
-- Tipos: page (UI), api (operaciones), dashboard (por rol)
-- ============================================

DO $$
DECLARE
    v_app_id INTEGER;
BEGIN
    SELECT id INTO v_app_id FROM core_apps WHERE key = 'titulatec';
    IF v_app_id IS NULL THEN
        RAISE EXCEPTION 'La app titulatec no existe. Ejecuta primero 00_insert_app.sql';
    END IF;

    INSERT INTO core_permissions (app_id, code, name, description) VALUES
    -- ==================== DASHBOARD ====================
    (v_app_id, 'titulatec.dashboard.student',        'Dashboard alumno',        'Acceso al dashboard del alumno'),
    (v_app_id, 'titulatec.dashboard.school_services', 'Dashboard servicios escolares', 'Acceso al dashboard de Servicios Escolares'),
    (v_app_id, 'titulatec.dashboard.titulaciones',   'Dashboard titulaciones',  'Acceso al dashboard de Titulaciones (DEP)'),
    (v_app_id, 'titulatec.dashboard.sinodal',        'Dashboard sinodal',       'Acceso al dashboard del sinodal'),
    (v_app_id, 'titulatec.dashboard.vinculacion',    'Dashboard vinculación',   'Acceso al dashboard de vinculación'),
    (v_app_id, 'titulatec.dashboard.admin',          'Dashboard admin',         'Acceso al dashboard administrativo'),

    -- ==================== PROCESS ====================
    (v_app_id, 'titulatec.process.page.my',          'Página mi proceso',       'Ver mi proceso de titulación'),
    (v_app_id, 'titulatec.process.page.list',        'Página bandeja procesos', 'Ver la bandeja de procesos (admin)'),
    (v_app_id, 'titulatec.process.page.detail',      'Página detalle proceso',  'Ver el detalle de un proceso'),
    (v_app_id, 'titulatec.process.api.read.own',     'Leer mi proceso',         'Consultar mi propio proceso'),
    (v_app_id, 'titulatec.process.api.read.all',     'Leer todos los procesos', 'Consultar todos los procesos'),
    (v_app_id, 'titulatec.process.api.read.department','Leer procesos de depto', 'Consultar procesos de su departamento'),
    (v_app_id, 'titulatec.process.api.advance',      'Avanzar fase',            'Enviar fase a revisión (alumno)'),
    (v_app_id, 'titulatec.process.api.approve_phase','Aprobar fase',            'Aprobar una fase del proceso'),
    (v_app_id, 'titulatec.process.api.reject_phase', 'Rechazar fase',           'Rechazar una fase con motivo'),
    (v_app_id, 'titulatec.process.api.cancel',       'Cancelar proceso',        'Cancelar un proceso de titulación'),
    (v_app_id, 'titulatec.process.api.hold',         'Pausar proceso',          'Poner un proceso en espera'),

    -- ==================== COHORT ====================
    (v_app_id, 'titulatec.cohort.page.list',         'Página convocatorias',    'Ver lista de convocatorias'),
    (v_app_id, 'titulatec.cohort.page.detail',       'Página detalle convocatoria', 'Ver detalle de convocatoria'),
    (v_app_id, 'titulatec.cohort.api.read',          'Leer convocatorias',      'Consultar convocatorias'),
    (v_app_id, 'titulatec.cohort.api.create',        'Crear convocatoria',      'Crear convocatoria'),
    (v_app_id, 'titulatec.cohort.api.update',        'Actualizar convocatoria', 'Modificar convocatoria'),
    (v_app_id, 'titulatec.cohort.api.import_csv',    'Importar CSV',            'Importar alumnos del Forms y activar rol student'),

    -- ==================== DOCUMENT ====================
    (v_app_id, 'titulatec.document.api.upload.own',  'Subir mis documentos',    'Subir documentos de mi proceso'),
    (v_app_id, 'titulatec.document.api.read.own',    'Leer mis documentos',     'Ver mis documentos'),
    (v_app_id, 'titulatec.document.api.read.all',    'Leer todos los documentos','Ver documentos de cualquier proceso'),
    (v_app_id, 'titulatec.document.api.delete.own',  'Eliminar mi documento',   'Eliminar mi documento'),
    (v_app_id, 'titulatec.document.api.approve',     'Aprobar documento',       'Aprobar un documento'),
    (v_app_id, 'titulatec.document.api.reject',      'Rechazar documento',      'Rechazar un documento (pedir corrección)'),

    -- ==================== FORMAT_B ====================
    (v_app_id, 'titulatec.format_b.page.fill',       'Página Formato B',        'Llenar el Formato B'),
    (v_app_id, 'titulatec.format_b.api.save',        'Guardar Formato B',       'Guardado parcial del Formato B'),
    (v_app_id, 'titulatec.format_b.api.submit',      'Enviar Formato B',        'Enviar Formato B a revisión'),
    (v_app_id, 'titulatec.format_b.api.read.own',    'Leer mi Formato B',       'Ver mi Formato B'),
    (v_app_id, 'titulatec.format_b.api.read.all',    'Leer Formatos B',         'Ver Formato B de cualquier proceso'),
    (v_app_id, 'titulatec.format_b.api.approve',     'Aprobar Formato B',       'Aprobar Formato B'),
    (v_app_id, 'titulatec.format_b.api.reject',      'Rechazar Formato B',      'Rechazar Formato B'),

    -- ==================== SYNODAL ====================
    (v_app_id, 'titulatec.synodal.page.list',        'Página asignación sinodales', 'Ver/gestionar asignación de sinodales'),
    (v_app_id, 'titulatec.synodal.page.my_reviews',  'Página mis revisiones',   'Ver mis procesos asignados como sinodal'),
    (v_app_id, 'titulatec.synodal.api.assign',       'Asignar sinodales',       'Asignar sinodales y crear chat'),
    (v_app_id, 'titulatec.synodal.api.read',         'Leer sinodales',          'Consultar sinodales de un proceso'),
    (v_app_id, 'titulatec.synodal.api.vote',         'Votar como sinodal',      'Emitir voto/Vo.Bo. como sinodal'),
    (v_app_id, 'titulatec.synodal.api.release',      'Liberar proyecto',        'Liberar el proyecto (presidente/vinculación)'),

    -- ==================== CHAT ====================
    (v_app_id, 'titulatec.chat.page.view',           'Página chat',             'Ver el chat de titulación'),
    (v_app_id, 'titulatec.chat.api.read',            'Leer chat',               'Leer mensajes del chat'),
    (v_app_id, 'titulatec.chat.api.send',            'Enviar mensaje',          'Enviar mensaje al chat'),
    (v_app_id, 'titulatec.chat.api.upload',          'Adjuntar en chat',        'Subir adjunto al chat'),
    (v_app_id, 'titulatec.chat.api.pin_document',    'Pinear documento',        'Fijar la versión actual del proyecto'),

    -- ==================== APPOINTMENT (cita de cotejo) ====================
    (v_app_id, 'titulatec.appointment.page.list',    'Página citas',            'Ver/gestionar citas de cotejo'),
    (v_app_id, 'titulatec.appointment.page.my',      'Página mi cita',          'Ver mi cita de cotejo'),
    (v_app_id, 'titulatec.appointment.api.create',   'Crear cita',              'Agendar cita de cotejo'),
    (v_app_id, 'titulatec.appointment.api.update',   'Actualizar cita',         'Modificar cita de cotejo'),
    (v_app_id, 'titulatec.appointment.api.confirm.own','Confirmar mi cita',     'Confirmar asistencia a mi cita'),
    (v_app_id, 'titulatec.appointment.api.mark_attended','Marcar asistencia',   'Marcar asistencia a la cita'),
    (v_app_id, 'titulatec.appointment.api.reschedule','Reagendar cita',         'Reagendar cita de cotejo'),

    -- ==================== CEREMONY (acto protocolario) ====================
    (v_app_id, 'titulatec.ceremony.page.list',       'Página actos',            'Ver/gestionar actos protocolarios'),
    (v_app_id, 'titulatec.ceremony.page.my',         'Página mi acto',          'Ver mi acto protocolario'),
    (v_app_id, 'titulatec.ceremony.api.create',      'Crear acto',              'Crear acto protocolario'),
    (v_app_id, 'titulatec.ceremony.api.update',      'Actualizar acto',         'Modificar acto protocolario'),
    (v_app_id, 'titulatec.ceremony.api.upload.own',  'Subir trabajo final',     'Subir proyecto final y presentación'),

    -- ==================== NOTIFICATIONS ====================
    (v_app_id, 'titulatec.notifications.api.read.own','Leer notificaciones',    'Ver mis notificaciones'),
    (v_app_id, 'titulatec.notifications.api.mark_read','Marcar leída',          'Marcar notificación como leída'),

    -- ==================== OFFICERS (encargados) ====================
    (v_app_id, 'titulatec.officers.page.list',  'Encargados (ver)',        'Ver y gestionar encargados por carrera'),
    (v_app_id, 'titulatec.officers.api.manage', 'Encargados (gestionar)', 'Crear/editar encargados, usuarios y carreras')
    ON CONFLICT (app_id, code) DO NOTHING;

    RAISE NOTICE '✅ Permisos de TitulaTec insertados';
END $$;
