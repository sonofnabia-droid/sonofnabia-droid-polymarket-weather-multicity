#!/usr/bin/env python3
"""Read fleet.json and launch PAPER A-D in isolated tmux sessions."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
CONFIG = Path(__file__).with_name("fleet.json")
PAPER_IDS = {"A", "B", "C", "D"}
CITY_RE = re.compile(r"^[a-z][a-z0-9_]*$")
POLICIES = {
    "A": ([], ["V6_MAKER", "V6_MAKER_PRICE", "V6_MAKER_TTL_MIN"], False),
    "B": (["V6_FILTER=1", "V6_MIN_PWIN=0.85", "V6_NO_POLLING=1"],
          ["V6_MAKER", "V6_MAKER_PRICE", "V6_MAKER_TTL_MIN"], True),
    "C": (["V6_FILTER=1", "V6_MIN_PWIN=0.85", "V6_NO_POLLING=1"],
          ["V6_MAKER", "D4_MAKER", "V6_V5_MAX_ASK", "V6_F1_MIN_ASK"], False),
    "D": (["V6_FILTER=1", "V6_MIN_PWIN=0.82", "V6_NO_POLLING=1",
           "V6_V5_MAX_ASK=0.75", "V6_F1_MIN_ASK=0.80"],
          ["D4_MAKER", "V6_MAKER", "V6_MAKER_PRICE", "V6_MAKER_TTL_MIN"], False),
}


def read_config() -> dict:
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    if cfg.get("schema_version") != 1:
        raise ValueError("schema_version de fleet.json não suportado")
    return cfg


def resolve_cities(bot: dict, city_sets: dict) -> list[str]:
    ref = bot.get("city_set")
    cities = city_sets.get(ref) if isinstance(ref, str) else bot.get("cities")
    if not isinstance(cities, list) or not cities:
        raise ValueError(f"{bot.get('id')}: city_set/cities vazio ou inválido")
    if len(set(cities)) != len(cities) or any(not CITY_RE.fullmatch(c) for c in cities):
        raise ValueError(f"{bot.get('id')}: slugs de cidade duplicados ou inválidos")
    return cities


def command_for(bot: dict, cities: list[str]) -> str:
    bot_id = bot["id"]
    log_dir = bot["log_dir"]
    env, unset, load_env2 = POLICIES[bot_id]
    parts = ["set -a", ". ./.env"]
    if load_env2:
        parts.append("[ ! -f .env2 ] || . ./.env2")
    parts.extend(["set +a", "unset POLY_PRIVATE_KEY POLY_FUNDER ALCHEMY_POLYGON " + " ".join(unset)])
    parts.extend(f"export {value}" for value in env)
    parts.append(f"export CASS_LOG_DIR={shlex.quote(log_dir)}")
    args = ["./venv/bin/python", "-u", "cassiopeia_live_bot.py", "--cities",
            ",".join(cities), "--mode", "cassiopeia", "--run", "paper"]
    if bot_id == "C":
        args.extend(["--max-buy-ask", "0.90", "--no-dashboard"])
    elif bot_id == "D":
        args.extend(["--min-buy-ask", "0.60", "--max-buy-ask", "0.90", "--no-dashboard"])
    if bot_id == "A":
        parts.append("export CASS_BOT=A")
    parts.append("exec " + shlex.join(args) + f" >> {shlex.quote(log_dir + '/bot_live.log')} 2>&1")
    return "; ".join(parts)


def main() -> int:
    cfg = read_config()
    city_sets = cfg.get("city_sets", {})
    bots = cfg.get("bots", [])
    if {b.get("id") for b in bots} != {"A", "B", "C", "D", "E"}:
        raise ValueError("fleet.json deve registar exatamente A/B/C/D/E")

    e = next(b for b in bots if b["id"] == "E")
    if e.get("enabled") or e.get("launchable") is not False or e.get("mode") != "real":
        raise ValueError("E/REAL é informativo e tem de permanecer desativado/não lançável")

    selected = [b for b in bots if b.get("id") in PAPER_IDS and b.get("enabled")]
    if not selected:
        print("Nenhum bot PAPER enabled=true; nada iniciado.")
        return 0
    if any(b.get("mode") != "paper" for b in selected):
        raise ValueError("O launcher só aceita A-D em modo paper")
    if not (ROOT / ".env").is_file() or not (ROOT / "venv/bin/python").is_file():
        raise FileNotFoundError("São necessários .env local e venv/bin/python")
    if shutil.which("tmux") is None:
        raise FileNotFoundError("tmux não está instalado")

    prepared = []
    for bot in selected:
        cities = resolve_cities(bot, city_sets)
        for city in cities:
            required = [
                ROOT / "historic" / f"{city}.csv",
                ROOT / "cities" / city / f"{city}_peak_model/lgbm_peak.pkl",
                ROOT / "cities" / city / "cassiopeia_rebound_model/lgbm_rebound.pkl",
                ROOT / "cities" / city / "v5_quantile_model/quantiles.pkl",
                ROOT / "cities" / city / "v5_quantile_model/atom_classifier.pkl",
                ROOT / "cities" / city / "v5_quantile_model/f1_report.json",
            ]
            missing = [str(p.relative_to(ROOT)) for p in required if not p.is_file()]
            if missing:
                raise FileNotFoundError(f"{bot['id']}/{city}: artefactos em falta: {', '.join(missing)}")
        session = bot["session"]
        probe = subprocess.run(["tmux", "has-session", "-t", f"={session}"],
                               cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if probe.returncode == 0:
            raise RuntimeError(f"A sessão {session} já existe; nenhum processo foi tocado")
        prepared.append((bot, cities))

    for bot, cities in prepared:
        log_dir = bot["log_dir"]
        (ROOT / log_dir).mkdir(parents=True, exist_ok=True)
        command = command_for(bot, cities)
        subprocess.run(["tmux", "new-session", "-d", "-s", bot["session"],
                        "-c", str(ROOT), command], cwd=ROOT, check=True)
        print(f"PAPER {bot['id']} iniciado: {len(cities)} cidades, sessão {bot['session']}")
    print("E/REAL e collectors não foram iniciados por este comando.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        raise SystemExit(2)
