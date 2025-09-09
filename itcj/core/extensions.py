
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_socketio import SocketIO

# Inicialización de las extensiones
db = SQLAlchemy()            # Para manejar la base de datos
migrate = Migrate()          # Para las migraciones de base de datos
socketio = SocketIO()        # Para manejar WebSockets
