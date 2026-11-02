"use strict";
/* global $, $$, esc, debounce, toast, copyText, store, svg, onView, sapi, confirmDialog, plural, segValue, currentView */

/* ======================================================================
   Git dashboard
   ====================================================================== */
const G = { data: null, loaded: false, loading: false, filter: "all", sort: store.get("g-sort", "status"), q: "", open: null };

const HEALTH = {
  conflict: { label: "Конфликт", cls: "h-red" },
  dirty: { label: "Есть изменения", cls: "h-yellow" },
  unpushed: { label: "Не отправлено", cls: "h-violet" },
  behind: { label: "Отстаёт", cls: "h-blue" },
  local: { label: "Без remote", cls: "h-gray" },
  clean: { label: "Чисто", cls: "h-green" },
  error: { label: "Ошибка", cls: "h-red" },
};
const ATTENTION = new Set(["conflict", "dirty", "unpushed", "behind", "error"]);

function ago(iso) {
  if (!iso) return null;
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return "только что";
  if (s < 3600) return `${Math.floor(s / 60)} мин назад`;
  if (s < 86400) return `${Math.floor(s / 3600)} ч назад`;
  const d = Math.floor(s / 86400);
  if (d < 30) return `${d} ${plural(d, "день", "дня", "дней")} назад`;
  if (d < 365) return `${Math.floor(d / 30)} мес назад`;
  return `${Math.floor(d / 365)} г назад`;
}

/* ---------------------------------------------------------------- data */
async function loadRepos() {
  if (G.loading) return;
  G.loading = true;
  $("#gRefresh").classList.add("spinning");
  if (!G.data) $("#gGrid").innerHTML = skeletons();
  try {
    G.data = await sapi("GET", "/api/git/repos");
    renderSummary();
    renderGrid();
    updateNavCount();
  } catch (err) {
    toast(err.message, true);
  } finally {
    G.loading = false;
    $("#gRefresh").classList.remove("spinning");
  }
}

function updateNavCount() {
  const n = G.data ? G.data.repos.filter((r) => ATTENTION.has(r.health)).length : 0;
  $("#gNavCount").textContent = n || "";
}

/* ----------------------------------------------------------- rendering */
const skeletons = () => Array.from({ length: 6 }, () => '<div class="repo-card skeleton"><i></i><i></i><i></i></div>').join("");

function renderSummary() {
  const s = G.data.summary;
  const chip = (n, label, cls = "") => `<span class="stat-chip ${cls}"><b>${n}</b> ${label}</span>`;
  $("#gSummary").innerHTML = [
    chip(s.total, plural(s.total, "репозиторий", "репозитория", "репозиториев")),
    s.dirty ? chip(s.dirty, "с изменениями", "c-yellow") : "",
    s.unpushed ? chip(s.unpushed, "не отправлено", "c-violet") : "",
    s.behind ? chip(s.behind, "отстают", "c-blue") : "",
    s.merged_branches ? chip(s.merged_branches, plural(s.merged_branches, "слитая ветка", "слитые ветки", "слитых веток")) : "",
    !s.dirty && !s.unpushed && !s.behind && s.total ? chip("✓", "всё чисто", "c-green") : "",
  ].join("");
}

function sparkline(values) {
  const max = Math.max(1, ...values);
  const w = 6, gap = 3, h = 26;
  const bars = values.map((v, i) => {
    const bh = v ? Math.max(3, Math.round((v / max) * h)) : 2;
    return `<rect x="${i * (w + gap)}" y="${h - bh}" width="${w}" height="${bh}" rx="1.5" class="${v ? "on" : ""}"><title>${v} ${plural(v, "коммит", "коммита", "коммитов")}</title></rect>`;
  }).join("");
  return `<svg class="spark" viewBox="0 0 ${values.length * (w + gap) - gap} ${h}" preserveAspectRatio="none">${bars}</svg>`;
}

function changePills(r) {
  const pills = [];
  if (r.conflicts) pills.push(`<span class="pill p-red" title="Конфликтов">✗ ${r.conflicts}</span>`);
  if (r.staged) pills.push(`<span class="pill p-green" title="В индексе (staged)">+${r.staged}</span>`);
  if (r.modified) pills.push(`<span class="pill p-yellow" title="Изменено">~${r.modified}</span>`);
  if (r.untracked) pills.push(`<span class="pill p-gray" title="Новые файлы (untracked)">?${r.untracked}</span>`);
  if (r.stash) pills.push(`<span class="pill p-blue" title="Записей в stash">stash ${r.stash}</span>`);
  if (r.merged_branches) pills.push(`<span class="pill p-violet" title="Локальных веток, уже слитых в основную">⎇ ${r.merged_branches} слито</span>`);
  if (r.stale_branches) pills.push(`<span class="pill p-gray" title="Веток без коммитов больше 30 дней">${r.stale_branches} устар.</span>`);
  return pills.join("") || '<span class="pill p-green">рабочая копия чистая</span>';
}

function repoCard(r) {
  const h = HEALTH[r.health] || HEALTH.error;
  if (r.health === "error") {
    return `<article class="repo-card ${h.cls}" data-path="${esc(r.path)}"><div class="rc-head"><b>${esc(r.name)}</b><span class="health ${h.cls}">${h.label}</span></div><div class="muted small">${esc(r.error)}</div></article>`;
  }
  const sync = (r.ahead ? `<span class="sync up" title="Не отправлено коммитов">↑${r.ahead}</span>` : "")
    + (r.behind ? `<span class="sync down" title="Отстаёт от upstream">↓${r.behind}</span>` : "");
  const branch = r.branch || "(detached HEAD)";
  const lc = r.last_commit;
  const fetched = r.last_fetch ? `fetch ${ago(r.last_fetch)}` : (r.remote ? "fetch ни разу" : "");
  const total = r.activity.reduce((a, b) => a + b, 0);
  return `<article class="repo-card ${h.cls}" data-path="${esc(r.path)}" tabindex="0">
    <div class="rc-head">
      <b title="${esc(r.name)}">${esc(r.name)}</b>
      <span class="health ${h.cls}"><i></i>${h.label}</span>
    </div>
    <div class="rc-branch"><span class="branch-chip">⎇ ${esc(branch)}</span>${sync}${r.upstream ? "" : r.remote && r.branch ? '<span class="sync none" title="У ветки нет upstream">нет upstream</span>' : ""}</div>
    <div class="rc-pills">${changePills(r)}</div>
    <div class="rc-commit">${lc ? `<span class="rc-subject" title="${esc(lc.subject)}">${esc(lc.subject)}</span><span class="rc-when">${esc(lc.author)} · ${ago(lc.time)}</span>` : '<span class="muted">Коммитов пока нет</span>'}</div>
    <div class="rc-activity" title="Коммитов за 14 дней: ${total}">${sparkline(r.activity)}<span>${total}<small> за 14 дн.</small></span></div>
    <footer class="rc-foot">
      <code class="rc-path" title="${esc(r.path)}">${esc(r.path)}</code>
      <span class="rc-fetch">${fetched}</span>
      <div class="rc-actions">
        <button class="mini-icon" data-act="cd" title="Скопировать cd">${svg("terminal")}</button>
        ${r.web_url ? `<a class="mini-icon" href="${esc(r.web_url)}" target="_blank" rel="noopener" title="Открыть ${esc(r.web_url)}">${svg("link")}</a>` : ""}
        ${r.remote ? `<button class="mini-icon" data-act="fetch" title="git fetch">${svg("download")}</button>` : ""}
      </div>
    </footer>
  </article>`;
}

function visibleRepos() {
  let list = [...G.data.repos];
  if (G.filter === "attention") list = list.filter((r) => ATTENTION.has(r.health));
  else if (G.filter === "clean") list = list.filter((r) => !ATTENTION.has(r.health));
  if (G.q) {
    const q = G.q.toLowerCase();
    list = list.filter((r) => r.name.toLowerCase().includes(q) || (r.branch || "").toLowerCase().includes(q) || r.path.toLowerCase().includes(q));
  }
  if (G.sort === "name") list.sort((a, b) => a.name.localeCompare(b.name));
  else if (G.sort === "activity") {
    const t = (r) => (r.last_commit ? new Date(r.last_commit.time).getTime() : 0);
    list.sort((a, b) => t(b) - t(a));
  }
  return list;
}

function renderGrid() {
  const grid = $("#gGrid");
  const d = G.data;
  if (!d.git) {
    grid.innerHTML = emptyState("Git не найден", "Установите git и перезапустите Dev Toolkit: дашборд использует его командную строку.", false);
    return;
  }
  if (!d.repos.length) {
    grid.innerHTML = emptyState("Добавьте папку с проектами",
      "Укажите папку, в которой лежат ваши репозитории (например, <code>~/projects</code>). Dev Toolkit найдёт их на глубине до двух уровней.", true);
    return;
  }
  const list = visibleRepos();
  grid.innerHTML = list.length ? list.map(repoCard).join("")
    : `<div class="empty-state small grid-span"><p class="muted">${G.filter === "attention" ? "🎉 Всё чисто: ни одному репозиторию не нужно внимание" : "Ничего не найдено"}</p></div>`;
}

function emptyState(title, text, withForm) {
  return `<div class="empty-state grid-span">
    <div class="es-icon">${svg("git")}</div>
    <h2>${title}</h2>
    <p class="muted">${text}</p>
    ${withForm ? `<form class="roots-add es-form" id="gRootForm">
      <input class="input mono" id="gRootInput" placeholder="~/projects" autocomplete="off">
      <button class="btn primary" type="submit">Добавить</button></form>` : ""}
  </div>`;
}

/* --------------------------------------------------------------- drawer */
const FILE_STATUS = { M: "изменён", A: "добавлен", D: "удалён", R: "переименован", C: "скопирован", U: "конфликт", "?": "новый", T: "тип изменён" };
function fileRow(f) {
  const badge = (c, where) => (c && c !== "." ? `<span class="fs fs-${c === "?" ? "Q" : c}" title="${FILE_STATUS[c] || c} (${where})">${c}</span>` : `<span class="fs fs-none"></span>`);
  const slash = f.path.lastIndexOf("/");
  const dir = slash >= 0 ? f.path.slice(0, slash + 1) : "";
  const name = slash >= 0 ? f.path.slice(slash + 1) : f.path;
  return `<div class="file-row">${f.x === "?" ? badge("?", "untracked") + '<span class="fs fs-none"></span>' : badge(f.x, "индекс") + badge(f.y, "рабочая копия")}
    <span class="file-path"><span class="muted">${esc(dir)}</span>${esc(name)}</span></div>`;
}

function branchRow(b) {
  const marks = [];
  if (b.current) marks.push('<span class="pill p-green">текущая</span>');
  if (b.default) marks.push('<span class="pill p-blue">основная</span>');
  if (b.merged) marks.push('<span class="pill p-violet">слита</span>');
  if (b.stale) marks.push(`<span class="pill p-yellow">${b.age_days} дн. без коммитов</span>`);
  if (b.gone) marks.push('<span class="pill p-red">upstream удалён</span>');
  if (b.ahead) marks.push(`<span class="sync up">↑${b.ahead}</span>`);
  if (b.behind) marks.push(`<span class="sync down">↓${b.behind}</span>`);
  const deletable = b.merged && !b.current && !b.default;
  return `<label class="branch-row${deletable ? " deletable" : ""}">
    ${deletable ? `<input type="checkbox" value="${esc(b.name)}" checked>` : '<span class="cb-space"></span>'}
    <span class="br-main"><b>${esc(b.name)}</b><span class="br-sub" title="${esc(b.subject)}">${esc(b.subject)}</span></span>
    <span class="br-marks">${marks.join("")}</span>
    <span class="br-age">${ago(b.last_commit) || ""}</span>
  </label>`;
}

async function openRepo(path, { push = true } = {}) {
  G.open = path;
  const dr = $("#gDrawer");
  const body = $("#gDrawerBody");
  dr.hidden = false;
  requestAnimationFrame(() => dr.classList.add("open"));
  body.innerHTML = '<div class="drawer-loading"><span class="spinner"></span> Читаю репозиторий…</div>';
  if (push) history.replaceState(null, "", "#git/" + encodeURIComponent(path));
  try {
    const r = await sapi("GET", "/api/git/repo?path=" + encodeURIComponent(path));
    if (G.open !== path) return;
    renderDrawer(r);
  } catch (err) {
    body.innerHTML = `<div class="drawer-loading">✗ ${esc(err.message)}</div>`;
  }
}

function renderDrawer(r) {
  const h = HEALTH[r.health] || HEALTH.error;
  const deletable = r.branches.filter((b) => b.merged && !b.current && !b.default);
  const canPull = r.behind && !r.changes && r.upstream;
  $("#gDrawerBody").innerHTML = `
    <header class="dr-head">
      <div class="dr-title">
        <h2>${esc(r.name)}</h2>
        <span class="health ${h.cls}"><i></i>${h.label}</span>
      </div>
      <button class="icon-btn" data-act="close" title="Закрыть (Esc)">✕</button>
    </header>
    <code class="dr-path">${esc(r.path)}</code>
    <div class="dr-branch">
      <span class="branch-chip big">⎇ ${esc(r.branch || "(detached HEAD)")}</span>
      ${r.upstream ? `<span class="muted small">→ ${esc(r.upstream)}</span>` : ""}
      ${r.ahead ? `<span class="sync up">↑${r.ahead} не отправлено</span>` : ""}
      ${r.behind ? `<span class="sync down">↓${r.behind} отстаёт</span>` : ""}
    </div>
    <div class="dr-actions">
      ${r.remote ? `<button class="btn" data-act="fetch">${svg("download")}Fetch</button>` : ""}
      ${canPull ? `<button class="btn primary" data-act="pull" title="git pull --ff-only">↓ Pull (fast-forward)</button>` : ""}
      <button class="btn ghost" data-act="cd">${svg("terminal")}cd</button>
      ${r.web_url ? `<a class="btn ghost" href="${esc(r.web_url)}" target="_blank" rel="noopener">${svg("link")}Открыть на ${esc(new URL(r.web_url).host)}</a>` : ""}
    </div>

    <section class="dr-section">
      <h3>Изменения <span class="count-badge">${r.changes}</span>
        ${r.stash ? `<span class="pill p-blue">stash ${r.stash}</span>` : ""}</h3>
      ${r.files.length ? `<div class="file-list">${r.files.map(fileRow).join("")}</div>` : '<p class="muted small">Рабочая копия чистая ✓</p>'}
    </section>

    <section class="dr-section">
      <h3>Ветки <span class="count-badge">${r.branches.length}</span>
        ${r.default_branch ? `<span class="muted small">основная: ${esc(r.default_branch)}</span>` : ""}</h3>
      <form id="gBranchForm">
        <div class="branch-list">${r.branches.map(branchRow).join("")}</div>
        ${deletable.length ? `<div class="branch-actions"><span class="muted small">Слитые ветки можно безопасно удалить: используется <code>git branch -d</code></span>
          <button class="btn danger sm" type="submit">${svg("trash")}Удалить выбранные</button></div>` : ""}
      </form>
    </section>

    <section class="dr-section">
      <h3>Последние коммиты</h3>
      <div class="commit-list">${r.commits.map((c) => `
        <div class="commit-row"><code>${esc(c.sha)}</code>
          <span class="cm-main"><span class="cm-subject">${esc(c.subject)}</span>
          ${c.refs ? `<span class="cm-refs">${c.refs.split(", ").map((x) => `<span class="ref">${esc(x.replace("HEAD -> ", "HEAD → "))}</span>`).join("")}</span>` : ""}</span>
          <span class="cm-meta">${esc(c.author)}<br>${ago(c.time)}</span></div>`).join("") || '<p class="muted small">Коммитов пока нет</p>'}
      </div>
    </section>
    <p class="muted small dr-foot">Статус прочитан за ${r.elapsed_ms} мс</p>`;
  $("#gBranchForm").addEventListener("submit", (e) => { e.preventDefault(); deleteBranches(r); });
}

function closeDrawer() {
  const dr = $("#gDrawer");
  if (dr.hidden) return;
  dr.classList.remove("open");
  G.open = null;
  history.replaceState(null, "", "#git");
  setTimeout(() => { if (!G.open) dr.hidden = true; }, 220);
}

/* --------------------------------------------------------------- actions */
async function withBusy(btn, fn) {
  btn?.classList.add("busy");
  btn && (btn.disabled = true);
  try { return await fn(); } finally { btn?.classList.remove("busy"); btn && (btn.disabled = false); }
}

async function fetchOne(path, btn) {
  await withBusy(btn, async () => {
    try {
      await sapi("POST", "/api/git/fetch", { path });
      toast("Fetch выполнен");
      await loadRepos();
      if (G.open === path) openRepo(path, { push: false });
    } catch (err) { toast(err.message, true); }
  });
}

async function fetchAll() {
  const btn = $("#gFetchAll");
  await withBusy(btn, async () => {
    try {
      const r = await sapi("POST", "/api/git/fetch", {});
      toast(r.failed ? `Fetch: успешно ${r.ok}, с ошибками ${r.failed}` : `Fetch выполнен для ${r.ok} ${plural(r.ok, "репозитория", "репозиториев", "репозиториев")}`, r.failed > 0);
      await loadRepos();
    } catch (err) { toast(err.message, true); }
  });
}

async function pull(path, btn) {
  await withBusy(btn, async () => {
    try {
      await sapi("POST", "/api/git/pull", { path });
      toast("Pull выполнен");
      await loadRepos();
      openRepo(path, { push: false });
    } catch (err) { toast(err.message, true); }
  });
}

async function deleteBranches(r) {
  const names = $$("#gBranchForm input[type=checkbox]:checked").map((c) => c.value);
  if (!names.length) return toast("Не выбрано ни одной ветки", true);
  const ok = await confirmDialog(`Удалить ${names.length} ${plural(names.length, "ветку", "ветки", "веток")}?`, names.join(", "));
  if (!ok) return;
  try {
    const res = await sapi("POST", "/api/git/delete-branches", { path: r.path, branches: names });
    if (res.errors.length) toast(`Удалено ${res.deleted.length}, ошибки: ${res.errors.map((e) => e.name + ": " + e.error).join("; ")}`, true);
    else toast(`Удалено веток: ${res.deleted.length}`);
    await loadRepos();
    openRepo(r.path, { push: false });
  } catch (err) { toast(err.message, true); }
}

const cdCommand = (path) => (/\s/.test(path) ? `cd "${path}"` : `cd ${path}`);

/* ---------------------------------------------------------------- events */
$("#gGrid").addEventListener("click", (e) => {
  const card = e.target.closest(".repo-card[data-path]");
  if (!card) return;
  const act = e.target.closest("[data-act]")?.dataset.act;
  if (e.target.closest("a")) return;
  if (act === "cd") return copyText(cdCommand(card.dataset.path));
  if (act === "fetch") return fetchOne(card.dataset.path, e.target.closest("button"));
  openRepo(card.dataset.path);
});
$("#gGrid").addEventListener("keydown", (e) => {
  const card = e.target.closest(".repo-card[data-path]");
  if (card && e.key === "Enter") openRepo(card.dataset.path);
});
$("#gGrid").addEventListener("submit", async (e) => {
  if (e.target.id !== "gRootForm") return;
  e.preventDefault();
  const v = $("#gRootInput").value.trim();
  if (!v) return;
  try {
    const r = await sapi("PUT", "/api/settings/git_roots", { roots: [...(G.data.roots || []), v] });
    toast(`Найдено репозиториев: ${r.repos.length}`);
    await loadRepos();
  } catch (err) { toast(err.message, true); }
});

$("#gDrawer").addEventListener("click", (e) => {
  if (e.target.id === "gDrawer") return closeDrawer();
  const btn = e.target.closest("[data-act]");
  if (!btn || !G.open) return;
  const act = btn.dataset.act;
  if (act === "close") closeDrawer();
  else if (act === "fetch") fetchOne(G.open, btn);
  else if (act === "pull") pull(G.open, btn);
  else if (act === "cd") copyText(cdCommand(G.open));
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !$("#gDrawer").hidden && $("#confirm").hidden && $("#palette").hidden) { e.preventDefault(); closeDrawer(); }
  if (currentView !== "git" || e.target.closest("input, textarea, select") || e.ctrlKey || e.metaKey || e.altKey) return;
  if ((e.key === "r" || e.key === "к") && $("#gDrawer").hidden) { e.preventDefault(); loadRepos(); }
});

$("#gRefresh").addEventListener("click", () => loadRepos());
$("#gFetchAll").addEventListener("click", fetchAll);
$("#gSearch").addEventListener("input", debounce((e) => { G.q = e.target.value.trim(); if (G.data) renderGrid(); }, 100));
$('[data-name="gFilter"]').addEventListener("change", () => { G.filter = segValue("gFilter"); if (G.data) renderGrid(); });
$("#gSort").value = G.sort;
$("#gSort").addEventListener("change", (e) => { G.sort = e.target.value; store.set("g-sort", G.sort); if (G.data) renderGrid(); });

/* ----------------------------------------------------------------- hooks */
onView.git = () => {
  if (!G.loaded) { G.loaded = true; loadRepos(); }
  else loadRepos();
};
onView.gitRoute = (path) => {
  if (path) openRepo(path, { push: false });
  else if (!$("#gDrawer").hidden) closeDrawer();
};
onView.fetchAll = fetchAll;
window.addEventListener("hashchange", () => { if (!location.hash.startsWith("#git")) closeDrawer(); });

// keep the sidebar badge fresh without opening the module
sapi("GET", "/api/git/repos").then((d) => { G.data = G.data || d; updateNavCount(); }).catch(() => {});
