# Monitor PPPoE — Documento de diseño

Referencia persistente del proyecto. Reemplaza la memoria de contexto de la sesión:
todo lo necesario para retomar el trabajo está acá.

Archivos de referencia:
- `backend/tests/fixtures/` — copias sanitizadas usadas por los tests (XML NETCONF y salidas Radius).
- Las salidas reales con PII (`comando y salida.txt`, `historicos.txt`) no se versionan.

## 0. Estado de implementación

- [x] Paso 1 — scaffold, config loader, auth JWT + SQLite, `/health`, CLI.
- [x] Paso 2 — `bras/client.py` (NETCONF persistente), `bras/parser.py`, tests contra XML sanitizado.
- [x] Paso 3 — `LeaseManager` + poller + SSE (gracia, heartbeat, TTL) + endpoints de monitoreo.
- [x] Paso 4 — pulido de OpenAPI (`/api/docs`, tags, descripciones) + suite de tests.
- [x] Paso 5 — frontend (HTML/CSS/JS + Chart.js) — código completo, falta prueba visual en navegador.
- [x] Paso 6 — deploy: `deploy/backend.service` + `deploy/nginx.conf` listos (falta instalarlos en el servidor).
- [x] Paso 7 — métricas del NAS (CPU/memoria/usuarios) y tasa por contadores QoS (+tests).
- [x] Paso 8 — histórico de conexiones API Radius + últimas desconexiones BRAS en modal.
- [x] Paso 9 — migración a NETCONF (usuario/QoS/desconexiones) + SNMP (CPU/memoria/usuarios/chasis/versión).

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
- **Slot / lease**: recurso exclusivo compuesto por **1 conexión NETCONF persistente + 1 cliente SNMP + 1 poller**.

## 3. Requisitos funcionales

- Monitorear **1 subscriber a la vez** (ver §9 "Caso A"). Escalable a 2-3 en el futuro.
- Login (JWT). Varias personas pueden usarlo, pero solo una ocupa el recurso a la vez.
- Mostrar chasis y versión de software del NAS en la barra superior tras el login.
- Mostrar datos estáticos de la sesión **una sola vez**.
- Graficar velocidades **en tiempo real** consultando cada ~5 s.
- **Solo lectura** por ahora (a futuro: acciones, ej. desconectar al abonado).
- Segundo operador: **rechazo** con `409` + opción de **reintentar**.
- La pantalla muestra **botón "Cerrar conexión"** que cierra la sesión NETCONF al terminar.
- Pantalla y sesión NETCONF viven **máximo 10 minutos** (TTL duro) — suficiente para diagnóstico.
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
| Exclusión | 1 slot = 1 viewer = 1 NETCONF + 1 SNMP + 1 poller (`MAX_SESIONES` configurable) |

## 5. BRAS: consultas NETCONF y SNMP

Ya no se usa Netmiko ni comandos CLI. La conexión persistente por lease es **NETCONF sobre SSH**
(`ncclient`, sin `device_params={"name": "huawei"}` para mantener el modo RFC-compliant). Las
métricas del NAS y la info del chasis se leen por **SNMP v2c** (`pysnmp` 7, API asyncio).

### 5.1 Datos del equipo (SNMP)

Al entrar, el frontend consulta `GET /api/v1/monitor/system/info`. El backend hace dos `GET`
SNMP y muestra el resultado en la barra superior:

| Dato | OID |
|---|---|
| Nombre del chasis | `1.3.6.1.2.1.47.1.1.1.1.7.16777216` |
| Detalle/`sysDescr` (versión de software) | `1.3.6.1.2.1.1.1.0` |

Ejemplo de `sysDescr`:

```text
Huawei Versatile Routing Platform Software VRP (R) software, Version 8.230 (NetEngine 8000 V800R023C00SPC500) Copyright (C) 2012-2023 Huawei Technologies Co., Ltd. HUAWEI NetEngine 8000 F1A-8H20Q
```

El parser toma lo que está entre paréntesis como versión
(`NetEngine 8000 V800R023C00SPC500`) y `HUAWEI NetEngine 8000 F1A-8H20Q` como chasis.

### 5.2 Suscriptor y QoS (NETCONF)

Al hacer clic en **Monitorar**, fuera del poller y una sola vez por lease, se ejecutan dos
consultas NETCONF:

1. Usuario, con el filtro `urn:huawei:yang:huawei-bras-user-manage` por
   `access-user-name`. Devuelve `access-index`, IP, MAC e inicio de sesión.
2. Desconexiones, con el mismo namespace y `record-type=offline-record`,
   `user-name=<usuario>` y `view-count=5`.

En el poller se consulta QoS con `urn:huawei:yang:huawei-qos`, filtrando por el
`access-index` inicial, `service-class=total` y `pass-bytes`:

- `direction=inbound` → **subida**.
- `direction=outbound` → **bajada**.
- Se aplica la misma fórmula de delta/Mbps de siempre sobre `pass-bytes`.

Los campos antiguos `in_qos`, `out_qos`, `in_pir_kbps` y `out_cir_kbps` se conservan en el
schema por compatibilidad, pero ahora se emiten en `null` y no se muestran en el frontend.

Si no hay contadores `total` para alguna dirección, el backend publica
`El usuario no tiene contadores QoS disponibles para este tipo de monitoreo.`, libera el lease
y cierra el SSE.

### 5.3 Histórico de conexiones

Se consulta **una sola vez**, cuando la consulta inicial de usuario devuelve `state="ok"`. Si el
usuario no tiene conexión, no se ejecuta ninguna de las dos consultas y no se muestra el botón
**Histórico**.

Fuentes independientes (un fallo de una no afecta a la otra ni al monitoreo):

```text
NETCONF <bras-user-manage>/<online-fail-or-offline-records>  # BRAS
GET <webservice>?accion=consulta-con&login=<usuario>         # API Radius
```

- API Radius: hasta 80 conexiones; se toman las primeras 5 (ya vienen de la más nueva a la
  más vieja). Incluye inicio, fin, upload/download en **bytes**, NAS, causa, MAC e IP.
  Una conexión activa tiene `final` vacío.
- BRAS: últimas 5 desconexiones con inicio, fin, IP, MAC y motivo (`interface` queda `null`).
- El frontend muestra **dos bloques separados** de hasta 5 filas cada uno:
  - API: inicio, fin, duración, subida, bajada, IP, MAC, causa.
  - BRAS: inicio, fin, duración, IP, MAC, motivo.
- `upload/download` se formatean a B/KB/MB/GB con base 1000.
- El resultado se cachea en el lease y se emite por SSE como evento `history` (se reenvía si
  el navegador reconecta).

## 6. Parser (`bras/parser.py`)

- Usar `xml.etree.ElementTree` (stdlib) sobre `reply.data_xml`; no se parsea texto de comandos.
- De `<access-table>` extraer `access-index`, `access-ipaddress`, `access-mac-address` y
  `access-start-time`.
- De `<online-fail-or-offline-record>` extraer `login-time`, `offline-time`, `ipv4-address`,
  `mac-address` y `online-fail-or-offline-reason`; la duración se calcula restando fechas.
- De `<user-information>` tomar solo `service-class=total` y su `pass-bytes` por dirección;
  no se suman clases parciales.
- Los campos QoS estáticos antiguos quedan en `None`.

### 6.1 Estados según cantidad de bloques (sesiones del mismo usuario)

| Bloques | Estado | Acción |
|---|---|---|
| 1 | `ok` | snapshot normal |
| 0 | `sin_conexion` | mostrar "sin conexión", **cortar poller** y cerrar NETCONF/SNMP |
| >1 | `error` | "múltiples sesiones", **sin gráfica**; se mantiene polling por si cambia |

### 6.2 Cálculo de tasa

`monitor/rates.py` guarda la última muestra `(bytes, timestamp)` por dirección y calcula:

```
mbps = (bytes_actual - bytes_anterior) * 8 / (segundos_transcurridos * 1_000_000)
```

- La primera muestra de una sesión es solo baseline: `latest = None` y la gráfica espera el
  siguiente ciclo.
- Se usa `time.monotonic()` y el tiempo real transcurrido, no el `POLL_INTERVAL` nominal.
- El baseline se conserva si una consulta QoS falla o devuelve `None`.
- Se reinicia el baseline si el contador baja (reset del BRAS) o cambia la sesión.
- `up_bytes`/`down_bytes` se conservan en `LatestSample` para diagnóstico y tooltip.
- `inbound` = subida; `outbound` = bajada.

### 6.3 Cadencia y emisión

- Los contadores QoS se consultan cada `POLL_INTERVAL` (5 s en producción) con la misma
  conexión NETCONF. El intervalo se mide de inicio a inicio: se descuenta el tiempo consumido
  por la consulta, no se suma una espera completa después de cada consulta.
- El usuario **no** se vuelve a consultar en el poller; MAC/IP/inicio se cachean al inicio.
- **SSE emite solo cuando cambia** la tasa calculada o alguna métrica del NAS/estática.
- `SAMPLE_MODE = on_change | every_poll` (configurable). `on_change` compara `up_mbps` y
  `down_mbps`; `every_poll` publica cada ciclo.
- No hay fallback a `Ipv4 Realtime speed`: si QoS no responde, no se inventa una tasa.

### 6.4 Tests

- `tests/test_parser.py`: XML de usuario (1/0/>1 registros, campos estáticos, `access-index`),
  desconexiones y QoS (`inbound`/`outbound`, solo `total`, salida inválida).
- `tests/test_rates.py`: baseline inicial, delta, contador en cero, reset, cambio de sesión y
  muestra faltante.
- `tests/test_monitor.py` cubre el flujo completo con contadores QoS simulados, el caso sin
  contadores QoS y la carga única del histórico (incluido fallback independiente).
- `tests/test_bras_client.py`: conexión NETCONF, filtros y parseo devuelto por la fachada.
- `tests/test_host_metrics.py`: parseo de `sysDescr`/versión y detección de cambios de host.
- `tests/test_history.py`: parseo de `consulta-con`, límite de 5, conexión activa y respuesta
  sin registros. `tests/test_parser.py` cubre el parseo de desconexiones NETCONF.

### 6.5 Métricas del NAS

Además del abonado, el poller consulta el estado del NAS por SNMP y lo publica en
`snapshot.host`:

| OID | Dato | Destino |
|---|---|---|
| `1.3.6.1.4.1.2011.5.25.31.1.1.1.1.5.16842753` | CPU (avg 5 min) | `host.cpu_percent` |
| `1.3.6.1.4.1.2011.5.25.31.1.1.1.1.7.16842753` | Memoria (avg 5 min) | `host.memory_percent` |
| `1.3.6.1.4.1.2011.5.25.40.1.1.20.1.5.71` | Usuarios online | `host.online_users` |

Se consultan en el primer ciclo y luego cada `SNMP_POLL_INTERVAL` (5 s por defecto), no en cada
`POLL_INTERVAL` para no gastar CPU del plano de control. Con `SAMPLE_MODE=on_change` el snapshot
se emite si cambia el tráfico o alguna de estas métricas. Si SNMP falla, se publica
`Error de SNMP: ...`, se libera el lease y se cierra el SSE.


## 7. Modelo de datos (Pydantic)

```python
class StaticInfo(BaseModel):
    # Campos QoS heredados: siempre null en la versión NETCONF.
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
    up_bytes: int | None        # contador QoS inbound
    down_bytes: int | None      # contador QoS outbound

class HostMetrics(BaseModel):
    cpu_percent: int | None
    memory_percent: int | None
    online_users: int | None

class SystemInfo(BaseModel):
    chassis_name: str | None
    software_version: str | None

class MonitorSnapshot(BaseModel):
    username: str
    online: bool
    state: Literal["ok", "sin_conexion", "error"]
    error_msg: str | None
    version: int
    collected_at: datetime
    static: StaticInfo
    latest: LatestSample | None
    host: HostMetrics | None

class HistoryConnection(BaseModel):     # API Radius
    start: str | None
    end: str | None
    duration_seconds: int | None
    upload_bytes: int | None
    download_bytes: int | None
    nas: str | None
    reason: str | None
    mac: str | None
    ip: str | None

class HistoryDisconnection(BaseModel):  # BRAS
    start: str | None
    end: str | None
    duration_seconds: int | None
    reason: str | None
    mac: str | None
    ip: str | None
    interface: str | None

class MonitorHistory(BaseModel):
    connections: list[HistoryConnection]
    disconnections: list[HistoryDisconnection]
    connections_error: str | None
    disconnections_error: str | None
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
| GET | `/api/v1/monitor/system/info` | Bearer | `{chassis_name, software_version}` desde SNMP; `502` si falla |
| GET | `/api/v1/monitor/status` | Bearer | `{capacidad, ocupados, libres, leases[]}` (sin exponer el subscriber) |
| GET | `/api/v1/online-users?prefix=...` | Bearer | usuarios con sesión activa en el NAS que empiezan con el prefijo (mín. 3); `400` prefijo inválido; `502` webservice |
| POST | `/api/v1/monitor/leases` | Bearer | body `{username}` → `201 {lease_id, lease_token, username, expires_at, expires_in}`; `409` ocupado (`owner`, `expira_en`, `segundos_restantes`); `400` username inválido; `502` falla NETCONF |
| GET | `/api/v1/monitor/stream?lease_token=...` | lease token | SSE |
| GET | `/api/v1/monitor/snapshot` | Bearer + `X-Lease-Token` | último snapshot cacheado (apps sin SSE) |
| POST | `/api/v1/monitor/heartbeat` | Bearer + `X-Lease-Token` | refresca liveness (`204`) |
| DELETE | `/api/v1/monitor/leases` | Bearer + `X-Lease-Token` | release manual (cierra NETCONF/SNMP, `204`) |
| GET | `/api/v1/health` | — | healthcheck |
| GET | `/api/docs` | — | OpenAPI/Swagger |

El `lease_token` se usa en query para el stream (EventSource no manda headers) y en
`X-Lease-Token` para el resto de operaciones del lease.

### 8.1 Eventos SSE

```
event: snapshot       data: {MonitorSnapshot}      # incluye state: ok|sin_conexion|error
event: history        data: {MonitorHistory}       # una vez; se reenvía al reconectar
event: expired        data: {"reason":"expired"}
event: error          data: {"reason":"ssh_error|netconf_error|snmp_error"}
event: closed         data: {"reason":"manual|disconnected|heartbeat|shutdown"}
: ping
```

En `sin_conexion` no hay evento aparte: llega un `snapshot` con `state="sin_conexion"`.

`ping` (comentario cada ~15 s) sirve además para detectar desconexión del cliente al escribir
sobre socket cerrado.

### 8.2 Webservice de usuarios online (autocompletado)

El panel autocompleta el usuario del abonado con el webservice de dialup del NAS. Se consulta
**desde el backend** (HTTP interno, sin autenticación) para evitar CORS y contenido mixto.

```text
GET http://10.10.10.2/dialup2/webserv/
  ?accion=usuarios_online
  &username=<prefijo de 3+ caracteres>
  &ip=<IPv4 del NAS>
```

- `accion`: fijo, `usuarios_online`.
- `username`: prefijo; mínimo 3 caracteres; devuelve usuarios cuyo nombre **comienza** con él.
- `ip`: IPv4 del NAS (default `200.49.120.10`).

Solo incluye sesiones activas (`AcctSessionTime = 0` y `AcctStopTime` nulo), sin duplicados.

| Respuesta | Cuerpo |
|---|---|
| OK con usuarios | `{"status":"ok","resultado":["gbaigosar","gbarrera"]}` |
| OK sin coincidencias | `{"status":"ok","resultado":[]}` |
| Error | `{"status":"err","resultado":"Accion no reconocida o faltante ----"}` |

El backend expone `GET /api/v1/online-users?prefix=...` (Bearer): valida el prefijo, deduplica,
filtra y mapea errores/timeout del webservice a `502`. El front consulta **una sola vez al llegar
a 3 caracteres** y los caracteres siguientes filtran localmente la lista.

Claves: `ONLINE_USERS_URL`, `ONLINE_USERS_NAS_IP`, `ONLINE_USERS_TIMEOUT`.

## 9. Lease / ciclo de vida

**Caso A** (elegido): cada viewer monitorea un subscriber distinto → **1 slot = 1 viewer =
1 NETCONF + 1 SNMP + 1 poller**. `MAX_SESIONES=1` hoy, escalable a 2-3.

```
LIBRE → ASIGNADO(conectando) → ACTIVO → LIBERANDO → LIBRE
```

- **acquire** atómico (`asyncio.Lock`):
  - sin slot libre → `409 {owner, ocupado_desde, libera_en}`.
  - slot libre → reserva, genera `lease_token`, conecta NETCONF, consulta el usuario y,
    si está online, carga el histórico; si falla → `502` y libera.
- **ACTIVO**: arranca poller (5 s) y `expires_at = acquire + SESSION_TTL (600 s)`.
- **Liberación (4 vías)**:
  1. Botón "Cerrar conexión" (`DELETE`).
  2. Corte del SSE → tras `DISCONNECT_GRACE = 10s` (tolera microcortes; si reconecta con el mismo
     token dentro de la gracia, sigue).
  3. `HEARTBEAT_TTL = 45s` vencido (respaldo cuando el TCP no cierra, ej. red caída).
   4. Expiración absoluta de 600 s (autoritativa) → cierra NETCONF/SNMP, emite `expired`.
- **NETCONF/SNMP caído**: la librería lanza error → libera y emite `error`.

- **SIGTERM** (systemd stop): cierra todas las conexiones y libera.

## 10. Frontend (HTML/CSS/JS vanilla)

Páginas: `index.html` (login) y `monitor.html` (dashboard).

Estados de pantalla:
- `idle` — sin sesión.
- `ocupado` — `409`: "En uso por X, mm:ss" + **Reintentar** (auto-retry cada 5 s).
- `activo` — chasis/versión en la barra superior, gráfica + cuenta regresiva 10:00 + botón **Cerrar conexión**.
- `sin_conexion` — usuario inexistente.
- `error` — múltiples sesiones, error NETCONF/SNMP o ausencia de contadores QoS; en estos dos
  últimos casos el backend libera el lease y cierra el canal mostrando el mensaje correspondiente.
- `expirado` — TTL alcanzado.

Gráfica: Chart.js 4 local (`frontend/vendor/chart.umd.min.js`), dos datasets (subida/bajada),
`animation:false`, ventana rolling de 180 puntos, eje Y en Mbps; tarjetas con el valor actual.
Colores: subida `#22d3ee`, bajada `#a78bfa`.

Arriba de subida/bajada se muestran tres métricas del NAS: **CPU**, **memoria** y **usuarios
online** (`snapshot.host`). Se actualizan con cada snapshot (solo cuando cambian). Cada tarjeta
incluye un **mini-gauge SVG semicircular** junto al número; el número sigue siendo el valor
exacto y el gauge colorea según umbral:

| Métrica | Verde | Amarillo | Naranja | Rojo |
|---|---|---|---|---|
| CPU | `<35%` | `35-59%` | `60-74%` | `>=75%` |
| Memoria | `<=50%` | — | `51-75%` | `>75%` |
| Usuarios | `<=20000` | `20001-28000` | `28001-29000` | `>29000` (escala hasta 32000) |

Si SNMP no devuelve valor, el número y el gauge quedan en gris.

La barra superior muestra `<chasis> · <versión de software>` cuando responde
`/api/v1/monitor/system/info`; si falla, se oculta el chip.

Auth: access token en memoria, refresh token en cookie httpOnly (mismo origen).
`js/config.js` con `API_BASE`, heartbeats cada 20 s y reintentos cada 5 s.
El lease token viaja en `X-Lease-Token` (salvo SSE, que usa `?lease_token=`).

Autocompletado del abonado (`js/autocomplete.js`): al llegar a **3 caracteres** consulta
`GET /api/v1/online-users?prefix=...` (una sola vez por prefijo); los caracteres siguientes
filtran localmente la lista. Se navega con flechas y se selecciona con Enter o clic. El
backend hace de proxy al webservice HTTP interno para evitar CORS y contenido mixto.

**Histórico**: al final del dashboard aparece el botón **Histórico** solo si el usuario está
online y hay registros. Abre un `<dialog>` modal con dos bloques de hasta 5 filas (API Radius
y BRAS), con scroll vertical si hace falta y scroll horizontal para las tablas en pantallas
angostas. No se consulta al abrir el modal: los datos llegan una vez por SSE.

## 11. Configuración (opción A: en repo pero gitignored)

- `backend/instance/config.py` — **secretos, no versionado** (`.gitignore` incluye `backend/instance/`).
- `backend/config.example.py` — **plantilla versionada**.
- Carga: defaults en `app/config.py` → merge con `instance/config.py` → variables de entorno (opcional, ganan).
- `chmod 600 backend/instance/config.py`.
- `git pull` no toca archivos ignorados (cuidado con `rsync --delete`).

Claves:

| Clave | Valor |
|---|---|
| `BRAS_HOST` | host usado por defecto por NETCONF/SNMP |
| `BRAS_USER`, `BRAS_PASSWORD` | credenciales heredadas del panel (no se usan para NETCONF) |
| `NETCONF_HOST`, `NETCONF_PORT` | host/puerto NETCONF (default `830`) |
| `NETCONF_USER`, `NETCONF_PASSWORD` | credenciales NETCONF |
| `NETCONF_TIMEOUT` | timeout de conexión NETCONF |
| `SNMP_HOST`, `SNMP_PORT` | host/puerto SNMP (default `161`) |
| `SNMP_VERSION` | `2` (v2c) |
| `SNMP_COMMUNITY` | community SNMP |
| `SNMP_TIMEOUT`, `SNMP_RETRIES` | timeout/reintentos UDP |
| `SNMP_POLL_INTERVAL` | **5** (separado de `POLL_INTERVAL`) |
| `HISTORY_LIMIT` | `5` |
| `USERNAME_REGEX` | charset seguro del abonado |
| `JWT_SECRET`, `JWT_ALG`, `ACCESS_TTL`, `REFRESH_TTL` | auth |
| `DATABASE_PATH` | SQLite de usuarios (default `backend/instance/bras_monitor.db`) |
| `MAX_SESIONES` | `1` |
| `POLL_INTERVAL` | `5` por defecto (en producción puede ser `3`) |
| `SESSION_TTL` | `600` |
| `DISCONNECT_GRACE` | `10` |
| `HEARTBEAT_TTL` | `45` |
| `SAMPLE_MODE` | `on_change` |
| `ONLINE_USERS_URL` | webservice dialup (default `http://10.10.10.2/dialup2/webserv/`) |
| `ONLINE_USERS_NAS_IP` | IP del NAS a consultar (default `200.49.120.10`) |
| `ONLINE_USERS_TIMEOUT` | `5.0` |

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
    bras/{client.py,parser.py,netconf.py,snmp.py,xml_filters.py}
    monitor/{lease.py,poller.py,rates.py,events.py,router.py}
    online_users.py         # proxy al webservice de usuarios online
    history.py              # consulta del historial de conexiones Radius
    cli.py                  # bootstrap / crear usuarios
  instance/config.py        # SECRETOS, gitignored
  config.example.py
  tests/{test_parser.py,test_rates.py,test_host_metrics.py,test_auth_config.py,test_monitor.py,test_bras_client.py,test_online_users.py,test_history.py,fixtures/}
  requirements.txt
frontend/
  index.html monitor.html
  css/app.css
  js/{config.js,api.js,auth.js,monitor.js,chart.js,autocomplete.js}
  vendor/chart.umd.min.js
deploy/{backend.service,nginx.conf}
.gitignore
```

## 13. Componentes backend

- **`bras/client.py`**: fachada que combina `NetconfClient` y `SnmpClient`.
- **`bras/netconf.py`**: conexión `ncclient` **persistente** por lease, filtros subtree y
  reconexión acotada; sin `device_params` propietario.
- **`bras/snmp.py`**: cliente asyncio de pysnmp 7 para CPU/memoria/usuarios/chasis/versión.
- **`bras/xml_filters.py`**: filtros NETCONF para usuario, desconexiones y QoS.
- **`bras/parser.py`**: XML NETCONF → datos estáticos + `access-index`, desconexiones y bytes
  acumulados de QoS (§6).
- **`monitor/rates.py`**: baseline y cálculo de Mbps por delta de contadores QoS.
- **`monitor/lease.py`**: `LeaseManager` con slots, `acquire/release`, timers, gracia, heartbeat.
- **`monitor/poller.py`**: task asyncio por slot; NETCONF bloqueante en threadpool
  (`anyio.to_thread.run_sync`); cadencia start-to-start descontando la duración de la consulta;
  snapshot con `version`. Usa el `access-index` cacheado, consulta QoS `inbound`/`outbound` y
  calcula tasas. Las métricas SNMP se consultan cada `SNMP_POLL_INTERVAL`. Publica si cambió la
  tasa o alguna métrica.
- **`monitor/events.py`**: generator SSE, keepalive, detección de corte (`GeneratorExit`/
  `CancelledError`), emisión solo en cambio.
- **`online_users.py`**: proxy autenticado al webservice de dialup (`usuarios_online`),
  timeout y mapeo de errores a `502`; deduplica y filtra por prefijo.

## 14. Despliegue (git clone / git pull + nginx + TLS autofirmado)

Artefactos: `deploy/backend.service` y `deploy/nginx.conf` (rutas de ejemplo `/opt/monitor-pppoe`).
Flujo de actualización: **git pull** en producción; `backend/instance/config.py`, `.venv/` y la
DB están gitignored, así que no se pisan.

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
#   - NETCONF_HOST / NETCONF_PORT / NETCONF_USER / NETCONF_PASSWORD reales
#   - SNMP_HOST / SNMP_PORT / SNMP_VERSION / SNMP_COMMUNITY / SNMP_TIMEOUT / SNMP_RETRIES
#   - SNMP_POLL_INTERVAL (separado de POLL_INTERVAL)
#   - JWT_SECRET: python3 -c "import secrets; print(secrets.token_urlsafe(48))"
#   - COOKIE_SECURE = True      (detrás de HTTPS)
#   - SERVE_FRONTEND = False    (nginx sirve el front)
#   - ONLINE_USERS_URL / ONLINE_USERS_NAS_IP solo si difieren del default
#     (http://10.10.10.2/dialup2/webserv/ y 200.49.120.10)

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
- **Obligatorio `workers=1`**: el lease vive en memoria; más workers = locks duplicados/sesiones NETCONF duplicadas.
- **systemd**: `Restart=always`, usuario sin privilegios, logs a journald, hardening
  (`ProtectSystem=strict`, `ProtectHome`, `NoNewPrivileges`; escritura solo en `backend/instance`).
- **nginx**: `frontend/` en `/`, proxy `/api/` → uvicorn; `proxy_buffering off`,
  `proxy_read_timeout` alto, headers de seguridad y CSP estricta.
- **Swagger/Redoc y CSP**: `/api/docs` y `/api/redoc` cargan su bundle desde jsDelivr y usan
  un script de inicialización inline. Con `script-src 'self'` el HTML carga (se ve el título
  "Swagger UI") pero queda en blanco. Por eso `deploy/nginx.conf` relaja la CSP **solo** para
  esas dos rutas; el resto de la app sigue igual. Si el servidor no tiene salida a internet,
  el CDN tampoco carga: conviene self-hostear los assets o deshabilitar la doc en producción
  (`docs_url=None`, `redoc_url=None`, `openapi_url=None`).
- **TLS autofirmado**: el navegador mostrará advertencia hasta aceptar la excepción. No activar
  HSTS hasta tener un certificado de confianza; para clientes/curl usar `-k` o instalar el `.crt`.
- `COOKIE_SECURE=True` exige HTTPS (el `80` solo redirige). Si se prueba por HTTP, el refresh
  cookie no viaja.
- CORS allowlist configurable **solo** para apps externas de otro origen (el front propio es
  mismo-origen, sin CORS).
- Swagger/Redoc: `/api/docs` y `/api/redoc` (detrás del proxy `/api/`). Ruta correcta:
  `/api/docs` (no `/api/dosc`).

## 15. Seguridad

- Credenciales del BRAS **solo en el backend**; nunca al navegador.
- **Validar el username con regex estricta** y serializarlo con `xml.etree.ElementTree` antes de
  mandarlo en el filtro NETCONF (evita inyección XML).
- No loguear password ni la salida cruda (contiene datos del abonado).
- Hash de contraseñas de usuarios (argon2/bcrypt).
- Rate-limit en login.
- `lease_token` aleatorio, atado a user+slot; solo el dueño puede streamear/liberar.
- Secretos en `instance/config.py` (`chmod 600`).
- El webservice de usuarios online es HTTP interno: se consulta **desde el backend**
  (no desde el navegador) para evitar CORS y contenido mixto; el endpoint del panel exige
  sesión y valida el prefijo antes de llamarlo.

## 16. Calibraciones abiertas (ajustar sobre la marcha)

1. **Contadores QoS**: verificar en producción que `service-class=total / pass-bytes` crece de
   forma monótona y que un reset del BRAS no genera un pico (el tracker reinicia el baseline).
2. **Access-index cacheado**: si el BRAS reutiliza el índice durante la sesión, las métricas
   quedarían asociadas a otra sesión. El usuario aceptó el riesgo por ser diagnóstico ocasional.
3. **`SAMPLE_MODE`**: decidir si graficar `on_change` (solo cambios de tasa) o
   `every_poll` (paso fijo de 5 s). Default `on_change`.
4. **`MAX_SESIONES`**: 1 hoy; evaluar 2-3 si se necesita monitoreo concurrente (Caso A).

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
- La tasa se obtiene de **contadores QoS** (`service-class=total / pass-bytes`) por delta de
  5 s, no de `Ipv4 Realtime speed` ni `Flow Statistic` (refrescan cada ~20-30 s y pierden picos).
- **Sin fallback**: si QoS no responde, no se publica tasa. El usuario se consulta una sola vez
  al inicio; el `access-index` se cachea para todo el lease.
- Sin contadores QoS (`inbound`/`outbound` sin `total/pass-bytes`) → estado `error`, mensaje del
  backend, liberación del lease y cierre del SSE; el frontend vuelve a `idle`.
- Se eliminó Netmiko/CLI: NETCONF para usuario/QoS/desconexiones y SNMP para métricas del NAS.
- SNMP se consulta cada `SNMP_POLL_INTERVAL` para no gastar CPU del plano de control en cada
  `POLL_INTERVAL`.
- Histórico: API y BRAS como fuentes independientes, 5 registros cada una, consultadas una
  sola vez tras confirmar conexión y emitidas por SSE. Si no hay conexión no se consultan.
- Multi-sesión → error; inexistente → `sin_conexion` + cortar poller.
- Secretos en `instance/config.py` gitignored (opción A).
