-- ============================================
-- TITULATEC - Mapeo puestos → roles
-- ============================================
-- Habilita "todo el depto maneja igual" para Servicios Escolares y Titulaciones,
-- y la asignación de vinculación por puesto. PK (position_id, app_id, role_id).

-- titulatec_school_services_head → solo el puesto de jefe
INSERT INTO core_position_app_roles (position_id, app_id, role_id)
SELECT p.id, a.id, r.id
FROM core_positions p, core_apps a, core_roles r
WHERE a.key = 'titulatec' AND r.name = 'titulatec_school_services_head'
  AND p.code = 'head_school_services'
ON CONFLICT DO NOTHING;

-- titulatec_school_services (operativo) → secretary/aux
INSERT INTO core_position_app_roles (position_id, app_id, role_id)
SELECT p.id, a.id, r.id
FROM core_positions p, core_apps a, core_roles r
WHERE a.key = 'titulatec' AND r.name = 'titulatec_school_services'
  AND p.code IN ('secretary_school_services', 'aux_school_services')
ON CONFLICT DO NOTHING;

-- Cleanup: head_school_services ya no debe tener el rol operativo (ahora tiene el head).
DELETE FROM core_position_app_roles par
USING core_positions p, core_apps a, core_roles r
WHERE par.position_id = p.id AND par.app_id = a.id AND par.role_id = r.id
  AND a.key = 'titulatec' AND r.name = 'titulatec_school_services'
  AND p.code = 'head_school_services';

-- titulatec_titulaciones → puestos de la División de Estudios Profesionales (DEP)
INSERT INTO core_position_app_roles (position_id, app_id, role_id)
SELECT p.id, a.id, r.id
FROM core_positions p, core_apps a, core_roles r
WHERE a.key = 'titulatec' AND r.name = 'titulatec_titulaciones'
  AND p.code IN ('head_prof_studies_div', 'secretary_prof_studies_div', 'aux_prof_studies_div')
ON CONFLICT DO NOTHING;

-- titulatec_vinculacion → puestos coord_vinculacion_*
INSERT INTO core_position_app_roles (position_id, app_id, role_id)
SELECT p.id, a.id, r.id
FROM core_positions p, core_apps a, core_roles r
WHERE a.key = 'titulatec' AND r.name = 'titulatec_vinculacion'
  AND p.code LIKE 'coord_vinculacion_%'
ON CONFLICT DO NOTHING;

DO $$
BEGIN
    RAISE NOTICE '✅ Mapeo puestos→roles de TitulaTec completado';
END $$;
