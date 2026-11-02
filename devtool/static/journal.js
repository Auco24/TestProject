"use strict";
/* global $, $$, esc, debounce, toast, copyText, store, svg, onView, sapi, confirmDialog, plural */

/* ======================================================================
   Developer journal
   ====================================================================== */
const J = {
  kind: "done", meta: null, days: [], before: null, hasMore: false, loaded: false,
  q: "", project: "", format: store.get("j-format", "text"), standupDate: "",
};
const KIND_ICON = { done: "✓", plan: "○", blocker: "!", note: "•" };
const KIND_PLACEHOLDER = {
  done: "Что сделано? Enter — записать. Можно #теги",
  plan: "Что планируете сделать?",
  blocker: "Что мешает работе?",
  note: "Заметка, мысль, ссылка…",
};

const isoToday = () => {
  const d = new Date();
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
};
const hhmm = (iso) => (iso || "").slice(11, 16);
const withTags = (text) => esc(text).replace(/(^|[^\w&])#([\w.+-]+)/gu, '$1<span class="j-tag">#$2</span>');

/* ---------------------------------------------------------------- data */
async function loadMeta() {
  J.meta = await sapi("GET", "/api/journal/meta");
  const st = J.meta.stats;
  $("#jStreakNav").textContent = st.streak ? `🔥${st.streak}` : "";
  const remembered = store.get("j-project", "");
  const opts = J.meta.projects.map((p) => `<option value="${esc(p.path || "name:" + p.name)}">${esc(p.name)}</option>`).join("");
  $("#jProject").innerHTML = '<option value="">Без проекта</option>' + opts;
  if ([...$("#jProject").options].some((o) => o.value === remembered)) $("#jProject").value = remembered;
  const names = [...new Set(J.meta.projects.map((p) => p.name))];
  $("#jFilterProject").innerHTML = '<option value="">Все проекты</option>' + names.map((n) => `<option>${esc(n)}</option>`).join("");
  $("#jFilterProject").value = J.project;
  renderStats();
  renderRoots();
}

async function loadTimeline(append = false) {
  const p = new URLSearchParams({ days: 14 });
  if (append && J.before) p.set("before", J.before);
  if (J.q) p.set("q", J.q);
  if (J.project) p.set("project", J.project);
  const r = await sapi("GET", "/api/journal?" + p);
  J.days = append ? [...J.days, ...r.days] : r.days;
  J.before = r.next_before;
  J.hasMore = r.has_more;
  renderTimeline();
}

async function loadStandup() {
  const p = new URLSearchParams({ format: J.format });
  if (J.standupDate) p.set("date", J.standupDate);
  const r = await sapi("GET", "/api/journal/standup?" + p);
  $("#jStandup").textContent = r.text;
  return r;
}

async function refreshAll() {
  try { await Promise.all([loadMeta(), loadTimeline(), loadStandup()]); }
  catch (err) { toast(err.message, true); }
}
const refreshSide = () => Promise.all([loadMeta(), loadStandup()]).catch((e) => toast(e.message, true));

/* ----------------------------------------------------------- rendering */
function entryHtml(e) {
  const checkable = e.kind === "plan" || e.kind === "blocker";
  const title = e.kind === "plan" ? (e.completed ? "Вернуть в план" : "Отметить выполненным")
    : e.kind === "blocker" ? (e.completed ? "Вернуть блокер" : "Отметить решённым") : "";
  const icon = e.completed ? "✓" : KIND_ICON[e.kind];
  const project = e.project
    ? `<span class="j-project" title="${esc(e.repo_path || "")}">${esc(e.project)}${e.branch ? `<i>⎇ ${esc(e.branch)}</i>` : ""}</span>` : "";
  return `<div class="j-entry k-${e.kind}${e.completed ? " completed" : ""}" data-id="${e.id}">
    <button class="j-icon" ${checkable ? `data-act="toggle" title="${title}"` : "disabled"}>${icon}</button>
    <div class="j-body">
      <div class="j-text">${withTags(e.text)}</div>
      <div class="j-meta"><span class="j-time">${hhmm(e.created_at)}</span>${project}</div>
    </div>
    <div class="j-actions">
      <button class="mini-icon" data-act="edit" title="Редактировать">${svg("edit")}</button>
      <button class="mini-icon danger" data-act="delete" title="Удалить">${svg("trash")}</button>
    </div>
  </div>`;
}

function commitsHtml(commits, open) {
  if (!commits.length) return "";
  const projects = [...new Set(commits.map((c) => c.project))];
  return `<details class="j-commits"${open ? " open" : ""}>
    <summary><span class="j-commit-ico">⎇</span>${commits.length} ${plural(commits.length, "коммит", "коммита", "коммитов")}
      <span class="muted">· ${projects.map(esc).join(", ")}</span></summary>
    <div class="j-commit-list">${commits.map((c) => `
      <div class="j-commit"><code>${esc(c.sha)}</code><span class="j-commit-msg">${esc(c.subject)}</span>
        <span class="j-project">${esc(c.project)}</span><span class="j-time">${hhmm(c.time)}</span></div>`).join("")}
    </div>
  </details>`;
}

function renderTimeline() {
  const el = $("#jTimeline");
  const nonEmpty = J.days.filter((d) => d.entries.length || d.commits.length);
  if (!nonEmpty.length && !J.days.length) {
    el.innerHTML = `<div class="empty-state small"><p class="muted">${J.q || J.project ? "Ничего не найдено" : "Пока пусто"}</p></div>`;
  } else {
    el.innerHTML = J.days.map((d, i) => {
      const counts = ["done", "plan", "blocker"].map((k) => [k, d.entries.filter((e) => e.kind === k).length]).filter(([, n]) => n);
      const empty = !d.entries.length && !d.commits.length;
      return `<section class="j-day${d.date === isoToday() ? " today" : ""}">
        <header class="j-day-head">
          <h3>${esc(d.label)}</h3><span class="j-date">${d.date}</span>
          <span class="j-counts">${counts.map(([k, n]) => `<span class="jc k-${k}">${KIND_ICON[k]} ${n}</span>`).join("")}</span>
        </header>
        ${empty ? `<div class="j-empty">Записей пока нет. Что уже успели сделать? Пишите сверху ↑</div>` : ""}
        <div class="j-entries">${d.entries.map(entryHtml).join("")}</div>
        ${commitsHtml(d.commits, i === 0)}
      </section>`;
    }).join("");
  }
  $("#jMore").hidden = !J.hasMore;
}

const STAT_DEFS = [
  ["streak", "🔥", "дней подряд"],
  ["week", "📝", "записей за неделю"],
  ["open_plans", "○", "открытых планов"],
  ["commits", "⎇", "коммитов за 18 нед."],
];
function renderStats() {
  const st = J.meta.stats;
  $("#jStats").innerHTML = STAT_DEFS.map(([k, ico, label]) =>
    `<div class="stat"><div class="stat-v"><span>${ico}</span>${st[k]}</div><div class="stat-l">${label}</div></div>`
  ).join("");

  const { start, end, counts } = st.heatmap;
  const max = Math.max(1, ...Object.values(counts));
  const level = (n) => (!n ? 0 : Math.min(4, Math.ceil((n / max) * 4)));
  const cells = [];
  const d = new Date(start + "T00:00:00");
  const last = new Date(end + "T00:00:00");
  const months = [];
  let col = 0;
  while (d <= last) {
    const iso = new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
    const n = counts[iso] || 0;
    if (d.getDay() === 1) {
      if (d.getDate() <= 7) months.push([col, d.toLocaleDateString("ru-RU", { month: "short" }).replace(".", "")]);
      col++;
    }
    cells.push(`<i class="l${level(n)}" title="${d.toLocaleDateString("ru-RU", { weekday: "short", day: "numeric", month: "long" })}: ${n} ${plural(n, "событие", "события", "событий")}"></i>`);
    d.setDate(d.getDate() + 1);
  }
  $("#jHeatmap").style.setProperty("--cols", col);
  $("#jHeatmap").innerHTML =
    `<div class="hm-months">${months.map(([c, m]) => `<span style="grid-column:${c}">${m}</span>`).join("")}</div>
     <div class="hm-grid">${cells.join("")}</div>`;
}

function renderRoots() {
  const roots = J.meta.git_roots;
  $("#jRootsHint").textContent = J.meta.git
    ? "Коммиты из git-репозиториев в этих папках попадают в таймлайн и отчёт."
    : "Git не найден в системе: коммиты подтягиваться не будут.";
  const repoCount = J.meta.projects.filter((p) => p.path).length;
  $("#jRoots").innerHTML = roots.map((r) =>
    `<div class="root"><code title="${esc(r)}">${esc(r)}</code><button class="mini-icon danger" data-root="${esc(r)}" title="Убрать">×</button></div>`
  ).join("") + (repoCount ? `<div class="muted small">Найдено репозиториев: <b>${repoCount}</b></div>` : "");
}

/* -------------------------------------------------------------- actions */
function setKind(kind) {
  J.kind = kind;
  $$("#jKind button").forEach((b) => b.classList.toggle("on", b.dataset.kind === kind));
  $(".composer").dataset.kind = kind;
  $("#jText").placeholder = KIND_PLACEHOLDER[kind];
}

async function addEntry() {
  const input = $("#jText");
  const text = input.value.trim();
  if (!text) { input.focus(); return; }
  const proj = $("#jProject").value;
  const body = { text, kind: J.kind };
  if (proj.startsWith("name:")) body.project = proj.slice(5);
  else if (proj) body.repo_path = proj;
  try {
    await sapi("POST", "/api/journal", body);
    input.value = "";
    if (J.kind !== "done" && J.kind !== "note") toast(J.kind === "plan" ? "Добавлено в план" : "Блокер записан");
    await Promise.all([loadTimeline(), refreshSide()]);
    $(".j-day.today .j-entry")?.classList.add("flash");
  } catch (err) { toast(err.message, true); }
}

function findEntry(id) {
  for (const d of J.days) {
    const e = d.entries.find((x) => x.id === id);
    if (e) return e;
  }
  return null;
}

async function patchEntry(id, body) {
  try {
    await sapi("PATCH", `/api/journal/${id}`, body);
    await Promise.all([loadTimeline(), refreshSide()]);
  } catch (err) { toast(err.message, true); }
}

function startEdit(row, e) {
  const textEl = $(".j-text", row);
  textEl.innerHTML = `<input class="j-edit" value="${esc(e.text)}" maxlength="2000">`;
  const inp = $("input", textEl);
  inp.focus();
  inp.setSelectionRange(inp.value.length, inp.value.length);
  let done = false;
  const finish = (save) => {
    if (done) return;
    done = true;
    if (save && inp.value.trim() && inp.value.trim() !== e.text) patchEntry(e.id, { text: inp.value });
    else textEl.innerHTML = withTags(e.text);
  };
  inp.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter") { ev.preventDefault(); finish(true); }
    if (ev.key === "Escape") { ev.preventDefault(); ev.stopPropagation(); finish(false); }
  });
  inp.addEventListener("blur", () => finish(true));
}

$("#jTimeline").addEventListener("click", async (ev) => {
  const btn = ev.target.closest("[data-act]");
  if (!btn) return;
  const row = btn.closest(".j-entry");
  const e = findEntry(+row.dataset.id);
  if (!e) return;
  const act = btn.dataset.act;
  if (act === "toggle") {
    if (!e.completed) row.classList.add("completing");
    await patchEntry(e.id, { completed: !e.completed });
  } else if (act === "edit") startEdit(row, e);
  else if (act === "delete") {
    const ok = await confirmDialog("Удалить запись?", `«${e.text.slice(0, 120)}»`);
    if (ok) {
      try { await sapi("DELETE", `/api/journal/${e.id}`); toast("Удалено"); await Promise.all([loadTimeline(), refreshSide()]); }
      catch (err) { toast(err.message, true); }
    }
  }
});

async function copyStandup() {
  try {
    const r = await loadStandup();
    await copyText(r.text);
  } catch (err) { toast(err.message, true); }
}

/* --------------------------------------------------------------- events */
$("#jKind").addEventListener("click", (e) => {
  const b = e.target.closest("button");
  if (b) { setKind(b.dataset.kind); $("#jText").focus(); }
});
$("#jText").addEventListener("keydown", (e) => {
  if (e.key === "Enter") { e.preventDefault(); addEntry(); }
});
$("#jAdd").addEventListener("click", addEntry);
$("#jProject").addEventListener("change", (e) => store.set("j-project", e.target.value));
document.addEventListener("keydown", (e) => {
  if (currentView !== "journal" || !e.altKey) return;
  const k = ["done", "plan", "blocker", "note"][+e.key - 1];
  if (k) { e.preventDefault(); setKind(k); $("#jText").focus(); }
});

$("#jSearch").addEventListener("input", debounce((e) => { J.q = e.target.value.trim(); loadTimeline().catch((x) => toast(x.message, true)); }, 200));
$("#jFilterProject").addEventListener("change", (e) => { J.project = e.target.value; loadTimeline().catch((x) => toast(x.message, true)); });
$("#jMore").addEventListener("click", () => loadTimeline(true).catch((x) => toast(x.message, true)));

$(`[data-name="jFormat"] [data-value="${J.format}"]`)?.click();
$('[data-name="jFormat"]').addEventListener("change", () => {
  J.format = segValue("jFormat");
  store.set("j-format", J.format);
  loadStandup().catch((x) => toast(x.message, true));
});
$("#jStandupDate").value = isoToday();
$("#jStandupDate").addEventListener("change", (e) => { J.standupDate = e.target.value; loadStandup().catch((x) => toast(x.message, true)); });
$("#jStandupCopy").addEventListener("click", copyStandup);

$("#jRootsForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const v = $("#jRootInput").value.trim();
  if (!v) return;
  try {
    const r = await sapi("PUT", "/api/settings/git_roots", { roots: [...J.meta.git_roots, v] });
    $("#jRootInput").value = "";
    toast(`Папка добавлена, репозиториев: ${r.repos.length}`);
    await refreshAll();
  } catch (err) { toast(err.message, true); }
});
$("#jRoots").addEventListener("click", async (e) => {
  const b = e.target.closest("[data-root]");
  if (!b) return;
  try {
    await sapi("PUT", "/api/settings/git_roots", { roots: J.meta.git_roots.filter((r) => r !== b.dataset.root) });
    await refreshAll();
  } catch (err) { toast(err.message, true); }
});

/* ---------------------------------------------------------------- hooks */
onView.journal = async () => {
  setKind(J.kind);
  if (!J.loaded) { J.loaded = true; await refreshAll(); }
  else await Promise.all([loadTimeline(), refreshSide()]).catch(() => {});
  if (window.innerWidth > 760) $("#jText").focus();
};
onView.focusJournal = () => $("#jText").focus();
onView.copyStandup = copyStandup;

sapi("GET", "/api/journal/meta").then((m) => {
  $("#jStreakNav").textContent = m.stats.streak ? `🔥${m.stats.streak}` : "";
}).catch(() => {});
