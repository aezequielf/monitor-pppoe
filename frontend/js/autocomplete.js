/**
 * Combobox de usuarios conectados.
 *
 * - Al llegar a `minChars` (3) consulta el backend una sola vez por prefijo.
 * - Los caracteres siguientes filtran localmente la lista ya obtenida.
 * - La selección final se hace con clic o con ArrowUp/Down + Enter.
 */
export function initUserAutocomplete({ input, list, fetchUsers, minChars = 3 }) {
  let basePrefix = "";
  let users = [];
  let matches = [];
  let activeIndex = -1;
  let loading = false;
  let errorMessage = "";
  let controller = null;
  let sequence = 0;

  const value = () => input.value.trim();

  function optionId(index) {
    return `${list.id}-option-${index}`;
  }

  function setExpanded(expanded) {
    input.setAttribute("aria-expanded", expanded ? "true" : "false");
    list.hidden = !expanded;
    if (!expanded) input.removeAttribute("aria-activedescendant");
  }

  function close() {
    setExpanded(false);
    activeIndex = -1;
  }

  function cancel() {
    if (controller) {
      controller.abort();
      controller = null;
    }
    sequence += 1;
  }

  function clearState() {
    cancel();
    basePrefix = "";
    users = [];
    matches = [];
    activeIndex = -1;
    loading = false;
    errorMessage = "";
    close();
  }

  function addStatus(text, kind = "") {
    const item = document.createElement("li");
    item.className = kind ? `combo__status combo__status--${kind}` : "combo__status";
    item.setAttribute("role", "presentation");
    item.textContent = text;
    list.appendChild(item);
  }

  function render() {
    list.replaceChildren();
    if (activeIndex < 0) input.removeAttribute("aria-activedescendant");

    if (loading) {
      addStatus("Buscando usuarios…");
      setExpanded(true);
      return;
    }
    if (errorMessage) {
      addStatus(errorMessage, "error");
      setExpanded(true);
      return;
    }
    if (value().length < minChars) {
      close();
      return;
    }
    if (!users.length) {
      addStatus("Sin usuarios conectados con ese prefijo.", "empty");
      setExpanded(true);
      return;
    }
    if (!matches.length) {
      addStatus("Sin coincidencias para ese texto.", "empty");
      setExpanded(true);
      return;
    }

    matches.forEach((user, index) => {
      const item = document.createElement("li");
      item.id = optionId(index);
      item.className = index === activeIndex ? "combo__option is-active" : "combo__option";
      item.setAttribute("role", "option");
      item.setAttribute("aria-selected", index === activeIndex ? "true" : "false");
      item.textContent = user;
      item.addEventListener("pointerdown", (event) => {
        event.preventDefault();
        select(user);
      });
      list.appendChild(item);
    });

    setExpanded(true);
    if (activeIndex >= 0) {
      input.setAttribute("aria-activedescendant", optionId(activeIndex));
    } else {
      input.removeAttribute("aria-activedescendant");
    }
  }

  function applyFilter() {
    const term = value().toLowerCase();
    matches = users.filter((user) => user.toLowerCase().startsWith(term));
    activeIndex = matches.length ? 0 : -1;
    loading = false;
    errorMessage = "";
    render();
  }

  async function load(prefix) {
    cancel();
    const requestId = sequence;
    controller = new AbortController();
    basePrefix = prefix;
    users = [];
    matches = [];
    activeIndex = -1;
    errorMessage = "";
    loading = true;
    render();

    try {
      const data = await fetchUsers(prefix, controller.signal);
      if (requestId !== sequence) return;
      const result = data && Array.isArray(data.resultado) ? data.resultado : [];
      users = [
        ...new Set(
          result
            .filter((item) => typeof item === "string")
            .map((item) => item.trim())
            .filter((item) => item.length > 0),
        ),
      ];
      loading = false;
      applyFilter();
    } catch (error) {
      if (requestId !== sequence || (error && error.name === "AbortError")) return;
      loading = false;
      matches = [];
      errorMessage = error.message || "No se pudo consultar el servicio de usuarios.";
      render();
    } finally {
      if (requestId === sequence) controller = null;
    }
  }

  function select(user) {
    input.value = user;
    cancel();
    basePrefix = "";
    users = [];
    matches = [];
    activeIndex = -1;
    loading = false;
    errorMessage = "";
    close();
    input.focus();
  }

  function moveActive(delta) {
    const next =
      activeIndex < 0
        ? 0
        : (activeIndex + delta + matches.length) % matches.length;
    activeIndex = next;
    render();
    const node = list.children[activeIndex];
    if (node) node.scrollIntoView({ block: "nearest" });
  }

  input.addEventListener("input", () => {
    const term = value();
    if (term.length < minChars) {
      clearState();
      return;
    }

    const prefix = term.slice(0, minChars);
    if (prefix !== basePrefix || errorMessage) {
      load(prefix);
      return;
    }
    if (!loading) applyFilter();
  });

  input.addEventListener("focus", () => {
    if (value().length >= minChars && !loading && (users.length || errorMessage)) {
      render();
    }
  });

  input.addEventListener("blur", close);

  input.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      if (!list.hidden) {
        event.preventDefault();
        close();
      }
      return;
    }

    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      if (loading) return;
      if (list.hidden) {
        if (matches.length) {
          event.preventDefault();
          render();
        }
        return;
      }
      if (!matches.length) return;
      event.preventDefault();
      moveActive(event.key === "ArrowDown" ? 1 : -1);
      return;
    }

    if (event.key === "Enter" && !list.hidden && activeIndex >= 0) {
      const selected = matches[activeIndex];
      if (selected === value()) {
        close();
        return;
      }
      event.preventDefault();
      select(selected);
    }
  });

  return { close, clear: clearState };
}
