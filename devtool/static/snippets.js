"use strict";
/* global $, $$, esc, debounce, toast, copyText, store, svg, onView, ApiError */

/* ======================================================================
   Lightweight syntax highlighter (no dependencies)
   ====================================================================== */
const KW = {
  shell: "if then else elif fi for do done while until case esac function return export local in sudo echo cd source alias exit set unset readonly",
  python: "def class return if elif else for while in import from as with try except finally raise lambda yield None True False and or not is pass break continue async await global nonlocal self print",
  js: "const let var function return if else for while do of in new class extends import from export default async await try catch finally throw typeof instanceof null undefined true false this interface type enum implements switch case break continue yield delete void",
  sql: "select from where group by order having join left right inner outer full cross on as insert into values update set delete create table index view drop alter add column primary key foreign references and or not null is in like between limit offset desc asc distinct count sum avg min max case when then else end union all exists with returning default",
  docker: "from run cmd copy add workdir env expose entrypoint arg user volume label healthcheck shell onbuild stopsignal as",
  c: "func fn let mut pub struct impl trait enum match package import return if else for while loop break continue class public private protected static void int string bool var new const type interface go defer chan map range nil true false null self use mod crate where async await namespace using include",
  yaml: "true false null yes no on off",
  powershell: "function param if else elseif foreach for while do return try catch finally throw switch begin process end",
};
const LANG_FAMILY = {
  bash: ["shell", "#"], python: ["python", "#"], javascript: ["js", "//"], typescript: ["js", "//"],
  sql: ["sql", "--"], docker: ["docker", "#"], yaml: ["yaml", "#"], go: ["c", "//"], rust: ["c", "//"],
  java: ["c", "//"], csharp: ["c", "//"], cpp: ["c", "//"], css: [null, "/*"], powershell: ["powershell", "#"],
  json: [null, null], html: [null, "<!--"], markdown: [null, null], text: [null, null],
};
const LANG_COLOR = {
  bash: "#34d399", python: "#fbbf24", javascript: "#facc15", typescript: "#60a5fa", sql: "#22d3ee",
  docker: "#38bdf8", yaml: "#f472b6", go: "#67e8f9", rust: "#fb923c", java: "#f87171", csharp: "#a78bfa",
  cpp: "#818cf8", html: "#fb7185", css: "#c084fc", json: "#a3e635", markdown: "#94a3b8", powershell: "#93c5fd", text: "#94a3b8",
};
const LANG_LABEL = { javascript: "JavaScript", typescript: "TypeScript", csharp: "C#", cpp: "C++", sql: "SQL", json: "JSON", yaml: "YAML", html: "HTML", css: "CSS" };
const langLabel = (l) => LANG_LABEL[l] || l.charAt(0).toUpperCase() + l.slice(1);

const kwSets = Object.fromEntries(Object.entries(KW).map(([k, v]) => [k, new Set(v.split(" "))]));

function tokenize(code, lang) {
  const [family, comment] = LANG_FAMILY[lang] || [null, null];
  if (lang === "text" || lang === "markdown") return [{ t: code }];
  const parts = [];
  if (comment === "#") parts.push("#[^\\n]*");
  if (comment === "//") parts.push("\\/\\/[^\\n]*", "\\/\\*[\\s\\S]*?\\*\\/");
  if (comment === "--") parts.push("--[^\\n]*", "\\/\\*[\\s\\S]*?\\*\\/");
  if (comment === "/*") parts.push("\\/\\*[\\s\\S]*?\\*\\/");
  if (comment === "<!--") parts.push("<!--[\\s\\S]*?-->");
  const commentCount = parts.length;
  parts.push(
    '"(?:\\\\.|[^"\\\\])*"', "'(?:\\\\.|[^'\\\\])*'", "`(?:\\\\.|[^`\\\\])*`",   // strings
    "\\$\\{?[A-Za-z_][\\w]*\\}?",                                             // $vars
    "(?<![\\w-])--?[A-Za-z][\\w-]*",                                           // --flags
    "\\b\\d+(?:\\.\\d+)?\\b",                                                  // numbers
    "[A-Za-z_][\\w]*",                                                         // words
  );
  const re = new RegExp(parts.map((p) => `(${p})`).join("|"), "g");
  const kws = family ? kwSets[family] : null;
  const ci = family === "sql" || family === "docker" || family === "powershell";
  const out = [];
  let last = 0, m;
  while ((m = re.exec(code))) {
    if (m.index > last) out.push({ t: code.slice(last, m.index) });
    const g = m.slice(1).findIndex((x) => x !== undefined);
    const text = m[0];
    let cls = null;
    if (g < commentCount) cls = "c-com";
    else {
      const k = g - commentCount;
      if (k <= 2) cls = "c-str";
      else if (k === 3) cls = lang === "bash" || lang === "powershell" || lang === "docker" ? "c-var" : null;
      else if (k === 4) cls = lang === "bash" || lang === "powershell" || lang === "docker" ? "c-flag" : null;
      else if (k === 5) cls = "c-num";
      else if (kws && kws.has(ci ? text.toLowerCase() : text)) cls = "c-kw";
      else if (/^[A-Z][A-Z0-9_]{2,}$/.test(text)) cls = "c-const";
      else if (code[re.lastIndex] === "(") cls = "c-fn";
      if (cls === null && (k === 3 || k === 4)) {
        // not a shell-ish language: let the leading char through and re-scan the rest
        out.push({ t: text[0] });
        re.lastIndex = m.index + 1;
        last = re.lastIndex;
        continue;
      }
    }
    out.push({ t: text, c: cls });
    last = re.lastIndex;
  }
  if (last < code.length) out.push({ t: code.slice(last) });
  return out;
}

function highlightCode(code, lang, { lineNumbers = true } = {}) {
  const lines = [[]];
  for (const tok of tokenize(code, lang)) {
    tok.t.split("\n").forEach((piece, i) => {
      if (i > 0) lines.push([]);
      if (piece) lines[lines.length - 1].push(tok.c ? `<span class="${tok.c}">${esc(piece)}</span>` : esc(piece));
    });
  }
  if (!lineNumbers) return lines.map((l) => l.join("")).join("\n");
  return lines.map((l, i) => `<span class="ln" data-n="${i + 1}"></span>${l.join("") || " "}`).join("\n");
}

/* ======================================================================
   State & API
   ====================================================================== */
const S = {
  items: [], meta: null, selected: null, mode: "view", // view | edit | new
  q: "", lang: "", sort: store.get("snip-sort", "recent"), fav: false, tags: new Set(), loaded: false,
};

async function sapi(method, url, body) {
  const res = await fetch(url, {
    method,
    headers: body !== undefined ? { "Content-Type": "application/json" } : {},
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (res.status === 204) return null;
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError(data.error || { message: data.detail || "Ошибка сервера" });
  return data;
}

async function loadMeta() {
  S.meta = await sapi("GET", "/api/snippets/meta");
  const { stats, tags, languages } = S.meta;
  $("#snipCount").textContent = stats.total || "";
  $("#snipStats").innerHTML = `
    <span class="stat-chip"><b>${stats.total}</b> ${plural(stats.total, "сниппет", "сниппета", "сниппетов")}</span>
    <span class="stat-chip"><b>${stats.favorites}</b> в избранном</span>
    <span class="stat-chip"><b>${tags.length}</b> ${plural(tags.length, "тег", "тега", "тегов")}</span>`;
  const used = new Set(stats.languages.map((l) => l.language));
  const sel = $("#snipLang");
  sel.innerHTML = '<option value="">Все языки</option>' + languages.filter((l) => used.has(l) || l === S.lang)
    .map((l) => `<option value="${l}">${langLabel(l)}</option>`).join("");
  sel.value = S.lang;
  for (const t of [...S.tags]) if (!tags.some((x) => x.tag === t)) S.tags.delete(t);
  $("#snipTags").innerHTML = tags.map((t) =>
    `<button class="tag-chip${S.tags.has(t.tag) ? " on" : ""}" data-tag="${esc(t.tag)}">#${esc(t.tag)}<i>${t.count}</i></button>`
  ).join("");
}

async function loadList() {
  const p = new URLSearchParams({ q: S.q, sort: S.sort });
  if (S.lang) p.set("lang", S.lang);
  if (S.fav) p.set("favorite", "true");
  S.tags.forEach((t) => p.append("tag", t));
  const r = await sapi("GET", "/api/snippets?" + p);
  S.items = r.items;
  renderList();
}

async function refresh() {
  try {
    await Promise.all([loadMeta(), loadList()]);
    if (!S.items.length && S.mode === "view") { S.selected = null; renderMain(); }
  } catch (err) { toast(err.message, true); }
}

function plural(n, one, few, many) {
  const a = Math.abs(n) % 100, b = a % 10;
  if (a > 10 && a < 20) return many;
  if (b > 1 && b < 5) return few;
  if (b === 1) return one;
  return many;
}

function relTime(iso) {
  if (!iso) return "никогда";
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 60) return "только что";
  const units = [[31536000, "г."], [2592000, "мес."], [86400, "дн."], [3600, "ч."], [60, "мин."]];
  for (const [s, u] of units) if (diff >= s) return `${Math.floor(diff / s)} ${u} назад`;
  return "только что";
}

/* ======================================================================
   Rendering
   ====================================================================== */
const langDot = (l) => `<span class="lang-badge" style="--lc:${LANG_COLOR[l] || "#94a3b8"}"><i></i>${langLabel(l)}</span>`;

function renderList() {
  const list = $("#snipList");
  const hasFilters = S.q || S.lang || S.fav || S.tags.size;
  if (!S.items.length) {
    list.innerHTML = hasFilters
      ? `<div class="list-empty">Ничего не найдено<br><button class="mini" id="snipReset">Сбросить фильтры</button></div>`
      : "";
    if (!hasFilters && S.mode === "view") renderMain();
    return;
  }
  list.innerHTML = S.items.map((s) => {
    const first = s.content.split("\n").find((l) => l.trim()) || "";
    return `<div class="snip-item${S.selected?.id === s.id ? " sel" : ""}" data-id="${s.id}" tabindex="-1">
      <div class="si-top">
        ${s.favorite ? '<span class="si-star">★</span>' : ""}
        <b>${esc(s.title)}</b>
        <button class="si-copy" data-copy-snip="${s.id}" title="Копировать">${svg("copy")}</button>
      </div>
      <code class="si-preview">${highlightCode(first.slice(0, 120), s.language, { lineNumbers: false })}</code>
      <div class="si-meta">${langDot(s.language)}${s.tags.slice(0, 4).map((t) => `<span class="si-tag">#${esc(t)}</span>`).join("")}${s.use_count ? `<span class="si-uses" title="Сколько раз скопирован">${s.use_count}×</span>` : ""}</div>
    </div>`;
  }).join("");
  if (S.mode === "view" && (!S.selected || !S.items.some((x) => x.id === S.selected.id))) {
    select(S.items[0], { replace: true });
  }
}

function renderMain() {
  const main = $("#snipMain");
  if (S.mode === "edit" || S.mode === "new") return renderEditor();
  const s = S.selected;
  if (!s) {
    const empty = S.meta && S.meta.stats.total === 0;
    main.innerHTML = empty ? `
      <div class="empty-state">
        <div class="es-icon">${svg("snippet")}</div>
        <h2>Здесь будут ваши сниппеты</h2>
        <p class="muted">Сохраняйте команды, которые постоянно гуглите, и находите их за секунду: здесь, через <kbd>Ctrl</kbd><kbd>K</kbd> или в терминале через <code>devtool snip find</code>.</p>
        <div class="es-actions">
          <button class="btn primary" data-act="new">${svg("plus")}Создать первый</button>
          <button class="btn" data-act="examples">${svg("sparkle")}Добавить примеры</button>
        </div>
      </div>` : `<div class="empty-state small"><p class="muted">Выберите сниппет слева</p></div>`;
    return;
  }
  const lines = s.content.split("\n").length;
  main.innerHTML = `
    <article class="snip-detail">
      <header class="sd-head">
        <div class="sd-title">
          <h2>${esc(s.title)}</h2>
          <div class="sd-meta">
            ${langDot(s.language)}
            ${s.tags.map((t) => `<button class="tag-chip small" data-tag="${esc(t)}">#${esc(t)}</button>`).join("")}
          </div>
        </div>
        <div class="sd-actions">
          <button class="icon-btn fav${s.favorite ? " on" : ""}" data-act="fav" title="Избранное (F)">${svg("star")}</button>
          <button class="icon-btn" data-act="edit" title="Редактировать (E)">${svg("edit")}</button>
          <button class="icon-btn danger" data-act="delete" title="Удалить">${svg("trash")}</button>
        </div>
      </header>
      ${s.description ? `<p class="sd-desc">${esc(s.description)}</p>` : ""}
      <div class="code-block">
        <div class="cb-head">
          <span class="cb-dots"><i></i><i></i><i></i></span>
          <span class="cb-info">${lines} ${plural(lines, "строка", "строки", "строк")} · ${s.content.length} симв.</span>
          <button class="btn primary sm" data-act="copy">${svg("copy")}Копировать<kbd>Enter</kbd></button>
        </div>
        <pre class="code numbered">${highlightCode(s.content, s.language)}</pre>
      </div>
      <footer class="sd-foot">
        <span title="${esc(s.created_at)}">Создан ${relTime(s.created_at)}</span>
        <span title="${esc(s.updated_at)}">Изменён ${relTime(s.updated_at)}</span>
        <span>Скопирован ${s.use_count} ${plural(s.use_count, "раз", "раза", "раз")}${s.last_used_at ? `, последний ${relTime(s.last_used_at)}` : ""}</span>
        <span class="sd-cli" title="Команда для терминала"><code>devtool snip copy ${s.id}</code></span>
      </footer>
    </article>`;
}

function renderEditor() {
  const isNew = S.mode === "new";
  const s = isNew ? { title: "", content: "", language: store.get("snip-last-lang", "bash"), description: "", tags: [], favorite: false } : S.selected;
  const langs = (S.meta?.languages || ["text"]).map((l) => `<option value="${l}"${l === s.language ? " selected" : ""}>${langLabel(l)}</option>`).join("");
  const knownTags = (S.meta?.tags || []).map((t) => `<option value="${esc(t.tag)}">`).join("");
  $("#snipMain").innerHTML = `
    <form class="snip-editor" id="snipForm" autocomplete="off">
      <div class="se-head">
        <h2>${isNew ? "Новый сниппет" : "Редактирование"}</h2>
        <label class="switch"><input type="checkbox" name="favorite"${s.favorite ? " checked" : ""}><span></span>★ Избранное</label>
      </div>
      <label class="field"><span>Название</span>
        <input class="input" name="title" value="${esc(s.title)}" placeholder="Например: Удалить все остановленные контейнеры" required maxlength="200">
      </label>
      <div class="field-row">
        <label class="field"><span>Язык</span><select class="input" name="language">${langs}</select></label>
        <label class="field grow"><span>Теги <em>через запятую или пробел</em></span>
          <input class="input" name="tags" list="snipTagList" value="${esc(s.tags.join(", "))}" placeholder="docker, cleanup">
          <datalist id="snipTagList">${knownTags}</datalist>
        </label>
      </div>
      <label class="field"><span>Описание <em>необязательно</em></span>
        <input class="input" name="description" value="${esc(s.description)}" placeholder="Когда и зачем это нужно">
      </label>
      <label class="field"><span>Код</span>
        <div class="se-code">
          <pre class="code numbered se-hl" aria-hidden="true"></pre>
          <textarea name="content" spellcheck="false" placeholder="Вставьте команду или код…" required>${esc(s.content)}</textarea>
        </div>
      </label>
      <div class="se-actions">
        <span class="muted small"><kbd>Ctrl</kbd>+<kbd>Enter</kbd> сохранить · <kbd>Esc</kbd> отмена</span>
        <div class="spacer"></div>
        <button type="button" class="btn ghost" data-act="cancel">Отмена</button>
        <button type="submit" class="btn primary">${isNew ? "Создать" : "Сохранить"}</button>
      </div>
    </form>`;
  const form = $("#snipForm");
  const ta = form.content, hl = $(".se-hl", form);
  const sync = () => { hl.innerHTML = highlightCode(ta.value, form.language.value) + "\n"; };
  sync();
  ta.addEventListener("input", sync);
  form.language.addEventListener("change", sync);
  ta.addEventListener("scroll", () => { hl.scrollTop = ta.scrollTop; hl.scrollLeft = ta.scrollLeft; });
  ta.addEventListener("keydown", (e) => {
    if (e.key === "Tab" && !e.shiftKey) {
      e.preventDefault();
      const { selectionStart: a, selectionEnd: b } = ta;
      ta.setRangeText("  ", a, b, "end");
      sync();
    }
  });
  form.addEventListener("submit", (e) => { e.preventDefault(); saveForm(); });
  form.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") { e.preventDefault(); saveForm(); }
    if (e.key === "Escape") { e.preventDefault(); cancelEdit(); }
  });
  (isNew ? form.title : ta).focus();
}

/* ======================================================================
   Actions
   ====================================================================== */
function select(s, { replace = false } = {}) {
  S.selected = s || null;
  S.mode = "view";
  $$(".snip-item").forEach((el) => el.classList.toggle("sel", +el.dataset.id === s?.id));
  $(`.snip-item[data-id="${s?.id}"]`)?.scrollIntoView({ block: "nearest" });
  const hash = s ? `#snippets/${s.id}` : "#snippets";
  if (location.hash !== hash) history[replace ? "replaceState" : "pushState"](null, "", hash);
  renderMain();
}

async function copySnippet(s) {
  await copyText(s.content);
  try {
    const upd = await sapi("POST", `/api/snippets/${s.id}/use`);
    const i = S.items.findIndex((x) => x.id === s.id);
    if (i >= 0) S.items[i] = upd;
    if (S.selected?.id === s.id) { S.selected = upd; if (S.mode === "view") renderMain(); }
    if (S.loaded) renderList();
  } catch { /* counter is best-effort */ }
}

async function saveForm() {
  const f = $("#snipForm");
  const body = {
    title: f.title.value, content: f.content.value, language: f.language.value,
    tags: f.tags.value, description: f.description.value, favorite: f.favorite.checked,
  };
  try {
    const saved = S.mode === "new"
      ? await sapi("POST", "/api/snippets", body)
      : await sapi("PATCH", `/api/snippets/${S.selected.id}`, body);
    store.set("snip-last-lang", body.language);
    toast(S.mode === "new" ? "Сниппет создан" : "Сохранено");
    S.mode = "view";
    S.selected = saved;
    await refresh();
    select(saved, { replace: true });
  } catch (err) { toast(err.message, true); }
}

function cancelEdit() {
  S.mode = "view";
  renderMain();
}

async function toggleFav() {
  const s = S.selected;
  try {
    S.selected = await sapi("PATCH", `/api/snippets/${s.id}`, { favorite: !s.favorite });
    toast(S.selected.favorite ? "Добавлено в избранное" : "Убрано из избранного");
    await refresh();
    renderMain();
  } catch (err) { toast(err.message, true); }
}

function confirmDialog(title, text) {
  return new Promise((resolve) => {
    const dlg = $("#confirm");
    $("#confirmTitle").textContent = title;
    $("#confirmText").textContent = text;
    dlg.hidden = false;
    $("#confirmYes").focus();
    const done = (v) => {
      dlg.hidden = true;
      dlg.removeEventListener("click", onClick);
      document.removeEventListener("keydown", onKey, true);
      resolve(v);
    };
    const onClick = (e) => {
      if (e.target.id === "confirmYes") done(true);
      else if (e.target.id === "confirmNo" || e.target === dlg) done(false);
    };
    const onKey = (e) => { if (e.key === "Escape") { e.stopPropagation(); done(false); } };
    dlg.addEventListener("click", onClick);
    document.addEventListener("keydown", onKey, true);
  });
}

async function deleteSelected() {
  const s = S.selected;
  if (!(await confirmDialog("Удалить сниппет?", `«${s.title}» будет удалён без возможности восстановления.`))) return;
  try {
    await sapi("DELETE", `/api/snippets/${s.id}`);
    toast("Удалено");
    const idx = S.items.findIndex((x) => x.id === s.id);
    S.selected = S.items[idx + 1] || S.items[idx - 1] || null;
    await refresh();
    renderMain();
  } catch (err) { toast(err.message, true); }
}

function startNew() {
  S.mode = "new";
  renderMain();
}

async function addExamples() {
  try {
    const r = await sapi("POST", "/api/snippets/examples");
    toast(`Добавлено примеров: ${r.added}`);
    S.selected = null;
    await refresh();
  } catch (err) { toast(err.message, true); }
}

/* ======================================================================
   Events
   ====================================================================== */
$("#snipMain").addEventListener("click", (e) => {
  const act = e.target.closest("[data-act]")?.dataset.act;
  if (act === "copy") copySnippet(S.selected);
  else if (act === "edit") { S.mode = "edit"; renderMain(); }
  else if (act === "delete") deleteSelected();
  else if (act === "fav") toggleFav();
  else if (act === "cancel") cancelEdit();
  else if (act === "new") startNew();
  else if (act === "examples") addExamples();
});

$("#snipList").addEventListener("click", (e) => {
  const cp = e.target.closest("[data-copy-snip]");
  if (cp) {
    e.stopPropagation();
    const s = S.items.find((x) => x.id === +cp.dataset.copySnip);
    if (s) copySnippet(s);
    return;
  }
  if (e.target.id === "snipReset") {
    S.q = ""; S.lang = ""; S.fav = false; S.tags.clear();
    $("#snipSearch").value = ""; $("#snipFavOnly").classList.remove("on");
    refresh();
    return;
  }
  const item = e.target.closest(".snip-item");
  if (item) {
    if (S.mode !== "view") S.mode = "view";
    select(S.items.find((x) => x.id === +item.dataset.id));
  }
});

document.addEventListener("click", (e) => {
  const chip = e.target.closest("#view-snippets [data-tag]");
  if (!chip) return;
  const t = chip.dataset.tag;
  S.tags.has(t) ? S.tags.delete(t) : S.tags.add(t);
  refresh();
});

const searchInput = $("#snipSearch");
searchInput.addEventListener("input", debounce(() => { S.q = searchInput.value; loadList().catch((e) => toast(e.message, true)); }, 120));
searchInput.addEventListener("keydown", (e) => {
  if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); moveSel(e.key === "ArrowDown" ? 1 : -1); }
  else if (e.key === "Enter" && S.selected) { e.preventDefault(); copySnippet(S.selected); }
  else if (e.key === "Escape") { searchInput.value = ""; S.q = ""; loadList(); searchInput.blur(); }
});
$("#snipLang").addEventListener("change", (e) => { S.lang = e.target.value; loadList(); });
$("#snipSort").value = S.sort;
$("#snipSort").addEventListener("change", (e) => { S.sort = e.target.value; store.set("snip-sort", S.sort); loadList(); });
$("#snipFavOnly").addEventListener("click", (e) => { S.fav = !S.fav; e.currentTarget.classList.toggle("on", S.fav); loadList(); });
$("#snipNew").addEventListener("click", startNew);

$("#snipImport").addEventListener("change", async (e) => {
  const file = e.target.files[0];
  e.target.value = "";
  if (!file) return;
  try {
    const data = JSON.parse(await file.text());
    const r = await sapi("POST", "/api/snippets/import", data);
    toast(`Импортировано: ${r.added}, пропущено дубликатов: ${r.skipped}`);
    await refresh();
  } catch (err) {
    toast(err instanceof SyntaxError ? "Файл не является корректным JSON" : err.message, true);
  }
});

function moveSel(delta) {
  if (!S.items.length) return;
  const i = S.items.findIndex((x) => x.id === S.selected?.id);
  const next = S.items[Math.max(0, Math.min(S.items.length - 1, i + delta))];
  if (next) select(next, { replace: true });
}

document.addEventListener("keydown", (e) => {
  if (currentView !== "snippets" || !$("#palette").hidden || !$("#confirm").hidden) return;
  const typing = e.target.closest("input, textarea, select, [contenteditable]");
  if (typing || e.ctrlKey || e.metaKey || e.altKey) return;
  if (e.key === "/") { e.preventDefault(); searchInput.focus(); searchInput.select(); }
  else if (S.mode !== "view") return;
  else if (e.key === "n" || e.key === "т") { e.preventDefault(); startNew(); }
  else if (!S.selected) return;
  else if (e.key === "j" || e.key === "ArrowDown") { e.preventDefault(); moveSel(1); }
  else if (e.key === "k" || e.key === "ArrowUp") { e.preventDefault(); moveSel(-1); }
  else if (e.key === "Enter" || e.key === "c") { e.preventDefault(); copySnippet(S.selected); }
  else if (e.key === "e" || e.key === "у") { e.preventDefault(); S.mode = "edit"; renderMain(); }
  else if (e.key === "f" || e.key === "а") { e.preventDefault(); toggleFav(); }
  else if (e.key === "Delete") { e.preventDefault(); deleteSelected(); }
});

/* ======================================================================
   Hooks into app.js
   ====================================================================== */
onView.snippets = async () => {
  if (!S.loaded) { S.loaded = true; await refresh(); }
  else renderMain();
};
onView.snippetsRoute = async (id) => {
  if (!S.loaded) { S.loaded = true; await refresh(); }
  if (!id) return;
  if (S.selected?.id === +id && S.mode !== "view") return;
  let s = S.items.find((x) => x.id === +id);
  if (!s) { try { s = await sapi("GET", `/api/snippets/${id}`); } catch { return; } }
  select(s, { replace: true });
};
onView.newSnippet = async () => { if (!S.loaded) { S.loaded = true; await refresh(); } startNew(); };
onView.copySnippet = copySnippet;

// sidebar counter even before the module is opened
sapi("GET", "/api/snippets/meta").then((m) => { $("#snipCount").textContent = m.stats.total || ""; }).catch(() => {});
route();
