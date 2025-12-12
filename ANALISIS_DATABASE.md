# ANÁLISIS DE MEJORAS - DATABASE & INICIALIZACIÓN
## Sistema ITCJ - Scripts DML y Configuración Inicial

**Fecha:** 2025-12-12
**Alcance:** Scripts SQL de inicialización, comando `flask init-db`, datos semilla
**Criticidad:** ALTA - Ejecutados una sola vez, deben ser perfectos

---

## RESUMEN EJECUTIVO

El sistema de inicialización de base de datos del proyecto ITCJ utiliza **scripts SQL estáticos** ejecutados mediante el comando `flask init-db`. Hay **25 archivos SQL** organizados en 3 directorios (core, agendatec, helpdesk) que insertan datos semilla incluyendo aplicaciones, departamentos, posiciones, roles, permisos y usuarios.

### Hallazgos Principales

🔴 **CRÍTICO:**
- **Orden de ejecución no documentado** - FK constraints pueden fallar
- **Contraseñas hardcodeadas** en 07_insert_user.sql (mismo hash para todos)
- **Sin estrategia de rollback** - Si falla a la mitad, BD queda inconsistente
- **IDs hardcodeados** - Frágil ante cambios en sequence

⚠️ **RIESGOS:**
- **Sin idempotencia completa** - Algunos scripts usan ON CONFLICT, otros no
- **Datos de prueba mezclados con producción** - No se distinguen
- **Sin versionado de scripts** - No se puede recrear versión específica
- **Dependencias implícitas** - Scripts dependen entre sí sin validación

✅ **FORTALEZAS:**
- **Uso de subqueries** para FKs (mejor que IDs hardcodeados directos)
- **ON CONFLICT DO NOTHING** en scripts críticos (roles, permisos)
- **Estructura jerárquica** clara (apps → roles → permisos → usuarios)
- **Modelo de permisos excelente** (granular y escalable)

---

## 📁 ESTRUCTURA DE SCRIPTS DML

### Inventario Completo

```
database/DML/
├── core/ (13 archivos)
│   ├── 00_insert_apps.sql                          # 3 apps
│   ├── 01_insert_departments.sql                   # Jerarquía dept (18 deps)
│   ├── 02_insert_positions.sql                     # 50+ posiciones
│   ├── 03_insert_icons_deparments.sql              # Íconos UI
│   ├── 04_insert_roles.sql                         # 8 roles base
│   ├── 05_insert_permissions.sql                   # 70+ permisos core
│   ├── 06_insert_role_permissions.sql              # Mapeo roles-perms
│   ├── 07_insert_user.sql                          # 50+ usuarios ⚠️
│   ├── 08_insert_role_positions_helpdesk.sql       # Roles por posición
│   ├── 09_insert_user_positions.sql                # Usuarios en posiciones
│   ├── 10_insert_user_roles.sql                    # Roles de usuarios
│   ├── agendatec/
│   │   ├── 01_insert_permissions.sql               # Permisos agendatec
│   │   ├── 02_insert_user_app.sql                  # User-app associations
│   │   └── 03_insert_role_permission.sql           # Role-perm agendatec
│   └── core/ (vacío)
│
└── helpdesk/ (12 archivos)
    ├── 01_insert_permissions.sql                   # Permisos helpdesk
    ├── 02_insert_roles.sql                         # Roles específicos
    ├── 03_insert_role_permission.sql               # Mapeos
    ├── 04_insert_categories.sql                    # Categorías tickets
    ├── 05_insert_inventory_categories.sql          # Categorías inventario
    ├── 06_insert_enhanced_inventory_categories.sql # Categorías enhanced
    ├── 07_insert_position_app_perm.sql             # Permisos por posición
    ├── 08_insert_technician_user.sql               # Usuario técnico
    ├── 09_insert_user_role_technician.sql          # Rol de técnico
    ├── 10_insert_position_technician.sql           # Posición técnico (?)
    ├── 11_insert_user_position_technician.sql      # Asignación técnico
    └── 12_insert_configure_moodle_custom_fields.sql # Config Moodle ⭐ NUEVO
```

**Total:** 25 archivos SQL

---

## 🚨 PRIORIDAD CRÍTICA / URGENTE

### 1. **Documentar orden de ejecución y dependencias**

**Problema:**
El comando `flask init-db` ejecuta scripts en orden alfabético/numérico, pero las **dependencias no están documentadas**. Si alguien modifica los nombres de archivo o agrega scripts nuevos, pueden ocurrir errores de FK.

**Ubicación:** `itcj/core/commands.py:238`

**Código actual:**
```python
sql_directories = [
    ('database/DML/core', [
        '00_insert_apps.sql',
        '01_insert_departments.sql',
        # ... 13 archivos
    ]),
    ('database/DML/core/agendatec', [
        '01_insert_permissions.sql',
        # ... 3 archivos
    ]),
    ('database/DML/helpdesk', [
        '01_insert_permissions.sql',
        # ... 12 archivos
    ])
]
```

**Problema identificado:**
- Orden hardcodeado en código Python
- Sin validación de dependencias
- Sin rollback si falla a mitad

**Solución 1: Crear README con grafo de dependencias**

```markdown
# database/DML/README.md

# Orden de Ejecución de Scripts DML

## ⚠️ IMPORTANTE
Los scripts DEBEN ejecutarse en este orden exacto. Las dependencias están marcadas con flechas.

## Diagrama de Dependencias

```
CORE:
00_insert_apps.sql
    ↓
01_insert_departments.sql
    ↓
02_insert_positions.sql → (depende de departments)
    ↓
03_insert_icons_deparments.sql → (depende de departments)
    ↓
04_insert_roles.sql
    ↓
05_insert_permissions.sql → (depende de apps)
    ↓
06_insert_role_permissions.sql → (depende de roles + permissions)
    ↓
07_insert_user.sql → (depende de departments)
    ↓
08_insert_role_positions_helpdesk.sql → (depende de positions + roles)
    ↓
09_insert_user_positions.sql → (depende de users + positions)
    ↓
10_insert_user_roles.sql → (depende de users + roles + apps)

AGENDATEC (después de CORE):
01_insert_permissions.sql → (depende de core: apps)
    ↓
02_insert_user_app.sql → (depende de core: users + apps)
    ↓
03_insert_role_permission.sql → (depende de 01 + core: roles)

HELPDESK (después de CORE):
01_insert_permissions.sql → (depende de core: apps)
    ↓
02_insert_roles.sql
    ↓
03_insert_role_permission.sql → (depende de 01 + 02)
    ↓
04_insert_categories.sql
    ↓
05_insert_inventory_categories.sql
06_insert_enhanced_inventory_categories.sql
    ↓
07_insert_position_app_perm.sql → (depende de core: positions + 01)
    ↓
08_insert_technician_user.sql → (depende de core: departments)
    ↓
09_insert_user_role_technician.sql → (depende de 08 + 02)
11_insert_user_position_technician.sql → (depende de 08 + core: positions)
    ↓
12_insert_configure_moodle_custom_fields.sql → (depende de 04)
```

## Validaciones Previas

Antes de ejecutar, verificar:
1. ✅ Base de datos existe
2. ✅ Migraciones aplicadas (flask db upgrade)
3. ✅ Variables de entorno configuradas
4. ✅ PostgreSQL versión 14+

## Rollback

Si un script falla:
1. Identificar el script que falló
2. Ejecutar: `flask db downgrade base` (resetea todo)
3. Ejecutar: `flask db upgrade`
4. Corregir el script problemático
5. Re-ejecutar: `flask init-db`

## Testing

Para probar scripts en ambiente limpio:
```bash
# Crear BD de prueba
createdb itcj_test

# Ejecutar migraciones
FLASK_APP=wsgi.py DATABASE_URL=postgresql://user:pass@localhost/itcj_test flask db upgrade

# Ejecutar scripts DML
FLASK_APP=wsgi.py DATABASE_URL=postgresql://user:pass@localhost/itcj_test flask init-db

# Verificar
psql itcj_test -c "SELECT COUNT(*) FROM core_users;"
```
```

**Esfuerzo estimado:** Muy Bajo (1 hora documentación)
**Impacto:** Muy Alto (previene errores, facilita mantenimiento)
**Riesgo:** Ninguno

---

**Solución 2: Validación de dependencias en código**

```python
# itcj/core/commands.py
import sys

# Definir dependencias explícitamente
SCRIPT_DEPENDENCIES = {
    'core': {
        '00_insert_apps.sql': [],
        '01_insert_departments.sql': ['00_insert_apps.sql'],
        '02_insert_positions.sql': ['01_insert_departments.sql'],
        '03_insert_icons_deparments.sql': ['01_insert_departments.sql'],
        '04_insert_roles.sql': [],
        '05_insert_permissions.sql': ['00_insert_apps.sql'],
        '06_insert_role_permissions.sql': ['04_insert_roles.sql', '05_insert_permissions.sql'],
        '07_insert_user.sql': ['01_insert_departments.sql'],
        '08_insert_role_positions_helpdesk.sql': ['02_insert_positions.sql', '04_insert_roles.sql'],
        '09_insert_user_positions.sql': ['07_insert_user.sql', '02_insert_positions.sql'],
        '10_insert_user_roles.sql': ['07_insert_user.sql', '04_insert_roles.sql', '00_insert_apps.sql'],
    },
    'agendatec': {
        '01_insert_permissions.sql': ['core/00_insert_apps.sql'],
        '02_insert_user_app.sql': ['core/07_insert_user.sql', 'core/00_insert_apps.sql'],
        '03_insert_role_permission.sql': ['01_insert_permissions.sql', 'core/04_insert_roles.sql'],
    },
    'helpdesk': {
        '01_insert_permissions.sql': ['core/00_insert_apps.sql'],
        '02_insert_roles.sql': [],
        '03_insert_role_permission.sql': ['01_insert_permissions.sql', '02_insert_roles.sql'],
        '04_insert_categories.sql': [],
        '05_insert_inventory_categories.sql': [],
        '06_insert_enhanced_inventory_categories.sql': [],
        '07_insert_position_app_perm.sql': ['core/02_insert_positions.sql', '01_insert_permissions.sql'],
        '08_insert_technician_user.sql': ['core/01_insert_departments.sql'],
        '09_insert_user_role_technician.sql': ['08_insert_technician_user.sql', '02_insert_roles.sql'],
        '11_insert_user_position_technician.sql': ['08_insert_technician_user.sql', 'core/02_insert_positions.sql'],
        '12_insert_configure_moodle_custom_fields.sql': ['04_insert_categories.sql'],
    }
}


def validate_dependencies(executed_scripts, pending_script, module):
    """Validar que todas las dependencias fueron ejecutadas."""
    dependencies = SCRIPT_DEPENDENCIES.get(module, {}).get(pending_script, [])

    missing = []
    for dep in dependencies:
        # Normalizar path de dependencia
        if '/' in dep:
            dep_full = dep  # Ya incluye módulo
        else:
            dep_full = f"{module}/{dep}"

        if dep_full not in executed_scripts:
            missing.append(dep)

    return missing


@click.command('init-db')
@with_appcontext
def init_db():
    """Inicializar base de datos con datos semilla."""
    click.echo("🔄 Inicializando base de datos con datos semilla...")

    executed_scripts = []
    failed_scripts = []

    sql_directories = [
        ('database/DML/core', 'core', [
            '00_insert_apps.sql',
            '01_insert_departments.sql',
            '02_insert_positions.sql',
            '03_insert_icons_deparments.sql',
            '04_insert_roles.sql',
            '05_insert_permissions.sql',
            '06_insert_role_permissions.sql',
            '07_insert_user.sql',
            '08_insert_role_positions_helpdesk.sql',
            '09_insert_user_positions.sql',
            '10_insert_user_roles.sql',
        ]),
        ('database/DML/core/agendatec', 'agendatec', [
            '01_insert_permissions.sql',
            '02_insert_user_app.sql',
            '03_insert_role_permission.sql',
        ]),
        ('database/DML/helpdesk', 'helpdesk', [
            '01_insert_permissions.sql',
            '02_insert_roles.sql',
            '03_insert_role_permission.sql',
            '04_insert_categories.sql',
            '05_insert_inventory_categories.sql',
            '06_insert_enhanced_inventory_categories.sql',
            '07_insert_position_app_perm.sql',
            '08_insert_technician_user.sql',
            '09_insert_user_role_technician.sql',
            '11_insert_user_position_technician.sql',
            '12_insert_configure_moodle_custom_fields.sql',
        ])
    ]

    try:
        for directory, module, sql_files in sql_directories:
            click.echo(f"\n📂 Procesando módulo: {module}")

            for sql_file in sql_files:
                # Validar dependencias
                missing_deps = validate_dependencies(executed_scripts, sql_file, module)
                if missing_deps:
                    click.echo(f"  ❌ {sql_file} - Dependencias faltantes: {', '.join(missing_deps)}", err=True)
                    failed_scripts.append((sql_file, f"Missing dependencies: {missing_deps}"))
                    continue

                file_path = os.path.join(directory, sql_file)

                if not os.path.exists(file_path):
                    click.echo(f"  ⚠️  {sql_file} - Archivo no encontrado", err=True)
                    continue

                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        sql_content = f.read()

                    # Ejecutar en transacción
                    db.session.execute(text(sql_content))
                    db.session.commit()

                    click.echo(f"  ✅ {sql_file}")
                    executed_scripts.append(f"{module}/{sql_file}")

                except Exception as e:
                    db.session.rollback()
                    click.echo(f"  ❌ {sql_file} - Error: {str(e)}", err=True)
                    failed_scripts.append((sql_file, str(e)))

                    # Si falla un script crítico, abortar
                    if sql_file in ['00_insert_apps.sql', '04_insert_roles.sql', '05_insert_permissions.sql']:
                        click.echo("\n🛑 Script crítico falló. Abortando inicialización.", err=True)
                        sys.exit(1)

        # Resumen
        click.echo(f"\n✨ Inicialización completada:")
        click.echo(f"  ✅ Scripts ejecutados: {len(executed_scripts)}")
        if failed_scripts:
            click.echo(f"  ❌ Scripts fallidos: {len(failed_scripts)}")
            for script, error in failed_scripts:
                click.echo(f"     - {script}: {error}")
            sys.exit(1)

    except Exception as e:
        click.echo(f"\n💥 Error fatal: {e}", err=True)
        db.session.rollback()
        sys.exit(1)
```

**Esfuerzo estimado:** Medio (4 horas)
**Impacto:** Muy Alto (previene errores, rollback automático)
**Riesgo:** Bajo

---

### 2. **Eliminar contraseñas hardcodeadas en scripts**

**Problema CRÍTICO:**
El archivo `07_insert_user.sql` contiene **50+ usuarios** con la **misma contraseña hardcodeada**.

**Ubicación:** `database/DML/core/07_insert_user.sql`

**Código problemático:**
```sql
INSERT INTO core_users (
    control_number, username, email, first_name, last_name,
    department_id, password_hash, must_change_password, is_active
)
SELECT
    NULL,
    'francisco.saucedo',
    'francisco.saucedo@cdjuarez.tecnm.mx',
    'Francisco',
    'Saucedo',
    (SELECT id FROM core_departments WHERE code = 'DIR'),
    'scrypt:32768:8:1$ZshV34gGFmJl1s8G$a675f0c4117ce077f4b3320561c431b84726a615327cae96ec1e23e2ebc97e06b898b9a7d6faea1b055ede7bdaaed1f1086f4cb9c8b7482c5d9f22ca2dc88835',
    TRUE,  -- ✅ BUENO: must_change_password
    TRUE
WHERE NOT EXISTS (
    SELECT 1 FROM core_users WHERE username = 'francisco.saucedo'
);
-- ... repetido 50+ veces con diferentes usuarios
```

**Problemas:**
1. **Mismo hash para todos** - Si se descifra uno, se descifran todos
2. **Hash visible en Git** - Cualquiera con acceso al repo puede verlo
3. **¿Cuál es la contraseña?** - No documentada (probablemente "itcj2024" o similar)

**Solución: Generar contraseñas aleatorias en script**

```python
# itcj/core/commands.py
import secrets
import string
from werkzeug.security import generate_password_hash

def generate_random_password(length=12):
    """Generar contraseña aleatoria segura."""
    alphabet = string.ascii_letters + string.digits + "!@#$%"
    return ''.join(secrets.choice(alphabet) for _ in range(length))


@click.command('seed-users')
@click.option('--output-csv', type=click.Path(), help='Guardar credenciales en CSV')
@with_appcontext
def seed_users(output_csv):
    """Crear usuarios iniciales con contraseñas aleatorias."""
    from itcj.core.models import User, Department

    # Lista de usuarios a crear
    users_data = [
        {
            'username': 'francisco.saucedo',
            'email': 'francisco.saucedo@cdjuarez.tecnm.mx',
            'first_name': 'Francisco',
            'last_name': 'Saucedo',
            'department_code': 'DIR',
            'role': 'director'
        },
        {
            'username': 'juan.perez',
            'email': 'juan.perez@cdjuarez.tecnm.mx',
            'first_name': 'Juan',
            'last_name': 'Pérez',
            'department_code': 'SISTEMAS',
            'role': 'jefe_departamento'
        },
        # ... más usuarios ...
    ]

    created_users = []
    credentials = []  # Para exportar

    for user_data in users_data:
        # Verificar si ya existe
        existing = User.query.filter_by(username=user_data['username']).first()
        if existing:
            click.echo(f"  ⚠️  Usuario {user_data['username']} ya existe, saltando...")
            continue

        # Buscar departamento
        dept = Department.query.filter_by(code=user_data['department_code']).first()
        if not dept:
            click.echo(f"  ❌ Departamento {user_data['department_code']} no encontrado", err=True)
            continue

        # Generar contraseña aleatoria
        password = generate_random_password(12)

        # Crear usuario
        user = User(
            username=user_data['username'],
            email=user_data['email'],
            first_name=user_data['first_name'],
            last_name=user_data['last_name'],
            department_id=dept.id,
            is_active=True,
            must_change_password=True  # ✅ FORZAR cambio en primer login
        )
        user.set_nip(password)  # Hashear contraseña

        db.session.add(user)
        created_users.append(user)

        # Guardar credenciales para exportar
        credentials.append({
            'username': user.username,
            'email': user.email,
            'password': password,
            'role': user_data['role']
        })

        click.echo(f"  ✅ Usuario {user.username} creado")

    db.session.commit()

    # Exportar credenciales si se solicita
    if output_csv:
        import csv
        with open(output_csv, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=['username', 'email', 'password', 'role'])
            writer.writeheader()
            writer.writerows(credentials)

        click.echo(f"\n📄 Credenciales guardadas en: {output_csv}")
        click.echo("⚠️  IMPORTANTE: Enviar este archivo de forma segura a cada usuario")
        click.echo("⚠️  BORRAR el archivo después de distribuir las contraseñas")

    click.echo(f"\n✨ {len(created_users)} usuarios creados exitosamente")
```

**Uso:**
```bash
# Crear usuarios con contraseñas aleatorias
flask seed-users --output-csv usuarios_iniciales.csv

# Archivo CSV generado:
# username,email,password,role
# francisco.saucedo,francisco.saucedo@...,Xy9$mK2pQw3L,director
# juan.perez,juan.perez@...,aB8#nP5tRv4M,jefe_departamento
```

**Proceso seguro:**
1. Ejecutar `flask seed-users --output-csv temp_passwords.csv`
2. Enviar contraseñas por canal seguro (email encriptado, mensaje directo)
3. **BORRAR** `temp_passwords.csv` inmediatamente
4. Usuarios cambian contraseña en primer login (`must_change_password=TRUE`)

**ELIMINAR 07_insert_user.sql:**
```bash
# Marcar como deprecado
mv database/DML/core/07_insert_user.sql database/DML/core/07_insert_user.sql.DEPRECATED

# Actualizar lista en commands.py (quitar de la lista)
```

**Esfuerzo estimado:** Medio (3 horas)
**Impacto:** CRÍTICO (elimina vulnerabilidad de seguridad)
**Riesgo:** Bajo (proceso controlado)

---

### 3. **Implementar transacciones con rollback automático**

**Problema:**
Si un script falla a mitad de ejecución, la BD queda en estado inconsistente.

**Ejemplo:**
```
✅ 00_insert_apps.sql - OK
✅ 01_insert_departments.sql - OK
✅ 02_insert_positions.sql - OK
❌ 03_insert_icons_deparments.sql - ERROR
⏸️  04_insert_roles.sql - NO EJECUTADO
⏸️  05_insert_permissions.sql - NO EJECUTADO
```

Resultado: BD tiene apps, departments, positions pero **sin roles ni permisos** → sistema roto.

**Solución: Transacción global con savepoints**

```python
# itcj/core/commands.py
from sqlalchemy import text

@click.command('init-db')
@click.option('--dry-run', is_flag=True, help='Simular ejecución sin aplicar cambios')
@click.option('--continue-on-error', is_flag=True, help='Continuar si hay errores no críticos')
@with_appcontext
def init_db(dry_run, continue_on_error):
    """Inicializar base de datos con datos semilla (transaccional)."""
    click.echo("🔄 Inicializando base de datos con datos semilla...")

    if dry_run:
        click.echo("🧪 MODO DRY-RUN: No se aplicarán cambios reales\n")

    executed_scripts = []
    failed_scripts = []

    # Definir scripts críticos (no pueden fallar)
    CRITICAL_SCRIPTS = [
        'core/00_insert_apps.sql',
        'core/04_insert_roles.sql',
        'core/05_insert_permissions.sql'
    ]

    sql_directories = [
        # ... (igual que antes) ...
    ]

    # Iniciar transacción global
    connection = db.session.connection()

    try:
        for directory, module, sql_files in sql_directories:
            click.echo(f"\n📂 Módulo: {module}")

            for sql_file in sql_files:
                file_path = os.path.join(directory, sql_file)
                script_key = f"{module}/{sql_file}"

                if not os.path.exists(file_path):
                    click.echo(f"  ⚠️  {sql_file} - No encontrado", err=True)
                    continue

                # Crear savepoint para este script
                savepoint_name = f"sp_{module}_{sql_file.replace('.', '_')}"

                try:
                    # Savepoint
                    if not dry_run:
                        connection.execute(text(f"SAVEPOINT {savepoint_name}"))

                    # Leer y ejecutar script
                    with open(file_path, 'r', encoding='utf-8') as f:
                        sql_content = f.read()

                    if not dry_run:
                        connection.execute(text(sql_content))
                        connection.execute(text(f"RELEASE SAVEPOINT {savepoint_name}"))

                    click.echo(f"  ✅ {sql_file}")
                    executed_scripts.append(script_key)

                except Exception as e:
                    # Rollback a savepoint
                    if not dry_run:
                        connection.execute(text(f"ROLLBACK TO SAVEPOINT {savepoint_name}"))

                    error_msg = str(e).split('\n')[0]  # Primera línea del error
                    click.echo(f"  ❌ {sql_file} - {error_msg}", err=True)
                    failed_scripts.append((script_key, error_msg))

                    # Si es script crítico, abortar TODO
                    if script_key in CRITICAL_SCRIPTS:
                        click.echo(f"\n🛑 Script CRÍTICO falló: {sql_file}", err=True)
                        click.echo("   Abortando inicialización completa...", err=True)
                        raise

                    # Si no es crítico y --continue-on-error, continuar
                    if not continue_on_error:
                        click.echo("\n⚠️  Use --continue-on-error para ignorar errores no críticos", err=True)
                        raise

        # Commit final
        if dry_run:
            click.echo("\n🧪 DRY-RUN completado. No se aplicaron cambios.")
            db.session.rollback()
        else:
            db.session.commit()
            click.echo(f"\n✨ Inicialización completada:")
            click.echo(f"  ✅ Scripts ejecutados: {len(executed_scripts)}")

        if failed_scripts:
            click.echo(f"  ⚠️  Scripts fallidos (no críticos): {len(failed_scripts)}")
            for script, error in failed_scripts:
                click.echo(f"     - {script}: {error}")

    except Exception as e:
        # Rollback global
        db.session.rollback()
        click.echo(f"\n💥 Error fatal. Todos los cambios fueron revertidos.", err=True)
        click.echo(f"   Error: {e}", err=True)
        sys.exit(1)
```

**Uso:**
```bash
# Modo dry-run (prueba sin aplicar cambios)
flask init-db --dry-run

# Ejecución normal (aborta en primer error)
flask init-db

# Continuar aunque haya errores no críticos
flask init-db --continue-on-error
```

**Esfuerzo estimado:** Medio (4 horas)
**Impacto:** Muy Alto (consistencia de BD garantizada)
**Riesgo:** Bajo

---

### 4. **Eliminar IDs hardcodeados, usar claves naturales**

**Problema:**
Algunos scripts usan IDs hardcodeados en lugar de claves naturales:

```sql
-- ❌ MAL: ID hardcodeado
INSERT INTO core_user_app_roles (user_id, app_id, role_id)
VALUES (1, 1, 1);  -- Frágil! Si sequences cambian, falla

-- ✅ BIEN: Usar subqueries con claves naturales
INSERT INTO core_user_app_roles (user_id, app_id, role_id)
SELECT
    (SELECT id FROM core_users WHERE username = 'admin'),
    (SELECT id FROM core_apps WHERE key = 'itcj'),
    (SELECT id FROM core_roles WHERE name = 'super_admin')
WHERE NOT EXISTS (
    SELECT 1 FROM core_user_app_roles WHERE ...
);
```

**Auditar todos los scripts:**

```bash
# Buscar IDs hardcodeados
grep -r "VALUES ([0-9]" database/DML/
grep -r "= [0-9]\+)" database/DML/
```

**Patrón correcto:**

```sql
-- Template para inserts seguros
INSERT INTO tabla_destino (fk_id, campo1, campo2)
SELECT
    (SELECT id FROM tabla_referencia WHERE clave_natural = 'valor'),
    'valor1',
    'valor2'
WHERE NOT EXISTS (
    SELECT 1 FROM tabla_destino WHERE campo_unico = 'valor'
);
```

**Esfuerzo estimado:** Alto (revisar 25 archivos)
**Impacto:** Alto (robustez)
**Riesgo:** Bajo

---

## 🔥 PRIORIDAD ALTA

### 5. **Agregar validaciones previas a init-db**

**Problema:**
No se valida el estado de la BD antes de ejecutar scripts.

**Solución: Pre-flight checks**

```python
# itcj/core/commands.py
def validate_database_state():
    """Validar que la BD está lista para inicialización."""
    issues = []

    # 1. Verificar que migraciones estén aplicadas
    try:
        from alembic.script import ScriptDirectory
        from alembic.runtime.migration import MigrationContext

        engine = db.engine
        context = MigrationContext.configure(engine.connect())
        current_rev = context.get_current_revision()

        script_dir = ScriptDirectory('migrations')
        head_rev = script_dir.get_current_head()

        if current_rev != head_rev:
            issues.append(f"Migraciones pendientes. Actual: {current_rev}, Esperado: {head_rev}")
            issues.append("Ejecutar: flask db upgrade")
    except Exception as e:
        issues.append(f"Error al verificar migraciones: {e}")

    # 2. Verificar que tablas existen
    inspector = db.inspect(db.engine)
    required_tables = [
        'core_apps',
        'core_departments',
        'core_roles',
        'core_permissions',
        'core_users'
    ]

    for table in required_tables:
        if table not in inspector.get_table_names():
            issues.append(f"Tabla requerida no existe: {table}")

    # 3. Verificar que BD está vacía (o permitir re-ejecución)
    apps_count = db.session.query(func.count(App.id)).scalar()
    if apps_count > 0:
        issues.append(f"La BD ya contiene datos ({apps_count} apps)")
        issues.append("Use --force para re-ejecutar (⚠️ puede duplicar datos)")

    return issues


@click.command('init-db')
@click.option('--force', is_flag=True, help='Forzar ejecución aunque haya datos')
@click.option('--dry-run', is_flag=True, help='Simular sin aplicar cambios')
@with_appcontext
def init_db(force, dry_run):
    """Inicializar BD con validaciones previas."""
    click.echo("🔍 Validando estado de la base de datos...")

    issues = validate_database_state()

    if issues:
        click.echo("\n⚠️  Problemas encontrados:")
        for issue in issues:
            click.echo(f"  - {issue}")

        if not force:
            click.echo("\n🛑 Abortando. Use --force para continuar de todas formas.")
            sys.exit(1)
        else:
            click.echo("\n⚠️  Continuando con --force...")

    click.echo("✅ Validación completada\n")

    # ... resto del código de inicialización ...
```

**Esfuerzo estimado:** Medio (3 horas)
**Impacto:** Alto (previene errores)
**Riesgo:** Muy Bajo

---

### 6. **Separar datos de prueba de datos de producción**

**Problema:**
50+ usuarios de prueba mezclados con datos reales.

**Solución: Scripts separados**

```
database/DML/
├── core/
│   ├── required/  # Scripts SIEMPRE ejecutados
│   │   ├── 00_insert_apps.sql
│   │   ├── 01_insert_departments.sql
│   │   ├── 04_insert_roles.sql
│   │   └── 05_insert_permissions.sql
│   │
│   ├── production/  # Solo en producción
│   │   ├── 02_insert_positions.sql
│   │   └── 06_insert_role_permissions.sql
│   │
│   └── development/  # Solo en desarrollo/testing
│       ├── 07_insert_test_users.sql
│       ├── 08_insert_test_positions.sql
│       └── 09_insert_test_assignments.sql
```

```python
# itcj/core/commands.py
@click.command('init-db')
@click.option('--env', type=click.Choice(['development', 'production']), help='Ambiente')
@with_appcontext
def init_db(env):
    """Inicializar BD según ambiente."""
    if not env:
        env = current_app.config.get('ENV', 'development')

    click.echo(f"🌍 Ambiente: {env}")

    # Scripts que SIEMPRE se ejecutan
    required_scripts = [
        ('database/DML/core/required', 'core', [...]),
    ]

    # Scripts según ambiente
    if env == 'production':
        env_scripts = [
            ('database/DML/core/production', 'core', [...]),
        ]
    else:
        env_scripts = [
            ('database/DML/core/development', 'core', [...]),
        ]

    all_scripts = required_scripts + env_scripts

    # Ejecutar...
```

**Esfuerzo estimado:** Alto (6 horas - reorganizar scripts)
**Impacto:** Alto (claridad, seguridad)
**Riesgo:** Medio (cambio estructural)

---

### 7. **Agregar versionado de scripts**

**Problema:**
No se puede rastrear qué versión de scripts se usó para inicializar la BD.

**Solución: Tabla de metadata**

```sql
-- Migración: add_dml_version_table.py
CREATE TABLE core_dml_metadata (
    id SERIAL PRIMARY KEY,
    script_name VARCHAR(200) NOT NULL,
    script_version VARCHAR(50),
    executed_at TIMESTAMP DEFAULT NOW(),
    checksum VARCHAR(64),  -- SHA256 del contenido del script
    success BOOLEAN DEFAULT TRUE,
    error_message TEXT
);

CREATE INDEX ix_dml_metadata_script ON core_dml_metadata(script_name);
```

```python
# itcj/core/commands.py
import hashlib

def get_file_checksum(file_path):
    """Calcular SHA256 del archivo."""
    sha256 = hashlib.sha256()
    with open(file_path, 'rb') as f:
        sha256.update(f.read())
    return sha256.hexdigest()


def record_script_execution(script_name, success, error_msg=None, checksum=None):
    """Registrar ejecución de script."""
    from itcj.core.models import DMLMetadata  # Crear modelo

    metadata = DMLMetadata(
        script_name=script_name,
        script_version='1.0',  # O leer de git tag
        checksum=checksum,
        success=success,
        error_message=error_msg
    )
    db.session.add(metadata)
    db.session.commit()


# En init_db, después de ejecutar cada script:
checksum = get_file_checksum(file_path)
record_script_execution(script_key, success=True, checksum=checksum)
```

**Beneficios:**
- Auditoría completa de inicialización
- Detectar si scripts cambiaron desde último init
- Prevenir re-ejecución accidental

**Esfuerzo estimado:** Medio (3 horas)
**Impacto:** Medio (auditoría)
**Riesgo:** Bajo

---

## ⚠️ PRIORIDAD MEDIA

### 8. **Convertir scripts SQL a Python (Flask-Seeder)**

**Problema:**
SQL estático es difícil de mantener, no permite lógica condicional.

**Alternativa: Seeders en Python**

```bash
pip install flask-seeder
```

```python
# itcj/core/seeders/app_seeder.py
from flask_seeder import Seeder
from itcj.core.models import App

class AppSeeder(Seeder):
    """Seeder para aplicaciones."""

    def run(self):
        apps = [
            {'key': 'itcj', 'name': 'ITCJ Core', 'is_active': True},
            {'key': 'agendatec', 'name': 'AgendaTec', 'is_active': True},
            {'key': 'helpdesk', 'name': 'Help Desk', 'is_active': True},
        ]

        for app_data in apps:
            # Buscar o crear
            app = App.query.filter_by(key=app_data['key']).first()

            if not app:
                app = App(**app_data)
                self.db.session.add(app)
                print(f"  ✅ App creada: {app.name}")
            else:
                print(f"  ⚠️  App ya existe: {app.name}")

        self.db.session.commit()
```

**Ventajas:**
- Lógica condicional (if/else)
- Generación dinámica de datos
- Testing más fácil
- Type checking con IDEs

**Desventajas:**
- Más verboso que SQL
- Requiere aprender nueva librería

**Esfuerzo estimado:** Muy Alto (migrar 25 archivos)
**Impacto:** Medio (mantenibilidad)
**Riesgo:** Alto (cambio arquitectónico)

---

### 9. **Agregar tests de integración para scripts**

**Problema:**
Scripts solo se prueban manualmente.

**Solución: Tests automatizados**

```python
# tests/integration/test_dml_scripts.py
import pytest
from itcj import create_app, db
from itcj.core.models import App, Role, Permission, User

@pytest.fixture
def clean_db():
    """BD limpia para testing."""
    app = create_app('testing')
    with app.app_context():
        db.create_all()
        yield db
        db.session.remove()
        db.drop_all()


def test_init_db_creates_apps(clean_db):
    """Test: init-db crea las 3 apps."""
    # Ejecutar comando
    runner = app.test_cli_runner()
    result = runner.invoke(args=['init-db'])

    assert result.exit_code == 0

    # Verificar apps
    apps = App.query.all()
    assert len(apps) == 3

    app_keys = [app.key for app in apps]
    assert 'itcj' in app_keys
    assert 'agendatec' in app_keys
    assert 'helpdesk' in app_keys


def test_init_db_creates_roles(clean_db):
    """Test: init-db crea los roles base."""
    runner = app.test_cli_runner()
    runner.invoke(args=['init-db'])

    roles = Role.query.all()
    assert len(roles) >= 8  # Al menos 8 roles base

    role_names = [role.name for role in roles]
    assert 'staff' in role_names
    assert 'super_admin' in role_names


def test_init_db_idempotent(clean_db):
    """Test: init-db se puede ejecutar múltiples veces."""
    runner = app.test_cli_runner()

    # Primera ejecución
    result1 = runner.invoke(args=['init-db'])
    assert result1.exit_code == 0

    apps_count_1 = App.query.count()

    # Segunda ejecución
    result2 = runner.invoke(args=['init-db', '--force'])
    assert result2.exit_code == 0

    apps_count_2 = App.query.count()

    # No debe duplicar datos
    assert apps_count_1 == apps_count_2


def test_init_db_rollback_on_error(clean_db):
    """Test: Si falla un script, se hace rollback completo."""
    # TODO: Simular error en script específico
    pass


def test_script_dependencies_respected(clean_db):
    """Test: Scripts se ejecutan en orden correcto."""
    # Verificar que no hay errores de FK
    runner = app.test_cli_runner()
    result = runner.invoke(args=['init-db'])

    assert result.exit_code == 0
    assert 'FK constraint' not in result.output
```

**Ejecutar:**
```bash
pytest tests/integration/test_dml_scripts.py -v
```

**Esfuerzo estimado:** Alto (8 horas)
**Impacto:** Alto (previene regresiones)
**Riesgo:** Bajo

---

### 10. **Optimizar scripts grandes**

**Problema:**
`07_insert_user.sql` tiene 50+ usuarios con INSERT individual.

**Optimización: Batch inserts**

```sql
-- ❌ LENTO: 50 INSERTs individuales
INSERT INTO core_users (...) SELECT ... WHERE NOT EXISTS ...;
INSERT INTO core_users (...) SELECT ... WHERE NOT EXISTS ...;
-- ... 50 veces

-- ✅ RÁPIDO: Un solo INSERT con múltiples VALUES
INSERT INTO core_users (username, email, first_name, last_name, department_id, password_hash, must_change_password, is_active)
SELECT * FROM (VALUES
    ('user1', 'user1@example.com', 'User', 'One', (SELECT id FROM core_departments WHERE code = 'DIR'), 'hash', TRUE, TRUE),
    ('user2', 'user2@example.com', 'User', 'Two', (SELECT id FROM core_departments WHERE code = 'SIS'), 'hash', TRUE, TRUE),
    -- ... más usuarios
) AS users(username, email, first_name, last_name, department_id, password_hash, must_change_password, is_active)
WHERE NOT EXISTS (
    SELECT 1 FROM core_users WHERE core_users.username = users.username
);
```

**Ganancia:** 50 queries → 1 query

**Esfuerzo estimado:** Medio (2 horas por script)
**Impacto:** Medio (velocidad de inicialización)
**Riesgo:** Bajo

---

## 📝 PRIORIDAD BAJA (Mejoras futuras)

### 11. **Migrar a Alembic data migrations**

**Alternativa:** Usar migraciones de Alembic para datos semilla.

**Esfuerzo:** Muy Alto | **Impacto:** Medio | **Riesgo:** Alto

---

### 12. **Agregar comando para reset de BD**

```bash
flask reset-db  # Drop all → migrate → seed
```

**Esfuerzo:** Bajo | **Impacto:** Bajo | **Riesgo:** Muy Bajo

---

### 13. **Exportar/Importar configuración**

```bash
flask export-config > config.json
flask import-config config.json
```

**Esfuerzo:** Medio | **Impacto:** Bajo | **Riesgo:** Bajo

---

## 📊 ANÁLISIS ESPECÍFICO DE ARCHIVOS

### 12_insert_configure_moodle_custom_fields.sql

**Descripción:**
Archivo más reciente (mencionado por usuario), configura campos personalizados para tickets de Moodle.

**Contenido:**
```sql
INSERT INTO helpdesk_categories (name, description, active)
SELECT 'dev_moodle', 'Tickets para desarrollo en Moodle', TRUE
WHERE NOT EXISTS (SELECT 1 FROM helpdesk_categories WHERE name = 'dev_moodle');

-- Campo: is_moodle_course (checkbox)
INSERT INTO helpdesk_custom_fields (category_id, name, label, field_type, required, ...)
SELECT
    (SELECT id FROM helpdesk_categories WHERE name = 'dev_moodle'),
    'is_moodle_course',
    '¿El ticket está relacionado con un curso de Moodle?',
    'checkbox',
    TRUE,
    ...
WHERE NOT EXISTS (...);

-- Campo: course_name (visible si checkbox = TRUE)
-- ... configuración de visibilidad condicional
```

**Calidad:** ⭐⭐⭐⭐ (4/5)
- ✅ Usa ON CONFLICT
- ✅ Subqueries para FKs
- ✅ Configuración JSONB bien estructurada
- ✅ Campos condicionales (visible_when)
- ⚠️ Muy específico (podría parametrizarse)

**Mejoras sugeridas:**
1. Parametrizar nombre de categoría
2. Separar en categoría + campos (2 scripts)
3. Agregar comentarios explicando lógica condicional

---

## 📊 RESUMEN DE PRIORIDADES

### Crítico / Urgente (Sprint 1: Semana 1-2)
| # | Mejora | Esfuerzo | Impacto | Riesgo |
|---|--------|----------|---------|--------|
| 1 | Documentar dependencias | Muy Bajo | Muy Alto | Ninguno |
| 2 | Eliminar contraseñas hardcodeadas | Medio | CRÍTICO | Bajo |
| 3 | Transacciones con rollback | Medio | Muy Alto | Bajo |
| 4 | Eliminar IDs hardcodeados | Alto | Alto | Bajo |

**Ganancia:** BD consistente, segura, robusta

---

### Alta (Sprint 2-3: Semana 3-6)
| # | Mejora | Esfuerzo | Impacto |
|---|--------|----------|---------|
| 5 | Validaciones pre-init | Medio | Alto |
| 6 | Separar test/prod | Alto | Alto |
| 7 | Versionado de scripts | Medio | Medio |

**Ganancia:** Auditoría, claridad, prevención de errores

---

### Media (Sprint 4-5: Semana 7-10)
| # | Mejora | Esfuerzo | Impacto |
|---|--------|----------|---------|
| 8 | Migrar a Python seeders | Muy Alto | Medio |
| 9 | Tests de integración | Alto | Alto |
| 10 | Optimizar batch inserts | Medio | Medio |

**Ganancia:** Mantenibilidad, testing automatizado

---

## 🎯 PLAN DE ACCIÓN RECOMENDADO

### **Semana 1: Documentación & Seguridad**
**Día 1:**
- [ ] Crear README.md con grafo de dependencias (2 horas)
- [ ] Documentar cada script (qué hace, dependencias) (4 horas)

**Día 2-3:**
- [ ] Crear comando `flask seed-users` con contraseñas aleatorias (4 horas)
- [ ] Marcar 07_insert_user.sql como deprecado (30 min)
- [ ] Testing de creación de usuarios (2 horas)

**Día 4-5:**
- [ ] Implementar validación de dependencias en init-db (4 horas)
- [ ] Testing de validación (2 horas)

### **Semana 2: Robustez**
**Día 1-2:**
- [ ] Implementar transacciones con savepoints (4 horas)
- [ ] Agregar --dry-run flag (2 horas)
- [ ] Testing de rollback (2 horas)

**Día 3-5:**
- [ ] Auditar IDs hardcodeados en 25 scripts (6 horas)
- [ ] Convertir a subqueries (6 horas)
- [ ] Testing exhaustivo (4 horas)

### **Semana 3-4: Validaciones & Versionado**
- [ ] Pre-flight checks (validar migraciones, tablas) (3 horas)
- [ ] Tabla de metadata + registro de ejecuciones (3 horas)
- [ ] Separar scripts test/prod (6 horas)
- [ ] Testing integración (4 horas)

---

## 📚 RECURSOS

### PostgreSQL
- **Transactions:** https://www.postgresql.org/docs/14/tutorial-transactions.html
- **Savepoints:** https://www.postgresql.org/docs/14/sql-savepoint.html

### Flask
- **CLI Commands:** https://flask.palletsprojects.com/en/2.3.x/cli/
- **Flask-Seeder:** https://github.com/diddi-/flask-seeder

### Testing
- **Pytest:** https://docs.pytest.org/

---

**Última actualización:** 2025-12-12
**Criticidad:** ALTA - Scripts se ejecutan UNA VEZ
**Versión documento:** 1.0
