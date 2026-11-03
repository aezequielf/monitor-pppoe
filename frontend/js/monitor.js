import * as api from "./api.js";
import { CONFIG } from "./config.js";
import { appendPoint, formatMbps, initChart, resetChart } from "./chart.js";

const $ = (id) => document.getElementById(id);

const els = {
  form: $("monitor-form"),
  subscriber: $("subscriber"),
  monitorBtn: $("monitor-btn"),
  monitorSpinner: $("monitor-spinner"),
  monitorLabel: $("monitor-btn-label"),
  sessionTools: $("session-tools"),
  statePill: $("state-pill"),
  stateText: $("state-pill-text"),
  countdown: $("countdown"),
  closeBtn: $("close-btn"),
  logoutBtn: $("logout-btn"),
  alert: $("alert"),
  idle: $("idle-state"),
  dashboard: $("dashboard"),
  upValue: $("up-value"),
  downValue: $("down-value"),
  userChip: $("user-chip-name"),
  chartCanvas: $("traffic-chart"),
  info: {
    mac: $("info-mac"),
    ip: $("info-ip"),
    start: $("info-start"),
    inQos: $("info-in-qos"),
    outQos: $("info-out-qos"),
    inPir: $("info-in-pir"),
    outCir: $("info-out-cir"),
  },
};

const ICONS = {
  busy:
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>',
  error:
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z"/><path d="M12 9v4"/><path d="M12 17h.01"/></svg>',
  warn:
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z"/><path d="M12 9v4"/><path d="M12 17h.01"/></svg>',
  info:
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M12 11v5"/><path d="M12 8h.01"/></svg>',
};

let lease = null;
let stream = null;
let chart = null;
let expiresAt = null;
let heartbeatTimer = null;
let countdownTimer = null;
let retryTimer = null;
let busyTick = null;
let acquiring = false;
let currentUsername = "";
let busyOwner = null;
let busyExpiresAt = null;

/* ------------------------------------------------------------------ */
/* Utilidades                                                         */
/* ------------------------------------------------------------------ */

function escapeHtml(value) {
  return String(value ?? "").replace(
    /[&<>"']/g,
    (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char],
  );
}

function formatCountdown(totalSeconds) {
  const seconds = Math.max(0, Math.floor(totalSeconds));
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  if (minutes >= 60) {
    const hours = Math.floor(minutes / 60);
    return `${hours}:${String(minutes % 60).padStart(2, "0")}:${String(rest).padStart(2, "0")}`;
  }
  return `${String(minutes).padStart(2, "0")}:${String(rest).padStart(2, "0")}`;
}

function timeLabel(iso) {
  const date = iso ? new Date(iso) : new Date();
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function setPill(mode, text) {
  els.statePill.className = mode === "idle" ? "pill" : `pill pill--${mode}`;
  els.stateText.textContent = text;
}

function setMonitorLoading(on) {
  els.monitorBtn.disabled = on;
  els.monitorSpinner.hidden = !on;
  els.monitorLabel.textContent = on ? "Conectando…" : "Monitorear";
}

function showAlert(kind, html, { retry = false } = {}) {
  els.alert.hidden = false;
  els.alert.className = `alert alert--${kind}`;
  els.alert.innerHTML = `
    <div class="alert__icon">${ICONS[kind] || ICONS.info}</div>
    <div class="alert__body">${html}</div>
    ${
      retry
        ? '<div class="alert__actions"><button class="btn btn--ghost btn--sm" data-action="retry" type="button">Reintentar ahora</button></div>'
        : ""
    }
  `;
}

function clearAlert() {
  els.alert.hidden = true;
  els.alert.innerHTML = "";
}

function setText(node, value, suffix = "") {
  const empty = value === null || value === undefined || value === "";
  node.textContent = empty ? "—" : `${value}${suffix}`;
}

function setMetric(up, down) {
  els.upValue.textContent = formatMbps(up);
  els.downValue.textContent = formatMbps(down);
}

function resetInfo() {
  Object.values(els.info).forEach((node) => {
    node.textContent = "—";
  });
}

function updateInfo(info) {
  setText(els.info.mac, info.mac);
  setText(els.info.ip, info.ip);
  setText(els.info.start, info.start_time);
  setText(els.info.inQos, info.in_qos);
  setText(els.info.outQos, info.out_qos);
  setText(els.info.inPir, info.in_pir_kbps, " kbps");
  setText(els.info.outCir, info.out_cir_kbps, " kbps");
}

/* ------------------------------------------------------------------ */
/* Sesión exclusiva (lease)                                           */
/* ------------------------------------------------------------------ */

function enterBusy(detail) {
  busyOwner = detail.owner;
  const seconds = Number(detail.segundos_restantes);
  busyExpiresAt = detail.expira_en
    ? new Date(detail.expira_en)
    : new Date(Date.now() + (Number.isFinite(seconds) ? seconds : 0) * 1000);

  renderBusy();

  if (!retryTimer) {
    retryTimer = setInterval(tryAcquire, CONFIG.RETRY_MS);
  }
  if (!busyTick) {
    busyTick = setInterval(renderBusy, 1000);
  }
}

function renderBusy() {
  const left = busyExpiresAt ? Math.max(0, Math.round((busyExpiresAt.getTime() - Date.now()) / 1000)) : 0;
  showAlert(
    "busy",
    `El recurso está en uso por <b>${escapeHtml(busyOwner || "otro operador")}</b>.
     Se libera en <b>${formatCountdown(left)}</b>. Reintentando automáticamente…`,
    { retry: true },
  );
}

function exitBusy() {
  clearInterval(retryTimer);
  retryTimer = null;
  clearInterval(busyTick);
  busyTick = null;
  busyOwner = null;
  busyExpiresAt = null;
}

async function withRefresh(call) {
  try {
    return await call();
  } catch (error) {
    if (error.status !== 401) throw error;
    await api.refresh();
    return await call();
  }
}

async function tryAcquire() {
  if (acquiring || lease || !currentUsername) return;
  acquiring = true;
  setMonitorLoading(true);
  try {
    const data = await withRefresh(() => api.acquire(currentUsername));
    startSession(data);
  } catch (error) {
    if (error.status === 401) {
      redirectToLogin();
      return;
    }
    if (error.status === 409) {
      enterBusy(error.detail || {});
    } else {
      exitBusy();
      showAlert("error", escapeHtml(error.message || "No se pudo iniciar el monitoreo."));
    }
  } finally {
    acquiring = false;
    setMonitorLoading(false);
  }
}

function startSession(data) {
  exitBusy();
  lease = { id: data.lease_id, token: data.lease_token, username: data.username };
  expiresAt = new Date(data.expires_at);
  currentUsername = data.username;
  els.subscriber.value = data.username;
  els.subscriber.disabled = true;
  els.sessionTools.hidden = false;
  els.idle.hidden = true;
  els.dashboard.hidden = false;
  els.alert.hidden = true;

  if (!chart) chart = initChart(els.chartCanvas);
  resetChart();
  resetInfo();
  setMetric(null, null);
  setPill("warn", "Conectando…");
  updateCountdown();
  startCountdown();
  startHeartbeat();
  openStream();
}

/* ------------------------------------------------------------------ */
/* Streaming                                                          */
/* ------------------------------------------------------------------ */

function openStream() {
  closeStream();
  stream = new EventSource(api.streamUrl(lease.token));

  stream.onopen = () => {
    if (lease) setPill("warn", "Conectando…");
  };

  stream.addEventListener("snapshot", (event) => {
    let snapshot;
    try {
      snapshot = JSON.parse(event.data);
    } catch {
      return;
    }
    handleSnapshot(snapshot);
  });

  stream.addEventListener("expired", () => {
    endSession("La sesión de monitoreo expiró (10 minutos).");
  });

  stream.addEventListener("closed", (event) => {
    let reason = "";
    try {
      reason = JSON.parse(event.data).reason;
    } catch {
      /* ignorar */
    }
    endSession(closedMessage(reason));
  });

  stream.onerror = (event) => {
    if (event && typeof event.data === "string" && event.data) {
      endSession("El backend reportó un error de conexión con el BRAS.");
      return;
    }
    if (lease) setPill("warn", "Reconectando…");
  };
}

function closeStream() {
  if (stream) {
    stream.close();
    stream = null;
  }
}

function handleSnapshot(snapshot) {
  if (!lease) return;
  updateInfo(snapshot.static || {});

  if (snapshot.state === "sin_conexion") {
    setPill("warn", "Sin conexión");
    showAlert(
      "warn",
      `El usuario <b>${escapeHtml(snapshot.username)}</b> no tiene una sesión activa en el BRAS.`,
    );
    return;
  }

  if (snapshot.state === "error") {
    setPill("error", "Error");
    showAlert("error", escapeHtml(snapshot.error_msg || "No se pudo consultar la sesión."));
    return;
  }

  els.alert.hidden = true;
  setPill("live", "En vivo");

  const latest = snapshot.latest;
  if (latest) {
    const up = latest.up_mbps ?? 0;
    const down = latest.down_mbps ?? 0;
    setMetric(up, down);
    appendPoint(timeLabel(latest.ts), up, down);
  }
}

function closedMessage(reason) {
  switch (reason) {
    case "manual":
      return "La conexión fue cerrada.";
    case "disconnected":
      return "Se perdió la conexión con esta pantalla.";
    case "heartbeat":
      return "La pantalla dejó de responder; la sesión se cerró.";
    case "expired":
      return "La sesión de monitoreo expiró (10 minutos).";
    case "shutdown":
      return "El servidor cerró la sesión.";
    case "ssh_error":
      return "Se perdió la conexión SSH con el BRAS.";
    default:
      return "La sesión de monitoreo finalizó.";
  }
}

/* ------------------------------------------------------------------ */
/* Temporizadores                                                     */
/* ------------------------------------------------------------------ */

function startHeartbeat() {
  clearInterval(heartbeatTimer);
  heartbeatTimer = setInterval(async () => {
    if (!lease) return;
    try {
      await withRefresh(() => api.heartbeat(lease.token));
    } catch (error) {
      if (error.status === 401) {
        redirectToLogin();
      } else if ([403, 404].includes(error.status)) {
        endSession("La sesión de monitoreo finalizó.");
      } else if (error.status === 0) {
        setPill("warn", "Reconectando…");
      }
    }
  }, CONFIG.HEARTBEAT_MS);
}

function updateCountdown() {
  const left = expiresAt ? Math.max(0, Math.round((expiresAt.getTime() - Date.now()) / 1000)) : 0;
  els.countdown.textContent = formatCountdown(left);
}

function startCountdown() {
  clearInterval(countdownTimer);
  countdownTimer = setInterval(() => {
    if (!lease) return;
    updateCountdown();
    if (expiresAt && Date.now() >= expiresAt.getTime()) {
      endSession("La sesión de monitoreo expiró (10 minutos).");
    }
  }, 1000);
}

/* ------------------------------------------------------------------ */
/* Cierre                                                             */
/* ------------------------------------------------------------------ */

function teardown() {
  closeStream();
  clearInterval(heartbeatTimer);
  heartbeatTimer = null;
  clearInterval(countdownTimer);
  countdownTimer = null;
  exitBusy();

  lease = null;
  expiresAt = null;
  els.sessionTools.hidden = true;
  els.dashboard.hidden = true;
  els.idle.hidden = false;
  els.subscriber.disabled = false;
  setPill("idle", "Inactivo");
  setMonitorLoading(false);
  resetInfo();
  setMetric(null, null);
}

function endSession(message) {
  teardown();
  if (message) showAlert("info", escapeHtml(message));
}

function redirectToLogin() {
  teardown();
  location.replace(CONFIG.LOGIN_PAGE);
}

async function onClose() {
  const token = lease ? lease.token : null;
  teardown();
  if (token) {
    try {
      await api.releaseLease(token);
    } catch {
      /* el backend libera por heartbeat/expiración */
    }
  }
  showAlert("info", "Conexión cerrada. El recurso quedó libre.");
}

async function onLogout() {
  const token = lease ? lease.token : null;
  teardown();
  if (token) {
    try {
      await api.releaseLease(token);
    } catch {
      /* el backend libera por heartbeat/expiración */
    }
  }
  try {
    await api.logout();
  } catch {
    /* sesión local cerrada igualmente */
  }
  location.replace(CONFIG.LOGIN_PAGE);
}

/* ------------------------------------------------------------------ */
/* Eventos y arranque                                                 */
/* ------------------------------------------------------------------ */

els.form.addEventListener("submit", (event) => {
  event.preventDefault();
  const value = els.subscriber.value.trim();
  if (!value) {
    els.subscriber.focus();
    return;
  }
  currentUsername = value;
  exitBusy();
  clearAlert();
  tryAcquire();
});

els.closeBtn.addEventListener("click", onClose);
els.logoutBtn.addEventListener("click", onLogout);

els.alert.addEventListener("click", (event) => {
  if (event.target.closest('[data-action="retry"]')) {
    exitBusy();
    tryAcquire();
  }
});

async function boot() {
  setPill("idle", "Inactivo");
  setMonitorLoading(false);

  try {
    await api.refresh();
  } catch {
    location.replace(CONFIG.LOGIN_PAGE);
    return;
  }

  try {
    const user = await api.me();
    els.userChip.textContent = user.username;
  } catch (error) {
    if (error.status === 401) {
      location.replace(CONFIG.LOGIN_PAGE);
      return;
    }
  }

  const preset = new URLSearchParams(location.search).get("u");
  if (preset) els.subscriber.value = preset;
}

boot();
