import { ApiError, login, refresh } from "./api.js";
import { CONFIG } from "./config.js";

const form = document.getElementById("login-form");
const username = document.getElementById("username");
const password = document.getElementById("password");
const errorBox = document.getElementById("login-error");
const button = document.getElementById("login-btn");
const spinner = document.getElementById("login-spinner");
const label = document.getElementById("login-btn-label");

function setLoading(on) {
  button.disabled = on;
  spinner.hidden = !on;
  label.textContent = on ? "Ingresando…" : "Ingresar";
}

function showError(message) {
  errorBox.textContent = message;
  errorBox.hidden = false;
}

function clearError() {
  errorBox.hidden = true;
  errorBox.textContent = "";
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  clearError();

  const user = username.value.trim();
  if (!user || !password.value) {
    showError("Completá usuario y contraseña.");
    return;
  }

  setLoading(true);
  try {
    await login(user, password.value);
    location.replace(CONFIG.MONITOR_PAGE);
  } catch (error) {
    showError(
      error instanceof ApiError && error.status === 401
        ? "Usuario o contraseña incorrectos."
        : error.message || "No se pudo iniciar sesión.",
    );
    setLoading(false);
  }
});

(async function boot() {
  try {
    await refresh();
    location.replace(CONFIG.MONITOR_PAGE);
  } catch {
    /* sin sesión previa: se muestra el formulario */
  }
})();
