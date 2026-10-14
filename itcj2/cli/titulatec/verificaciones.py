"""Verificaciones contra la BD que corre `init-titulatec` al terminar de sembrar.

`_verify_survey_2026_09` (delta de la encuesta: también la corre
`load-survey-2026-09`), `_verify_titulacion` (Departamento de Titulación y el
reparto de Liberados) y `_verify_computer_center` (accesos de Centro de
Cómputo), con las constantes de roles, puestos y permisos que fijan. Otros
deltas (`biblioteca`, `deltas`) reusan esas constantes desde aquí.
"""

_SURVEY_2026_09_PERMS = (
    "titulatec.survey.page.list",
    "titulatec.survey.api.read",
    "titulatec.survey.api.export",
    "titulatec.survey.api.manage",
    "titulatec.enrollment_request.page.list",
    "titulatec.enrollment_request.api.approve",
    "titulatec.enrollment_request.api.reject",
    "titulatec.process.api.requirement.mark",
    # 2026-09-15 (spec 2026-09-15-titulatec-liberacion-gtv): liberacion de la
    # encuesta de egresados por Gestion Tecnologica y Vinculacion (GTV).
    "titulatec.survey_review.page.list",
    "titulatec.survey_review.api.approve",
    "titulatec.survey_review.api.reject",
)

_PERM_MARCA_REQUISITO = "titulatec.process.api.requirement.mark"

# ---------------------------------------------------------------------------
# Reparto de GTV (2026-09-15): rol nuevo `titulatec_tech_management`, puesto
# de ventanilla `external_service_tech_management` (el de jefatura,
# `head_tech_management`, ya existe en el organigrama del core). Ver spec
# 2026-09-15-titulatec-liberacion-gtv-design.md, seccion 7.
# ---------------------------------------------------------------------------
_ROL_GTV = "titulatec_tech_management"
_PUESTO_GTV_VENTANILLA = "external_service_tech_management"

# Los 2 de notificaciones no son parte del delta (`_SURVEY_2026_09_PERMS`,
# arriba): ya existian desde 02_insert_permissions.sql. Se listan aparte para
# no inflar el contrato de "codigos que este delta declara" con permisos que
# ya declaraba otro archivo.
_PERMISOS_NOTIFICACIONES = (
    "titulatec.notifications.api.read.own",
    "titulatec.notifications.api.mark_read",
)

# Los 9 que debe tener GTV en titulatec: los 3 nuevos de liberacion + los 4
# `survey.*` (bandeja/detalle/exportar/administrar, que la jefatura pierde) +
# los 2 de notificaciones que ya tiene el resto de los roles de la app.
_PERMISOS_GTV = (
    "titulatec.survey_review.page.list",
    "titulatec.survey_review.api.approve",
    "titulatec.survey_review.api.reject",
    "titulatec.survey.page.list",
    "titulatec.survey.api.read",
    "titulatec.survey.api.export",
    "titulatec.survey.api.manage",
) + _PERMISOS_NOTIFICACIONES

# La jefatura de Servicios Escolares pierde `titulatec.survey.%` (pasa a GTV,
# spec D12) pero conserva estos 4: las 3 solicitudes de auto-inscripcion y el
# marcado de requisitos de cotejo.
_ROL_JEFATURA_ESCOLARES = "titulatec_school_services_head"
_PERMISOS_JEFATURA_CONSERVA = (
    "titulatec.enrollment_request.page.list",
    "titulatec.enrollment_request.api.approve",
    "titulatec.enrollment_request.api.reject",
    _PERM_MARCA_REQUISITO,
)

_ROL_OPERATIVO_ESCOLARES = "titulatec_school_services"
# 2026-09-21 (spec 2026-09-21-titulatec-dpto-titulacion, "encargados de
# carrera en la bandeja de Solicitudes"): el operativo deja de tener SOLO
# `requirement.mark` y gana ADEMAS los mismos 3 `enrollment_request.*` que ya
# tenia la jefatura -- los encargados de carrera (puestos `se_officer_*`),
# la secretaria y el auxiliar del depto cuelgan de este rol. El alcance por
# carrera de esa bandeja YA estaba implementado en `requests_admin.py`
# (`officer_programs` + `_load_scoped_request`/`_program_in_scope`); este
# delta solo abre la puerta del permiso. `api.approve` tambien gatea el
# reenvio de liga (`requests_admin.py::resend`) -- intencional.
_PERMISOS_OPERATIVO_CONSERVA = (
    _PERM_MARCA_REQUISITO,
    "titulatec.enrollment_request.page.list",
    "titulatec.enrollment_request.api.approve",
    "titulatec.enrollment_request.api.reject",
)


def _verify_survey_2026_09() -> list[str]:
    """Comprueba que el delta ATERRIZÓ. Devuelve la lista de problemas.

    Existe porque los `RAISE NOTICE` del DML son INVISIBLES: nada en `itcj2/`
    lee `connection.notices`. Sin esto, el operador ve "OK" aunque el
    `INSERT ... SELECT` de grants haya insertado cero filas — que es justo lo
    que pasa si el rol todavía no existe. Mismo patrón que
    `itcj2/cli/directory.py::_verify_settings_permission`.

    2026-09-15: además del set original (8 permisos + grants a la jefatura y
    al operativo) verifica el reparto de la liberación de GTV (spec
    2026-09-15-titulatec-liberacion-gtv, sección 7):
      - el rol nuevo `titulatec_tech_management` con sus 9 permisos
        (3 `survey_review.*` + 4 `survey.*` + 2 `notifications.*`);
      - la jefatura de Servicios Escolares se quedó SIN ningún
        `titulatec.survey.%` (el DELETE de 10 se re-aplica en cada corrida)
        mientras conserva `enrollment_request.*` y `requirement.mark`;
      - el encargado operativo conserva `requirement.mark`;
      - el puesto de ventanilla (`external_service_tech_management`) existe y
        el mapeo puesto→rol de GTV tiene exactamente 2 filas (jefatura +
        ventanilla).

    2026-09-21 (spec 2026-09-21-titulatec-dpto-titulacion, "encargados de
    carrera en la bandeja de Solicitudes"): el encargado operativo
    (`titulatec_school_services`) ADEMÁS recibe los 3 `enrollment_request.*`
    -mismo trío que ya tenía la jefatura- para que los encargados de carrera
    puedan resolver la bandeja de Solicitudes de SU carrera. El alcance real
    no lo da este permiso: lo acota `scope_service.officer_programs()` +
    `_load_scoped_request`/`_program_in_scope` en `pages/requests_admin.py`,
    que ya filtraba esa bandeja antes de este delta.
    """
    from sqlalchemy import text

    from itcj2.cli.core import _get_engine

    problemas: list[str] = []
    codigos = list(_SURVEY_2026_09_PERMS)
    # Para el chequeo de grants a GTV hace falta ademas los 2 de notificaciones,
    # que no son parte del delta (ya existian) pero si del reparto de GTV.
    codigos_grants = sorted(set(codigos) | set(_PERMISOS_NOTIFICACIONES))

    with _get_engine().connect() as conn:
        existentes = {
            row[0]
            for row in conn.execute(
                text(
                    "SELECT p.code FROM core_permissions p "
                    "JOIN core_apps a ON a.id = p.app_id AND a.key = 'titulatec' "
                    "WHERE p.code = ANY(:codes)"
                ),
                {"codes": codigos},
            )
        }
        for code in codigos:
            if code not in existentes:
                problemas.append(f"permiso ausente: {code}")

        concedidos = {
            (row[0], row[1])
            for row in conn.execute(
                text(
                    "SELECT r.name, p.code "
                    "  FROM core_role_permissions rp "
                    "  JOIN core_roles r ON r.id = rp.role_id "
                    "  JOIN core_permissions p ON p.id = rp.perm_id "
                    "  JOIN core_apps a ON a.id = p.app_id AND a.key = 'titulatec' "
                    " WHERE p.code = ANY(:codes)"
                ),
                {"codes": codigos_grants},
            )
        }
        for code in _PERMISOS_JEFATURA_CONSERVA:
            if (_ROL_JEFATURA_ESCOLARES, code) not in concedidos:
                problemas.append(f"sin grant a la jefatura: {code}")
        for code in _PERMISOS_OPERATIVO_CONSERVA:
            if (_ROL_OPERATIVO_ESCOLARES, code) not in concedidos:
                problemas.append(f"sin grant al encargado operativo: {code}")

        for code in _PERMISOS_GTV:
            if (_ROL_GTV, code) not in concedidos:
                problemas.append(f"sin grant a GTV ({_ROL_GTV}): {code}")

        # La jefatura NO debe conservar ningun titulatec.survey.% (paso a GTV,
        # spec D12). LIKE con punto literal tras "survey": no alcanza a
        # titulatec.survey_review.* (llevan '_' ahi, no '.').
        supervivientes = [
            row[0]
            for row in conn.execute(
                text(
                    "SELECT p.code FROM core_role_permissions rp "
                    "  JOIN core_roles r ON r.id = rp.role_id "
                    "  JOIN core_permissions p ON p.id = rp.perm_id "
                    "  JOIN core_apps a ON a.id = p.app_id AND a.key = 'titulatec' "
                    " WHERE r.name = :rol AND p.code LIKE 'titulatec.survey.%'"
                ),
                {"rol": _ROL_JEFATURA_ESCOLARES},
            )
        ]
        if supervivientes:
            problemas.append(
                "la jefatura de Servicios Escolares todavía tiene "
                f"titulatec.survey.%: {supervivientes} "
                "(el DELETE de 10_insert_survey_role_permissions.sql no aterrizó)"
            )

        puesto_id = conn.execute(
            text("SELECT id FROM core_positions WHERE code = :code"),
            {"code": _PUESTO_GTV_VENTANILLA},
        ).scalar()
        if puesto_id is None:
            problemas.append(f"puesto ausente: {_PUESTO_GTV_VENTANILLA}")

        n_mapeo = conn.execute(
            text(
                "SELECT COUNT(*) FROM core_position_app_roles par "
                "  JOIN core_apps a ON a.id = par.app_id AND a.key = 'titulatec' "
                "  JOIN core_roles r ON r.id = par.role_id "
                " WHERE r.name = :rol"
            ),
            {"rol": _ROL_GTV},
        ).scalar()
        if n_mapeo != 2:
            problemas.append(
                f"mapeo puesto→rol de GTV ({_ROL_GTV}): se esperaban 2 filas, hay {n_mapeo}"
            )

        abiertos = conn.execute(
            text(
                "SELECT version FROM titulatec_survey_forms "
                " WHERE code = 'egresados' AND status = 'open'"
            )
        ).fetchall()
        if len(abiertos) != 1:
            problemas.append(
                f"formularios 'egresados' abiertos: {len(abiertos)} "
                "(el índice parcial uq_titulatec_survey_forms_open exige exactamente 1)"
            )

    return problemas


# ---------------------------------------------------------------------------
# Departamento de Titulación (2026-09-21, spec
# 2026-09-21-titulatec-dpto-titulacion): rol nuevo `titulatec_titulacion` con
# sus 2 puestos (`head_titulacion`, `aux_titulacion`), colgado del
# departamento `titulacion` (a su vez colgado de `prof_studies_div`).
#
# `titulatec_titulaciones` (la jefatura de la División) se recortó ese mismo
# día a solo-supervisión (D6/D7) y el usuario REVIRTIÓ el recorte poco
# después: quiere que la jefatura pueda hacer cualquier cosa en TitulaTec,
# aunque el trabajo diario de dictamen lo siga haciendo el Departamento de
# Titulación. Hoy `titulatec_titulaciones` tiene el reparto PLENO (25) y
# `titulatec_titulacion` se quedó igual (22) — ver spec secciones 3 y 6, y el
# comentario de cada bloque del ARRAY en `03_insert_role_permissions.sql`.
# 2026-10-07 (spec 2026-10-07-titulatec-liberados-biblioteca-helpdesk, D1 +
# D7/D8): `titulatec_titulacion` queda en 16 EXACTOS (Liberados + expediente
# resumido + dictamen); `titulatec_titulaciones` no cambia.
# ---------------------------------------------------------------------------
_DEPTO_TITULACION = "titulacion"
_DEPTO_PADRE_TITULACION = "prof_studies_div"
_PUESTO_HEAD_TITULACION = "head_titulacion"
_PUESTO_AUX_TITULACION = "aux_titulacion"
_ROL_TITULACION = "titulatec_titulacion"
_ROL_TITULACIONES_DIV = "titulatec_titulaciones"
_PUESTO_HEAD_PROF_STUDIES_DIV = "head_prof_studies_div"

_PERMISOS_HANDOFF = (
    "titulatec.handoff.page.list",
    "titulatec.handoff.api.export",
)

# Los 8 permisos de dictamen de las fases 3-8 (Formato B en adelante). Los
# tiene `titulatec_titulacion` (Departamento de Titulación, quien dictamina
# en el día a día) y, desde que el usuario revirtió el recorte D6/D7, también
# `titulatec_titulaciones` (la jefatura de la División — puede hacerlo aunque
# normalmente no lo haga).
_PERMISOS_DICTAMEN_FASES_3_8 = (
    "titulatec.process.api.approve_phase",
    "titulatec.process.api.reject_phase",
    "titulatec.process.api.cancel",
    "titulatec.process.api.hold",
    "titulatec.format_b.api.approve",
    "titulatec.format_b.api.reject",
    "titulatec.document.api.approve",
    "titulatec.document.api.reject",
)

# Los 2 de escritura de ceremony (fase 8). Mismo reparto que
# `_PERMISOS_DICTAMEN_FASES_3_8` de arriba: `titulatec_titulacion` los tiene
# desde que nació, y `titulatec_titulaciones` los recuperó al revertirse D6/D7.
_PERMISOS_CEREMONY_ESCRITURA = (
    "titulatec.ceremony.api.create",
    "titulatec.ceremony.api.update",
)

# Los 3 de Convocatorias (cohort). Decisión explícita del usuario al revertir
# D6/D7: la jefatura de la División (`titulatec_titulaciones`) también debe
# ver Convocatorias, no solo dictaminar. `titulatec_titulacion` (Departamento
# de Titulación) NO los tiene -- por eso ese rol se quedó en 22 (16 desde el
# 2026-10-07) y este otro sube a 25: la diferencia es intencional, no hay que
# "igualarlos".
_PERMISOS_COHORT_TITULACIONES_DIV = (
    "titulatec.cohort.page.list",
    "titulatec.cohort.page.detail",
    "titulatec.cohort.api.read",
)

# Permiso NUEVO del 2026-10-07 (spec 2026-10-07-titulatec-liberados-
# biblioteca-helpdesk-design.md, D7): el expediente RESUMIDO -- solo las
# fases previas al corte y su dictamen, sin desglose. Lo declaran el 02 (base)
# y el delta `ajustes_2026_10/01` (producción).
_PERM_PROCESS_SUMMARY = "titulatec.process.page.summary"

# Los 7 que `titulatec_titulacion` (Departamento de Titulación) PIERDE el
# 2026-10-07 (D1 «solo ocultar pantallas» + D8): Bandeja, Procesos,
# Documentos, Actos protocolarios y el expediente COMPLETO con sus lecturas de
# desglose -- en su lugar ve el expediente resumido. `titulatec_titulaciones`
# (jefatura de la División) los conserva. La base (03) converge el rol a su
# set exacto en cada corrida (DELETE de todo lo de titulatec fuera de los
# 16); en producción lo converge el delta `ajustes_2026_10/01` (comando
# `init-ajustes-2026-10`).
_PERMISOS_RETIRADOS_TITULACION = (
    "titulatec.dashboard.titulaciones",
    "titulatec.process.page.list",
    "titulatec.process.page.detail",
    "titulatec.document.page.list",
    "titulatec.document.api.read.all",
    "titulatec.format_b.api.read.all",
    "titulatec.ceremony.page.list",
)

# Los 12 permisos de SUPERVISIÓN (lectura de todo + la bandeja de liberados)
# de la jefatura de la División (`titulatec_titulaciones`). Hasta el
# 2026-10-07 los compartía completos con `titulatec_titulacion`; desde
# entonces ese rol solo conserva 5 (ver `_PERMISOS_CONSULTA_TITULACION`).
# Arreglo A3(c) (revisión final 2026-09-21): antes `_verify_titulacion()`
# solo comprobaba que `titulatec_titulacion` tuviera los 10 del delta
# (dictamen + ceremony), no el reparto completo del rol -- una siembra que
# dejara sin sembrar alguno de estos (p.ej. si `02_insert_permissions.sql`
# se ejecutara truncado) pasaba en verde. Mismo motivo por el que el verify
# de `titulatec_titulaciones` (abajo) también exige el reparto completo, no
# un subconjunto.
_PERMISOS_SUPERVISION_TITULACIONES = (
    "titulatec.dashboard.titulaciones",
    "titulatec.process.page.list",
    "titulatec.process.page.detail",
    "titulatec.process.api.read.all",
    "titulatec.document.api.read.all",
    "titulatec.document.page.list",
    "titulatec.format_b.api.read.all",
    "titulatec.ceremony.page.list",
) + _PERMISOS_HANDOFF + (
    "titulatec.notifications.api.read.own",
    "titulatec.notifications.api.mark_read",
)

# Lo que `titulatec_titulacion` consulta (6): de la supervisión conserva 5
# (12 - 7) -- `process.api.read.all`, sin el cual la bandeja de Liberados sale
# vacía (sus puestos no tienen carreras), Liberados y notificaciones -- y gana
# el expediente resumido.
_PERMISOS_CONSULTA_TITULACION = tuple(
    code for code in _PERMISOS_SUPERVISION_TITULACIONES
    if code not in _PERMISOS_RETIRADOS_TITULACION
) + (_PERM_PROCESS_SUMMARY,)

# Los 16 permisos EXACTOS de `titulatec_titulacion` desde el 2026-10-07
# (eran 22, D5 de la spec 2026-09-21): los 6 de consulta (arriba) mas los 10
# de dictamen (8 de fase 3-8 + 2 de ceremony), dormidos por el corte a T-soft.
_PERMISOS_ROL_TITULACION = (
    _PERMISOS_CONSULTA_TITULACION
    + _PERMISOS_DICTAMEN_FASES_3_8
    + _PERMISOS_CEREMONY_ESCRITURA
)

# Los 25 permisos completos de `titulatec_titulaciones` (jefatura de la
# División) tras revertir el recorte D6/D7: los 12 de supervisión, los 10 de
# dictamen MÁS los 3 de cohort. No cambia el 2026-10-07 (D1). Queda con MÁS
# permisos que `titulatec_titulacion` -- es intencional (ver
# `_PERMISOS_COHORT_TITULACIONES_DIV`), no lo "corrijas".
_PERMISOS_ROL_TITULACIONES_DIV = (
    _PERMISOS_SUPERVISION_TITULACIONES
    + _PERMISOS_DICTAMEN_FASES_3_8
    + _PERMISOS_CEREMONY_ESCRITURA
    + _PERMISOS_COHORT_TITULACIONES_DIV
)


def _verify_titulacion() -> list[str]:
    """Comprueba que el Departamento de Titulación ATERRIZÓ Y que la jefatura de
    la División quedó con su reparto PLENO. Devuelve problemas.

    Mismo contrato que `_verify_survey_2026_09`: abre su propia conexión,
    arma sets contra la BD y devuelve strings de problema en vez de levantar.
    Sin esto un `INSERT ... SELECT` que inserta 0 filas (p.ej. porque `04b` no
    corrió antes que `05`, o `prof_studies_div` no existe en esta base) sale
    en verde igual que la app a medio sembrar del incidente de los seeders
    borrados. Ver spec 2026-09-21-titulatec-dpto-titulacion, sección 6.

    Fija el reparto COMPLETO de los dos roles de Titulación, no un subconjunto:
    `titulatec_titulacion` con EXACTAMENTE sus 16 (`_PERMISOS_ROL_TITULACION`,
    22 hasta el 2026-10-07) y `titulatec_titulaciones` con sus 25
    (`_PERMISOS_ROL_TITULACIONES_DIV`) — el usuario revirtió el recorte D6/D7
    del mismo día: la jefatura de la División puede dictaminar, escribir
    ceremony y ver Convocatorias, aunque el trabajo diario lo siga haciendo el
    Departamento de Titulación. Las reglas sobre los permisos de los roles
    viven en `_problemas_grants_titulacion` (pura, probada sin BD).
    """
    from sqlalchemy import text

    from itcj2.cli.core import _get_engine

    problemas: list[str] = []

    with _get_engine().connect() as conn:
        # Departamento titulacion con su parent_id correcto.
        depto = conn.execute(
            text(
                "SELECT d.id, padre.code "
                "FROM core_departments d "
                "LEFT JOIN core_departments padre ON padre.id = d.parent_id "
                "WHERE d.code = :code"
            ),
            {"code": _DEPTO_TITULACION},
        ).first()
        if depto is None:
            problemas.append(f"departamento ausente: {_DEPTO_TITULACION}")
        elif depto[1] != _DEPTO_PADRE_TITULACION:
            problemas.append(
                f"departamento {_DEPTO_TITULACION}: parent_id apunta a "
                f"'{depto[1]}', se esperaba '{_DEPTO_PADRE_TITULACION}'"
            )

        # Los 2 puestos nuevos.
        puestos = {
            row[0]
            for row in conn.execute(
                text("SELECT code FROM core_positions WHERE code = ANY(:codes)"),
                {"codes": [_PUESTO_HEAD_TITULACION, _PUESTO_AUX_TITULACION]},
            )
        }
        for code in (_PUESTO_HEAD_TITULACION, _PUESTO_AUX_TITULACION):
            if code not in puestos:
                problemas.append(f"puesto ausente: {code}")

        # Los 2 permisos de la bandeja de liberados.
        permisos = {
            row[0]
            for row in conn.execute(
                text(
                    "SELECT p.code FROM core_permissions p "
                    "JOIN core_apps a ON a.id = p.app_id AND a.key = 'titulatec' "
                    "WHERE p.code = ANY(:codes)"
                ),
                {"codes": list(_PERMISOS_HANDOFF)},
            )
        }
        for code in _PERMISOS_HANDOFF:
            if code not in permisos:
                problemas.append(f"permiso ausente: {code}")

        # Mapeo puesto→rol: el rol nuevo debe INCLUIR head+aux, y el viejo
        # debe INCLUIR head_prof_studies_div. Arreglo A7 (revision final
        # 2026-09-21): antes esto exigia una CUENTA EXACTA (2 y 1 filas). Si
        # un admin mapeara mas adelante, con toda intencion, un tercer puesto
        # al rol nuevo (o a la supervision de la Division) desde el
        # organigrama del core, `init-titulatec` abortaba en rojo con la
        # siembra perfectamente sana -- "contiene al menos estos puestos" no
        # se rompe con una decision de organigrama que nada tiene que ver con
        # el DML.
        puestos_de = {}
        for rol in (_ROL_TITULACION, _ROL_TITULACIONES_DIV):
            puestos_de[rol] = {
                row[0]
                for row in conn.execute(
                    text(
                        "SELECT pos.code FROM core_position_app_roles par "
                        "  JOIN core_apps a ON a.id = par.app_id AND a.key = 'titulatec' "
                        "  JOIN core_roles r ON r.id = par.role_id "
                        "  JOIN core_positions pos ON pos.id = par.position_id "
                        " WHERE r.name = :rol"
                    ),
                    {"rol": rol},
                )
            }

        faltan_nuevo = {_PUESTO_HEAD_TITULACION, _PUESTO_AUX_TITULACION} - puestos_de[_ROL_TITULACION]
        if faltan_nuevo:
            problemas.append(
                f"mapeo puesto→rol de {_ROL_TITULACION}: faltan {sorted(faltan_nuevo)} "
                f"(hay {sorted(puestos_de[_ROL_TITULACION])})"
            )

        if _PUESTO_HEAD_PROF_STUDIES_DIV not in puestos_de[_ROL_TITULACIONES_DIV]:
            problemas.append(
                f"mapeo puesto→rol de {_ROL_TITULACIONES_DIV}: falta "
                f"{_PUESTO_HEAD_PROF_STUDIES_DIV} "
                f"(hay {sorted(puestos_de[_ROL_TITULACIONES_DIV])})"
            )

        # Los permisos de los 4 roles que fija este verify, en una consulta.
        roles = (_ROL_TITULACION, _ROL_TITULACIONES_DIV,
                 _ROL_OPERATIVO_ESCOLARES, _ROL_JEFATURA_ESCOLARES)
        concedidos: dict[str, set[str]] = {rol: set() for rol in roles}
        for rol, code in conn.execute(
            text(
                "SELECT r.name, p.code FROM core_role_permissions rp "
                "  JOIN core_roles r ON r.id = rp.role_id "
                "  JOIN core_permissions p ON p.id = rp.perm_id "
                "  JOIN core_apps a ON a.id = p.app_id AND a.key = 'titulatec' "
                " WHERE r.name = ANY(:roles)"
            ),
            {"roles": list(roles)},
        ):
            concedidos[rol].add(code)

    problemas.extend(_problemas_grants_titulacion(concedidos))
    return problemas


def _problemas_grants_titulacion(concedidos: dict[str, set[str]]) -> list[str]:
    """Reglas de `_verify_titulacion` sobre los permisos de los roles, PURAS
    (sin BD): `concedidos` es `{rol: {codigo, ...}}` en titulatec.

    - `titulatec_titulacion` tiene EXACTAMENTE sus 16 (2026-10-07, D1 + D8;
      arreglo A3(c): el reparto completo, no solo los 10 del delta de
      dictamen). El 03 lo converge en cada corrida (DELETE de todo lo de
      titulatec fuera de los 16), así que un permiso de más o de menos es
      una siembra que no aterrizó.
    - `titulatec_titulaciones` (jefatura de la División) CONTIENE su reparto
      PLENO: 25 -- los 12 de supervisión, los 8 de dictamen de fases 3-8, los
      2 de escritura de ceremony y los 3 de cohort. El usuario revirtió el
      recorte D6/D7 del 2026-09-21: la jefatura puede hacer cualquier cosa en
      TitulaTec aunque el trabajo diario de dictamen lo siga haciendo el
      Departamento de Titulación. Positivo, no negativo: antes de ese cambio
      este verify exigía que el rol NO tuviera dictamen/ceremony.
    - Los dos roles de Servicios Escolares CONTIENEN Liberados (D2,
      2026-10-07): `handoff.page.list` + `handoff.api.export`.

    Semántica «contiene al menos» salvo titulación (mismo motivo que el
    arreglo A7: un permiso extra concedido a mano no es un problema de la
    siembra; titulación sí, porque el propio 03 lo converge).
    """
    problemas: list[str] = []
    titulacion = concedidos.get(_ROL_TITULACION, set())
    debe = set(_PERMISOS_ROL_TITULACION)
    if titulacion != debe:
        problemas.append(
            f"{_ROL_TITULACION} no tiene exactamente sus {len(debe)} permisos "
            f"(faltan {sorted(debe - titulacion)}, sobran {sorted(titulacion - debe)}; "
            "el 03 lo converge en cada corrida)"
        )

    division = concedidos.get(_ROL_TITULACIONES_DIV, set())
    for code in _PERMISOS_ROL_TITULACIONES_DIV:
        if code not in division:
            problemas.append(f"sin grant a {_ROL_TITULACIONES_DIV}: {code}")

    for rol in (_ROL_OPERATIVO_ESCOLARES, _ROL_JEFATURA_ESCOLARES):
        for code in _PERMISOS_HANDOFF:
            if code not in concedidos.get(rol, set()):
                problemas.append(f"sin grant a {rol}: {code} (Liberados, 2026-10-07)")
    return problemas


# ---------------------------------------------------------------------------
# Centro de Cómputo (2026-09-24, spec 2026-09-24-titulatec-accesos-centro-
# computo): NIP en dos pasos. Servicios Escolares aprueba y, si el
# solicitante no tiene cuenta, la solicitud pasa a `awaiting_access`; Centro
# de Cómputo (CC) es quien le da el NIP desde la bandeja nueva «Accesos».
# ---------------------------------------------------------------------------
_ROL_COMPUTER_CENTER = "titulatec_computer_center"
_ROL_ADMIN = "admin"
_PUESTO_HEAD_COMP_CENTER = "head_comp_center"
_PUESTO_SECRETARY_COMP_CENTER = "secretary_comp_center"

_PERMISOS_ACCESOS_COMPUTO = (
    "titulatec.enrollment_access.page.list",
    "titulatec.enrollment_access.api.grant",
    "titulatec.enrollment_access.api.return",
    "titulatec.enrollment_access.api.reject",
)


def _verify_computer_center() -> list[str]:
    """Comprueba que el rol de Centro de Cómputo ATERRIZÓ. Devuelve problemas.

    Mismo contrato que `_verify_survey_2026_09`/`_verify_titulacion`: abre su
    propia conexión, arma sets contra la BD y devuelve strings de problema en
    vez de levantar. Sin esto un `INSERT ... SELECT` que inserta 0 filas
    (p.ej. porque `head_comp_center`/`secretary_comp_center` no existen en
    esta base) sale en verde igual que la app a medio sembrar del incidente de
    los seeders borrados.

    Tres chequeos (spec sección 7, D1/D2):
      - el rol `titulatec_computer_center` concede EXACTAMENTE los 4 códigos
        de la bandeja de Accesos, ni uno más ni uno menos;
      - el mapeo puesto→rol INCLUYE `head_comp_center` y
        `secretary_comp_center` -- semántica "contiene al menos" (arreglo A7,
        igual que `_verify_titulacion`): no exige conteo exacto de filas, así
        que mapear a mano un tercer puesto más adelante no rompe esto;
      - `head_comp_center` tiene ADEMÁS el rol `admin` en titulatec (D2).

    Si algún puesto no existe en la base (0 filas), el mensaje lo dice
    explícitamente en vez de reportar solo "falta el mapeo": la causa más
    probable es que el organigrama de Centro de Cómputo no esté sembrado
    todavía en ese ambiente.
    """
    from sqlalchemy import text

    from itcj2.cli.core import _get_engine

    problemas: list[str] = []

    with _get_engine().connect() as conn:
        puestos = {
            row[0]
            for row in conn.execute(
                text("SELECT code FROM core_positions WHERE code = ANY(:codes)"),
                {"codes": [_PUESTO_HEAD_COMP_CENTER, _PUESTO_SECRETARY_COMP_CENTER]},
            )
        }
        for code in (_PUESTO_HEAD_COMP_CENTER, _PUESTO_SECRETARY_COMP_CENTER):
            if code not in puestos:
                problemas.append(
                    f"puesto ausente: {code} (el organigrama de Centro de "
                    "Cómputo no está sembrado en esta base)"
                )

        concedidos = {
            row[0]
            for row in conn.execute(
                text(
                    "SELECT p.code FROM core_role_permissions rp "
                    "  JOIN core_roles r ON r.id = rp.role_id "
                    "  JOIN core_permissions p ON p.id = rp.perm_id "
                    "  JOIN core_apps a ON a.id = p.app_id AND a.key = 'titulatec' "
                    " WHERE r.name = :rol"
                ),
                {"rol": _ROL_COMPUTER_CENTER},
            )
        }
        if concedidos != set(_PERMISOS_ACCESOS_COMPUTO):
            faltan = set(_PERMISOS_ACCESOS_COMPUTO) - concedidos
            sobran = concedidos - set(_PERMISOS_ACCESOS_COMPUTO)
            problemas.append(
                f"{_ROL_COMPUTER_CENTER} no tiene exactamente los 4 permisos "
                f"de Accesos (faltan {sorted(faltan)}, sobran {sorted(sobran)})"
            )

        # Mapeo puesto→rol para los dos roles que nos importan aquí, con la
        # MISMA consulta parametrizada (patrón de `_verify_titulacion`:
        # ~639-653) en vez de repetirla una vez por rol.
        puestos_de_rol = {}
        for rol in (_ROL_COMPUTER_CENTER, _ROL_ADMIN):
            puestos_de_rol[rol] = {
                row[0]
                for row in conn.execute(
                    text(
                        "SELECT pos.code FROM core_position_app_roles par "
                        "  JOIN core_apps a ON a.id = par.app_id AND a.key = 'titulatec' "
                        "  JOIN core_roles r ON r.id = par.role_id "
                        "  JOIN core_positions pos ON pos.id = par.position_id "
                        " WHERE r.name = :rol"
                    ),
                    {"rol": rol},
                )
            }

        faltan_mapeo = (
            {_PUESTO_HEAD_COMP_CENTER, _PUESTO_SECRETARY_COMP_CENTER}
            - puestos_de_rol[_ROL_COMPUTER_CENTER]
        )
        if faltan_mapeo:
            problemas.append(
                f"mapeo puesto→rol de {_ROL_COMPUTER_CENTER}: faltan "
                f"{sorted(faltan_mapeo)} (hay {sorted(puestos_de_rol[_ROL_COMPUTER_CENTER])})"
            )

        if _PUESTO_HEAD_COMP_CENTER not in puestos_de_rol[_ROL_ADMIN]:
            problemas.append(
                f"mapeo puesto→rol de {_ROL_ADMIN}: falta {_PUESTO_HEAD_COMP_CENTER} "
                f"(hay {sorted(puestos_de_rol[_ROL_ADMIN])})"
            )

    return problemas
