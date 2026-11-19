#!/usr/bin/env python3
"""opportunity_logger.py — captura as oportunidades bloqueadas pela banda (D4).

Cada "CITY BUY BLOQUEADO" nos logs dos bots é um disparo do modelo que a
banda D-V1 recusou. São exatamente os eventos que decidem a questão
maker/volume na D-v4: quantos por semana, a que preços o livro estava.

Corre por cron (hora a hora): faz TAIL dos logs vivos desde a última
corrida (offsets persistentes) e acrescenta JSONL em
live_bot_logs/opportunity_logger.jsonl.

⚠️ Resolução temporal: o ts gravado é o da CAPTURA (cron), não do evento —
os logs vivos não têm timestamp por linha. Precisão ±1h, suficiente para
agregados semanais. (A versão estruturada, com p/rmax/bracket, entra no
restart da D-v4 via _log_opportunity no live bot.)
"""
import json
import re
from datetime import datetime, timezone
from pathlib import Path

BOTS = {
    "A": Path("live_bot_logs/bot_live.log"),
    "B": Path("live_bot_logs_v6/bot_live.log"),
    "C": Path("live_bot_logs_calipso/bot_live.log"),
}
OUT = Path("live_bot_logs/opportunity_logger.jsonl")
STATE = Path("live_bot_logs/opportunity_offsets.json")

RE_BLOCK = re.compile(
    r"([A-Z_]+) BUY BLOQUEADO: ask (?:fresco )?(\d+(?:\.\d+)?)¢ ([<>]) "
    r"(?:mínimo|máx) (\d+)¢")


def tail_new_lines(path: Path, offset: int):
    """Devolve (novas_linhas, novo_offset). Se o ficheiro encolheu (rotação
    copy-truncate), recomeça do zero."""
    if not path.exists():
        return [], offset
    size = path.stat().st_size
    if size < offset:
        offset = 0
    with open(path, "r", errors="replace") as f:
        f.seek(offset)
        lines = f.readlines()
        new_offset = f.tell()
    return lines, new_offset


def main():
    offsets = json.loads(STATE.read_text()) if STATE.exists() else {}
    n_new = 0
    with open(OUT, "a") as out:
        for bot, path in BOTS.items():
            off = int(offsets.get(bot, 0))
            lines, off = tail_new_lines(path, off)
            offsets[bot] = off
            for line in lines:
                m = RE_BLOCK.search(line)
                if not m:
                    continue
                city, ask, direction, limit = m.groups()
                row = {
                    "captured_at": datetime.now(timezone.utc).isoformat(),
                    "bot": bot,
                    "city": city.lower(),
                    "ask": float(ask) / 100.0,
                    "gate": "max" if direction == ">" else "min",
                    "band_limit": float(limit) / 100.0,
                }
                out.write(json.dumps(row) + "\n")
                n_new += 1
    STATE.write_text(json.dumps(offsets))
    print(f"[opportunity_logger] {n_new} novos eventos "
          f"({sum(1 for _ in open(OUT)) if OUT.exists() else 0} totais)")


if __name__ == "__main__":
    main()
