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
HISTORY_LIMIT = 5
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

# --- Muestreo -----------------------------------------------------------
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

# --- NETCONF -------------------------------------------------------------
NETCONF_HOST = BRAS_HOST
NETCONF_PORT = 830
NETCONF_USER = "CAMBIAR"
NETCONF_PASSWORD = "CAMBIAR"
NETCONF_TIMEOUT = 10

# --- SNMP ----------------------------------------------------------------
SNMP_HOST = BRAS_HOST
SNMP_VERSION = 2
SNMP_PORT = 161
SNMP_COMMUNITY = "CAMBIAR"
SNMP_TIMEOUT = 2
SNMP_RETRIES = 1
SNMP_POLL_INTERVAL = 5
