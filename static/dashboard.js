const state = { lastSeen: null, timer: null };

const fmtMoney = (value) => {
  const n = Number(value || 0);
  return `${n >= 0 ? "+" : ""}${n.toFixed(2)}$`;
};

const fmtTemp = (value) => value === null || value === undefined ? "—" : `${Number(value).toFixed(1)}°`;
const fmtPct = (value) => `${Math.round(Number(value || 0) * 100)}%`;
const esc = (value) => String(value ?? "").replace(/[&<>"']/g, ch => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
}[ch]));

function statusClass(city) {
  const s = String(city.status || "").toLowerCase();
  if (city.stop_loss_hit || s.includes("stop")) return "stop";
  if (city.bought || s.includes("comprado")) return "bought";
  if ((city.p_ensemble || 0) >= (city.threshold || 0.65) || s.includes("signal")) return "signal";
  return "";
}

function ageLabel(iso) {
  if (!iso) return "sem dados";
  const seconds = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m`;
  return `${Math.floor(minutes / 60)}h${String(minutes % 60).padStart(2, "0")}m`;
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
  return `
    <svg class="spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" aria-hidden="true">
      <polyline points="${pts}" fill="none" stroke="rgba(80,213,255,.85)" stroke-width="2.2" />
      <line x1="0" y1="${h - pad}" x2="${w}" y2="${h - pad}" stroke="rgba(255,255,255,.08)" />
    </svg>
  `;
}

function renderMetrics(data) {
  const summary = data.summary || {};
  document.getElementById("m-cities").textContent = summary.n_cities ?? "--";
  document.getElementById("m-signals").textContent = summary.n_signal ?? "--";
  document.getElementById("m-positions").textContent = summary.n_bought ?? "--";
  document.getElementById("m-pnl").textContent = fmtMoney(summary.daily_pnl);
  document.getElementById("m-pnl").className = Number(summary.daily_pnl || 0) >= 0 ? "money-pos" : "money-neg";
  document.getElementById("m-trades").textContent = summary.daily_trades ?? "--";
  document.getElementById("m-updated").textContent = ageLabel(data.generated_at);

  const mode = document.getElementById("mode");
  mode.textContent = data.trading_mode || "UNKNOWN";
  mode.className = `pill ${String(data.trading_mode || "").toLowerCase()}`;

  document.getElementById("source").textContent =
    data.source === "live_snapshot" ? `live snapshot · ${ageLabel(data.generated_at)} atrás` : "fallback logs";
}

function cityCard(city, generatedAt) {
  const cls = statusClass(city);
  const stale = generatedAt && (Date.now() - new Date(generatedAt).getTime()) > 120000 ? " stale" : "";
  const p = Number(city.p_ensemble || 0);
  const thr = Number(city.threshold || 0.65);
  const fillClass = p >= thr ? "buy" : p >= thr * 0.85 ? "hot" : "";
  const target = city.target_bracket || {};
  const ask = target.ask ?? target.price;
  const market = city.market || {};
  const fc = [
    city.wu_forecast !== null && city.wu_forecast !== undefined ? `WU ${city.wu_forecast}°` : null,
    city.om_forecast !== null && city.om_forecast !== undefined ? `OM ${city.om_forecast}°` : null,
  ].filter(Boolean).join(" · ") || "sem forecast";

  return `
    <article class="city-card ${cls}${stale}">
      <div class="city-head">
        <div class="city-name">
          <div class="flag">${esc(city.flag || "🌍")}</div>
          <div>
            <strong>${esc(city.label || city.name)}</strong>
            <span>${esc(city.local_hm || "--:--")} · ${esc(city.timezone || "")}</span>
          </div>
        </div>
        <div class="status ${cls}">${esc(city.status || "Monitor")}</div>
      </div>

      <div class="temps">
        <div class="reading"><span>Temp</span><strong>${fmtTemp(city.temp)}</strong></div>
        <div class="reading"><span>RMax</span><strong>${fmtTemp(city.running_max)}</strong></div>
        <div class="reading"><span>Hum</span><strong>${city.humidity == null ? "—" : `${Math.round(city.humidity)}%`}</strong></div>
      </div>

      ${sparkline(city.slots)}

      <div class="prob-row">
        <span>P(pico)</span>
        <div class="bar"><div class="bar-fill ${fillClass}" style="width:${Math.min(100, p * 100)}%"></div></div>
        <strong>${fmtPct(p)}</strong>
      </div>
      <div class="prob-row">
        <span>Risk</span>
        <div class="bar"><div class="bar-fill risk" style="width:${Math.min(100, ((city.daily_loss || 0) / Math.max(city.max_daily_loss || 1, 1)) * 100)}%"></div></div>
        <strong>${Math.round(city.daily_loss || 0)}$</strong>
      </div>

      <div class="forecast">
        <span>${esc(fc)}</span>
        <span>${city.forecast_agree === true ? "concordam" : city.forecast_agree === false ? "divergem" : ""}</span>
      </div>
      <div class="market-mini">
        <span class="target">${target.label ? esc(target.label) : "sem target"}${ask ? ` · ${Math.round(ask * 100)}¢` : ""}</span>
        <span>${market.volume ? `$${Math.round(market.volume).toLocaleString("en-US")} vol` : "sem mercado"}</span>
      </div>
    </article>
  `;
}

function renderCities(data) {
  const grid = document.getElementById("city-grid");
  const cities = [...(data.cities || [])].sort((a, b) => {
    const ca = statusClass(a), cb = statusClass(b);
    const rank = { signal: 0, bought: 1, stop: 2, "": 3 };
    return (rank[ca] ?? 9) - (rank[cb] ?? 9) || (b.p_ensemble || 0) - (a.p_ensemble || 0);
  });
  grid.innerHTML = cities.map(city => cityCard(city, data.generated_at)).join("");
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
  const rows = collectPositions(data.cities);
  document.getElementById("position-count").textContent = rows.length;
  if (!rows.length) {
    holder.innerHTML = `<div class="empty">Sem posições abertas ou registadas.</div>`;
    return;
  }
  holder.innerHTML = rows.slice(0, 12).map(({ city, pos }) => {
    const pnl = pos.pnl_usd ?? 0;
    const entry = pos.entry_ask ?? pos.ask;
    const bracket = pos.bracket_label ?? pos.bracket ?? "Bracket";
    return `
      <div class="position-row">
        <div class="row-top">
          <span>${esc(city.flag)} ${esc(city.label)}</span>
          <span class="${Number(pnl) >= 0 ? "money-pos" : "money-neg"}">${pos.pnl_usd == null ? "—" : fmtMoney(pnl)}</span>
        </div>
        <div class="row-sub">
          <span>${esc(bracket)}</span>
          <span>${entry ? `${Math.round(entry * 100)}¢` : "—"} · ${esc(pos.status || pos.mode || "")}</span>
        </div>
      </div>
    `;
  }).join("");
}

function renderMarkets(data) {
  const holder = document.getElementById("markets");
  const rows = (data.cities || [])
    .filter(c => c.market && c.market.brackets && c.market.brackets.length)
    .sort((a, b) => (b.market.volume || 0) - (a.market.volume || 0))
    .slice(0, 10);
  if (!rows.length) {
    holder.innerHTML = `<div class="empty">Ainda sem dados de mercado.</div>`;
    return;
  }
  holder.innerHTML = rows.map(city => {
    const best = [...city.market.brackets].sort((a, b) => (b.ask || 0) - (a.ask || 0))[0] || {};
    return `
      <div class="market-row">
        <div class="row-top">
          <span>${esc(city.flag)} ${esc(city.label)}</span>
          <span class="accent">${best.ask ? `${Math.round(best.ask * 100)}¢` : "—"}</span>
        </div>
        <div class="row-sub">
          <span>${esc(best.label || "—")}</span>
          <span>${city.market.volume ? `$${Math.round(city.market.volume).toLocaleString("en-US")}` : "sem vol"}</span>
        </div>
      </div>
    `;
  }).join("");
}

async function refresh() {
  const badge = document.getElementById("connection");
  try {
    const response = await fetch("/api/snapshot", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    state.lastSeen = Date.now();
    badge.textContent = "ONLINE";
    badge.className = "pill ok";
    renderMetrics(data);
    renderCities(data);
    renderPositions(data);
    renderMarkets(data);
  } catch (error) {
    badge.textContent = "OFFLINE";
    badge.className = "pill bad";
  }
}

refresh();
state.timer = setInterval(refresh, 5000);
