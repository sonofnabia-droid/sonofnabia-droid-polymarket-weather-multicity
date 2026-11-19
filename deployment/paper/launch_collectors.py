#!/usr/bin/env python3
"""Launch explicitly enabled data collectors; never starts bots or downloads history."""
from __future__ import annotations

import json
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
CONFIG = Path(__file__).with_name("fleet.json")


def main() -> int:
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    collectors = cfg.get("collectors", {})
    enabled = [(key, value) for key, value in collectors.items() if value.get("enabled")]
    if not enabled:
        print("Todos os collectors estão disabled; nada iniciado.")
        return 0
    if not (ROOT / "venv/bin/python").is_file() or shutil.which("tmux") is None:
        raise RuntimeError("É necessário venv/bin/python e tmux")

    city_sets = cfg.get("city_sets", {})
    prepared = []
    for key, section in enabled:
        cities = city_sets.get(section.get("city_set"))
        if not cities or len(set(cities)) != len(cities):
            raise ValueError(f"{key}: city_set inválido ou duplicado")
        session = section["session"]
        probe = subprocess.run(["tmux", "has-session", "-t", f"={session}"],
                               cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if probe.returncode == 0:
            raise RuntimeError(f"A sessão {session} já existe; nada foi interrompido")

        log_dir = ROOT / f"live_bot_logs_{session}"
        if key == "pm_books":
            subprocess.run([str(ROOT / "venv/bin/python"),
                            "deployment/paper/pm_books_collector.py", "--check"],
                           cwd=ROOT, check=True)
            command = "exec ./venv/bin/python -u deployment/paper/pm_books_collector.py"
        elif key == "ask_csv":
            if not (ROOT / ".env").is_file():
                raise FileNotFoundError(".env local é necessário para o collector PAPER")
            if section.get("output") != "ask_collector_data.csv":
                raise ValueError("ask_collector.py grava ask_collector_data.csv; output JSON divergiu")
            command = "set -a; . ./.env; set +a; unset POLY_PRIVATE_KEY POLY_FUNDER ALCHEMY_POLYGON; exec "
            command += shlex.join(["./venv/bin/python", "-u", "ask_collector.py",
                                   "--cities", ",".join(cities),
                                   "--interval", str(int(section["interval_seconds"]))])
        else:
            raise ValueError(f"Collector desconhecido: {key}")
        command += f" >> {shlex.quote(str(log_dir / 'collector.log'))} 2>&1"
        prepared.append((section, command, log_dir))

    for section, command, log_dir in prepared:
        log_dir.mkdir(parents=True, exist_ok=True)
        subprocess.run(["tmux", "new-session", "-d", "-s", section["session"],
                        "-c", str(ROOT), command], cwd=ROOT, check=True)
        print(f"Collector {section['session']} iniciado em sessão isolada.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        raise SystemExit(2)
