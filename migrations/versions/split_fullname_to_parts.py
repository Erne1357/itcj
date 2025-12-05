"""Split full_name into first_name, last_name, middle_name

Revision ID: split_fullname_to_parts
Revises: 8961531fbe52
Create Date: 2025-12-02 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
import csv
import os

# revision identifiers, used by Alembic.
revision = 'split_fullname_to_parts'
down_revision = '8961531fbe52'
branch_labels = None
depends_on = None


def upgrade():
    # Agregar las nuevas columnas (temporalmente nullables para migración)
    op.add_column('core_users', sa.Column('first_name', sa.Text(), nullable=True))
    op.add_column('core_users', sa.Column('last_name', sa.Text(), nullable=True))
    op.add_column('core_users', sa.Column('middle_name', sa.Text(), nullable=True))
    
    # Leer el CSV de activos
    # Intentar múltiples rutas posibles
    possible_paths = [
        os.path.join(os.path.dirname(__file__), '..', '..', 'database', 'CSV', 'Activos.csv'),  # Ruta relativa
        '/app/database/CSV/Activos.csv',  # Ruta absoluta en Docker
        os.path.join(os.getcwd(), 'database', 'CSV', 'Activos.csv'),  # Desde directorio de trabajo
    ]
    
    csv_path = None
    for path in possible_paths:
        if os.path.exists(path):
            csv_path = path
            break
    
    csv_data = {}
    
    if csv_path:
        # Intentar diferentes encodings
        encodings = ['utf-8', 'utf-8-sig', 'latin-1', 'cp1252']
        
        for encoding in encodings:
            try:
                with open(csv_path, 'r', encoding=encoding) as f:
                    lines = f.readlines()
                
                # Leer header
                header = lines[0].strip().split(';')
                required_cols = ['no_de_control', 'apellido_paterno', 'apellido_materno', 'nombre_alumno']
                missing_cols = [col for col in required_cols if col not in header]
                
                if missing_cols:
                    continue
                
                # Obtener índices
                idx_control = header.index('no_de_control')
                idx_paterno = header.index('apellido_paterno')
                idx_materno = header.index('apellido_materno')
                idx_nombre = header.index('nombre_alumno')
                
                # Procesar filas
                for line in lines[1:]:
                    if not line.strip():
                        continue
                    
                    cols = line.strip().split(';')
                    if len(cols) > max(idx_control, idx_paterno, idx_materno, idx_nombre):
                        control = cols[idx_control].strip()
                        paterno = cols[idx_paterno].strip()
                        materno = cols[idx_materno].strip()
                        nombre = cols[idx_nombre].strip()
                        
                        csv_data[control] = {
                            'first_name': nombre.upper() if nombre else '',
                            'last_name': paterno.upper() if paterno else '',
                            'middle_name': materno.upper() if materno else None
                        }
                
                break
                
            except Exception:
                continue
    
    # Obtener conexión
    connection = op.get_bind()
    
    # Verificar si existe la columna full_name
    has_full_name = False
    try:
        result = connection.execute(sa.text("""
            SELECT column_name FROM information_schema.columns 
            WHERE table_name = 'core_users' AND column_name = 'full_name'
        """))
        has_full_name = result.fetchone() is not None
    except:
        pass
    
    # Obtener todos los usuarios
    if has_full_name:
        query = "SELECT id, username, control_number, full_name FROM core_users"
    else:
        query = "SELECT id, username, control_number FROM core_users"
    
    result = connection.execute(sa.text(query))
    users = result.fetchall()
    mapped_count = 0
    unmapped_users = []
    
    for user in users:
        user_id = user[0]
        username = user[1]
        control_number = user[2]
        full_name_old = user[3] if has_full_name and len(user) > 3 else None
        
        mapped = False
        match_type = None
        data = None
        
        # Intentar mapear por control_number (números de 8 dígitos)
        if control_number:
            # Buscar exacto
            if control_number in csv_data:
                data = csv_data[control_number]
                match_type = f"control_number exact: {control_number}"
                mapped = True
            # Buscar sin espacios/padding
            elif control_number.strip() in csv_data:
                data = csv_data[control_number.strip()]
                match_type = f"control_number stripped: {control_number.strip()}"
                mapped = True
        
        # Intentar mapear por username (puede tener letras, ej: D21111182)
        if not mapped and username:
            # Buscar exacto
            if username in csv_data:
                data = csv_data[username]
                match_type = f"username exact: {username}"
                mapped = True
            # Buscar en mayúsculas
            elif username.upper() in csv_data:
                data = csv_data[username.upper()]
                match_type = f"username upper: {username.upper()}"
                mapped = True
        
        # NO usar full_name como fallback - solo mapear usuarios que estén en el CSV
        # Los usuarios que no estén en el CSV quedarán sin mapear para procesamiento manual
        
        # Si se encontró coincidencia, actualizar
        if mapped and data:
            try:
                connection.execute(sa.text("""
                    UPDATE core_users 
                    SET first_name = :first_name,
                        last_name = :last_name,
                        middle_name = :middle_name
                    WHERE id = :user_id
                """), {
                    'first_name': data['first_name'],
                    'last_name': data['last_name'],
                    'middle_name': data['middle_name'],
                    'user_id': user_id
                })
                mapped_count += 1
            except Exception:
                mapped = False
        
        # Si no se pudo mapear, guardar para procesamiento manual
        if not mapped:
            unmapped_users.append({
                'id': user_id,
                'username': username,
                'control_number': control_number,
                'full_name': full_name_old
            })
    
    # Mapear usuarios administrativos manualmente (no están en el CSV)
    admin_mappings = {
        'msifuentes': {'first_name': 'MARIA DE LOS ANGELES', 'last_name': 'SIFUENTES', 'middle_name': 'MARTÍNEZ'},
        'marroyo': {'first_name': 'MARTÍN DAVID', 'last_name': 'ARROYO', 'middle_name': 'LECHUGA'},
        'jrivera': {'first_name': 'JESUS', 'last_name': 'RIVERA', 'middle_name': 'HURTADO'},
        'pcardona': {'first_name': 'PERLA IVONNE', 'last_name': 'CARDONA', 'middle_name': 'SALAIS'},
        'flira': {'first_name': 'FELIX ALFONSO', 'last_name': 'LIRA', 'middle_name': 'CASAS'},
        'acordero': {'first_name': 'ANA VERONICA', 'last_name': 'CORDERO', 'middle_name': 'BALIND'},
        'gsaenz': {'first_name': 'GERARDO ALONSO', 'last_name': 'SAENZ', 'middle_name': 'RAMIREZ'},
        'jvillanueva': {'first_name': 'JESUS MARIA', 'last_name': 'VILLANUEVA', 'middle_name': 'GAMERO'},
        'servicio_social': {'first_name': 'SERVICIO', 'last_name': 'SOCIAL', 'middle_name': None},
        'evillarreal': {'first_name': 'ERNESTO', 'last_name': 'VILLARREAL', 'middle_name': 'IBARRA'},
        'rcera': {'first_name': 'ROSA SILVANA', 'last_name': 'CERA', 'middle_name': 'GAYTÁN'},
        'jnevarez': {'first_name': 'JESUS ELEAZAR', 'last_name': 'NEVAREZ', 'middle_name': 'VAZQUEZ'},
        'jchavez': {'first_name': 'JANETH SARAHÍ', 'last_name': 'CHÁVEZ', 'middle_name': 'RODARTE'},
        'jrodriguez': {'first_name': 'JEOVANY RAFAEL', 'last_name': 'RODRÍGUEZ', 'middle_name': 'MEJÍA'},
        'ydozal': {'first_name': 'YADIRA', 'last_name': 'DOZAL', 'middle_name': 'ASSMAR'},
        'aflores': {'first_name': 'ANILÚ', 'last_name': 'FLORES', 'middle_name': 'REGALADO'},
    }
    
    admin_mapped = 0
    still_unmapped = []
    
    for user_info in unmapped_users:
        username = user_info['username']
        user_id = user_info['id']
        control_number = user_info['control_number']
        
        # Intentar mapeo administrativo
        if username and username in admin_mappings:
            admin_data = admin_mappings[username]
            try:
                connection.execute(sa.text("""
                    UPDATE core_users 
                    SET first_name = :first_name,
                        last_name = :last_name,
                        middle_name = :middle_name
                    WHERE id = :user_id
                """), {
                    'first_name': admin_data['first_name'],
                    'last_name': admin_data['last_name'],
                    'middle_name': admin_data['middle_name'],
                    'user_id': user_id
                })
                admin_mapped += 1
            except Exception:
                still_unmapped.append(user_info)
        # Usuario de prueba con control 12345678
        elif control_number == '12345678':
            try:
                connection.execute(sa.text("""
                    UPDATE core_users 
                    SET first_name = :first_name,
                        last_name = :last_name,
                        middle_name = :middle_name
                    WHERE id = :user_id
                """), {
                    'first_name': 'USUARIO',
                    'last_name': 'DE',
                    'middle_name': 'PRUEBA',
                    'user_id': user_id
                })
                admin_mapped += 1
            except Exception:
                still_unmapped.append(user_info)
        else:
            still_unmapped.append(user_info)
    
    unmapped_users = still_unmapped
    
    # Hacer NOT NULL las columnas obligatorias solo si todos fueron mapeados
    if len(unmapped_users) == 0:
        op.alter_column('core_users', 'first_name', nullable=False)
        op.alter_column('core_users', 'last_name', nullable=False)
        
        # Eliminar la columna full_name si existe
        if has_full_name:
            op.drop_column('core_users', 'full_name')


def downgrade():
    # Recrear la columna full_name
    op.add_column('core_users', sa.Column('full_name', sa.Text(), nullable=True))
    
    # Reconstruir full_name a partir de las partes
    connection = op.get_bind()
    connection.execute(sa.text("""
        UPDATE core_users 
        SET full_name = CASE 
            WHEN middle_name IS NOT NULL THEN last_name || ' ' || middle_name || ' ' || first_name
            ELSE last_name || ' ' || first_name
        END
    """))
    
    # Eliminar las nuevas columnas
    op.drop_column('core_users', 'middle_name')
    op.drop_column('core_users', 'last_name')
    op.drop_column('core_users', 'first_name')
