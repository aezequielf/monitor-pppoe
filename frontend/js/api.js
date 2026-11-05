import { CONFIG } from "./config.js";

let accessToken = null;

export class ApiError extends Error {
  constructor(status, detail) {
    const message =
      typeof detail === "string"
        ? detail
        : detail && detail.message
          ? detail.message
          : `HTTP ${status}`;
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

async function readBody(response) {
  const text = await response.text();
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

async function request(
  path,
  { method = "GET", body, auth = true, headers = {}, signal } = {},
) {
  const requestHeaders = { ...headers };
  if (body !== undefined) requestHeaders["Content-Type"] = "application/json";
  if (auth && accessToken) requestHeaders["Authorization"] = `Bearer ${accessToken}`;

  let response;
  try {
    response = await fetch(`${CONFIG.API_BASE}${path}`, {
      method,
      headers: requestHeaders,
      credentials: "same-origin",
      body: body !== undefined ? JSON.stringify(body) : undefined,
      signal,
    });
  } catch (error) {
    if (error && error.name === "AbortError") throw error;
    throw new ApiError(0, "No se pudo contactar al servidor");
  }

  const data = await readBody(response);
  if (!response.ok) {
    throw new ApiError(response.status, data && data.detail !== undefined ? data.detail : data);
  }
  return data;
}

export async function login(username, password) {
  const data = await request("/auth/login", {
    method: "POST",
    body: { username, password },
    auth: false,
  });
  accessToken = data.access_token;
  return data;
}

export async function refresh() {
  const data = await request("/auth/refresh", { method: "POST", auth: false });
  accessToken = data.access_token;
  return data;
}

export async function logout() {
  try {
    await request("/auth/logout", { method: "POST", auth: false });
  } finally {
    accessToken = null;
  }
}

export function me() {
  return request("/auth/me");
}

export function acquire(username) {
  return request("/monitor/leases", { method: "POST", body: { username } });
}

export function onlineUsers(prefix, signal) {
  return request(`/online-users?prefix=${encodeURIComponent(prefix)}`, { signal });
}

export function releaseLease(token) {
  return request("/monitor/leases", {
    method: "DELETE",
    headers: { "X-Lease-Token": token },
  });
}

export function heartbeat(token) {
  return request("/monitor/heartbeat", {
    method: "POST",
    headers: { "X-Lease-Token": token },
  });
}

export function getStatus() {
  return request("/monitor/status");
}

export function streamUrl(token) {
  return `${CONFIG.API_BASE}/monitor/stream?lease_token=${encodeURIComponent(token)}`;
}
