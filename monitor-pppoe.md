# Monitor PPPoE — Documento de diseño

Referencia persistente del proyecto. Reemplaza la memoria de contexto de la sesión:
todo lo necesario para retomar el trabajo está acá.

Archivos de referencia:
- `comando-y-saldida.txt` — comando exacto del BRAS, salida real de ejemplo y datos a mostrar/graficar.

## 0. Estado de implementación

- [x] Paso 1 — scaffold, config loader, auth JWT + SQLite, `/health`, CLI.
- [x] Paso 2 — `bras/client.py` (Netmiko persistente), `bras/parser.py`, tests contra salida real.
- [x] Paso 3 — `LeaseManager` + poller + SSE (gracia, heartbeat, TTL) + endpoints de monitoreo.
- [x] Paso 4 — pulido de OpenAPI (`/api/docs`, tags, descripciones) + tests de endpoints (29 tests).
- [x] Paso 5 — frontend (HTML/CSS/JS + Chart.js) — código completo, falta prueba visual en navegador.
- [x] Paso 6 — deploy: `deploy/backend.service` + `deploy/nginx.conf` listos (falta instalarlos en el servidor).

> Nota de entorno: el servidor no traía `ensurepip`/`python3-venv`; el `.venv` se creó con
> `python -m venv --without-pip` y se bootstrapeó pip con `get-pip.py`.

---

## 1. Objetivo

Pantalla web para **monitorear en tiempo real una sesión de abonado (PPPoE/IPoE) en un BRAS
Huawei**, con diagnóstico de velocidades de subida/bajada. El backend expone una **API
consumible por otras aplicaciones** (no solo por el front propio).

## 2. Glosario

- **Operador / usuario del sistema**: quien se loguea en la app (autenticación JWT).
- **Subscriber / abonado**: el usuario del BRAS cuya sesión se consulta (ej. `usuario`). **No**
  es el operador.
- **Slot / lease**: recurso exclusivo compuesto por **1 conexión SSH persistente + 1 poller**.

## 3. Requisitos funcionales

- Monitorear **1 subscriber a la vez** (ver §9 "Caso A"). Escalable a 2-3 en el futuro.
- Login (JWT). Varias personas pueden usarlo, pero solo una ocupa el recurso a la vez.
- Mostrar datos estáticos de la sesión **una sola vez**.
- Graficar velocidades **en tiempo real** consultando cada ~5 s.
- **Solo lectura** por ahora (a futuro: acciones, ej. desconectar al abonado).
- Segundo operador: **rechazo** con `409` + opción de **reintentar**.
- La pantalla muestra **botón "Cerrar conexión"** que cierra el SSH al terminar.
- Pantalla y sesión SSH viven **máximo 10 minutos** (TTL duro) — suficiente para diagnóstico.
- Si el cliente cierra la página / pierde conexión: el backend **libera el recurso**.
- Usuario con **múltiples sesiones** → mostrar **error**.
- Usuario **inexistente** → mostrar **sin conexión** y **cortar el poller**.
- Config de secretos **gitignored** (patrón tipo `config.inc.php`, opción A).

## 4. Decisiones de arquitectura

| Tema | Decisión |
|---|---|
| Backend | **FastAPI** (OpenAPI/Swagger automático, Pydantic, SSE async) |
| Auth | **JWT** para humanos y otras apps (general) |
| Frontend | HTML + CSS + **JS vanilla**, sin build |
| Transporte tiempo real | **SSE** (Server-Sent Events) |
| Gráfica | **Chart.js 4** (UMD vendorizado en `frontend/vendor/`), **una gráfica, dos líneas** (subida/bajada) |
| Despliegue | `venv` + **systemd** + **nginx**, sin Docker |
| Proceso | uvicorn **`--workers 1`** (el lease vive en memoria) |
| Dominio | **mismo dominio y puerto** (nginx sirve front en `/`, proxya `/api/`) |
| Repo | monorepo `backend/` + `frontend/` |
| Exclusión | 1 slot = 1 viewer = 1 SSH + 1 poller (`MAX_SESIONES` configurable) |

## 5. BRAS: comando y salida

Comando (Huawei VRP), con el usuario inyectado:

```
display access-user username <usuario> verbose nop | no-more
```

`| no-more` desactiva la paginación. `device_type` de Netmiko: `huawei`.

La salida se divide en secciones: `Basic`, `AAA`, `Dot1X`, `VPN&Policy-route`,
`Multicast Service`, `ACL&QoS`, `Flow Statistic`, `Dslam information`.

### 5.1 Campos a mostrar (una vez)

| Campo pantalla | Sección | Clave en salida |
|---|---|---|
| MAC | Basic | `User MAC` |
| IP | Basic | `User IP address` |
| Inicio de sesión | Basic | `Access start time` |
| QoS entrada (nombre) | ACL&QoS | `Inbound QOS-profile-name` |
| QoS salida (nombre) | ACL&QoS | `Outbound QOS-profile-name` |
| PIR entrada | ACL&QoS | `Inbound pir` (kbps) |
| CIR salida | ACL&QoS | `Outbound cir` (kbps) |

### 5.2 Datos a graficar (tiempo real)

| Serie | Sección | Clave | Dirección |
|---|---|---|---|
| **Subida (up)** | AAA | `Ipv4 Realtime speed inbound` | inbound |
| **Bajada (down)** | AAA | `Ipv4 Realtime speed outbound` | outbound |

**Convención de dirección**: se interpreta **siempre desde el punto de vista del BRAS**, no del
suscriptor. Por eso `inbound` = subida y `outbound` = bajada. Coherente con QoS del ejemplo:
`Inbound pir 112640 kbps` ≈ 110 Mbps (subida) y `Outbound cir 215040 kbps` ≈ 210 Mbps (bajada).

Mapeo configurable: `DIR_UP=inbound`, `DIR_DOWN=outbound`.

## 6. Parser (`bras/parser.py`)

- Cortar en secciones: cabecera = línea sin `:` y sin guiones; contenido = `linea.split(':', 1)`
  → `strip()`. Usar `split(':', 1)` es obligatorio porque hay valores con `:` (ej. horas
  `07:11:43`).
- Valores `-` → `None`.
- Extraer los campos de §5.1 (estáticos) y §5.2 (tiempo real).

### 6.1 Estados según cantidad de bloques (sesiones del mismo usuario)

| Bloques | Estado | Acción |
|---|---|---|
| 1 | `ok` | snapshot normal |
| 0 | `sin_conexion` | mostrar "sin conexión", **cortar poller** y cerrar SSH |
| >1 | `error` | "múltiples sesiones", **sin gráfica**; se mantiene polling por si cambia |

### 6.2 Unidades y conversión

El BRAS informa la velocidad en `kbyte/min` (aparente). Se muestra en **Mbps**:

```
mbps = valor_kbyte * KBYTE_UNIT_BYTES * 8 / KBYTE_TIME_BASE / 1_000_000
```

- `KBYTE_UNIT_BYTES` = 1024 (default, configurable).
- `KBYTE_TIME_BASE` = 60 (default, configurable; usar 1 si en realidad es por segundo).
- Se guarda también el **valor crudo** (`raw`) para tooltip/diagnóstico.
- Referencia: `1 kbyte/min ≈ 0.0001365 Mbps`; `200 Mbps ≈ 1_464_843 kbyte/min`.
- Ver §16 (calibración).

### 6.3 Cadencia real del dato

El contador `Ipv4 Realtime speed` del BRAS **refresca cada ~20-30 s**, no en cada consulta.
Por eso:
- Se consulta cada `POLL_INTERVAL=5s` (barato con SSH persistente).
- **SSE emite solo cuando el valor cambia** (evita mandar el mismo dato).
- La gráfica agrega punto al recibir snapshot nuevo → tramos planos entre refrescos.
- `SAMPLE_MODE = on_change | every_poll` (configurable) para ajustar sobre la marcha.

### 6.4 Tests

`tests/test_parser.py` contra `tests/fixtures/salida.txt` (copia de la salida real de
`comando-y-saldida.txt`). Incluye casos: 1 bloque, 0 bloques, >1 bloques.

## 7. Modelo de datos (Pydantic)

```python
class StaticInfo(BaseModel):
    mac: str | None
    ip: str | None
    start_time: str | None
    in_qos: str | None
    out_qos: str | None
    in_pir_kbps: int | None
    out_cir_kbps: int | None

class LatestSample(BaseModel):
    ts: datetime
    up_mbps: float | None       # inbound
    down_mbps: float | None     # outbound
    in_raw: float | None
    out_raw: float | None

class MonitorSnapshot(BaseModel):
    username: str
    online: bool
    state: Literal["ok", "sin_conexion", "error"]
    error_msg: str | None
    version: int
    collected_at: datetime
    static: StaticInfo
    latest: LatestSample | None
```

## 8. API v1

Todas las apps consumen lo mismo. Auth REST con `Authorization: Bearer <jwt>`. El stream usa
`?lease_token=` porque `EventSource` del navegador no permite headers.

| Método | Ruta | Auth | Descripción |
|---|---|---|---|
| POST | `/api/v1/auth/login` | — | → access (JWT) + refresh (cookie httpOnly) |
| POST | `/api/v1/auth/refresh` | cookie | renueva access token |
| POST | `/api/v1/auth/logout` | — | borra cookie de refresh |
| GET | `/api/v1/auth/me` | Bearer | usuario actual |
| GET | `/api/v1/monitor/status` | Bearer | `{capacidad, ocupados, libres, leases[]}` (sin exponer el subscriber) |
| POST | `/api/v1/monitor/leases` | Bearer | body `{username}` → `201 {lease_id, lease_token, username, expires_at, expires_in}`; `409` ocupado (`owner`, `expira_en`, `segundos_restantes`); `400` username inválido; `502` falla SSH |
| GET | `/api/v1/monitor/stream?lease_token=...` | lease token | SSE |
| GET | `/api/v1/monitor/snapshot` | Bearer + `X-Lease-Token` | último snapshot cacheado (apps sin SSE) |
| POST | `/api/v1/monitor/heartbeat` | Bearer + `X-Lease-Token` | refresca liveness (`204`) |
| DELETE | `/api/v1/monitor/leases` | Bearer + `X-Lease-Token` | release manual (cierra SSH, `204`) |
| GET | `/api/v1/health` | — | healthcheck |
| GET | `/api/docs` | — | OpenAPI/Swagger |

El `lease_token` se usa en query para el stream (EventSource no manda headers) y en
`X-Lease-Token` para el resto de operaciones del lease.

### 8.1 Eventos SSE

```
event: snapshot       data: {MonitorSnapshot}      # incluye state: ok|sin_conexion|error
event: expired        data: {"reason":"expired"}
event: error          data: {"reason":"ssh_error"}
event: closed         data: {"reason":"manual|disconnected|heartbeat|shutdown"}
: ping
```

En `sin_conexion` no hay evento aparte: llega un `snapshot` con `state="sin_conexion"`.

`ping` (comentario cada ~15 s) sirve además para detectar desconexión del cliente al escribir
sobre socket cerrado.

## 9. Lease / ciclo de vida

**Caso A** (elegido): cada viewer monitorea un subscriber distinto → **1 slot = 1 viewer = 1 SSH
+ 1 poller**. `MAX_SESIONES=1` hoy, escalable a 2-3.

```
LIBRE → ASIGNADO(conectando) → ACTIVO → LIBERANDO → LIBRE
```

- **acquire** atómico (`asyncio.Lock`):
  - sin slot libre → `409 {owner, ocupado_desde, libera_en}`.
  - slot libre → reserva, genera `lease_token`, conecta Netmiko; si falla → `502` y libera.
- **ACTIVO**: arranca poller (5 s) y `expires_at = acquire + SESSION_TTL (600 s)`.
- **Liberación (4 vías)**:
  1. Botón "Cerrar conexión" (`DELETE`).
  2. Corte del SSE → tras `DISCONNECT_GRACE = 10s` (tolera microcortes; si reconecta con el mismo
     token dentro de la gracia, sigue).
  3. `HEARTBEAT_TTL = 45s` vencido (respaldo cuando el TCP no cierra, ej. red caída).
  4. Expiración absoluta de 600 s (autoritativa) → cierra SSH, emite `expired`.
- **SSH muerto**: reintento dentro del poll; si falla → libera y emite `error`.
- **SIGTERM** (systemd stop): cierra todas las conexiones y libera.

## 10. Frontend (HTML/CSS/JS vanilla)

Páginas: `index.html` (login) y `monitor.html` (dashboard).

Estados de pantalla:
- `idle` — sin sesión.
- `ocupado` — `409`: "En uso por X, mm:ss" + **Reintentar** (auto-retry cada 5 s).
- `activo` — gráfica + cuenta regresiva 10:00 + botón **Cerrar conexión**.
- `sin_conexion` — usuario inexistente.
- `error` — múltiples sesiones.
- `expirado` — TTL alcanzado.

Gráfica: Chart.js 4 local (`frontend/vendor/chart.umd.min.js`), dos datasets (subida/bajada),
`animation:false`, ventana rolling de 180 puntos, eje Y en Mbps; tarjetas con el valor actual.
Colores: subida `#22d3ee`, bajada `#a78bfa`.

Auth: access token en memoria, refresh token en cookie httpOnly (mismo origen).
`js/config.js` con `API_BASE`, heartbeats cada 20 s y reintentos cada 5 s.
El lease token viaja en `X-Lease-Token` (salvo SSE, que usa `?lease_token=`).

## 11. Configuración (opción A: en repo pero gitignored)

- `backend/instance/config.py` — **secretos, no versionado** (`.gitignore` incluye `backend/instance/`).
- `backend/config.example.py` — **plantilla versionada**.
- Carga: defaults en `app/config.py` → merge con `instance/config.py` → variables de entorno (opcional, ganan).
- `chmod 600 backend/instance/config.py`.
- `git pull` no toca archivos ignorados (cuidado con `rsync --delete`).

Claves:

| Clave | Valor |
|---|---|
| `BRAS_HOST`, `BRAS_PORT` | datos del equipo |
| `BRAS_USER`, `BRAS_PASSWORD`, `BRAS_SECRET` | credenciales |
| `BRAS_DEVICE_TYPE` | `huawei` |
| `BRAS_CONN_TIMEOUT`, `BRAS_READ_TIMEOUT` | timeouts SSH |
| `COMMAND_TEMPLATE` | `display access-user username {username} verbose nop \| no-more` |
| `USERNAME_REGEX` | charset seguro del abonado |
| `JWT_SECRET`, `JWT_ALG`, `ACCESS_TTL`, `REFRESH_TTL` | auth |
| `DATABASE_PATH` | SQLite de usuarios (default `backend/instance/bras_monitor.db`) |
| `MAX_SESIONES` | `1` |
| `POLL_INTERVAL` | **`5`** |
| `SESSION_TTL` | `600` |
| `DISCONNECT_GRACE` | `10` |
| `HEARTBEAT_TTL` | `45` |
| `KBYTE_UNIT_BYTES` | `1024` |
| `KBYTE_TIME_BASE` | `60` |
| `DIR_UP`, `DIR_DOWN` | `inbound`, `outbound` |
| `SAMPLE_MODE` | `on_change` |

### Usuarios del panel (operadores)

**No hay alta pública** (el sitio no tiene registro). Los usuarios del login se crean por
consola y se guardan en la SQLite de `DATABASE_PATH`:

```bash
cd backend
../.venv/bin/python -m app.cli init-db
../.venv/bin/python -m app.cli create-user --username admin   # pide la contraseña 2 veces
../.venv/bin/python -m app.cli set-password --username admin  # cambiar contraseña
../.venv/bin/python -m app.cli list-users
```

En producción, ejecutar como el usuario del servicio: `sudo -u brasmonitor ...`.
El usuario del login es el **operador**; el usuario del **abonado** (BRAS) se ingresa aparte
en la pantalla de monitoreo.

## 12. Estructura del repo

```
backend/
  app/
    main.py                 # FastAPI + lifespan (arranca/cierra leases)
    config.py               # defaults + merge instance/config.py
    schemas.py              # Pydantic
    auth/{jwt.py,users.py,router.py}
    bras/{client.py,parser.py}
    monitor/{lease.py,poller.py,events.py,router.py}
    cli.py                  # bootstrap / crear usuarios
  instance/config.py        # SECRETOS, gitignored
  config.example.py
  tests/{test_parser.py,test_auth_config.py,test_monitor.py,fixtures/salida.txt}
  requirements.txt
frontend/
  index.html monitor.html
  css/app.css
  js/{config.js,api.js,auth.js,monitor.js,chart.js}
  vendor/chart.umd.min.js
deploy/{backend.service,nginx.conf}
.gitignore
```

## 13. Componentes backend

- **`bras/client.py`**: conexión Netmiko **persistente** (reusar canal), `terminal length 0` /
  paginación off, `send_command`, timeouts, reconexión acotada.
- **`bras/parser.py`**: salida → `MonitorSnapshot` (§6).
- **`monitor/lease.py`**: `LeaseManager` con slots, `acquire/release`, timers, gracia, heartbeat.
- **`monitor/poller.py`**: task asyncio por slot; Netmiko bloqueante en threadpool
  (`anyio.to_thread.run_sync`); cadencia `max(POLL_INTERVAL, dur_comando)`; snapshot con `version`.
- **`monitor/events.py`**: generator SSE, keepalive, detección de corte (`GeneratorExit`/
  `CancelledError`), emisión solo en cambio.

## 14. Despliegue (git clone / git pull + nginx + TLS autofirmado)

Artefactos: `deploy/backend.service` y `deploy/nginx.conf` (rutas de ejemplo `/opt/monitor-pppoe`).
Flujo de actualización: **git pull** en producción; `backend/instance/config.py`, `.venv/` y la
DB están gitignored, así que no se pisan.

> Antes de desplegar: el repo local aún **no tiene commit ni remoto**. Crear el commit inicial y
> pushearlo al remoto que se vaya a clonar en producción.

### 14.1 Instalación inicial en producción

```bash
# 0) Paquetes base (Ubuntu/Debian)
sudo apt update
sudo apt install -y git python3-venv nginx
sudo useradd --system --home /var/lib/monitor-pppoe --shell /usr/sbin/nologin brasmonitor
sudo mkdir -p /var/lib/monitor-pppoe
sudo chown brasmonitor:brasmonitor /var/lib/monitor-pppoe

# 1) Código y venv (código root-owned; el venv queda del usuario del servicio)
sudo git clone REPO_URL /opt/monitor-pppoe
cd /opt/monitor-pppoe
sudo python3 -m venv .venv
sudo chown -R brasmonitor:brasmonitor .venv
sudo -u brasmonitor .venv/bin/pip install --no-cache-dir -r backend/requirements.txt

# 2) Configuración local (NO se versiona)
sudo mkdir -p /opt/monitor-pppoe/backend/instance
sudo cp /opt/monitor-pppoe/backend/config.example.py /opt/monitor-pppoe/backend/instance/config.py
sudo chown -R brasmonitor:brasmonitor /opt/monitor-pppoe/backend/instance
sudo chmod 600 /opt/monitor-pppoe/backend/instance/config.py
sudo -u brasmonitor nano /opt/monitor-pppoe/backend/instance/config.py
#   - BRAS_HOST / BRAS_USER / BRAS_PASSWORD / BRAS_SECRET reales
#   - JWT_SECRET: python3 -c "import secrets; print(secrets.token_urlsafe(48))"
#   - COOKIE_SECURE = True      (detrás de HTTPS)
#   - SERVE_FRONTEND = False    (nginx sirve el front)

# 3) Usuario del panel + SQLite (el módulo `app` vive en backend/)
cd /opt/monitor-pppoe/backend
sudo -u brasmonitor ../.venv/bin/python -m app.cli init-db
sudo -u brasmonitor ../.venv/bin/python -m app.cli create-user --username admin

# 4) Certificado autofirmado (SAN obligatorio en navegadores modernos)
#    Si se accede por IP, agregar: -addext "subjectAltName=DNS:monitor.example.com,IP:10.0.0.5"
sudo openssl req -x509 -nodes -days 825 -newkey rsa:2048 \
  -keyout /etc/ssl/private/monitor-pppoe.key \
  -out /etc/ssl/certs/monitor-pppoe.crt \
  -subj "/CN=monitor.example.com" \
  -addext "subjectAltName=DNS:monitor.example.com"
sudo chmod 600 /etc/ssl/private/monitor-pppoe.key

# 5) systemd
sudo cp deploy/backend.service /etc/systemd/system/monitor-pppoe.service
sudo systemctl daemon-reload
sudo systemctl enable --now monitor-pppoe
curl -fsS http://127.0.0.1:8000/api/v1/health
sudo journalctl -u monitor-pppoe -n 50 --no-pager

# 6) nginx (ajustar server_name y rutas del cert si hace falta)
sudo cp deploy/nginx.conf /etc/nginx/sites-available/monitor-pppoe
sudo ln -sf /etc/nginx/sites-available/monitor-pppoe /etc/nginx/sites-enabled/monitor-pppoe
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx

# 7) Firewall
sudo ufw allow 'Nginx Full'
```

Verificación: `https://monitor.example.com` (aceptar la advertencia del certificado autofirmado),
`/api/docs` para Swagger.

### 14.2 Actualizaciones (git pull)

```bash
cd /opt/monitor-pppoe
sudo git pull --ff-only
sudo -u brasmonitor .venv/bin/pip install --no-cache-dir -r backend/requirements.txt  # si cambió
sudo systemctl restart monitor-pppoe                                                 # si cambió backend
```

- Cambios solo de **frontend** (`frontend/`): nginx los sirve al instante, sin reiniciar.
- Cambios de **systemd/nginx**: volver a copiar el archivo, `daemon-reload` y `reload`.
- `git pull` **no** toca `backend/instance/config.py`, `.venv/` ni `bras_monitor.db`.

### 14.3 Notas

- `uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1` (el unit ya lo hace).
- **Obligatorio `workers=1`**: el lease vive en memoria; más workers = locks duplicados/SSH doble.
- **systemd**: `Restart=always`, usuario sin privilegios, logs a journald, hardening
  (`ProtectSystem=strict`, `ProtectHome`, `NoNewPrivileges`; escritura solo en `backend/instance`).
- **nginx**: `frontend/` en `/`, proxy `/api/` → uvicorn; `proxy_buffering off`,
  `proxy_read_timeout` alto, headers de seguridad y CSP estricta.
- **TLS autofirmado**: el navegador mostrará advertencia hasta aceptar la excepción. No activar
  HSTS hasta tener un certificado de confianza; para clientes/curl usar `-k` o instalar el `.crt`.
- `COOKIE_SECURE=True` exige HTTPS (el `80` solo redirige). Si se prueba por HTTP, el refresh
  cookie no viaja.
- CORS allowlist configurable **solo** para apps externas de otro origen (el front propio es
  mismo-origen, sin CORS).
- Swagger/Redoc: `/api/docs` y `/api/redoc` (detrás del proxy `/api/`).

## 15. Seguridad

- Credenciales del BRAS **solo en el backend**; nunca al navegador.
- **Validar el username con regex estricta** antes de inyectarlo en la CLI del BRAS (evita
  inyección de comandos VRP).
- No loguear password ni la salida cruda (contiene datos del abonado).
- Hash de contraseñas de usuarios (argon2/bcrypt).
- Rate-limit en login.
- `lease_token` aleatorio, atado a user+slot; solo el dueño puede streamear/liberar.
- Secretos en `instance/config.py` (`chmod 600`).

## 16. Calibraciones abiertas (ajustar sobre la marcha)

1. **Base de tiempo**: confirmar si `kbyte/min` es realmente por minuto o por segundo. Validar con
   una prueba de velocidad conocida y ajustar `KBYTE_TIME_BASE` (60 o 1) para que el Mbps mostrado
   coincida. El usuario observó que el valor cambia cada ~20-30 s.
2. **`SAMPLE_MODE`**: decidir si graficar `on_change` (más fiel al refresco del BRAS) o
   `every_poll` (paso fijo de 5 s). Default `on_change`.
3. **`MAX_SESIONES`**: 1 hoy; evaluar 2-3 si se necesita monitoreo concurrente (Caso A).

## 17. Orden de implementación

1. Scaffold + config loader + auth JWT/SQLite + `/health`.
2. `bras/client.py` + `bras/parser.py` + tests contra salida real (mapeo in=subida / out=bajada).
3. `LeaseManager` + `poller` + SSE (gracia/heartbeat/TTL).
4. Endpoints completos + OpenAPI.
5. Frontend (login, acquire/409, gráfica, countdown, cerrar).
6. Deploy (systemd, nginx) + hardening.

## 18. Historial de decisiones clave

- Se evaluó Flask+JS vs backend separado → se optó por **FastAPI API-first** para exponer API a
  otras apps.
- Auth por **JWT** (genérico, sin atarse a un proveedor).
- **Mismo dominio/puerto** vía nginx (evita CORS en el front propio).
- Exclusión **Caso A** (slot por viewer/subscriber).
- Actualización gráfica cada **5 s** (antes 3 s), emitiendo solo en cambio.
- Velocidades en **Mbps**; dirección desde el punto de vista del BRAS (`inbound`=subida,
  `outbound`=bajada).
- Multi-sesión → error; inexistente → `sin_conexion` + cortar poller.
- Secretos en `instance/config.py` gitignored (opción A).
