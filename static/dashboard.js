const state = { lastSeen: null, timer: null };

const fmtMoney = (value) => {
  const n = Number(value || 0);
  return `${n >= 0 ? "+" : ""}${n.toFixed(2)}$`;
};

const fmtCapital = (value) => `$${Number(value || 0).toLocaleString("en-US", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})}`;
const fmtTemp = (value) => value === null || value === undefined ? "—" : `${Number(value).toFixed(1)}°`;
const fmtPct = (value) => `${Math.round(Number(value || 0) * 100)}%`;
const fmtPrice = (value) => value === null || value === undefined ? "" : ` · ${Math.round(Number(value) * 100)}¢`;
const esc = (value) => String(value ?? "").replace(/[&<>"']/g, ch => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
}[ch]));

function marketFavorite(city) {
  const brackets = (city.market && city.market.brackets) || [];
  return [...brackets].sort((a, b) => (b.ask || 0) - (a.ask || 0))[0] || {};
}

function isMarketResolved(city) {
  if (city.bought) return false;
  const fav = marketFavorite(city);
  const favAsk = fav.ask ?? fav.price;
  return favAsk !== null && favAsk !== undefined && Number(favAsk) >= 0.95;
}

function wuLabel(city) {
  if (!city.has_wu) return "WU n/a";
  return city.wu_forecast == null ? "WU —" : `WU ${Math.round(city.wu_forecast)}°`;
}

function omLabel(city) {
  return city.om_forecast == null ? "OM —" : `OM ${Math.round(city.om_forecast)}°`;
}

function statusClass(city) {
  const s = String(city.status || "").toLowerCase();
  if (city.stop_loss_hit || s.includes("stop")) return "stop";
  if (city.bought || s.includes("comprado")) return "bought";
  if (isMarketResolved(city)) return "resolved";
  if ((city.p_ensemble || 0) >= (city.threshold || 0.65) || s.includes("signal")) return "signal";
  if (s.includes("monitor")) return "monitoring";
  if (s.includes("aguarda") || s.includes("fora") || s.includes("sem snapshot")) return "idle";
  return "";
}

function cityGroup(city) {
  const cls = statusClass(city);
  if (cls === "stop" || cls === "bought") return "bought";
  if (cls === "signal" || cls === "monitoring") return "monitoring";
  return "idle";
}

function idleSortRank(city) {
  const cls = statusClass(city);
  if (cls === "resolved") return 1;
  return 0;
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
  const capitalStart = Number(summary.initial_capital ?? summary.bankroll ?? 0);
  const capitalNow = Number(summary.current_capital ?? (capitalStart + Number(summary.daily_pnl || 0)));
  document.getElementById("m-cities").textContent = summary.n_cities ?? "--";
  document.getElementById("m-signals").textContent = summary.n_signal ?? "--";
  document.getElementById("m-positions").textContent = summary.n_bought ?? "--";
  document.getElementById("m-capital-start").textContent = capitalStart ? fmtCapital(capitalStart) : "--";
  document.getElementById("m-capital-now").textContent = capitalNow ? fmtCapital(capitalNow) : "--";
  document.getElementById("m-capital-now").className = capitalNow >= capitalStart ? "money-pos" : "money-neg";
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
  const favorite = marketFavorite(city);
  const favoriteAsk = favorite.ask ?? favorite.price;
  const forecastState = city.forecast_agree === true ? "concordam" : city.forecast_agree === false ? "divergem" : "sem consenso";
  const statusText = cls === "resolved" ? "✅ RESOLVIDO" : (city.status || "Monitor");

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
        <div class="status ${cls}">${esc(statusText)}</div>
      </div>

      <div class="trade-readings overview">
        <div class="reading primary"><span>Agora</span><strong>${fmtTemp(city.temp)}</strong></div>
        <div class="reading"><span>WU</span><strong>${city.has_wu ? (city.wu_forecast == null ? "—" : `${Math.round(city.wu_forecast)}°`) : "n/a"}</strong></div>
        <div class="reading"><span>Open-Meteo</span><strong>${city.om_forecast == null ? "—" : `${Math.round(city.om_forecast)}°`}</strong></div>
        <div class="reading forecast-state"><span>Forecast</span><strong>${esc(forecastState)}</strong></div>
      </div>

      ${sparkline(city.slots)}

      <div class="prob-row">
        <span>P(pico)</span>
        <div class="bar"><div class="bar-fill ${fillClass}" style="width:${Math.min(100, p * 100)}%"></div></div>
        <strong>${fmtPct(p)}</strong>
      </div>

      <div class="market-box">
        <div>
          <span>Bracket do bot</span>
          <strong>${target.label ? esc(target.label) : "—"}${fmtPrice(ask)}</strong>
        </div>
        <div>
          <span>Favorito mercado</span>
          <strong class="market-favorite">${favorite.label ? esc(favorite.label) : "—"}${fmtPrice(favoriteAsk)}</strong>
        </div>
        <div>
          <span>Volume</span>
          <strong>${market.volume ? `$${Math.round(market.volume).toLocaleString("en-US")}` : "—"}</strong>
        </div>
      </div>
    </article>
  `;
}

function renderCities(data) {
  const grouped = { idle: [], monitoring: [], bought: [] };
  for (const city of data.cities || []) {
    grouped[cityGroup(city)].push(city);
  }
  grouped.monitoring.sort((a, b) =>
    ((b.p_ensemble || 0) - (b.threshold || 0.65)) - ((a.p_ensemble || 0) - (a.threshold || 0.65))
  );
  grouped.bought.sort((a, b) => (b.daily_pnl || 0) - (a.daily_pnl || 0));
  grouped.idle.sort((a, b) => idleSortRank(a) - idleSortRank(b) || String(a.label).localeCompare(String(b.label)));

  for (const key of ["idle", "monitoring", "bought"]) {
    const lane = document.getElementById(`lane-${key}`);
    const count = document.getElementById(`count-${key}`);
    count.textContent = grouped[key].length;
    lane.innerHTML = grouped[key].length
      ? grouped[key].map(city => cityCard(city, data.generated_at)).join("")
      : `<div class="empty lane-empty">Sem cidades neste estado.</div>`;
  }
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
    .filter(c => c.market && c.market.brackets && c.market.brackets.length && !isMarketResolved(c))
    .sort((a, b) => (b.market.volume || 0) - (a.market.volume || 0))
    .slice(0, 10);
  if (!rows.length) {
    holder.innerHTML = `<div class="empty">Ainda sem dados de mercado.</div>`;
    return;
  }
  holder.innerHTML = rows.map(city => {
    const best = marketFavorite(city);
    const pRaw = Number(city.p_ensemble || 0);
    const p = fmtPct(pRaw);
    const fc = `${wuLabel(city)} · ${omLabel(city)}`;
    return `
      <div class="market-row">
        <div class="row-top">
          <span>${esc(city.flag)} ${esc(city.label)}</span>
          <span class="market-favorite">${best.ask === null || best.ask === undefined ? "—" : `${Math.round(best.ask * 100)}¢`}</span>
        </div>
        <div class="market-local-time">${esc(city.local_hm || "--:--")} · ${esc(city.timezone || "")}</div>
        <div class="row-sub">
          <span>${esc(best.label || "—")}</span>
          <span>${city.market.volume ? `$${Math.round(city.market.volume).toLocaleString("en-US")}` : "sem vol"}</span>
        </div>
        <div class="row-sub">
          <span>${esc(fc)}</span>
          <span></span>
        </div>
        <div class="mini-prob">
          <span>P(pico)</span>
          <div class="mini-bar"><div style="width:${Math.min(100, pRaw * 100)}%"></div></div>
          <strong>${p}</strong>
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
