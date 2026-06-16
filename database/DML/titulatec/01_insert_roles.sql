-- ============================================
-- TITULATEC - Roles nuevos
-- ============================================
-- Roles globales (core_roles), asignados a usuarios en la app 'titulatec'
-- vía core_user_app_roles (directo) o core_position_app_roles (por puesto).
--
-- NOTA: el alumno RECICLA el rol global 'student' (no se crea uno propio).
-- 'student' ya existe en core_roles y es el role_id de los alumnos; al darle
-- los permisos titulatec.* (app-scoped) sólo obtiene acceso a esta app.

INSERT INTO core_roles (name) VALUES
    ('titulatec_school_services'),        -- Servicios Escolares operativo (secretary/aux)
    ('titulatec_school_services_head'),   -- jefe de Servicios Escolares (gestiona encargados + ve todo)
    ('titulatec_titulaciones'),           -- División Estudios Profesionales / Titulaciones (vía puestos)
    ('titulatec_sinodal'),           -- sinodal (auto-grant al asignar a un proceso)
    ('titulatec_vinculacion')        -- jefe de proyecto de vinculación (vía puestos coord_vinculacion_*)
ON CONFLICT (name) DO NOTHING;

DO $$
BEGIN
    RAISE NOTICE '✅ Roles de TitulaTec insertados';
END $$;
