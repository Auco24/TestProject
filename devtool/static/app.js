"use strict";

/* ======================================================================
   Helpers
   ====================================================================== */
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

const store = {
  get(key, fallback = null) { try { return localStorage.getItem("devtool-" + key) ?? fallback; } catch { return fallback; } },
  set(key, value) { try { localStorage.setItem("devtool-" + key, value); } catch { /* ignore */ } },
};

const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

function debounce(fn, ms = 220) {
  let t;
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
}

class ApiError extends Error {
  constructor(info) { super(info.message); Object.assign(this, info); }
}

async function api(tool, body = {}) {
  const res = await fetch("/api/tools/" + tool, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError(data.error || { message: data.detail || "Ошибка сервера" });
  return data.result;
}

function toast(msg, isError = false) {
  const el = document.createElement("div");
  el.className = "toast" + (isError ? " err" : "");
  el.textContent = msg;
  $("#toasts").appendChild(el);
  setTimeout(() => { el.style.transition = "opacity .3s"; el.style.opacity = "0"; }, 1800);
  setTimeout(() => el.remove(), 2200);
}

async function copyText(text) {
  if (!text || !text.trim()) return toast("Нечего копировать", true);
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    const ta = Object.assign(document.createElement("textarea"), { value: text });
    document.body.appendChild(ta); ta.select(); document.execCommand("copy"); ta.remove();
  }
  toast("Скопировано");
}

function highlightJson(json) {
  return esc(json).replace(
    /(&quot;(?:\\.|(?!&quot;)[^\\])*&quot;)(\s*:)?|\b(true|false)\b|\bnull\b|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?/g,
    (m, str, colon, bool) => {
      if (str) return colon ? `<span class="j-key">${str}</span>${colon}` : `<span class="j-str">${str}</span>`;
      if (bool) return `<span class="j-bool">${m}</span>`;
      if (m === "null") return `<span class="j-null">${m}</span>`;
      return `<span class="j-num">${m}</span>`;
    }
  );
}

function segValue(name) { return $(`.segmented[data-name="${name}"] .on`).dataset.value; }

/* ======================================================================
   Icons, tabs, theme, palette
   ====================================================================== */
const ICONS = {
  braces: '<path d="M8 4H7a2 2 0 0 0-2 2v4l-2 2 2 2v4a2 2 0 0 0 2 2h1M16 4h1a2 2 0 0 1 2 2v4l2 2-2 2v4a2 2 0 0 1-2 2h-1"/>',
  key: '<circle cx="8" cy="15" r="4"/><path d="M11 12l9-9M17 6l3 3M15 8l2 2"/>',
  code: '<path d="M4 7V5h16v2M9 19h6M12 5v14"/>',
  clock: '<circle cx="12" cy="12" r="8.5"/><path d="M12 7v5l3 2"/>',
  regex: '<path d="M17 3v10M12.7 5.5l8.6 5M12.7 10.5l8.6-5"/><rect x="3" y="15" width="6" height="6" rx="1.5"/>',
  snippet: '<path d="M8 4h8l4 4v12H4V4h4zM8 4v4h8"/><path d="M8 13h8M8 17h5"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  journal: '<path d="M5 4h11a3 3 0 0 1 3 3v13H8a3 3 0 0 1-3-3z"/><path d="M5 17a3 3 0 0 1 3-3h11"/>',
  copy: '<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V5a1 1 0 0 1 1-1h10"/>',
  star: '<path d="M12 3.5l2.6 5.3 5.9.9-4.3 4.1 1 5.8L12 16.9l-5.2 2.7 1-5.8-4.3-4.1 5.9-.9z"/>',
  edit: '<path d="M4 20h4L19 9l-4-4L4 16z"/><path d="M13.5 6.5l4 4"/>',
  trash: '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/>',
  sparkle: '<path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z"/><path d="M19 16l.8 2.2L22 19l-2.2.8L19 22l-.8-2.2L16 19l2.2-.8z"/>',
};
const svg = (name) => `<svg viewBox="0 0 24 24">${ICONS[name] || ""}</svg>`;
const TOOLS = $$(".tool").map((el) => ({ id: el.dataset.tool, title: el.dataset.title, desc: el.dataset.desc, icon: el.dataset.icon, el }));
const onActivate = {};

const VIEWS = {
  utils: { title: "Утилиты", sub: "Всё работает локально, данные не покидают ваш компьютер." },
  snippets: { title: "Сниппеты", sub: "Команды и куски кода, которые всегда под рукой." },
  journal: { title: "Дневник", sub: "Что сделано, что в планах и что мешает. Отчёт к стендапу в один клик." },
};
const onView = {};
let currentView = null;

function showView(name) {
  if (!VIEWS[name]) name = "utils";
  $$(".view").forEach((v) => (v.hidden = v.id !== "view-" + name));
  $$(".nav-item[data-view]").forEach((a) => a.classList.toggle("active", a.dataset.view === name));
  $("#pageTitle").textContent = VIEWS[name].title;
  $("#pageSub").textContent = VIEWS[name].sub;
  const changed = currentView !== name;
  currentView = name;
  if (changed) onView[name]?.();
}

function route() {
  const hash = decodeURIComponent(location.hash.slice(1));
  if (hash.startsWith("snippets")) {
    showView("snippets");
    onView.snippetsRoute?.(hash.split("/")[1]);
  } else if (hash === "journal") {
    showView("journal");
  } else {
    activate(hash || store.get("tab", "json"));
  }
}
window.addEventListener("hashchange", route);

function activate(id) {
  showView("utils");
  const tool = TOOLS.find((t) => t.id === id) || TOOLS[0];
  TOOLS.forEach((t) => t.el.classList.toggle("active", t === tool));
  $$(".tab").forEach((b) => b.classList.toggle("active", b.dataset.tool === tool.id));
  store.set("tab", tool.id);
  history.replaceState(null, "", "#" + tool.id);
  onActivate[tool.id]?.();
  const first = $("textarea, input:not([type=checkbox]):not([type=range])", tool.el);
  if (first && window.innerWidth > 760) first.focus({ preventScroll: true });
}

$("#tabs").innerHTML = TOOLS.map((t) =>
  `<button class="tab" role="tab" data-tool="${t.id}"><span class="tab-ico">${svg(t.icon)}</span><span><b>${t.title}</b><small>${t.desc}</small></span></button>`
).join("");
$$(".tab").forEach((b) => b.addEventListener("click", () => activate(b.dataset.tool)));

$("#themeToggle").addEventListener("click", () => {
  const next = document.documentElement.dataset.theme === "light" ? "dark" : "light";
  document.documentElement.dataset.theme = next;
  store.set("theme", next);
});

// Command palette (Ctrl/Cmd+K): tools, modules and snippets
const palette = { el: $("#palette"), input: $("#paletteIn"), list: $("#paletteList"), sel: 0, items: [], snippets: [] };
const PALETTE_STATIC = [
  ...TOOLS.map((t) => ({ kind: "tool", id: t.id, title: t.title, desc: t.desc, icon: t.icon })),
  { kind: "view", id: "snippets", title: "Сниппеты", desc: "Модуль", icon: "snippet" },
  { kind: "view", id: "journal", title: "Дневник", desc: "Модуль", icon: "journal" },
  { kind: "action", id: "new-snippet", title: "Новый сниппет", desc: "Действие", icon: "plus" },
  { kind: "action", id: "log", title: "Записать в дневник", desc: "Действие", icon: "journal" },
  { kind: "action", id: "standup", title: "Скопировать отчёт к стендапу", desc: "Действие", icon: "copy" },
];
function renderPalette() {
  const q = palette.input.value.trim().toLowerCase();
  palette.items = [
    ...PALETTE_STATIC.filter((t) => (t.title + " " + t.desc).toLowerCase().includes(q)),
    ...palette.snippets.map((s) => ({ kind: "snippet", id: s.id, title: s.title, desc: "копировать · " + s.language, icon: "copy", snippet: s })),
  ];
  palette.sel = Math.min(palette.sel, Math.max(0, palette.items.length - 1));
  let lastKind = null;
  palette.list.innerHTML = palette.items.map((t, i) => {
    let head = "";
    if (t.kind === "snippet" && lastKind !== "snippet") head = '<div class="palette-group">Сниппеты</div>';
    lastKind = t.kind;
    return `${head}<div class="palette-item${i === palette.sel ? " sel" : ""}" data-i="${i}"><span class="tab-ico">${svg(t.icon)}</span><b>${esc(t.title)}</b><small>${esc(t.desc)}</small></div>`;
  }).join("") || '<div class="palette-item muted">Ничего не найдено</div>';
  $(".palette-item.sel", palette.list)?.scrollIntoView({ block: "nearest" });
}
const searchPaletteSnippets = debounce(async () => {
  const q = palette.input.value.trim();
  if (!q) { palette.snippets = []; renderPalette(); return; }
  try {
    const r = await (await fetch("/api/snippets?q=" + encodeURIComponent(q))).json();
    palette.snippets = (r.items || []).slice(0, 8);
  } catch { palette.snippets = []; }
  renderPalette();
}, 150);
function runPaletteItem(item) {
  closePalette();
  if (item.kind === "tool") activate(item.id);
  else if (item.kind === "view") location.hash = item.id;
  else if (item.id === "new-snippet") { location.hash = "snippets"; setTimeout(() => onView.newSnippet?.(), 0); }
  else if (item.id === "log") { location.hash = "journal"; setTimeout(() => onView.focusJournal?.(), 50); }
  else if (item.id === "standup") onView.copyStandup?.();
  else if (item.kind === "snippet") onView.copySnippet?.(item.snippet);
}
function openPalette() { palette.el.hidden = false; palette.input.value = ""; palette.sel = 0; palette.snippets = []; renderPalette(); palette.input.focus(); }
function closePalette() { palette.el.hidden = true; }
$("#openPalette").addEventListener("click", openPalette);
palette.el.addEventListener("click", (e) => { if (e.target === palette.el) closePalette(); });
palette.input.addEventListener("input", () => { palette.sel = 0; renderPalette(); searchPaletteSnippets(); });
palette.list.addEventListener("click", (e) => {
  const it = e.target.closest("[data-i]");
  if (it) runPaletteItem(palette.items[it.dataset.i]);
});
document.addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); palette.el.hidden ? openPalette() : closePalette(); return; }
  if (palette.el.hidden) return;
  if (e.key === "Escape") closePalette();
  else if (e.key === "ArrowDown" || e.key === "ArrowUp") {
    e.preventDefault();
    const n = palette.items.length || 1;
    palette.sel = (palette.sel + (e.key === "ArrowDown" ? 1 : -1) + n) % n;
    renderPalette();
  } else if (e.key === "Enter" && palette.items[palette.sel]) { e.preventDefault(); runPaletteItem(palette.items[palette.sel]); }
});

/* ======================================================================
   Generic controls
   ====================================================================== */
$$(".segmented").forEach((seg) => seg.addEventListener("click", (e) => {
  const b = e.target.closest("button");
  if (!b || b.classList.contains("on")) return;
  $$("button", seg).forEach((x) => x.classList.toggle("on", x === b));
  seg.dispatchEvent(new Event("change", { bubbles: true }));
}));

document.addEventListener("click", (e) => {
  const copy = e.target.closest("[data-copy]");
  if (copy) {
    const el = document.getElementById(copy.dataset.copy);
    copyText(el.value ?? el.innerText);
    return;
  }
  const clear = e.target.closest("[data-clear]");
  if (clear) {
    const el = document.getElementById(clear.dataset.clear);
    el.value = ""; el.dispatchEvent(new Event("input")); el.focus();
  }
  const sample = e.target.closest("[data-sample]");
  if (sample) SAMPLES[sample.dataset.sample]();
});

/* ======================================================================
   JSON
   ====================================================================== */
const jsonIn = $("#jsonIn"), jsonOut = $("#jsonOut"), jsonMeta = $("#jsonMeta");
async function runJson() {
  const text = jsonIn.value;
  jsonOut.classList.remove("error");
  if (!text.trim()) { jsonOut.innerHTML = ""; jsonMeta.textContent = ""; return; }
  const mode = segValue("jsonMode");
  try {
    const out = await api("json/" + mode, { text, indent: +$("#jsonIndent").value, sort_keys: $("#jsonSort").checked });
    jsonOut.innerHTML = highlightJson(out);
    const kb = (n) => (n / 1024).toFixed(n < 10240 ? 1 : 0) + " KB";
    jsonMeta.textContent = `✓ валидный · ${kb(new Blob([text]).size)} → ${kb(new Blob([out]).size)}`;
  } catch (err) {
    jsonOut.classList.add("error");
    jsonOut.textContent = "✗ " + err.message;
    jsonMeta.textContent = "";
  }
}
const runJsonD = debounce(runJson);
jsonIn.addEventListener("input", runJsonD);
["#jsonIndent", "#jsonSort"].forEach((s) => $(s).addEventListener("change", runJson));
$('[data-name="jsonMode"]').addEventListener("change", runJson);

/* ======================================================================
   JWT
   ====================================================================== */
const jwtIn = $("#jwtIn");
const STATUS_TEXT = {
  valid: "✓ Токен действителен",
  expired: "✗ Срок действия токена истёк",
  "not-yet-valid": "… Токен ещё не начал действовать (nbf)",
  "no-exp": "• У токена нет срока действия (exp)",
};
const TIME_LABEL = { iat: "Выдан (iat)", nbf: "Действует с (nbf)", exp: "Истекает (exp)" };
async function runJwt() {
  const token = jwtIn.value.trim();
  const status = $("#jwtStatus");
  if (!token) {
    ["#jwtColored", "#jwtStatus", "#jwtHeader", "#jwtPayload", "#jwtTimes"].forEach((s) => ($(s).innerHTML = ""));
    status.className = "jwt-status";
    return;
  }
  try {
    const r = await api("jwt/decode", { token });
    const [h, p, s] = r.parts;
    $("#jwtColored").innerHTML = `<span class="h">${esc(h)}</span><span class="d">.</span><span class="p">${esc(p)}</span><span class="d">.</span><span class="s">${esc(s)}</span>`;
    status.className = "jwt-status " + r.status;
    let extra = "";
    if (r.times.exp) extra = ` · ${r.times.exp.relative}`;
    status.textContent = STATUS_TEXT[r.status] + extra;
    $("#jwtHeader").innerHTML = highlightJson(JSON.stringify(r.header, null, 2));
    $("#jwtPayload").innerHTML = highlightJson(JSON.stringify(r.payload, null, 2));
    $("#jwtTimes").innerHTML = Object.entries(r.times).map(([k, t]) =>
      `<div class="card kv" data-value="${esc(t.iso)}"><div class="k">${TIME_LABEL[k]}<i>копировать</i></div><div class="v">${esc(new Date(t.iso).toLocaleString("ru-RU"))}</div><div class="muted small">${esc(t.relative)}</div></div>`
    ).join("");
  } catch (err) {
    ["#jwtColored", "#jwtHeader", "#jwtPayload", "#jwtTimes"].forEach((s) => ($(s).innerHTML = ""));
    status.className = "jwt-status error";
    status.textContent = "✗ " + err.message;
  }
}
jwtIn.addEventListener("input", debounce(runJwt));

/* ======================================================================
   Base64 / URL
   ====================================================================== */
const encIn = $("#encIn"), encOut = $("#encOut");
async function runEnc() {
  const kind = segValue("encKind"), dir = segValue("encDir");
  $("#urlSafeWrap").style.display = kind === "base64" ? "" : "none";
  encOut.classList.remove("error");
  if (!encIn.value) { encOut.textContent = ""; return; }
  try {
    encOut.textContent = await api(`${kind}/${dir}`, { text: encIn.value, url_safe: $("#b64UrlSafe").checked });
  } catch (err) {
    encOut.classList.add("error");
    encOut.textContent = "✗ " + err.message;
  }
}
encIn.addEventListener("input", debounce(runEnc));
$("#b64UrlSafe").addEventListener("change", runEnc);
$$('[data-name="encKind"], [data-name="encDir"]').forEach((s) => s.addEventListener("change", runEnc));
$("#encSwap").addEventListener("click", () => {
  if (encOut.classList.contains("error")) return toast("Сначала исправьте ошибку", true);
  encIn.value = encOut.textContent;
  const seg = $('[data-name="encDir"]');
  $$("button", seg).forEach((b) => b.classList.toggle("on"));
  runEnc();
});

/* ======================================================================
   Timestamp
   ====================================================================== */
const tsIn = $("#tsIn"), tsTz = $("#tsTz");
(function initTz() {
  const local = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  let zones = [];
  try { zones = Intl.supportedValuesOf("timeZone"); } catch { /* old browser */ }
  if (!zones.length) zones = ["Europe/Berlin", "Europe/Moscow", "Europe/London", "America/New_York", "Asia/Tokyo"];
  const all = ["UTC", ...zones.filter((z) => z !== "UTC" && z !== local)];
  tsTz.innerHTML = `<option value="${local}">${local} (локальный)</option>` + all.map((z) => `<option>${z}</option>`).join("");
  tsTz.value = store.get("tz", local);
  if (!tsTz.value) tsTz.value = local;
})();
async function runTs() {
  const hero = $("#tsHero");
  try {
    const r = await api("timestamp", { value: tsIn.value, tz: tsTz.value });
    hero.className = "hero-time";
    hero.innerHTML = `<div class="big">${esc(r.human)}</div><div class="sub">${esc(r.weekday)} · ${esc(r.timezone)}</div><span class="rel">${esc(r.relative)}</span>`;
    const cards = [
      ["Unix, секунды", r.unix], ["Unix, миллисекунды", r.unix_ms],
      ["ISO 8601 (UTC)", r.iso_utc], [`ISO 8601 (${r.timezone})`, r.iso_local],
      ["RFC 2822", r.rfc2822],
    ];
    $("#tsCards").innerHTML = cards.map(([k, v]) =>
      `<div class="card kv" data-value="${esc(v)}"><div class="k">${esc(k)}<i>копировать</i></div><div class="v">${esc(v)}</div></div>`
    ).join("");
  } catch (err) {
    hero.className = "hero-time error";
    hero.textContent = "✗ " + err.message;
    $("#tsCards").innerHTML = "";
  }
}
tsIn.addEventListener("input", debounce(runTs));
tsTz.addEventListener("change", () => { store.set("tz", tsTz.value); runTs(); });
$("#tsNow").addEventListener("click", () => { tsIn.value = Math.floor(Date.now() / 1000); runTs(); });
onActivate.time = runTs;

document.addEventListener("click", (e) => {
  const kv = e.target.closest(".kv[data-value]");
  if (kv) copyText(kv.dataset.value);
});

/* ======================================================================
   Regex
   ====================================================================== */
const reIn = $("#reIn"), reText = $("#reText"), reHl = $("#reHighlight");
const reFlags = new Set(store.get("re-flags", "").split("").filter(Boolean));
$$("#reFlags button").forEach((b) => {
  b.classList.toggle("on", reFlags.has(b.dataset.flag));
  b.addEventListener("click", () => {
    reFlags.has(b.dataset.flag) ? reFlags.delete(b.dataset.flag) : reFlags.add(b.dataset.flag);
    b.classList.toggle("on");
    store.set("re-flags", [...reFlags].join(""));
    runRe();
  });
});

async function runRe() {
  const text = reText.value, pattern = reIn.value;
  const bar = $(".regex-bar"), errEl = $("#reError"), list = $("#reMatches"), meta = $("#reMeta");
  bar.classList.remove("bad"); errEl.textContent = "";
  if (!pattern) {
    reHl.innerHTML = esc(text) + "\n"; meta.textContent = "";
    list.innerHTML = '<div class="empty">Введите регулярное выражение</div>';
    return;
  }
  try {
    const r = await api("regex", { pattern, text, flags: [...reFlags].join("") });
    // Python returns code-point offsets; slice by code points so emoji etc. line up.
    const chars = Array.from(text);
    let html = "", pos = 0;
    r.matches.forEach((m, i) => {
      if (m.end === m.start) return;
      html += esc(chars.slice(pos, m.start).join(""));
      html += `<mark class="${i % 2 ? "alt" : ""}">${esc(chars.slice(m.start, m.end).join(""))}</mark>`;
      pos = m.end;
    });
    reHl.innerHTML = html + esc(chars.slice(pos).join("")) + "\n";
    meta.textContent = `${r.count}${r.truncated ? "+" : ""} совп.`;
    list.innerHTML = r.matches.length ? r.matches.map((m, i) => {
      const groups = m.groups.map((g, gi) => {
        const name = r.group_names[gi];
        return `<span class="grp"><b>${esc(name || gi + 1)}</b>${g === null ? '<span class="muted">null</span>' : esc(g)}</span>`;
      }).join("");
      return `<div class="match"><div class="match-top"><span class="match-idx">${i + 1}</span><span class="match-val">${esc(m.match) || '<span class="muted">(пусто)</span>'}</span><span class="match-pos">${m.start}–${m.end}</span></div>${groups ? `<div class="match-groups">${groups}</div>` : ""}</div>`;
    }).join("") : '<div class="empty">Совпадений нет</div>';
  } catch (err) {
    bar.classList.add("bad");
    errEl.textContent = "✗ " + err.message;
    reHl.innerHTML = esc(text) + "\n";
    meta.textContent = "";
    list.innerHTML = "";
  }
}
const runReD = debounce(runRe, 180);
reIn.addEventListener("input", runReD);
reText.addEventListener("input", () => { reHl.innerHTML = esc(reText.value) + "\n"; runReD(); });
reText.addEventListener("scroll", () => { reHl.scrollTop = reText.scrollTop; });

/* ======================================================================
   Generators
   ====================================================================== */
const STRENGTH_COLOR = { "слабый": "var(--red)", "средний": "var(--yellow)", "сильный": "var(--green)", "очень сильный": "var(--cyan)" };
async function runPw() {
  $("#pwLenVal").textContent = $("#pwLen").value;
  try {
    const r = await api("password", {
      length: +$("#pwLen").value,
      upper: $("#pwUpper").checked, lower: $("#pwLower").checked,
      digits: $("#pwDigits").checked, symbols: $("#pwSymbols").checked,
      exclude_ambiguous: $("#pwAmb").checked,
    });
    $("#pwOut").textContent = r.password;
    $("#pwInfo").textContent = `Энтропия ≈ ${r.entropy} бит · ${r.strength}`;
    $("#pwMeter").style.width = Math.min(100, (r.entropy / 160) * 100) + "%";
    $("#pwMeter").style.background = STRENGTH_COLOR[r.strength];
  } catch (err) {
    $("#pwOut").textContent = "—";
    $("#pwInfo").textContent = err.message;
    $("#pwMeter").style.width = "0";
  }
}
$("#pwLen").addEventListener("input", debounce(runPw, 60));
$$("#pwUpper, #pwLower, #pwDigits, #pwSymbols, #pwAmb").forEach((el) => el.addEventListener("change", runPw));
$("#pwRegen").addEventListener("click", runPw);

async function runUuid() {
  try {
    const list = await api("uuid", { count: +$("#uuidCount").value || 1, uppercase: $("#uuidUpper").checked, hyphens: !$("#uuidNoHyph").checked });
    $("#uuidList").innerHTML = list.map((u) => `<div title="Нажмите, чтобы скопировать">${u}</div>`).join("");
  } catch (err) { toast(err.message, true); }
}
$("#uuidGen").addEventListener("click", runUuid);
$$("#uuidUpper, #uuidNoHyph, #uuidCount").forEach((el) => el.addEventListener("change", runUuid));
$("#uuidList").addEventListener("click", (e) => { if (e.target.parentElement.id === "uuidList") copyText(e.target.textContent); });

async function runHash() {
  try {
    const r = await api("hash", { text: $("#hashIn").value });
    $("#hashList").innerHTML = Object.entries(r).map(([k, v]) =>
      `<div class="hash-row" data-hash="${v}" title="Нажмите, чтобы скопировать"><b>${k.toUpperCase()}</b><span>${v}</span></div>`
    ).join("");
  } catch (err) { toast(err.message, true); }
}
$("#hashIn").addEventListener("input", debounce(runHash));
$("#hashList").addEventListener("click", (e) => { const r = e.target.closest(".hash-row"); if (r) copyText(r.dataset.hash); });

let genReady = false;
onActivate.gen = () => { if (!genReady) { genReady = true; runPw(); runUuid(); runHash(); } };

/* ======================================================================
   Samples
   ====================================================================== */
function b64url(obj) {
  const bytes = new TextEncoder().encode(JSON.stringify(obj));
  return btoa(String.fromCharCode(...bytes)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}
const SAMPLES = {
  json() {
    jsonIn.value = '{"project":"Dev Toolkit","version":"0.1.0","modules":["utils","snippets","journal","git"],"offline":true,"author":{"name":"you","coffee_per_day":3.5},"license":null}';
    runJson();
  },
  jwt() {
    const now = Math.floor(Date.now() / 1000);
    jwtIn.value = [b64url({ alg: "HS256", typ: "JWT" }), b64url({ sub: "1234567890", name: "Иван Петров", role: "admin", iat: now - 3600, exp: now + 7200 }), "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"].join(".");
    runJwt();
  },
  regex() {
    reIn.value = "(?P<user>[\\w.+-]+)@(?P<domain>[\\w-]+\\.[\\w.]+)";
    reText.value = "Пишите: ivan.petrov@example.com или support@devtool.io\nНевалидный: hello@world\nЕщё один: anna+test@mail.co.uk";
    reHl.innerHTML = esc(reText.value);
    runRe();
  },
};

/* ======================================================================
   Boot
   ====================================================================== */
(async function boot() {
  const pill = $("#status");
  try {
    const r = await (await fetch("/api/health")).json();
    pill.classList.add("ok");
    pill.lastElementChild.textContent = "работает · v" + r.version;
  } catch {
    pill.classList.add("err");
    pill.lastElementChild.textContent = "нет связи";
  }
})();
runRe();
// Modules (snippets.js, journal.js) register their hooks first; route once everything is loaded.
document.addEventListener("DOMContentLoaded", route);
