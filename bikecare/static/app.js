"use strict";

let S = null;                       // last /api/state
let tab = localStorage.getItem("tab") || "todo";
let calMonth = new Date(); calMonth.setDate(1);

const $ = (sel) => document.querySelector(sel);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const STATUS = { critical: "Критично", overdue: "Просрочено", soon: "Скоро",
                 ok: "В порядке", idle: "—" };
const COLOR = { critical: "var(--critical)", overdue: "var(--overdue)",
                soon: "var(--soon)", ok: "var(--ok)", idle: "var(--idle)" };
const FRAMES = { road: "Шоссе", gravel: "Гревел", mtb: "MTB", city: "Город" };
const day = (iso) => iso ? new Date(iso).toLocaleDateString("ru-RU",
  { day: "numeric", month: "short", year: "numeric" }) : "";
const km = (m) => Math.round(m / 1000).toLocaleString("ru-RU");
const localInput = (d = new Date()) =>
  new Date(d - d.getTimezoneOffset() * 6e4).toISOString().slice(0, 16);
const toUTC = (local) => local ? new Date(local).toISOString().replace(/\.\d+Z$/, "Z") : null;

async function api(path, body, method = "POST") {
  const r = await fetch(path, { method, headers: { "Content-Type": "application/json" },
                                body: body ? JSON.stringify(body) : undefined });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.error || r.statusText);
  return j;
}

async function load() {
  S = await (await fetch("/api/state")).json();
  render();
}

function toast(msg) {
  const t = $("#toast"); t.textContent = msg; t.hidden = false;
  clearTimeout(toast.h); toast.h = setTimeout(() => (t.hidden = true), 3500);
}

async function act(fn, ok) {
  try { await fn(); if (ok) toast(ok); await load(); }
  catch (e) { toast("Ошибка: " + e.message); }
}

/* ---------- header ---------- */
function renderStrava() {
  const s = S.strava, el = $("#strava");
  if (s.connected) {
    el.innerHTML = `<span>Strava: ${esc(s.athlete?.name || "подключена")}
      ${s.synced_at ? "· " + day(s.synced_at) : ""}</span>
      <button class="btn small" id="sync">Синхронизировать</button>
      <button class="btn small link" id="disc">Отключить</button>`;
    $("#sync").onclick = () => act(async () => {
      const r = await api("/api/strava/sync"); toast(`Загружено поездок: ${r.rides}`);
    });
    $("#disc").onclick = () => confirm("Отключить Strava? Поездки останутся.") &&
      act(() => api("/api/strava/disconnect"), "Strava отключена");
  } else if (s.configured) {
    el.innerHTML = `<a class="btn small primary" href="/strava/connect">Подключить Strava</a>`;
  } else {
    el.innerHTML = `<span title="Задайте STRAVA_CLIENT_ID и STRAVA_CLIENT_SECRET и перезапустите сервер">Strava не настроена</span>`;
  }
}

/* ---------- views ---------- */
const bar = (w) => `<div class="bar"><i style="width:${Math.min(w.progress, 1) * 100}%;
  background:${COLOR[w.status]}"></i></div>`;

function viewTodo() {
  const t = S.todo, active = S.bikes.filter((b) => !b.retired);
  const n = (st) => t.filter((i) => i.status === st).length;
  const month = Date.now() - 30 * 864e5;
  const recent = S.rides.filter((r) => new Date(r.start) > month);
  const head = `<h2>Один список на все велосипеды</h2>
    <p class="sub">Что пора сделать, от самого срочного. Нажмите на пункт, чтобы отметить работу.</p>
    <div class="summary">
      <div class="card"><div class="muted">Велосипедов</div><div class="big">${active.length}</div></div>
      <div class="card"><div class="muted">Просрочено</div><div class="big" style="color:var(--critical)">${n("critical") + n("overdue")}</div></div>
      <div class="card"><div class="muted">Скоро</div><div class="big" style="color:var(--soon)">${n("soon")}</div></div>
      <div class="card"><div class="muted">За 30 дней</div><div class="big">${km(recent.reduce((a, r) => a + r.distance_m, 0))} км</div></div>
    </div>`;
  if (!active.length) return head + emptyGarage();
  if (!t.length) return head + `<div class="card empty">Всё в порядке — можно кататься 🚲</div>`;
  return head + t.map((i) => `
    <div class="card todo b-${i.status}" data-log="${i.component_id}">
      <div class="row">
        <div class="dot" style="background:${COLOR[i.status]}"></div>
        <div class="grow"><h3>${esc(i.title)}</h3>
          <div class="muted">${esc(i.bike)} · ${esc(i.label)}</div></div>
        <span class="pill s-${i.status}">${STATUS[i.status]}</span>
      </div>${bar(i)}
    </div>`).join("");
}

function emptyGarage() {
  return `<div class="card empty">
    <p>Гараж пуст. Подключите Strava — велосипеды и поездки подтянутся сами —
    или добавьте велосипед вручную.</p>
    <button class="btn primary" data-addbike>Добавить велосипед</button></div>`;
}

function viewBikes() {
  const head = `<div class="bike-head"><div><h2>Велосипеды</h2>
    <p class="sub">Карточка сборки: детали, интервалы и сколько от них уже съедено.</p></div>
    <button class="btn primary" data-addbike>+ Велосипед</button></div>`;
  if (!S.bikes.length) return head + emptyGarage();
  return head + S.bikes.map((b) => `
    <div class="card" style="${b.retired ? "opacity:.55" : ""}">
      <div class="bike-head">
        <div><h3 style="font-size:18px">${esc(b.name)}</h3>
          <div class="muted">${FRAMES[b.frame] || b.frame} · ${b.total_km.toLocaleString("ru-RU")} км ·
            ${b.ride_count} поездок${b.strava_gear_id ? " · Strava" : ""}${b.retired ? " · на пенсии" : ""}</div>
          ${b.notes ? `<div class="muted" style="margin-top:4px">${esc(b.notes)}</div>` : ""}</div>
        <div class="actions">
          <button class="btn small" data-addcomp="${b.id}">+ Деталь</button>
          <button class="btn small" data-editbike="${b.id}">Изменить</button>
        </div>
      </div>
      ${b.components.map((c) => `
        <div class="comp">
          <div><b>${esc(c.name || c.label_kind)}</b>
            ${c.name ? `<span class="muted"> · ${esc(c.label_kind)}</span>` : ""}
            <div class="muted">${esc(c.wear.label)} · с ${day(c.wear.since)} ·
              ${limitsText(c.wear)}</div>${bar(c.wear)}</div>
          <div class="actions" style="align-items:start">
            <button class="btn small" data-log="${c.id}">${c.wear.action === "service" ? "Обслужено" : "Заменено"}</button>
            <button class="btn small link" data-editcomp="${c.id}" title="Настроить">⚙</button>
          </div>
        </div>`).join("") || `<div class="muted">Деталей нет</div>`}
    </div>`).join("");
}

function limitsText(w) {
  const parts = [];
  if (w.limits.km) parts.push(`${Math.round(w.used.km)} / ${w.limits.km} км`);
  if (w.limits.hours) parts.push(`${Math.round(w.used.hours)} / ${w.limits.hours} ч`);
  if (w.limits.days) parts.push(`${Math.round(w.used.days)} / ${w.limits.days} дн`);
  return parts.join(" · ");
}

function viewLogs() {
  const rows = S.logs.map((l) => `<tr>
    <td>${day(l.at)}</td><td>${esc(l.bike)}</td>
    <td>${esc(l.component || kindLabel(l.kind) || "—")}
      <div class="muted">${l.action === "replace" ? "замена" : l.action === "service" ? "обслуживание" : "заметка"}</div></td>
    <td class="hide-sm">${esc(l.note)}</td>
    <td class="num">${l.cost != null ? l.cost : ""}</td>
    <td><button class="btn small link" data-dellog="${l.id}" title="Удалить">✕</button></td></tr>`).join("");
  return `<h2>Журнал обслуживания</h2><p class="sub">Каждая запись обнуляет счётчик своей детали.</p>
    ${S.logs.length ? `<div class="card"><table><tr><th>Дата</th><th>Велосипед</th><th>Что</th>
      <th class="hide-sm">Заметка</th><th class="num">€</th><th></th></tr>${rows}</table></div>`
      : `<div class="card empty">Пока пусто</div>`}`;
}
const kindLabel = (k) => S.kinds.find((x) => x.key === k)?.label;

function viewCalendar() {
  const y = calMonth.getFullYear(), m = calMonth.getMonth();
  const first = new Date(y, m, 1), shift = (first.getDay() + 6) % 7;
  const start = new Date(y, m, 1 - shift);
  const key = (d) => `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
  const ev = {};
  const push = (d, html) => ((ev[key(d)] ||= []).push(html));
  S.rides.forEach((r) => push(new Date(r.start),
    `<span class="ev ride" title="${esc(r.name)} · ${esc(r.bike || "")}">${km(r.distance_m)} км ${esc(r.bike || "")}</span>`));
  S.logs.forEach((l) => push(new Date(l.at),
    `<span class="ev log" title="${esc(l.note)}">✓ ${esc(l.component || kindLabel(l.kind) || "")}</span>`));
  S.bikes.filter((b) => !b.retired).forEach((b) => b.components.forEach((c) => {
    const w = c.wear;
    if (w.eta_days == null || !["ok", "soon"].includes(w.status)) return;
    const d = new Date(Date.now() + w.eta_days * 864e5);
    push(d, `<span class="ev due" title="${esc(b.name)} · ${esc(w.label)}">⏰ ${esc(c.name || c.label_kind)}</span>`);
  }));
  const today = key(new Date());
  let cells = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"].map((d) => `<div class="dow">${d}</div>`).join("");
  for (let i = 0; i < 42; i++) {
    const d = new Date(start); d.setDate(start.getDate() + i);
    if (i >= 35 && d.getMonth() !== m) break;
    cells += `<div class="day ${d.getMonth() !== m ? "out" : ""} ${key(d) === today ? "today" : ""}">
      <div class="n">${d.getDate()}</div>${(ev[key(d)] || []).join("")}</div>`;
  }
  const title = first.toLocaleDateString("ru-RU", { month: "long" }) + " " + y;
  return `<div class="bike-head"><div><h2 style="text-transform:capitalize">${title}</h2>
    <p class="sub">Поездки, сделанные работы и прогноз — когда что подойдёт при нынешнем темпе.</p></div>
    <div class="actions"><button class="btn small" data-cal="-1">←</button>
    <button class="btn small" data-cal="0">Сегодня</button>
    <button class="btn small" data-cal="1">→</button></div></div>
    <div class="cal">${cells}</div>`;
}

function viewRides() {
  const opts = (sel) => `<option value="">— без велосипеда —</option>` + S.bikes.map((b) =>
    `<option value="${b.id}" ${b.id === sel ? "selected" : ""}>${esc(b.name)}</option>`).join("");
  const rows = S.rides.map((r) => `<tr>
    <td>${day(r.start)}</td>
    <td>${esc(r.name)}<div class="muted">${esc(r.sport)}${r.trainer ? " · станок" : ""}${r.commute ? " · коммьют" : ""}</div></td>
    <td class="num">${km(r.distance_m)} км</td>
    <td class="num hide-sm">${Math.round(r.elev_m)} м</td>
    <td><select data-ride="${esc(r.id)}">${opts(r.bike_id)}</select></td></tr>`).join("");
  return `<div class="bike-head"><div><h2>Поездки</h2>
    <p class="sub">Из Strava или вручную. Не тот велосипед — поменяйте, износ пересчитается.</p></div>
    <button class="btn primary" data-addride>+ Поездка</button></div>
    ${S.rides.length ? `<div class="card"><table><tr><th>Дата</th><th>Поездка</th>
      <th class="num">Дист.</th><th class="num hide-sm">Набор</th><th>Велосипед</th></tr>${rows}</table></div>`
      : `<div class="card empty">Поездок пока нет</div>`}`;
}

/* ---------- modals ---------- */
function modal(html, onSubmit) {
  const d = $("#modal"), f = $("#modal-body");
  f.innerHTML = html + `<div class="actions"><button class="btn" value="cancel" formnovalidate>Отмена</button>
    <button class="btn primary" value="ok">Сохранить</button></div>`;
  f.onsubmit = (e) => {
    if (e.submitter?.value !== "ok") return;
    const data = Object.fromEntries(new FormData(f));
    f.querySelectorAll("input[type=checkbox]").forEach((c) => (data[c.name] = c.checked));
    onSubmit(data);
  };
  d.showModal();
}

function findComp(id) {
  for (const b of S.bikes) for (const c of b.components) if (c.id === id) return [b, c];
  return [];
}

function logModal(id) {
  const [b, c] = findComp(id);
  const w = c.wear;
  modal(`<h3>${esc(c.name || c.label_kind)} · ${esc(b.name)}</h3>
    <div><span class="pill s-${w.status}">${STATUS[w.status]}</span>
      <span class="muted"> ${esc(w.label)} · ${limitsText(w)}</span></div>
    ${w.prep.length ? `<div><div class="muted">Подготовить</div><ul class="prep">
      ${w.prep.map((p) => `<li>${esc(p)}</li>`).join("")}</ul></div>` : ""}
    <label>Что сделано<select name="action">
      <option value="replace" ${w.action === "replace" ? "selected" : ""}>Замена</option>
      <option value="service" ${w.action === "service" ? "selected" : ""}>Обслуживание</option></select></label>
    <label>Когда<input type="datetime-local" name="at" value="${localInput()}"></label>
    <label>Заметка<input name="note" placeholder="модель, что заметили…"></label>
    <label>Стоимость<input name="cost" type="number" step="0.01" min="0"></label>`,
    (d) => act(() => api(`/api/components/${id}/log`, { ...d, at: toUTC(d.at) }),
               "Записано — счётчик обнулён"));
}

function intervalFields(src = {}) {
  return `<div class="grid3">
    <label>км<input name="interval_km" type="number" min="0" value="${src.km ?? ""}"></label>
    <label>дней<input name="interval_days" type="number" min="0" value="${src.days ?? ""}"></label>
    <label>часов<input name="interval_hours" type="number" min="0" value="${src.hours ?? ""}"></label></div>`;
}

function compModal(id) {
  const [b, c] = findComp(id);
  modal(`<h3>${esc(c.label_kind)} · ${esc(b.name)}</h3>
    <label>Модель<input name="name" value="${esc(c.name)}" placeholder="напр. Shimano CN-M8100"></label>
    <label>Установлена / последнее ТО (если не знаете — оставьте)
      <input type="datetime-local" name="installed_at" value="${localInput(new Date(c.installed_at))}"></label>
    <div class="muted">Интервал — что наступит раньше</div>${intervalFields(c.wear.limits)}
    <label class="check"><input type="checkbox" name="remove"> Снять деталь с велосипеда</label>`,
    (d) => act(() => api(`/api/components/${id}`, {
      name: d.name, installed_at: toUTC(d.installed_at),
      interval_km: d.interval_km, interval_days: d.interval_days,
      interval_hours: d.interval_hours, active: d.remove ? 0 : 1 }), "Сохранено"));
}

function addCompModal(bikeId) {
  const opts = S.kinds.map((k) => `<option value="${k.key}">${esc(k.label)}</option>`).join("");
  modal(`<h3>Новая деталь</h3>
    <label>Тип<select name="kind" id="kindsel">${opts}</select></label>
    <label>Модель<input name="name"></label>
    <label>Установлена<input type="datetime-local" name="installed_at" value="${localInput()}"></label>
    <div class="muted">Интервал (пусто — по умолчанию для типа)</div>${intervalFields()}`,
    (d) => act(() => api(`/api/bikes/${bikeId}/components`,
                         { ...d, installed_at: toUTC(d.installed_at) }), "Деталь добавлена"));
}

function bikeModal(id) {
  const b = S.bikes.find((x) => x.id === id) || { name: "", frame: "gravel", notes: "" };
  const frames = Object.entries(FRAMES).map(([k, v]) =>
    `<option value="${k}" ${b.frame === k ? "selected" : ""}>${v}</option>`).join("");
  modal(`<h3>${id ? "Велосипед" : "Новый велосипед"}</h3>
    <label>Название<input name="name" required value="${esc(b.name)}"></label>
    <label>Тип<select name="frame">${frames}</select></label>
    ${id ? `<label>Сборка, заметки<textarea name="notes" rows="3">${esc(b.notes)}</textarea></label>
      <label class="check"><input type="checkbox" name="retired" ${b.retired ? "checked" : ""}> На пенсии (скрыть из to-do)</label>
      <label class="check"><input type="checkbox" name="del"> Удалить велосипед совсем</label>`
      : `<div class="muted">Набор деталей подставится по типу; лишнее можно снять.</div>`}`,
    (d) => act(async () => {
      if (!id) return api("/api/bikes", d);
      if (d.del) { if (confirm("Удалить велосипед, его детали и журнал?")) return api(`/api/bikes/${id}`, null, "DELETE"); return; }
      return api(`/api/bikes/${id}`, { name: d.name, frame: d.frame, notes: d.notes, retired: d.retired ? 1 : 0 });
    }, "Сохранено"));
}

function rideModal() {
  const opts = S.bikes.filter((b) => !b.retired).map((b) => `<option value="${b.id}">${esc(b.name)}</option>`).join("");
  modal(`<h3>Поездка вручную</h3>
    <label>Велосипед<select name="bike_id">${opts}</select></label>
    <label>Когда<input type="datetime-local" name="start" value="${localInput()}"></label>
    <div class="grid3"><label>км<input name="distance_km" type="number" step="0.1" min="0" required></label>
      <label>набор, м<input name="elev_m" type="number" min="0"></label>
      <label>часов<input name="hours" type="number" step="0.1" min="0"></label></div>
    <label>Покрытие<select name="sport"><option value="Ride">Асфальт</option>
      <option value="GravelRide">Гревел</option><option value="MountainBikeRide">MTB</option></select></label>
    <label class="check"><input type="checkbox" name="trainer"> На станке</label>
    <label class="check"><input type="checkbox" name="commute"> Коммьют</label>`,
    (d) => act(() => api("/api/rides", { ...d, start: toUTC(d.start) }), "Поездка добавлена"));
}

/* ---------- wiring ---------- */
const VIEWS = { todo: viewTodo, bikes: viewBikes, logs: viewLogs, calendar: viewCalendar, rides: viewRides };

function render() {
  renderStrava();
  document.querySelectorAll("#tabs button").forEach((b) => b.classList.toggle("on", b.dataset.tab === tab));
  $("#view").innerHTML = VIEWS[tab]();
}

document.addEventListener("click", (e) => {
  const t = e.target.closest("button, [data-log]");
  if (!t) return;
  const d = t.dataset;
  if (d.tab) { tab = d.tab; localStorage.setItem("tab", tab); render(); }
  else if (d.log) logModal(+d.log);
  else if (d.editcomp) compModal(+d.editcomp);
  else if (d.addcomp) addCompModal(+d.addcomp);
  else if ("addbike" in d) bikeModal(null);
  else if (d.editbike) bikeModal(+d.editbike);
  else if ("addride" in d) rideModal();
  else if (d.dellog) confirm("Удалить запись?") && act(() => api(`/api/logs/${d.dellog}`, null, "DELETE"));
  else if (d.cal) {
    if (d.cal === "0") { calMonth = new Date(); calMonth.setDate(1); }
    else calMonth.setMonth(calMonth.getMonth() + +d.cal);
    render();
  }
});
document.addEventListener("change", (e) => {
  const id = e.target.dataset?.ride;
  if (id) act(() => api(`/api/rides/${encodeURIComponent(id)}`,
                        { bike_id: e.target.value ? +e.target.value : null }), "Велосипед поменян");
});

const HASH = { "#synced": "Strava подключена, поездки загружены",
               "#strava-denied": "Strava: доступ не выдан",
               "#strava-error": "Strava: ошибка, см. лог сервера",
               "#strava-missing": "Сначала задайте STRAVA_CLIENT_ID и STRAVA_CLIENT_SECRET" };
if (HASH[location.hash]) { toast(HASH[location.hash]); history.replaceState(null, "", "/"); }
load();
