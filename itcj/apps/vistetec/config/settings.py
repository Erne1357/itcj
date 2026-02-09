# Categorías de prendas disponibles
GARMENT_CATEGORIES = [
    'camisa', 'pantalon', 'vestido', 'falda', 'chamarra',
    'sueter', 'zapatos', 'tenis', 'accesorios', 'otro',
]

# Géneros disponibles
GARMENT_GENDERS = ['masculino', 'femenino', 'unisex']

# Condiciones de prenda
GARMENT_CONDITIONS = ['nuevo', 'como_nuevo', 'buen_estado', 'usado']

# Estados de prenda
GARMENT_STATUSES = ['available', 'reserved', 'delivered', 'withdrawn']

# Estados de cita
APPOINTMENT_STATUSES = ['scheduled', 'attended', 'no_show', 'cancelled', 'completed']

# Resultados de cita
APPOINTMENT_OUTCOMES = ['taken', 'not_fit', 'declined']

# Tipos de donación
DONATION_TYPES = ['garment', 'pantry']

# Categorías de despensa
PANTRY_CATEGORIES = ['enlatados', 'granos', 'higiene', 'limpieza', 'mascotas', 'otro']

# Extensiones de imagen permitidas
ALLOWED_IMAGE_EXTENSIONS = {'jpg', 'jpeg', 'png', 'webp'}

# Tamaño máximo de imagen (10 MB - cliente comprime, servidor re-comprime)
MAX_IMAGE_SIZE = 10 * 1024 * 1024
