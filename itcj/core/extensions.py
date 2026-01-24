
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate

# Inicialización de las extensiones
db = SQLAlchemy()            # Para manejar la base de datos
migrate = Migrate()          # Para las migraciones de base de datos

# SocketIO instance - se asigna en init_socketio()
socketio = None
