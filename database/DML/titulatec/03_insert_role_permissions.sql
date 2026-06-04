-- ============================================
-- TITULATEC - Asignación rol → permisos
-- ============================================
-- core_role_permissions(role_id, perm_id). Permisos por app 'titulatec'.

DO $$
DECLARE
    v_app_id INTEGER;
BEGIN
    SELECT id INTO v_app_id FROM core_apps WHERE key = 'titulatec';
    IF v_app_id IS NULL THEN
        RAISE EXCEPTION 'La app titulatec no existe. Ejecuta primero 00_insert_app.sql';
    END IF;

    -- ---------- student (rol global reciclado) ----------
    -- El alumno usa el rol global 'student'. Los permisos son app-scoped
    -- (Permission.app_id = titulatec), así que esto NO afecta a otras apps.
    INSERT INTO core_role_permissions (role_id, perm_id)
    SELECT r.id, p.id FROM core_roles r
    JOIN core_permissions p ON p.app_id = v_app_id AND p.code = ANY(ARRAY[
        'titulatec.dashboard.student',
        'titulatec.process.page.my', 'titulatec.process.api.read.own', 'titulatec.process.api.advance',
        'titulatec.document.api.upload.own', 'titulatec.document.api.read.own', 'titulatec.document.api.delete.own',
        'titulatec.format_b.page.fill', 'titulatec.format_b.api.save', 'titulatec.format_b.api.submit', 'titulatec.format_b.api.read.own',
        'titulatec.chat.page.view', 'titulatec.chat.api.read', 'titulatec.chat.api.send', 'titulatec.chat.api.upload',
        'titulatec.appointment.page.my', 'titulatec.appointment.api.confirm.own',
        'titulatec.ceremony.page.my', 'titulatec.ceremony.api.upload.own',
        'titulatec.notifications.api.read.own', 'titulatec.notifications.api.mark_read'
    ]) WHERE r.name = 'student'
    ON CONFLICT DO NOTHING;

    -- ---------- titulatec_school_services (operativo: scoped, sin read.all) ----------
    INSERT INTO core_role_permissions (role_id, perm_id)
    SELECT r.id, p.id FROM core_roles r
    JOIN core_permissions p ON p.app_id = v_app_id AND p.code = ANY(ARRAY[
        'titulatec.dashboard.school_services',
        'titulatec.process.page.list', 'titulatec.process.page.detail',
        'titulatec.process.api.approve_phase', 'titulatec.process.api.reject_phase',
        'titulatec.document.api.read.all', 'titulatec.document.api.approve', 'titulatec.document.api.reject',
        'titulatec.cohort.page.list', 'titulatec.cohort.page.detail', 'titulatec.cohort.api.read',
        'titulatec.cohort.api.create', 'titulatec.cohort.api.update', 'titulatec.cohort.api.import_csv',
        'titulatec.appointment.page.list', 'titulatec.appointment.api.create', 'titulatec.appointment.api.update',
        'titulatec.appointment.api.mark_attended', 'titulatec.appointment.api.reschedule',
        'titulatec.document.page.list',
        'titulatec.notifications.api.read.own', 'titulatec.notifications.api.mark_read'
    ]) WHERE r.name = 'titulatec_school_services'
    ON CONFLICT DO NOTHING;

    -- ---------- titulatec_school_services_head ----------
    INSERT INTO core_role_permissions (role_id, perm_id)
    SELECT r.id, p.id FROM core_roles r
    JOIN core_permissions p ON p.app_id = v_app_id AND p.code = ANY(ARRAY[
        'titulatec.dashboard.school_services',
        'titulatec.process.page.list', 'titulatec.process.page.detail', 'titulatec.process.api.read.all',
        'titulatec.process.api.approve_phase', 'titulatec.process.api.reject_phase',
        'titulatec.document.api.read.all', 'titulatec.document.api.approve', 'titulatec.document.api.reject',
        'titulatec.cohort.page.list', 'titulatec.cohort.page.detail', 'titulatec.cohort.api.read',
        'titulatec.cohort.api.create', 'titulatec.cohort.api.update', 'titulatec.cohort.api.import_csv',
        'titulatec.appointment.page.list', 'titulatec.appointment.api.create', 'titulatec.appointment.api.update',
        'titulatec.appointment.api.mark_attended', 'titulatec.appointment.api.reschedule',
        'titulatec.officers.page.list', 'titulatec.officers.api.manage',
        'titulatec.cohort.api.review_days',
        'titulatec.document.page.list',
        'titulatec.notifications.api.read.own', 'titulatec.notifications.api.mark_read'
    ]) WHERE r.name = 'titulatec_school_services_head'
    ON CONFLICT DO NOTHING;

    -- ---------- titulatec_titulaciones ----------
    INSERT INTO core_role_permissions (role_id, perm_id)
    SELECT r.id, p.id FROM core_roles r
    JOIN core_permissions p ON p.app_id = v_app_id AND p.code = ANY(ARRAY[
        'titulatec.dashboard.titulaciones',
        'titulatec.process.page.list', 'titulatec.process.page.detail', 'titulatec.process.api.read.all',
        'titulatec.process.api.approve_phase', 'titulatec.process.api.reject_phase',
        'titulatec.process.api.cancel', 'titulatec.process.api.hold',
        'titulatec.document.api.read.all', 'titulatec.document.api.approve', 'titulatec.document.api.reject',
        'titulatec.document.page.list',
        'titulatec.format_b.api.read.all', 'titulatec.format_b.api.approve', 'titulatec.format_b.api.reject',
        'titulatec.ceremony.page.list', 'titulatec.ceremony.api.create', 'titulatec.ceremony.api.update',
        'titulatec.notifications.api.read.own', 'titulatec.notifications.api.mark_read'
    ]) WHERE r.name = 'titulatec_titulaciones'
    ON CONFLICT DO NOTHING;

    -- ---------- titulatec_sinodal ----------
    INSERT INTO core_role_permissions (role_id, perm_id)
    SELECT r.id, p.id FROM core_roles r
    JOIN core_permissions p ON p.app_id = v_app_id AND p.code = ANY(ARRAY[
        'titulatec.dashboard.sinodal',
        'titulatec.synodal.page.my_reviews', 'titulatec.synodal.api.read',
        'titulatec.synodal.api.vote', 'titulatec.synodal.api.release',
        'titulatec.process.api.read.own',
        'titulatec.document.api.read.all',
        'titulatec.chat.page.view', 'titulatec.chat.api.read', 'titulatec.chat.api.send', 'titulatec.chat.api.upload', 'titulatec.chat.api.pin_document',
        'titulatec.notifications.api.read.own', 'titulatec.notifications.api.mark_read'
    ]) WHERE r.name = 'titulatec_sinodal'
    ON CONFLICT DO NOTHING;

    -- ---------- titulatec_vinculacion ----------
    INSERT INTO core_role_permissions (role_id, perm_id)
    SELECT r.id, p.id FROM core_roles r
    JOIN core_permissions p ON p.app_id = v_app_id AND p.code = ANY(ARRAY[
        'titulatec.dashboard.vinculacion',
        'titulatec.synodal.page.list', 'titulatec.synodal.api.assign', 'titulatec.synodal.api.read', 'titulatec.synodal.api.release',
        'titulatec.process.api.read.department',
        'titulatec.chat.page.view', 'titulatec.chat.api.read', 'titulatec.chat.api.send', 'titulatec.chat.api.upload', 'titulatec.chat.api.pin_document',
        'titulatec.notifications.api.read.own', 'titulatec.notifications.api.mark_read'
    ]) WHERE r.name = 'titulatec_vinculacion'
    ON CONFLICT DO NOTHING;

    -- Cleanup: el rol operativo ya no debe tener read.all (queda scoped por carrera).
    DELETE FROM core_role_permissions crp
    USING core_roles r, core_permissions p
    WHERE crp.role_id = r.id AND crp.perm_id = p.id
      AND r.name = 'titulatec_school_services'
      AND p.app_id = v_app_id AND p.code = 'titulatec.process.api.read.all';

    -- Cleanup: Convocatorias (cohorts) son de Servicios Escolares; Titulaciones ya no las ve.
    DELETE FROM core_role_permissions crp
    USING core_roles r, core_permissions p
    WHERE crp.role_id = r.id AND crp.perm_id = p.id
      AND r.name = 'titulatec_titulaciones'
      AND p.app_id = v_app_id
      AND p.code IN ('titulatec.cohort.page.list', 'titulatec.cohort.page.detail', 'titulatec.cohort.api.read');

    RAISE NOTICE '✅ Asignación rol→permisos de TitulaTec completada';
END $$;
