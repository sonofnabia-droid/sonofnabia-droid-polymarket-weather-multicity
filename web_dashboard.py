"""
web_dashboard.py
================
Dashboard Flask read-only para o live bot multi-cidade.

Corre como processo independente. A app só lê ficheiros em live_bot_logs; não
importa nem controla o live_bot, por isso uma falha na web app não pára o bot.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, date
from functools import wraps
from pathlib import Path
from zoneinfo import ZoneInfo

from flask import Flask, abort, jsonify, render_template, request

from cities.config import CITIES


LOG_DIR = Path("live_bot_logs")
SNAPSHOT_PATH = LOG_DIR / "live_snapshot.json"
RECONCILED_PATH = LOG_DIR / "reconciled_summary.json"
API_KEY = os.environ.get("DASHBOARD_API_KEY", "").strip()

FLAGS = {
    "munich": "🇩🇪", "dallas": "🇺🇸", "ankara": "🇹🇷",
    "singapore": "🇸🇬", "jakarta": "🇮🇩", "kuala_lumpur": "🇲🇾",
    "lagos": "🇳🇬", "taipei": "🇹🇼", "miami": "🇺🇸",
    "karachi": "🇵🇰", "moscow": "🇷🇺", "warsaw": "🇵🇱",
    "beijing": "🇨🇳", "chicago": "🇺🇸", "madrid": "🇪🇸",
    "tel_aviv": "🇮🇱", "phoenix": "🇺🇸", "las_vegas": "🇺🇸",
    "buenos_aires": "🇦🇷",
}

PRETTY = {
    "las_vegas": "Las Vegas",
    "kuala_lumpur": "Kuala Lumpur",
    "buenos_aires": "Buenos Aires",
    "tel_aviv": "Tel Aviv",
}


def label(city_name: str) -> str:
    return PRETTY.get(city_name, city_name.replace("_", " ").title())


def safe_read_json(path: Path, default):
    try:
        if not path.exists():
            return default
        return json.loads(path.read_text())
    except Exception:
        return default


def today_for_city(city_name: str) -> date:
    cfg = CITIES[city_name]
    return datetime.now(tz=ZoneInfo(cfg.timezone)).date()


def read_daily_stats(city_name: str) -> dict:
    path = LOG_DIR / f"{city_name}_{today_for_city(city_name)}.json"
    return safe_read_json(path, {})


def read_positions() -> list[dict]:
    paper = safe_read_json(LOG_DIR / "paper_positions.json", [])
    real = safe_read_json(LOG_DIR / "real_positions.json", [])
    for p in paper:
        p.setdefault("mode", "paper")
    for p in real:
        p.setdefault("mode", "real")
    return list(paper) + list(real)


def fallback_snapshot() -> dict:
    """Snapshot mínimo quando o live_bot ainda não escreveu live_snapshot.json."""
    now = datetime.now(tz=ZoneInfo("Europe/Lisbon"))
    positions = read_positions()
    cities = []
    for name, cfg in CITIES.items():
        stats = read_daily_stats(name)
        local_now = datetime.now(tz=ZoneInfo(cfg.timezone))
        city_positions = [
            p for p in positions
            if name in str(p.get("market_slug", "")) or name in str(p.get("bracket_label", "")).lower()
        ]
        daily_pnl = stats.get("daily_pnl", 0.0)
        trades = stats.get("trades", [])
        cities.append({
            "name": name,
            "label": label(name),
            "flag": FLAGS.get(name, "🌍"),
            "timezone": cfg.timezone,
            "local_time": local_now.isoformat(),
            "local_hm": local_now.strftime("%H:%M"),
            "day_start": cfg.day_start,
            "day_end": cfg.day_end,
            "has_wu": bool(cfg.wu_history_path),
            "threshold": cfg.threshold if cfg.threshold is not None else 0.65,
            "hour_min": cfg.hour_min if cfg.hour_min is not None else 14,
            "status": "Sem snapshot live",
            "temp": None,
            "running_max": None,
            "p_ensemble": 0.0,
            "p_lgbm": None,
            "slots": [],
            "wu_forecast": None,
            "om_forecast": None,
            "forecast_agree": None,
            "market": {"title": None, "volume": None, "n_outcomes": None, "brackets": []},
            "target_bracket": None,
            "bought": any(p.get("status") == "open" for p in city_positions),
            "position": city_positions[-1] if city_positions else None,
            "positions_all": city_positions,
            "daily_pnl": daily_pnl,
            "n_trades": len(trades),
            "daily_loss": stats.get("total_invested", 0.0),
            "max_daily_loss": cfg.max_daily_loss,
            "bankroll": getattr(cfg, "max_per_trade", 5.0) * 100,
            "humidity": None,
            "cloud_cover": None,
            "stop_loss_hit": stats.get("total_invested", 0.0) >= cfg.max_daily_loss,
        })

    initial_capital = 1000.0
    bankroll = sum(c["bankroll"] for c in cities)
    daily_pnl_total = sum(c["daily_pnl"] for c in cities)
    return {
        "generated_at": now.isoformat(),
        "trading_mode": "UNKNOWN",
        "session": {"total_trades": sum(c["n_trades"] for c in cities), "total_pnl": 0.0},
        "summary": {
            "n_cities": len(cities),
            "n_bought": sum(1 for c in cities if c["bought"]),
            "n_signal": 0,
            "n_stop": sum(1 for c in cities if c["stop_loss_hit"]),
            "daily_pnl": daily_pnl_total,
            "daily_trades": sum(c["n_trades"] for c in cities),
            "bankroll": bankroll,
            "initial_capital": initial_capital,
            "current_capital": initial_capital + daily_pnl_total,
        },
        "cities": cities,
        "source": "fallback",
    }


def require_auth(view_func):
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if API_KEY and request.headers.get("X-API-Key") != API_KEY:
            abort(401)
        return view_func(*args, **kwargs)

    return wrapper


def get_snapshot() -> dict:
    snapshot = safe_read_json(SNAPSHOT_PATH, None)
    if not snapshot:
        snapshot = fallback_snapshot()
    reconciled = safe_read_json(RECONCILED_PATH, None)
    if isinstance(reconciled, dict):
        snapshot["reconciled"] = reconciled
        snapshot["reconciled_today"] = datetime.now(tz=ZoneInfo("Europe/Lisbon")).date().isoformat()
    for city in snapshot.get("cities", []):
        cfg = CITIES.get(city.get("name"))
        if not cfg:
            continue
        city.setdefault("has_wu", bool(cfg.wu_history_path))
        city.setdefault("label", label(cfg.name))
        city.setdefault("flag", FLAGS.get(cfg.name, "🌍"))
    summary = snapshot.setdefault("summary", {})
    trading_mode = str(snapshot.get("trading_mode", "")).upper()
    default_initial = 1000.0 if trading_mode == "PAPER" else summary.get("bankroll", 0.0)
    initial_capital = summary.get("initial_capital", default_initial)
    if trading_mode == "PAPER" and float(initial_capital or 0.0) != 1000.0:
        initial_capital = 1000.0
    daily_pnl = summary.get("daily_pnl", 0.0)
    summary["initial_capital"] = initial_capital
    summary["current_capital"] = float(initial_capital or 0.0) + float(daily_pnl or 0.0)
    snapshot["source"] = snapshot.get("source", "live_snapshot")
    return snapshot


app = Flask(__name__)
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0


@app.after_request
def add_no_cache_headers(response):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@app.get("/")
@require_auth
def index():
    try:
        return render_template("dashboard.html")
    except Exception:
        return "<h1>Dashboard HTML template missing. API available at /api/snapshot</h1>", 200


@app.get("/api/snapshot")
@require_auth
def api_snapshot():
    return jsonify(get_snapshot())


@app.get("/health")
@require_auth
def health():
    snapshot = get_snapshot()
    return jsonify({
        "ok": True,
        "source": snapshot.get("source"),
        "generated_at": snapshot.get("generated_at"),
    })


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5050, debug=False)
