const state = { timer: null, selectedCity: null };

const fmtMoney = (value) => {
  const n = Number(value || 0);
  return `${n >= 0 ? "+" : ""}${n.toFixed(2)}$`;
};
const fmtCapital = (value) => `$${Number(value || 0).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const intTemp = (value) => {
  const n = Number(value);
  if (!Number.isFinite(n)) return null;
  return n < 0 ? Math.ceil(n) : Math.floor(n);
};
const fmtTemp = (value) => value === null || value === undefined ? "—" : `${intTemp(value)}°`;
const fmtPct = (value) => `${Math.round(Number(value || 0) * 100)}%`;
const esc = (value) => String(value ?? "").replace(/[&<>"']/g, ch => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));

function ageLabel(iso) {
  if (!iso) return "sem dados";
  const seconds = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m`;
  return `${Math.floor(minutes / 60)}h${String(minutes % 60).padStart(2, "0")}m`;
}

function marketFavorite(city) {
  const brackets = (city.market && city.market.brackets) || [];
  return [...brackets].sort((a, b) => (b.ask || 0) - (a.ask || 0))[0] || {};
}

function isWuSource(src) {
  const s = String(src || "").toLowerCase();
  return s.includes("wu") || s.includes("weather underground") || s.includes("station");
}

function chartSlotsForCity(city) {
  const slots = city.slots || [];
  const wuSlots = slots.filter(s => isWuSource(s.source));
  return wuSlots.length >= 2 ? wuSlots : slots;
}

function statusClass(city) {
  const s = String(city.status || "").toLowerCase();
  if (city.stop_loss_hit || s.includes("stop")) return "stop";
  if (city.bought || s.includes("comprado")) return "bought";
  if ((city.p_ensemble || 0) >= (city.threshold || 0.65) || s.includes("signal")) return "signal";
  if (s.includes("monitor")) return "monitoring";
  return "idle";
}

function sparkline(slots) {
  const temps = (slots || []).map(s => Number(s.temp_c)).filter(Number.isFinite);
  if (temps.length < 2) return `<div class="spark"></div>`;
  const w = 320, h = 42, pad = 3;
  const min = Math.min(...temps);
  const max = Math.max(...temps);
  const range = Math.max(max - min, 0.5);
  const pts = temps.map((t, i) => {
    const x = pad + (i / Math.max(temps.length - 1, 1)) * (w - pad * 2);
    const y = h - pad - ((t - min) / range) * (h - pad * 2);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  return `<svg class="spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none"><polyline points="${pts}" fill="none" stroke="rgba(80,213,255,.85)" stroke-width="2.2" /></svg>`;
}

function renderMetrics(data) {
  const summary = data.summary || {};
  const session = data.session || {};
  const cities = data.cities || [];
  const reconciled = data.reconciled || {};
  const reconciledDaily = reconciled.daily || {};
  const reconciledTodayKey = data.reconciled_today || new Date().toISOString().slice(0, 10);
  const reconciledToday = reconciledDaily[reconciledTodayKey] || null;
  const hasPosition = (c) => Boolean(c.bought || c.position || (c.positions_all && c.positions_all.length));
  const nCities = cities.length || Number(summary.n_cities || 0);
  const nPositions = cities.filter(hasPosition).length;
  const nSignals = cities.filter(c => !hasPosition(c) && Number(c.p_ensemble || 0) >= Number(c.threshold || 0.65)).length;
  let dailyTrades = cities.reduce((acc, c) => acc + Number(c.n_trades || 0), 0);
  let dailyPnl = cities.reduce((acc, c) => acc + Number(c.daily_pnl || 0), 0);
  if (reconciledToday) {
    dailyTrades = Number(reconciledToday.trades || 0);
    dailyPnl = Number(reconciledToday.realized_pnl || 0);
  }
  if (dailyPnl === 0 && Number.isFinite(Number(session.total_pnl))) {
    dailyPnl = Number(session.total_pnl || 0);
  }

  const capitalStart = Number(summary.initial_capital ?? 1000);
  const realizedTotal = Number(reconciled.total_realized_pnl || 0);
  const capitalNow = capitalStart + (reconciledToday ? realizedTotal : dailyPnl);

  document.getElementById("m-cities").textContent = nCities || "--";
  document.getElementById("m-signals").textContent = nSignals ?? "--";
  document.getElementById("m-positions").textContent = nPositions ?? "--";
  document.getElementById("m-capital-start").textContent = fmtCapital(capitalStart);
  document.getElementById("m-capital-now").textContent = fmtCapital(capitalNow);
  document.getElementById("m-capital-now").className = capitalNow >= capitalStart ? "money-pos" : "money-neg";
  document.getElementById("m-pnl").textContent = fmtMoney(dailyPnl);
  document.getElementById("m-pnl").className = Number(dailyPnl || 0) >= 0 ? "money-pos" : "money-neg";
  const tradesDisplay = reconciledToday
    ? Number(dailyTrades || 0)
    : Math.max(Number(dailyTrades || 0), Number(session.total_trades || 0), Number(nPositions || 0));
  document.getElementById("m-trades").textContent = tradesDisplay ?? "--";
  document.getElementById("m-updated").textContent = ageLabel(data.generated_at);
  document.getElementById("source").textContent = data.source === "live_snapshot" ? `live snapshot · ${ageLabel(data.generated_at)} atrás` : "fallback logs";

  const mode = document.getElementById("mode");
  mode.textContent = data.trading_mode || "UNKNOWN";
  mode.className = `pill ${String(data.trading_mode || "").toLowerCase()}`;
}

function activeWatchRows(cities) {
  return (cities || [])
    .filter(c => c.market && c.market.brackets && c.market.brackets.length)
    .sort((a, b) => {
      const aHasPos = Boolean(a.bought || a.position || (a.positions_all && a.positions_all.length));
      const bHasPos = Boolean(b.bought || b.position || (b.positions_all && b.positions_all.length));
      if (aHasPos !== bHasPos) return Number(bHasPos) - Number(aHasPos); // ativas com posição primeiro
      const aSignal = Number(a.p_ensemble || 0) >= Number(a.threshold || 0.65);
      const bSignal = Number(b.p_ensemble || 0) >= Number(b.threshold || 0.65);
      if (aSignal !== bSignal) return Number(bSignal) - Number(aSignal); // depois sinais ativos
      return (b.market.volume || 0) - (a.market.volume || 0);
    });
}

function renderWatchlist(data) {
  const holder = document.getElementById("watchlist");
  const rows = activeWatchRows(data.cities);
  document.getElementById("watch-count").textContent = rows.length;
  if (!rows.length) {
    holder.innerHTML = `<div class="empty">Ainda sem dados de mercado.</div>`;
    return;
  }
  holder.innerHTML = rows.map(city => {
    const best = marketFavorite(city);
    const pRaw = Number(city.p_ensemble || 0);
    const hasPosition = Boolean(city.bought || city.position || (city.positions_all && city.positions_all.length));
    const isSignal = Number(city.p_ensemble || 0) >= Number(city.threshold || 0.65);
    const buying = hasPosition ? " buying" : "";
    const active = (!hasPosition && isSignal) ? " active" : "";
    const selected = state.selectedCity === city.name ? " selected" : "";
    return `
      <div class="market-row${buying}${active}${selected}" data-city="${esc(city.name)}">
        <div class="row-top"><span>${esc(city.flag)} ${esc(city.label)}</span><span class="market-favorite">${best.ask == null ? "—" : `${Math.round(best.ask * 100)}¢`}</span></div>
        <div class="market-local-time">${esc(city.local_hm || "--:--")} · ${esc(city.timezone || "")}</div>
        <div class="row-sub"><span>${esc(best.label || "—")}</span><span>${city.market.volume ? `$${Math.round(city.market.volume).toLocaleString("en-US")}` : "sem vol"}</span></div>
        <div class="mini-prob"><span>P(pico)</span><div class="mini-bar"><div style="width:${Math.min(100, pRaw * 100)}%"></div></div><strong>${fmtPct(pRaw)}</strong></div>
      </div>
    `;
  }).join("");

  holder.querySelectorAll(".market-row").forEach(el => {
    el.addEventListener("click", () => {
      state.selectedCity = el.getAttribute("data-city");
      renderWatchlist(data);
      renderDetail(data);
    });
  });
}

function collectPositions(cities) {
  const rows = [];
  for (const city of cities || []) {
    for (const pos of city.positions_all || []) rows.push({ city, pos });
    if ((!city.positions_all || !city.positions_all.length) && city.position) {
      rows.push({ city, pos: city.position });
    }
  }
  return rows;
}

function renderPositions(data) {
  const holder = document.getElementById("positions");
  if (!holder) return;
  const rows = collectPositions(data.cities);
  const openRows = rows.filter(({ pos }) => String(pos.status || "").toLowerCase() === "open");
  const displayRows = (openRows.length ? openRows : rows).slice(0, 12);
  const countEl = document.getElementById("position-count");
  if (countEl) countEl.textContent = String(rows.length);
  if (!displayRows.length) {
    holder.innerHTML = `<div class="empty">Sem posições abertas.</div>`;
    return;
  }
  holder.innerHTML = displayRows.map(({ city, pos }) => {
    const pnl = Number(pos.pnl_usd || 0);
    const entry = Number(pos.entry_ask ?? pos.ask ?? 0);
    const status = String(pos.status || "open").toUpperCase();
    return `
      <div class="position-row">
        <div class="row-top">
          <span>${esc(city.flag || "🌍")} ${esc(city.label || city.name)}</span>
          <span class="${pnl >= 0 ? "money-pos" : "money-neg"}">${fmtMoney(pnl)}</span>
        </div>
        <div class="row-sub">
          <span>${esc(pos.bracket_label || pos.bracket || "Bracket")}</span>
          <span>${entry > 0 ? `${Math.round(entry * 100)}¢` : "—"} · ${esc(status)}</span>
        </div>
      </div>
    `;
  }).join("");
}

function tempChart(city) {
  const slots = chartSlotsForCity(city);
  const temps = slots.map(s => Number(s.temp_c)).filter(Number.isFinite);
  if (temps.length < 2) return `<div class="empty">Sem dados suficientes para chart de temperatura.</div>`;
  const w = 760, h = 280, padL = 48, padR = 18, padT = 16, padB = 30;
  const min = Math.min(...temps);
  const max = Math.max(...temps);
  const range = Math.max(max - min, 0.5);
  const yTicks = [min, min + range * 0.5, max];
  const xLabelL = slots[0] ? `${String(slots[0].hour).padStart(2, "0")}:${String(slots[0].slot30 || 0).padStart(2, "0")}` : "";
  const xLabelR = slots[slots.length - 1]
    ? `${String(slots[slots.length - 1].hour).padStart(2, "0")}:${String(slots[slots.length - 1].slot30 || 0).padStart(2, "0")}`
    : "";

  const xSpan = w - padL - padR;
  const ySpan = h - padT - padB;
  const pts = temps.map((t, i) => {
    const x = padL + (i / Math.max(temps.length - 1, 1)) * xSpan;
    const y = h - padB - ((t - min) / range) * ySpan;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  const dots = temps.map((t, i) => {
    const x = padL + (i / Math.max(temps.length - 1, 1)) * xSpan;
    const y = h - padB - ((t - min) / range) * ySpan;
    return `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="2.5" fill="rgba(80,213,255,.95)"><title>${t.toFixed(1)}°C</title></circle>`;
  }).join("");

  const yGrid = yTicks.map(v => {
    const y = h - padB - ((v - min) / range) * ySpan;
    return `
      <line x1="${padL}" y1="${y.toFixed(1)}" x2="${w - padR}" y2="${y.toFixed(1)}" stroke="rgba(255,255,255,.12)" />
      <text x="${padL - 6}" y="${(y + 4).toFixed(1)}" text-anchor="end" fill="rgba(255,255,255,.72)" font-size="11">${intTemp(v)}°</text>
    `;
  }).join("");

  return `
    <svg class="temp-chart" viewBox="0 0 ${w} ${h}" preserveAspectRatio="xMidYMid meet">
      <rect x="0" y="0" width="${w}" height="${h}" fill="transparent" />
      ${yGrid}
      <line x1="${padL}" y1="${h - padB}" x2="${w - padR}" y2="${h - padB}" stroke="rgba(255,255,255,.22)" />
      <polyline points="${pts}" fill="none" stroke="rgba(80,213,255,.9)" stroke-width="2.4" />
      ${dots}
      <text x="${padL}" y="${h - 6}" fill="rgba(255,255,255,.6)" font-size="11">${xLabelL}</text>
      <text x="${w - padR}" y="${h - 6}" text-anchor="end" fill="rgba(255,255,255,.6)" font-size="11">${xLabelR}</text>
      <text x="${padL}" y="${padT + 2}" fill="rgba(255,255,255,.86)" font-size="12">max ${intTemp(max)}°</text>
    </svg>
  `;
}

function bracketChart(city) {
  const rows = ((city.market && city.market.brackets) || [])
    .slice()
    .map(r => {
      const vol = Number(r.volume || 0);
      const ask = Number(r.ask || 0);
      const weight = vol > 0 ? vol : ask * 1000; // fallback visual quando volume não vem no snapshot
      return { ...r, _weight: weight };
    })
    .sort((a, b) => Number(a.temp_lo ?? 0) - Number(b.temp_lo ?? 0))
    .slice(0, 12);
  if (!rows.length) return `<div class="empty">Sem brackets para esta cidade.</div>`;
  const rmax = Number(city.running_max);
  const wuFc = Number(city.wu_forecast);
  const hasRmax = Number.isFinite(rmax);
  const hasWu = Number.isFinite(wuFc);
  const maxVol = Math.max(...rows.map(r => Number(r._weight || 0)), 1);
  return `<div class="bracket-chart">${rows.map(r => {
    const width = Math.max(3, Math.round((Number(r._weight || 0) / maxVol) * 100));
    const lo = Number(r.temp_lo);
    const hi = Number(r.temp_hi);
    const inRmax = hasRmax && Number.isFinite(lo) && Number.isFinite(hi) && rmax >= lo && rmax < hi;
    const inWu = hasWu && Number.isFinite(lo) && Number.isFinite(hi) && wuFc >= lo && wuFc < hi;
    const rowClass = `${inRmax ? " current-max" : ""}${inWu ? " wu-forecast" : ""}`;
    return `
      <div class="br-row${rowClass}">
        <div class="br-label">${esc(r.label || "—")}</div>
        <div class="br-bar"><div style="width:${width}%"></div></div>
        <div class="br-ask">${r.ask == null ? "—" : `${Math.round(Number(r.ask) * 100)}¢`}</div>
        <div class="br-vol">${r.volume ? Math.round(Number(r.volume)).toLocaleString("en-US") : "0"}</div>
      </div>
    `;
  }).join("")}</div>`;
}

function renderDetail(data) {
  const holder = document.getElementById("city-detail");
  const cities = data.cities || [];
  let city = cities.find(c => c.name === state.selectedCity);
  if (!city && cities.length) {
    city = activeWatchRows(cities)[0] || cities[0];
    state.selectedCity = city ? city.name : null;
  }
  if (!city) {
    holder.innerHTML = `<div class="empty">Sem cidade selecionada.</div>`;
    document.getElementById("selected-city").textContent = "Nenhuma";
    return;
  }
  document.getElementById("selected-city").textContent = city.label || city.name;

  const target = city.target_bracket || {};
  const pos = city.position || (city.positions_all && city.positions_all[0]) || null;
  const sourceSlots = chartSlotsForCity(city);
  const sourceSet = new Set(sourceSlots.map(s => String(s.source || "")).filter(Boolean));
  let sourceLabel = "—";
  if (sourceSet.size === 1) sourceLabel = [...sourceSet][0];
  if (sourceSet.size > 1) sourceLabel = [...sourceSet].join(" + ");
  if (sourceSlots.length && sourceSlots.every(s => isWuSource(s.source))) {
    sourceLabel = "WU station endpoint";
  }
  const pRaw = Number(city.p_ensemble || 0);
  const pPct = Math.max(0, Math.min(100, Math.round(pRaw * 100)));
  holder.innerHTML = `
    <div class="detail-layout">
      <div class="detail-left">
        <article class="detail-card">
          <h3>${esc(city.flag || "🌍")} ${esc(city.label || city.name)} · ${esc(city.local_hm || "--:--")}</h3>
          <div class="detail-grid">
            <div class="detail-item"><span>Status</span><strong>${esc(city.status || "—")}</strong></div>
            <div class="detail-item"><span>P(pico)</span><strong>${fmtPct(city.p_ensemble || 0)}</strong></div>
            <div class="detail-item"><span>Fonte</span><strong>${esc(sourceLabel)}</strong></div>
            <div class="detail-item"><span>Timezone</span><strong>${esc(city.timezone || "—")}</strong></div>
            <div class="detail-item"><span>Temp atual</span><strong>${fmtTemp(city.temp)}</strong></div>
            <div class="detail-item"><span>RMax</span><strong>${fmtTemp(city.running_max)}</strong></div>
            <div class="detail-item"><span>Target bracket</span><strong>${target.label ? esc(target.label) : "—"}</strong></div>
            <div class="detail-item"><span>Target ask</span><strong>${target.ask == null ? "—" : `${Math.round(Number(target.ask) * 100)}¢`}</strong></div>
            <div class="detail-item"><span>Posição</span><strong>${pos ? "ABERTA" : "SEM POSIÇÃO"}</strong></div>
            <div class="detail-item"><span>PnL dia</span><strong class="${Number(city.daily_pnl || 0) >= 0 ? "money-pos" : "money-neg"}">${fmtMoney(city.daily_pnl || 0)}</strong></div>
          </div>
        </article>
      </div>
      <div class="detail-right">
        <article class="detail-card">
          <h3>Temperatura (slots do dia)</h3>
          <div class="prob-hero">
            <div class="prob-hero-top">
              <span>P(pico)</span>
              <strong>${pPct}%</strong>
            </div>
            <div class="prob-hero-bar"><div style="width:${pPct}%"></div></div>
          </div>
          <div class="chart-wrap">${tempChart(city)}</div>
        </article>
        <article class="detail-card">
          <h3>Brackets e Volume (Top 12)</h3>
          <div class="chart-wrap">${bracketChart(city)}</div>
        </article>
      </div>
    </div>
  `;
}

async function refresh() {
  const badge = document.getElementById("connection");
  try {
    const response = await fetch("/api/snapshot", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    badge.textContent = "ONLINE";
    badge.className = "pill ok";
    renderMetrics(data);
    renderWatchlist(data);
    renderPositions(data);
    renderDetail(data);
  } catch (error) {
    badge.textContent = "OFFLINE";
    badge.className = "pill bad";
  }
}

refresh();
state.timer = setInterval(refresh, 5000);
