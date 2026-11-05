"""Plantilla de configuración. Copiar a `instance/config.py` y completar.

`instance/config.py` NO se versiona (ver .gitignore): guarda secretos y no se
pisa al actualizar el código.

Uso:
    cp config.example.py instance/config.py
    chmod 600 instance/config.py

Este archivo usa los mismos nombres de clave (MAYÚSCULAS) que `app/config.py`
espera. Solo hace falta definir lo que se quiera sobreescribir.
"""

# --- BRAS ---------------------------------------------------------------
BRAS_HOST = "192.0.2.10"          # IP/hostname del BRAS
BRAS_PORT = 22
BRAS_USER = "monitor"
BRAS_PASSWORD = "CAMBIAR"
BRAS_SECRET = ""                  # password de enable (si aplica)
BRAS_DEVICE_TYPE = "huawei"
BRAS_CONN_TIMEOUT = 15
BRAS_READ_TIMEOUT = 30

COMMAND_TEMPLATE = "display access-user username {username} verbose nop | no-more"
USERNAME_REGEX = r"^[A-Za-z0-9][A-Za-z0-9._@-]{0,63}$"

# --- Auth / JWT ---------------------------------------------------------
# Generar con: python -c "import secrets; print(secrets.token_urlsafe(48))"
JWT_SECRET = "CAMBIAR-POR-UN-SECRETO-LARGO-Y-ALEATORIO"
JWT_ALG = "HS256"
ACCESS_TTL = 3600                 # segundos
REFRESH_TTL = 86400               # segundos
COOKIE_SECURE = False             # True detrás de HTTPS

# --- Base de usuarios ---------------------------------------------------
# Por defecto: backend/instance/bras_monitor.db
# DATABASE_PATH = "/ruta/absoluta/a/bras_monitor.db"

# --- Monitor / lease ----------------------------------------------------
MAX_SESIONES = 1
POLL_INTERVAL = 5
SESSION_TTL = 600
DISCONNECT_GRACE = 10
HEARTBEAT_TTL = 45

# --- Unidades / mapeo de dirección -------------------------------------
KBYTE_UNIT_BYTES = 1024
KBYTE_TIME_BASE = 60
DIR_UP = "inbound"                # inbound = subida (punto de vista del BRAS)
DIR_DOWN = "outbound"             # outbound = bajada
SAMPLE_MODE = "on_change"         # on_change | every_poll

# --- Búsqueda de usuarios online (autocompletado) -----------------------
# Webservice de dialup (HTTP interno, sin autenticación). Se consulta desde
# el backend para evitar CORS/contenido mixto en el navegador.
ONLINE_USERS_URL = "http://10.10.10.2/dialup2/webserv/"
ONLINE_USERS_NAS_IP = "200.49.120.10"
ONLINE_USERS_TIMEOUT = 5.0

# --- CORS (apps externas en otro origen) --------------------------------
CORS_ORIGINS = []

# --- Frontend (solo desarrollo) -----------------------------------------
# En producción nginx sirve frontend/. En dev se puede montar desde FastAPI.
SERVE_FRONTEND = False
# FRONTEND_DIR = "/ruta/a/monitor-pppoe/frontend"
