const DEFAULT_API = "https://gerador-relatorios-production-eca0.up.railway.app";

const el = (id) => document.getElementById(id);

const apiBaseEl = el("apiBase");
const fileInput = el("fileInput");

const btnHealth = el("btnHealth");
const btnUpload = el("btnUpload");
const btnOptions = el("btnOptions");
const btnGerar = el("btnGerar");
const btnReset = el("btnReset");
const btnClearLog = el("btnClearLog");

const statusDot = el("statusDot");
const statusText = el("statusText");

const uploadIdEl = el("uploadId");
const uploadNameEl = el("uploadName");
const optionsArea = el("optionsArea");
const logEl = el("log");

let state = {
  upload_id: null,
  options: null,
  selections: {},
};

function log(msg, obj) {
  const ts = new Date().toLocaleString();
  let line = `[${ts}] ${msg}`;
  if (obj !== undefined) {
    try { line += "\n" + JSON.stringify(obj, null, 2); }
    catch { line += "\n" + String(obj); }
  }
  logEl.textContent = (line + "\n\n" + logEl.textContent).slice(0, 12000);
}

function setStatus(ok, text) {
  statusDot.style.background = ok ? "var(--good)" : "var(--bad)";
  statusDot.style.boxShadow = ok
    ? "0 0 0 4px rgba(34,197,94,.18)"
    : "0 0 0 4px rgba(239,68,68,.18)";
  statusText.textContent = text;
}

function apiUrl(path) {
  const base = (apiBaseEl.value || "").trim().replace(/\/+$/, "");
  return `${base}${path}`;
}

async function fetchWithTimeout(url, opts = {}, timeoutMs = 60000) {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(url, { ...opts, signal: ctrl.signal });
    return res;
  } finally {
    clearTimeout(t);
  }
}

async function healthCheck() {
  try {
    setStatus(true, "Checando…");
    const res = await fetchWithTimeout(apiUrl("/health"), {}, 20000);
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      setStatus(false, `Falhou (${res.status})`);
      log("Health FAIL", { status: res.status, data });
      return;
    }
    setStatus(true, data?.status === "ok" ? "Online (health ok)" : "Online");
    log("Health OK", data);
  } catch (e) {
    setStatus(false, "Offline / erro");
    log("Health ERROR", { error: String(e) });
  }
}

function resetAll() {
  state = { upload_id: null, options: null, selections: {} };
  uploadIdEl.textContent = "—";
  uploadNameEl.textContent = "—";
  optionsArea.innerHTML = `
    <div class="empty">
      <div class="icon">⚙️</div>
      <div>
        <b>Nenhuma opção carregada ainda.</b>
        <div class="muted">Faça o upload e clique em “Buscar opções”.</div>
      </div>
    </div>
  `;
  log("Reset feito.");
}

function normalizeOptionItem(item) {
  // Aceita: "SC", 2025, {value,label}, {id,name}, etc.
  if (item === null || item === undefined) return { value: "", label: "" };
  if (typeof item === "string" || typeof item === "number" || typeof item === "boolean") {
    return { value: String(item), label: String(item) };
  }
  if (typeof item === "object") {
    if ("value" in item && "label" in item) return { value: String(item.value), label: String(item.label) };
    if ("id" in item && "name" in item) return { value: String(item.id), label: String(item.name) };
    // fallback: stringify compacto
    const asText = JSON.stringify(item);
    return { value: asText, label: asText };
  }
  return { value: String(item), label: String(item) };
}

function isArrayOfPrimitives(arr) {
  return Array.isArray(arr) && arr.every(v => ["string","number","boolean"].includes(typeof v) || v === null);
}

function renderOptions(optionsJson) {
  optionsArea.innerHTML = "";

  const keys = Object.keys(optionsJson || {});
  if (!keys.length) {
    optionsArea.innerHTML = `
      <div class="empty">
        <div class="icon">😶</div>
        <div>
          <b>API retornou opções vazias.</b>
          <div class="muted">Se isso estiver errado, me manda um print do Swagger de <code>/faturamento/options</code>.</div>
        </div>
      </div>
    `;
    return;
  }

  const grid = document.createElement("div");
  grid.className = "optionGrid";

  keys.forEach((k) => {
    const v = optionsJson[k];

    // Se for lista -> multi-select
    if (Array.isArray(v)) {
      const field = document.createElement("div");
      field.className = "field";

      const label = document.createElement("label");
      label.textContent = k;

      const select = document.createElement("select");
      select.multiple = true;
      select.dataset.key = k;

      const items = v.map(normalizeOptionItem);
      items.forEach(({ value, label }) => {
        const opt = document.createElement("option");
        opt.value = value;
        opt.textContent = label;
        select.appendChild(opt);
      });

      select.addEventListener("change", () => {
        const chosen = Array.from(select.selectedOptions).map(o => o.value);
        state.selections[k] = chosen;
      });

      field.appendChild(label);
      field.appendChild(select);

      const hint = document.createElement("small");
      hint.textContent = "Selecione 1 ou mais (Ctrl/Shift).";
      field.appendChild(hint);

      grid.appendChild(field);
      return;
    }

    // Se for string/number/bool -> input
    if (["string","number","boolean"].includes(typeof v) || v === null) {
      const field = document.createElement("div");
      field.className = "field";

      const label = document.createElement("label");
      label.textContent = k;

      const input = document.createElement("input");
      input.type = "text";
      input.value = v === null ? "" : String(v);
      input.dataset.key = k;

      input.addEventListener("input", () => {
        state.selections[k] = input.value;
      });

      field.appendChild(label);
      field.appendChild(input);

      const hint = document.createElement("small");
      hint.textContent = "Campo simples retornado pela API.";
      field.appendChild(hint);

      grid.appendChild(field);
      return;
    }

    // Se for objeto -> mostra JSON e cria textarea
    if (typeof v === "object") {
      const field = document.createElement("div");
      field.className = "field";

      const label = document.createElement("label");
      label.textContent = k;

      const input = document.createElement("input");
      input.type = "text";
      input.value = JSON.stringify(v);
      input.dataset.key = k;

      input.addEventListener("input", () => {
        state.selections[k] = input.value;
      });

      field.appendChild(label);
      field.appendChild(input);

      const hint = document.createElement("small");
      hint.textContent = "Objeto complexo (fallback). Se quiser, eu adapto pra ficar bonito.";
      field.appendChild(hint);

      grid.appendChild(field);
      return;
    }
  });

  const box = document.createElement("div");
  box.className = "optionsBox";
  box.appendChild(grid);

  optionsArea.appendChild(box);
}

async function uploadFile() {
  const f = fileInput.files?.[0];
  if (!f) {
    log("Selecione um arquivo antes.");
    return;
  }

  btnUpload.disabled = true;
  try {
    log("Upload iniciando…", { name: f.name, size: f.size });

    const fd = new FormData();
    fd.append("file", f);

    const res = await fetchWithTimeout(apiUrl("/upload"), {
      method: "POST",
      body: fd,
    }, 120000);

    const data = await res.json().catch(() => ({}));

    if (!res.ok) {
      log("Upload FAIL", { status: res.status, data });
      return;
    }

    // esperado: { upload_id, filename }
    state.upload_id = data.upload_id || data.uploadId || null;

    uploadIdEl.textContent = state.upload_id || "—";
    uploadNameEl.textContent = data.filename || f.name;

    log("Upload OK", data);
  } catch (e) {
    log("Upload ERROR", { error: String(e) });
  } finally {
    btnUpload.disabled = false;
  }
}

async function fetchOptions() {
  if (!state.upload_id) {
    log("Você precisa fazer upload primeiro (upload_id está vazio).");
    return;
  }

  btnOptions.disabled = true;
  try {
    log("Buscando opções…", { upload_id: state.upload_id });

    const url = apiUrl(`/faturamento/options?upload_id=${encodeURIComponent(state.upload_id)}`);
    const res = await fetchWithTimeout(url, { method: "GET" }, 120000);

    const data = await res.json().catch(() => ({}));

    if (!res.ok) {
      log("Options FAIL", { status: res.status, data });
      return;
    }

    state.options = data;
    state.selections = {}; // reset selections a cada options novo
    renderOptions(data);

    log("Options OK", data);
  } catch (e) {
    log("Options ERROR", { error: String(e) });
  } finally {
    btnOptions.disabled = false;
  }
}

function getFileNameFromHeaders(res) {
  const cd = res.headers.get("content-disposition");
  if (!cd) return null;
  const m = /filename\*?=(?:UTF-8'')?["']?([^"';]+)["']?/i.exec(cd);
  if (!m) return null;
  try { return decodeURIComponent(m[1]); } catch { return m[1]; }
}

async function gerarRelatorio() {
  if (!state.upload_id) {
    log("Sem upload_id. Faça upload primeiro.");
    return;
  }

  btnGerar.disabled = true;
  try {
    // payload “seguro”: sempre manda upload_id + selections
    const payload = {
      upload_id: state.upload_id,
      ...state.selections,
    };

    log("Gerando relatório… (POST /faturamento/gerar)", payload);

    const res = await fetchWithTimeout(apiUrl("/faturamento/gerar"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }, 180000);

    const ct = res.headers.get("content-type") || "";
    if (!res.ok) {
      const err = await res.text();
      log("Gerar FAIL", { status: res.status, body: err });
      return;
    }

    // Se for JSON -> salva como .json
    if (ct.includes("application/json") || ct.includes("text/json")) {
      const json = await res.json();
      log("Gerar OK (json)", json);

      const blob = new Blob([JSON.stringify(json, null, 2)], { type: "application/json" });
      downloadBlob(blob, `relatorio_${Date.now()}.json`);
      return;
    }

    // Senão, tenta baixar arquivo
    const blob = await res.blob();
    const name = getFileNameFromHeaders(res) || `relatorio_${Date.now()}`;
    log("Gerar OK (arquivo)", { contentType: ct, filename: name, size: blob.size });
    downloadBlob(blob, name);
  } catch (e) {
    log("Gerar ERROR", { error: String(e) });
  } finally {
    btnGerar.disabled = false;
  }
}

function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

// init
(function init() {
  apiBaseEl.value = DEFAULT_API;

  btnHealth.addEventListener("click", healthCheck);
  btnUpload.addEventListener("click", uploadFile);
  btnOptions.addEventListener("click", fetchOptions);
  btnGerar.addEventListener("click", gerarRelatorio);
  btnReset.addEventListener("click", resetAll);
  btnClearLog.addEventListener("click", () => (logEl.textContent = ""));

  // auto-check
  healthCheck();
})();
